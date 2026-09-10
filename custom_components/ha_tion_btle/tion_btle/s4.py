from __future__ import annotations

import binascii
import logging

from bleak.backends.device import BLEDevice

if __package__ == "":
    from tion_btle.tion import TionException
    from tion_btle.light_family import TionLiteFamily
else:
    from .tion import TionException
    from .light_family import TionLiteFamily

_LOGGER = logging.getLogger(__name__)


class TionS4(TionLiteFamily):
    FRAME_RANDOM = 0xAD
    BLE_REQUEST_ID = 1
    MIN_STATE_RESPONSE_SIZE = 31
    TURBO_RESPONSE_SIZE = 4
    STATE_RESPONSE_PARAMS = [0x31, 0x32]
    TURBO_SET_PARAMS = [0x30, 0x41]
    TURBO_RESPONSE_PARAMS = [0x31, 0x41]
    TURBO_REQUEST_PARAMS = [0x32, 0x41]
    ERROR_CODES = tuple(f"EC{code:02d}" for code in range(1, 12))
    WARNING_CODES = tuple(f"WS{code:02d}" for code in range(1, 7))
    HEATER_POWER_BY_TYPE = {0: 0, 1: 1000, 2: 1400}

    def __init__(self, mac: str | BLEDevice):
        super().__init__(mac)

        self.modes = ['outside', 'recirculation']
        self._request_id = 0
        self._filter_change_required = False
        self._heater_power_rating: int | None = 0
        self._magicair_connected = False
        self._magicair_auto = False
        self._timer_active = False
        self._comm_source = "auto"
        self._pcb_control_temp = 0
        self._pcb_power_temp = 0
        self._work_time = 0
        self._fan_time = 0
        self._airflow_counter = 0
        self._airflow_total = 0.0
        self._max_fan_speed = 6
        self._heater_output = 0
        self._boost_active = False
        self._boost_time_left = 0
        self._boost_error_code = 0

        if mac == "dummy":
            _LOGGER.info("Dummy mode!")
            self._package_id: int = 0

    @property
    def REQUEST_DEVICE_INFO(self) -> list:
        return [50, 51]  # 0x32 0x33

    @property
    def SET_PARAMS(self) -> list:
        return [48, 50]  # 0x30 0x32

    @property
    def SAVE_PARAMS(self) -> list:
        return [52, 50]  # 0x34 0x32

    @property
    def REQUEST_PARAMS(self) -> list:
        return [50, 50]  # 0x32 0x32

    def _decode_response(self, response: bytearray):
        _LOGGER.debug("Data is %s", bytes(response).hex())
        if len(response) < self.MIN_STATE_RESPONSE_SIZE:
            raise TionException(
                "s4 _decode_response",
                f"Got invalid Tion 4S response: expected at least {self.MIN_STATE_RESPONSE_SIZE} bytes, "
                f"got {len(response)}",
            )

        try:
            self._mode = response[2]
            self._heater_temp = response[3]
            self._fan_speed = response[4]
            self._in_temp = self.decode_temperature(response[5])
            self._out_temp = self.decode_temperature(response[6])
            self._pcb_control_temp = self.decode_temperature(response[7])
            self._pcb_power_temp = self.decode_temperature(response[8])
            self._work_time = int.from_bytes(response[9:13], byteorder='little', signed=False)
            self._fan_time = int.from_bytes(response[13:17], byteorder='little', signed=False)
            filter_time = int.from_bytes(response[17:21], byteorder='little', signed=False)
            self._filter_remain = filter_time / 86400
            self._airflow_counter = int.from_bytes(response[21:25], byteorder='little', signed=False)
            self._airflow_total = self._airflow_counter * 15 / 3600
            self._state = response[0] & 1
            self._sound = response[0] >> 1 & 1
            self._light = response[0] >> 2 & 1
            self._heater = True if response[0] >> 4 & 1 == 0 else False
            self._comm_source = "user" if response[0] >> 5 & 1 else "auto"
            self._filter_change_required = bool(response[0] >> 6 & 1)
            heater_type = ((response[0] >> 7) & 1) | ((response[1] & 0b11) << 1)
            self._heater_power_rating = self.HEATER_POWER_BY_TYPE.get(heater_type)
            self._magicair_connected = bool(response[1] >> 2 & 1)
            self._magicair_auto = bool(response[1] >> 3 & 1)
            self._timer_active = bool(response[1] >> 4 & 1)
            self._error_code = int.from_bytes(response[25:29], byteorder='little', signed=False)
            self._max_fan_speed = response[29]
            self._heater_output = response[30]
            # The raw byte-0 bit 3 is not a reliable indication of active heat
            # on 4S devices. The protocol exposes actual heater output in byte
            # 30; the reference controller likewise treats a non-zero
            # heater_var as active heating.
            self._actual_heating = self._heater_output > 0
        except IndexError as e:
            raise TionException(
                "s4 _decode_response",
                f"Got bad response from Tion '{response}': {str(e)} while parsing"
            )

    def _generate_model_specific_json(self) -> dict:
        return {
            "light": self.light,
            "active_error_codes": self.active_error_codes,
            "device_problem": bool(self.active_error_codes),
            "heater_active": bool(self._actual_heating),
            "filter_change_required": self._filter_change_required,
            "heater_power_rating": self._heater_power_rating,
            "magicair_connected": self._magicair_connected,
            "magicair_auto": self._magicair_auto,
            "timer_active": self._timer_active,
            "comm_source": self._comm_source,
            "pcb_control_temp": self._pcb_control_temp,
            "pcb_power_temp": self._pcb_power_temp,
            "work_time": self._work_time,
            "fan_time": self._fan_time,
            "airflow_counter": self._airflow_counter,
            "airflow_total": self._airflow_total,
            "max_fan_speed": self._max_fan_speed,
            "heater_output": self._heater_output,
            "boost_active": self._boost_active,
            "boost_time_left": self._boost_time_left,
            "boost_error_code": self._boost_error_code,
        }

    @property
    def active_error_codes(self) -> list[str]:
        """Return active 4S errors and warnings encoded in the state bit mask."""
        codes = [name for bit, name in enumerate(self.ERROR_CODES) if self._error_code & (1 << bit)]
        codes.extend(
            name for bit, name in enumerate(self.WARNING_CODES, start=24) if self._error_code & (1 << bit)
        )
        return codes

    def _validate_state_before_write(self, requested_changes: dict | None = None) -> None:
        """Leave command safety and error recovery to the breezer firmware.

        In particular, EC01-EC03 describe valve-position faults. Recovering from
        one can require another power transition, so blocking every write while
        an EC bit is present creates an integration-side deadlock. The error
        mask remains exposed through active_error_codes/device_problem, and the
        device may still reject commands it considers unsafe.
        """

    def _next_request_id(self) -> int:
        self._request_id = (self._request_id + 1) & 0xFFFFFFFF
        if self._request_id == 0:
            self._request_id = 1
        return self._request_id

    def _build_frame(self, packet_id: int, frame_type: list[int], data: bytes = b"") -> bytearray:
        """Build a Tion 4S LT frame with protocol constants and CRC16-CCITT."""
        frame = bytearray([packet_id, 0x00, 0x00, self.MAGIC_NUMBER, self.FRAME_RANDOM])
        frame.extend(frame_type)
        frame.extend(self.BLE_REQUEST_ID.to_bytes(4, byteorder='little'))
        frame.extend(data)

        frame_size = len(frame) - 1 + 2  # Packet id is outside the LT frame; CRC is inside it.
        frame[1:3] = frame_size.to_bytes(2, byteorder='little')
        crc = binascii.crc_hqx(frame[1:], 0xFFFF)
        frame.extend(crc.to_bytes(2, byteorder='big'))
        return frame

    def _expected_state_response_type(self) -> bytes:
        return bytes(self.STATE_RESPONSE_PARAMS)

    def _decode_turbo_response(self, response: bytearray, *, reject_error: bool = False) -> None:
        """Decode the firmware-managed 4S Turbo status payload."""
        if len(response) != self.TURBO_RESPONSE_SIZE:
            raise TionException(
                "s4 _decode_turbo_response",
                f"Got invalid Tion 4S Turbo response: expected {self.TURBO_RESPONSE_SIZE} bytes, "
                f"got {len(response)}",
            )

        self._boost_active = bool(response[0])
        self._boost_time_left = (
            int.from_bytes(response[1:3], byteorder="little", signed=False)
            if self._boost_active
            else 0
        )
        self._boost_error_code = response[3]
        if self._boost_error_code and reject_error:
            raise TionException(
                "s4 _decode_turbo_response",
                f"Tion 4S rejected the Turbo command with error code {self._boost_error_code}",
            )
        if self._boost_error_code:
            _LOGGER.warning(
                "Tion 4S Turbo status reports error code %s",
                self._boost_error_code,
            )

    async def _update_additional_state_from_breezer(self) -> None:
        """Read native Turbo status, which is separate from the regular state."""
        self._prepare_response()
        await self._try_write(request=self.command_getTurboStatus)
        response = await self._get_data_from_breezer(self.TURBO_RESPONSE_PARAMS)
        self._decode_turbo_response(response)

    def _encode_turbo_request(self, duration_seconds: int) -> bytearray:
        if not 0 <= duration_seconds <= 0xFFFF:
            raise TionException(
                "s4 _encode_turbo_request",
                f"Tion 4S Turbo duration must be between 0 and 65535 seconds, got {duration_seconds}",
            )

        data = bytearray(self._next_request_id().to_bytes(4, byteorder="little"))
        data.extend(duration_seconds.to_bytes(2, byteorder="little"))
        data.append(0)
        return self._build_frame(self.SINGLE_PACKET_ID, self.TURBO_SET_PARAMS, data)

    async def set_boost(self, duration_seconds: int) -> None:
        """Start or cancel the native, firmware-managed Turbo timer."""
        duration_seconds = int(duration_seconds)
        try:
            await self.connect()

            if duration_seconds > 0:
                # Refresh regular state before starting Turbo. Device errors
                # remain visible but do not create an integration-side command
                # deadlock; the firmware decides whether Turbo is acceptable.
                self._prepare_response()
                await self._try_write(request=self.command_getStatus)
                state = await self._get_data_from_breezer(self.STATE_RESPONSE_PARAMS)
                self._decode_response(state)
                self._validate_state_before_write()

            self._prepare_response()
            await self._send_request(self._encode_turbo_request(duration_seconds))
            turbo = await self._get_data_from_breezer(self.TURBO_RESPONSE_PARAMS)
            self._decode_turbo_response(turbo, reject_error=True)

            # Turbo has a separate response and does not carry the resulting
            # power, speed, gate, or heater state. Refresh those fields before
            # publishing the coordinator update.
            self._prepare_response()
            await self._try_write(request=self.command_getStatus)
            state = await self._get_data_from_breezer(self.STATE_RESPONSE_PARAMS)
            self._decode_response(state)
        except Exception:
            await self.reset_connection()
            raise

    def _encode_request(self, request: dict) -> bytearray:
        def encode_state() -> int:
            """Encode different device states to single status int"""
            #   power   sound   light   heater  true    resetSettings   resetErrorCounter   resetFilterResource
            #   0       1       2       3       4       5               6                   7
            return self._encode_state(request["state"]) | \
                (self._encode_state(request["sound"]) << 1) | \
                (self._encode_state(request["light"]) << 2) | \
                ((not self._encode_state(request["heater"])) << 3) | \
                (True << 4) | \
                (bool(request.get("reset_errors")) << 6) | \
                (bool(request.get("reset_filter")) << 7)
        if request["mode"] not in self.modes:
            raise TionException("s4 _encode_request", f"Unsupported Tion 4S mode: {request['mode']!r}")

        fan_speed = int(request["fan_speed"]) or 1
        if not 1 <= fan_speed <= 6:
            raise TionException("s4 _encode_request", f"Unsupported Tion 4S fan speed: {fan_speed}")

        data = bytearray(self._next_request_id().to_bytes(4, byteorder='little'))
        data.extend([
            encode_state(),
            0x00,
            self._encode_mode(request["mode"]),
            int(request["heater_temp"]),
            fan_speed,
        ])
        data.extend((0).to_bytes(2, byteorder='little'))
        frame_type = self.SAVE_PARAMS if request.get("_save_state") else self.SET_PARAMS
        return self._build_frame(self.FIRST_PACKET_ID, frame_type, data)

    @property
    def _packages(self) -> list:
        return [
            #                                       |           |                                               |
            bytearray([0x00, 0x2f, 0x00, 0x3a, 0x27, 0x31, 0x32, 0x72, 0x7b, 0x64, 0xd7, 0x31, 0xea, 0x58, 0x3a, 0x2f, 0x51, 0x00, 0x19, 0x04]),
            bytearray([0x40, 0x0e, 0x10, 0x1b, 0x26, 0x3b, 0x6e, 0x07, 0x00, 0xfa, 0x4e, 0x07, 0x00, 0x06, 0xff, 0xe5, 0x00, 0xa6, 0xe9, 0x22]),
            bytearray([0xc0, 0x00, 0x00, 0x00, 0x00, 0x00, 0x06, 0x00, 0x98, 0x5d])
        ]

    @property
    def command_getStatus(self) -> bytearray:
        return self._build_frame(TionLiteFamily.SINGLE_PACKET_ID, self.REQUEST_PARAMS)

    @property
    def command_getTurboStatus(self) -> bytearray:
        return self._build_frame(TionLiteFamily.SINGLE_PACKET_ID, self.TURBO_REQUEST_PARAMS)
