from __future__ import annotations

import abc
import asyncio
import inspect
import logging
from asyncio import Semaphore
from typing import Callable, List, final
from time import localtime, strftime

from bleak import exc
from bleak.backends.device import BLEDevice
from bleak_retry_connector import BleakClientWithServiceCache, establish_connection

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

    def handleNotification(self, handle: object, data: bytearray):
        # Do not retain a backend-owned mutable buffer. Some Bleak backends
        # reuse notification storage after the callback returns.
        packet = bytearray(data)
        self._data.append(packet)
        _LOGGER.debug(f"Got data in {handle} response {bytes(packet).hex()}")
        _LOGGER.debug(f"{self._data=}")

    @property
    def data(self) -> bytearray:
        return self._data.pop(0)

    @property
    def haveNewData(self) -> bool:
        return len(self._data) > 0


class TionException(Exception):
    def __init__(self, expression, message):
        super().__init__(message)
        self.expression = expression
        self.message = message


class Tion:
    statuses = ['off', 'on']
    modes = ['recirculation', 'mixed']  # 'recirculation', 'mixed' and 'outside', as Index exception
    uuid_notify: str = ""
    uuid_write: str = ""

    def __init__(self, mac: str | BLEDevice):
        self._mac = mac
        self._ble_device: BLEDevice | str = mac
        self._btle: BleakClientWithServiceCache | None = None
        self._next_btle_device: BLEDevice | str | None = None
        self._active_ble_device: BLEDevice | None = None
        self._ble_device_callback: Callable[[], BLEDevice | None] | None = None
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
        self._actual_heating: bool | None = None
        self._sound: bool = False
        self._filter_remain: float = 0.0
        self._error_code: int = 0
        self.__failed_connects: int = 0
        self.__notifications_enabled: bool = False
        self.__notification_client: BleakClientWithServiceCache | None = None
        self.__notification_generation = 0
        self.have_breezer_state: bool = False
        self._semaphore = Semaphore(1)

    def set_ble_device_callback(self, callback: Callable[[], BLEDevice | None]) -> None:
        """Set a callback that resolves the current HA connection candidate."""
        self._ble_device_callback = callback

    def _resolve_ble_device(self) -> BLEDevice | None:
        """Return the freshest connectable device known to Home Assistant."""
        if self._ble_device_callback is not None:
            device = self._ble_device_callback()
            if device is not None:
                self._ble_device = device
                self._next_btle_device = device

        candidate = self._next_btle_device if self._next_btle_device is not None else self._ble_device
        return candidate if isinstance(candidate, BLEDevice) else None

    def _reset_message_assembly(self) -> None:
        """Reset model-specific response assembly state."""

    def _prepare_response(self) -> None:
        """Discard stale notifications and partial frames before a new request."""
        while self._delegation.haveNewData:
            stale = self._delegation.data
            _LOGGER.debug("Discarding stale notification before request: %s", bytes(stale).hex())
        self._reset_message_assembly()
        self.have_breezer_state = False

    def _expected_state_response_type(self) -> bytes | None:
        """Return the model-specific frame type used for state responses."""
        return None

    def _response_frame_type(self) -> bytes | None:
        """Return the frame type of the most recently assembled response."""
        return None

    def _invalidate_notifications(
        self,
        client: BleakClientWithServiceCache | None = None,
    ) -> None:
        """Invalidate callbacks belonging to the current notification session."""
        if client is not None and self.__notification_client is not client:
            return
        self.__notifications_enabled = False
        self.__notification_client = None
        self.__notification_generation += 1

    def _notifications_are_ready(self) -> bool:
        """Return whether the connected client owns the active subscription."""
        client = self._btle
        return bool(
            client is not None
            and client.is_connected
            and self.__notifications_enabled
            and self.__notification_client is client
        )

    async def _update_additional_state_from_breezer(self) -> None:
        """Read model-specific state that is not included in the main response."""

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
        """Return actual heater activity when reported, otherwise estimate it."""
        if self._actual_heating is not None:
            return self._decode_state(self._actual_heating)

        if self.heater == "off":
            return "off"

        if self.heater_temp - self.in_temp > 3 and self.out_temp > self.in_temp:
            return "on"

        return "off"

    @final
    async def get_state_from_breezer(self) -> None:
        """
        Get current state from breezer
        :return: None
        """
        try:
            await self.connect()
            self._prepare_response()
            await self._try_write(request=self.command_getStatus)
            response = await self._get_data_from_breezer(self._expected_state_response_type())
            self._decode_response(response)
            await self._update_additional_state_from_breezer()
        except Exception:
            await self.reset_connection()
            raise

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
        for p in ['fan_speed', 'heater_temp', 'heater', 'sound', 'light', 'mode', 'state']:
            try:
                setattr(self, p, request[p])
            except KeyError:
                pass

    @final
    async def set(self, new_settings=None) -> None:
        """
        Set new breezer state
        :param new_settings: json with new state
        :return: None
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
            # A cached error mask must never permanently block writes. Always
            # confirm the current device state with a newly assembled response.
            self._prepare_response()
            await self._try_write(request=self.command_getStatus)
            raw = await self._get_data_from_breezer(self._expected_state_response_type())
            self._decode_response(raw)
            current_settings = self.__generate_common_json()
            current_settings.update(self._generate_model_specific_json())

            merged_settings = {**current_settings, **new_settings}
            merged_settings["_save_state"] = bool({"sound", "light"} & new_settings.keys())
            self._validate_state_before_write(new_settings)

            encoded_request = self._encode_request(merged_settings)
            _LOGGER.debug("Will write %s", encoded_request)
            self._prepare_response()
            await self._send_request(encoded_request)
            raw = await self._get_data_from_breezer(self._expected_state_response_type())
            self._decode_response(raw)
            self._validate_state_before_write(new_settings)
            await self._update_additional_state_from_breezer()
        except Exception:
            await self.reset_connection()
            raise

    async def set_boost(self, duration_seconds: int) -> None:
        """Set a firmware-managed boost duration when supported by the model."""
        raise TionException("set_boost", f"Native boost is not supported by {self.model}")

    def _validate_state_before_write(self, requested_changes: dict | None = None) -> None:
        """Reject a write when a model reports a state that makes it unsafe."""

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
        status = "connected" if (self._btle is not None and self._btle.is_connected) else "disc"
        return status

    @final
    async def _try_connect(self) -> bool:
        """Connect once through bleak-retry-connector's bounded retry loop."""
        device = self._resolve_ble_device()
        if device is None:
            device = self._ble_device

        def _on_disconnect(client: BleakClientWithServiceCache) -> None:
            is_current = self._btle is client
            _LOGGER.debug(
                "BLE disconnected callback: address=%s client_id=%s current_client_id=%s is_current=%s",
                self.mac,
                id(client),
                id(self._btle) if self._btle is not None else None,
                is_current,
            )
            if is_current:
                self.have_breezer_state = False
                self._invalidate_notifications(client)
                self._btle = None
                self._active_ble_device = None

        if isinstance(device, BLEDevice):
            self._active_ble_device = device
            try:
                client = await establish_connection(
                    BleakClientWithServiceCache,
                    device,
                    device.name or self.mac,
                    disconnected_callback=_on_disconnect,
                    use_services_cache=True,
                    max_attempts=3,
                    ble_device_callback=self._resolve_ble_device,
                )
            except Exception:
                _LOGGER.debug(
                    "BLE connection failed: address=%s path=%s",
                    device.address,
                    device.details.get("path") if isinstance(device.details, dict) else None,
                    exc_info=True,
                )
                raise
            self._btle = client
        else:
            # fallback for plain MAC string (no HA integration)
            self._btle = BleakClientWithServiceCache(device, disconnected_callback=_on_disconnect)
            await self._btle.connect()

        self._next_btle_device = None
        _LOGGER.debug(
            "BLE connection established: address=%s client_id=%s path=%s",
            self.mac,
            id(self._btle),
            self._active_ble_device.details.get("path")
            if self._active_ble_device is not None and isinstance(self._active_ble_device.details, dict)
            else None,
        )
        return self._btle.is_connected

    @final
    async def _connect(self, need_notifications: bool = True):
        _LOGGER.debug(f"Connecting. {self.connection_status=}.")
        try:
            if self.connection_status == "disc":
                await self._try_connect()
            if need_notifications:
                await self._enable_notifications()
            else:
                _LOGGER.debug("Notifications was not requested")
        except Exception:
            # Connector, subscription, and protocol failures all require the
            # same clean reconnect path.
            await self.reset_connection()
            raise
        _LOGGER.debug(f"_connect done. {self.connection_status=}.")

    @final
    async def _disconnect(self):
        client = self._btle
        device = self._active_ble_device
        _LOGGER.debug(
            "Disconnecting: address=%s status=%s client_id=%s client_connected=%s path=%s",
            self.mac,
            self.connection_status,
            id(client) if client is not None else None,
            client.is_connected if client is not None else None,
            device.details.get("path") if device is not None and isinstance(device.details, dict) else None,
        )
        notification_client = self.__notification_client
        notifications_enabled = (
            self.__notifications_enabled and notification_client is client
        )
        self._invalidate_notifications(client)
        if client is not None and notifications_enabled and client.is_connected:
            try:
                await client.stop_notify(self.uuid_notify)
            except Exception as err:
                _LOGGER.debug(
                    "Could not stop notifications while disconnecting from %s: %s",
                    self.mac,
                    err,
                )
        try:
            if client is not None:
                # Always call disconnect when a client object exists.  A BLE
                # peripheral may have already dropped the link, making
                # is_connected false while the backend still owns transport
                # resources that only disconnect() closes.
                await client.disconnect()
        except Exception as err:
            _LOGGER.warning("Error while disconnecting from %s: %s", self.mac, err)
        finally:
            # Keep the client installed until disconnect() has had a chance to
            # invoke its callback.  Clearing it before the await made every
            # expected callback look stale and hid the real BlueZ state.
            if self._btle is client:
                self._btle = None
            if self._active_ble_device is device:
                self._active_ble_device = None

        _LOGGER.debug(
            "Disconnect complete: address=%s status=%s client_id=%s",
            self.mac,
            self.connection_status,
            id(client) if client is not None else None,
        )

    @final
    async def _try_write(self, request: bytearray):
        """Write once; replaying a partially delivered multi-packet command is unsafe."""
        _LOGGER.debug(f"Writing {bytes(request).hex()} to {self.uuid_write}, {self.connection_status=}")
        if self._btle is None or not self._btle.is_connected:
            raise exc.BleakError(f"Tion breezer {self.mac} is not connected")
        return await self._btle.write_gatt_char(
            self.uuid_write,
            request,
            False
        )

    @final
    async def _enable_notifications(self):
        _LOGGER.debug(f"Enabling notification. {self.connection_status=}")
        client = self._btle
        if client is None or not client.is_connected:
            raise exc.BleakError(f"Tion breezer {self.mac} is not connected")

        if self._notifications_are_ready():
            _LOGGER.debug("Reusing active notification subscription for %s", self.mac)
            return

        self._invalidate_notifications()
        generation = self.__notification_generation

        def _handle_notification(handle: object, data: bytearray) -> None:
            if (
                self._btle is not client
                or self.__notification_client is not client
                or not self.__notifications_enabled
                or self.__notification_generation != generation
            ):
                _LOGGER.debug(
                    "Ignoring notification from stale BLE session: address=%s client_id=%s "
                    "current_client_id=%s generation=%s current_generation=%s",
                    self.mac,
                    id(client),
                    id(self._btle) if self._btle is not None else None,
                    generation,
                    self.__notification_generation,
                )
                return
            self._delegation.handleNotification(handle, data)

        self.__notification_client = client
        self.__notifications_enabled = True
        try:
            await client.start_notify(self.uuid_notify, _handle_notification)
        except Exception as err:
            self._invalidate_notifications(client)
            _LOGGER.warning("Got exception %s while enabling notifications!", err)
            raise

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
            if self._btle is None:
                raise TionException("pair", "BLE client is not connected")
            await self._btle.pair()
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
        """Ensure the persistent BLE connection is ready."""
        if self._notifications_are_ready():
            _LOGGER.debug("Reusing persistent BLE connection to %s", self.mac)
            return

        async with self._semaphore:
            # Another waiter may have established the connection while this
            # task waited for the semaphore.
            if self._notifications_are_ready():
                return
            self.have_breezer_state = False
            await self._connect()

    @final
    async def disconnect(self):
        """Explicitly close the persistent BLE connection."""
        await self._disconnect()
        self.have_breezer_state = False
        while self._delegation.haveNewData:
            _LOGGER.debug(f"Cleaning data in disconnect: {self._delegation.data=}")
        self._reset_message_assembly()

    @final
    async def reset_connection(self):
        """Force a clean connection state after failures or entry unload."""
        await self._disconnect()
        self.have_breezer_state = False
        while self._delegation.haveNewData:
            _LOGGER.debug(f"Cleaning data in reset_connection: {self._delegation.data=}")
        self._reset_message_assembly()

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
    async def _get_data_from_breezer(
        self,
        expected_frame_type: bytes | bytearray | list[int] | tuple[int, ...] | None = None,
    ) -> bytearray:
        """Get one complete response, optionally matching a protocol frame type.

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
                    actual_frame_type = self._response_frame_type()
                    if (
                        expected_frame_type is not None
                        and actual_frame_type != bytes(expected_frame_type)
                    ):
                        _LOGGER.warning(
                            "Ignoring unexpected Tion response frame type %s while waiting for %s",
                            actual_frame_type.hex() if actual_frame_type is not None else None,
                            bytes(expected_frame_type).hex(),
                        )
                        self._reset_message_assembly()
                        i = 0
                        continue
                    self.have_breezer_state = True
                    break
                i = 0
            else:
                await asyncio.sleep(0.5)
            i += 1
        else:
            _LOGGER.debug("Waiting too long for data")

        if self.have_breezer_state:
            result = bytearray(self._data)
            self._reset_message_assembly()

        else:
            raise TionException("_get_data_from_breezer", "Could not get breezer state")

        return result

    @final
    def update_btle_device(self, new_device: str | BLEDevice):
        if new_device is None:
            _LOGGER.info(f"Skipping update due to {new_device= }!")
            return
        self._ble_device = new_device
        self._next_btle_device = new_device

    @final
    def set_new_btle_device(self):
        """Kept for API compatibility; device updates are handled via update_btle_device."""
        pass
