from collections import namedtuple
from unittest.mock import AsyncMock, Mock

from bleak.backends.device import BLEDevice
from bleak_retry_connector import BleakOutOfConnectionSlotsError
import pytest

import bluetooth_lifecycle as lifecycle


Allocation = namedtuple("Allocation", "source slots free allocated")


def _device() -> BLEDevice:
    return BLEDevice(
        "AA:BB:CC:DD:EE:FF",
        "Tion",
        {"path": "/org/bluez/hci0/dev_AA_BB_CC_DD_EE_FF"},
    )


def test_guard_fails_fast_when_selected_adapter_is_full(monkeypatch):
    manager = Mock()
    manager.async_current_allocations.return_value = [Allocation("hci0", 1, 0, ("11:22:33:44:55:66",))]
    manager.async_scanner_devices_by_address.return_value = []
    monkeypatch.setattr(lifecycle, "get_manager", lambda: manager)

    with pytest.raises(BleakOutOfConnectionSlotsError):
        lifecycle.guard_connection_slot(_device())

    manager.async_current_allocations.assert_called_once_with("hci0")


def test_guard_allows_existing_allocation_for_same_device(monkeypatch):
    manager = Mock()
    manager.async_current_allocations.return_value = [Allocation("hci0", 1, 0, ("aa:bb:cc:dd:ee:ff",))]
    manager.async_scanner_devices_by_address.return_value = []
    monkeypatch.setattr(lifecycle, "get_manager", lambda: manager)

    lifecycle.guard_connection_slot(_device())


@pytest.mark.asyncio
async def test_reconcile_waits_for_bluez_then_releases_exact_device(monkeypatch):
    device = _device()
    manager = Mock()
    manager.async_current_allocations.side_effect = [
        [Allocation("hci0", 1, 0, (device.address,))],
        [Allocation("hci0", 1, 1, ())],
    ]
    wait_for_disconnect = AsyncMock()
    monkeypatch.setattr(lifecycle, "get_manager", lambda: manager)
    monkeypatch.setattr(lifecycle, "wait_for_disconnect", wait_for_disconnect)

    await lifecycle.reconcile_connection_slot(device)

    wait_for_disconnect.assert_awaited_once_with(device, 0)
    manager.async_release_connection_slot.assert_called_once_with(device)
