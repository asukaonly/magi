"""Cancellation must not release plugin resources while a thread owns them."""

import asyncio
import threading

import pytest

from magi.plugins.operation_execution import (
    plugin_user_content_clear_boundary,
    run_plugin_archive_operation,
    run_plugin_callback_operation,
    run_plugin_lifecycle_operation,
    run_plugin_preparation_operation,
)


@pytest.mark.asyncio
@pytest.mark.parametrize("run_operation", [
    run_plugin_archive_operation,
    run_plugin_callback_operation,
    run_plugin_lifecycle_operation,
    run_plugin_preparation_operation,
])
async def test_cancelled_operation_drains_thread_before_releasing_clear_barrier(run_operation):
    entered = threading.Event()
    release = threading.Event()
    mutation_finished = threading.Event()
    clear_entered = asyncio.Event()

    def mutate():
        entered.set()
        assert release.wait(5)
        mutation_finished.set()

    async def clear():
        async with plugin_user_content_clear_boundary():
            assert mutation_finished.is_set()
            clear_entered.set()

    activation = asyncio.create_task(run_operation(mutate))
    clearing = None
    try:
        assert await asyncio.to_thread(entered.wait, 2)
        activation.cancel()
        clearing = asyncio.create_task(clear())
        await asyncio.sleep(0)
        await asyncio.sleep(0)
        assert not activation.done()
        activation.cancel()
        await asyncio.sleep(0)
        assert not activation.done()
        assert not clear_entered.is_set()
    finally:
        release.set()
        with pytest.raises(asyncio.CancelledError):
            await activation
        if clearing is not None:
            await asyncio.wait_for(clearing, 2)
    assert clear_entered.is_set()


@pytest.mark.asyncio
async def test_cancelled_queued_lifecycle_does_not_start_after_running_work():
    entered = threading.Event()
    release = threading.Event()
    queued_started = threading.Event()

    def running():
        entered.set()
        assert release.wait(5)

    first = asyncio.create_task(run_plugin_lifecycle_operation(running))
    queued = None
    try:
        assert await asyncio.to_thread(entered.wait, 2)
        queued = asyncio.create_task(run_plugin_lifecycle_operation(queued_started.set))
        await asyncio.sleep(0)
        queued.cancel()
        with pytest.raises(asyncio.CancelledError):
            await asyncio.wait_for(queued, 1)
    finally:
        release.set()
        await first
        if queued is not None and not queued.done():
            await queued
    assert not queued_started.is_set()
