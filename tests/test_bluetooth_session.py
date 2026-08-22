import asyncio
from unittest.mock import AsyncMock

import pytest

from bluetooth_session import TionBluetoothSessionManager


@pytest.mark.asyncio
async def test_sessions_are_serialized_until_cleanup_finishes():
    manager = TionBluetoothSessionManager()
    first_entered = asyncio.Event()
    allow_first_cleanup = asyncio.Event()
    order: list[str] = []

    async def first_cleanup() -> bool:
        order.append("first-cleanup-start")
        await allow_first_cleanup.wait()
        order.append("first-cleanup-end")
        return True

    async def first_session() -> None:
        async with manager.session(
            "first",
            first_cleanup,
            wait_for_advertisement=False,
        ):
            order.append("first-operation")
            first_entered.set()

    second_cleanup = AsyncMock(return_value=False)

    async def second_session() -> None:
        await first_entered.wait()
        async with manager.session("second", second_cleanup):
            order.append("second-operation")

    first_task = asyncio.create_task(first_session())
    second_task = asyncio.create_task(second_session())
    await first_entered.wait()
    await asyncio.sleep(0)

    assert "second-operation" not in order
    allow_first_cleanup.set()
    await asyncio.gather(first_task, second_task)

    assert order == [
        "first-operation",
        "first-cleanup-start",
        "first-cleanup-end",
        "second-operation",
    ]
    second_cleanup.assert_awaited_once()


@pytest.mark.asyncio
async def test_session_cleans_up_after_operation_error():
    manager = TionBluetoothSessionManager()
    cleanup = AsyncMock(return_value=False)

    with pytest.raises(RuntimeError, match="operation failed"):
        async with manager.session("device", cleanup):
            raise RuntimeError("operation failed")

    cleanup.assert_awaited_once()


@pytest.mark.asyncio
async def test_session_waits_for_post_disconnect_advertisement():
    manager = TionBluetoothSessionManager()
    cleanup = AsyncMock(return_value=True)
    operation_finished = asyncio.Event()

    async def run_session() -> None:
        async with manager.session("aa:bb:cc:dd:ee:ff", cleanup):
            operation_finished.set()

    task = asyncio.create_task(run_session())
    await operation_finished.wait()
    while cleanup.await_count == 0:
        await asyncio.sleep(0)
    assert not task.done()

    manager.advertisement_seen("AA:BB:CC:DD:EE:FF")
    await task
