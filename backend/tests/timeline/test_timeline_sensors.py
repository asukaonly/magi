"""Tests for the PhotoLibraryTimelineSensor — output building, sync, and metadata."""
from __future__ import annotations

import importlib.util
import time
from pathlib import Path
from unittest.mock import MagicMock

import pytest

_sensor_path = Path(__file__).resolve().parents[3] / "plugins" / "photo-library" / "sensor.py"
_spec = importlib.util.spec_from_file_location(
    "photo_library_sensor",
    _sensor_path,
    submodule_search_locations=[str(_sensor_path.parent)],
)
assert _spec is not None and _spec.loader is not None
_mod = importlib.util.module_from_spec(_spec)
import sys
sys.modules[_spec.name] = _mod
_spec.loader.exec_module(_mod)
PhotoLibraryTimelineSensor = _mod.PhotoLibraryTimelineSensor

# Also load reader module to get ScanResult
_reader_path = Path(__file__).resolve().parents[3] / "plugins" / "photo-library" / "reader.py"
_reader_spec = importlib.util.spec_from_file_location(
    "photo_library_reader",
    _reader_path,
    submodule_search_locations=[str(_reader_path.parent)],
)
assert _reader_spec is not None and _reader_spec.loader is not None
_reader_mod = importlib.util.module_from_spec(_reader_spec)
sys.modules[_reader_spec.name] = _reader_mod
_reader_spec.loader.exec_module(_reader_mod)
ScanResult = _reader_mod.ScanResult

from magi.awareness import SensorSyncContext
from magi.timeline.adapter import TimelineAdapter
from magi.timeline.insight_pipeline import TimelineInsightPipeline


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _photo_item(**overrides) -> dict:
    """Build a realistic photo item dict with defaults."""
    base = {
        "asset_local_id": "abc123",
        "path": "/photos/sunset.jpg",
        "filename": "sunset.jpg",
        "extension": ".jpg",
        "file_size": 4096000,
        "file_hash": "deadbeef12345678",
        "modified_at": 1710000000.0,
        "capture_timestamp": 1710000000.0,
        "datetime_original": "2024:03:09 12:00:00",
        "camera_make": "Canon",
        "camera_model": "EOS R5",
        "lens_model": "RF 50mm F1.8 STM",
        "focal_length": "50.0mm",
        "aperture": "f/1.8",
        "exposure_time": "1/250s",
        "iso": "400",
        "image_width": 8192,
        "image_height": 5464,
        "orientation": 1,
        "latitude": 35.6586,
        "longitude": 139.7454,
        "altitude": 40.0,
    }
    base.update(overrides)
    return base


class _FakeUnifiedMemory:
    def __init__(self):
        self.edges = []

    def upsert_user_graph_edge(self, **kwargs):
        self.edges.append(kwargs)


class _FakeReader:
    """Fake reader that returns pre-configured items."""

    def __init__(self, items: list[dict] | None = None, errors: int = 0):
        self._items = items or []
        self._errors = errors

    def scan_directory(self, source_path, *, limit=500, min_modified_at=0.0):
        filtered = [
            it for it in self._items
            if float(it.get("modified_at", 0)) > min_modified_at
        ][:limit]
        return ScanResult(
            items=filtered,
            total_scanned=len(self._items),
            errors=self._errors,
        )


# ---------------------------------------------------------------------------
# Identity & dedup tests
# ---------------------------------------------------------------------------

class TestSensorIdentity:
    def test_source_item_identity_uses_asset_local_id(self):
        sensor = PhotoLibraryTimelineSensor(source_path="/photos")
        item = _photo_item()
        assert sensor.source_item_identity(item) == "abc123"

    def test_source_item_identity_falls_back_to_hash(self):
        sensor = PhotoLibraryTimelineSensor(source_path="/photos")
        item = _photo_item(asset_local_id="")
        assert sensor.source_item_identity(item) == "deadbeef12345678"

    def test_version_fingerprint_changes_with_hash(self):
        sensor = PhotoLibraryTimelineSensor(source_path="/photos")
        item_a = _photo_item(file_hash="aaa")
        item_b = _photo_item(file_hash="bbb")
        assert sensor.source_item_version_fingerprint(item_a) != \
               sensor.source_item_version_fingerprint(item_b)


# ---------------------------------------------------------------------------
# fetch_item — path scope enforcement
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_fetch_item_rejects_paths_outside_scope(tmp_path: Path):
    allowed_dir = tmp_path / "photos"
    allowed_dir.mkdir()
    allowed_photo = allowed_dir / "img-1.jpg"
    allowed_photo.write_bytes(b"img")

    sensor = PhotoLibraryTimelineSensor(source_path=str(allowed_dir))

    # Allowed path succeeds
    fetched = await sensor.fetch_item({
        "asset_local_id": "photo-1",
        "path": str(allowed_photo),
        "modified_at": 1710000000.0,
        "file_hash": "abc123",
    })
    assert fetched["path"] == str(allowed_photo)

    # Outside path raises
    outside_photo = tmp_path / "outside.jpg"
    outside_photo.write_bytes(b"bad")
    with pytest.raises(ValueError, match="outside"):
        await sensor.fetch_item({
            "asset_local_id": "photo-2",
            "path": str(outside_photo),
            "modified_at": 1710000001.0,
        })


@pytest.mark.asyncio
async def test_fetch_item_requires_source_path():
    sensor = PhotoLibraryTimelineSensor()
    with pytest.raises(ValueError, match="source_path"):
        await sensor.fetch_item({
            "asset_local_id": "photo-1",
            "path": "/some/path.jpg",
        })


# ---------------------------------------------------------------------------
# build_output
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_build_output_full_exif():
    sensor = PhotoLibraryTimelineSensor(source_path="/photos")
    item = _photo_item()
    output = await sensor.build_output(item)
    assert output.source_type == "photo_library"
    assert output.title == "sunset.jpg"
    assert "Canon EOS R5" in output.summary
    assert "50.0mm" in output.summary
    assert output.occurred_at == 1710000000.0
    assert output.provenance["camera"] == "Canon EOS R5"
    assert output.provenance["focal_length"] == "50.0mm"
    assert "photo_library" in output.tags


@pytest.mark.asyncio
async def test_build_output_no_exif():
    sensor = PhotoLibraryTimelineSensor(source_path="/photos")
    item = _photo_item(
        camera_make="", camera_model="",
        focal_length="", aperture="", exposure_time="", iso="",
        latitude=None, longitude=None,
    )
    output = await sensor.build_output(item)
    assert output.title == "sunset.jpg"
    # Summary should not contain camera info
    assert "Canon" not in output.summary


@pytest.mark.asyncio
async def test_build_output_gps_content_block():
    sensor = PhotoLibraryTimelineSensor(source_path="/photos")
    item = _photo_item(latitude=35.6586, longitude=139.7454)
    output = await sensor.build_output(item)
    gps_blocks = [b for b in output.content_blocks if b.kind == "text" and "GPS" in b.value]
    assert len(gps_blocks) == 1
    assert "35.658600" in gps_blocks[0].value


# ---------------------------------------------------------------------------
# extract_metadata
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_extract_metadata_entities():
    sensor = PhotoLibraryTimelineSensor(source_path="/photos")
    item = _photo_item()
    meta = await sensor.extract_metadata(item)
    entity_types = {e["entity_type"] for e in meta.entities}
    assert "device" in entity_types
    assert "location" in entity_types
    assert "photo_library" in meta.tags
    predicates = {r["predicate"] for r in meta.relation_candidates}
    assert "CAPTURED" in predicates
    assert "RELATED_TO" in predicates
    assert "CREATED" in predicates


@pytest.mark.asyncio
async def test_extract_metadata_minimal():
    sensor = PhotoLibraryTimelineSensor(source_path="/photos")
    item = _photo_item(
        camera_make="", camera_model="",
        latitude=None, longitude=None,
    )
    meta = await sensor.extract_metadata(item)
    assert len(meta.entities) == 0
    predicates = {r["predicate"] for r in meta.relation_candidates}
    assert predicates == {"CAPTURED"}


# ---------------------------------------------------------------------------
# l2_batch_policy
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_l2_batch_policy_shards_by_camera():
    sensor = PhotoLibraryTimelineSensor(source_path="/photos")
    item_a = _photo_item(camera_make="Canon", camera_model="EOS R5")
    item_b = _photo_item(camera_make="Sony", camera_model="A7R V")

    output_a = await sensor.build_output(item_a)
    output_b = await sensor.build_output(item_b)

    policy_a = sensor.l2_batch_policy(output_a)
    policy_b = sensor.l2_batch_policy(output_b)

    assert policy_a is not None
    assert policy_b is not None
    assert "Canon EOS R5" in policy_a.owner
    assert "Sony A7R V" in policy_b.owner
    assert policy_a.catch_up_owner is not None


# ---------------------------------------------------------------------------
# collect_items
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_collect_items_returns_scanned_photos(tmp_path: Path):
    photos_dir = tmp_path / "photos"
    photos_dir.mkdir()
    # Create a fake photo file
    photo = photos_dir / "test.jpg"
    photo.write_bytes(b"\xff" * 100)

    fake_items = [{
        "asset_local_id": "hash1",
        "path": str(photo),
        "filename": "test.jpg",
        "extension": ".jpg",
        "file_size": 100,
        "file_hash": "hash1",
        "modified_at": time.time(),
        "capture_timestamp": time.time(),
        "camera_make": "Canon",
        "camera_model": "EOS R5",
        "lens_model": "",
        "focal_length": "",
        "aperture": "",
        "exposure_time": "",
        "iso": "",
        "image_width": 0,
        "image_height": 0,
        "orientation": 0,
        "latitude": None,
        "longitude": None,
        "altitude": None,
    }]

    reader = _FakeReader(items=fake_items)
    sensor = PhotoLibraryTimelineSensor(
        source_path=str(photos_dir),
        reader=reader,
    )

    ctx = SensorSyncContext(
        source_type="photo_library",
        manual=False,
        last_cursor=None,
        last_success_at=0.0,
        limit=100,
        runtime_paths=MagicMock(),
        plugin_settings={
            "sensors": {"photo_library": {"source_path": str(photos_dir)}}
        },
    )
    result = await sensor.collect_items(ctx)
    assert len(result.items) == 1
    assert result.stats["count"] == 1
    assert result.next_cursor is not None


@pytest.mark.asyncio
async def test_collect_items_empty_source_path():
    sensor = PhotoLibraryTimelineSensor()
    ctx = SensorSyncContext(
        source_type="photo_library",
        manual=False,
        last_cursor=None,
        last_success_at=0.0,
        limit=100,
        runtime_paths=MagicMock(),
        plugin_settings={},
    )
    result = await sensor.collect_items(ctx)
    assert len(result.items) == 0
    assert "source_path" in str(result.stats.get("error", ""))


@pytest.mark.asyncio
async def test_collect_items_uses_cursor_for_incremental_sync(tmp_path: Path):
    photos_dir = tmp_path / "photos"
    photos_dir.mkdir()
    photo = photos_dir / "test.jpg"
    photo.write_bytes(b"\xff" * 100)

    old_item = {
        "asset_local_id": "old1",
        "path": str(photo),
        "filename": "test.jpg",
        "modified_at": 1000.0,  # old
        "file_hash": "old1",
    }
    new_item = {
        "asset_local_id": "new1",
        "path": str(photos_dir / "new.jpg"),
        "filename": "new.jpg",
        "modified_at": 2000.0,  # new
        "file_hash": "new1",
    }
    # Write the new file too
    (photos_dir / "new.jpg").write_bytes(b"\x00" * 50)

    reader = _FakeReader(items=[old_item, new_item])
    sensor = PhotoLibraryTimelineSensor(
        source_path=str(photos_dir),
        reader=reader,
    )

    ctx = SensorSyncContext(
        source_type="photo_library",
        manual=False,
        last_cursor="1500.0",  # only items after 1500
        last_success_at=1500.0,
        limit=100,
        runtime_paths=MagicMock(),
        plugin_settings={
            "sensors": {"photo_library": {"source_path": str(photos_dir)}}
        },
    )
    result = await sensor.collect_items(ctx)
    # Only the new item should pass through
    assert len(result.items) == 1
    assert result.items[0]["asset_local_id"] == "new1"


# ---------------------------------------------------------------------------
# Insight pipeline integration — edge whitelist enforcement
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_insight_pipeline_enforces_source_edge_whitelist():
    sensor = PhotoLibraryTimelineSensor(source_path="/tmp/photos")
    item = _photo_item(
        path="/tmp/photos/asuka.jpg",
        filename="asuka.jpg",
    )

    output = await sensor.build_output(item)
    metadata = await sensor.extract_metadata(item)

    event_id = "evt_photo_whitelist_1"
    event = TimelineAdapter._build_timeline_event(event_id, output, metadata)

    # Manually craft relation candidates that include out-of-whitelist predicates
    manual_candidates = [
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
    ]

    memory = _FakeUnifiedMemory()
    pipeline = TimelineInsightPipeline(memory)

    persisted = await pipeline.process_event(
        event, manual_candidates, ["LIKES", "FREEFORM"],
    )

    assert len(persisted) == 1
    assert persisted[0]["predicate"] == "LIKES"
    assert memory.edges[0]["predicate"] == "LIKES"
    assert memory.edges[0]["evidence_event_ids"] == ["evt_photo_whitelist_1"]
