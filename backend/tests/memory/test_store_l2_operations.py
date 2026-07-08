"""Tests for unified memory L2 operation facade methods."""

from __future__ import annotations

from unittest.mock import AsyncMock

import pytest

from magi.memory.store_l2_operations import UnifiedMemoryL2OperationsMixin


class _Harness(UnifiedMemoryL2OperationsMixin):
    def __init__(self, l2) -> None:
        self.l1 = None
        self.l2 = l2
        self.l2_pipeline = None


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
