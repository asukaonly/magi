from __future__ import annotations

import time

import pytest

from magi.memory.l2.corrections.models import CorrectionKind


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
    current = await store.list_current_assertions(entity_id="user:u1")
    assert [item["assertion_id"] for item in current] == [replacement_id]


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
    assert await store.list_assertions_by_status("shadow", entity_id="user:u1") == []

    await store.upsert_assertion_candidate(
        _candidate("Hangzhou", "evt-after-move", observed_at=time.time())
    )
    shadows = await store.list_assertions_by_status("shadow", entity_id="user:u1")
    assert len(shadows) == 1
    current = await store.list_current_assertions(entity_id="user:u1")
    assert [item["assertion_id"] for item in current] == [replacement_id]


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
        scope={"project": "magi"},
    )
    magi_id = corrected["current_assertion"]["assertion_id"]

    returned_id = await store.upsert_assertion_candidate(
        _candidate("Shanghai", "evt-missing-scope")
    )
    assert returned_id == assertion_id
    assert await store.list_current_assertions(entity_id="user:u1") == []

    same_id = await store.upsert_assertion_candidate(
        _candidate("Shanghai", "evt-magi", scope={"project": "magi"})
    )
    assert same_id == magi_id
    other_id = await store.upsert_assertion_candidate(
        _candidate("Beijing", "evt-other", scope={"project": "another"})
    )
    assert other_id != magi_id

    magi_current = await store.list_current_assertions(
        entity_id="user:u1",
        context_scope={"project": "magi"},
    )
    other_current = await store.list_current_assertions(
        entity_id="user:u1",
        context_scope={"project": "another"},
    )
    assert [item["assertion_id"] for item in magi_current] == [magi_id]
    assert [item["assertion_id"] for item in other_current] == [other_id]


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
