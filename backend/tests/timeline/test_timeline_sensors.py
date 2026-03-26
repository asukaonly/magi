import time
from pathlib import Path

import pytest

from magi.timeline.sensors import (
    PhotoLibraryTimelineSensor,
)
from magi.timeline.adapter import TimelineAdapter
from magi.timeline.insight_pipeline import TimelineInsightPipeline


class _FakeUnifiedMemory:
    def __init__(self):
        self.edges = []

    def upsert_user_graph_edge(self, **kwargs):
        self.edges.append(kwargs)

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
    sensor = PhotoLibraryTimelineSensor(source_path="/tmp/photos")
    item = {
        "asset_local_id": "photo-1",
        "path": "/tmp/photos/asuka.jpg",
        "modified_at": 1710000000.0,
        "analysis_scope": "full",
        "file_hash": "abc123",
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

    output = await sensor.build_output(item)
    metadata = await sensor.extract_metadata(item)

    # Pipeline expects TimelineEvent; convert via adapter
    event_id = f"{output.source_type}:{output.source_item_id}"
    event = TimelineAdapter._build_timeline_event(event_id, output, metadata)

    memory = _FakeUnifiedMemory()
    pipeline = TimelineInsightPipeline(memory)

    persisted = await pipeline.process_event(event, metadata.relation_candidates, ["LIKES", "FREEFORM"])

    assert len(persisted) == 1
    assert persisted[0]["predicate"] == "LIKES"
    assert memory.edges[0]["predicate"] == "LIKES"
