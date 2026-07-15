from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from magi.memory.event_contracts import (
    IngestTarget,
    MemoryDomain,
    MemoryEvent,
    RetentionClass,
    TomDepth,
)
from magi.memory.hybrid_retrieval.models import RetrievalPayload, RetrievalQuery
from magi.memory.hybrid_retrieval.recall_shape import classify_recall_shape
from magi.memory.hybrid_retrieval.service import HybridRetrievalService
from magi.memory.l1.event_store import L1EventStore
from magi.memory.structured_recall.photo import expand_photo_structured_recall


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
                    "Hangzhou, Zhejiang, China",
                    "Tiankongzhicheng, Hangzhou, Zhejiang, China",
                    "Sky Tengji, Wuchang Subway Station Entrance & Exit B, Hangzhou",
                ]
            },
        },
    )


@pytest.mark.asyncio
async def test_photo_structured_recall_expands_seed_to_complete_stats(tmp_path) -> None:
    db_path = _migrated_l1_db_path(tmp_path)
    store = L1EventStore(db_path=str(db_path), vector_enabled=False)
    await store.initialize()

    seed_event = _photo_event(
        "evt-photo-1",
        "照片记录：用 iPhone 13 Pro Max 在 Tiankongzhicheng 拍摄了 3 张照片。",
        timestamp=1_702_000_000.0,
    )
    related_event = _photo_event(
        "evt-photo-2",
        "照片记录：用 iPhone 13 Pro Max 在 Sky Tengji 拍摄了 2 张照片。",
        timestamp=1_706_000_000.0,
    )
    other_event = _photo_event(
        "evt-photo-3",
        "照片记录：用 iPhone 13 Pro Max 在 West Lake 拍摄了 4 张照片。",
        timestamp=1_708_000_000.0,
    )
    other_event.metadata_json["representative_photos"][0]["location_name"] = "West Lake, Hangzhou, Zhejiang, China"
    other_event.metadata_json["representative_photos"][0]["apple_photos_place_address"] = "West Lake, Hangzhou"
    other_event.metadata_json["projection"]["retrieval_terms"] = [
        "photo_library",
        "session",
        "geo",
        "Hangzhou, Zhejiang, China",
        "West Lake, Hangzhou",
    ]
    seed_event.metadata_json["representative_photos"].append(
        {
            "asset_local_id": "apple-photos:broad-seed",
            "location_name": "Hangzhou, Zhejiang, China",
            "apple_photos_place_address": "Hangzhou, Zhejiang China",
        }
    )
    other_event.metadata_json["representative_photos"].append(
        {
            "asset_local_id": "apple-photos:broad-other",
            "location_name": "Hangzhou, Zhejiang, China",
            "apple_photos_place_address": "Hangzhou, Zhejiang China",
        }
    )

    await store.store(seed_event)
    await store.store(related_event)
    await store.store(other_event)

    result = await expand_photo_structured_recall(
        l1_store=store,
        request=RetrievalQuery(query="我在天空之城拍过几次照片", query_mode="cross_session"),
        recall_shape=classify_recall_shape("我在天空之城拍过几次照片"),
        payload=RetrievalPayload(l1_events=[seed_event.to_dict()]),
    )

    assert result is not None
    assert result["coverage"]["kind"] == "exhaustive"
    assert result["coverage"]["can_claim_total"] is True
    assert result["summary"]["session_count"] == 2
    assert result["summary"]["photo_count"] == 5
    assert {item["event_id"] for item in result["items"]} == {"evt-photo-1", "evt-photo-2"}


@pytest.mark.asyncio
async def test_photo_structured_recall_uses_query_location_without_seed(tmp_path) -> None:
    db_path = _migrated_l1_db_path(tmp_path)
    store = L1EventStore(db_path=str(db_path), vector_enabled=False)
    await store.initialize()

    tokyo_event = _photo_event(
        "evt-photo-tokyo-1",
        "照片 拍摄 2025-07-14 周一上午用 Apple iPhone 16 Pro Max 在Honshu, Taito, Tokyo, Japan拍摄了3 张照片（08:22–09:00）",
        timestamp=1_752_452_577.0,
    )
    tokyo_event.metadata_json["representative_photos"][0]["location_name"] = (
        "Honshu, Taito, Tokyo, Japan"
    )
    tokyo_event.metadata_json["representative_photos"][0]["apple_photos_place_address"] = (
        "Senso-ji, Taito, Tokyo, Japan"
    )
    tokyo_event.metadata_json["projection"]["retrieval_terms"] = [
        "photo_library",
        "session",
        "geo",
        "日本",
        "东京",
        "Honshu, Taito, Tokyo, Japan",
        "Senso-ji, Taito, Tokyo, Japan",
    ]

    other_event = _photo_event(
        "evt-photo-hangzhou-1",
        "照片 拍摄 2024-02-06 周二下午用 Apple iPhone 13 Pro Max 在Tiankongzhicheng, Hangzhou, Zhejiang, China拍摄了2 张照片",
        timestamp=1_707_200_000.0,
    )

    await store.store(tokyo_event)
    await store.store(other_event)

    result = await expand_photo_structured_recall(
        l1_store=store,
        request=RetrievalQuery(
            query="我在东京拍了什么照片",
            query_mode="experience_recall",
            user_id="user-1",
        ),
        recall_shape=classify_recall_shape("我在东京拍了什么照片"),
        payload=RetrievalPayload(l1_events=[]),
    )

    assert result is not None
    assert result["coverage"]["can_claim_total"] is True
    assert result["summary"]["session_count"] == 1
    assert result["summary"]["photo_count"] == 3
    assert [item["event_id"] for item in result["items"]] == ["evt-photo-tokyo-1"]


@pytest.mark.asyncio
async def test_service_attaches_photo_structured_recall(tmp_path) -> None:
    db_path = _migrated_l1_db_path(tmp_path)
    store = L1EventStore(db_path=str(db_path), vector_enabled=False)
    await store.initialize()

    seed_event = _photo_event(
        "evt-photo-1",
        "照片记录：用 iPhone 13 Pro Max 在 Tiankongzhicheng 拍摄了 3 张照片。",
        timestamp=1_702_000_000.0,
    )
    related_event = _photo_event(
        "evt-photo-2",
        "照片记录：用 iPhone 13 Pro Max 在 Tiankongzhicheng 拍摄了 2 张照片。",
        timestamp=1_706_000_000.0,
    )
    await store.store(seed_event)
    await store.store(related_event)

    svc = HybridRetrievalService.__new__(HybridRetrievalService)
    svc._memory = SimpleNamespace(
        l1=store,
        l2=SimpleNamespace(
            db_path=str(db_path),
            active_correction_evidence_event_ids=AsyncMock(return_value=set()),
        ),
    )

    payload = await svc._apply_structured_recall(
        request=RetrievalQuery(query="我在天空之城拍过几次照片", query_mode="cross_session"),
        recall_shape=classify_recall_shape("我在天空之城拍过几次照片"),
        payload=RetrievalPayload(l1_events=[seed_event.to_dict()]),
    )

    assert payload.trace["structured_recall"] == "photo"
    assert payload.structured_results[0]["coverage"]["can_claim_total"] is True
    assert payload.structured_results[0]["summary"]["photo_count"] == 5
