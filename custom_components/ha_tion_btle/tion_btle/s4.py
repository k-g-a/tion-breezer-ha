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
    ERROR_CODES = tuple(f"EC{code:02d}" for code in range(1, 12))
    WARNING_CODES = tuple(f"WS{code:02d}" for code in range(1, 7))

    def __init__(self, mac: str | BLEDevice):
        super().__init__(mac)

        self.modes = ['outside', 'recirculation']
        self._request_id = 0

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
            self._filter_remain = int.from_bytes(response[17:20], byteorder='little', signed=False) / 86400
            self._state = response[0] & 1
            self._sound = response[0] >> 1 & 1
            self._light = response[0] >> 2 & 1
            self._heater = True if response[0] >> 4 & 1 == 0 else False
            self._error_code = int.from_bytes(response[25:29], byteorder='little', signed=False)
        except IndexError as e:
            raise TionException(
                "s4 _decode_response",
                f"Got bad response from Tion '{response}': {str(e)} while parsing"
            )

    def _generate_model_specific_json(self) -> dict:
        return {
            "light": self.light,
            "active_error_codes": self.active_error_codes,
        }

    @property
    def active_error_codes(self) -> list[str]:
        """Return active 4S errors and warnings encoded in the state bit mask."""
        codes = [name for bit, name in enumerate(self.ERROR_CODES) if self._error_code & (1 << bit)]
        codes.extend(
            name for bit, name in enumerate(self.WARNING_CODES, start=24) if self._error_code & (1 << bit)
        )
        return codes

    def _validate_state_before_write(self) -> None:
        critical_errors = [code for code in self.active_error_codes if code.startswith("EC")]
        if critical_errors:
            raise TionException(
                "s4 set",
                "Refusing to change Tion 4S state while the device reports critical error(s): "
                + ", ".join(critical_errors),
            )

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

    def _encode_request(self, request: dict) -> bytearray:
        def encode_state() -> int:
            """Encode different device states to single status int"""
            #   power   sound   light   heater  true    resetSettings   resetErrorCounter   resetFilterResource
            #   0       1       2       3       4       5               6                   7
            return self._encode_state(request["state"]) | \
                (self._encode_state(request["sound"]) << 1) | \
                (self._encode_state(request["light"]) << 2) | \
                ((not self._encode_state(request["heater"])) << 3) | \
                (True << 4)
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
        return self._build_frame(self.FIRST_PACKET_ID, self.SET_PARAMS, data)

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
