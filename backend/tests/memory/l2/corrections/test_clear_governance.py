from __future__ import annotations

import asyncio
import time

import aiosqlite

from _shared.memory_schema import apply_memory_shared_schema
from magi.memory.l2.corrections.models import (
    ApplyAssertionCorrectionCommand,
    ApplyRelationshipCorrectionCommand,
    CorrectionKind,
)
from magi.memory.l2.corrections.relationship_service import RelationshipCorrectionService
from magi.memory.l2.corrections.service import MemoryCorrectionService
from magi.memory.l2.store import L2CognitionStore


def _assertion_candidate(*, now: float) -> dict[str, object]:
    return {
        "entity_id": "user:u1",
        "entity_type": "user",
        "trait_family": "preference_profile",
        "trait_name": "favorite_food",
        "trait_value": "ramen",
        "confidence_score": 0.9,
        "evidence_events": ["event-old"],
        "volatility_index": 0.1,
        "source_domain": "conversation",
        "inference_depth": "explicit",
        "validation_state": "stable",
        "first_inferred_at": now,
        "last_validated_at": now,
        "temporal_scope": "persistent",
    }


async def test_clear_removes_correction_history_rules_and_versions(tmp_path) -> None:
    db_path = str(tmp_path / "memory.db")
    await apply_memory_shared_schema(db_path)
    store = L2CognitionStore(db_path=db_path)
    await store.initialize()
    now = time.time()

    candidate = _assertion_candidate(now=now)
    assertion_id = await store.upsert_assertion_candidate(candidate)
    await MemoryCorrectionService(db_path).apply_assertion_correction(
        ApplyAssertionCorrectionCommand(
            assertion_id=assertion_id,
            request_id="clear-assertion",
            actor_id="user:u1",
            correction_kind=CorrectionKind.RECORD_ERROR,
            reason="Sensitive correction reason",
        )
    )

    triple_id = await store.upsert_knowledge_edge(
        subject_id="user:u1",
        subject_type="user",
        predicate="CURRENT_LIVES_IN",
        object_id="place:hangzhou",
        object_type="place",
        evidence_event_ids=["event-edge"],
        confidence=0.9,
        observed_at=now,
        source_type="conversation",
        extraction_method="explicit",
    )
    await RelationshipCorrectionService(db_path).apply(
        ApplyRelationshipCorrectionCommand(
            triple_id=triple_id,
            request_id="clear-edge",
            actor_id="user:u1",
            correction_kind=CorrectionKind.RECORD_ERROR,
        )
    )

    async with aiosqlite.connect(db_path) as db:
        await db.execute(
            """
            INSERT INTO memory_derivation_dependencies(
                artifact_kind, artifact_id, source_kind, source_id,
                subject_key, source_revision, created_at
            ) VALUES ('snapshot', 'user:u1', 'assertion', ?, 'user:u1', 1, ?)
            """,
            (assertion_id, now),
        )
        await db.commit()

    await store.clear()

    governed_tables = (
        "memory_derivation_dependencies",
        "memory_derivation_jobs",
        "memory_correction_rules",
        "memory_corrections",
        "memory_subject_revisions",
        "knowledge_graph_versions",
    )
    async with aiosqlite.connect(db_path) as db:
        for table in governed_tables:
            async with db.execute(f"SELECT COUNT(*) FROM {table}") as cursor:
                assert await cursor.fetchone() == (0,), table

    replayed_id = await store.upsert_assertion_candidate(candidate)
    current = await store.list_current_assertions(entity_id="user:u1")
    assert [item["assertion_id"] for item in current] == [replayed_id]


async def test_clear_waits_for_running_correction_work(tmp_path) -> None:
    db_path = str(tmp_path / "memory.db")
    await apply_memory_shared_schema(db_path)
    store = L2CognitionStore(db_path=db_path)
    await store.initialize()
    assertion_id = await store.upsert_assertion_candidate(
        _assertion_candidate(now=time.time())
    )
    correction = await MemoryCorrectionService(db_path).apply_assertion_correction(
        ApplyAssertionCorrectionCommand(
            assertion_id=assertion_id,
            request_id="clear-running",
            actor_id="user:u1",
            correction_kind=CorrectionKind.RECORD_ERROR,
            replacement_value="udon",
        )
    )
    assert correction is not None
    async with aiosqlite.connect(db_path) as db:
        await db.execute(
            """
            UPDATE memory_derivation_jobs
            SET status = 'completed'
            WHERE correction_id = ? AND job_kind != 'snapshot'
            """,
            (correction.correction.correction_id,),
        )
        await db.commit()

    started = asyncio.Event()
    release = asyncio.Event()

    async def pause_snapshot(_job) -> None:  # type: ignore[no-untyped-def]
        started.set()
        await release.wait()

    store.register_memory_correction_job_handler("snapshot", pause_snapshot)
    worker = asyncio.create_task(store.process_memory_correction_jobs(limit=1))
    await asyncio.wait_for(started.wait(), timeout=2)
    clearing = asyncio.create_task(store.clear())
    await asyncio.sleep(0.05)
    assert not clearing.done()

    release.set()
    await asyncio.gather(worker, clearing)

    async with aiosqlite.connect(db_path) as db:
        async with db.execute("SELECT COUNT(*) FROM memory_corrections") as cursor:
            assert await cursor.fetchone() == (0,)
        async with db.execute("SELECT COUNT(*) FROM memory_derivation_jobs") as cursor:
            assert await cursor.fetchone() == (0,)
