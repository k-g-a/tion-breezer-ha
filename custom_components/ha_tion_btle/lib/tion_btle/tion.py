from __future__ import annotations

import abc
import asyncio
import inspect
import logging
from asyncio import Semaphore
from typing import Callable, List, final
from time import localtime, strftime

from bleak import BleakClient
from bleak import exc
from bleak.backends.device import BLEDevice
from bleak_retry_connector import (
    establish_connection,
    BleakClientWithServiceCache,
)

_LOGGER = logging.getLogger(__name__)


class MaxTriesExceededError(Exception):
    pass


def retry(retries: int = 2, delay: int = 0):
    def decor(f: Callable):
        async def wrapper(*args, **kwargs):
            last_info_exception = None
            last_warning_exception = None
            for i in range(retries+1):
                try:
                    _LOGGER.debug("Trying %d/%d: %s(args=%s,kwargs=%s)", i, retries, f.__name__, args, kwargs)
                    if inspect.iscoroutinefunction(f):
                        return await f(*args, **kwargs)
                    return f(*args, **kwargs)
                except (exc.BleakError, exc.BleakDBusError) as _e:
                    next_message = "Will try again" if i < retries else "Will not try again"
                    _LOGGER.warning("Got exception: %s. %s", str(_e), next_message)
                    last_warning_exception = _e
                    if delay > 0:
                        await asyncio.sleep(delay)

            _LOGGER.critical("Retry limit (%d) exceeded for %s(%s, %s)", retries, f.__name__, args, kwargs)
            if _LOGGER.level > logging.INFO and last_info_exception is not None:
                _LOGGER.critical(f"Last exception was {last_info_exception}")
            elif _LOGGER.level > logging.WARNING and last_warning_exception is not None:
                _LOGGER.critical(f"Last exception was {last_warning_exception}")

            raise MaxTriesExceededError

        return wrapper
    return decor


class TionDelegation:
    def __init__(self):
        self._data: List[bytearray] = []

    def handleNotification(self, handle: int, data: bytearray):
        self._data.append(data)
        _LOGGER.debug(f"Got data in {handle} response {bytes(data).hex()}")
        _LOGGER.debug(f"{self._data=}")

    @property
    def data(self) -> bytearray:
        return self._data.pop(0)

    @property
    def haveNewData(self) -> bool:
        return len(self._data) > 0


class TionException(Exception):
    def __init__(self, expression, message):
        self.expression = expression
        self.message = message


class Tion:
    statuses = ['off', 'on']
    modes = ['recirculation', 'mixed']  # 'recirculation', 'mixed' and 'outside', as Index exception
    uuid_notify: str = ""
    uuid_write: str = ""

    def __init__(self, mac: str | BLEDevice):
        self._mac = mac
        # --- REFACTORED: no direct BleakClient creation ---
        # Connection is managed via establish_connection() from bleak-retry-connector.
        # _ble_device_callback must be set by the HA integration layer before
        # any connect() call. It returns a fresh BLEDevice from HA Bluetooth API.
        self._client: BleakClientWithServiceCache | None = None
        self._ble_device_callback: Callable[[], BLEDevice | None] | None = None
        # --- END REFACTORED ---
        self._delegation = TionDelegation()
        self._fan_speed = 0
        self._model: str = self.__class__.__name__
        self._data: bytearray = bytearray()
        """Data from breezer response at request state command"""
        # states
        self._in_temp: int = 0
        self._out_temp: int = 0
        self._heater_temp: int = 0
        self._fan_speed: int = 0
        self._mode: int = 0
        self._state: bool = False
        self._heater: bool = False
        self._sound: bool = False
        self._filter_remain: float = 0.0
        self._error_code: int = 0
        self.__failed_connects: int = 0
        self.__connections_count: int = 0
        self.__notifications_enabled: bool = False
        self.have_breezer_state: bool = False
        self._semaphore = Semaphore(1)

    def set_ble_device_callback(self, callback: Callable[[], BLEDevice | None]) -> None:
        """Set the callback that returns a fresh BLEDevice from HA Bluetooth API.

        This must be called by the HA integration (__init__.py) before any
        connect() attempt. The callback is passed to establish_connection()
        as ble_device_callback so it can handle adapter/proxy switching.
        """
        self._ble_device_callback = callback

    @abc.abstractmethod
    async def _send_request(self, request: bytearray):
        """ Send request to device

        Args:
          request : array of bytes to send to device
        Returns:
          array of bytes with device response
        """
        pass

    @abc.abstractmethod
    def _decode_response(self, response: bytearray) -> dict:
        """ Decode response from device

        Args:
          response: array of bytes with data from device, taken from _send_request
        Returns:
          dictionary with device response
        """
        pass

    @abc.abstractmethod
    def _encode_request(self, request: dict) -> bytearray:
        """ Encode dictionary of request to byte array

        Args:
          request: dictionary with request
        Returns:
          Byte array for sending to device
        """
        pass

    @abc.abstractmethod
    def _generate_model_specific_json(self) -> dict:
        """
        Generates dict with model-specific parameters based on class variables
        :return: dict of model specific properties
        """
        raise NotImplementedError()

    def __generate_common_json(self) -> dict:
        """
        Generates dict with common parameters based on class properties
        :return: dict of common properties
        """
        return {
            "state": self.state,
            "heater": self.heater,
            "heating": self.heating,
            "sound": self.sound,
            "mode": self.mode,
            "out_temp": self.out_temp,
            "in_temp": self.in_temp,
            "heater_temp": self._heater_temp,
            "fan_speed": self.fan_speed,
            "filter_remain": self.filter_remain,
            "time": strftime("%H:%M", localtime()),
            "request_error_code": self._error_code,
            "model": self.model,
        }

    @final
    @property
    def heating(self) -> str:
        """Tries to guess is heater working right now."""
        if self.heater == "off":
            return "off"

        if self.heater_temp - self.in_temp > 3 and self.out_temp > self.in_temp:
            return "on"

        return "off"

    @final
    async def get_state_from_breezer(self) -> None:
        """
        Get current state from breezer.
        Uses persistent BLE connection — does NOT disconnect on success.
        Only disconnects on error for clean recovery.
        """
        try:
            await self.connect()
            await self._try_write(request=self.command_getStatus)
            response = await self._get_data_from_breezer()
        except Exception:
            # Error: force cleanup so the BLE slot is released
            await self.reset_connection()
            raise

        self._decode_response(response)

    @final
    async def get(self, skip_update: bool = False) -> dict:
        """
        Report current breezer state
        :param skip_update: may we skip requesting data from breezer or not
        :return:
          dictionary with device state
        """
        if skip_update and self.have_breezer_state:
            _LOGGER.debug(f"Skipping getting state from breezer because skip_update={skip_update} and "
                          f"have_breezer_state={self.have_breezer_state}")
        else:
            await self.get_state_from_breezer()
        common = self.__generate_common_json()
        model_specific_data = self._generate_model_specific_json()

        return {**common, **model_specific_data}

    @final
    def _set_internal_state_from_request(self, request: dict) -> None:
        """
        Set internal parameters based on user request
        :param request: changed breezer parameter from set request
        :return: None
        """
        for p in ['fan_speed', 'heater_temp', 'heater', 'sound', 'mode', 'state']:
            # ToDo: lite have additional parameters to set: "light" and "co2_auto_control", so we should get this
            #  list from class
            try:
                setattr(self, p, request[p])
            except KeyError:
                pass

    @final
    async def set(self, new_settings=None) -> None:
        """
        Set new breezer state.
        Uses persistent BLE connection — does NOT disconnect on success.
        Only disconnects on error for clean recovery.
        """
        if new_settings is None:
            new_settings = {}

        try:
            if new_settings["fan_speed"] == 0:
                del new_settings["fan_speed"]
                new_settings["state"] = "off"
        except KeyError:
            pass

        try:
            await self.connect()
            # Use internal cached state instead of extra BLE read
            current_settings = self.__generate_common_json()
            current_settings.update(self._generate_model_specific_json())

            merged_settings = {**current_settings, **new_settings}

            encoded_request = self._encode_request(merged_settings)
            _LOGGER.debug("Will write %s", encoded_request)
            await self._send_request(encoded_request)
            self._set_internal_state_from_request(new_settings)
            await self._get_data_from_breezer()
        except Exception:
            # Error: force cleanup so the BLE slot is released
            await self.reset_connection()
            raise

    @final
    @property
    def mac(self):
        return self._mac.address if isinstance(self._mac, BLEDevice) else self._mac

    @staticmethod
    def decode_temperature(raw: int) -> int:
        """ Converts temperature from bytes with addition code to int
        Args:
          raw: raw temperature value from Tion
        Returns:
          Integer value for temperature
        """
        barrier = 0b10000000
        return raw if raw < barrier else -(~(raw - barrier) + barrier + 1)

    @final
    def _process_status(self, code: int) -> str:
        try:
            status = self.statuses[code]
        except IndexError:
            status = 'unknown'
        return status

    @final
    @property
    def connection_status(self):
        if self._client is not None:
            status = "connected" if self._client.is_connected else "disc"
        else:
            status = "disc"
        return status

    # ============================================================
    # REFACTORED: Connection management via establish_connection
    # ============================================================

    def _disconnected_callback(self, client: BleakClient) -> None:
        """Called by bleak when the device disconnects (planned or unplanned).
        
        IMPORTANT: Identity check prevents stale callbacks from failed
        establish_connection() attempts from overwriting a successful one.
        Without this check, a callback from attempt N-1 could null out
        self._client that was set by successful attempt N.
        """
        if self._client is not client:
            _LOGGER.debug(
                "Ignoring disconnected callback from stale client "
                "(callback client != current self._client)"
            )
            return
        _LOGGER.debug("Disconnected callback fired for %s", self.mac)
        self._client = None
        self.__notifications_enabled = False
        self.have_breezer_state = False

    async def _ensure_client(self) -> BleakClientWithServiceCache:
        """Return a connected BleakClient, creating one if necessary.

        Uses establish_connection() from bleak-retry-connector which is the
        HA-recommended way to manage BLE connections. It handles:
        - Automatic retries with exponential backoff
        - Bluetooth adapter/proxy switching via ble_device_callback
        - GATT service caching for faster reconnections
        """
        if self._client is not None and self._client.is_connected:
            return self._client

        if self._ble_device_callback is None:
            raise RuntimeError(
                "ble_device_callback not set. Call set_ble_device_callback() "
                "from the HA integration before using connect()."
            )

        device = self._ble_device_callback()
        if device is None:
            raise exc.BleakError(
                f"BLE device {self.mac} not found via HA Bluetooth API. "
                "Device may be out of range or Bluetooth adapter unavailable."
            )

        _LOGGER.debug("Establishing BLE connection to %s via establish_connection()", self.mac)

        self._client = await establish_connection(
            BleakClientWithServiceCache,
            device,
            self.mac,
            disconnected_callback=self._disconnected_callback,
            max_attempts=2,
            ble_device_callback=self._ble_device_callback,
            use_services_cache=True,
        )
        _LOGGER.debug("BLE connection established to %s", self.mac)
        return self._client

    @final
    async def _connect(self, need_notifications: bool = True):
        """Connect to the breezer using HA-managed BLE connection."""
        _LOGGER.debug(f"Connecting. {self.connection_status=}.")
        if self.connection_status == "disc":
            try:
                await self._ensure_client()
            except exc.BleakError as e:
                _LOGGER.warning(f"Got {str(e)=} exception in _connect")
                raise e

            if need_notifications:
                await self._enable_notifications()
            else:
                _LOGGER.debug("Notifications was not requested")
        _LOGGER.debug(f"_connect done. {self.connection_status=}.")

    @final
    async def _disconnect(self):
        """Disconnect from the breezer."""
        _LOGGER.debug(f"Disconnecting. {self.connection_status=}.")
        if self._client is not None and self._client.is_connected:
            try:
                await self._client.disconnect()
            except Exception as e:
                _LOGGER.warning(f"Error during disconnect: {e}")
            self._client = None
            self.__notifications_enabled = False
            # Give BlueZ time to release the connection slot on the adapter.
            # Without this, rapid connect/disconnect cycles can exhaust the
            # single slot on adapters like CSR8510.
            await asyncio.sleep(0.5)
        _LOGGER.debug(f"_disconnect done. {self.connection_status=}")

    # ============================================================
    # END REFACTORED
    # ============================================================

    @final
    @retry(retries=3)
    async def _try_write(self, request: bytearray):
        # SECURITY: Do NOT call _ensure_client() here!
        # _ensure_client() creates BLE connections via establish_connection(),
        # which must ONLY be called from _connect() (under semaphore).
        # If client is disconnected, raise TionException (not caught by @retry)
        # instead of BleakError (which would be retried uselessly).
        if self._client is None or not self._client.is_connected:
            _LOGGER.warning("_try_write called but BLE not connected")
            raise TionException("_try_write", "BLE not connected")
        _LOGGER.debug(f"Writing {bytes(request).hex()} to {self.uuid_write}, {self.connection_status=}")
        return await self._client.write_gatt_char(
            self.uuid_write,
            request,
            False
        )

    @final
    async def _enable_notifications(self):
        _LOGGER.debug(f"Enabling notification. {self.connection_status=}")
        # SECURITY: Use self._client directly, do NOT call _ensure_client().
        # This method is only called from _connect() which already ensured
        # the client exists via _ensure_client().
        if self._client is None or not self._client.is_connected:
            raise TionException("_enable_notifications", "BLE not connected")
        try:
            await self._client.start_notify(self.uuid_notify, self._delegation.handleNotification)
        except exc.BleakError as e:
            _LOGGER.warning("Got exception %s while enabling notifications!" % str(e))
            raise e

        self.__notifications_enabled = True
        _LOGGER.debug(f"_enable_notifications done")
        return

    @final
    @property
    def fan_speed(self):
        return self._fan_speed

    @fan_speed.setter
    def fan_speed(self, new_speed: int):
        if 0 <= new_speed <= 6:
            self._fan_speed = new_speed

        else:
            _LOGGER.warning("Incorrect new fan speed. Will use 1 instead")
            self._fan_speed = 1

        # self.set({"fan_speed": new_speed})

    @final
    def _process_mode(self, mode_code: int) -> str:
        try:
            mode = self.modes[mode_code]
        except IndexError:
            mode = 'outside'
        return mode

    @staticmethod
    def _decode_state(state: bool) -> str:
        return "on" if state else "off"

    @staticmethod
    def _encode_state(state: str) -> bool:
        return state == "on"

    @final
    @property
    def state(self) -> str:
        return self._decode_state(self._state)

    @final
    @state.setter
    def state(self, new_state: str):
        self._state = self._encode_state(new_state)

    @final
    @property
    def heater(self) -> str:
        return self._decode_state(self._heater)

    @final
    @heater.setter
    def heater(self, new_state: str):
        self._heater = self._encode_state(new_state)

    @final
    @property
    def heater_temp(self) -> int:
        return self._heater_temp

    @final
    @heater_temp.setter
    def heater_temp(self, new_temp: int):
        self._heater_temp = new_temp

    @final
    @property
    def target_temp(self) -> int:
        return self.heater_temp

    @final
    @target_temp.setter
    def target_temp(self, new_temp: int):
        self.heater_temp = new_temp

    @final
    @property
    def in_temp(self):
        """Income air temperature"""
        return self._in_temp

    @final
    @property
    def out_temp(self):
        """Outcome air temperature"""
        return self._out_temp

    @final
    @property
    def sound(self) -> str:
        return self._decode_state(self._sound)

    @final
    @sound.setter
    def sound(self, new_state: str):
        self._sound = self._encode_state(new_state)

    @final
    @property
    def filter_remain(self) -> float:
        return self._filter_remain

    @final
    @property
    def mode(self):
        return self._process_mode(self._mode)

    @final
    @mode.setter
    def mode(self, new_state: str):
        self._mode = self._encode_mode(new_state)

    @final
    @property
    def model(self) -> str:
        return self._model.removeprefix("Tion")

    @final
    def _encode_status(self, status: str) -> int:
        """
        Encode string status () to int
        :param status: one of:  "on", "off"
        :return: integer equivalent of state
        """
        return self.statuses.index(status) if status in self.statuses else 0

    @final
    def _encode_mode(self, mode: str) -> int:
        """
        Encode string mode to integer
        :param mode: one of self.modes + any other as outside
        :return: integer equivalent of mode
        """
        return self.modes.index(mode) if mode in self.modes else 2

    @final
    async def pair(self):
        _LOGGER.debug("Pairing")
        await self._connect(need_notifications=False)
        _LOGGER.debug("Connected. BT pairing ...")
        try:
            if self._client is None or not self._client.is_connected:
                raise TionException("pair", "BLE not connected after _connect()")
            await self._client.pair()
            # device-specific pairing
            _LOGGER.debug("Device-specific pairing ...")
            await self._pair()
            _LOGGER.debug("Device pair is done")
        except Exception as e:
            _LOGGER.critical(f"Got exception while pair {type(e).__name__}: {str(e)}")
            raise TionException('pair', f"{type(e).__name__}: {str(e)}")
        finally:
            _LOGGER.debug("disconnected")
            await self._disconnect()

    @abc.abstractmethod
    async def _pair(self):
        """Perform model-specific pair steps"""

    @final
    async def connect(self):
        """Connect to breezer. Keeps connection alive between calls.

        In persistent mode, the BLE connection is maintained across
        operations. Only reconnects if the connection has actually
        dropped (client is None or not connected).
        """
        if self.__connections_count < 0:
            self.__connections_count = 0

        # Detect dead connection: count > 0 but client is gone
        # (e.g. _disconnected_callback fired due to BLE timeout)
        connection_alive = (
            self._client is not None and self._client.is_connected
        )

        if self.__connections_count == 0 or not connection_alive:
            # Reset count — we're doing a fresh connection attempt
            self.__connections_count = 0
            self.have_breezer_state = False
            async with self._semaphore:
                try:
                    await self._connect()
                except Exception:
                    self.__connections_count = 0
                    self.have_breezer_state = False
                    raise

        self.__connections_count = min(self.__connections_count + 1, 100)

    @final
    async def reset_connection(self):
        """Force-disconnect and reset all connection state.

        Used for error recovery: ensures the BLE slot is released
        and the next connect() starts from a clean state.
        """
        _LOGGER.debug("reset_connection: force cleanup")
        self.__connections_count = 0
        try:
            await self._disconnect()
        except Exception as e:
            _LOGGER.warning(f"reset_connection: error during _disconnect: {e}")
        self._client = None
        self.__notifications_enabled = False
        self.have_breezer_state = False

    @final
    async def disconnect(self):
        self.__connections_count = max(0, self.__connections_count - 1)
        if self.__connections_count <= 0:
            await self._disconnect()
            self.have_breezer_state = False
            while self._delegation.haveNewData:
                _LOGGER.debug(f"Cleaning data in disconnect: {self._delegation.data=}")

    @property
    @abc.abstractmethod
    def command_getStatus(self) -> bytearray:
        raise NotImplementedError()

    @abc.abstractmethod
    def _collect_message(self, package: bytearray) -> bool:
        """
        Collects message from several package
        Must set self._data

        :param package: single package from breezer
        :return: Have we full response from breezer or not
        """
        raise NotImplementedError()

    @final
    async def _get_data_from_breezer(self) -> bytearray:
        """ Get byte array with breezer response on state request

        :returns:
          breezer response
        """
        self.have_breezer_state = False

        _LOGGER.debug("Collecting data")

        i = 0
        while i < 10:
            if self._delegation.haveNewData:
                byte_response = self._delegation.data
                if self._collect_message(byte_response):
                    self.have_breezer_state = True
                    break
                i = 0  # partial data, reset counter
            else:
                await asyncio.sleep(0.5)
            i += 1
        else:
            _LOGGER.warning("Waiting too long for data from breezer (timeout 5s)")

        if self.have_breezer_state:
            result = self._data

        else:
            raise TionException("_get_data_from_breezer", "Could not get breezer state")

        return result

    @final
    def update_btle_device(self, new_device: str | BLEDevice):
        """Update the BLE device reference.

        With establish_connection + ble_device_callback, the HA integration
        handles device updates through the callback. This method is kept for
        backward compatibility but the actual device resolution now happens
        in _ble_device_callback provided by the HA layer.
        """
        if new_device is None:
            _LOGGER.info(f"Skipping update due to {new_device= }!")
            return
        # Store for reference but actual connections use _ble_device_callback
        self._mac = new_device
