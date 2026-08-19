"""Home Assistant Bluetooth connection-slot lifecycle helpers."""

from __future__ import annotations

import logging
from typing import Any

from bleak.backends.device import BLEDevice
from bleak_retry_connector import BleakOutOfConnectionSlotsError, wait_for_disconnect
from habluetooth import get_manager

_LOGGER = logging.getLogger(__name__)


def _device_source(device: BLEDevice) -> str | None:
    """Return the HA Bluetooth source represented by a Bleak device."""
    if not isinstance(device.details, dict):
        return None

    if source := device.details.get("source"):
        return str(source)

    path = device.details.get("path")
    if not isinstance(path, str):
        return None
    parts = path.split("/")
    return next((part for part in parts if part.startswith("hci")), None)


def _allocation_fields(allocation: Any) -> tuple[str | None, int, int, tuple[str, ...]]:
    """Normalize allocation snapshots across supported HA versions."""
    source = getattr(allocation, "source", getattr(allocation, "adapter", None))
    slots = int(getattr(allocation, "slots", 0))
    free = int(getattr(allocation, "free", 0))
    allocated = tuple(str(address).upper() for address in getattr(allocation, "allocated", ()))
    return source, slots, free, allocated


def _allocation_snapshot(device: BLEDevice) -> tuple[Any | None, list[Any]]:
    """Return the Bluetooth manager and relevant slot snapshots."""
    try:
        manager = get_manager()
        source = _device_source(device)
        allocations = manager.async_current_allocations(source) if source else manager.async_current_allocations()
        return manager, list(allocations or [])
    except (AttributeError, RuntimeError):
        _LOGGER.debug(
            "BLE slot information is unavailable: address=%s source=%s",
            device.address,
            _device_source(device),
            exc_info=True,
        )
        return None, []


def _log_allocations(stage: str, device: BLEDevice, allocations: list[Any]) -> None:
    """Log enough allocation state to diagnose leaked or exhausted slots."""
    path = device.details.get("path") if isinstance(device.details, dict) else None
    if not allocations:
        _LOGGER.debug(
            "BLE slots %s: address=%s path=%s source=%s allocations=unavailable",
            stage,
            device.address,
            path,
            _device_source(device),
        )
        return

    for allocation in allocations:
        source, slots, free, allocated = _allocation_fields(allocation)
        _LOGGER.debug(
            "BLE slots %s: address=%s path=%s source=%s slots=%s free=%s allocated=%s",
            stage,
            device.address,
            path,
            source,
            slots,
            free,
            allocated,
        )


def guard_connection_slot(device: BLEDevice) -> None:
    """Log slot state and fail immediately when the selected source is full."""
    _, allocations = _allocation_snapshot(device)
    _log_allocations("before-connect", device, allocations)
    target = device.address.upper()

    for allocation in allocations:
        source, slots, free, allocated = _allocation_fields(allocation)
        # slots == 0 means that this source does not report slot information.
        if slots > 0 and free <= 0 and target not in allocated:
            raise BleakOutOfConnectionSlotsError(
                f"Bluetooth source {source} has no free connection slots "
                f"(slots={slots}, allocated={allocated})"
            )


async def reconcile_connection_slot(device: BLEDevice) -> None:
    """Wait for BlueZ disconnect and release the exact HA allocation."""
    manager, before = _allocation_snapshot(device)
    _log_allocations("before-release", device, before)
    if manager is None:
        return

    # Bleak's disconnect coroutine can return before the BlueZ Connected=False
    # property reaches HA. wait_for_disconnect observes that property directly.
    await wait_for_disconnect(device, 0)
    manager.async_release_connection_slot(device)

    _, after = _allocation_snapshot(device)
    _log_allocations("after-release", device, after)
