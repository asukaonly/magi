"""Tests for bounded same-session extraction context."""

from __future__ import annotations

import pytest

from magi.memory.event_contracts import (
    IngestTarget,
    MemoryDomain,
    MemoryEvent,
    RetentionClass,
    TomDepth,
)
from magi.memory.l2.pipeline.context import L2PipelineContextMixin


def _event(*, event_id: str, session_seq: int) -> MemoryEvent:
    return MemoryEvent(
        event_id=event_id,
        correlation_id="corr",
        timestamp=float(session_seq),
        created_at=float(session_seq),
        event_type="USER_MESSAGE",
        source="chat",
        source_item_id=None,
        memory_domain=MemoryDomain.USER_AUTHORED,
        ingest_target=IngestTarget.L1_ONLY,
        cognition_eligible=True,
        tom_depth=TomDepth.NONE,
        retention_class=RetentionClass.PERMANENT,
        session_id="session-1",
        turn_id=None,
        user_id="user-1",
        task_id=None,
        content="current",
        author_type="user",
        content_type="text",
        importance_score=0.5,
        level=20,
        session_seq=session_seq,
    )


class _FakeL1Store:
    def __init__(self, rows: list[dict[str, object]]) -> None:
        self.rows = rows
        self.calls: list[dict[str, object]] = []

    async def query_session_event_window(self, **kwargs):  # type: ignore[no-untyped-def]
        self.calls.append(dict(kwargs))
        return list(self.rows)


@pytest.mark.asyncio
async def test_context_messages_are_closest_prior_events_with_provenance() -> None:
    store = _FakeL1Store(
        [
            {
                "event_id": "evt-0",
                "session_seq": 0,
                "timestamp": 0.0,
                "author_type": "assistant",
                "content": "oldest",
            },
            {
                "event_id": "evt-1",
                "session_seq": 1,
                "timestamp": 1.0,
                "author_type": "assistant",
                "content": "still relevant",
            },
            {
                "event_id": "evt-2",
                "session_seq": 2,
                "timestamp": 2.0,
                "author_type": "user",
                "content": "我最近在听 DIIV 的专辑",
            },
            {
                "event_id": "evt-3",
                "session_seq": 3,
                "timestamp": 3.0,
                "author_type": "assistant",
                "content": "是 Oshin 还是新专？",
            },
            {
                "event_id": "evt-4",
                "session_seq": 4,
                "timestamp": 4.0,
                "author_type": "user",
                "content": "是新专",
            },
            {
                "event_id": "evt-5",
                "session_seq": 5,
                "timestamp": 5.0,
                "author_type": "assistant",
                "content": "future response",
            },
        ]
    )
    pipeline = L2PipelineContextMixin()
    pipeline._l1_store = store  # type: ignore[attr-defined]
    pipeline._entity_catalog = None  # type: ignore[attr-defined]
    pipeline._cognition_store = None  # type: ignore[attr-defined]

    messages = await pipeline._load_context_messages(_event(event_id="evt-4", session_seq=4))

    assert messages == [
            {
                "event_id": "evt-1",
                "session_seq": 1,
                "timestamp": 1.0,
                "role": "assistant",
                "content": "still relevant",
        },
        {
            "event_id": "evt-2",
            "session_seq": 2,
            "timestamp": 2.0,
            "role": "user",
            "content": "我最近在听 DIIV 的专辑",
        },
        {
            "event_id": "evt-3",
            "session_seq": 3,
            "timestamp": 3.0,
            "role": "assistant",
            "content": "是 Oshin 还是新专？",
        },
    ]
    assert store.calls == [
        {
            "session_id": "session-1",
            "center_session_seq": 4,
            "window": 4,
            "user_id": "user-1",
            "limit": 9,
            "include_metadata_json": False,
            "include_embedding_fields": False,
        }
    ]
