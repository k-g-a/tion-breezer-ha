import binascii
from unittest.mock import AsyncMock, Mock, call

import pytest

import tion_btle.tion as tion_module
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


def test_critical_device_error_does_not_block_recovery_writes():
    breezer = TionS4("dummy")
    breezer._error_code = (1 << 0) | (1 << 1)

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
    get_response = AsyncMock(side_effect=[response, response, bytearray(4)])
    monkeypatch.setattr(breezer, "connect", connect)
    monkeypatch.setattr(breezer, "disconnect", disconnect)
    monkeypatch.setattr(breezer, "_try_write", write_status)
    monkeypatch.setattr(breezer, "_send_request", send_request)
    monkeypatch.setattr(breezer, "_get_data_from_breezer", get_response)

    await breezer.set({"fan_speed": 3})

    assert breezer.fan_speed == 2
    assert breezer.active_error_codes == []
    assert write_status.await_args_list == [
        call(request=breezer.command_getStatus),
        call(request=breezer.command_getTurboStatus),
    ]
    send_request.assert_awaited_once()
    disconnect.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("current_power", "current_mode", "changes"),
    [
        (True, 0, {"state": "off"}),
        (False, 0, {"state": "on"}),
        (True, 0, {"mode": "recirculation"}),
        (True, 1, {"mode": "outside"}),
    ],
)
async def test_power_and_air_source_transitions_share_valve_settling_delay(
    monkeypatch, current_power, current_mode, changes
):
    breezer = TionS4("dummy")
    breezer._last_air_valve_transition_at = 100.0
    state = bytearray(31)
    state[0] = int(current_power)
    state[2] = current_mode
    state[4] = 1
    sleep = AsyncMock()
    clock = Mock(side_effect=[105.0, 115.0])
    monkeypatch.setattr(tion_module.asyncio, "sleep", sleep)
    monkeypatch.setattr(tion_module, "monotonic", clock)
    monkeypatch.setattr(breezer, "connect", AsyncMock())
    monkeypatch.setattr(breezer, "_try_write", AsyncMock())
    monkeypatch.setattr(breezer, "_send_request", AsyncMock())
    monkeypatch.setattr(
        breezer,
        "_get_data_from_breezer",
        AsyncMock(side_effect=[state, state, bytearray(4)]),
    )

    await breezer.set(changes)

    assert sleep.await_args.args[0] == pytest.approx(10.0)
    assert breezer._last_air_valve_transition_at == 115.0


@pytest.mark.asyncio
async def test_first_valve_transition_is_immediate(monkeypatch):
    breezer = TionS4("dummy")
    state = bytearray(31)
    state[4] = 1
    sleep = AsyncMock()
    monkeypatch.setattr(tion_module.asyncio, "sleep", sleep)
    monkeypatch.setattr(tion_module, "monotonic", Mock(return_value=100.0))
    monkeypatch.setattr(breezer, "connect", AsyncMock())
    monkeypatch.setattr(breezer, "_try_write", AsyncMock())
    monkeypatch.setattr(breezer, "_send_request", AsyncMock())
    monkeypatch.setattr(
        breezer,
        "_get_data_from_breezer",
        AsyncMock(side_effect=[state, state, bytearray(4)]),
    )

    await breezer.set({"state": "on"})

    sleep.assert_not_awaited()
    assert breezer._last_air_valve_transition_at == 100.0


@pytest.mark.asyncio
async def test_non_valve_changes_are_not_delayed(monkeypatch):
    breezer = TionS4("dummy")
    breezer._last_air_valve_transition_at = 100.0
    state = bytearray(31)
    state[4] = 1
    sleep = AsyncMock()
    clock = Mock()
    monkeypatch.setattr(tion_module.asyncio, "sleep", sleep)
    monkeypatch.setattr(tion_module, "monotonic", clock)
    monkeypatch.setattr(breezer, "connect", AsyncMock())
    monkeypatch.setattr(breezer, "_try_write", AsyncMock())
    monkeypatch.setattr(breezer, "_send_request", AsyncMock())
    monkeypatch.setattr(
        breezer,
        "_get_data_from_breezer",
        AsyncMock(side_effect=[state, state, bytearray(4)]),
    )

    await breezer.set({"fan_speed": 2})

    sleep.assert_not_awaited()
    clock.assert_not_called()
    assert breezer._last_air_valve_transition_at == 100.0


def test_turbo_status_request_uses_native_4s_frame_type_and_valid_crc():
    breezer = TionS4("dummy")

    request = breezer.command_getTurboStatus

    assert request[0] == breezer.SINGLE_PACKET_ID
    assert request[5:7] == bytes(breezer.TURBO_REQUEST_PARAMS)
    assert int.from_bytes(request[7:11], byteorder="little") == breezer.BLE_REQUEST_ID
    assert binascii.crc_hqx(request[1:], 0xFFFF) == 0


def test_turbo_set_request_encodes_duration_and_valid_crc():
    breezer = TionS4("dummy")

    request = breezer._encode_turbo_request(300)

    assert request[0] == breezer.SINGLE_PACKET_ID
    assert request[5:7] == bytes(breezer.TURBO_SET_PARAMS)
    assert int.from_bytes(request[7:11], byteorder="little") == breezer.BLE_REQUEST_ID
    assert int.from_bytes(request[11:15], byteorder="little") == 1
    assert int.from_bytes(request[15:17], byteorder="little") == 300
    assert request[17] == 0
    assert binascii.crc_hqx(request[1:], 0xFFFF) == 0


@pytest.mark.parametrize("duration", [-1, 0x10000])
def test_turbo_set_rejects_duration_outside_uint16(duration):
    breezer = TionS4("dummy")

    with pytest.raises(TionException, match="between 0 and 65535 seconds"):
        breezer._encode_turbo_request(duration)


def test_turbo_response_exposes_device_timer_state():
    breezer = TionS4("dummy")

    breezer._decode_turbo_response(bytearray([1, 0x2C, 0x01, 0]))

    state = breezer._generate_model_specific_json()
    assert state["boost_active"] is True
    assert state["boost_time_left"] == 300
    assert state["boost_error_code"] == 0

    breezer._decode_turbo_response(bytearray([0, 0x2C, 0x01, 0]))
    assert breezer._boost_active is False
    assert breezer._boost_time_left == 0


def test_turbo_response_rejects_invalid_size_and_device_error():
    breezer = TionS4("dummy")

    with pytest.raises(TionException, match="invalid Tion 4S Turbo response"):
        breezer._decode_turbo_response(bytearray(3))

    with pytest.raises(TionException, match="error code 7"):
        breezer._decode_turbo_response(bytearray([0, 0, 0, 7]), reject_error=True)


def test_turbo_status_error_is_exposed_without_breaking_state_poll():
    breezer = TionS4("dummy")

    breezer._decode_turbo_response(bytearray([1, 30, 0, 7]))

    assert breezer._boost_active is True
    assert breezer._boost_time_left == 30
    assert breezer._boost_error_code == 7


@pytest.mark.asyncio
async def test_response_reader_ignores_unrelated_valid_frame_type():
    breezer = TionS4("dummy")
    state = bytearray(31)
    state[4] = 3
    turbo_frame = breezer._build_frame(
        breezer.SINGLE_PACKET_ID,
        breezer.TURBO_RESPONSE_PARAMS,
        (1).to_bytes(4, byteorder="little") + bytearray([1, 44, 1, 0]),
    )
    state_frame = breezer._build_frame(
        breezer.FIRST_PACKET_ID,
        breezer.STATE_RESPONSE_PARAMS,
        (2).to_bytes(4, byteorder="little") + state,
    )

    for packet in breezer.split_command(turbo_frame):
        breezer._delegation.handleNotification(1, packet)
    for packet in breezer.split_command(state_frame):
        breezer._delegation.handleNotification(1, packet)

    response = await breezer._get_data_from_breezer(breezer.STATE_RESPONSE_PARAMS)

    assert response == state
    assert not breezer._delegation.haveNewData


@pytest.mark.asyncio
async def test_native_boost_uses_firmware_timer_and_refreshes_regular_state(monkeypatch):
    breezer = TionS4("dummy")
    before = bytearray(31)
    before[4] = 2
    after = bytearray(31)
    after[4] = 6
    turbo = bytearray([1, 0x2C, 0x01, 0])
    write_status = AsyncMock()
    send_request = AsyncMock()
    get_response = AsyncMock(side_effect=[before, turbo, after])
    monkeypatch.setattr(breezer, "connect", AsyncMock())
    monkeypatch.setattr(breezer, "_try_write", write_status)
    monkeypatch.setattr(breezer, "_send_request", send_request)
    monkeypatch.setattr(breezer, "_get_data_from_breezer", get_response)

    await breezer.set_boost(300)

    assert write_status.await_args_list == [
        call(request=breezer.command_getStatus),
        call(request=breezer.command_getStatus),
    ]
    request = send_request.await_args.args[0]
    assert request[5:7] == bytes(breezer.TURBO_SET_PARAMS)
    assert int.from_bytes(request[15:17], byteorder="little") == 300
    assert get_response.await_args_list == [
        call(breezer.STATE_RESPONSE_PARAMS),
        call(breezer.TURBO_RESPONSE_PARAMS),
        call(breezer.STATE_RESPONSE_PARAMS),
    ]
    assert breezer._boost_active is True
    assert breezer._boost_time_left == 300
    assert breezer.fan_speed == 6


@pytest.mark.asyncio
async def test_native_boost_cancel_bypasses_state_error_guard(monkeypatch):
    breezer = TionS4("dummy")
    state = bytearray(31)
    state[4] = 2
    state[25:29] = ((1 << 0) | (1 << 10)).to_bytes(4, byteorder="little")
    write_status = AsyncMock()
    send_request = AsyncMock()
    monkeypatch.setattr(breezer, "connect", AsyncMock())
    monkeypatch.setattr(breezer, "_try_write", write_status)
    monkeypatch.setattr(breezer, "_send_request", send_request)
    monkeypatch.setattr(
        breezer,
        "_get_data_from_breezer",
        AsyncMock(side_effect=[bytearray(4), state]),
    )

    await breezer.set_boost(0)

    write_status.assert_awaited_once_with(request=breezer.command_getStatus)
    request = send_request.await_args.args[0]
    assert int.from_bytes(request[15:17], byteorder="little") == 0
    assert breezer._boost_active is False
    assert breezer.active_error_codes == ["EC01", "EC11"]


@pytest.mark.asyncio
async def test_native_boost_enable_is_left_to_firmware_during_device_error(monkeypatch):
    breezer = TionS4("dummy")
    state = bytearray(31)
    state[25:29] = (1 << 2).to_bytes(4, byteorder="little")
    turbo = bytearray([1, 0x2C, 0x01, 0])
    send_request = AsyncMock()
    reset_connection = AsyncMock()
    monkeypatch.setattr(breezer, "connect", AsyncMock())
    monkeypatch.setattr(breezer, "_try_write", AsyncMock())
    monkeypatch.setattr(breezer, "_send_request", send_request)
    monkeypatch.setattr(
        breezer,
        "_get_data_from_breezer",
        AsyncMock(side_effect=[state, turbo, state]),
    )
    monkeypatch.setattr(breezer, "reset_connection", reset_connection)

    await breezer.set_boost(300)

    send_request.assert_awaited_once()
    reset_connection.assert_not_awaited()
    assert breezer.active_error_codes == ["EC03"]


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
        "boost_active": False,
        "boost_time_left": 0,
        "boost_error_code": 0,
    }


def test_4s_active_heating_uses_heater_output_not_raw_state_bit():
    breezer = TionS4("dummy")
    response = bytearray(31)
    response[0] = (1 << 0) | (1 << 3) | (1 << 4)
    response[4] = 1
    response[30] = 0

    breezer._decode_response(response)

    assert breezer.heater == "off"
    assert breezer.heating == "off"
    assert breezer._generate_model_specific_json()["heater_active"] is False

    response[30] = 25
    breezer._decode_response(response)

    assert breezer.heating == "on"
    assert breezer._generate_model_specific_json()["heater_active"] is True


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


def test_error_mask_does_not_block_maintenance_actions():
    breezer = TionS4("dummy")
    breezer._error_code = (1 << 0) | (1 << 10)

    breezer._validate_state_before_write({"reset_errors": True})
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
    monkeypatch.setattr(
        breezer,
        "_get_data_from_breezer",
        AsyncMock(side_effect=[response, response, bytearray(4)]),
    )

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
    monkeypatch.setattr(
        breezer,
        "_get_data_from_breezer",
        AsyncMock(side_effect=[response, response, bytearray(4)]),
    )

    await breezer.set({"reset_errors": True})

    request = send_request.await_args.args[0]
    assert request[15] & (1 << 6)
    assert breezer.active_error_codes == ["EC01", "EC11"]
