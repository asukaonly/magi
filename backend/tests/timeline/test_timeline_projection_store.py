from __future__ import annotations

from pathlib import Path

import pytest

from magi.timeline.projection_models import TimelineProjectionItem
from magi.timeline.projection_store import TimelineProjectionStore


@pytest.mark.asyncio
async def test_projection_store_saves_loads_and_invalidates_window(tmp_path: Path) -> None:
    store = TimelineProjectionStore(db_path=str(tmp_path / "timeline_projection.db"))
    item = TimelineProjectionItem(
        item_id="event:evt-1",
        window_key="0:100",
        filter_hash="all",
        item_type="event",
        time_start=10.0,
        time_end=10.0,
        sort_time=10.0,
        primary_event_id="evt-1",
        source_event_ids=["evt-1"],
        display_payload={"title": "Event one"},
        projection_version=1,
        generated_at=20.0,
    )

    await store.save_items(
        window_key="0:100",
        filter_hash="all",
        projection_version=1,
        items=[item],
    )

    loaded = await store.load_items(
        window_key="0:100",
        filter_hash="all",
        projection_version=1,
        limit=10,
    )

    assert len(loaded) == 1
    assert loaded[0].item_id == "event:evt-1"
    assert loaded[0].display_payload["title"] == "Event one"

    removed = await store.invalidate_window(
        window_key="0:100",
        filter_hash="all",
        projection_version=1,
    )

    assert removed == 1
    assert await store.load_items(
        window_key="0:100",
        filter_hash="all",
        projection_version=1,
        limit=10,
    ) == []
