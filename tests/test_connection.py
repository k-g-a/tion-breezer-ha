from unittest.mock import AsyncMock, Mock

from bleak import exc
from bleak.backends.device import BLEDevice
import pytest

import tion_btle.tion as tion_module
from tion_btle.s4 import TionS4


def _device() -> BLEDevice:
    return BLEDevice("AA:BB:CC:DD:EE:FF", "Tion", {})


@pytest.mark.asyncio
async def test_connect_uses_retry_connector_and_latest_ble_device(monkeypatch):
    device = _device()
    breezer = TionS4(device)
    breezer.set_ble_device_callback(lambda: device)
    client = Mock(is_connected=True)
    establish_connection = AsyncMock(return_value=client)
    monkeypatch.setattr(tion_module, "establish_connection", establish_connection)

    assert await breezer._ensure_client() is client

    callback = establish_connection.await_args.kwargs["disconnected_callback"]
    device_callback = establish_connection.await_args.kwargs["ble_device_callback"]
    assert device_callback() is device
    assert establish_connection.await_args.kwargs["max_attempts"] == 2

    callback(Mock())
    assert breezer._client is client

    callback(client)
    assert breezer._client is None


@pytest.mark.asyncio
async def test_failed_retry_connector_call_is_not_retried_again(monkeypatch):
    device = _device()
    breezer = TionS4(device)
    breezer.set_ble_device_callback(lambda: device)
    establish_connection = AsyncMock(side_effect=exc.BleakError("not reachable"))
    monkeypatch.setattr(tion_module, "establish_connection", establish_connection)

    with pytest.raises(exc.BleakError):
        await breezer._ensure_client()

    establish_connection.assert_awaited_once()


@pytest.mark.asyncio
async def test_failed_write_is_not_replayed():
    breezer = TionS4("AA:BB:CC:DD:EE:FF")
    client = AsyncMock()
    client.is_connected = True
    client.write_gatt_char.side_effect = exc.BleakError("write status unknown")
    breezer._client = client

    with pytest.raises(exc.BleakError):
        await breezer._try_write(bytearray(b"request"))

    client.write_gatt_char.assert_awaited_once()


@pytest.mark.asyncio
async def test_successful_operations_reuse_one_persistent_connection(monkeypatch):
    device = _device()
    breezer = TionS4(device)
    breezer.set_ble_device_callback(lambda: device)
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
async def test_reset_connection_disconnects_and_clears_buffer():
    breezer = TionS4("AA:BB:CC:DD:EE:FF")
    client = AsyncMock()
    client.is_connected = True
    breezer._client = client
    breezer.have_breezer_state = True
    breezer._delegation.handleNotification(1, bytearray(b"stale"))

    await breezer.reset_connection()

    client.disconnect.assert_awaited_once()
    assert breezer._client is None
    assert not breezer.have_breezer_state
    assert not breezer._delegation.haveNewData
