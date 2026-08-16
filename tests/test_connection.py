from unittest.mock import AsyncMock, Mock

from bleak import exc
from bleak.backends.device import BLEDevice
import pytest

import tion_btle.tion as tion_module
from tion_btle.s4 import TionS4


@pytest.mark.asyncio
async def test_connect_uses_retry_connector_and_latest_ble_device(monkeypatch):
    device = BLEDevice("AA:BB:CC:DD:EE:FF", "Tion", {})
    breezer = TionS4(device)
    client = Mock(is_connected=True)
    establish_connection = AsyncMock(return_value=client)
    monkeypatch.setattr(tion_module, "establish_connection", establish_connection)

    assert await breezer._try_connect()

    callback = establish_connection.await_args.kwargs["disconnected_callback"]
    device_callback = establish_connection.await_args.kwargs["ble_device_callback"]
    assert device_callback() is device

    callback(Mock())
    assert breezer._btle is client

    callback(client)
    assert breezer._btle is None


@pytest.mark.asyncio
async def test_failed_connect_does_not_poison_connection_count(monkeypatch):
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
async def test_reset_connection_clears_client_and_buffer(monkeypatch):
    breezer = TionS4("AA:BB:CC:DD:EE:FF")
    client = AsyncMock()
    client.is_connected = True
    breezer._btle = client
    breezer.have_breezer_state = True
    breezer._delegation.handleNotification(1, bytearray(b"stale"))

    await breezer.reset_connection()

    client.disconnect.assert_awaited_once()
    assert breezer._btle is None
    assert not breezer.have_breezer_state
    assert not breezer._delegation.haveNewData
