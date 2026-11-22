"""Tests for Timeline cross-viewport hybrid search, historical window SQL filtering, and O(1) assets."""

from __future__ import annotations

import json
import time
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from _shared.memory_stores import build_memory_store
from magi.memory.event_contracts import (
    IngestTarget,
    MemoryDomain,
    MemoryEvent,
    RetentionClass,
    TomDepth,
)
from magi.memory.l3.models import L3Candidate
from magi.memory.unified_store import MemoryStoreTuning
from magi.timeline.context_bundle_builder import TimelineContextBundleBuilder
from magi.timeline.service import TimelineService
from magi.timeline.viewport_builder import TimelineViewportBuilder


def _make_event(
    *,
    event_id: str,
    timestamp: float,
    source: str,
    content: str,
    source_item_id: str | None = None,
    metadata_json: dict | None = None,
) -> MemoryEvent:
    return MemoryEvent(
        event_id=event_id,
        correlation_id=f"corr-{event_id}",
        timestamp=timestamp,
        created_at=timestamp,
        event_type="SensorEvent",
        source=source,
        source_item_id=source_item_id or event_id,
        memory_domain=MemoryDomain.EXTERNAL_ACTIVITY,
        ingest_target=IngestTarget.L1_ONLY,
        cognition_eligible=True,
        tom_depth=TomDepth.NONE,
        retention_class=RetentionClass.COMPRESSIBLE,
        session_id=None,
        turn_id=None,
        user_id="local_user",
        task_id=None,
        content=content,
        author_type="external",
        content_type="observation",
        importance_score=0.7,
        level=20,
        idempotency_key=f"{source}:{source_item_id or event_id}",
        metadata_json=metadata_json or {},
    )


@pytest.mark.asyncio
async def test_cross_viewport_hybrid_search_and_five_month_old_day_state_bands(
    tmp_path: Path,
) -> None:
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
    await store.initialize(start_workers=False)
    try:
        now = time.time()
        day = 86400.0

        # Seed events across yesterday, 4 days ago, and 3 months ago
        evt_yesterday_git = _make_event(
            event_id="evt-yesterday-git",
            timestamp=now - 1.2 * day,
            source="git_activity",
            content="git commit: refactor timeline query interpreter",
        )
        evt_last_week_music = _make_event(
            event_id="evt-last-week-music",
            timestamp=now - 4.0 * day,
            source="netease_music",
            content="网易云音乐 播放了《夜曲》 Nocturne",
        )
        evt_three_months_cafe = _make_event(
            event_id="evt-3mo-cafe",
            timestamp=now - 90.0 * day,
            source="manual_journal",
            content="下午在河边咖啡馆看书，喝了一杯手冲美式",
        )
        for ev in (evt_yesterday_git, evt_last_week_music, evt_three_months_cafe):
            await store.l1.store(ev)

        # Seed a 5-month-old day summary PLUS 220 newer summaries (exceeding the old global-200 cap).
        old_day_ts = now - 150.0 * day
        old_day_event = _make_event(
            event_id="evt-5mo-day",
            timestamp=old_day_ts,
            source="chrome_history",
            content="Read notes about autumn travel",
        )
        await store.l1.store(old_day_event)
        await store.l3.upsert_candidate(
            candidate=L3Candidate(
                summary_type="temporal",
                summary_category="day",
                content="Calm five-month-old autumn day planning a trip.",
                source_event_ids=[old_day_event.event_id],
            ),
            summary_overrides={
                "period_start": old_day_ts - 3600,
                "period_end": old_day_ts + 3600,
                "sentiment_summary": {"mood_label": "warm", "stress_level": 0.2},
            },
        )
        # Insert 215 newer summaries so any unfiltered LIMIT 200 query would drop the 5-month-old one.
        for idx in range(215):
            ts = now - (idx * 0.5 * day)
            await store.l3.upsert_candidate(
                candidate=L3Candidate(
                    summary_type="temporal",
                    summary_category="day",
                    content=f"Newer daily summary #{idx}",
                    source_event_ids=[evt_yesterday_git.event_id],
                ),
                summary_overrides={
                    "period_start": ts - 1800,
                    "period_end": ts + 1800,
                },
            )

        builder = TimelineViewportBuilder(
            l1_store=store.l1,
            l2_store=store.l2,
            l3_store=store.l3,
            archive_search=store.archives,
        )

        # Anchor viewport on TODAY only ([now - day, now])
        today_start, today_end = now - day, now

        # 1. Search "上周听的歌" jumps outside today's viewport and finds 4-day-old NetEase event
        music_vp = await builder.build_viewport(
            scale="hour",
            start=today_start,
            end=today_end,
            query="上周听的歌",
            locale="zh-CN",
        )
        assert any(ev["event_id"] == "evt-last-week-music" for ev in music_vp["raw_events"])

        # 2. Search "三个月前咖啡馆看书" jumps ~90d back and hits Chinese event via jieba FTS5
        cafe_vp = await builder.build_viewport(
            scale="hour",
            start=today_start,
            end=today_end,
            query="三个月前咖啡馆看书",
            locale="zh-CN",
        )
        assert any(ev["event_id"] == "evt-3mo-cafe" for ev in cafe_vp["raw_events"])

        # 3. Search "yesterday git commit" jumps to yesterday and finds git commit
        git_vp = await builder.build_viewport(
            scale="hour",
            start=today_start,
            end=today_end,
            query="yesterday git commit",
            locale="en",
        )
        assert any(ev["event_id"] == "evt-yesterday-git" for ev in git_vp["raw_events"])

        # 4. Opening the 5-month-old day renders its L3 summary and state band despite 215 newer summaries
        old_day_vp = await builder.build_viewport(
            scale="day",
            start=old_day_ts - 43200,
            end=old_day_ts + 43200,
            locale="en",
        )
        assert "five-month-old autumn day" in old_day_vp["overview"]["summary"]
        assert old_day_vp["state_bands"]
        assert old_day_vp["summary"]["events_truncated"] is False
    finally:
        await store.shutdown()


@pytest.mark.asyncio
async def test_photo_library_asset_uses_single_indexed_lookup_and_async_io(tmp_path: Path) -> None:
    photo_file = tmp_path / "sunset.jpg"
    photo_file.write_bytes(b"\xff\xd8\xff\xe0fake-jpeg-bytes")

    asset_id = "PH-ASSET-9988"
    photo_event = {
        "event_id": "evt-photo-1",
        "source": "photo_library",
        "source_item_id": asset_id,
        "metadata_json": {
            "representative_photos": [
                {
                    "asset_local_id": asset_id,
                    "path": str(photo_file),
                    "mime_type": "image/jpeg",
                }
            ]
        },
    }

    fake_l1 = SimpleNamespace(
        find_event_by_photo_asset_id=AsyncMock(return_value=photo_event),
        query_events=AsyncMock(side_effect=AssertionError("must not scan 5000 rows")),
    )
    service = TimelineService(
        SimpleNamespace(l1=fake_l1, l2=None, l3=None, l4=None),
    )

    served = await service.serve_asset(asset_ref=f"photo-library://{asset_id}")
    assert served is not None
    data, content_type = served
    assert data == b"\xff\xd8\xff\xe0fake-jpeg-bytes"
    assert content_type == "image/jpeg"
    fake_l1.find_event_by_photo_asset_id.assert_awaited_once()
    fake_l1.query_events.assert_not_awaited()


@pytest.mark.asyncio
async def test_context_bundle_builder_batches_l1_and_l2_edge_lookups() -> None:
    fake_l1 = SimpleNamespace(
        fetch_events=AsyncMock(
            return_value=[
                {"event_id": "e1", "timestamp": 100.0, "source": "chat", "content": "one"},
                {"event_id": "e2", "timestamp": 110.0, "source": "chat", "content": "two"},
                {"event_id": "e3", "timestamp": 120.0, "source": "chat", "content": "three"},
            ]
        ),
        get_user_visible_event=AsyncMock(side_effect=AssertionError("must batch instead of N+1")),
    )
    fake_l2 = SimpleNamespace(
        list_tom_assertions=AsyncMock(return_value=[]),
        find_edges_by_event_ids=AsyncMock(
            return_value=[
                {
                    "triple_id": "t1",
                    "subject_id": "user:self",
                    "predicate": "LIKES",
                    "object_id": "topic:jazz",
                    "evidence_event_ids": ["e1", "e2"],
                }
            ]
        ),
        find_edges_by_event_id=AsyncMock(side_effect=AssertionError("must batch instead of N+1")),
    )
    fake_l4 = SimpleNamespace(
        get_all_skills=AsyncMock(side_effect=AssertionError("must not attach unrelated global L4 skills")),
    )
    builder = TimelineContextBundleBuilder(
        l1_store=fake_l1,
        l2_store=fake_l2,
        l3_store=None,
        l4_store=fake_l4,
    )
    bundle = await builder.build(
        anchor={
            "anchor_id": "cluster:1",
            "anchor_type": "cluster",
            "title": "Evening",
            "summary": "Evening activity",
            "source_event_ids": ["e1", "e2", "e3"],
        }
    )
    assert len(bundle["l1_events"]) == 3
    assert len(bundle["l2_state_evidence"]) == 1
    assert bundle["l4_related_procedures"] == []
    fake_l1.fetch_events.assert_awaited_once()
    fake_l2.find_edges_by_event_ids.assert_awaited_once_with(["e1", "e2", "e3"])
