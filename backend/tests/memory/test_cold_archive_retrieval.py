"""End-to-end tests for default cold-archive retention and seamless retrieval."""

from __future__ import annotations

import time

import pytest

from magi.config.memory_models import MemoryHistoryBehavior, MemorySettings
from magi.memory.event_contracts import (
    IngestTarget,
    MemoryDomain,
    MemoryEvent,
    RetentionClass,
    TomDepth,
)
from magi.memory.hybrid_retrieval.models import RetrievalConfig, RetrievalQuery
from magi.memory.hybrid_retrieval.service import HybridRetrievalService
from magi.memory.l3.models import L3Candidate
from magi.memory.unified_store import MemoryStoreTuning
from magi.timeline.viewport_builder import TimelineViewportBuilder
from _shared.memory_stores import build_memory_store


def test_default_memory_settings_preserve_history_via_archive():
    settings = MemorySettings()
    assert settings.history_behavior == MemoryHistoryBehavior.ARCHIVE
    assert settings.l1.retention_days == 90
    assert settings.l3.retention_days == 365


@pytest.mark.asyncio
async def test_archived_100_day_event_is_retrievable_in_timeline_and_hybrid_and_respects_forget(
    tmp_path,
):
    store = build_memory_store(
        persist_dir=str(tmp_path / "memory"),
        l1_db_path=str(tmp_path / "l1.db"),
        memory_db_path=str(tmp_path / "memory.db"),
        archive_dir_path=str(tmp_path / "archive"),
        enable_l0=False,
        enable_l1=True,
        enable_l2=True,
        enable_l3=True,
        enable_l4=False,
        tuning=MemoryStoreTuning(
            enable_l1_vectors=False,
            enable_l2_vectors=False,
            enable_l3_vectors=False,
            async_embeddings=False,
        ),
    )
    await store.initialize()
    try:
        old_ts = time.time() - (100 * 86400)
        event_id = "evt-music-100d"
        await store.l1.store(
            MemoryEvent(
                event_id=event_id,
                correlation_id="corr-100d",
                timestamp=old_ts,
                created_at=old_ts,
                event_type="SensorEvent",
                source="netease_music",
                source_item_id="track-nocturne-100d",
                memory_domain=MemoryDomain.EXTERNAL_ACTIVITY,
                ingest_target=IngestTarget.L1_ONLY,
                cognition_eligible=True,
                tom_depth=TomDepth.NONE,
                retention_class=RetentionClass.COMPRESSIBLE,
                session_id=None,
                turn_id=None,
                user_id="local_user",
                task_id=None,
                content="Listened to Nocturne in E-flat major at the riverside cafe",
                author_type="external",
                content_type="observation",
                importance_score=0.6,
                level=20,
                idempotency_key="netease_music:track-nocturne-100d",
            )
        )

        await store.l3.upsert_candidate(
            candidate=L3Candidate(
                summary_type="temporal",
                summary_category="day",
                content="Relaxing evening listening to Nocturne at the riverside cafe.",
                source_event_ids=[event_id],
            ),
            summary_overrides={
                "period_start": old_ts - 600,
                "period_end": old_ts + 600,
            },
        )

        # Run L1 cleanup with default history_behavior='archive' and 90-day retention.
        stats = await store.cleanup_l1_data()
        assert stats["archived_events"] == 1
        assert stats["deleted_events"] == 1
        assert await store.l1.get_active_event(event_id) is None

        # 1. Timeline viewport for that 100-day-old day recovers the archived event.
        builder = TimelineViewportBuilder(
            l1_store=store.l1,
            l2_store=store.l2,
            l3_store=store.l3,
            archive_search=store.archives,
        )
        viewport = await builder.build_viewport(
            scale="hour",
            start=old_ts - 1800,
            end=old_ts + 1800,
            locale="en",
        )
        raw_ids = [ev["event_id"] for ev in viewport["raw_events"]]
        assert event_id in raw_ids

        # 2. HybridRetrievalService recovers the archived event seamlessly.
        retrieval = HybridRetrievalService(
            store,
            config=RetrievalConfig(
                intent_decider_llm_enabled=False,
                query_expansion_enabled=False,
            ),
        )
        payload = await retrieval.query(
            RetrievalQuery(
                query="Nocturne riverside cafe",
                user_id="local_user",
                time_range={"start": old_ts - 3600, "end": old_ts + 3600},
                limit=10,
            )
        )
        assert any(
            item["event_id"] == event_id and item.get("archived") is True
            for item in payload.l1_events
        )

        # 3. Forgetting the archived event removes it from both Timeline and HybridRetrieval.
        await store.forget_source_event(event_id)

        viewport_after = await builder.build_viewport(
            scale="hour",
            start=old_ts - 1800,
            end=old_ts + 1800,
            locale="en",
        )
        assert all(ev["event_id"] != event_id for ev in viewport_after["raw_events"])

        payload_after = await retrieval.query(
            RetrievalQuery(
                query="Nocturne riverside cafe",
                user_id="local_user",
                time_range={"start": old_ts - 3600, "end": old_ts + 3600},
                limit=10,
            )
        )
        assert all(item["event_id"] != event_id for item in payload_after.l1_events)
    finally:
        await store.shutdown()
