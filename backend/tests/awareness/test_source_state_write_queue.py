"""Tests for the source state fingerprint write queue."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from magi.awareness.source_state import SourceStateWriteQueue


@pytest.fixture
def fake_store():
    store = MagicMock()
    store.add_fingerprint_groups = AsyncMock()
    return store


@pytest.mark.asyncio
async def test_batches_fingerprints_by_source(fake_store):
    queue = SourceStateWriteQueue(
        source_state_store=fake_store,
        max_batch_size=10,
        flush_interval_seconds=0.01,
    )
    await queue.start()

    await queue.add_fingerprint("chrome_history", "fp-1")
    await queue.add_fingerprint("chrome_history", "fp-2")
    await queue.add_fingerprint("screen_time", "fp-3")
    await queue.drain()
    await queue.stop()

    fake_store.add_fingerprint_groups.assert_awaited_once()
    groups = fake_store.add_fingerprint_groups.await_args.args[0]
    assert groups == {
        "chrome_history": {"fp-1", "fp-2"},
        "screen_time": {"fp-3"},
    }

    stats = queue.get_stats()
    assert stats.enqueued_count == 3
    assert stats.flushed_batch_count == 1
    assert stats.flushed_fingerprint_count == 3
    assert stats.last_flush_latency_ms is not None


@pytest.mark.asyncio
async def test_flushes_when_batch_size_is_reached(fake_store):
    queue = SourceStateWriteQueue(
        source_state_store=fake_store,
        max_batch_size=2,
        flush_interval_seconds=10.0,
    )
    await queue.start()

    await queue.add_fingerprint("chrome_history", "fp-1")
    await queue.add_fingerprint("chrome_history", "fp-2")
    await queue.drain()
    await queue.stop()

    fake_store.add_fingerprint_groups.assert_awaited_once_with(
        {"chrome_history": {"fp-1", "fp-2"}}
    )


@pytest.mark.asyncio
async def test_retries_failed_batches(fake_store):
    fake_store.add_fingerprint_groups.side_effect = [RuntimeError("busy"), None]
    queue = SourceStateWriteQueue(
        source_state_store=fake_store,
        max_batch_size=1,
        flush_interval_seconds=0.01,
        retry_attempts=1,
    )
    await queue.start()

    await queue.add_fingerprint("chrome_history", "fp-1")
    await queue.drain()
    await queue.stop()

    assert fake_store.add_fingerprint_groups.await_count == 2
    assert queue.get_stats().retry_count == 1


@pytest.mark.asyncio
async def test_requires_start_before_enqueue(fake_store):
    queue = SourceStateWriteQueue(source_state_store=fake_store)

    with pytest.raises(RuntimeError):
        await queue.add_fingerprint("chrome_history", "fp-1")
