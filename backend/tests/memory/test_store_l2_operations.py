"""Tests for unified memory L2 operation facade methods."""

from __future__ import annotations

from unittest.mock import AsyncMock
from types import SimpleNamespace

import pytest

from magi.core.operation_barrier import AsyncOperationBarrier
from magi.memory.store_l2_operations import UnifiedMemoryL2OperationsMixin


class _Harness(UnifiedMemoryL2OperationsMixin):
    def __init__(self, l2, *, l1=None, l2_pipeline=None) -> None:  # type: ignore[no-untyped-def]
        self.l1 = l1
        self.l2 = l2
        self.l2_pipeline = l2_pipeline
        self._memory_epoch = 0
        self._memory_barrier = AsyncOperationBarrier()

    def memory_operation_epoch(self) -> int:
        return self._memory_epoch

    def memory_operation_guard(self):
        return self._memory_barrier.operation()


@pytest.mark.asyncio
async def test_upsert_user_graph_edges_delegates_to_l2_batch_writer():
    l2 = AsyncMock()
    l2.upsert_knowledge_edges.return_value = ["triple-1"]
    harness = _Harness(l2)

    result = await harness.upsert_user_graph_edges(
        [
            {
                "subject_id": "user:self",
                "subject_type": "user",
                "predicate": "VIEWED",
                "object_id": "site:1",
                "object_type": "web_page",
                "evidence_event_ids": ["evt-1"],
                "confidence": 0.8,
                "observed_at": 1.0,
                "source_type": "chrome_history",
                "subject_attributes": {"ignored": True},
            }
        ]
    )

    assert result == ["triple-1"]
    l2.upsert_knowledge_edges.assert_awaited_once_with(
        [
            {
                "subject_id": "user:local_user",
                "subject_type": "user",
                "predicate": "VIEWED",
                "object_id": "site:1",
                "object_type": "web_page",
                "fact_kind": None,
                "evidence_event_ids": ["evt-1"],
                "confidence": 0.8,
                "observed_at": 1.0,
                "source_type": "chrome_history",
            }
        ]
    )


@pytest.mark.asyncio
async def test_upsert_user_graph_edge_canonicalizes_self_subject():
    l2 = AsyncMock()
    harness = _Harness(l2)

    await harness.upsert_user_graph_edge(
        subject_id="user:self",
        subject_type="user",
        predicate="VIEWED",
        object_id="site:1",
        object_type="web_page",
        evidence_event_ids=["evt-1"],
        confidence=0.8,
        observed_at=1.0,
        source_type="chrome_history",
    )

    l2.upsert_knowledge_edge.assert_awaited_once_with(
        subject_id="user:local_user",
        subject_type="user",
        predicate="VIEWED",
        object_id="site:1",
        object_type="web_page",
        fact_kind=None,
        evidence_event_ids=["evt-1"],
        confidence=0.8,
        observed_at=1.0,
        source_type="chrome_history",
    )


@pytest.mark.asyncio
async def test_upsert_user_graph_edges_returns_empty_without_l2_store():
    harness = _Harness(None)

    assert await harness.upsert_user_graph_edges([]) == []


@pytest.mark.asyncio
async def test_replay_l2_extraction_uses_the_durable_projection_queue():
    event = SimpleNamespace(
        event_id="event-replay",
        source="chat",
        event_type="UserMessage",
    )
    l1 = AsyncMock()
    l1.get_memory_event.return_value = event
    l2 = AsyncMock()
    l2.enqueue_projection_job.return_value = False
    l2.request_projection_replay.return_value = True
    pipeline = AsyncMock()
    harness = _Harness(l2, l1=l1, l2_pipeline=pipeline)

    assert await harness.replay_l2_extraction("event-replay") is True

    l2.enqueue_projection_job.assert_awaited_once_with(
        event_id="event-replay",
        source="chat",
        event_type="UserMessage",
    )
    l2.request_projection_replay.assert_awaited_once_with("event-replay")
    pipeline.enqueue_event.assert_not_awaited()
    pipeline.flush_all_pending_batches.assert_awaited_once_with()
