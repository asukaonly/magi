"""Tests for the photo-library source under the current session-based contract."""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from magi.awareness import SourceSyncContext
from magi.awareness.source_projection import build_source_projection
from magi.timeline.insight_pipeline import TimelineInsightPipeline
from magi.timeline.source_projection import build_source_timeline_event

_repo_root = Path(__file__).resolve().parents[3]
_plugin_root = _repo_root / "plugins" / "photo-library"
if not _plugin_root.exists():
    _plugin_root = _repo_root.parent / "magi-plugins" / "plugins" / "photo-library"

_source_path = _plugin_root / "source.py"
if not _source_path.exists():  # pragma: no cover - plugin repo absent (e.g. CI)
    pytest.skip(
        "photo-library plugin not available (magi-plugins is a separate repo); "
        "plugin-backed source tests run only where the plugin is checked out",
        allow_module_level=True,
    )
_spec = importlib.util.spec_from_file_location(
    "photo_library_source",
    _source_path,
    submodule_search_locations=[str(_source_path.parent)],
)
assert _spec is not None and _spec.loader is not None
_mod = importlib.util.module_from_spec(_spec)
sys.modules[_spec.name] = _mod
_spec.loader.exec_module(_mod)
PhotoLibraryTimelineSource = _mod.PhotoLibraryTimelineSource

_reader_path = _plugin_root / "reader.py"
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


def _session_item(**overrides) -> dict:
    base = {
        "session_key": "session:2024-03-09:canon-eos-r5:35.66,139.75",
        "date": "2024-03-09",
        "weekday_index": 5,
        "time_of_day": "afternoon",
        "device_slug": "canon-eos-r5",
        "device_name": "Canon EOS R5",
        "location_name": "Tokyo Tower",
        "latitude": 35.6586,
        "longitude": 139.7454,
        "geo_cell": "35.66,139.75",
        "photo_count": 3,
        "burst_total": 0,
        "first_capture_ts": 1710000000.0,
        "last_capture_ts": 1710003600.0,
        "max_modified_at": 1710003600.0,
        "representative_photos": [
            {
                "path": "/photos/sunset-1.jpg",
                "asset_local_id": "photo-1",
                "capture_ts": 1710000000.0,
                "latitude": 35.6586,
                "longitude": 139.7454,
            },
            {
                "path": "/photos/sunset-2.jpg",
                "asset_local_id": "photo-2",
                "capture_ts": 1710001800.0,
                "latitude": 35.6586,
                "longitude": 139.7454,
            },
            {
                "path": "/photos/sunset-3.jpg",
                "asset_local_id": "photo-3",
                "capture_ts": 1710003600.0,
                "latitude": 35.6586,
                "longitude": 139.7454,
            },
        ],
    }
    base.update(overrides)
    return base


def _raw_photo(path: str, **overrides) -> dict:
    base = {
        "asset_local_id": "raw-photo-1",
        "path": path,
        "filename": Path(path).name,
        "extension": Path(path).suffix,
        "file_size": 100,
        "file_hash": "hash-1",
        "modified_at": 1710000000.0,
        "capture_timestamp": 1710000000.0,
        "camera_make": "Canon",
        "camera_model": "EOS R5",
        "lens_model": "",
        "focal_length": "",
        "aperture": "",
        "exposure_time": "",
        "iso": "",
        "image_width": 0,
        "image_height": 0,
        "orientation": 1,
        "latitude": None,
        "longitude": None,
        "altitude": None,
    }
    base.update(overrides)
    return base


class _FakeUnifiedMemory:
    def __init__(self):
        self.edges = []

    def upsert_user_graph_edge(self, **kwargs):
        self.edges.append(kwargs)


class _FakeReader:
    def __init__(self, items: list[dict] | None = None, errors: int = 0):
        self._items = items or []
        self._errors = errors

    def scan_directory(self, source_path, *, limit=500, min_modified_at=0.0, exclude_patterns=None, analysis_features=None):
        filtered = [
            item for item in self._items
            if float(item.get("modified_at", 0.0)) > min_modified_at
        ][:limit]
        return ScanResult(
            items=filtered,
            total_scanned=len(self._items),
            errors=self._errors,
        )


class TestSourceIdentity:
    def test_source_item_identity_uses_session_key(self):
        source = PhotoLibraryTimelineSource(source_paths=["/photos"])
        item = _session_item()
        assert source.source_item_identity(item) == "session:2024-03-09:canon-eos-r5:35.66,139.75"

    def test_source_item_identity_falls_back_to_unknown(self):
        source = PhotoLibraryTimelineSource(source_paths=["/photos"])
        assert source.source_item_identity({}) == "session:unknown"

    def test_version_fingerprint_changes_with_session_key(self):
        source = PhotoLibraryTimelineSource(source_paths=["/photos"])
        item_a = _session_item(session_key="session:2024-03-09:canon-eos-r5:35.66,139.75")
        item_b = _session_item(session_key="session:2024-03-10:sony-a7r-v:nogps")
        assert source.source_item_version_fingerprint(item_a) != source.source_item_version_fingerprint(item_b)


@pytest.mark.asyncio
async def test_fetch_item_returns_a_copy_without_scope_enforcement(tmp_path: Path):
    photo = tmp_path / "outside.jpg"
    photo.write_bytes(b"img")
    source = PhotoLibraryTimelineSource()

    source_item = {"asset_local_id": "photo-1", "path": str(photo)}
    fetched = await source.fetch_item(source_item)

    assert fetched == source_item
    assert fetched is not source_item


@pytest.mark.asyncio
async def test_build_output_for_photo_session():
    source = PhotoLibraryTimelineSource(source_paths=["/photos"])
    output = await source.build_output(_session_item())

    assert output.source_type == "photo_library"
    assert output.source_item_id == "session:2024-03-09:canon-eos-r5:35.66,139.75"
    assert output.activity.source.code == "photos"
    assert output.activity.action.code == "capture"
    assert output.activity.object is not None and output.activity.object.code == "photo"
    assert output.activity.qualifiers == {"session_type": "photo_session"}
    assert output.narration.title is not None
    assert "2024-03-09" in output.narration.title
    assert "Tokyo Tower" in output.narration.title
    assert "Canon EOS R5" in output.narration.title
    assert output.narration.body
    assert "Tokyo Tower" in output.narration.body
    assert "Canon EOS R5" in output.narration.body
    assert output.occurred_at == 1710000000.0
    assert [block.kind for block in output.content_blocks] == ["image", "image", "image"]
    assert output.tags == ["photo_library", "session", "geo", "Tokyo Tower", "东京"]
    assert output.provenance["device_name"] == "Canon EOS R5"
    assert output.provenance["photo_count"] == 3
    assert output.domain_payload["representative_photos"][0]["asset_local_id"] == "photo-1"


@pytest.mark.asyncio
async def test_build_output_without_device_or_location():
    source = PhotoLibraryTimelineSource(source_paths=["/photos"])
    output = await source.build_output(
        _session_item(
            device_name="",
            device_slug="",
            location_name="",
            latitude=None,
            longitude=None,
            geo_cell="nogps",
        )
    )

    assert output.narration.title is not None
    assert "Canon EOS R5" not in output.narration.title
    assert "Tokyo Tower" not in output.narration.title
    assert output.narration.body
    assert output.tags == ["photo_library", "session"]


@pytest.mark.asyncio
async def test_extract_metadata_for_session_entities_and_relations():
    source = PhotoLibraryTimelineSource(source_paths=["/photos"])
    meta = await source.extract_metadata(_session_item())

    entity_types = {entity["entity_type"] for entity in meta.entities}
    # photo-library 87910b7: entity hints use host-valid ontology types — the
    # geocoded entity is "place" (in ENTITY_TYPE_REGISTRY), not "location".
    assert entity_types == {"hardware", "place"}
    assert meta.tags == ["photo_library", "session", "geo", "Tokyo Tower", "东京"]
    predicates = {candidate["predicate"] for candidate in meta.relation_candidates}
    # Same 87910b7 alignment: OWNS is the host-valid predicate.
    assert predicates == {"OWNS", "VISITED"}


@pytest.mark.asyncio
async def test_extract_metadata_for_minimal_session():
    source = PhotoLibraryTimelineSource(source_paths=["/photos"])
    meta = await source.extract_metadata(
        _session_item(
            device_name="",
            device_slug="",
            location_name="",
            latitude=None,
            longitude=None,
            geo_cell="nogps",
        )
    )

    assert meta.entities == []
    assert meta.tags == ["photo_library", "session"]
    assert meta.relation_candidates == []


@pytest.mark.asyncio
async def test_l2_batch_policy_groups_sessions_by_month():
    source = PhotoLibraryTimelineSource(source_paths=["/photos"])
    output = await source.build_output(_session_item(first_capture_ts=1710000000.0, last_capture_ts=1710003600.0))

    policy = source.l2_batch_policy(output)

    assert policy is not None
    assert policy.owner == "photo_library:202403"
    assert policy.catch_up_owner == "photo_library:catchup"


@pytest.mark.asyncio
async def test_collect_items_returns_settled_sessions(tmp_path: Path):
    photos_dir = tmp_path / "photos"
    photos_dir.mkdir()
    photo = photos_dir / "test.jpg"
    photo.write_bytes(b"\xff" * 100)

    reader = _FakeReader(items=[_raw_photo(str(photo))])
    source = PhotoLibraryTimelineSource(source_paths=[str(photos_dir)], reader=reader, analysis_features=[])

    ctx = SourceSyncContext(
        source_type="photo_library",
        manual=False,
        last_cursor=None,
        last_success_at=0.0,
        limit=100,
        runtime_paths=MagicMock(),
        plugin_settings={
            "sources": {
                "photo_library": {
                    "source_paths": [str(photos_dir)],
                    "analysis_features": [],
                }
            }
        },
    )
    result = await source.collect_items(ctx)

    assert len(result.items) == 1
    assert result.items[0]["photo_count"] == 1
    assert result.items[0]["device_name"] == "Canon EOS R5"
    assert result.stats["count"] == 1
    assert result.next_cursor == "1710000000.0"


@pytest.mark.asyncio
async def test_collect_items_requires_source_paths():
    source = PhotoLibraryTimelineSource()
    ctx = SourceSyncContext(
        source_type="photo_library",
        manual=False,
        last_cursor=None,
        last_success_at=0.0,
        limit=100,
        runtime_paths=MagicMock(),
        plugin_settings={},
    )

    result = await source.collect_items(ctx)

    assert result.items == []
    assert result.stats["error"] == "source_paths not configured"


@pytest.mark.asyncio
async def test_collect_items_uses_cursor_for_incremental_sync(tmp_path: Path):
    photos_dir = tmp_path / "photos"
    photos_dir.mkdir()
    old_photo = photos_dir / "old.jpg"
    new_photo = photos_dir / "new.jpg"
    old_photo.write_bytes(b"\xff" * 50)
    new_photo.write_bytes(b"\x00" * 50)

    reader = _FakeReader(
        items=[
            _raw_photo(str(old_photo), asset_local_id="old1", file_hash="old1", modified_at=1000.0, capture_timestamp=1000.0),
            _raw_photo(str(new_photo), asset_local_id="new1", file_hash="new1", modified_at=2000.0, capture_timestamp=2000.0),
        ]
    )
    source = PhotoLibraryTimelineSource(source_paths=[str(photos_dir)], reader=reader, analysis_features=[])

    ctx = SourceSyncContext(
        source_type="photo_library",
        manual=False,
        last_cursor="1500.0",
        last_success_at=1500.0,
        limit=100,
        runtime_paths=MagicMock(),
        plugin_settings={
            "sources": {
                "photo_library": {
                    "source_paths": [str(photos_dir)],
                    "analysis_features": [],
                }
            }
        },
    )
    result = await source.collect_items(ctx)

    assert len(result.items) == 1
    assert result.items[0]["max_modified_at"] == 2000.0
    assert result.stats["photos_seen"] == 1
    assert result.next_cursor == "2000.0"


@pytest.mark.asyncio
async def test_insight_pipeline_enforces_source_edge_whitelist():
    source = PhotoLibraryTimelineSource(source_paths=["/tmp/photos"])
    source_item = _session_item()

    output = await source.build_output(source_item)
    metadata = await source.extract_metadata(source_item)
    projection = build_source_projection(source, output)
    event = build_source_timeline_event("evt_photo_whitelist_1", output, projection, metadata)

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
    persisted = await pipeline.process_event(event, manual_candidates, ["LIKES", "FREEFORM"])

    assert len(persisted) == 1
    assert persisted[0]["predicate"] == "LIKES"
    assert memory.edges[0]["predicate"] == "LIKES"
    assert memory.edges[0]["evidence_event_ids"] == ["evt_photo_whitelist_1"]


@pytest.mark.asyncio
async def test_collect_items_multi_path_keeps_distinct_sessions(tmp_path: Path):
    dir_a = tmp_path / "photos_a"
    dir_b = tmp_path / "photos_b"
    dir_a.mkdir()
    dir_b.mkdir()
    photo_a = dir_a / "a.jpg"
    photo_b = dir_b / "b.jpg"
    photo_a.write_bytes(b"\xff" * 50)
    photo_b.write_bytes(b"\xff" * 50)

    items_a = [
        _raw_photo(
            str(photo_a),
            asset_local_id="ha",
            file_hash="ha",
            modified_at=1710000000.0,
            capture_timestamp=1710000000.0,
            camera_make="Canon",
            camera_model="EOS R5",
        )
    ]
    items_b = [
        _raw_photo(
            str(photo_b),
            asset_local_id="hb",
            file_hash="hb",
            modified_at=1710007200.0,
            capture_timestamp=1710007200.0,
            camera_make="Sony",
            camera_model="A7R V",
        )
    ]

    class _MultiPathReader:
        def scan_directory(self, source_path, *, limit=500, min_modified_at=0.0, exclude_patterns=None, analysis_features=None):
            if source_path == str(dir_a):
                return ScanResult(items=items_a, total_scanned=1)
            if source_path == str(dir_b):
                return ScanResult(items=items_b, total_scanned=1)
            return ScanResult()

    source = PhotoLibraryTimelineSource(
        source_paths=[str(dir_a), str(dir_b)],
        reader=_MultiPathReader(),
        analysis_features=[],
    )
    ctx = SourceSyncContext(
        source_type="photo_library",
        manual=False,
        last_cursor=None,
        last_success_at=0.0,
        limit=100,
        runtime_paths=MagicMock(),
        plugin_settings={
            "sources": {
                "photo_library": {
                    "source_paths": [str(dir_a), str(dir_b)],
                    "analysis_features": [],
                }
            }
        },
    )
    result = await source.collect_items(ctx)

    assert len(result.items) == 2
    assert {item["device_name"] for item in result.items} == {"Canon EOS R5", "Sony A7R V"}


@pytest.mark.asyncio
async def test_collect_items_exclude_patterns_passed_to_reader(tmp_path: Path):
    photos = tmp_path / "photos"
    photos.mkdir()
    (photos / "img.jpg").write_bytes(b"\xff" * 50)

    captured_kwargs = {}

    class _CapturingReader:
        def scan_directory(self, source_path, **kwargs):
            captured_kwargs.update(kwargs)
            return ScanResult(items=[], total_scanned=0)

    source = PhotoLibraryTimelineSource(
        source_paths=[str(photos)],
        reader=_CapturingReader(),
        analysis_features=[],
    )
    ctx = SourceSyncContext(
        source_type="photo_library",
        manual=False,
        last_cursor=None,
        last_success_at=0.0,
        limit=100,
        runtime_paths=MagicMock(),
        plugin_settings={
            "sources": {
                "photo_library": {
                    "source_paths": [str(photos)],
                    "exclude_patterns": ["thumbnails", ".cache"],
                    "analysis_features": [],
                }
            }
        },
    )

    await source.collect_items(ctx)

    assert captured_kwargs.get("exclude_patterns") == ["thumbnails", ".cache"]
