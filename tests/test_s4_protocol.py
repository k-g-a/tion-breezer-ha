import binascii
from unittest.mock import AsyncMock

import pytest

from tion_btle.s4 import TionS4
from tion_btle.tion import TionException


def test_status_request_uses_protocol_constants_and_valid_crc():
    breezer = TionS4("dummy")

    request = breezer.command_getStatus

    assert request[0] == breezer.SINGLE_PACKET_ID
    assert int.from_bytes(request[1:3], byteorder="little") == len(request) - 1
    assert request[3:5] == bytes([breezer.MAGIC_NUMBER, breezer.FRAME_RANDOM])
    assert request[5:7] == bytes(breezer.REQUEST_PARAMS)
    assert int.from_bytes(request[7:11], byteorder="little") == breezer.BLE_REQUEST_ID
    assert binascii.crc_hqx(request[1:], 0xFFFF) == 0
    assert request[-2:] != bytes([0xBB, 0xAA])


def test_set_request_has_logical_request_id_zero_filter_time_and_valid_crc():
    breezer = TionS4("dummy")
    settings = {
        "state": "on",
        "sound": "off",
        "light": "on",
        "heater": "on",
        "mode": "outside",
        "heater_temp": 22,
        "fan_speed": 3,
    }

    request = breezer._encode_request(settings)

    assert request[0] == breezer.FIRST_PACKET_ID
    assert int.from_bytes(request[1:3], byteorder="little") == len(request) - 1
    assert request[3:5] == bytes([breezer.MAGIC_NUMBER, breezer.FRAME_RANDOM])
    assert request[5:7] == bytes(breezer.SET_PARAMS)
    assert int.from_bytes(request[7:11], byteorder="little") == breezer.BLE_REQUEST_ID
    assert int.from_bytes(request[11:15], byteorder="little") == 1
    assert request[15:20] == bytes([0b00010101, 0, 0, 22, 3])
    assert int.from_bytes(request[20:22], byteorder="little") == 0
    assert binascii.crc_hqx(request[1:], 0xFFFF) == 0


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

    connect = AsyncMock()
    disconnect = AsyncMock()
    send_request = AsyncMock()
    get_response = AsyncMock(return_value=response)
    monkeypatch.setattr(breezer, "connect", connect)
    monkeypatch.setattr(breezer, "disconnect", disconnect)
    monkeypatch.setattr(breezer, "_send_request", send_request)
    monkeypatch.setattr(breezer, "_get_data_from_breezer", get_response)

    await breezer.set({"fan_speed": 3})

    assert breezer.fan_speed == 2
    send_request.assert_awaited_once()
    disconnect.assert_awaited_once()


def test_invalid_state_response_size_is_rejected():
    breezer = TionS4("dummy")

    with pytest.raises(TionException, match="invalid Tion 4S response"):
        breezer._decode_response(bytearray(28))
