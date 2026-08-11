"""`all` mode runs the API and the worker in one process. In the two-container
layout a worker crash exited its container and the restart policy revived it;
collapsed into one container, the same outcome has to come from the process
exiting. These cover that contract."""

import asyncio

import pytest

from yas.__main__ import _supervise


async def test_supervise_returns_when_both_finish():
    async def ok():
        return None

    await _supervise(ok(), ok())


async def test_worker_failure_propagates():
    async def server():
        await asyncio.sleep(3600)  # would outlive the worker

    async def worker():
        raise RuntimeError("worker exploded")

    with pytest.raises(ExceptionGroup) as ei:
        await _supervise(server(), worker())
    assert any(isinstance(e, RuntimeError) for e in ei.value.exceptions)


async def test_worker_failure_cancels_server():
    cancelled = asyncio.Event()

    async def server():
        try:
            await asyncio.sleep(3600)
        except asyncio.CancelledError:
            cancelled.set()
            raise

    async def worker():
        await asyncio.sleep(0)
        raise RuntimeError("worker exploded")

    with pytest.raises(ExceptionGroup):
        await _supervise(server(), worker())
    assert cancelled.is_set(), "server task must be cancelled when the worker dies"


async def test_server_failure_cancels_worker():
    cancelled = asyncio.Event()

    async def server():
        await asyncio.sleep(0)
        raise RuntimeError("server exploded")

    async def worker():
        try:
            await asyncio.sleep(3600)
        except asyncio.CancelledError:
            cancelled.set()
            raise

    with pytest.raises(ExceptionGroup):
        await _supervise(server(), worker())
    assert cancelled.is_set(), "worker task must be cancelled when the server dies"
