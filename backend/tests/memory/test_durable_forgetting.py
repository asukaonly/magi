from __future__ import annotations

import asyncio
import json
import time
from contextlib import asynccontextmanager
from pathlib import Path
from types import SimpleNamespace

import aiosqlite
import pytest

from _shared.memory_schema import apply_memory_shared_schema
from magi.memory.event_contracts import (
    IngestTarget,
    MemoryDomain,
    MemoryEvent,
    RetentionClass,
    TomDepth,
)
from magi.memory.forgetting import DurableForgetRunner, ForgetReference, ForgetSelector
from magi.memory.forgetting.repository import ForgetOperationRepository
from magi.memory.l3.daily_mood.models import DailyMoodAggregate
from magi.memory.l3.daily_mood.store import DailyMoodAggregateStore
from magi.memory.l3.models import L3Candidate
from magi.memory.l3.storage.operations import ForgottenSummarySourceEventError
from magi.memory.l2.episodes.crud import ForgottenEpisodeTimeRangeError
from magi.memory.unified_store import MemoryStoreTuning, UnifiedMemoryStore


def _event(
    event_id: str,
    *,
    session_id: str = "session-1",
    turn_id: str = "turn-1",
    message_id: str | None = None,
    content: str = "private content",
    author_type: str = "user",
    timestamp: float = 1_720_000_000.0,
) -> MemoryEvent:
    return MemoryEvent(
        event_id=event_id,
        correlation_id=f"correlation:{event_id}",
        timestamp=timestamp,
        created_at=timestamp,
        event_type="AIResponse" if author_type == "assistant" else "UserMessage",
        source="chat",
        source_item_id=message_id,
        memory_domain=MemoryDomain.USER_AUTHORED,
        ingest_target=IngestTarget.L1_ONLY,
        cognition_eligible=True,
        tom_depth=TomDepth.NONE,
        retention_class=RetentionClass.PERMANENT,
        session_id=session_id,
        turn_id=turn_id,
        user_id="u1",
        task_id=None,
        content=content,
        author_type=author_type,
        content_type="text",
        importance_score=0.9,
        level=20,
        idempotency_key=message_id,
    )


def _build_memory(tmp_path: Path) -> UnifiedMemoryStore:
    return UnifiedMemoryStore(
        persist_dir=str(tmp_path / "memory"),
        l1_db_path=str(tmp_path / "l1.db"),
        memory_db_path=str(tmp_path / "memory.db"),
        l2_batch_flush_interval_seconds=0,
        tuning=MemoryStoreTuning(
            enable_l1_vectors=False,
            enable_l2_vectors=False,
            enable_l3_vectors=False,
            enable_l4_vectors=False,
            enable_l3_llm_summary=False,
            enable_l2_conflict_arbitration=False,
            async_embeddings=False,
        ),
    )


async def _operation_row(db_path: Path) -> aiosqlite.Row:
    async with aiosqlite.connect(db_path) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            "SELECT * FROM memory_forget_operations ORDER BY created_at DESC LIMIT 1"
        ) as cursor:
            row = await cursor.fetchone()
    assert row is not None
    return row


async def _seed_archive(
    db_path: Path,
    *,
    event_ids: list[str],
) -> None:
    async with aiosqlite.connect(db_path) as db:
        await db.executescript("""
            CREATE TABLE archived_l1_events (
                event_id TEXT PRIMARY KEY,
                payload_json TEXT NOT NULL
            );
            CREATE TABLE archived_l3_summaries (
                summary_id TEXT PRIMARY KEY,
                payload_json TEXT NOT NULL
            );
            """)
        await db.executemany(
            "INSERT INTO archived_l1_events(event_id, payload_json) VALUES (?, ?)",
            [
                (event_id, json.dumps({"event_id": event_id}))
                for event_id in [*event_ids, "event-keep"]
            ],
        )
        await db.executemany(
            "INSERT INTO archived_l3_summaries(summary_id, payload_json) VALUES (?, ?)",
            [
                (
                    "summary-direct",
                    json.dumps(
                        {"summary": {"source_event_ids": [event_ids[0]]}, "event_links": []}
                    ),
                ),
                (
                    "summary-linked",
                    json.dumps(
                        {
                            "summary": {"source_event_ids": []},
                            "event_links": [{"event_id": event_ids[-1]}],
                        }
                    ),
                ),
                (
                    "summary-keep",
                    json.dumps(
                        {"summary": {"source_event_ids": ["event-keep"]}, "event_links": []}
                    ),
                ),
            ],
        )
        await db.commit()


@pytest.mark.asyncio
async def test_operation_archive_cleanup_opens_each_archive_once_and_is_idempotent(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import magi.memory.forgetting.cleanup as cleanup_module

    await apply_memory_shared_schema(str(tmp_path / "memory.db"))
    memory = _build_memory(tmp_path)
    await memory.initialize()
    event_ids = [f"event-{index:03d}" for index in range(205)]
    archive_paths = [
        memory._archive_dir / "2026-07-01.db",
        memory._archive_dir / "2026-07-02.db",
    ]
    for archive_path in archive_paths:
        await _seed_archive(archive_path, event_ids=event_ids)

    original_connection = cleanup_module.sqlite_connection_async
    opened_paths: list[Path] = []

    @asynccontextmanager
    async def counted_connection(db_path, *args, **kwargs):  # type: ignore[no-untyped-def]
        opened_paths.append(Path(db_path))
        async with original_connection(db_path, *args, **kwargs) as db:
            yield db

    monkeypatch.setattr(cleanup_module, "sqlite_connection_async", counted_connection)
    try:
        assert (
            await memory.forget_known_source_events(
                event_ids,
                reason="test_archive_operation_cleanup",
            )
            == 0
        )
        assert opened_paths.count(Path(memory.memory_db_path)) == 1
        for archive_path in archive_paths:
            assert opened_paths.count(archive_path) == 1
            async with aiosqlite.connect(archive_path) as db:
                async with db.execute(
                    "SELECT event_id FROM archived_l1_events ORDER BY event_id"
                ) as cursor:
                    assert await cursor.fetchall() == [("event-keep",)]
                async with db.execute(
                    "SELECT summary_id FROM archived_l3_summaries ORDER BY summary_id"
                ) as cursor:
                    assert await cursor.fetchall() == [("summary-keep",)]

        operation = await _operation_row(Path(memory.memory_db_path))
        second_pass = await memory._durable_forget_runner._cleanup.cleanup_operation_archives(
            str(operation["operation_id"])
        )
        assert second_pass == {"archived_l1_events": 0, "archived_l3_summaries": 0}
    finally:
        await memory.shutdown()


@pytest.mark.asyncio
async def test_time_range_forgetting_retains_l1_and_removes_all_derivatives(
    tmp_path: Path,
) -> None:
    await apply_memory_shared_schema(str(tmp_path / "memory.db"))
    memory = _build_memory(tmp_path)
    await memory.initialize()
    assert memory.l0 is not None and memory.l1 is not None
    assert memory.l2 is not None and memory.l2_entity_catalog is not None
    assert memory.l3 is not None and memory.l4 is not None
    source_event = _event("event-l0-source", timestamp=1_720_000_000.0)
    time_event = _event("event-l0-time", timestamp=1_720_001_000.0)
    await memory.l1.store(source_event)
    await memory.l1.store(time_event)
    await memory.l0.upsert_active_entity(
        session_id="session-1",
        entity_id="person:source",
        entity_type="person",
        snapshot={"name": "Source"},
        source_event_ids=[source_event.event_id],
    )
    await memory.l0.upsert_active_entity(
        session_id="session-1",
        entity_id="person:time",
        entity_type="person",
        snapshot={"name": "Time"},
        source_event_ids=[time_event.event_id],
    )
    await memory.l0.add_temporary_tactic(
        session_id="session-1",
        scope_type="session",
        scope_id="session-1",
        tactic_type="time-backed",
        tactic_payload={},
        source_event_ids=[time_event.event_id],
        tactic_id="tactic-time",
    )
    await memory.l0.add_temporary_tactic(
        session_id="session-1",
        scope_type="session",
        scope_id="session-1",
        tactic_type="time-turn-backed",
        tactic_payload={"turn_id": time_event.turn_id},
        source_event_ids=["unrelated-tool-call"],
        tactic_id="tactic-time-turn",
    )
    await memory.l0.checkpoint_session("session-1")
    assertion_id = await memory.l2.upsert_assertion_candidate(
        {
            "entity_id": "user:u1",
            "entity_type": "user",
            "trait_family": "preference_profile",
            "trait_name": "favorite_place",
            "trait_value": "Private Place",
            "confidence_score": 0.8,
            "evidence_events": [time_event.event_id],
            "volatility_index": 0.1,
            "source_domain": "conversation",
            "inference_depth": "explicit",
            "validation_state": "stable",
            "first_inferred_at": time_event.timestamp,
            "last_validated_at": time_event.timestamp,
            "temporal_scope": "persistent",
        }
    )
    edge_id = await memory.l2.upsert_knowledge_edge(
        subject_id="user:u1",
        subject_type="user",
        predicate="VISITED",
        object_id="place:private",
        object_type="place",
        evidence_event_ids=[time_event.event_id],
        confidence=0.8,
        observed_at=time_event.timestamp,
        source_type="conversation",
        extraction_method="explicit",
    )
    await memory.l2_entity_catalog.upsert_entity(
        canonical_name="Private Place",
        entity_type="place",
        entity_id="place:private",
        source_event_ids=[time_event.event_id],
    )
    await memory.l2_entity_catalog.record_mention(
        mention_text="Private Place",
        normalized_surface="private place",
        entity_type="place",
        evidence_event_ids=[time_event.event_id],
        evidence_text="private place evidence",
        resolved_entity_id="place:private",
        confidence=0.9,
    )
    summary = await memory.l3.upsert_candidate(
        candidate=L3Candidate(
            summary_type="thematic",
            summary_category="place",
            content="Private place summary",
            source_event_ids=[time_event.event_id],
            insight_key="time-range-private-place",
        )
    )
    skill_id = await memory.l4.record_memory_event(_task_event(time_event.event_id))
    assert skill_id is not None
    mood_store = DailyMoodAggregateStore(memory.memory_db_path)
    await mood_store.upsert_aggregate(
        DailyMoodAggregate(
            day_local_date="2024-07-03",
            dominant_valence="warm",
            volatility_score=0.2,
            state_curve_compact=[0.5],
            event_count=1,
            source_event_ids=[time_event.event_id],
        )
    )
    archive_path = memory._archive_dir / "2024-07-03.db"
    await _seed_archive(archive_path, event_ids=[time_event.event_id])

    try:
        assert await memory.forget_source_event(source_event.event_id) is True
        assert [
            entity["entity_id"]
            for entity in (await memory.l0.get_workbench("session-1"))["active_entities"]
        ] == ["person:time"]

        await memory.forget_time_range_memory(
            start=time_event.timestamp - 1,
            end=time_event.timestamp + 1,
            delete_l1_events=False,
        )
        assert (await memory.l0.get_workbench("session-1"))["active_entities"] == []
        assert (await memory.l0.get_workbench("session-1"))["temporary_tactics"] == []
        retained_l1 = await memory.l1.get_event(time_event.event_id)
        assert retained_l1 is not None and retained_l1["deleted_at"] is None
        assertion = await memory.l2.get_tom_assertion(assertion_id=assertion_id)
        edge = await memory.l2.get_relationship(triple_id=edge_id)
        assert assertion is not None and assertion["status"] == "archived"
        assert assertion["evidence_events"] == []
        assert edge is not None and edge["status"] == "archived"
        assert edge["evidence_event_ids"] == []
        assert (
            await memory.l2_entity_catalog.list_entities(
                limit=10,
                entity_ids=["place:private"],
            )
            == []
        )
        assert await memory.l3.get_summary_by_id(summary["summary_id"]) is None
        assert await memory.l4.fetch_by_ids([skill_id]) == []
        assert await mood_store.get_aggregate(day_local_date="2024-07-03") is None
        async with aiosqlite.connect(archive_path) as archive_db:
            async with archive_db.execute(
                "SELECT event_id FROM archived_l1_events ORDER BY event_id"
            ) as cursor:
                assert await cursor.fetchall() == [
                    ("event-keep",),
                    (time_event.event_id,),
                ]
            async with archive_db.execute(
                "SELECT summary_id FROM archived_l3_summaries ORDER BY summary_id"
            ) as cursor:
                assert await cursor.fetchall() == [("summary-keep",)]
        with pytest.raises(ForgottenSummarySourceEventError):
            await memory.l3.upsert_candidate(
                candidate=L3Candidate(
                    summary_type="thematic",
                    summary_category="place",
                    content="Late private place summary",
                    source_event_ids=[time_event.event_id],
                    insight_key="late-time-range-private-place",
                )
            )
        assert await memory.l4.record_memory_event(_task_event(time_event.event_id)) is None
        assert not await mood_store.upsert_aggregate(
            DailyMoodAggregate(
                day_local_date="2024-07-04",
                dominant_valence="warm",
                volatility_score=0.2,
                state_curve_compact=[0.5],
                event_count=1,
                source_event_ids=[time_event.event_id],
            )
        )
        assert (
            await memory.l0.upsert_active_entity(
                session_id="session-1",
                entity_id="person:late-time",
                entity_type="person",
                snapshot={"name": "Late Time"},
                source_event_ids=[time_event.event_id],
            )
            is None
        )
        assert (
            await memory.l0.add_temporary_tactic(
                session_id="session-1",
                scope_type="session",
                scope_id="session-1",
                tactic_type="late-time-backed",
                tactic_payload={},
                source_event_ids=[time_event.event_id],
            )
            is None
        )
        async with aiosqlite.connect(tmp_path / "memory.db") as db:
            async with db.execute("SELECT COUNT(*) FROM l0_active_entities") as cursor:
                assert (await cursor.fetchone())[0] == 0
            async with db.execute(
                "SELECT COUNT(*) FROM memory_source_event_tombstones WHERE event_id = ?",
                (time_event.event_id,),
            ) as cursor:
                assert await cursor.fetchone() == (0,)
        operation = await _operation_row(tmp_path / "memory.db")
        assert operation["status"] == "completed"
        assert operation["phase"] == "completed"
    finally:
        await memory.shutdown()


@pytest.mark.asyncio
async def test_completed_time_range_governs_first_late_sync_and_all_derivatives(
    tmp_path: Path,
) -> None:
    await apply_memory_shared_schema(str(tmp_path / "memory.db"))
    memory = _build_memory(tmp_path)
    await memory.initialize()
    assert memory.l0 is not None and memory.l1 is not None
    assert memory.l2 is not None and memory.l2_entity_catalog is not None
    assert memory.l3 is not None and memory.l4 is not None
    range_start = 1_720_100_000.0
    range_end = range_start + 100.0
    late_event = _event(
        "event-first-late-range",
        turn_id="turn-first-late-range",
        timestamp=range_start + 50.0,
    )

    try:
        await memory.forget_time_range_memory(
            start=range_start,
            end=range_end,
            delete_l1_events=False,
        )
        result = await memory.ingest_event(late_event)

        assert result["l1_written"] is True
        assert result["l2_job_enqueued"] is False
        assert result["skip_reason"] == "time_range_forgotten"
        retained = await memory.l1.get_event(late_event.event_id)
        assert retained is not None and retained["deleted_at"] is None
        assert await memory.l2.has_projection_job(event_id=late_event.event_id) is False
        assert (await memory.l0.get_workbench(late_event.session_id))["session"] is None

        direct_l0_event = _event(
            "event-direct-l0-late-range",
            session_id="session-direct-l0-late-range",
            turn_id="turn-direct-l0-late-range",
            timestamp=late_event.timestamp,
        )
        await memory.l0.capture_event(direct_l0_event)
        assert (await memory.l0.get_workbench(direct_l0_event.session_id))["session"] is None
        assert (
            await memory.l0.upsert_active_entity(
                session_id=late_event.session_id,
                entity_id="person:late-range",
                entity_type="person",
                snapshot={"name": "Late Range"},
                source_event_ids=[late_event.event_id],
            )
            is None
        )
        blocked_assertion_id = await memory.l2.upsert_assertion_candidate(
            {
                "entity_id": "user:u1",
                "entity_type": "user",
                "trait_family": "preference_profile",
                "trait_name": "late_range_preference",
                "trait_value": "blocked",
                "confidence_score": 0.8,
                "evidence_events": [late_event.event_id],
                "volatility_index": 0.1,
                "source_domain": "conversation",
                "inference_depth": "explicit",
                "validation_state": "stable",
                "first_inferred_at": late_event.timestamp,
                "last_validated_at": late_event.timestamp,
                "temporal_scope": "persistent",
            }
        )
        assert await memory.l2.get_tom_assertion(assertion_id=blocked_assertion_id) is None
        unknown_assertion_id = await memory.l2.upsert_assertion_candidate(
            {
                "entity_id": "user:u1",
                "entity_type": "user",
                "trait_family": "preference_profile",
                "trait_name": "unknown_late_range_preference",
                "trait_value": "blocked",
                "confidence_score": 0.8,
                "evidence_events": ["event-unknown-late-range"],
                "volatility_index": 0.1,
                "source_domain": "conversation",
                "inference_depth": "explicit",
                "validation_state": "stable",
                "first_inferred_at": late_event.timestamp,
                "last_validated_at": late_event.timestamp,
                "temporal_scope": "persistent",
            }
        )
        assert await memory.l2.get_tom_assertion(assertion_id=unknown_assertion_id) is None
        await memory.l2_entity_catalog.upsert_entity(
            canonical_name="Late Range",
            entity_type="person",
            entity_id="person:late-range",
            source_event_ids=[late_event.event_id],
        )
        assert (
            await memory.l2_entity_catalog.list_entities(
                limit=10,
                entity_ids=["person:late-range"],
            )
            == []
        )
        with pytest.raises(ForgottenEpisodeTimeRangeError):
            await memory.l2.create_episode(
                episode_id="episode-first-late-range",
                status="active",
                time_start=late_event.timestamp,
                time_end=late_event.timestamp,
            )
        with pytest.raises(ForgottenSummarySourceEventError):
            await memory.l3.upsert_candidate(
                candidate=L3Candidate(
                    summary_type="thematic",
                    summary_category="person",
                    content="Late range summary",
                    source_event_ids=[late_event.event_id],
                    insight_key="first-late-range-summary",
                )
            )
        with pytest.raises(ForgottenSummarySourceEventError):
            await memory.l3.upsert_candidate(
                candidate=L3Candidate(
                    summary_type="thematic",
                    summary_category="person",
                    content="Unverifiable late range summary",
                    source_event_ids=["event-unverifiable-late-range"],
                    insight_key="unverifiable-late-range-summary",
                ),
                summary_overrides={
                    "period_start": late_event.timestamp,
                    "period_end": late_event.timestamp,
                },
            )
        with pytest.raises(
            ForgottenSummarySourceEventError,
            match="valid occurrence period",
        ):
            await memory.l3.upsert_candidate(
                candidate=L3Candidate(
                    summary_type="thematic",
                    summary_category="person",
                    content="Invalid unresolved occurrence period",
                    source_event_ids=["event-invalid-period-late-range"],
                    insight_key="invalid-period-late-range-summary",
                ),
                summary_overrides={
                    "period_start": float("nan"),
                    "period_end": late_event.timestamp,
                },
            )
        task_event = _task_event("event-direct-l4-late-range")
        task_event.timestamp = late_event.timestamp
        task_event.created_at = late_event.created_at
        task_event.turn_id = "turn-direct-l4-late-range"
        assert await memory.l4.record_memory_event(task_event) is None
        async with aiosqlite.connect(tmp_path / "memory.db") as db:
            async with db.execute(
                """
                SELECT COUNT(*)
                FROM memory_projection_blocks
                WHERE event_id IN (?, ?)
                  AND block_kind = 'episode_formation'
                  AND target_id LIKE 'time:%'
                """,
                (late_event.event_id, late_event.turn_id),
            ) as cursor:
                assert (await cursor.fetchone())[0] == 2
    finally:
        await memory.shutdown()


@pytest.mark.asyncio
async def test_late_time_range_delete_honors_inclusive_boundaries_only(
    tmp_path: Path,
) -> None:
    await apply_memory_shared_schema(str(tmp_path / "memory.db"))
    memory = _build_memory(tmp_path)
    await memory.initialize()
    assert memory.l1 is not None
    range_start = 1_720_200_000.0
    range_end = range_start + 100.0

    try:
        await memory.forget_time_range_memory(
            start=range_start,
            end=range_end,
            delete_l1_events=True,
        )
        boundary_events = [
            _event(
                "event-late-range-start",
                turn_id="turn-late-range-start",
                timestamp=range_start,
            ),
            _event(
                "event-late-range-end",
                turn_id="turn-late-range-end",
                timestamp=range_end,
            ),
        ]
        outside_events = [
            _event(
                "event-before-late-range",
                turn_id="turn-before-late-range",
                timestamp=range_start - 0.001,
            ),
            _event(
                "event-after-late-range",
                turn_id="turn-after-late-range",
                timestamp=range_end + 0.001,
            ),
        ]

        for event in boundary_events:
            result = await memory.ingest_event(event)
            assert result["l1_written"] is False
            assert result["skip_reason"] == "time_range_forgotten"
            assert await memory.l1.get_event(event.event_id) is None

        for event in outside_events:
            result = await memory.ingest_event(event)
            assert result["l1_written"] is True
            assert await memory.l1.get_event(event.event_id) is not None
            summary = await memory.l3.upsert_candidate(
                candidate=L3Candidate(
                    summary_type="thematic",
                    summary_category="person",
                    content=f"Allowed outside range: {event.event_id}",
                    source_event_ids=[event.event_id],
                    insight_key=f"outside-range:{event.event_id}",
                )
            )
            assert await memory.l3.get_summary_by_id(summary["summary_id"]) is not None
        unresolved_outside = await memory.l3.upsert_candidate(
            candidate=L3Candidate(
                summary_type="thematic",
                summary_category="person",
                content="Allowed unresolved source outside range",
                source_event_ids=["event-unresolved-outside-range"],
                insight_key="unresolved-outside-range",
            ),
            summary_overrides={
                "period_start": range_end + 10.0,
                "period_end": range_end + 20.0,
            },
        )
        assert await memory.l3.get_summary_by_id(unresolved_outside["summary_id"]) is not None
    finally:
        await memory.shutdown()


@pytest.mark.asyncio
async def test_repeated_time_range_barriers_coexist_and_full_clear_removes_them(
    tmp_path: Path,
) -> None:
    await apply_memory_shared_schema(str(tmp_path / "memory.db"))
    memory = _build_memory(tmp_path)
    await memory.initialize()
    range_start = 1_720_300_000.0
    range_end = range_start + 100.0

    try:
        for _ in range(2):
            await memory.forget_time_range_memory(
                start=range_start,
                end=range_end,
                delete_l1_events=False,
            )
        async with aiosqlite.connect(tmp_path / "memory.db") as db:
            async with db.execute(
                """
                SELECT COUNT(*), COUNT(DISTINCT target_id)
                FROM memory_time_range_forget_barriers
                WHERE range_start = ? AND range_end = ?
                """,
                (range_start, range_end),
            ) as cursor:
                assert await cursor.fetchone() == (2, 2)

        await memory.clear_all_memory()
        async with aiosqlite.connect(tmp_path / "memory.db") as db:
            async with db.execute(
                "SELECT COUNT(*) FROM memory_time_range_forget_barriers"
            ) as cursor:
                assert await cursor.fetchone() == (0,)
    finally:
        await memory.shutdown()


@pytest.mark.asyncio
async def test_time_range_cleanup_failure_stays_incomplete_and_resumes(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    await apply_memory_shared_schema(str(tmp_path / "memory.db"))
    memory = _build_memory(tmp_path)
    await memory.initialize()
    assert memory.l0 is not None and memory.l1 is not None
    assert memory.l3 is not None and memory.l4 is not None
    event = _event("event-time-range-retry", timestamp=1_720_002_000.0)
    await memory.l1.store(event)
    await memory.l0.upsert_active_entity(
        session_id="session-1",
        entity_id="person:retry",
        entity_type="person",
        snapshot={"name": "Retry"},
        source_event_ids=[event.event_id],
    )
    await memory.l0.add_temporary_tactic(
        session_id="session-1",
        scope_type="session",
        scope_id="session-1",
        tactic_type="retry-turn-backed",
        tactic_payload={"turn_id": event.turn_id},
        source_event_ids=["unrelated-retry-tool-call"],
        tactic_id="tactic-retry-turn",
    )
    await memory.l0.checkpoint_session("session-1")
    summary = await memory.l3.upsert_candidate(
        candidate=L3Candidate(
            summary_type="thematic",
            summary_category="retry",
            content="Must stay hidden while cleanup retries",
            source_event_ids=[event.event_id],
            insight_key="time-range-retry-summary",
        )
    )
    skill_id = await memory.l4.record_memory_event(_task_event(event.event_id))
    assert skill_id is not None
    original_l3_forget = memory.l3.forget_source_events

    async def fail_l3_cleanup(_event_ids):  # type: ignore[no-untyped-def]
        raise RuntimeError("time range L3 cleanup interrupted")

    monkeypatch.setattr(memory.l3, "forget_source_events", fail_l3_cleanup)
    try:
        with pytest.raises(RuntimeError, match="time range L3 cleanup interrupted"):
            await memory.forget_time_range_memory(
                start=event.timestamp - 1,
                end=event.timestamp + 1,
                delete_l1_events=False,
            )

        failed = await _operation_row(tmp_path / "memory.db")
        assert failed["status"] == "failed"
        assert failed["phase"] == "target_cleanup"
        retained_l1 = await memory.l1.get_event(event.event_id)
        assert retained_l1 is not None and retained_l1["deleted_at"] is None
        assert await memory.l3.get_summary_by_id(summary["summary_id"]) is None
        assert await memory.l4.fetch_by_ids([skill_id]) == []
        assert (await memory.l0.get_workbench("session-1"))["active_entities"] == []
        assert (await memory.l0.get_workbench("session-1"))["temporary_tactics"] == []
        async with aiosqlite.connect(tmp_path / "memory.db") as db:
            async with db.execute(
                "SELECT derivation_state FROM summaries WHERE summary_id = ?",
                (summary["summary_id"],),
            ) as cursor:
                assert (await cursor.fetchone())[0] != "current"
            async with db.execute(
                "SELECT deleted_at FROM procedural_skills WHERE skill_id = ?",
                (skill_id,),
            ) as cursor:
                assert await cursor.fetchone() == (None,)
            async with db.execute(
                "SELECT COUNT(*) FROM l0_active_entities WHERE entity_id = 'person:retry'"
            ) as cursor:
                assert await cursor.fetchone() == (1,)
            async with db.execute(
                "SELECT COUNT(*) FROM l0_temporary_tactics WHERE tactic_id = 'tactic-retry-turn'"
            ) as cursor:
                assert await cursor.fetchone() == (1,)

        monkeypatch.setattr(memory.l3, "forget_source_events", original_l3_forget)
        await memory.forget_time_range_memory(
            start=event.timestamp - 1,
            end=event.timestamp + 1,
            delete_l1_events=False,
        )
        completed = await _operation_row(tmp_path / "memory.db")
        assert completed["status"] == "completed"
        assert completed["phase"] == "completed"
        async with aiosqlite.connect(tmp_path / "memory.db") as db:
            async with db.execute(
                "SELECT derivation_state FROM summaries WHERE summary_id = ?",
                (summary["summary_id"],),
            ) as cursor:
                assert (await cursor.fetchone())[0] != "current"
            async with db.execute(
                "SELECT deleted_at FROM procedural_skills WHERE skill_id = ?",
                (skill_id,),
            ) as cursor:
                assert (await cursor.fetchone())[0] is not None
            async with db.execute(
                "SELECT COUNT(*) FROM l0_active_entities WHERE entity_id = 'person:retry'"
            ) as cursor:
                assert await cursor.fetchone() == (0,)
            async with db.execute(
                "SELECT COUNT(*) FROM l0_temporary_tactics WHERE tactic_id = 'tactic-retry-turn'"
            ) as cursor:
                assert await cursor.fetchone() == (0,)
    finally:
        await memory.shutdown()


@pytest.mark.asyncio
async def test_time_range_projection_cleanup_pages_every_event_and_turn_reference(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    await apply_memory_shared_schema(str(tmp_path / "memory.db"))
    memory = _build_memory(tmp_path)
    await memory.initialize()
    assert memory.l1 is not None
    base_timestamp = 1_720_010_000.0
    events = [
        _event(
            f"event-time-page-{index:03d}",
            turn_id=f"turn-time-page-{index:03d}",
            timestamp=base_timestamp + index,
        )
        for index in range(205)
    ]
    for event in events:
        await memory.l1.store(event)

    cleaned_references: set[str] = set()

    async def record_cleanup(references, **_kwargs):  # type: ignore[no-untyped-def]
        cleaned_references.update(str(reference) for reference in references)

    monkeypatch.setattr(
        memory._durable_forget_runner._cleanup,
        "cleanup_references",
        record_cleanup,
    )
    try:
        result = await memory.forget_time_range_memory(
            start=base_timestamp - 1,
            end=base_timestamp + len(events),
            delete_l1_events=False,
        )
        expected_references = {
            reference for event in events for reference in (event.event_id, str(event.turn_id))
        }
        assert cleaned_references == expected_references
        assert result["l1_events_deleted"] == 0
        assert result["l2_counts"]["projection_source_references"] == len(expected_references)
        async with aiosqlite.connect(tmp_path / "memory.db") as db:
            async with db.execute("""
                SELECT COUNT(*)
                FROM memory_projection_blocks
                WHERE block_kind = 'episode_formation'
                  AND target_id LIKE 'time:%'
                """) as cursor:
                assert await cursor.fetchone() == (len(expected_references),)
        operation = await _operation_row(tmp_path / "memory.db")
        assert operation["status"] == "completed"
    finally:
        await memory.shutdown()


@pytest.mark.asyncio
async def test_startup_force_recovers_failed_operation_with_unexpired_foreign_lease(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    await apply_memory_shared_schema(str(tmp_path / "memory.db"))
    memory = _build_memory(tmp_path)
    await memory.initialize()
    assert memory.l1 is not None and memory.l3 is not None
    await memory.l1.store(_event("event-crash"))

    async def fail_cleanup(_event_ids):  # type: ignore[no-untyped-def]
        raise RuntimeError("simulated cleanup crash")

    monkeypatch.setattr(memory.l3, "forget_source_events", fail_cleanup)
    with pytest.raises(RuntimeError, match="simulated cleanup crash"):
        await memory.forget_source_event("event-crash")

    hidden = await memory.l1.get_event("event-crash")
    assert hidden is not None and hidden["deleted_at"] is not None
    failed = await _operation_row(tmp_path / "memory.db")
    assert failed["status"] == "failed"
    assert failed["selection_complete"] == 1

    async with aiosqlite.connect(tmp_path / "memory.db") as db:
        await db.execute(
            """
            UPDATE memory_forget_operations
            SET status = 'running', lease_owner = 'dead-process',
                lease_expires_at = ?
            WHERE operation_id = ?
            """,
            (time.time() + 3600, failed["operation_id"]),
        )
        await db.commit()
    await memory.shutdown()

    recovered = _build_memory(tmp_path)
    await recovered.initialize()
    try:
        completed = await _operation_row(tmp_path / "memory.db")
        assert completed["status"] == "completed"
        assert completed["phase"] == "completed"
        assert completed["attempt_count"] == 2
        assert completed["lease_owner"] is None
    finally:
        await recovered.shutdown()


@pytest.mark.asyncio
async def test_session_projection_cleanup_failure_is_resumed_and_scrubbed(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    await apply_memory_shared_schema(str(tmp_path / "memory.db"))
    memory = _build_memory(tmp_path)
    await memory.initialize()
    assert memory.l1 is not None
    await memory.l1.store(_event("event-session", session_id="session-private"))
    async with aiosqlite.connect(tmp_path / "l1.db") as db:
        await db.execute("""
            UPDATE chat_sessions
            SET title = 'Private title', summary = 'Private summary',
                workspace_path = '/private/workspace'
            WHERE session_id = 'session-private'
            """)
        await db.commit()

    async def fail_projection(_session_id: str) -> None:
        raise RuntimeError("projection cleanup interrupted")

    monkeypatch.setattr(memory.l1, "retire_chat_session_projection", fail_projection)
    with pytest.raises(RuntimeError, match="projection cleanup interrupted"):
        await memory.forget_chat_session_sources(
            user_id="u1",
            session_id="session-private",
            turn_ids=["turn-1"],
        )
    failed = await _operation_row(tmp_path / "memory.db")
    assert failed["phase"] == "target_cleanup"
    await memory.shutdown()

    recovered = _build_memory(tmp_path)
    await recovered.initialize()
    try:
        async with aiosqlite.connect(tmp_path / "l1.db") as db:
            async with db.execute("""
                SELECT title, summary, last_message_preview,
                       last_user_message_preview, message_count,
                       workspace_path, deleted_at
                FROM chat_sessions
                WHERE session_id = 'session-private'
                """) as cursor:
                row = await cursor.fetchone()
        assert row is not None
        assert tuple(row[:6]) == ("", "", "", "", 0, None)
        assert row[6] is not None
        assert (await _operation_row(tmp_path / "memory.db"))["status"] == "completed"
        assert await recovered.was_chat_session_forgotten(
            user_id="u1",
            session_id="session-private",
        )
        assert not await recovered.was_chat_session_forgotten(
            user_id="another-user",
            session_id="session-private",
        )
    finally:
        await recovered.shutdown()


@pytest.mark.asyncio
async def test_message_projection_rebuild_failure_resumes_from_remaining_events(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    await apply_memory_shared_schema(str(tmp_path / "memory.db"))
    memory = _build_memory(tmp_path)
    await memory.initialize()
    assert memory.l1 is not None
    await memory.l1.store(
        _event(
            "event-delete",
            session_id="session-message",
            message_id="message-delete",
            content="delete this preview",
            timestamp=1_720_000_001.0,
        )
    )
    await memory.l1.store(
        _event(
            "event-keep",
            session_id="session-message",
            message_id="message-keep",
            content="keep this preview",
            timestamp=1_720_000_000.0,
        )
    )

    async def fail_projection(_session_id: str) -> None:
        raise RuntimeError("projection rebuild interrupted")

    monkeypatch.setattr(memory.l1, "rebuild_chat_session_projection", fail_projection)
    with pytest.raises(RuntimeError, match="projection rebuild interrupted"):
        await memory.forget_chat_message_source(
            user_id="u1",
            session_id="session-message",
            message_id="message-delete",
            source="chat",
            event_type="UserMessage",
        )
    await memory.shutdown()

    recovered = _build_memory(tmp_path)
    await recovered.initialize()
    try:
        async with aiosqlite.connect(tmp_path / "l1.db") as db:
            async with db.execute("""
                SELECT last_message_preview, last_user_message_preview, message_count
                FROM chat_sessions
                WHERE session_id = 'session-message'
                """) as cursor:
                row = await cursor.fetchone()
        assert row is not None
        assert tuple(row) == ("keep this preview", "keep this preview", 1)
        assert (await _operation_row(tmp_path / "memory.db"))["status"] == "completed"
    finally:
        await recovered.shutdown()


class _RecordingVectorIndex:
    def __init__(self) -> None:
        self.deleted: list[str] = []

    async def delete_entity(self, *, entity_id: str) -> None:
        self.deleted.append(entity_id)

    async def close(self) -> None:
        return None


class _BlockingAsyncLock:
    def __init__(self) -> None:
        self.waiting = asyncio.Event()
        self.release = asyncio.Event()

    async def __aenter__(self) -> None:
        self.waiting.set()
        await self.release.wait()

    async def __aexit__(self, *args: object) -> None:
        return None


class _CoordinatedVectorIndex(_RecordingVectorIndex):
    def __init__(self, source_write_lock: _BlockingAsyncLock) -> None:
        super().__init__()
        self._coordinator = SimpleNamespace(source_write_lock=source_write_lock)
        self.vector_present = False

    async def delete_entity(self, *, entity_id: str) -> None:
        await super().delete_entity(entity_id=entity_id)
        self.vector_present = False


def _task_event(event_id: str) -> MemoryEvent:
    event = _event(event_id, turn_id=f"turn:{event_id}")
    event.event_type = "TaskCompleted"
    event.task_id = "private-workflow"
    event.content = "private workflow learned from the entity"
    return event


@pytest.mark.asyncio
async def test_entity_catalog_forget_waits_for_inflight_vector_write(
    tmp_path: Path,
) -> None:
    await apply_memory_shared_schema(str(tmp_path / "memory.db"))
    memory = _build_memory(tmp_path)
    await memory.initialize()
    assert memory.l2_entity_catalog is not None
    catalog = memory.l2_entity_catalog
    await catalog.upsert_entity(
        canonical_name="Private Person",
        entity_type="person",
        entity_id="person:private",
    )
    source_write_lock = _BlockingAsyncLock()
    vector_index = _CoordinatedVectorIndex(source_write_lock)
    catalog._vector_index = vector_index  # type: ignore[assignment]

    try:
        forget_task = asyncio.create_task(catalog.forget_entity_catalog("person:private"))
        await asyncio.wait_for(source_write_lock.waiting.wait(), timeout=1.0)
        assert not forget_task.done()
        vector_index.vector_present = True
        source_write_lock.release.set()

        counts = await asyncio.wait_for(forget_task, timeout=1.0)
        assert counts["entity_catalog"] == 1
        assert vector_index.deleted == ["person:private"]
        assert not vector_index.vector_present
    finally:
        source_write_lock.release.set()
        await memory.shutdown()


@pytest.mark.asyncio
async def test_entity_forget_waits_for_active_l2_projection_batch(
    tmp_path: Path,
) -> None:
    await apply_memory_shared_schema(str(tmp_path / "memory.db"))
    memory = _build_memory(tmp_path)
    await memory.initialize()
    assert memory.l1 is not None
    assert memory.l2 is not None
    assert memory.l2_entity_catalog is not None
    assert memory.l2_pipeline is not None
    await memory.l2_pipeline.shutdown()
    await memory.l1.store(_event("event-private-person"))
    await memory.l1.write_event_entities(
        [("event-private-person", "person:private", "person", 0.9)]
    )
    await memory.l2_entity_catalog.upsert_entity(
        canonical_name="Private Person",
        entity_type="person",
        entity_id="person:private",
    )
    forget_task: asyncio.Task[dict[str, object]] | None = None

    try:
        async with memory.l2.memory_correction_job_guard():
            forget_task = asyncio.create_task(
                memory.forget_entity_memory(
                    entity_id="person:private",
                    delete_l1_events=True,
                )
            )
            operation = None
            for _ in range(100):
                await asyncio.sleep(0.01)
                async with aiosqlite.connect(tmp_path / "memory.db") as db:
                    db.row_factory = aiosqlite.Row
                    async with db.execute(
                        "SELECT * FROM memory_forget_operations LIMIT 1"
                    ) as cursor:
                        operation = await cursor.fetchone()
                if operation is not None:
                    break
            assert operation is not None
            assert operation["status"] == "running"
            assert not forget_task.done()

        await asyncio.wait_for(forget_task, timeout=2.0)
    finally:
        if forget_task is not None and not forget_task.done():
            forget_task.cancel()
            await asyncio.gather(forget_task, return_exceptions=True)
        await memory.shutdown()


@pytest.mark.asyncio
async def test_entity_forget_removes_old_l3_l4_and_blocks_only_preexisting_evidence(
    tmp_path: Path,
) -> None:
    await apply_memory_shared_schema(str(tmp_path / "memory.db"))
    memory = _build_memory(tmp_path)
    await memory.initialize()
    assert memory.l1 is not None
    assert memory.l2 is not None
    assert memory.l2_entity_catalog is not None
    assert memory.l3 is not None
    assert memory.l4 is not None
    catalog = memory.l2_entity_catalog
    old_event_id = "event-private-person"
    future_event_id = "event-future-person"
    await memory.l1.store(_event(old_event_id, content="Private Person appears here"))
    await catalog.upsert_entity(
        canonical_name="Private Person",
        entity_type="person",
        entity_id="person:private",
        source_event_ids=[old_event_id],
    )
    await catalog.add_alias(
        entity_id="person:private",
        alias_text="Secret Alias",
    )
    await memory.l2.enqueue_projection_job(
        event_id=old_event_id,
        source="chat",
        event_type="UserMessage",
    )
    summary = await memory.l3.upsert_candidate(
        candidate=L3Candidate(
            summary_type="thematic",
            summary_category="person",
            content="Private Person summary",
            source_event_ids=[old_event_id],
            insight_key="private-person-summary",
        )
    )
    skill_id = await memory.l4.record_memory_event(_task_event(old_event_id))
    assert skill_id is not None

    try:
        await memory.forget_entity_memory(
            entity_id="person:private",
            delete_l1_events=False,
        )

        raw = await memory.l1.get_event(old_event_id)
        assert raw is not None and raw["deleted_at"] is None
        assert await memory.l3.get_summary_by_id(summary["summary_id"]) is None
        assert await memory.l4.fetch_by_ids([skill_id]) == []
        with pytest.raises(ForgottenSummarySourceEventError):
            await memory.l3.upsert_candidate(
                candidate=L3Candidate(
                    summary_type="thematic",
                    summary_category="person",
                    content="late old summary",
                    source_event_ids=[old_event_id],
                    insight_key="late-private-person-summary",
                )
            )
        assert await memory.l4.record_memory_event(_task_event(old_event_id)) is None
        assert (
            await catalog.filter_projection_source_event_ids(
                target_entity_id="person:private",
                normalized_surface="secret alias",
                entity_type="person",
                event_ids=[old_event_id],
            )
            == ()
        )
        assert await catalog.filter_projection_source_event_ids(
            target_entity_id="person:private",
            normalized_surface="secret alias",
            entity_type="person",
            event_ids=[future_event_id],
        ) == (future_event_id,)
        assert await memory.l4.record_memory_event(_task_event(future_event_id)) is not None
    finally:
        await memory.shutdown()


@pytest.mark.asyncio
async def test_entity_forget_scopes_old_backlog_to_the_target_entity(
    tmp_path: Path,
) -> None:
    await apply_memory_shared_schema(str(tmp_path / "memory.db"))
    memory = _build_memory(tmp_path)
    await memory.initialize()
    assert memory.l1 is not None
    assert memory.l2 is not None
    assert memory.l2_entity_catalog is not None
    assert memory.l3 is not None
    assert memory.l4 is not None
    assert memory.l2_pipeline is not None
    await memory.l2_pipeline.shutdown()
    target_event_id = "event-pending-target"
    unrelated_event_id = "event-pending-unrelated"
    await memory.l1.store(_event(target_event_id, content="Private Person appears here"))
    await memory.l1.store(_event(unrelated_event_id, content="An unrelated project update"))
    await memory.l2_entity_catalog.upsert_entity(
        canonical_name="Private Person",
        entity_type="person",
        entity_id="person:private",
    )
    for event_id in (target_event_id, unrelated_event_id):
        assert await memory.l2.enqueue_projection_job(
            event_id=event_id,
            source="chat",
            event_type="UserMessage",
        )
    archive_path = memory._archive_dir / "2024-07-04.db"
    await _seed_archive(archive_path, event_ids=[unrelated_event_id])

    try:
        await memory.forget_entity_memory(
            entity_id="person:private",
            delete_l1_events=False,
        )

        async with aiosqlite.connect(tmp_path / "memory.db") as db:
            async with db.execute("""
                SELECT block_kind, event_id
                FROM memory_projection_blocks
                WHERE target_id = 'person:private'
                ORDER BY block_kind, event_id
                """) as cursor:
                assert await cursor.fetchall() == [
                    ("entity_projection_candidate", target_event_id),
                    ("entity_projection_candidate", unrelated_event_id),
                ]

        claimed = await memory.l2.claim_projection_jobs(
            consumer_name="entity-scope-test",
            limit=10,
        )
        assert {row["event_id"] for row in claimed} == {
            target_event_id,
            unrelated_event_id,
        }

        assert (
            await memory.l2_entity_catalog.filter_projection_source_event_ids(
                target_entity_id="person:private",
                normalized_surface="private person",
                entity_type="person",
                event_ids=[target_event_id],
            )
            == ()
        )
        async with aiosqlite.connect(tmp_path / "memory.db") as db:
            async with db.execute("""
                SELECT block_kind, event_id
                FROM memory_projection_blocks
                WHERE target_id = 'person:private'
                ORDER BY block_kind, event_id
                """) as cursor:
                assert await cursor.fetchall() == [
                    ("entity_projection", target_event_id),
                    ("entity_projection_candidate", target_event_id),
                    ("entity_projection_candidate", unrelated_event_id),
                ]
        with pytest.raises(ForgottenSummarySourceEventError):
            await memory.l3.upsert_candidate(
                candidate=L3Candidate(
                    summary_type="thematic",
                    summary_category="person",
                    content="Late private person summary",
                    source_event_ids=[target_event_id],
                    insight_key="late-pending-private-person",
                )
            )
        assert await memory.l4.record_memory_event(_task_event(target_event_id)) is None
        await memory.l2_entity_catalog.upsert_entity(
            canonical_name="Private Person",
            entity_type="person",
            entity_id="person:private",
            source_event_ids=[target_event_id],
        )
        assert (
            await memory.l2_entity_catalog.list_entities(
                limit=10,
                entity_ids=["person:private"],
            )
            == []
        )
        blocked_assertion_id = await memory.l2.upsert_assertion_candidate(
            {
                "entity_id": "person:private",
                "entity_type": "person",
                "trait_family": "preference_profile",
                "trait_name": "favorite_city",
                "trait_value": "Blocked City",
                "confidence_score": 0.8,
                "evidence_events": [target_event_id],
                "volatility_index": 0.1,
                "source_domain": "conversation",
                "inference_depth": "explicit",
                "validation_state": "stable",
                "first_inferred_at": 100.0,
                "last_validated_at": 100.0,
                "temporal_scope": "persistent",
            }
        )
        blocked_edge_id = await memory.l2.upsert_knowledge_edge(
            subject_id="person:private",
            subject_type="person",
            predicate="VISITED",
            object_id="place:blocked",
            object_type="place",
            evidence_event_ids=[target_event_id],
            confidence=0.8,
            observed_at=100.0,
            source_type="conversation",
            extraction_method="explicit",
        )
        await memory.l2.upsert_entity_facet(
            entity_id="person:private",
            entity_type="person",
            facet_name="role",
            facet_value="blocked",
            evidence_event_ids=[target_event_id],
            confidence=0.8,
            observed_at=100.0,
            source_type="conversation",
        )
        await memory.l2.create_episode(
            episode_id="episode-private-replay",
            status="active",
            time_start=100.0,
            time_end=200.0,
            primary_entity_ids=["person:private"],
        )
        assert (
            await memory.l2.add_episode_events(
                episode_id="episode-private-replay",
                event_ids=[target_event_id],
            )
            == 0
        )
        assert await memory.l2.get_tom_assertion(assertion_id=blocked_assertion_id) is None
        assert await memory.l2.get_relationship(triple_id=blocked_edge_id) is None
        assert await memory.l2.list_entity_facets(entity_id="person:private") == []

        allowed_assertion_id = await memory.l2.upsert_assertion_candidate(
            {
                "entity_id": "person:other",
                "entity_type": "person",
                "trait_family": "preference_profile",
                "trait_name": "favorite_city",
                "trait_value": "Allowed City",
                "confidence_score": 0.8,
                "evidence_events": [unrelated_event_id],
                "volatility_index": 0.1,
                "source_domain": "conversation",
                "inference_depth": "explicit",
                "validation_state": "stable",
                "first_inferred_at": 100.0,
                "last_validated_at": 100.0,
                "temporal_scope": "persistent",
            }
        )
        allowed_edge_id = await memory.l2.upsert_knowledge_edge(
            subject_id="person:other",
            subject_type="person",
            predicate="VISITED",
            object_id="place:allowed",
            object_type="place",
            evidence_event_ids=[unrelated_event_id],
            confidence=0.8,
            observed_at=100.0,
            source_type="conversation",
            extraction_method="explicit",
        )
        await memory.l2_entity_catalog.upsert_entity(
            canonical_name="Other Person",
            entity_type="person",
            entity_id="person:other",
            source_event_ids=[unrelated_event_id],
        )
        await memory.l2.upsert_entity_facet(
            entity_id="person:other",
            entity_type="person",
            facet_name="role",
            facet_value="allowed",
            evidence_event_ids=[unrelated_event_id],
            confidence=0.8,
            observed_at=100.0,
            source_type="conversation",
        )
        await memory.l2.create_episode(
            episode_id="episode-unrelated-replay",
            status="active",
            time_start=100.0,
            time_end=200.0,
            primary_entity_ids=["person:other"],
        )
        assert (
            await memory.l2.add_episode_events(
                episode_id="episode-unrelated-replay",
                event_ids=[unrelated_event_id],
            )
            == 1
        )
        unrelated_summary = await memory.l3.upsert_candidate(
            candidate=L3Candidate(
                summary_type="thematic",
                summary_category="project",
                content="Unrelated project summary",
                source_event_ids=[unrelated_event_id],
                insight_key="unrelated-backlog-summary",
            )
        )
        unrelated_skill_id = await memory.l4.record_memory_event(_task_event(unrelated_event_id))
        assert await memory.l2.get_tom_assertion(assertion_id=allowed_assertion_id) is not None
        assert await memory.l2.get_relationship(triple_id=allowed_edge_id) is not None
        assert len(await memory.l2.list_entity_facets(entity_id="person:other")) == 1
        assert await memory.l3.get_summary_by_id(unrelated_summary["summary_id"]) is not None
        assert unrelated_skill_id is not None
        assert await memory.l4.fetch_by_ids([unrelated_skill_id])
        async with aiosqlite.connect(archive_path) as archive_db:
            async with archive_db.execute(
                "SELECT summary_id FROM archived_l3_summaries ORDER BY summary_id"
            ) as cursor:
                assert await cursor.fetchall() == [
                    ("summary-direct",),
                    ("summary-keep",),
                    ("summary-linked",),
                ]
    finally:
        await memory.shutdown()


@pytest.mark.asyncio
async def test_entity_forget_snapshots_late_alias_for_every_blocked_event(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    await apply_memory_shared_schema(str(tmp_path / "memory.db"))
    memory = _build_memory(tmp_path)
    await memory.initialize()
    assert memory.l1 is not None
    assert memory.l2 is not None
    assert memory.l2_entity_catalog is not None
    assert memory.l2_pipeline is not None
    await memory.l2_pipeline.shutdown()
    catalog = memory.l2_entity_catalog
    full_event_id = "event-confirmed-target"
    candidate_event_ids = ("event-candidate-a", "event-candidate-b")
    blocked_event_ids = (full_event_id, *candidate_event_ids)
    for event_id in blocked_event_ids:
        await memory.l1.store(_event(event_id, content="Pending entity extraction"))
    for event_id in candidate_event_ids:
        assert await memory.l2.enqueue_projection_job(
            event_id=event_id,
            source="chat",
            event_type="UserMessage",
        )
    await catalog.upsert_entity(
        canonical_name="Private Person",
        entity_type="person",
        entity_id="person:private",
        source_event_ids=[full_event_id],
    )

    original_cleanup_target = memory._durable_forget_runner._cleanup_target

    async def add_late_alias_then_cleanup(operation):  # type: ignore[no-untyped-def]
        await catalog.add_alias(
            entity_id="person:private",
            alias_text="Late Secret Alias",
        )
        return await original_cleanup_target(operation)

    monkeypatch.setattr(
        memory._durable_forget_runner,
        "_cleanup_target",
        add_late_alias_then_cleanup,
    )
    try:
        await memory.forget_entity_memory(
            entity_id="person:private",
            delete_l1_events=False,
        )

        async with aiosqlite.connect(tmp_path / "memory.db") as db:
            async with db.execute("""
                SELECT event_id
                FROM memory_entity_projection_identity_blocks
                WHERE target_id = 'person:private'
                  AND normalized_surface = 'late secret alias'
                ORDER BY event_id
                """) as cursor:
                assert await cursor.fetchall() == [
                    (event_id,) for event_id in sorted(blocked_event_ids)
                ]
        for event_id in blocked_event_ids:
            assert (
                await catalog.filter_projection_source_event_ids(
                    target_entity_id="person:replacement",
                    normalized_surface="late secret alias",
                    entity_type="person",
                    event_ids=[event_id],
                )
                == ()
            )
        await catalog.upsert_entity(
            canonical_name="Late Secret Alias",
            entity_type="place",
            entity_id="place:late-secret-alias",
            source_event_ids=[candidate_event_ids[0]],
        )
        await catalog.add_alias(
            entity_id="place:late-secret-alias",
            alias_text="Late Secret Alias",
            source_event_ids=[candidate_event_ids[0]],
        )
        async with aiosqlite.connect(tmp_path / "memory.db") as db:
            async with db.execute("""
                SELECT normalized_alias
                FROM entity_aliases
                WHERE entity_id = 'place:late-secret-alias'
                """) as cursor:
                assert await cursor.fetchall() == [("late secret alias",)]
    finally:
        await memory.shutdown()


@pytest.mark.asyncio
async def test_entity_forget_promotes_raced_target_lineage_before_cleanup(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    await apply_memory_shared_schema(str(tmp_path / "memory.db"))
    memory = _build_memory(tmp_path)
    await memory.initialize()
    assert memory.l1 is not None
    assert memory.l2 is not None
    assert memory.l2_entity_catalog is not None
    assert memory.l3 is not None
    assert memory.l4 is not None
    assert memory.l2_pipeline is not None
    await memory.l2_pipeline.shutdown()
    event_id = "event-raced-target-lineage"
    await memory.l1.store(_event(event_id, content="Private Person appears here"))
    await memory.l2_entity_catalog.upsert_entity(
        canonical_name="Private Person",
        entity_type="person",
        entity_id="person:private",
    )
    assert await memory.l2.enqueue_projection_job(
        event_id=event_id,
        source="chat",
        event_type="UserMessage",
    )
    assert await memory.l2.complete_projection_jobs([event_id]) == 1
    summary = await memory.l3.upsert_candidate(
        candidate=L3Candidate(
            summary_type="thematic",
            summary_category="person",
            content="Raced private person summary",
            source_event_ids=[event_id],
            insight_key="raced-private-person-summary",
        )
    )
    skill_id = await memory.l4.record_memory_event(_task_event(event_id))
    assert skill_id is not None

    original_cleanup_target = memory._durable_forget_runner._cleanup_target

    async def inject_raced_lineage_then_cleanup(operation):  # type: ignore[no-untyped-def]
        await memory.l1.write_event_entities([(event_id, "person:private", "person", 0.9)])
        return await original_cleanup_target(operation)

    monkeypatch.setattr(
        memory._durable_forget_runner,
        "_cleanup_target",
        inject_raced_lineage_then_cleanup,
    )
    try:
        await memory.forget_entity_memory(
            entity_id="person:private",
            delete_l1_events=False,
        )
        async with aiosqlite.connect(tmp_path / "memory.db") as db:
            async with db.execute(
                """
                SELECT block_kind
                FROM memory_projection_blocks
                WHERE target_id = 'person:private' AND event_id = ?
                ORDER BY block_kind
                """,
                (event_id,),
            ) as cursor:
                assert await cursor.fetchall() == [("entity_projection",)]
            async with db.execute(
                """
                SELECT normalized_surface
                FROM memory_entity_projection_identity_blocks
                WHERE target_id = 'person:private' AND event_id = ?
                ORDER BY normalized_surface
                """,
                (event_id,),
            ) as cursor:
                assert await cursor.fetchall() == [("private person",)]
        assert await memory.l3.get_summary_by_id(summary["summary_id"]) is None
        assert await memory.l4.fetch_by_ids([skill_id]) == []
    finally:
        await memory.shutdown()


@pytest.mark.asyncio
async def test_entity_target_cleanup_runs_without_selected_l1_events(
    tmp_path: Path,
) -> None:
    await apply_memory_shared_schema(str(tmp_path / "memory.db"))
    memory = _build_memory(tmp_path)
    await memory.initialize()
    assert memory.l2_entity_catalog is not None
    catalog = memory.l2_entity_catalog
    await catalog.upsert_entity(
        canonical_name="Private Person",
        entity_type="person",
        entity_id="person:private",
    )
    await catalog.add_alias(
        entity_id="person:private",
        alias_text="Secret Alias",
    )
    await catalog.record_mention(
        mention_text="Private Person",
        normalized_surface="private person",
        entity_type="person",
        evidence_event_ids=["event-without-l1-row"],
        evidence_text="private evidence",
        resolved_entity_id="person:private",
        confidence=0.9,
    )
    vector_index = _RecordingVectorIndex()
    catalog._vector_index = vector_index  # type: ignore[assignment]

    try:
        result = await memory.forget_entity_memory(
            entity_id="person:private",
            delete_l1_events=True,
        )
        assert result["l1_events_deleted"] == 0
        assert result["l2_counts"]["entity_catalog"] == 1
        assert vector_index.deleted == ["person:private"]
        async with aiosqlite.connect(tmp_path / "memory.db") as db:
            for table in (
                "entity_catalog",
                "entity_aliases",
                "entity_mentions",
                "entity_name_evidence",
            ):
                async with db.execute(
                    (
                        f"SELECT COUNT(*) FROM {table} WHERE entity_id = ?"
                        if table != "entity_mentions"
                        else "SELECT COUNT(*) FROM entity_mentions WHERE resolved_entity_id = ?"
                    ),
                    ("person:private",),
                ) as cursor:
                    assert (await cursor.fetchone())[0] == 0
    finally:
        await memory.shutdown()


def _lease_runner(db_path: Path) -> DurableForgetRunner:
    return DurableForgetRunner(
        SimpleNamespace(
            memory_db_path=str(db_path),
            l1=None,
        )
    )


async def _create_lease_operation(
    repository: ForgetOperationRepository,
    *,
    event_id: str,
):
    return await repository.create_or_reuse(
        selector=ForgetSelector.known_events(
            [event_id],
            block_source_item=True,
        ),
        reason="test_forget_lease",
        reuse_completed=False,
    )


@pytest.mark.asyncio
async def test_startup_force_does_not_steal_a_live_runner_lease(
    tmp_path: Path,
) -> None:
    db_path = tmp_path / "memory.db"
    await apply_memory_shared_schema(str(db_path))
    runner_a = _lease_runner(db_path)
    runner_b = _lease_runner(db_path)
    operation = await _create_lease_operation(
        runner_a._repository,
        event_id="event-live-owner",
    )

    runner_a._repository.register_live_owner(runner_a._owner)
    try:
        claimed_a = await runner_a._repository.claim(
            operation.operation_id,
            owner=runner_a._owner,
            lease_seconds=300,
            force=False,
        )
        assert claimed_a is not None

        runner_b._repository.register_live_owner(runner_b._owner)
        try:
            claimed_b = await runner_b._repository.claim(
                operation.operation_id,
                owner=runner_b._owner,
                lease_seconds=300,
                force=True,
            )
        finally:
            runner_b._repository.unregister_live_owner(runner_b._owner)

        assert claimed_b is None
        current = await runner_a._repository.get(operation.operation_id)
        assert current is not None
        assert current.lease_token == claimed_a.lease_token
    finally:
        runner_a._repository.unregister_live_owner(runner_a._owner)


@pytest.mark.asyncio
async def test_expired_lease_takeover_fences_every_old_checkpoint(
    tmp_path: Path,
) -> None:
    db_path = tmp_path / "memory.db"
    await apply_memory_shared_schema(str(db_path))
    repository_a = ForgetOperationRepository(str(db_path))
    repository_b = ForgetOperationRepository(str(db_path))
    operation = await _create_lease_operation(
        repository_a,
        event_id="event-expired-owner",
    )
    claimed_a = await repository_a.claim(
        operation.operation_id,
        owner="runner-a",
        lease_seconds=300,
        force=False,
    )
    assert claimed_a is not None

    async with aiosqlite.connect(db_path) as db:
        await db.execute(
            "UPDATE memory_forget_operations SET lease_expires_at = ? " "WHERE operation_id = ?",
            (time.time() - 1, operation.operation_id),
        )
        await db.commit()

    claimed_b = await repository_b.claim(
        operation.operation_id,
        owner="runner-b",
        lease_seconds=300,
        force=False,
    )
    assert claimed_b is not None
    assert claimed_b.lease_token == claimed_a.lease_token + 1

    with pytest.raises(RuntimeError, match="lease was lost"):
        await repository_a.persist_selector_references(
            operation.operation_id,
            references=(
                ForgetReference(
                    "",
                    "barrier",
                    "exact_event",
                    "stale-runner-event",
                ),
            ),
            reason="stale_runner_write",
        )
    with pytest.raises(RuntimeError, match="lease was lost"):
        await repository_a.finish_selection(operation.operation_id)

    async with aiosqlite.connect(db_path) as db:
        assert (
            await (
                await db.execute(
                    "SELECT 1 FROM memory_source_event_tombstones "
                    "WHERE event_id = 'stale-runner-event'"
                )
            ).fetchone()
            is None
        )
        assert (
            await (
                await db.execute(
                    "SELECT 1 FROM memory_forget_operation_refs "
                    "WHERE operation_id = ? AND source_ref = 'stale-runner-event'",
                    (operation.operation_id,),
                )
            ).fetchone()
            is None
        )


@pytest.mark.asyncio
async def test_heartbeat_renews_a_long_running_forget_lease(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import magi.memory.forgetting.runner as runner_module

    db_path = tmp_path / "memory.db"
    await apply_memory_shared_schema(str(db_path))
    runner = _lease_runner(db_path)
    operation = await _create_lease_operation(
        runner._repository,
        event_id="event-heartbeat",
    )
    monkeypatch.setattr(runner_module, "_LEASE_SECONDS", 0.06)
    runner._repository.register_live_owner(runner._owner)
    try:
        claimed = await runner._repository.claim(
            operation.operation_id,
            owner=runner._owner,
            lease_seconds=runner_module._LEASE_SECONDS,
            force=False,
        )
        assert claimed is not None
        before = await _operation_row(db_path)
        before_expiry = float(before["lease_expires_at"])

        async def slow_run(operation_id: str):
            await asyncio.sleep(0.08)
            current = await runner._repository.get(operation_id)
            assert current is not None
            return current

        monkeypatch.setattr(runner, "_run_claimed", slow_run)
        await runner._run_claimed_with_lease(operation.operation_id)

        after = await _operation_row(db_path)
        assert float(after["lease_expires_at"]) > before_expiry
    finally:
        runner._repository.unregister_live_owner(runner._owner)


@pytest.mark.asyncio
async def test_heartbeat_loss_cancels_the_stale_runner(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import magi.memory.forgetting.runner as runner_module

    db_path = tmp_path / "memory.db"
    await apply_memory_shared_schema(str(db_path))
    runner = _lease_runner(db_path)
    operation = await _create_lease_operation(
        runner._repository,
        event_id="event-lease-loss",
    )
    monkeypatch.setattr(runner_module, "_LEASE_SECONDS", 0.03)
    runner._repository.register_live_owner(runner._owner)
    try:
        claimed = await runner._repository.claim(
            operation.operation_id,
            owner=runner._owner,
            lease_seconds=runner_module._LEASE_SECONDS,
            force=False,
        )
        assert claimed is not None
        started = asyncio.Event()
        cancelled = asyncio.Event()

        async def blocked_run(_operation_id: str):
            started.set()
            try:
                await asyncio.Event().wait()
            finally:
                cancelled.set()

        monkeypatch.setattr(runner, "_run_claimed", blocked_run)
        run_task = asyncio.create_task(runner._run_claimed_with_lease(operation.operation_id))
        await asyncio.wait_for(started.wait(), timeout=1)

        async with aiosqlite.connect(db_path) as db:
            await db.execute(
                """
                UPDATE memory_forget_operations
                SET lease_owner = 'replacement-runner',
                    lease_token = lease_token + 1,
                    lease_expires_at = ?
                WHERE operation_id = ?
                """,
                (time.time() + 300, operation.operation_id),
            )
            await db.commit()

        with pytest.raises(RuntimeError, match="lease was lost"):
            await asyncio.wait_for(run_task, timeout=1)
        assert cancelled.is_set()
    finally:
        runner._repository.unregister_live_owner(runner._owner)


@pytest.mark.asyncio
async def test_startup_recovery_processes_more_than_one_page(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    db_path = tmp_path / "memory.db"
    await apply_memory_shared_schema(str(db_path))
    runner = _lease_runner(db_path)
    created_at = 1_700_000_000.0
    rows = []
    for index in range(1001):
        selector = ForgetSelector.known_events(
            [f"event-recovery-{index:04d}"],
            block_source_item=True,
        )
        rows.append(
            (
                f"forget:recovery-{index:04d}",
                selector.kind,
                selector.selector_hash,
                selector.canonical_json,
                "test_paginated_recovery",
                created_at,
                created_at,
            )
        )
    async with aiosqlite.connect(db_path) as db:
        await db.executemany(
            """
            INSERT INTO memory_forget_operations(
                operation_id, selector_kind, selector_hash,
                selector_json, reason, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            rows,
        )
        await db.commit()

    async def complete_claimed(operation_id: str):
        completed = await runner._repository.mark_completed(operation_id)
        runner._repository.release_local_claim(operation_id)
        return completed

    monkeypatch.setattr(runner, "_run_claimed_with_lease", complete_claimed)
    stats = await runner.recover_pending(
        force=True,
        fail_on_barrier_error=True,
    )

    assert stats == {"found": 1001, "completed": 1001, "failed": 0}
    async with aiosqlite.connect(db_path) as db:
        async with db.execute(
            "SELECT COUNT(*) FROM memory_forget_operations WHERE status = 'completed'"
        ) as cursor:
            assert (await cursor.fetchone())[0] == 1001


@pytest.mark.asyncio
async def test_completion_waits_for_run_when_heartbeat_observes_terminal_state(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import magi.memory.forgetting.runner as runner_module

    db_path = tmp_path / "memory.db"
    await apply_memory_shared_schema(str(db_path))
    runner = _lease_runner(db_path)
    operation = await _create_lease_operation(
        runner._repository,
        event_id="event-completion-heartbeat-race",
    )
    monkeypatch.setattr(runner_module, "_LEASE_SECONDS", 0.03)
    runner._repository.register_live_owner(runner._owner)
    try:
        claimed = await runner._repository.claim(
            operation.operation_id,
            owner=runner._owner,
            lease_seconds=runner_module._LEASE_SECONDS,
            force=False,
        )
        assert claimed is not None
        heartbeat_observed_completion = asyncio.Event()
        original_renew_claim = runner._repository.renew_claim

        async def observed_renew_claim(
            operation_id: str,
            *,
            lease_seconds: float,
        ) -> bool:
            renewed = await original_renew_claim(
                operation_id,
                lease_seconds=lease_seconds,
            )
            if not renewed:
                heartbeat_observed_completion.set()
            return renewed

        async def complete_then_yield(operation_id: str):
            completed = await runner._repository.mark_completed(operation_id)
            await asyncio.wait_for(heartbeat_observed_completion.wait(), timeout=1)
            return completed

        monkeypatch.setattr(runner._repository, "renew_claim", observed_renew_claim)
        monkeypatch.setattr(runner, "_run_claimed", complete_then_yield)

        completed = await asyncio.wait_for(
            runner._run_claimed_with_lease(operation.operation_id),
            timeout=1,
        )
        assert completed.completed is True
        assert operation.operation_id not in runner._repository._claims
        assert operation.operation_id not in runner._repository._locally_completed
    finally:
        runner._repository.unregister_live_owner(runner._owner)
