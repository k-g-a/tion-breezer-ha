from __future__ import annotations

import abc
import binascii
import logging
from random import randrange
from typing import final, List

from bleak.backends.device import BLEDevice

if __package__ == "":
    from tion_btle.tion import Tion
else:
    from .tion import Tion

_LOGGER = logging.getLogger(__name__)


class TionLiteFamily(Tion):
    uuid: str = "98f00001-3788-83ea-453e-f52244709ddb"
    uuid_write: str = "98f00002-3788-83ea-453e-f52244709ddb"
    uuid_notify: str = "98f00003-3788-83ea-453e-f52244709ddb"
    uuid_notify_descriptor: str = "00002902-0000-1000-8000-00805f9b34fb"

    write: None
    notify: None

    SINGLE_PACKET_ID = 0x80
    FIRST_PACKET_ID = 0x00
    MIDDLE_PACKET_ID = 0x40
    END_PACKET_ID = 0xc0
    MAGIC_NUMBER: int = 0x3a  # 58

    def __init__(self, mac: str | BLEDevice):
        super().__init__(mac)
        self._data: bytearray = bytearray()
        self._crc: bytearray = bytearray()
        self._header: bytearray = bytearray()
        self._have_full_package: bool = False
        self._got_new_sequence: bool = False
        self._first_fragment: bytearray = bytearray()
        self.have_breezer_state: bool = False

        # states
        self._light: bool = False
        self._have_heater: bool = False

    @final
    @property
    def light(self) -> str:
        return self._decode_state(self._light)

    @final
    @light.setter
    def light(self, new_state: str):
        self._light = self._encode_state(new_state)

    @final
    @property
    def random(self) -> bytes:
        # return random hex number.
        return randrange(0xFF)

    @final
    @property
    def random4(self) -> list:
        # return 4 random hex.
        return [self.random, self.random, self.random, self.random]

    @final
    def _reset_message_assembly(self) -> None:
        """Discard every fragment belonging to an earlier response."""
        self._data = bytearray()
        self._crc = bytearray()
        self._header = bytearray()
        self._have_full_package = False
        self._got_new_sequence = False
        self._first_fragment = bytearray()

    @final
    def _response_frame_type(self) -> bytes | None:
        """Return the two-byte LT frame type from the assembled header."""
        return bytes(self._header[5:7]) if len(self._header) >= 7 else None

    @final
    def _collect_message(self, package: bytearray) -> bool:
        """Collect and validate one complete LT response frame."""
        self._have_full_package = False
        package = bytearray(package)

        if not package:
            _LOGGER.warning("Ignoring empty Tion notification")
            return False

        _LOGGER.debug("Got %s from tion", bytes(package).hex())
        packet_id = package[0]

        if packet_id == self.FIRST_PACKET_ID:
            if self._got_new_sequence:
                if package == self._first_fragment:
                    _LOGGER.debug("Ignoring duplicated first packet")
                    return False
                _LOGGER.warning("Got a new first packet before the previous response completed; discarding it")
            self._reset_message_assembly()
            self._data = package
            self._first_fragment = bytearray(package)
            self._got_new_sequence = True
            return False

        if packet_id == self.SINGLE_PACKET_ID:
            if self._got_new_sequence:
                _LOGGER.warning("Got a single packet while assembling a fragmented response; discarding it")
            self._reset_message_assembly()
            self._data = package
            self._have_full_package = True
        elif packet_id == self.MIDDLE_PACKET_ID:
            if not self._got_new_sequence:
                _LOGGER.warning("Ignoring middle packet without a matching first packet")
                return False
            expected_size = int.from_bytes(self._data[1:3], byteorder="little") + 1
            candidate_size = len(self._data) + len(package) - 1
            if candidate_size >= expected_size:
                # A middle packet cannot complete or exceed a frame. BlueZ
                # may deliver an already-received fragment twice after a
                # peripheral power-cycle; ignore the excess copy and retain
                # the valid sequence for its END packet.
                _LOGGER.debug(
                    "Ignoring duplicated or excess middle packet: assembled=%s candidate=%s expected=%s",
                    len(self._data),
                    candidate_size,
                    expected_size,
                )
                return False
            self._data.extend(package[1:])
            return False
        elif packet_id == self.END_PACKET_ID:
            if not self._got_new_sequence:
                _LOGGER.warning("Ignoring end packet without a matching first packet")
                return False
            self._data.extend(package[1:])
            self._got_new_sequence = False
            self._have_full_package = True
        else:
            _LOGGER.warning("Ignoring notification with unknown packet id %s", hex(packet_id))
            return False

        frame = bytearray(self._data)
        minimum_frame_size = 17  # packet id + 14-byte header + 2-byte CRC
        declared_size = int.from_bytes(frame[1:3], byteorder="little") if len(frame) >= 3 else -1
        invalid_reason = None

        if len(frame) < minimum_frame_size:
            invalid_reason = f"frame is too short: {len(frame)} bytes"
        elif declared_size != len(frame) - 1:
            invalid_reason = f"declared size {declared_size} does not match {len(frame) - 1}"
        elif frame[3] != self.MAGIC_NUMBER:
            invalid_reason = f"invalid magic byte {frame[3]:#04x}"
        elif binascii.crc_hqx(frame[1:], 0xFFFF) != 0:
            invalid_reason = "CRC validation failed"

        if invalid_reason is not None:
            _LOGGER.warning("Discarding invalid Tion response (%s): %s", invalid_reason, bytes(frame).hex())
            self._reset_message_assembly()
            return False

        self._header = frame[:15]
        self._crc = frame[-2:]
        self._data = frame[15:-2]
        self._have_full_package = False
        return True

    @final
    def split_command(self, request: bytearray) -> List[bytearray]:
        def chunks(lst, n):
            """Yield successive n-sized chunks from lst."""
            for j in range(0, len(lst), n):
                yield lst[j:j + n]

        request.pop(0)

        if len(request) < 20:
            request.insert(0, self.SINGLE_PACKET_ID)
            return [request]

        result = list(chunks(request, 19))

        for i in range(0, len(result)):
            if i == 0:  # First packet
                result[i].insert(0, self.FIRST_PACKET_ID)
            elif i == len(result)-1:  # Last packet
                result[i].insert(0, self.END_PACKET_ID)
            else:  # Middle packets
                result[i].insert(0, self.MIDDLE_PACKET_ID)

        return result

    @final
    async def _send_request(self, request: bytearray):
        self.have_breezer_state = False

        for d in self.split_command(request):
            _LOGGER.debug("Doing write: request=%s", bytes(d).hex())
            await self._try_write(d)

    async def _pair(self):
        """Lite family breezers is not require special pairing procedure"""
        return

    @final
    @property
    def CRC(self) -> list:
        return [0xbb, 0xaa]

    @abc.abstractmethod
    def _encode_request(self, request: dict) -> bytearray:
        """
        encode requested parameters
        :param request: dict with parameters that we should set
        :return: bytearray of encoded request. result[0] will be overwritten in  self._send_request()
        """
        raise NotImplementedError()
    @abc.abstractmethod
    def _decode_response(self, response: bytearray):
        raise NotImplementedError()

    @abc.abstractmethod
    def _generate_model_specific_json(self) -> dict:
        raise NotImplementedError()

    @property
    @abc.abstractmethod
    def REQUEST_PARAMS(self) -> list:
        raise NotImplementedError()

    @property
    @abc.abstractmethod
    def SET_PARAMS(self) -> list:
        raise NotImplementedError()

    @property
    @abc.abstractmethod
    def REQUEST_DEVICE_INFO(self) -> list:
        raise NotImplementedError()

    @property
    @abc.abstractmethod
    def _packages(self) -> list:
        """Packages for tests"""
        raise NotImplementedError()
