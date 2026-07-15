from __future__ import annotations

import asyncio
import time

import aiosqlite
import pytest

from _shared.memory_schema import apply_memory_shared_schema
from magi.memory.derivation_revision import DerivationRevisionChangedError
from magi.memory.l2.models import ReconciledTraitOutcome
from magi.memory.l2.corrections.derivations import CorrectionDerivationRunner
from magi.memory.l2.corrections.models import ApplyAssertionCorrectionCommand, CorrectionKind
from magi.memory.l2.corrections.repository import MemoryCorrectionRepository
from magi.memory.l2.corrections.service import MemoryCorrectionService
from magi.memory.l2.store import L2CognitionStore
from magi.memory.l3.models import L3Candidate, StateChangePacket
from magi.memory.l3.correction_derivation import L3CorrectionDerivationService
from magi.memory.l3.state_change_service import StateChangeService
from magi.memory.l3.summary_store import L3SummaryStore
from magi.memory.store_l3_insights import L3InsightsMixin


class _L1:
    async def get_memory_event(self, event_id: str):
        return {
            "event_id": event_id,
            "retention_class": "permanent",
            "memory_domain": "user_authored",
            "content": event_id,
        }


class _InsightHost(L3InsightsMixin):
    def __init__(self, *, l2: L2CognitionStore, l3: L3SummaryStore) -> None:
        self.l1 = _L1()
        self.l2 = l2
        self.l3 = l3


async def _seed_assertion(store: L2CognitionStore, *, now: float) -> str:
    return await store.upsert_assertion_candidate(
        {
            "entity_id": "user:u1",
            "entity_type": "user",
            "trait_family": "stress",
            "trait_name": "stress_level",
            "trait_value": "high",
            "confidence_score": 0.9,
            "evidence_events": ["evt-old-1", "evt-old-2"],
            "volatility_index": 0.2,
            "source_domain": "conversation",
            "inference_depth": "semantic",
            "validation_state": "stable",
            "first_inferred_at": now - 72 * 3600,
            "last_validated_at": now,
            "temporal_scope": "persistent",
            "natural_summary": "Work stress has stayed high.",
        }
    )


async def test_correction_only_rebuilds_dependent_l3_insight(tmp_path) -> None:
    db_path = str(tmp_path / "memory.db")
    await apply_memory_shared_schema(db_path)
    l2 = L2CognitionStore(db_path=db_path)
    l3 = L3SummaryStore(db_path=db_path, vector_enabled=False)
    await l2.initialize()
    await l3.initialize()

    now = time.time()
    assertion_id = await _seed_assertion(l2, now=now)
    candidate = await StateChangeService().build_candidate(
        StateChangePacket(
            entity_id="user:u1",
            entity_type="user",
            outcomes=[
                ReconciledTraitOutcome(
                    entity_id="user:u1",
                    entity_type="user",
                    trait_name="stress_level",
                    winning_value="high",
                    status="stable",
                    confidence=0.9,
                    evidence_event_ids=["evt-old-1", "evt-old-2"],
                    time_span_hours=72.0,
                    stability_kind="stable_pattern",
                    recommended_snapshot_field="core_traits",
                    natural_summary="Work stress has stayed high.",
                    trait_family="stress",
                    source_assertion_id=assertion_id,
                )
            ],
        )
    )
    assert candidate is not None
    insight = await _InsightHost(l2=l2, l3=l3).persist_l3_candidate(candidate=candidate)
    assert insight is not None
    temporal = await l3.upsert_candidate(
        candidate=L3Candidate(
            summary_type="temporal",
            summary_category="day",
            content="A real event happened today.",
            source_event_ids=["evt-unrelated"],
        )
    )

    async with aiosqlite.connect(db_path) as db:
        async with db.execute(
            """
            SELECT source_id FROM memory_derivation_dependencies
            WHERE artifact_kind = 'l3_insight' AND artifact_id = ?
            """,
            (insight["summary_id"],),
        ) as cursor:
            assert await cursor.fetchone() == (assertion_id,)

    corrected = await l2.apply_assertion_correction(
        assertion_id=assertion_id,
        request_id="l3-correction",
        actor_id="user:u1",
        correction_kind="situation_changed",
        replacement_value="low",
        effective_at=now - 48 * 3600,
        source_event_id="evt-new",
    )

    assert corrected is not None
    assert await l3.get_summary_by_id(insight["summary_id"]) is None
    await l2.process_memory_correction_jobs(limit=10)
    current_insight = await l3.get_summary_by_id(insight["summary_id"])
    current_temporal = await l3.get_summary_by_id(temporal["summary_id"])
    assert current_insight is not None
    assert current_insight["derivation_state"] == "current"
    assert current_insight["source_revision"] == 1
    assert "high" not in current_insight["content"].lower()
    assert "low" in current_insight["content"].lower()
    assert current_temporal is not None
    assert current_temporal["content"] == "A real event happened today."
    assert current_temporal["source_revision"] == 0

    replacement_id = corrected["current_assertion"]["assertion_id"]
    async with aiosqlite.connect(db_path) as db:
        async with db.execute(
            """
            SELECT source_id FROM memory_derivation_dependencies
            WHERE artifact_kind = 'l3_insight' AND artifact_id = ?
            """,
            (insight["summary_id"],),
        ) as cursor:
            assert await cursor.fetchone() == (replacement_id,)


async def test_newer_correction_supersedes_paused_l3_rebuild(
    tmp_path,
    monkeypatch,
) -> None:
    db_path = str(tmp_path / "memory.db")
    await apply_memory_shared_schema(db_path)
    l2 = L2CognitionStore(db_path=db_path)
    l3 = L3SummaryStore(db_path=db_path, vector_enabled=False)
    await l2.initialize()
    await l3.initialize()

    now = time.time()
    assertion_id = await _seed_assertion(l2, now=now)
    candidate = await StateChangeService().build_candidate(
        StateChangePacket(
            entity_id="user:u1",
            entity_type="user",
            outcomes=[
                ReconciledTraitOutcome(
                    entity_id="user:u1",
                    entity_type="user",
                    trait_name="stress_level",
                    winning_value="high",
                    status="stable",
                    confidence=0.9,
                    evidence_event_ids=["evt-old-1", "evt-old-2"],
                    time_span_hours=72.0,
                    stability_kind="stable_pattern",
                    recommended_snapshot_field="core_traits",
                    natural_summary="Work stress has stayed high.",
                    trait_family="stress",
                    source_assertion_id=assertion_id,
                )
            ],
        )
    )
    assert candidate is not None
    insight = await _InsightHost(l2=l2, l3=l3).persist_l3_candidate(candidate=candidate)
    assert insight is not None

    first = await l2.apply_assertion_correction(
        assertion_id=assertion_id,
        request_id="l3-race-first",
        actor_id="user:u1",
        correction_kind="situation_changed",
        replacement_value="medium",
        effective_at=now - 48 * 3600,
        source_event_id="evt-medium",
    )
    assert first is not None

    entered = asyncio.Event()
    release = asyncio.Event()
    original_build_candidate = L3CorrectionDerivationService._candidate_from_current_state

    async def _pause_medium_candidate(self, metadata, outcomes):
        rebuilt = await original_build_candidate(self, metadata, outcomes)
        if any(outcome.winning_value == "medium" for outcome in outcomes):
            entered.set()
            await release.wait()
        return rebuilt

    monkeypatch.setattr(
        L3CorrectionDerivationService,
        "_candidate_from_current_state",
        _pause_medium_candidate,
    )

    runner = CorrectionDerivationRunner(db_path=db_path, l2_store=l2)
    async with aiosqlite.connect(db_path) as db:
        await db.execute(
            """
            UPDATE memory_derivation_jobs
            SET status = 'completed'
            WHERE target_revision = 1 AND job_kind != 'l3_insight'
            """
        )
        await db.commit()

    first_run = asyncio.create_task(runner.run_pending(limit=1))
    await asyncio.wait_for(entered.wait(), timeout=2.0)
    second = await l2.apply_assertion_correction(
        assertion_id=first["current_assertion"]["assertion_id"],
        request_id="l3-race-second",
        actor_id="user:u1",
        correction_kind="situation_changed",
        replacement_value="low",
        effective_at=now - 24 * 3600,
        source_event_id="evt-low",
    )
    assert second is not None
    release.set()
    assert await first_run == {"completed": 0, "failed": 0, "superseded": 1}

    async with aiosqlite.connect(db_path) as db:
        async with db.execute(
            "SELECT content, source_revision, derivation_state FROM summaries WHERE summary_id = ?",
            (insight["summary_id"],),
        ) as cursor:
            stale = await cursor.fetchone()
        async with db.execute(
            """
            SELECT status FROM memory_derivation_jobs
            WHERE job_kind = 'l3_insight' AND target_key = 'user:u1'
              AND target_revision = 2
            """
        ) as cursor:
            replacement_job = await cursor.fetchone()
    assert stale is not None
    assert stale[1:] == (0, "stale")
    assert "medium" not in stale[0].lower()
    assert replacement_job == ("pending",)

    await runner.run_pending(limit=10)
    current = await l3.get_summary_by_id(insight["summary_id"])
    assert current is not None
    assert current["source_revision"] == 2
    assert current["derivation_state"] == "current"
    assert "medium" not in current["content"].lower()
    assert "low" in current["content"].lower()
    async with aiosqlite.connect(db_path) as db:
        async with db.execute(
            """
            SELECT source_id, source_revision
            FROM memory_derivation_dependencies
            WHERE artifact_kind = 'l3_insight' AND artifact_id = ?
            """,
            (insight["summary_id"],),
        ) as cursor:
            assert await cursor.fetchone() == (
                second["current_assertion"]["assertion_id"],
                2,
            )


async def test_l3_rebuild_guards_every_dependency_subject(
    tmp_path,
    monkeypatch,
) -> None:
    db_path = str(tmp_path / "memory.db")
    await apply_memory_shared_schema(db_path)
    l2 = L2CognitionStore(db_path=db_path)
    l3 = L3SummaryStore(db_path=db_path, vector_enabled=False)
    await l2.initialize()
    await l3.initialize()
    now = time.time()
    user_assertion_id = await _seed_assertion(l2, now=now)
    person_assertion_id = await l2.upsert_assertion_candidate(
        {
            "entity_id": "person:p1",
            "entity_type": "person",
            "trait_family": "mood",
            "trait_name": "mood",
            "trait_value": "calm",
            "confidence_score": 0.9,
            "evidence_events": ["evt-person-1", "evt-person-2"],
            "volatility_index": 0.1,
            "source_domain": "conversation",
            "inference_depth": "semantic",
            "validation_state": "stable",
            "first_inferred_at": now - 72 * 3600,
            "last_validated_at": now,
            "temporal_scope": "persistent",
            "natural_summary": "The person has stayed calm.",
        }
    )
    outcomes = [
        ReconciledTraitOutcome(
            entity_id="user:u1",
            entity_type="user",
            trait_name="stress_level",
            winning_value="high",
            status="stable",
            confidence=0.9,
            evidence_event_ids=["evt-old-1", "evt-old-2"],
            time_span_hours=72.0,
            stability_kind="stable_pattern",
            recommended_snapshot_field="core_traits",
            natural_summary="Work stress has stayed high.",
            trait_family="stress",
            source_assertion_id=user_assertion_id,
        ),
        ReconciledTraitOutcome(
            entity_id="person:p1",
            entity_type="person",
            trait_name="mood",
            winning_value="calm",
            status="stable",
            confidence=0.9,
            evidence_event_ids=["evt-person-1", "evt-person-2"],
            time_span_hours=72.0,
            stability_kind="stable_pattern",
            recommended_snapshot_field="core_traits",
            natural_summary="The person has stayed calm.",
            trait_family="mood",
            source_assertion_id=person_assertion_id,
        ),
    ]
    candidate = await StateChangeService().build_candidate(
        StateChangePacket(
            entity_id="user:u1",
            entity_type="user",
            outcomes=outcomes,
        )
    )
    assert candidate is not None
    insight = await l3.upsert_candidate(candidate=candidate)
    repository = MemoryCorrectionRepository(db_path)
    dependencies = [
        ("assertion", user_assertion_id, "user:u1", 0),
        ("assertion", person_assertion_id, "person:p1", 0),
    ]
    await repository.replace_artifact_dependencies(
        artifact_kind="l3_insight",
        artifact_id=str(insight["summary_id"]),
        dependencies=dependencies,
    )
    async with aiosqlite.connect(db_path) as db:
        await db.execute(
            "UPDATE summaries SET derivation_state = 'stale' WHERE summary_id = ?",
            (insight["summary_id"],),
        )
        await db.commit()

    original_build_candidate = L3CorrectionDerivationService._candidate_from_current_state

    async def _change_related_subject(self, metadata, current_outcomes):
        rebuilt = await original_build_candidate(self, metadata, current_outcomes)
        async with aiosqlite.connect(db_path) as db:
            await db.execute("BEGIN IMMEDIATE")
            await repository.bump_subject_revision(db, subject_key="person:p1")
            await db.commit()
        return rebuilt

    monkeypatch.setattr(
        L3CorrectionDerivationService,
        "_candidate_from_current_state",
        _change_related_subject,
    )

    with pytest.raises(DerivationRevisionChangedError):
        await L3CorrectionDerivationService(
            db_path=db_path,
            l2_store=l2,
        ).rebuild_subject("user:u1", expected_revision=0)

    async with aiosqlite.connect(db_path) as db:
        async with db.execute(
            "SELECT content, source_revision, derivation_state FROM summaries WHERE summary_id = ?",
            (insight["summary_id"],),
        ) as cursor:
            unchanged = await cursor.fetchone()
    assert unchanged == (candidate.content, 0, "stale")


async def test_stale_l3_insight_is_hidden_when_rebuild_has_no_current_claim(
    tmp_path,
) -> None:
    db_path = str(tmp_path / "memory.db")
    await apply_memory_shared_schema(db_path)
    l2 = L2CognitionStore(db_path=db_path)
    l3 = L3SummaryStore(db_path=db_path, vector_enabled=False)
    await l2.initialize()
    await l3.initialize()
    now = time.time()
    assertion_id = await _seed_assertion(l2, now=now)
    candidate = await StateChangeService().build_candidate(
        StateChangePacket(
            entity_id="user:u1",
            entity_type="user",
            outcomes=[
                ReconciledTraitOutcome(
                    entity_id="user:u1",
                    entity_type="user",
                    trait_name="stress_level",
                    winning_value="high",
                    status="stable",
                    confidence=0.9,
                    evidence_event_ids=["evt-old-1", "evt-old-2"],
                    time_span_hours=72.0,
                    stability_kind="stable_pattern",
                    recommended_snapshot_field="core_traits",
                    trait_family="stress",
                    source_assertion_id=assertion_id,
                )
            ],
        )
    )
    assert candidate is not None
    insight = await _InsightHost(l2=l2, l3=l3).persist_l3_candidate(candidate=candidate)
    assert insight is not None

    await MemoryCorrectionService(db_path).apply_assertion_correction(
        ApplyAssertionCorrectionCommand(
            assertion_id=assertion_id,
            request_id="l3-retire",
            actor_id="user:u1",
            correction_kind=CorrectionKind.RECORD_ERROR,
        )
    )

    assert await l3.get_summary_by_id(insight["summary_id"]) is None
    assert await l3.search_summaries(query="stress", limit=10) == []
    async with aiosqlite.connect(db_path) as db:
        async with db.execute(
            "SELECT derivation_state FROM summaries WHERE summary_id = ?",
            (insight["summary_id"],),
        ) as cursor:
            assert await cursor.fetchone() == ("stale",)

    await CorrectionDerivationRunner(
        db_path=db_path,
        l2_store=l2,
    ).run_pending(limit=10)
    async with aiosqlite.connect(db_path) as db:
        async with db.execute(
            "SELECT derivation_state FROM summaries WHERE summary_id = ?",
            (insight["summary_id"],),
        ) as cursor:
            assert await cursor.fetchone() == ("retired",)


async def test_relationship_dependent_insight_is_retired_without_touching_others(
    tmp_path,
) -> None:
    db_path = str(tmp_path / "memory.db")
    await apply_memory_shared_schema(db_path)
    l2 = L2CognitionStore(db_path=db_path)
    l3 = L3SummaryStore(db_path=db_path, vector_enabled=False)
    await l2.initialize()
    await l3.initialize()
    triple_id = await l2.upsert_knowledge_edge(
        subject_id="user:u1",
        subject_type="user",
        predicate="CURRENT_LIVES_IN",
        object_id="place:hangzhou",
        object_type="place",
        evidence_event_ids=["evt-edge"],
        confidence=0.9,
        observed_at=time.time(),
        source_type="conversation",
        extraction_method="explicit",
    )
    insight = await _InsightHost(l2=l2, l3=l3).persist_l3_candidate(
        candidate=L3Candidate(
            summary_type="insight",
            summary_category="relationship",
            content="The user currently lives in Hangzhou.",
            source_event_ids=["evt-edge"],
            insight_key="relationship:user:u1:home",
            claim_dependencies=[
                {
                    "source_kind": "edge",
                    "source_id": triple_id,
                    "subject_key": "user:u1",
                }
            ],
        )
    )
    assert insight is not None

    await l2.apply_relationship_correction(
        triple_id=triple_id,
        request_id="edge-insight-correction",
        actor_id="user:u1",
        correction_kind="record_error",
    )

    assert await l3.get_summary_by_id(insight["summary_id"]) is None
    await l2.process_memory_correction_jobs(limit=10)
    async with aiosqlite.connect(db_path) as db:
        async with db.execute(
            "SELECT derivation_state FROM summaries WHERE summary_id = ?",
            (insight["summary_id"],),
        ) as cursor:
            assert await cursor.fetchone() == ("retired",)
