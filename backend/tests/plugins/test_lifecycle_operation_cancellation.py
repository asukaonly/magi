"""Cancellation must not release plugin resources while a thread owns them."""

import asyncio
import threading

import pytest

from magi.plugins.operation_execution import (
    plugin_user_content_clear_boundary,
    run_plugin_lifecycle_operation,
)


@pytest.mark.asyncio
async def test_cancelled_activation_drains_thread_before_releasing_clear_barrier():
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

    activation = asyncio.create_task(run_plugin_lifecycle_operation(mutate))
    clearing = None
    try:
        assert await asyncio.to_thread(entered.wait, 2)
        activation.cancel()
        clearing = asyncio.create_task(clear())
        await asyncio.sleep(0)
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
