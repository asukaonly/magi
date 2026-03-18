from __future__ import annotations

import pytest

from magi.timeline.projection_builder import TimelineProjectionBuilder
from magi.timeline.projection_models import TimelineProjectionQuery


class _FakeL1Store:
    async def query_events(self, **kwargs):  # type: ignore[no-untyped-def]
        return [
            {
                "event_id": "evt-1",
                "event_type": "UserMessage",
                "source": "chat",
                "source_item_id": "turn-1",
                "timestamp": 100.0,
                "created_at": 100.0,
                "raw_content": "UserMessage I still like Asuka best.",
                "metadata": {
                    "timeline": {
                        "title": "Chat turn",
                        "summary": "Mentioned Asuka again.",
                        "source_type": "chat",
                        "content_blocks": [{"kind": "text", "value": "I still like Asuka best."}],
                        "tags": ["chat"],
                        "entities": [{"id": "person:asuka", "label": "Asuka", "type": "person"}],
                    }
                },
            }
        ]


class _FakeL3Store:
    async def list_summaries(self, *, limit: int = 100):  # type: ignore[no-untyped-def]
        return [
            {
                "summary_id": "summary-1",
                "summary_type": "temporal",
                "summary_category": "day",
                "period_start": 80.0,
                "period_end": 120.0,
                "content": "Spent time talking about favorite characters.",
                "key_topics": ["chat"],
                "key_entities": ["person:asuka"],
                "source_event_ids": ["evt-1"],
                "source_event_count": 1,
            }
        ]


@pytest.mark.asyncio
async def test_projection_builder_creates_event_and_summary_items() -> None:
    builder = TimelineProjectionBuilder(l1_store=_FakeL1Store(), l3_store=_FakeL3Store())

    items = await builder.build(
        TimelineProjectionQuery(
            start=50.0,
            end=150.0,
            source_type=None,
            limit=10,
        )
    )

    assert [item.item_type for item in items] == ["summary", "event"]
    event_item = next(item for item in items if item.item_type == "event")
    summary_item = next(item for item in items if item.item_type == "summary")

    assert event_item.primary_event_id == "evt-1"
    assert event_item.source_event_ids == ["evt-1"]
    assert event_item.display_payload["title"] == "Chat turn"
    assert summary_item.primary_summary_id == "summary-1"
    assert summary_item.source_summary_ids == ["summary-1"]
    assert summary_item.source_event_ids == ["evt-1"]
