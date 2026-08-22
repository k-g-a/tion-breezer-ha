"""Serialize short-lived Bluetooth sessions shared by all Tion entries."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager
import logging
from time import monotonic
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from homeassistant.core import HomeAssistant

_LOGGER = logging.getLogger(__name__)

DATA_SESSION_MANAGER = "_bluetooth_session_manager"
ADVERTISEMENT_REAPPEAR_TIMEOUT = 5.0


class TionBluetoothSessionManager:
    """Allow only one Tion connection to use the Bluetooth stack at a time."""

    def __init__(self) -> None:
        self._lock = asyncio.Lock()
        self._sequence = 0
        self._advertisement_generation: dict[str, int] = {}
        self._advertisement_waiters: dict[str, set[asyncio.Future[None]]] = {}

    def advertisement_seen(self, address: str) -> None:
        """Record a connectable advertisement and wake teardown waiters."""
        address = address.upper()
        self._advertisement_generation[address] = (
            self._advertisement_generation.get(address, 0) + 1
        )
        for waiter in self._advertisement_waiters.pop(address, set()):
            if not waiter.done():
                waiter.set_result(None)

    async def _wait_for_fresh_advertisement(
        self, address: str, baseline: int
    ) -> None:
        """Wait until the peripheral advertises after its link teardown began."""
        if self._advertisement_generation.get(address, 0) > baseline:
            return

        waiter = asyncio.get_running_loop().create_future()
        waiters = self._advertisement_waiters.setdefault(address, set())
        waiters.add(waiter)
        # Close the race between checking the generation and registering.
        if self._advertisement_generation.get(address, 0) > baseline:
            waiter.set_result(None)
        try:
            async with asyncio.timeout(ADVERTISEMENT_REAPPEAR_TIMEOUT):
                await waiter
            _LOGGER.debug("Fresh advertisement received after disconnect: address=%s", address)
        except TimeoutError:
            _LOGGER.warning(
                "No fresh advertisement from %s within %.1fs after disconnect",
                address,
                ADVERTISEMENT_REAPPEAR_TIMEOUT,
            )
        finally:
            waiters.discard(waiter)
            if not waiters:
                self._advertisement_waiters.pop(address, None)

    @asynccontextmanager
    async def session(
        self,
        address: str,
        cleanup: Callable[[], Awaitable[bool]],
        *,
        wait_for_advertisement: bool = True,
    ) -> AsyncIterator[None]:
        """Run an operation and finish its teardown before admitting another."""
        queued_at = monotonic()
        was_queued = self._lock.locked()
        address = address.upper()
        async with self._lock:
            self._sequence += 1
            sequence = self._sequence
            _LOGGER.debug(
                "BLE session acquired: sequence=%s address=%s queued=%s wait=%.3fs",
                sequence,
                address,
                was_queued,
                monotonic() - queued_at,
            )
            try:
                yield
            finally:
                teardown_started = monotonic()
                advertisement_baseline = self._advertisement_generation.get(address, 0)
                try:
                    had_connection = await cleanup()
                    if had_connection and wait_for_advertisement:
                        await self._wait_for_fresh_advertisement(
                            address, advertisement_baseline
                        )
                finally:
                    _LOGGER.debug(
                        "BLE session released: sequence=%s address=%s teardown=%.3fs",
                        sequence,
                        address,
                        monotonic() - teardown_started,
                    )


def get_session_manager(hass: HomeAssistant) -> TionBluetoothSessionManager:
    """Return the process-wide Tion Bluetooth session manager."""
    from .const import DOMAIN

    domain_data = hass.data.setdefault(DOMAIN, {})
    manager = domain_data.get(DATA_SESSION_MANAGER)
    if isinstance(manager, TionBluetoothSessionManager):
        return manager

    manager = TionBluetoothSessionManager()
    domain_data[DATA_SESSION_MANAGER] = manager
    return manager
