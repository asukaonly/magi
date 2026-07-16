from __future__ import annotations

import time

import aiosqlite
import pytest

from magi.memory.l2.corrections.models import CorrectionKind
from magi.memory.l2.corrections.service import (
    MemoryCorrectionConflictError,
    MemoryCorrectionValidationError,
)


async def _seed_assertion(
    store,  # type: ignore[no-untyped-def]
    *,
    trait_value: str = "Hangzhou",
    evidence_events: list[str] | None = None,
) -> str:
    now = time.time() - 3600
    return await store.upsert_assertion_candidate(
        {
            "entity_id": "user:u1",
            "entity_type": "user",
            "trait_family": "preference_profile",
            "trait_name": "location.home",
            "trait_value": trait_value,
            "confidence_score": 0.6,
            "evidence_events": evidence_events or ["evt-original"],
            "volatility_index": 0.2,
            "source_domain": "conversation",
            "inference_depth": "semantic",
            "validation_state": "corroborated",
            "first_inferred_at": now,
            "last_validated_at": now,
            "temporal_scope": "persistent",
        }
    )


async def _fetch_all(db_path: str, query: str, args: tuple = ()) -> list[dict]:
    async with aiosqlite.connect(db_path) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(query, args) as cursor:
            return [dict(row) for row in await cursor.fetchall()]


@pytest.mark.asyncio
async def test_record_error_replaces_without_copying_evidence(l2_store_with_schema):
    store = l2_store_with_schema
    assertion_id = await _seed_assertion(
        store,
        evidence_events=["evt-original", "evt-corroboration"],
    )

    result = await store.apply_assertion_correction(
        assertion_id=assertion_id,
        request_id="request-record-error",
        actor_id="user:u1",
        correction_kind=CorrectionKind.RECORD_ERROR,
        replacement_value="Shanghai",
        reason="The original record was wrong",
    )

    assert result is not None
    replacement = result["current_assertion"]
    assert replacement["trait_value"] == "Shanghai"
    assert replacement["evidence_events"] == []
    assert replacement["previous_version_id"] == assertion_id
    assert replacement["authority_ref"].startswith("correction:")
    assert result["subject_revision"] == 1

    original = await store.get_tom_assertion(assertion_id=assertion_id)
    assert original["status"] == "user_rejected"
    assert original["superseded_by"] == replacement["assertion_id"]

    correction = result["correction"]
    assert correction["reason"] == "The original record was wrong"
    assert correction["before"]["evidence_events"] == '["evt-original", "evt-corroboration"]'
    rules = await _fetch_all(
        store.db_path,
        "SELECT rule_kind FROM memory_correction_rules WHERE correction_id = ? ORDER BY rule_kind",
        (correction["correction_id"],),
    )
    assert [row["rule_kind"] for row in rules] == ["authoritative_slot", "block_claim"]


@pytest.mark.asyncio
async def test_rejected_feedback_creates_durable_correction(l2_store_with_schema):
    store = l2_store_with_schema
    assertion_id = await _seed_assertion(store)

    rejected = await store.apply_user_feedback(
        assertion_id=assertion_id,
        feedback="rejected",
    )

    assert rejected is not None
    assert rejected["status"] == "user_rejected"
    corrections = await store.list_assertion_corrections(assertion_id=assertion_id)
    assert len(corrections) == 1
    assert corrections[0]["correction_kind"] == CorrectionKind.RECORD_ERROR
    repeated = await store.apply_user_feedback(
        assertion_id=assertion_id,
        feedback="rejected",
    )
    assert repeated["status"] == "user_rejected"
    assert len(await store.list_assertion_corrections(assertion_id=assertion_id)) == 1
    with pytest.raises(MemoryCorrectionConflictError, match="correction history"):
        await store.apply_user_feedback(
            assertion_id=assertion_id,
            feedback="confirmed",
        )
    rules = await _fetch_all(
        store.db_path,
        "SELECT rule_kind FROM memory_correction_rules WHERE correction_id = ?",
        (corrections[0]["correction_id"],),
    )
    assert rules == [{"rule_kind": "block_claim"}]


@pytest.mark.asyncio
async def test_confirmed_feedback_is_idempotent(l2_store_with_schema):
    store = l2_store_with_schema
    assertion_id = await _seed_assertion(store)

    first = await store.apply_user_feedback(
        assertion_id=assertion_id,
        feedback="confirmed",
    )
    repeated = await store.apply_user_feedback(
        assertion_id=assertion_id,
        feedback="confirmed",
    )

    assert first is not None
    assert repeated is not None
    assert repeated["confidence_score"] == pytest.approx(first["confidence_score"])
    assert repeated["user_feedback_at"] == pytest.approx(first["user_feedback_at"])


@pytest.mark.asyncio
async def test_situation_changed_closes_old_version_at_effective_time(l2_store_with_schema):
    store = l2_store_with_schema
    assertion_id = await _seed_assertion(store)
    effective_at = time.time() - 60

    result = await store.apply_assertion_correction(
        assertion_id=assertion_id,
        request_id="request-situation-changed",
        actor_id="user:u1",
        correction_kind=CorrectionKind.SITUATION_CHANGED,
        replacement_value="Shanghai",
        effective_at=effective_at,
    )

    assert result is not None
    replacement = result["current_assertion"]
    original = await store.get_tom_assertion(assertion_id=assertion_id)
    assert original["status"] == "superseded"
    assert original["valid_to"] == pytest.approx(effective_at)
    assert replacement["valid_from"] == pytest.approx(effective_at)

    history = await store.get_assertion_correction_history(slot_key=replacement["slot_key"])
    assert [item["trait_value"] for item in history["assertions"]] == [
        "Hangzhou",
        "Shanghai",
    ]
    assert history["corrections"][0]["effective_at"] == pytest.approx(effective_at)


@pytest.mark.asyncio
async def test_situation_change_rejects_time_before_assertion_started(l2_store_with_schema):
    store = l2_store_with_schema
    assertion_id = await _seed_assertion(store)
    original = await store.get_tom_assertion(assertion_id=assertion_id)

    with pytest.raises(MemoryCorrectionValidationError, match="assertion start time"):
        await store.apply_assertion_correction(
            assertion_id=assertion_id,
            request_id="request-before-assertion-start",
            actor_id="user:u1",
            correction_kind=CorrectionKind.SITUATION_CHANGED,
            replacement_value="Shanghai",
            effective_at=float(original["first_inferred_at"]) - 1,
        )


@pytest.mark.asyncio
async def test_shadow_assertion_cannot_be_corrected(l2_store_with_schema):
    store = l2_store_with_schema
    assertion_id = await _seed_assertion(store)
    async with aiosqlite.connect(store.db_path) as db:
        await db.execute(
            """
            UPDATE tom_trait_assertions
            SET status = 'shadow', validation_state = 'shadow'
            WHERE assertion_id = ?
            """,
            (assertion_id,),
        )
        await db.commit()

    with pytest.raises(MemoryCorrectionConflictError, match="no longer current"):
        await store.apply_assertion_correction(
            assertion_id=assertion_id,
            request_id="request-shadow-assertion",
            actor_id="user:u1",
            correction_kind=CorrectionKind.RECORD_ERROR,
            replacement_value="Shanghai",
        )

    assert await store.list_assertion_corrections(assertion_id=assertion_id) == []


@pytest.mark.asyncio
async def test_invalidated_assertion_cannot_be_corrected(l2_store_with_schema):
    store = l2_store_with_schema
    assertion_id = await _seed_assertion(store)
    async with aiosqlite.connect(store.db_path) as db:
        await db.execute(
            """
            UPDATE tom_trait_assertions
            SET status = 'invalidated', validation_state = 'invalidated'
            WHERE assertion_id = ?
            """,
            (assertion_id,),
        )
        await db.commit()

    with pytest.raises(MemoryCorrectionConflictError, match="no longer current"):
        await store.apply_assertion_correction(
            assertion_id=assertion_id,
            request_id="request-invalidated-assertion",
            actor_id="user:u1",
            correction_kind=CorrectionKind.RECORD_ERROR,
            replacement_value="Shanghai",
        )

    assert await store.list_assertion_corrections(assertion_id=assertion_id) == []


@pytest.mark.asyncio
async def test_scope_refinement_only_reads_in_matching_context(l2_store_with_schema):
    store = l2_store_with_schema
    assertion_id = await _seed_assertion(store, trait_value="Shanghai")

    result = await store.apply_assertion_correction(
        assertion_id=assertion_id,
        request_id="request-scope-refinement",
        actor_id="user:u1",
        correction_kind=CorrectionKind.SCOPE_REFINEMENT,
        replacement_value="Shanghai",
        scope={"project": "magi"},
    )

    assert result is not None
    assert result["current_assertion"]["scope"] == {"project": "magi"}
    assert await store.list_current_assertions(entity_id="user:u1") == []
    assert (
        await store.list_current_assertions(
            entity_id="user:u1",
            context_scope={"project": "another"},
        )
        == []
    )
    matching = await store.list_current_assertions(
        entity_id="user:u1",
        context_scope={"project": "magi"},
    )
    assert [item["assertion_id"] for item in matching] == [
        result["current_assertion"]["assertion_id"]
    ]


@pytest.mark.asyncio
async def test_request_id_is_idempotent(l2_store_with_schema):
    store = l2_store_with_schema
    assertion_id = await _seed_assertion(store)
    command = {
        "assertion_id": assertion_id,
        "request_id": "request-idempotent",
        "actor_id": "user:u1",
        "correction_kind": CorrectionKind.RECORD_ERROR,
        "replacement_value": "Shanghai",
    }

    first = await store.apply_assertion_correction(**command)
    second = await store.apply_assertion_correction(**command)

    assert first is not None and second is not None
    assert first["created"] is True
    assert second["created"] is False
    assert first["correction"]["correction_id"] == second["correction"]["correction_id"]
    assert first["current_assertion"]["assertion_id"] == second["current_assertion"]["assertion_id"]
    counts = await _fetch_all(
        store.db_path,
        """
        SELECT
          (SELECT COUNT(*) FROM memory_corrections) AS corrections,
          (SELECT COUNT(*) FROM memory_subject_revisions WHERE subject_key = 'user:u1') AS revisions
        """,
    )
    assert counts == [{"corrections": 1, "revisions": 1}]
    assert await store.list_current_assertions(entity_id="user:u1")


@pytest.mark.asyncio
async def test_revert_restores_original_and_deactivates_rules(l2_store_with_schema):
    store = l2_store_with_schema
    assertion_id = await _seed_assertion(store)
    applied = await store.apply_assertion_correction(
        assertion_id=assertion_id,
        request_id="request-to-revert",
        actor_id="user:u1",
        correction_kind=CorrectionKind.RECORD_ERROR,
        replacement_value="Shanghai",
    )
    correction_id = applied["correction"]["correction_id"]
    replacement_id = applied["current_assertion"]["assertion_id"]

    reverted = await store.revert_assertion_correction(
        correction_id=correction_id,
        request_id="revert-request",
        actor_id="user:u1",
    )

    assert reverted is not None
    assert reverted["correction"]["state"] == "reverted"
    assert reverted["subject_revision"] == 2
    assert reverted["current_assertion"]["assertion_id"] == assertion_id
    assert reverted["current_assertion"]["trait_value"] == "Hangzhou"
    assert reverted["current_assertion"]["evidence_events"] == ["evt-original"]
    replacement = await store.get_tom_assertion(assertion_id=replacement_id)
    assert replacement["status"] == "archived"
    rules = await _fetch_all(
        store.db_path,
        "SELECT DISTINCT active FROM memory_correction_rules WHERE correction_id = ?",
        (correction_id,),
    )
    assert rules == [{"active": 0}]


@pytest.mark.asyncio
async def test_stale_update_and_older_revert_are_rejected(l2_store_with_schema):
    store = l2_store_with_schema
    assertion_id = await _seed_assertion(store)
    original = await store.get_tom_assertion(assertion_id=assertion_id)

    with pytest.raises(MemoryCorrectionConflictError, match="changed after"):
        await store.apply_assertion_correction(
            assertion_id=assertion_id,
            request_id="stale-request",
            actor_id="user:u1",
            correction_kind=CorrectionKind.RECORD_ERROR,
            replacement_value="Shanghai",
            expected_updated_at=original["updated_at"] - 1,
        )

    first = await store.apply_assertion_correction(
        assertion_id=assertion_id,
        request_id="first-request",
        actor_id="user:u1",
        correction_kind=CorrectionKind.RECORD_ERROR,
        replacement_value="Shanghai",
    )
    second = await store.apply_assertion_correction(
        assertion_id=first["current_assertion"]["assertion_id"],
        request_id="second-request",
        actor_id="user:u1",
        correction_kind=CorrectionKind.RECORD_ERROR,
        replacement_value="Beijing",
    )
    assert second is not None

    with pytest.raises(MemoryCorrectionConflictError, match="newer correction"):
        await store.revert_assertion_correction(
            correction_id=first["correction"]["correction_id"],
            request_id="invalid-revert",
            actor_id="user:u1",
        )
