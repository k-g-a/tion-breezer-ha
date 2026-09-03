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
    breezer._error_code = (1 << 0) | (1 << 10)
    response = bytearray(31)
    response[4] = 2

    connect = AsyncMock()
    disconnect = AsyncMock()
    write_status = AsyncMock()
    send_request = AsyncMock()
    get_response = AsyncMock(return_value=response)
    monkeypatch.setattr(breezer, "connect", connect)
    monkeypatch.setattr(breezer, "disconnect", disconnect)
    monkeypatch.setattr(breezer, "_try_write", write_status)
    monkeypatch.setattr(breezer, "_send_request", send_request)
    monkeypatch.setattr(breezer, "_get_data_from_breezer", get_response)

    await breezer.set({"fan_speed": 3})

    assert breezer.fan_speed == 2
    assert breezer.active_error_codes == []
    write_status.assert_awaited_once_with(request=breezer.command_getStatus)
    send_request.assert_awaited_once()
    disconnect.assert_not_awaited()


def test_invalid_state_response_size_is_rejected():
    breezer = TionS4("dummy")

    with pytest.raises(TionException, match="invalid Tion 4S response"):
        breezer._decode_response(bytearray(28))


def _build_state_response_packets(breezer: TionS4, errors: int = 0):
    state = bytearray(31)
    state[4] = 1
    state[25:29] = errors.to_bytes(4, byteorder="little")
    frame = breezer._build_frame(
        breezer.FIRST_PACKET_ID,
        [0x31, 0x32],
        (1).to_bytes(4, byteorder="little") + state,
    )
    return state, breezer.split_command(frame)


def test_fragmented_response_is_validated_before_decode():
    breezer = TionS4("dummy")
    state, packets = _build_state_response_packets(breezer, errors=1 << 2)

    assert [packet[0] for packet in packets] == [
        breezer.FIRST_PACKET_ID,
        breezer.MIDDLE_PACKET_ID,
        breezer.END_PACKET_ID,
    ]
    assert breezer._collect_message(packets[0]) is False
    assert breezer._collect_message(packets[1]) is False
    assert breezer._collect_message(packets[2]) is True
    assert breezer._data == state
    assert len(breezer._crc) == 2


def test_orphan_end_packet_is_discarded():
    breezer = TionS4("dummy")
    _, packets = _build_state_response_packets(breezer)

    assert breezer._collect_message(packets[-1]) is False
    assert breezer._data == bytearray()
    assert breezer._got_new_sequence is False


def test_bad_crc_resets_fragment_assembly():
    breezer = TionS4("dummy")
    _, packets = _build_state_response_packets(breezer)
    packets[-1][-1] ^= 0x01

    assert breezer._collect_message(packets[0]) is False
    assert breezer._collect_message(packets[1]) is False
    assert breezer._collect_message(packets[2]) is False
    assert breezer._data == bytearray()
    assert breezer._got_new_sequence is False


def test_reset_discards_incomplete_fragment_sequence():
    breezer = TionS4("dummy")
    _, packets = _build_state_response_packets(breezer)

    assert breezer._collect_message(packets[0]) is False
    assert breezer._got_new_sequence is True

    breezer._reset_message_assembly()

    assert breezer._collect_message(packets[-1]) is False
    assert breezer._data == bytearray()


def test_decode_exposes_all_regular_4s_state_fields():
    breezer = TionS4("dummy")
    response = bytearray(31)
    response[0] = 0b11101101
    response[1] = 0b00011100
    response[2] = 1
    response[3] = 23
    response[4] = 5
    response[5] = 0xFE
    response[6] = 18
    response[7] = 27
    response[8] = 42
    response[9:13] = (12345).to_bytes(4, byteorder="little")
    response[13:17] = (67890).to_bytes(4, byteorder="little")
    response[17:21] = (365 * 86400).to_bytes(4, byteorder="little")
    response[21:25] = (2400).to_bytes(4, byteorder="little")
    response[25:29] = ((1 << 2) | (1 << 24)).to_bytes(4, byteorder="little")
    response[29] = 6
    response[30] = 55

    breezer._decode_response(response)
    state = breezer._generate_model_specific_json()

    assert breezer.heating == "on"
    assert breezer.filter_remain == 365
    assert state == {
        "light": "on",
        "active_error_codes": ["EC03", "WS01"],
        "device_problem": True,
        "heater_active": True,
        "filter_change_required": True,
        "heater_power_rating": 1000,
        "magicair_connected": True,
        "magicair_auto": True,
        "timer_active": True,
        "comm_source": "user",
        "pcb_control_temp": 27,
        "pcb_power_temp": 42,
        "work_time": 12345,
        "fan_time": 67890,
        "airflow_counter": 2400,
        "airflow_total": 10,
        "max_fan_speed": 6,
        "heater_output": 55,
    }


def _settings(**changes):
    settings = {
        "state": "on",
        "sound": "on",
        "light": "on",
        "heater": "on",
        "mode": "outside",
        "heater_temp": 22,
        "fan_speed": 3,
    }
    settings.update(changes)
    return settings


def test_sound_and_light_preferences_use_persisted_state_frame():
    breezer = TionS4("dummy")

    request = breezer._encode_request(_settings(_save_state=True))

    assert request[5:7] == bytes(breezer.SAVE_PARAMS)


@pytest.mark.parametrize(
    "action, expected_flag",
    [("reset_errors", 1 << 6), ("reset_filter", 1 << 7)],
)
def test_maintenance_action_flags_are_encoded(action, expected_flag):
    breezer = TionS4("dummy")

    request = breezer._encode_request(_settings(**{action: True}))

    assert request[15] & expected_flag
    assert request[5:7] == bytes(breezer.SET_PARAMS)


def test_reset_errors_bypasses_critical_error_guard():
    breezer = TionS4("dummy")
    breezer._error_code = (1 << 0) | (1 << 10)

    breezer._validate_state_before_write({"reset_errors": True})

    with pytest.raises(TionException, match="EC01, EC11"):
        breezer._validate_state_before_write({"reset_filter": True})


@pytest.mark.asyncio
async def test_set_marks_sound_and_light_changes_as_persistent(monkeypatch):
    breezer = TionS4("dummy")
    response = bytearray(31)
    response[4] = 1
    send_request = AsyncMock()
    monkeypatch.setattr(breezer, "connect", AsyncMock())
    monkeypatch.setattr(breezer, "_try_write", AsyncMock())
    monkeypatch.setattr(breezer, "_send_request", send_request)
    monkeypatch.setattr(breezer, "_get_data_from_breezer", AsyncMock(return_value=response))

    await breezer.set({"sound": "off"})

    request = send_request.await_args.args[0]
    assert request[5:7] == bytes(breezer.SAVE_PARAMS)


@pytest.mark.asyncio
async def test_reset_errors_executes_while_critical_errors_are_active(monkeypatch):
    breezer = TionS4("dummy")
    response = bytearray(31)
    response[4] = 1
    response[25:29] = ((1 << 0) | (1 << 10)).to_bytes(4, byteorder="little")
    send_request = AsyncMock()
    monkeypatch.setattr(breezer, "connect", AsyncMock())
    monkeypatch.setattr(breezer, "_try_write", AsyncMock())
    monkeypatch.setattr(breezer, "_send_request", send_request)
    monkeypatch.setattr(breezer, "_get_data_from_breezer", AsyncMock(return_value=response))

    await breezer.set({"reset_errors": True})

    request = send_request.await_args.args[0]
    assert request[15] & (1 << 6)
    assert breezer.active_error_codes == ["EC01", "EC11"]
