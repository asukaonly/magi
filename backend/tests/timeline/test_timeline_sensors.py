import time
from pathlib import Path

import pytest

from magi.timeline.sensors import (
    BrowserHistoryTimelineSensor,
    ManualJournalTimelineSensor,
    PhotoLibraryTimelineSensor,
)
from magi.timeline.insight_pipeline import TimelineInsightPipeline


class _FakeUnifiedMemory:
    def __init__(self):
        self.edges = []

    def upsert_user_graph_edge(self, **kwargs):
        self.edges.append(kwargs)

@pytest.mark.asyncio
async def test_manual_journal_sensor_builds_text_and_image_blocks():
    sensor = ManualJournalTimelineSensor()
    item = {
        "entry_id": "journal-1",
        "title": "A calm evening",
        "text": "Cooked dinner and relaxed.",
        "image_refs": ["/tmp/evening.png"],
        "occurred_at": time.time(),
    }

    event = await sensor.build_timeline_event(item)

    assert event.source_type == "manual_journal"
    assert event.retention_mode == "retain_raw"
    assert [block.kind for block in event.content_blocks] == ["text", "image"]


@pytest.mark.asyncio
async def test_browser_history_sensor_uses_metadata_only_until_secondary_fetch_enabled():
    item = {
        "url": "https://example.com/articles/asuka",
        "title": "Asuka article",
        "visit_time": 1710000000.0,
        "visit_count": 4,
        "page_content": "Detailed page content that should stay gated.",
    }
    sensor = BrowserHistoryTimelineSensor(fetch_page_content=False)

    identity = sensor.source_item_identity(item)
    fingerprint = sensor.source_item_version_fingerprint(item)
    fetched = await sensor.fetch_item(item)

    assert "example.com/articles/asuka" in identity
    assert "Asuka article" in fingerprint
    assert "page_content" not in fetched

    rich_sensor = BrowserHistoryTimelineSensor(fetch_page_content=True)
    rich_fetched = await rich_sensor.fetch_item(item)
    assert rich_fetched["page_content"] == item["page_content"]


@pytest.mark.asyncio
async def test_photo_library_sensor_rejects_paths_outside_allowed_scope(tmp_path: Path):
    allowed_dir = tmp_path / "photos"
    allowed_dir.mkdir()
    allowed_photo = allowed_dir / "img-1.jpg"
    allowed_photo.write_bytes(b"img")

    sensor = PhotoLibraryTimelineSensor(source_path=str(allowed_dir))
    item = {
        "asset_local_id": "photo-1",
        "path": str(allowed_photo),
        "modified_at": 1710000000.0,
        "analysis_scope": "full",
        "file_hash": "abc123",
    }

    fetched = await sensor.fetch_item(item)
    assert fetched["path"] == str(allowed_photo)
    assert sensor.source_item_identity(item) == "photo-1"
    assert "abc123" in sensor.source_item_version_fingerprint(item)

    outside_photo = tmp_path / "outside.jpg"
    outside_photo.write_bytes(b"bad")
    with pytest.raises(ValueError):
        await sensor.fetch_item(
            {
                "asset_local_id": "photo-2",
                "path": str(outside_photo),
                "modified_at": 1710000001.0,
                "analysis_scope": "full",
            }
        )


@pytest.mark.asyncio
async def test_insight_pipeline_enforces_source_edge_whitelist():
    sensor = BrowserHistoryTimelineSensor(fetch_page_content=False)
    item = {
        "url": "https://example.com/articles/asuka",
        "title": "Asuka article",
        "visit_time": 1710000000.0,
        "visit_count": 4,
        "relation_candidates": [
            {
                "subject_id": "user:self",
                "subject_type": "user",
                "predicate": "LIKES",
                "object_id": "topic:asuka",
                "object_type": "topic",
                "confidence": 0.9,
            },
            {
                "subject_id": "user:self",
                "subject_type": "user",
                "predicate": "DISLIKES",
                "object_id": "topic:asuka",
                "object_type": "topic",
                "confidence": 0.2,
            },
        ],
    }

    event = await sensor.build_timeline_event(item)
    candidates = await sensor.extract_candidates(item)
    memory = _FakeUnifiedMemory()
    pipeline = TimelineInsightPipeline(memory)

    persisted = await pipeline.process_event(event, candidates["relation_candidates"], ["LIKES", "FREEFORM"])

    assert len(persisted) == 1
    assert persisted[0]["predicate"] == "LIKES"
    assert memory.edges[0]["predicate"] == "LIKES"
