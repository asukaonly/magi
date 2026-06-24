import pytest

from magi.memory.event_contracts import (
    IngestTarget,
    MemoryDomain,
    MemoryEvent,
    RetentionClass,
    TomDepth,
)
from magi.memory.l1.event_store import L1EventStore
from magi.memory.l1.source_facets import normalize_facet_text


def _migrated_l1_db_path(tmp_path):
    from magi.db.runner import MIGRATION_TARGETS, run_upgrade_head
    from magi.utils.runtime import RuntimePaths

    runtime_paths = RuntimePaths(base_dir=tmp_path / "runtime")
    l1_target = next(target for target in MIGRATION_TARGETS if target.name == "l1")

    run_upgrade_head(runtime_paths, targets=(l1_target,))
    return runtime_paths.l1_memory_db_path


def _photo_event(event_id: str, content: str, *, timestamp: float) -> MemoryEvent:
    return MemoryEvent(
        event_id=event_id,
        correlation_id=f"corr-{event_id}",
        timestamp=timestamp,
        created_at=timestamp,
        event_type="PhotoLibrarySession",
        source="photo_library_apple_photos",
        source_item_id=event_id,
        memory_domain=MemoryDomain.EXTERNAL_ACTIVITY,
        ingest_target=IngestTarget.L1_ONLY,
        cognition_eligible=True,
        tom_depth=TomDepth.NONE,
        retention_class=RetentionClass.PERMANENT,
        session_id="session-1",
        turn_id=None,
        user_id="user-1",
        task_id=None,
        content=content,
        author_type="external",
        content_type="observation",
        importance_score=0.5,
        level=20,
        metadata_json={
            "source": "photo_library_apple_photos",
            "representative_photos": [
                {
                    "asset_local_id": f"apple-photos:{event_id}",
                    "location_name": "Tiankongzhicheng, Hangzhou, Zhejiang, China",
                    "apple_photos_place_address": "Sky Tengji, Wuchang Subway Station Entrance & Exit B, Hangzhou",
                    "latitude": 30.2901,
                    "longitude": 120.0402,
                }
            ],
            "projection": {
                "retrieval_terms": [
                    "photo_library",
                    "session",
                    "geo",
                    "Tiankongzhicheng, Hangzhou, Zhejiang, China",
                    "Sky Tengji, Wuchang Subway Station Entrance & Exit B, Hangzhou",
                ]
            },
        },
    )


def test_normalize_facet_text_is_stable() -> None:
    assert normalize_facet_text(" Sky  Tengji, Hangzhou ") == "sky tengji hangzhou"


@pytest.mark.asyncio
async def test_l1_source_facets_are_indexed_for_photo_events(tmp_path) -> None:
    db_path = _migrated_l1_db_path(tmp_path)
    store = L1EventStore(db_path=str(db_path), vector_enabled=False)
    await store.initialize()

    event = _photo_event(
        "evt-photo-1",
        "照片记录：用 iPhone 13 Pro Max 在 Tiankongzhicheng 拍摄了 3 张照片。",
        timestamp=1_702_000_000.0,
    )
    await store.store(event)

    facets = await store.list_source_facets(event_id="evt-photo-1")
    names = {(facet["facet_name"], facet["normalized_text_value"]) for facet in facets}

    assert ("photo.location_name", "tiankongzhicheng hangzhou zhejiang china") in names
    assert ("photo.location_alias", "sky tengji wuchang subway station entrance exit b hangzhou") in names
    assert any(facet["facet_name"] == "photo.count" and facet["numeric_value"] == 3 for facet in facets)
