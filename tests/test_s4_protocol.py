from unittest.mock import AsyncMock

import pytest

from tion_btle.s4 import TionS4
from tion_btle.tion import TionException


def _settings() -> dict:
    return {
        "state": "on",
        "sound": "off",
        "light": "on",
        "heater": "on",
        "mode": "outside",
        "heater_temp": 22,
        "fan_speed": 3,
    }


def test_status_request_keeps_working_archive_framing():
    breezer = TionS4("dummy")

    request = breezer.command_getStatus

    assert request[0] == breezer.SINGLE_PACKET_ID
    assert request[1:3] == bytes([0x10, 0x00])
    assert request[3] == breezer.MAGIC_NUMBER
    assert request[5:7] == bytes(breezer.REQUEST_PARAMS)
    assert request[-2:] == bytes(breezer.CRC)


def test_set_request_keeps_working_archive_framing():
    breezer = TionS4("dummy")

    request = breezer._encode_request(_settings())

    assert request[0] == breezer.FIRST_PACKET_ID
    assert request[1:3] == bytes([0x17, 0x00])
    assert request[3] == breezer.MAGIC_NUMBER
    assert request[5:7] == bytes(breezer.SET_PARAMS)
    assert request[-2:] == bytes(breezer.CRC)


def test_decode_exposes_critical_errors_and_warnings():
    breezer = TionS4("dummy")
    response = bytearray(31)
    response[25:29] = ((1 << 0) | (1 << 1) | (1 << 25)).to_bytes(4, byteorder="little")

    breezer._decode_response(response)

    assert breezer.active_error_codes == ["EC01", "EC02", "WS02"]
    assert breezer._generate_model_specific_json()["active_error_codes"] == ["EC01", "EC02", "WS02"]


def test_critical_device_error_blocks_writes():
    breezer = TionS4("dummy")
    breezer._error_code = (1 << 0) | (1 << 1)

    with pytest.raises(TionException, match="EC01, EC02"):
        breezer._validate_state_before_write()


def test_device_warning_does_not_block_writes():
    breezer = TionS4("dummy")
    breezer._error_code = 1 << 24

    breezer._validate_state_before_write()


@pytest.mark.asyncio
async def test_set_uses_device_response_as_source_of_truth(monkeypatch):
    breezer = TionS4("dummy")
    breezer.have_breezer_state = True
    breezer._fan_speed = 1
    response = bytearray(31)
    response[4] = 2

    monkeypatch.setattr(breezer, "connect", AsyncMock())
    monkeypatch.setattr(breezer, "_send_request", AsyncMock())
    monkeypatch.setattr(breezer, "_get_data_from_breezer", AsyncMock(return_value=response))

    await breezer.set({"fan_speed": 3})

    assert breezer.fan_speed == 2


def test_invalid_state_response_size_is_rejected():
    breezer = TionS4("dummy")

    with pytest.raises(TionException, match="invalid Tion 4S response"):
        breezer._decode_response(bytearray(28))
