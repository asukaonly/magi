from __future__ import annotations

import json
import time
from unittest.mock import AsyncMock, patch

import aiosqlite
import pytest

from magi.memory.l2.corrections.current_claim import resolve_current_claim
from magi.memory.l2.corrections.models import CorrectionKind
from magi.memory.l2.retrieval.common import select_bounded_committed_candidates
from magi.user_profile.portrait_projection_builder import UserPortraitProjectionBuilder
from magi.user_profile.portrait_projection_repository import (
    UserPortraitProjectionRepository,
)
from magi.user_profile.projection_builder import UserProfileProjectionBuilder
from magi.user_profile.projection_repository import UserProfileProjectionRepository


async def _seed_profile_assertion(store) -> str:  # type: ignore[no-untyped-def]
    observed_at = time.time() - 60
    return await store.upsert_assertion_candidate(
        {
            "entity_id": "user:u1",
            "entity_type": "user",
            "trait_family": "communication_profile",
            "trait_name": "communication.address.preferred",
            "trait_value": "Old name",
            "confidence_score": 0.8,
            "evidence_events": ["event-old"],
            "volatility_index": 0.1,
            "source_domain": "conversation",
            "inference_depth": "semantic",
            "validation_state": "stable",
            "first_inferred_at": observed_at,
            "last_validated_at": observed_at,
            "temporal_scope": "persistent",
        }
    )


async def _seed_profile_views(store) -> None:  # type: ignore[no-untyped-def]
    await store.refresh_entity_snapshot(entity_id="user:u1", entity_type="user")
    profile = await UserProfileProjectionBuilder(store).build("u1")
    await UserProfileProjectionRepository(store.db_path).upsert(profile)
    portrait = await UserPortraitProjectionBuilder(
        store,
        profile_projection=profile,
    ).build("u1")
    await UserPortraitProjectionRepository(store.db_path).upsert(portrait)


async def _seed_relationship(store) -> str:  # type: ignore[no-untyped-def]
    return await store.upsert_knowledge_edge(
        subject_id="user:u1",
        subject_type="user",
        predicate="CURRENT_LIVES_IN",
        object_id="place:hangzhou",
        object_type="place",
        evidence_event_ids=["event-old-city"],
        confidence=0.8,
        observed_at=time.time() - 60,
        source_type="conversation",
        extraction_method="explicit",
    )


async def _transition_marker(db_path: str, correction_id: str) -> float | None:
    async with aiosqlite.connect(db_path) as db:
        async with db.execute(
            "SELECT transition_applied_at FROM memory_corrections WHERE correction_id = ?",
            (correction_id,),
        ) as cursor:
            row = await cursor.fetchone()
    assert row is not None
    return float(row[0]) if row[0] is not None else None


@pytest.mark.asyncio
async def test_future_assertion_refreshes_views_only_when_transition_is_due(
    l2_store_with_schema,
) -> None:
    store = l2_store_with_schema
    assertion_id = await _seed_profile_assertion(store)
    await _seed_profile_views(store)
    profile_repository = UserProfileProjectionRepository(store.db_path)
    portrait_repository = UserPortraitProjectionRepository(store.db_path)
    notify = AsyncMock()
    wakeup = AsyncMock()
    store.set_assertion_change_callback(notify)
    store.set_memory_correction_job_wakeup(wakeup)
    effective_at = time.time() + 600

    result = await store.apply_assertion_correction(
        assertion_id=assertion_id,
        request_id="future-assertion-transition",
        actor_id="user:u1",
        correction_kind=CorrectionKind.SITUATION_CHANGED,
        replacement_value="New name",
        effective_at=effective_at,
        audit_event_id="audit-future-assertion",
    )

    assert result is not None
    correction_id = result["correction"]["correction_id"]
    async with aiosqlite.connect(store.db_path) as db:
        await db.execute(
            """
            UPDATE memory_derivation_jobs
            SET status = 'completed'
            WHERE correction_id = ? AND job_kind = 'l1_audit'
            """,
            (correction_id,),
        )
        await db.commit()
    assert result["subject_revision"] is None
    assert await store.current_subject_revision("user:u1") == 0
    assert await store.get_memory_correction_derivation_state(correction_id) == "pending"
    assert await store.next_memory_correction_job_wakeup_at() == pytest.approx(effective_at)
    assert (await profile_repository.get("u1")).display_name == "Old name"
    assert await portrait_repository.get("u1") is not None
    assert await store.get_tom_snapshot(entity_id="user:u1", entity_type="user") is not None
    assert await _transition_marker(store.db_path, correction_id) is None
    notify.assert_not_awaited()
    wakeup.assert_awaited_once_with()

    with patch("time.time", return_value=effective_at + 1):
        stats = await store.process_memory_correction_jobs(limit=10)
        assert stats == {
            "completed": 3,
            "failed": 0,
            "superseded": 0,
            "activated": 1,
        }
        profile = await profile_repository.get("u1")
        portrait = await portrait_repository.get("u1")
        snapshot = await store.get_tom_snapshot(entity_id="user:u1", entity_type="user")
        assert profile is not None and profile.display_name == "New name"
        assert portrait is not None and "Old name" not in str(portrait.model_dump())
        assert snapshot is not None and "Old name" not in str(snapshot)

    assert await store.current_subject_revision("user:u1") == 1
    assert await store.get_memory_correction_derivation_state(correction_id) == "completed"
    assert await _transition_marker(store.db_path, correction_id) == pytest.approx(effective_at + 1)


@pytest.mark.asyncio
async def test_future_relationship_transition_is_idempotent(
    l2_store_with_schema,
) -> None:
    store = l2_store_with_schema
    triple_id = await _seed_relationship(store)
    original_snapshot = await store.refresh_entity_snapshot(
        entity_id="user:u1",
        entity_type="user",
    )
    assert original_snapshot is not None and "place:hangzhou" in str(original_snapshot)
    effective_at = time.time() + 600

    result = await store.apply_relationship_correction(
        triple_id=triple_id,
        request_id="future-relationship-transition",
        actor_id="user:u1",
        correction_kind=CorrectionKind.SITUATION_CHANGED,
        replacement={"object_id": "place:shanghai", "object_type": "place"},
        effective_at=effective_at,
    )

    assert result is not None
    correction_id = result["correction"]["correction_id"]
    assert result["subject_revision"] is None
    assert await store.current_subject_revision("user:u1") == 0
    assert await store.current_subject_revision("place:hangzhou") == 0
    assert await store.current_subject_revision("place:shanghai") == 0
    assert await store.get_memory_correction_derivation_state(correction_id) == "pending"
    before_due = await store.get_tom_snapshot(entity_id="user:u1", entity_type="user")
    assert before_due is not None and "place:hangzhou" in str(before_due)

    with patch("time.time", return_value=effective_at + 1):
        first = await store.process_memory_correction_jobs(limit=10)
        assert first["activated"] == 1
        assert first["failed"] == 0
        transitioned = await store.get_tom_snapshot(
            entity_id="user:u1",
            entity_type="user",
        )
        assert transitioned is not None
        current_outgoing = transitioned["relationship_topology"]["outgoing"]
        assert [item["object_id"] for item in current_outgoing] == ["place:shanghai"]
        assert any(
            "place:hangzhou" in json.dumps(entry["from"])
            and "place:shanghai" in json.dumps(entry["to"])
            for entry in transitioned["relationship_history"]
        )

        second = await store.process_memory_correction_jobs(limit=10)
        assert second == {
            "completed": 0,
            "failed": 0,
            "superseded": 0,
            "activated": 0,
        }

    assert await store.current_subject_revision("user:u1") == 1
    assert await store.current_subject_revision("place:hangzhou") == 1
    assert await store.current_subject_revision("place:shanghai") == 1
    assert await store.get_memory_correction_derivation_state(correction_id) == "completed"


@pytest.mark.asyncio
async def test_due_assertion_waits_for_atomic_transition_but_forecast_is_available(
    l2_store_with_schema,
) -> None:
    store = l2_store_with_schema
    assertion_id = await _seed_profile_assertion(store)
    effective_at = time.time() + 600
    result = await store.apply_assertion_correction(
        assertion_id=assertion_id,
        request_id="due-assertion-committed-read",
        actor_id="user:u1",
        correction_kind=CorrectionKind.SITUATION_CHANGED,
        replacement_value="New name",
        effective_at=effective_at,
    )

    with patch("time.time", return_value=effective_at + 1):
        committed = await store.list_current_assertions(entity_id="user:u1")
        forecast = await store.list_current_assertions(
            entity_id="user:u1",
            effective_at=effective_at + 1,
        )
        current_claim = await resolve_current_claim(
            store.db_path,
            correction=result["correction"],
        )
        processed = await store.process_memory_correction_jobs(limit=20)
        transitioned = await store.list_current_assertions(entity_id="user:u1")

    assert [item["trait_value"] for item in committed] == ["Old name"]
    assert [item["trait_value"] for item in forecast] == ["New name"]
    assert current_claim is not None
    assert current_claim["trait_value"] == "Old name"
    assert processed["activated"] == 1
    assert [item["trait_value"] for item in transitioned] == ["New name"]


@pytest.mark.asyncio
async def test_cancelled_due_assertion_keeps_original_committed_claim(
    l2_store_with_schema,
) -> None:
    store = l2_store_with_schema
    assertion_id = await _seed_profile_assertion(store)
    effective_at = time.time() + 600
    result = await store.apply_assertion_correction(
        assertion_id=assertion_id,
        request_id="cancelled-due-assertion-committed-read",
        actor_id="user:u1",
        correction_kind=CorrectionKind.SITUATION_CHANGED,
        replacement_value="New name",
        effective_at=effective_at,
    )
    await store.forget_time_range(
        start=effective_at - 1,
        end=effective_at + 1,
    )

    with patch("time.time", return_value=effective_at + 1):
        current_claim = await resolve_current_claim(
            store.db_path,
            correction=result["correction"],
        )
        committed = await store.list_current_assertions(entity_id="user:u1")

    assert current_claim is not None
    assert current_claim["assertion_id"] == assertion_id
    assert [item["assertion_id"] for item in committed] == [assertion_id]


@pytest.mark.parametrize(
    ("final_object_id", "request_suffix"),
    [
        ("place:hangzhou", "return"),
        ("place:beijing", "advance"),
    ],
)
@pytest.mark.asyncio
async def test_due_uncommitted_relationship_chain_keeps_committed_root(
    l2_store_with_schema,
    final_object_id: str,
    request_suffix: str,
) -> None:
    store = l2_store_with_schema
    original_id = await _seed_relationship(store)
    original = await store.get_relationship(triple_id=original_id)
    assert original is not None
    first_at = time.time() + 600
    second_at = first_at + 600
    first = await store.apply_relationship_correction(
        triple_id=original_id,
        request_id=f"committed-chain-first-{request_suffix}",
        actor_id="user:u1",
        correction_kind=CorrectionKind.SITUATION_CHANGED,
        replacement={"object_id": "place:shanghai", "object_type": "place"},
        effective_at=first_at,
    )
    assert first["current_relationship"]["triple_id"] == original_id
    second = await store.apply_relationship_correction(
        triple_id=first["correction"]["replacement_target_id"],
        request_id=f"committed-chain-second-{request_suffix}",
        actor_id="user:u1",
        correction_kind=CorrectionKind.SITUATION_CHANGED,
        replacement={"object_id": final_object_id, "object_type": "place"},
        effective_at=second_at,
    )
    assert second["current_relationship"]["triple_id"] == original_id

    with patch("time.time", return_value=second_at + 1):
        current = await store.list_current_relationships(subject_id="user:u1")
        batched = await store.batch_list_current_relationships(
            entity_ids=["user:u1"],
        )
        both_batched = await store.batch_list_current_relationships(
            entity_ids=["user:u1", "place:hangzhou"],
            direction="both",
        )
        forecast = await store.list_current_relationships(
            subject_id="user:u1",
            effective_at=second_at + 1,
        )
        current_claim = await resolve_current_claim(
            store.db_path,
            correction=second["correction"],
        )
        retried_first = await store.apply_relationship_correction(
            triple_id=original_id,
            request_id=f"committed-chain-first-{request_suffix}",
            actor_id="user:u1",
            correction_kind=CorrectionKind.SITUATION_CHANGED,
            replacement={"object_id": "place:shanghai", "object_type": "place"},
            effective_at=first_at,
        )

    assert [item["triple_id"] for item in current] == [original_id]
    assert [item["triple_id"] for item in batched["user:u1"]] == [original_id]
    assert [item["triple_id"] for item in both_batched["user:u1"]] == [original_id]
    assert [item["triple_id"] for item in both_batched["place:hangzhou"]] == [original_id]
    assert current_claim is not None
    assert current_claim["triple_id"] == original_id
    assert retried_first is not None
    assert retried_first["created"] is False
    assert retried_first["current_relationship"]["triple_id"] == original_id
    for committed in (
        current[0],
        batched["user:u1"][0],
        both_batched["user:u1"][0],
        both_batched["place:hangzhou"][0],
        current_claim,
        retried_first["current_relationship"],
    ):
        evidence = committed["evidence_event_ids"]
        if isinstance(evidence, str):
            evidence = json.loads(evidence)
        assert evidence == ["event-old-city"]
        assert float(committed["confidence"]) == pytest.approx(original["confidence"])
        assert float(committed["valid_from"]) == pytest.approx(original["valid_from"])
        assert float(committed["valid_from"]) < first_at
    assert [item["triple_id"] for item in forecast] == [
        second["correction"]["replacement_target_id"]
    ]


@pytest.mark.parametrize(
    ("final_value", "request_suffix"),
    [
        ("Old name", "return"),
        ("Newest name", "advance"),
    ],
)
@pytest.mark.asyncio
async def test_due_uncommitted_assertion_chain_keeps_committed_root(
    l2_store_with_schema,
    final_value: str,
    request_suffix: str,
) -> None:
    store = l2_store_with_schema
    original_id = await _seed_profile_assertion(store)
    original = await store.get_tom_assertion(assertion_id=original_id)
    assert original is not None
    first_at = time.time() + 600
    second_at = first_at + 600
    first = await store.apply_assertion_correction(
        assertion_id=original_id,
        request_id=f"committed-assertion-chain-first-{request_suffix}",
        actor_id="user:u1",
        correction_kind=CorrectionKind.SITUATION_CHANGED,
        replacement_value="New name",
        effective_at=first_at,
    )
    assert first["current_assertion"]["assertion_id"] == original_id
    second = await store.apply_assertion_correction(
        assertion_id=first["correction"]["replacement_target_id"],
        request_id=f"committed-assertion-chain-second-{request_suffix}",
        actor_id="user:u1",
        correction_kind=CorrectionKind.SITUATION_CHANGED,
        replacement_value=final_value,
        effective_at=second_at,
    )
    assert second["current_assertion"]["assertion_id"] == original_id

    with patch("time.time", return_value=second_at + 1):
        current = await store.list_current_assertions(entity_id="user:u1")
        batched = await store.batch_list_current_assertions(
            entity_ids=["user:u1"],
        )
        forecast = await store.list_current_assertions(
            entity_id="user:u1",
            effective_at=second_at + 1,
        )
        current_claim = await resolve_current_claim(
            store.db_path,
            correction=second["correction"],
        )
        retried_first = await store.apply_assertion_correction(
            assertion_id=original_id,
            request_id=f"committed-assertion-chain-first-{request_suffix}",
            actor_id="user:u1",
            correction_kind=CorrectionKind.SITUATION_CHANGED,
            replacement_value="New name",
            effective_at=first_at,
        )

    assert [item["assertion_id"] for item in current] == [original_id]
    assert [item["assertion_id"] for item in batched["user:u1"]] == [original_id]
    assert current_claim is not None
    assert current_claim["assertion_id"] == original_id
    assert retried_first is not None
    assert retried_first["created"] is False
    assert retried_first["current_assertion"]["assertion_id"] == original_id
    for committed in (
        current[0],
        batched["user:u1"][0],
        current_claim,
        retried_first["current_assertion"],
    ):
        evidence = committed["evidence_events"]
        if isinstance(evidence, str):
            evidence = json.loads(evidence)
        assert evidence == ["event-old"]
        assert float(committed["confidence_score"]) == pytest.approx(original["confidence_score"])
        assert float(committed["valid_from"]) == pytest.approx(original["valid_from"])
        assert float(committed["valid_from"]) < first_at
    assert [item["assertion_id"] for item in forecast] == [
        second["correction"]["replacement_target_id"]
    ]


@pytest.mark.asyncio
async def test_committed_assertion_cycle_filters_and_limits_after_snapshot_restore(
    l2_store_with_schema,
) -> None:
    store = l2_store_with_schema
    original_id = await _seed_profile_assertion(store)
    competitor_id = await store.upsert_assertion_candidate(
        {
            "entity_id": "user:u1",
            "entity_type": "user",
            "trait_family": "communication_profile",
            "trait_name": "communication.style.preferred",
            "trait_value": "Concise",
            "confidence_score": 0.8,
            "evidence_events": ["event-competitor"],
            "volatility_index": 0.1,
            "source_domain": "conversation",
            "inference_depth": "semantic",
            "validation_state": "corroborated",
            "first_inferred_at": time.time() - 30,
            "last_validated_at": time.time() - 30,
            "temporal_scope": "persistent",
        }
    )
    async with aiosqlite.connect(store.db_path) as db:
        await db.execute(
            """
            UPDATE tom_trait_assertions
            SET validation_state = 'corroborated', status = 'corroborated',
                updated_at = 100
            WHERE assertion_id = ?
            """,
            (original_id,),
        )
        await db.execute(
            """
            UPDATE tom_trait_assertions
            SET validation_state = 'corroborated', status = 'corroborated',
                updated_at = 200
            WHERE assertion_id = ?
            """,
            (competitor_id,),
        )
        await db.commit()

    first_at = time.time() + 600
    second_at = first_at + 600
    first = await store.apply_assertion_correction(
        assertion_id=original_id,
        request_id="committed-filter-assertion-first",
        actor_id="user:u1",
        correction_kind=CorrectionKind.SITUATION_CHANGED,
        replacement_value="New name",
        effective_at=first_at,
    )
    assert first is not None
    second = await store.apply_assertion_correction(
        assertion_id=first["correction"]["replacement_target_id"],
        request_id="committed-filter-assertion-return",
        actor_id="user:u1",
        correction_kind=CorrectionKind.SITUATION_CHANGED,
        replacement_value="Old name",
        effective_at=second_at,
    )
    assert second is not None

    with patch("time.time", return_value=second_at + 1):
        filtered = await store.list_current_assertions(
            entity_id="user:u1",
            validation_states=["corroborated"],
            limit=10,
        )
        batched = await store.batch_list_current_assertions(
            entity_ids=["user:u1"],
            validation_states=["corroborated"],
            limit_per_entity=1,
        )
        limited = await store.list_current_assertions(
            entity_id="user:u1",
            validation_states=["corroborated"],
            limit=1,
        )

    assert {item["assertion_id"] for item in filtered} == {
        original_id,
        competitor_id,
    }
    assert [item["assertion_id"] for item in batched["user:u1"]] == [competitor_id]
    assert [item["assertion_id"] for item in limited] == [competitor_id]


@pytest.mark.asyncio
async def test_committed_relationship_cycle_filters_and_limits_after_snapshot_restore(
    l2_store_with_schema,
) -> None:
    store = l2_store_with_schema
    original_id = await _seed_relationship(store)
    original = await store.get_relationship(triple_id=original_id)
    assert original is not None
    original_evidence_class = "direct_observation"
    competitor_id = await store.upsert_knowledge_edge(
        subject_id="user:u1",
        subject_type="user",
        predicate="LIKES",
        object_id="topic:music",
        object_type="topic",
        evidence_event_ids=["event-competitor-relationship"],
        confidence=0.8,
        observed_at=time.time() - 30,
        source_type="conversation",
        extraction_method="explicit",
    )
    async with aiosqlite.connect(store.db_path) as db:
        await db.execute(
            """
            UPDATE knowledge_graph
            SET updated_at = 100, evidence_class = ?, expires_at = NULL
            WHERE triple_id = ?
            """,
            (original_evidence_class, original_id),
        )
        await db.execute(
            """
            UPDATE knowledge_graph
            SET updated_at = 200, evidence_class = ?, expires_at = NULL
            WHERE triple_id = ?
            """,
            (original_evidence_class, competitor_id),
        )
        await db.commit()

    first_at = time.time() + 600
    second_at = first_at + 600
    first = await store.apply_relationship_correction(
        triple_id=original_id,
        request_id="committed-filter-relationship-first",
        actor_id="user:u1",
        correction_kind=CorrectionKind.SITUATION_CHANGED,
        replacement={"object_id": "place:shanghai", "object_type": "place"},
        effective_at=first_at,
    )
    assert first is not None
    second = await store.apply_relationship_correction(
        triple_id=first["correction"]["replacement_target_id"],
        request_id="committed-filter-relationship-return",
        actor_id="user:u1",
        correction_kind=CorrectionKind.SITUATION_CHANGED,
        replacement={"object_id": "place:hangzhou", "object_type": "place"},
        effective_at=second_at,
    )
    assert second is not None

    with patch("time.time", return_value=second_at + 1):
        filtered = await store.list_current_relationships(
            subject_id="user:u1",
            evidence_classes=[original_evidence_class],
            limit=10,
        )
        batched = await store.batch_list_current_relationships(
            entity_ids=["user:u1"],
            evidence_classes=[original_evidence_class],
            limit_per_entity=1,
        )
        limited = await store.list_current_relationships(
            subject_id="user:u1",
            evidence_classes=[original_evidence_class],
            limit=1,
        )

    assert {item["triple_id"] for item in filtered} == {
        original_id,
        competitor_id,
    }
    assert [item["triple_id"] for item in batched["user:u1"]] == [competitor_id]
    assert [item["triple_id"] for item in limited] == [competitor_id]


@pytest.mark.asyncio
async def test_unrelated_scheduled_assertion_keeps_scoped_read_on_normal_path(
    l2_store_with_schema,
) -> None:
    store = l2_store_with_schema
    original_id = await _seed_profile_assertion(store)
    unrelated_id = await store.upsert_assertion_candidate(
        {
            "entity_id": "user:u2",
            "entity_type": "user",
            "trait_family": "communication_profile",
            "trait_name": "communication.address.preferred",
            "trait_value": "Other user",
            "confidence_score": 0.8,
            "evidence_events": ["event-other-user"],
            "volatility_index": 0.1,
            "source_domain": "conversation",
            "inference_depth": "semantic",
            "validation_state": "stable",
            "first_inferred_at": time.time() - 30,
            "last_validated_at": time.time() - 30,
            "temporal_scope": "persistent",
        }
    )
    scheduled = await store.apply_assertion_correction(
        assertion_id=unrelated_id,
        request_id="unrelated-scoped-read-transition",
        actor_id="user:u2",
        correction_kind=CorrectionKind.SITUATION_CHANGED,
        replacement_value="Other user later",
        effective_at=time.time() + 3600,
    )
    assert scheduled is not None

    async with aiosqlite.connect(store.db_path) as db:
        db.row_factory = aiosqlite.Row
        rows = await select_bounded_committed_candidates(
            db,
            target_kind="assertion",
            identity_field="assertion_id",
            probe_base_sql=("SELECT * FROM tom_trait_assertions WHERE entity_id = ?"),
            probe_base_args=("user:u1",),
            normal_sql=(
                "SELECT tom_trait_assertions.*, 'normal' AS selected_path "
                "FROM tom_trait_assertions WHERE entity_id = ?"
            ),
            committed_sql=(
                "SELECT tom_trait_assertions.*, 'committed' AS selected_path "
                "FROM tom_trait_assertions WHERE entity_id = ?"
            ),
            args=("user:u1",),
        )

    assert [row["assertion_id"] for row in rows] == [original_id]
    assert rows[0]["selected_path"] == "normal"


@pytest.mark.asyncio
async def test_due_return_cycle_does_not_revive_expired_committed_relationship(
    l2_store_with_schema,
) -> None:
    store = l2_store_with_schema
    original_id = await _seed_relationship(store)
    first_at = time.time() + 600
    second_at = first_at + 600
    async with aiosqlite.connect(store.db_path) as db:
        await db.execute(
            "UPDATE knowledge_graph SET expires_at = ? WHERE triple_id = ?",
            (first_at - 1, original_id),
        )
        await db.commit()
    first = await store.apply_relationship_correction(
        triple_id=original_id,
        request_id="expired-committed-cycle-first",
        actor_id="user:u1",
        correction_kind=CorrectionKind.SITUATION_CHANGED,
        replacement={"object_id": "place:shanghai", "object_type": "place"},
        effective_at=first_at,
    )
    second = await store.apply_relationship_correction(
        triple_id=first["correction"]["replacement_target_id"],
        request_id="expired-committed-cycle-second",
        actor_id="user:u1",
        correction_kind=CorrectionKind.SITUATION_CHANGED,
        replacement={"object_id": "place:hangzhou", "object_type": "place"},
        effective_at=second_at,
    )

    with patch("time.time", return_value=second_at + 1):
        current = await store.list_current_relationships(subject_id="user:u1")
        batched = await store.batch_list_current_relationships(
            entity_ids=["user:u1"],
        )
        current_claim = await resolve_current_claim(
            store.db_path,
            correction=second["correction"],
        )

    assert current == []
    assert batched["user:u1"] == []
    assert current_claim is None


@pytest.mark.asyncio
async def test_reverted_future_transition_never_activates(l2_store_with_schema) -> None:
    store = l2_store_with_schema
    assertion_id = await _seed_profile_assertion(store)
    effective_at = time.time() + 600
    applied = await store.apply_assertion_correction(
        assertion_id=assertion_id,
        request_id="future-transition-to-revert",
        actor_id="user:u1",
        correction_kind=CorrectionKind.SITUATION_CHANGED,
        replacement_value="New name",
        effective_at=effective_at,
    )
    assert applied is not None
    correction_id = applied["correction"]["correction_id"]

    reverted = await store.revert_assertion_correction(
        correction_id=correction_id,
        request_id="revert-future-transition",
        actor_id="user:u1",
    )

    assert reverted is not None
    assert reverted["subject_revision"] is None
    assert await store.current_subject_revision("user:u1") == 0
    with patch("time.time", return_value=effective_at + 1):
        stats = await store.process_memory_correction_jobs(limit=10)
    assert stats["activated"] == 0
    assert await store.current_subject_revision("user:u1") == 0
