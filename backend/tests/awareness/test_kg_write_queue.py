"""Tests for the sensor-derived knowledge graph write queue."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from magi.awareness.kg_write_queue import KnowledgeGraphEdgeWrite, KnowledgeGraphWriteQueue


def _edge(object_id: str = "site:1") -> KnowledgeGraphEdgeWrite:
    return KnowledgeGraphEdgeWrite(
        subject_id="user:self",
        subject_type="user",
        predicate="VIEWED",
        object_id=object_id,
        object_type="web_page",
        fact_kind=None,
        evidence_event_ids=("evt-1",),
        confidence=0.8,
        observed_at=1.0,
        source_type="chrome_history",
        subject_attributes={},
        object_attributes={},
    )


@pytest.fixture
def fake_memory():
    memory = MagicMock()
    memory.upsert_user_graph_edges = AsyncMock(return_value=["triple-1"])
    return memory


@pytest.mark.asyncio
async def test_batches_edges_through_memory_batch_writer(fake_memory):
    queue = KnowledgeGraphWriteQueue(
        unified_memory=fake_memory,
        max_batch_size=10,
        flush_interval_seconds=0.01,
    )
    await queue.start()

    await queue.add_edge(_edge("site:1"))
    await queue.add_edge(_edge("site:2"))
    await queue.drain()
    await queue.stop()

    fake_memory.upsert_user_graph_edges.assert_awaited_once()
    edges = fake_memory.upsert_user_graph_edges.await_args.args[0]
    assert [edge["object_id"] for edge in edges] == ["site:1", "site:2"]

    stats = queue.get_stats()
    assert stats.enqueued_count == 2
    assert stats.flushed_batch_count == 1
    assert stats.flushed_edge_count == 2
    assert stats.last_flush_latency_ms is not None


@pytest.mark.asyncio
async def test_flushes_when_batch_size_is_reached(fake_memory):
    queue = KnowledgeGraphWriteQueue(
        unified_memory=fake_memory,
        max_batch_size=2,
        flush_interval_seconds=10.0,
    )
    await queue.start()

    await queue.add_edge(_edge("site:1"))
    await queue.add_edge(_edge("site:2"))
    await queue.drain()
    await queue.stop()

    fake_memory.upsert_user_graph_edges.assert_awaited_once()


@pytest.mark.asyncio
async def test_retries_failed_batches(fake_memory):
    fake_memory.upsert_user_graph_edges.side_effect = [RuntimeError("busy"), ["triple-1"]]
    queue = KnowledgeGraphWriteQueue(
        unified_memory=fake_memory,
        max_batch_size=1,
        flush_interval_seconds=0.01,
        retry_attempts=1,
    )
    await queue.start()

    await queue.add_edge(_edge())
    await queue.drain()
    await queue.stop()

    assert fake_memory.upsert_user_graph_edges.await_count == 2
    assert queue.get_stats().retry_count == 1


@pytest.mark.asyncio
async def test_requires_start_before_enqueue(fake_memory):
    queue = KnowledgeGraphWriteQueue(unified_memory=fake_memory)

    with pytest.raises(RuntimeError):
        await queue.add_edge(_edge())
