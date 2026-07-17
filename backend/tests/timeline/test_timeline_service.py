from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from magi.timeline.contracts import TimelineEvent
from magi.timeline.service import TimelineService


@pytest.mark.asyncio
async def test_upsert_event_does_not_reingest_into_unified_memory() -> None:
    unified_memory = SimpleNamespace(
        ingest_event=AsyncMock(),
        l1=None,
        l2=None,
        l3=None,
        l4=None,
    )
    service = TimelineService(unified_memory)

    event = TimelineEvent(
        event_id="evt_calendar_1",
        source_type="calendar",
        source_item_id="item-1",
        occurred_at=1700000000.0,
        captured_at=1700000001.0,
        title="Interview",
        summary="Interview",
        retention_mode="analyze_only",
    )

    result = await service.upsert_event(event)

    assert result == "evt_calendar_1"
    unified_memory.ingest_event.assert_not_awaited()


@pytest.mark.asyncio
async def test_get_context_bundle_resolves_episode_anchor() -> None:
    class _FakeL1:
        async def get_user_visible_event(self, event_id: str):  # type: ignore[no-untyped-def]
            if event_id != "evt-1":
                return None
            return {
                "event_id": "evt-1",
                "timestamp": 100.0,
                "source": "chat",
                "content": "Episode evidence",
                "metadata": {
                    "activity_snapshot": {
                        "title": "Episode event",
                        "summary": "Episode evidence summary.",
                    }
                },
            }

    class _FakeL2:
        async def list_episode_events(self, episode_id: str):  # type: ignore[no-untyped-def]
            if episode_id == "ep-1":
                return [{"event_id": "evt-1"}]
            return []

        async def find_edges_by_event_id(self, event_id: str):  # type: ignore[no-untyped-def]
            return []

    unified_memory = SimpleNamespace(
        l1=_FakeL1(),
        l2=_FakeL2(),
        l3=None,
        l4=None,
    )
    service = TimelineService(unified_memory)

    bundle = await service.get_context_bundle("episode:ep-1")

    assert bundle is not None
    assert bundle["episode_id"] == "ep-1"
    assert bundle["anchor"]["anchor_type"] == "episode"
    assert bundle["l1_events"][0]["event_id"] == "evt-1"


@pytest.mark.asyncio
async def test_get_context_bundle_does_not_read_hidden_event_content() -> None:
    l1 = SimpleNamespace(
        get_event=AsyncMock(
            return_value={
                "event_id": "evt-deleted",
                "content": "Deleted private content",
            }
        ),
        get_user_visible_event=AsyncMock(return_value=None),
    )
    unified_memory = SimpleNamespace(l1=l1, l2=None, l3=None, l4=None)
    service = TimelineService(unified_memory)

    bundle = await service.get_context_bundle("evt-deleted")

    assert bundle is not None
    assert bundle["l1_events"] == []
    assert "Deleted private content" not in str(bundle)
    l1.get_user_visible_event.assert_awaited_once_with("evt-deleted")
    l1.get_event.assert_not_awaited()
