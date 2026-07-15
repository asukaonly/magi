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
from magi.memory.structured_recall.generic import expand_generic_structured_recall


def _migrated_l1_db_path(tmp_path):
    from magi.db.runner import MIGRATION_TARGETS, run_upgrade_head
    from magi.utils.runtime import RuntimePaths

    runtime_paths = RuntimePaths(base_dir=tmp_path / "runtime")
    l1_target = next(target for target in MIGRATION_TARGETS if target.name == "l1")

    run_upgrade_head(runtime_paths, targets=(l1_target,))
    return runtime_paths.l1_memory_db_path


def _event(
    event_id: str,
    *,
    source: str,
    content: str,
    timestamp: float,
    metadata_json: dict,
) -> MemoryEvent:
    return MemoryEvent(
        event_id=event_id,
        correlation_id=f"corr-{event_id}",
        timestamp=timestamp,
        created_at=timestamp,
        event_type="ExternalActivity",
        source=source,
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
        metadata_json=metadata_json,
    )


@pytest.mark.asyncio
async def test_browser_structured_recall_expands_seed_to_complete_visit_count(tmp_path) -> None:
    db_path = _migrated_l1_db_path(tmp_path)
    store = L1EventStore(db_path=str(db_path), vector_enabled=False)
    await store.initialize()

    seed = _event(
        "evt-browser-1",
        source="browser_history",
        content="Visited Example docs.",
        timestamp=1_710_000_000.0,
        metadata_json={
            "source_facets": [
                {"name": "browser.domain", "text": "example.com"},
                {"name": "browser.title", "text": "Example docs"},
                {"name": "browser.visit_count", "numeric": 3},
            ]
        },
    )
    related = _event(
        "evt-browser-2",
        source="safari_history",
        content="Visited Example pricing.",
        timestamp=1_711_000_000.0,
        metadata_json={
            "source_facets": [
                {"name": "browser.domain", "text": "example.com"},
                {"name": "browser.title", "text": "Example pricing"},
                {"name": "browser.visit_count", "numeric": 2},
            ]
        },
    )
    other = _event(
        "evt-browser-3",
        source="browser_history",
        content="Visited Other docs.",
        timestamp=1_712_000_000.0,
        metadata_json={
            "source_facets": [
                {"name": "browser.domain", "text": "other.test"},
                {"name": "browser.visit_count", "numeric": 5},
            ]
        },
    )
    await store.store(seed)
    await store.store(related)
    await store.store(other)

    result = await expand_generic_structured_recall(
        l1_store=store,
        request=RetrievalQuery(query="example.com 浏览过几次", query_mode="cross_session"),
        recall_shape=classify_recall_shape("example.com 浏览过几次"),
        payload=RetrievalPayload(l1_events=[seed.to_dict()]),
    )

    assert result is not None
    assert result["domain"] == "browser"
    assert result["coverage"]["can_claim_total"] is True
    assert result["summary"]["event_count"] == 2
    assert result["summary"]["metric_total"] == 5
    assert {item["event_id"] for item in result["items"]} == {"evt-browser-1", "evt-browser-2"}


@pytest.mark.asyncio
async def test_music_structured_recall_expands_artist_seed_to_complete_play_count(tmp_path) -> None:
    db_path = _migrated_l1_db_path(tmp_path)
    store = L1EventStore(db_path=str(db_path), vector_enabled=False)
    await store.initialize()

    seed = _event(
        "evt-music-1",
        source="netease_music",
        content="Listened to Song A by Artist A.",
        timestamp=1_710_000_000.0,
        metadata_json={
            "source_facets": [
                {"name": "music.track", "text": "Song A"},
                {"name": "music.artist", "text": "Artist A"},
                {"name": "music.play_count", "numeric": 1},
                {"name": "music.play_duration_sec", "numeric": 180},
            ]
        },
    )
    related = _event(
        "evt-music-2",
        source="system_media",
        content="Listened to Song B by Artist A.",
        timestamp=1_711_000_000.0,
        metadata_json={
            "source_facets": [
                {"name": "music.track", "text": "Song B"},
                {"name": "music.artist", "text": "Artist A"},
                {"name": "music.play_count", "numeric": 1},
                {"name": "music.play_duration_sec", "numeric": 240},
            ]
        },
    )
    other = _event(
        "evt-music-3",
        source="netease_music",
        content="Listened to Song C by Artist B.",
        timestamp=1_712_000_000.0,
        metadata_json={
            "source_facets": [
                {"name": "music.track", "text": "Song C"},
                {"name": "music.artist", "text": "Artist B"},
                {"name": "music.play_count", "numeric": 1},
            ]
        },
    )
    await store.store(seed)
    await store.store(related)
    await store.store(other)

    result = await expand_generic_structured_recall(
        l1_store=store,
        request=RetrievalQuery(query="Artist A 听过几次", query_mode="cross_session"),
        recall_shape=classify_recall_shape("Artist A 听过几次"),
        payload=RetrievalPayload(l1_events=[seed.to_dict(), related.to_dict()]),
    )

    assert result is not None
    assert result["domain"] == "music"
    assert result["coverage"]["can_claim_total"] is True
    assert result["summary"]["event_count"] == 2
    assert result["summary"]["metric_total"] == 2
    assert result["summary"]["duration_total_sec"] == 420
    assert {item["event_id"] for item in result["items"]} == {"evt-music-1", "evt-music-2"}


@pytest.mark.asyncio
async def test_service_attaches_generic_structured_recall(tmp_path) -> None:
    db_path = _migrated_l1_db_path(tmp_path)
    store = L1EventStore(db_path=str(db_path), vector_enabled=False)
    await store.initialize()

    seed = _event(
        "evt-browser-1",
        source="browser_history",
        content="Visited Example docs.",
        timestamp=1_710_000_000.0,
        metadata_json={
            "source_facets": [
                {"name": "browser.domain", "text": "example.com"},
                {"name": "browser.visit_count", "numeric": 3},
            ]
        },
    )
    related = _event(
        "evt-browser-2",
        source="browser_history",
        content="Visited Example pricing.",
        timestamp=1_711_000_000.0,
        metadata_json={
            "source_facets": [
                {"name": "browser.domain", "text": "example.com"},
                {"name": "browser.visit_count", "numeric": 2},
            ]
        },
    )
    await store.store(seed)
    await store.store(related)

    svc = HybridRetrievalService.__new__(HybridRetrievalService)
    svc._memory = SimpleNamespace(
        l1=store,
        l2=SimpleNamespace(
            db_path=str(db_path),
            active_correction_evidence_event_ids=AsyncMock(return_value=set()),
        ),
    )

    payload = await svc._apply_structured_recall(
        request=RetrievalQuery(query="example.com 浏览过几次", query_mode="cross_session"),
        recall_shape=classify_recall_shape("example.com 浏览过几次"),
        payload=RetrievalPayload(l1_events=[seed.to_dict()]),
    )

    assert payload.trace["structured_recall"] == "browser"
    assert payload.structured_results[0]["summary"]["metric_total"] == 5


@pytest.mark.asyncio
async def test_service_structured_recall_excludes_corrected_l1_events(tmp_path) -> None:
    db_path = _migrated_l1_db_path(tmp_path)
    store = L1EventStore(db_path=str(db_path), vector_enabled=False)
    await store.initialize()
    corrected = _event(
        "evt-browser-corrected",
        source="browser_history",
        content="Visited Example docs.",
        timestamp=1_710_000_000.0,
        metadata_json={
            "source_facets": [
                {"name": "browser.domain", "text": "example.com"},
                {"name": "browser.visit_count", "numeric": 3},
            ]
        },
    )
    await store.store(corrected)
    svc = HybridRetrievalService.__new__(HybridRetrievalService)
    svc._memory = SimpleNamespace(
        l1=store,
        l2=SimpleNamespace(
            db_path=str(db_path),
            active_correction_evidence_event_ids=AsyncMock(
                return_value={"evt-browser-corrected"}
            ),
        ),
    )

    payload = await svc._apply_structured_recall(
        request=RetrievalQuery(
            query="example.com 浏览过几次",
            query_mode="cross_session",
        ),
        recall_shape=classify_recall_shape("example.com 浏览过几次"),
        payload=RetrievalPayload(l1_events=[]),
    )

    assert payload.structured_results == []
    assert payload.trace["structured_recall"] == "miss"
    assert payload.trace["structured_recall_correction_governance"] == "applied"
    assert payload.trace["structured_recall_correction_governance_dropped_count"] == 1
