from unittest.mock import AsyncMock, Mock

from bleak import exc
from bleak.backends.device import BLEDevice
import pytest

import tion_btle.tion as tion_module
from tion_btle.s4 import TionS4


@pytest.mark.asyncio
async def test_connect_uses_retry_connector_and_latest_ble_device(monkeypatch):
    initial_device = BLEDevice("AA:BB:CC:DD:EE:FF", "Tion", {"source": "old"})
    latest_device = BLEDevice("AA:BB:CC:DD:EE:FF", "Tion", {"source": "new"})
    breezer = TionS4(initial_device)
    breezer.set_ble_device_callback(lambda: latest_device)
    client = Mock(is_connected=True)
    establish_connection = AsyncMock(return_value=client)
    monkeypatch.setattr(tion_module, "establish_connection", establish_connection)

    assert await breezer._try_connect()

    callback = establish_connection.await_args.kwargs["disconnected_callback"]
    device_callback = establish_connection.await_args.kwargs["ble_device_callback"]
    assert establish_connection.await_args.args[1] is latest_device
    assert device_callback() is latest_device
    assert establish_connection.await_args.kwargs["max_attempts"] == 3

    callback(Mock())
    assert breezer._btle is client

    callback(client)
    assert breezer._btle is None


@pytest.mark.asyncio
async def test_failed_retry_connector_call_is_not_retried_again(monkeypatch):
    device = BLEDevice("AA:BB:CC:DD:EE:FF", "Tion", {})
    breezer = TionS4(device)
    establish_connection = AsyncMock(side_effect=exc.BleakError("not reachable"))
    monkeypatch.setattr(tion_module, "establish_connection", establish_connection)

    with pytest.raises(exc.BleakError):
        await breezer._try_connect()

    establish_connection.assert_awaited_once()


@pytest.mark.asyncio
async def test_failed_write_is_not_replayed():
    breezer = TionS4("AA:BB:CC:DD:EE:FF")
    client = AsyncMock()
    client.is_connected = True
    client.write_gatt_char.side_effect = exc.BleakError("write status unknown")
    breezer._btle = client

    with pytest.raises(exc.BleakError):
        await breezer._try_write(bytearray(b"request"))

    client.write_gatt_char.assert_awaited_once()


@pytest.mark.asyncio
async def test_failed_connect_allows_a_later_retry(monkeypatch):
    breezer = TionS4("AA:BB:CC:DD:EE:FF")
    connect = AsyncMock(side_effect=exc.BleakError("not reachable"))
    monkeypatch.setattr(breezer, "_connect", connect)

    with pytest.raises(exc.BleakError):
        await breezer.connect()

    connect.reset_mock(side_effect=True)
    connect.return_value = None
    await breezer.connect()

    connect.assert_awaited_once()


@pytest.mark.asyncio
async def test_multiple_requests_reuse_connection_until_session_cleanup(monkeypatch):
    device = BLEDevice("AA:BB:CC:DD:EE:FF", "Tion", {})
    breezer = TionS4(device)
    client = AsyncMock()
    client.is_connected = True
    establish_connection = AsyncMock(return_value=client)
    monkeypatch.setattr(tion_module, "establish_connection", establish_connection)
    monkeypatch.setattr(breezer, "_try_write", AsyncMock())
    monkeypatch.setattr(breezer, "_get_data_from_breezer", AsyncMock(return_value=bytearray(31)))

    await breezer.get()
    await breezer.get()

    establish_connection.assert_awaited_once()
    client.start_notify.assert_awaited_once()
    client.disconnect.assert_not_awaited()


@pytest.mark.asyncio
async def test_reset_connection_clears_client_and_buffer(monkeypatch):
    breezer = TionS4("AA:BB:CC:DD:EE:FF")
    client = AsyncMock()
    client.is_connected = True

    async def disconnect() -> None:
        client.is_connected = False

    client.disconnect.side_effect = disconnect
    breezer._btle = client
    breezer.have_breezer_state = True
    breezer._delegation.handleNotification(1, bytearray(b"stale"))

    await breezer.reset_connection()

    client.disconnect.assert_awaited_once()
    assert breezer._btle is None
    assert not breezer.have_breezer_state
    assert not breezer._delegation.haveNewData


@pytest.mark.asyncio
async def test_disconnect_closes_backend_when_client_reports_disconnected():
    breezer = TionS4("AA:BB:CC:DD:EE:FF")
    client = AsyncMock()
    client.is_connected = False
    breezer._btle = client

    await breezer._disconnect()

    client.disconnect.assert_awaited_once()
    assert breezer._btle is None


@pytest.mark.asyncio
async def test_disconnect_callback_only_clears_current_client(monkeypatch):
    device = BLEDevice("AA:BB:CC:DD:EE:FF", "Tion", {"path": "/org/bluez/hci0/dev_AA_BB_CC_DD_EE_FF"})
    breezer = TionS4(device)
    client = AsyncMock()
    client.is_connected = True
    establish_connection = AsyncMock(return_value=client)
    monkeypatch.setattr(tion_module, "establish_connection", establish_connection)

    await breezer._try_connect()
    callback = establish_connection.await_args.kwargs["disconnected_callback"]

    async def disconnect() -> None:
        assert breezer._btle is client
        client.is_connected = False
        callback(client)

    client.disconnect.side_effect = disconnect
    await breezer._disconnect()

    client.disconnect.assert_awaited_once()
    assert breezer._btle is None


@pytest.mark.asyncio
async def test_disconnect_stops_notifications_and_waits_for_bluez(monkeypatch):
    device = BLEDevice(
        "AA:BB:CC:DD:EE:FF",
        "Tion",
        {"path": "/org/bluez/hci0/dev_AA_BB_CC_DD_EE_FF"},
    )
    breezer = TionS4(device)
    client = AsyncMock()
    client.is_connected = True
    breezer._btle = client
    breezer._active_ble_device = device
    breezer._Tion__notifications_enabled = True
    wait_for_disconnect = AsyncMock()
    monkeypatch.setattr(tion_module, "wait_for_disconnect", wait_for_disconnect)

    async def disconnect() -> None:
        client.is_connected = False

    client.disconnect.side_effect = disconnect

    await breezer.disconnect()

    client.stop_notify.assert_awaited_once_with(breezer.uuid_notify)
    client.disconnect.assert_awaited_once()
    wait_for_disconnect.assert_awaited_once_with(
        device,
        tion_module.DISCONNECT_SETTLE_SECONDS,
    )
    assert breezer._btle is None


@pytest.mark.asyncio
async def test_disconnect_rejects_a_backend_that_remains_connected():
    breezer = TionS4("AA:BB:CC:DD:EE:FF")
    client = AsyncMock()
    client.is_connected = True
    breezer._btle = client

    with pytest.raises(exc.BleakError, match="remained connected"):
        await breezer.disconnect()

    client.disconnect.assert_awaited_once()
    assert breezer._btle is None
