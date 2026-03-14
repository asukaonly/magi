from __future__ import annotations

import pytest

from magi.timeline.contracts import TimelineEvent
from magi.timeline.insight_pipeline import TimelineInsightPipeline


class _SyncMemory:
    def __init__(self) -> None:
        self.edges: list[dict] = []

    def upsert_user_graph_edge(self, **kwargs) -> None:
        self.edges.append(kwargs)


@pytest.mark.asyncio
async def test_insight_pipeline_accepts_sync_graph_writer() -> None:
    memory = _SyncMemory()
    pipeline = TimelineInsightPipeline(memory)
    event = TimelineEvent(
        event_id="evt-1",
        source_type="chat",
        source_item_id="turn-1",
        occurred_at=1710000000.0,
        captured_at=1710000001.0,
        title="Chat turn",
        summary="User likes Asuka",
        retention_mode="retain_raw",
    )

    persisted = await pipeline.process_event(
        event,
        relation_candidates=[
            {
                "subject_id": "user:self",
                "subject_type": "user",
                "predicate": "LIKES",
                "object_id": "character:asuka",
                "object_type": "person",
                "confidence": 0.9,
            }
        ],
        allowed_edge_whitelist=["LIKES"],
    )

    assert len(persisted) == 1
    assert memory.edges[0]["predicate"] == "LIKES"
