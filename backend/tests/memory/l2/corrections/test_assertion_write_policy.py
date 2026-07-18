from __future__ import annotations

import time

import pytest

from _shared.context_scope import context_scope
from magi.core.sqlite import sqlite_connection_async
from magi.memory.context_scope import ContextScopeError
from magi.memory.l2.corrections.models import CorrectionKind
from magi.memory.l2.corrections.policy import (
    CorrectionPolicyAction,
    CorrectionPolicyEvaluator,
)


def _candidate(
    value: str,
    event_id: str,
    *,
    observed_at: float | None = None,
    scope: dict | None = None,
) -> dict:
    timestamp = float(observed_at if observed_at is not None else time.time())
    candidate = {
        "entity_id": "user:u1",
        "entity_type": "user",
        "trait_family": "preference_profile",
        "trait_name": "location.home",
        "trait_value": value,
        "confidence_score": 0.6,
        "evidence_events": [event_id],
        "volatility_index": 0.2,
        "source_domain": "conversation",
        "inference_depth": "semantic",
        "validation_state": "corroborated",
        "first_inferred_at": timestamp,
        "last_validated_at": timestamp,
        "temporal_scope": "persistent",
        "decay_policy": "standard_decay",
    }
    if scope is not None:
        candidate["scope"] = scope
    return candidate


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "invalid_scope",
    ["magi", [], False, {"project": "magi"}],
)
async def test_assertion_write_rejects_invalid_scope_without_writing_global(
    l2_store_with_schema,
    invalid_scope,
) -> None:
    candidate = _candidate("Hangzhou", "evt-invalid-scope")
    candidate["scope"] = invalid_scope

    with pytest.raises(ContextScopeError):
        await l2_store_with_schema.upsert_assertion_candidate(candidate)

    assert await l2_store_with_schema.list_current_assertions(entity_id="user:u1") == []


@pytest.mark.asyncio
async def test_replayed_rejected_claim_never_becomes_current(l2_store_with_schema):
    store = l2_store_with_schema
    assertion_id = await store.upsert_assertion_candidate(
        _candidate("Hangzhou", "evt-original", observed_at=time.time() - 3600)
    )
    corrected = await store.apply_assertion_correction(
        assertion_id=assertion_id,
        request_id="reject-and-replace",
        actor_id="user:u1",
        correction_kind=CorrectionKind.RECORD_ERROR,
        replacement_value="Shanghai",
    )
    replacement_id = corrected["current_assertion"]["assertion_id"]

    for event_id in ("evt-replay-1", "evt-replay-2", "evt-replay-3"):
        returned_id = await store.upsert_assertion_candidate(_candidate("Hangzhou", event_id))
        assert returned_id == assertion_id

    original = await store.get_tom_assertion(assertion_id=assertion_id)
    assert original["status"] == "user_rejected"
    assert original["evidence_events"] == ["evt-original"]
    assert await store.active_correction_evidence_event_ids(
        ["evt-replay-1", "evt-replay-2", "evt-replay-3"]
    ) == {"evt-replay-1", "evt-replay-2", "evt-replay-3"}
    current = await store.list_current_assertions(entity_id="user:u1")
    assert [item["assertion_id"] for item in current] == [replacement_id]
    assert await store.list_assertions_by_status("shadow", entity_id="user:u1") == []


@pytest.mark.asyncio
async def test_authoritative_claim_preserves_metadata_and_deduplicates_shadow(
    l2_store_with_schema,
):
    store = l2_store_with_schema
    assertion_id = await store.upsert_assertion_candidate(_candidate("Hangzhou", "evt-original"))
    corrected = await store.apply_assertion_correction(
        assertion_id=assertion_id,
        request_id="authoritative-shanghai",
        actor_id="user:u1",
        correction_kind=CorrectionKind.RECORD_ERROR,
        replacement_value="Shanghai",
    )
    replacement_id = corrected["current_assertion"]["assertion_id"]

    same_id = await store.upsert_assertion_candidate(_candidate("Shanghai", "evt-supporting"))
    assert same_id == replacement_id
    replacement = await store.get_tom_assertion(assertion_id=replacement_id)
    assert replacement["source_domain"] == "user_correction"
    assert replacement["authority_ref"].startswith("correction:")
    assert replacement["decay_policy"] is None
    assert replacement["evidence_events"] == ["evt-supporting"]

    first_shadow_id = await store.upsert_assertion_candidate(
        _candidate("Beijing", "evt-conflict-1")
    )
    second_shadow_id = await store.upsert_assertion_candidate(
        _candidate("Beijing", "evt-conflict-2")
    )
    assert second_shadow_id == first_shadow_id
    shadows = await store.list_assertions_by_status("shadow", entity_id="user:u1")
    assert len(shadows) == 1
    assert shadows[0]["trait_value"] == "Beijing"
    assert shadows[0]["evidence_events"] == ["evt-conflict-1", "evt-conflict-2"]
    assert await store.active_correction_evidence_event_ids(
        ["evt-conflict-1", "evt-conflict-2"]
    ) == {"evt-conflict-1", "evt-conflict-2"}
    current = await store.list_current_assertions(entity_id="user:u1")
    assert [item["assertion_id"] for item in current] == [replacement_id]


@pytest.mark.asyncio
async def test_newer_user_correction_can_make_an_older_blocked_claim_current(
    l2_store_with_schema,
) -> None:
    store = l2_store_with_schema
    original_id = await store.upsert_assertion_candidate(
        _candidate("Hangzhou", "evt-original", observed_at=time.time() - 3600)
    )
    first = await store.apply_assertion_correction(
        assertion_id=original_id,
        request_id="record-hangzhou-as-wrong",
        actor_id="user:u1",
        correction_kind=CorrectionKind.RECORD_ERROR,
        replacement_value="Shanghai",
    )
    second = await store.apply_assertion_correction(
        assertion_id=first["current_assertion"]["assertion_id"],
        request_id="confirm-hangzhou-as-current",
        actor_id="user:u1",
        correction_kind=CorrectionKind.RECORD_ERROR,
        replacement_value="Hangzhou",
    )
    current_id = second["current_assertion"]["assertion_id"]

    returned_id = await store.upsert_assertion_candidate(
        _candidate("Hangzhou", "evt-current-confirmation")
    )

    assert returned_id == current_id
    current = await store.get_tom_assertion(assertion_id=current_id)
    assert current["status"] == "stable"
    assert current["evidence_events"] == ["evt-current-confirmation"]
    assert await store.active_correction_evidence_event_ids(["evt-current-confirmation"]) == set()


@pytest.mark.asyncio
async def test_pre_change_evidence_only_updates_historical_version(l2_store_with_schema):
    store = l2_store_with_schema
    effective_at = time.time() - 120
    assertion_id = await store.upsert_assertion_candidate(
        _candidate("Hangzhou", "evt-original", observed_at=effective_at - 3600)
    )
    corrected = await store.apply_assertion_correction(
        assertion_id=assertion_id,
        request_id="move-to-shanghai",
        actor_id="user:u1",
        correction_kind=CorrectionKind.SITUATION_CHANGED,
        replacement_value="Shanghai",
        effective_at=effective_at,
    )
    replacement_id = corrected["current_assertion"]["assertion_id"]

    replayed_id = await store.upsert_assertion_candidate(
        _candidate("Hangzhou", "evt-before-move", observed_at=effective_at - 60)
    )
    assert replayed_id == assertion_id
    historical = await store.get_tom_assertion(assertion_id=assertion_id)
    assert historical["status"] == "superseded"
    assert historical["valid_to"] == pytest.approx(effective_at)
    assert historical["evidence_events"] == ["evt-before-move", "evt-original"]
    assert historical["last_validated_at"] <= effective_at
    assert await store.active_correction_evidence_event_ids(["evt-before-move"]) == {
        "evt-before-move"
    }
    assert await store.list_assertions_by_status("shadow", entity_id="user:u1") == []

    await store.upsert_assertion_candidate(
        _candidate("Hangzhou", "evt-after-move", observed_at=time.time())
    )
    shadows = await store.list_assertions_by_status("shadow", entity_id="user:u1")
    assert len(shadows) == 1
    current = await store.list_current_assertions(entity_id="user:u1")
    assert [item["assertion_id"] for item in current] == [replacement_id]


@pytest.mark.asyncio
async def test_scheduled_rules_follow_candidate_observation_time(l2_store_with_schema):
    store = l2_store_with_schema
    effective_at = time.time() + 600
    assertion_id = await store.upsert_assertion_candidate(
        _candidate("Hangzhou", "evt-original", observed_at=time.time() - 60)
    )
    corrected = await store.apply_assertion_correction(
        assertion_id=assertion_id,
        request_id="future-rule-window",
        actor_id="user:u1",
        correction_kind=CorrectionKind.SITUATION_CHANGED,
        replacement_value="Shanghai",
        effective_at=effective_at,
    )
    assert corrected is not None
    correction = corrected["correction"]
    replacement = await store.get_tom_assertion(
        assertion_id=correction["replacement_target_id"]
    )
    assert replacement is not None
    evaluator = CorrectionPolicyEvaluator()

    async with sqlite_connection_async(store.db_path) as db:
        old_before = await evaluator.evaluate_assertion(
            db,
            {
                "slot_key": correction["slot_key"],
                "claim_fingerprint": correction["claim_fingerprint"],
                "scope_key": "global",
                "last_validated_at": effective_at - 1,
            },
        )
        old_after = await evaluator.evaluate_assertion(
            db,
            {
                "slot_key": correction["slot_key"],
                "claim_fingerprint": correction["claim_fingerprint"],
                "scope_key": "global",
                "last_validated_at": effective_at + 1,
            },
        )
        replacement_before = await evaluator.evaluate_assertion(
            db,
            {
                "slot_key": correction["slot_key"],
                "claim_fingerprint": replacement["claim_fingerprint"],
                "scope_key": "global",
                "last_validated_at": effective_at - 1,
            },
        )
        replacement_at_boundary = await evaluator.evaluate_assertion(
            db,
            {
                "slot_key": correction["slot_key"],
                "claim_fingerprint": replacement["claim_fingerprint"],
                "scope_key": "global",
                "last_validated_at": effective_at,
            },
        )

    assert old_before.action == CorrectionPolicyAction.ACCEPT_HISTORICAL
    assert old_after.action == CorrectionPolicyAction.CREATE_SHADOW
    assert replacement_before.action == CorrectionPolicyAction.BLOCKED_BY_CORRECTION
    assert replacement_before.correction_id == correction["correction_id"]
    assert replacement_at_boundary.action == CorrectionPolicyAction.ACCEPT_ACTIVE
    assert replacement_at_boundary.correction_id == correction["correction_id"]

    same_value_id = await store.upsert_assertion_candidate(
        _candidate("Shanghai", "evt-early-replacement", observed_at=effective_at - 10)
    )
    third_value_id = await store.upsert_assertion_candidate(
        _candidate("Beijing", "evt-early-third", observed_at=effective_at - 10)
    )
    old_value_id = await store.upsert_assertion_candidate(
        _candidate("Hangzhou", "evt-before-change", observed_at=effective_at - 10)
    )

    assert same_value_id == assertion_id
    assert third_value_id == assertion_id
    assert old_value_id == assertion_id
    stored_replacement = await store.get_tom_assertion(assertion_id=replacement["assertion_id"])
    assert stored_replacement["evidence_events"] == []
    historical = await store.get_tom_assertion(assertion_id=assertion_id)
    assert historical["evidence_events"] == ["evt-before-change", "evt-original"]
    async with sqlite_connection_async(store.db_path) as db:
        async with db.execute(
            "SELECT COUNT(*) FROM tom_trait_assertions WHERE trait_value = 'Beijing'"
        ) as cursor:
            assert int((await cursor.fetchone())[0]) == 0


@pytest.mark.asyncio
async def test_scope_refinement_requires_context_and_allows_other_scopes(
    l2_store_with_schema,
):
    store = l2_store_with_schema
    assertion_id = await store.upsert_assertion_candidate(_candidate("Shanghai", "evt-global"))
    corrected = await store.apply_assertion_correction(
        assertion_id=assertion_id,
        request_id="scope-to-magi",
        actor_id="user:u1",
        correction_kind=CorrectionKind.SCOPE_REFINEMENT,
        replacement_value="Shanghai",
        scope=context_scope(project="magi"),
    )
    magi_id = corrected["current_assertion"]["assertion_id"]

    returned_id = await store.upsert_assertion_candidate(
        _candidate("Shanghai", "evt-missing-scope")
    )
    assert returned_id == assertion_id
    assert await store.list_current_assertions(entity_id="user:u1") == []

    same_id = await store.upsert_assertion_candidate(
        _candidate("Shanghai", "evt-magi", scope=context_scope(project="magi"))
    )
    assert same_id == magi_id
    other_id = await store.upsert_assertion_candidate(
        _candidate("Beijing", "evt-other", scope=context_scope(project="another"))
    )
    assert other_id != magi_id

    magi_current = await store.list_current_assertions(
        entity_id="user:u1",
        context_scope=context_scope(project="magi"),
    )
    other_current = await store.list_current_assertions(
        entity_id="user:u1",
        context_scope=context_scope(project="another"),
    )
    assert [item["assertion_id"] for item in magi_current] == [magi_id]
    assert [item["assertion_id"] for item in other_current] == [other_id]


@pytest.mark.asyncio
async def test_scope_refinement_blocks_only_the_original_scoped_claim_on_replay(
    l2_store_with_schema,
) -> None:
    store = l2_store_with_schema
    source_scope = context_scope(project="source-project")
    destination_scope = context_scope(project="destination-project")
    assertion_id = await store.upsert_assertion_candidate(
        _candidate("Shanghai", "evt-source", scope=source_scope)
    )
    corrected = await store.apply_assertion_correction(
        assertion_id=assertion_id,
        request_id="move-scoped-assertion",
        actor_id="user:u1",
        correction_kind=CorrectionKind.SCOPE_REFINEMENT,
        replacement_value="Shanghai",
        scope=destination_scope,
    )
    destination_id = corrected["current_assertion"]["assertion_id"]

    replayed_id = await store.upsert_assertion_candidate(
        _candidate("Shanghai", "evt-source-replay", scope=source_scope)
    )
    alternative_id = await store.upsert_assertion_candidate(
        _candidate("Beijing", "evt-source-alternative", scope=source_scope)
    )

    assert replayed_id == assertion_id
    assert await store.active_correction_evidence_event_ids(["evt-source-replay"]) == {
        "evt-source-replay"
    }
    assert alternative_id not in {assertion_id, destination_id}
    source_current = await store.list_current_assertions(
        entity_id="user:u1",
        context_scope=source_scope,
    )
    destination_current = await store.list_current_assertions(
        entity_id="user:u1",
        context_scope=destination_scope,
    )
    assert [item["assertion_id"] for item in source_current] == [alternative_id]
    assert [item["assertion_id"] for item in destination_current] == [destination_id]


@pytest.mark.asyncio
async def test_correction_policy_survives_store_restart(l2_store_with_schema):
    from magi.memory.l2.store import L2CognitionStore

    store = l2_store_with_schema
    assertion_id = await store.upsert_assertion_candidate(_candidate("Hangzhou", "evt-original"))
    corrected = await store.apply_assertion_correction(
        assertion_id=assertion_id,
        request_id="persistent-correction",
        actor_id="user:u1",
        correction_kind=CorrectionKind.RECORD_ERROR,
        replacement_value="Shanghai",
    )

    restarted = L2CognitionStore(db_path=store.db_path)
    await restarted.initialize()
    returned_id = await restarted.upsert_assertion_candidate(
        _candidate("Hangzhou", "evt-after-restart")
    )

    assert returned_id == assertion_id
    current = await restarted.list_current_assertions(entity_id="user:u1")
    assert [item["assertion_id"] for item in current] == [
        corrected["current_assertion"]["assertion_id"]
    ]


@pytest.mark.asyncio
async def test_confirmed_shadow_becomes_new_governed_authority(l2_store_with_schema):
    store = l2_store_with_schema
    assertion_id = await store.upsert_assertion_candidate(_candidate("Hangzhou", "evt-original"))
    corrected = await store.apply_assertion_correction(
        assertion_id=assertion_id,
        request_id="initial-authority",
        actor_id="user:u1",
        correction_kind=CorrectionKind.RECORD_ERROR,
        replacement_value="Shanghai",
    )
    prior_authority_id = corrected["current_assertion"]["assertion_id"]
    shadow_id = await store.upsert_assertion_candidate(_candidate("Beijing", "evt-beijing"))

    confirmed = await store.resolve_shadow_conflict(
        shadow_id=shadow_id,
        action="confirm",
    )

    assert confirmed is not None
    assert confirmed["trait_value"] == "Beijing"
    assert confirmed["assertion_id"] != shadow_id
    assert confirmed["authority_ref"].startswith("correction:")
    prior_authority = await store.get_tom_assertion(assertion_id=prior_authority_id)
    assert prior_authority["status"] == "user_rejected"
    archived_shadow = await store.get_tom_assertion(assertion_id=shadow_id)
    assert archived_shadow["status"] == "archived"

    same_id = await store.upsert_assertion_candidate(_candidate("Beijing", "evt-beijing-support"))
    assert same_id == confirmed["assertion_id"]
    next_shadow_id = await store.upsert_assertion_candidate(_candidate("Shenzhen", "evt-shenzhen"))
    assert next_shadow_id != confirmed["assertion_id"]
    next_shadow = await store.get_tom_assertion(assertion_id=next_shadow_id)
    assert next_shadow["status"] == "shadow"
