"""Source-forget reconciliation for Claim-owned assertion lifecycles."""

from __future__ import annotations

import json
import time
from datetime import datetime, timedelta
from typing import Any

import pytest

from magi.core.sqlite import sqlite_connection_async
from magi.memory.l2.assertions.occurrence_stats import (
    ClaimRouteValueKey,
    load_routed_claim_occurrence_stats,
)
from magi.memory.l2.semantic_routing import ROUTE_CONTRACT_VERSION
from magi.memory.l2.store import L2CognitionStore

_ROUTE_KEY = ClaimRouteValueKey(
    target_slot_key="assertion:user:u1:preference_profile:music_affinity",
    value_fingerprint="value:like:jazz",
)


async def _materialized_assertion(
    store: L2CognitionStore,
    *,
    event_ids: list[str],
    route_key: ClaimRouteValueKey = _ROUTE_KEY,
    trait_family: str = "preference_profile",
    trait_name: str = "music_affinity",
    trait_value: str = "jazz",
    temporal_scope: str = "stable",
    decay_policy: str = "evidence_only",
) -> str:
    observed_at = time.time() - 60
    return await store.upsert_assertion_candidate(
        {
            "entity_id": "user:u1",
            "entity_type": "user",
            "trait_family": trait_family,
            "trait_name": trait_name,
            "trait_value": trait_value,
            "confidence_score": 0.9,
            "evidence_events": event_ids,
            "volatility_index": 0.1,
            "source_domain": "conversation",
            "inference_depth": "explicit",
            "validation_state": "stable",
            "first_inferred_at": observed_at,
            "last_validated_at": observed_at,
            "temporal_scope": temporal_scope,
            "decay_policy": decay_policy,
            "decay_anchor_at": observed_at,
            "memory_subdomain": ("semantic" if decay_policy == "evidence_only" else "state"),
            "semantic_route_slot_key": route_key.target_slot_key,
            "route_contract_version": ROUTE_CONTRACT_VERSION,
        }
    )


async def _seed_routed_claim(
    db_path: str,
    *,
    claim_id: str,
    event_id: str,
    event_time: float,
    created_at: float,
    assertion_id: str | None,
    fact_kind: str = "stable_preference",
    temporal_cue: str = "stable",
    evidence_class: str = "user_self_report",
    source_type: str = "chat",
    source_domain: str = "user_authored",
    author_type: str = "user",
    route_key: ClaimRouteValueKey = _ROUTE_KEY,
    predicate: str = "LIKES",
    object_type: str = "topic",
    object_value: Any = "jazz",
    object_surface: str = "jazz",
    target_to: float | None = None,
    raw_time_frame: dict[str, Any] | None = None,
    timestamp_quality: str = "exact",
    evidence_mode: str = "direct",
) -> None:
    attempt_key = f"attempt:{claim_id}"
    async with sqlite_connection_async(db_path) as db:
        await db.execute(
            """
            INSERT INTO l2_grounded_claims(
                claim_id, identity_key, extractor_contract_version,
                evidence_rule_version, origin_attempt_key, profile_id,
                user_id, subject_ref, subject_type, canonical_predicate,
                fact_kind, object_type, polarity, specificity, confidence,
                object_value_json, object_surface, temporal_cue, target_to,
                raw_time_frame_json, availability, created_at, updated_at
            ) VALUES (?, ?, 1, 1, ?, 'chat.user_message', 'u1', 'user:u1',
                      'user', ?, ?, ?,
                      'positive', 'concrete', 0.9, ?, ?, ?, ?, ?,
                      'active', ?, ?)
            """,
            (
                claim_id,
                f"identity:{claim_id}",
                attempt_key,
                predicate,
                fact_kind,
                object_type,
                json.dumps(object_value),
                object_surface,
                temporal_cue,
                target_to,
                json.dumps(raw_time_frame) if raw_time_frame is not None else None,
                created_at,
                created_at,
            ),
        )
        await db.execute(
            """
            INSERT INTO l2_claim_evidence(
                claim_id, event_id, link_role, required_for_grounding,
                event_time, timestamp_confidence, timestamp_quality,
                evidence_rule_version, evidence_mode, source_type,
                source_domain, author_type, evidence_class, created_at
            ) VALUES (?, ?, 'supporting', 1, ?, ?, ?,
                      1, ?, ?, ?, ?, ?, ?)
            """,
            (
                claim_id,
                event_id,
                event_time,
                "exact" if timestamp_quality == "exact" else "inferred",
                timestamp_quality,
                evidence_mode,
                source_type,
                source_domain,
                author_type,
                evidence_class,
                created_at,
            ),
        )
        await db.execute(
            """
            INSERT INTO l2_claim_projection_outcomes(
                outcome_id, claim_id, attempt_key, target_kind, target_id,
                target_slot_key, route_contract_version, outcome, reason_code,
                details_json, created_at
            ) VALUES (?, ?, ?, 'route', ?, ?, ?, 'routed', 'test_route', ?, ?)
            """,
            (
                f"outcome:route:{claim_id}",
                claim_id,
                attempt_key,
                f"route:{claim_id}",
                route_key.target_slot_key,
                ROUTE_CONTRACT_VERSION,
                json.dumps({"value_fingerprint": route_key.value_fingerprint}),
                created_at,
            ),
        )
        if assertion_id is not None:
            await db.execute(
                """
                INSERT INTO l2_claim_projection_outcomes(
                    outcome_id, claim_id, attempt_key, target_kind, target_id,
                    target_slot_key, route_contract_version, outcome, reason_code,
                    details_json, created_at
                ) VALUES (?, ?, ?, 'assertion', ?, ?, ?, 'projected',
                          'test_projection', '{}', ?)
                """,
                (
                    f"outcome:assertion:{claim_id}",
                    claim_id,
                    attempt_key,
                    assertion_id,
                    route_key.target_slot_key,
                    ROUTE_CONTRACT_VERSION,
                    created_at,
                ),
            )
        await db.commit()


def _lifecycle_snapshot(assertion: dict[str, Any]) -> dict[str, Any]:
    return {
        "status": assertion["status"],
        "validation_state": assertion["validation_state"],
        "evidence_events": assertion["evidence_events"],
        "temporal_scope": assertion["temporal_scope"],
        "decay_policy": assertion["decay_policy"],
        "decay_anchor_at": assertion["decay_anchor_at"],
        "expires_at": assertion["expires_at"],
        "memory_subdomain": assertion["memory_subdomain"],
        "authority_ref": assertion["authority_ref"],
        "user_feedback": assertion["user_feedback"],
    }


@pytest.mark.asyncio
@pytest.mark.parametrize("direct_first", [True, False])
async def test_forget_recomputes_durable_assertion_to_event_only_independent_of_order(
    l2_store_with_schema: L2CognitionStore,
    direct_first: bool,
) -> None:
    store = l2_store_with_schema
    direct_event_id = "evt-promotion-direct"
    weak_event_id = "evt-promotion-weak"
    assertion_id = await _materialized_assertion(
        store,
        event_ids=[direct_event_id, weak_event_id],
    )
    now = time.time()
    claims = [
        {
            "claim_id": "claim:promotion-direct",
            "event_id": direct_event_id,
            "event_time": now - 120,
            "assertion_id": assertion_id,
        },
        {
            "claim_id": "claim:promotion-weak",
            "event_id": weak_event_id,
            "event_time": now - 60,
            "assertion_id": assertion_id,
            "fact_kind": "explicit_fact",
            "temporal_cue": "one_off",
            "evidence_class": "external_observation",
            "source_type": "browser-history",
            "source_domain": "external_activity",
            "author_type": "system",
        },
    ]
    ordered_claims = claims if direct_first else list(reversed(claims))
    for sequence, claim in enumerate(ordered_claims, start=1):
        await _seed_routed_claim(
            store.db_path,
            created_at=float(sequence),
            **claim,
        )

    before = await store.get_tom_assertion(assertion_id=assertion_id)
    assert before is not None
    assert before["temporal_scope"] == "stable"
    assert before["decay_policy"] == "evidence_only"

    forgotten = await store.forget_source_events(
        [direct_event_id],
        reason="user_delete_event",
    )

    assertion = await store.get_tom_assertion(assertion_id=assertion_id)
    assert assertion is not None
    assert assertion["status"] == "archived"
    assert assertion["validation_state"] == "tentative"
    assert assertion["evidence_events"] == [weak_event_id]
    assert assertion["temporal_scope"] == "momentary"
    assert assertion["decay_policy"] == "fast_decay"
    assert assertion["memory_subdomain"] == "state"
    assert assertion["authority_ref"] == "forget:event"
    assert forgotten["l2_grounded_claims"] == 1

    before_restart = _lifecycle_snapshot(assertion)
    restarted = L2CognitionStore(db_path=store.db_path)
    await restarted.initialize()
    repeated = await restarted.forget_source_events(
        [direct_event_id],
        reason="user_delete_event",
    )
    replayed = await restarted.get_tom_assertion(assertion_id=assertion_id)
    assert replayed is not None
    assert _lifecycle_snapshot(replayed) == before_restart
    assert repeated["source_event_tombstones"] == 0
    assert repeated["l2_grounded_claims"] == 0


@pytest.mark.asyncio
async def test_tombstone_then_cleanup_reconciles_assertion_before_receipts_are_redacted(
    l2_store_with_schema: L2CognitionStore,
) -> None:
    store = l2_store_with_schema
    direct_event_id = "evt-tombstone-direct"
    weak_event_id = "evt-tombstone-weak"
    assertion_id = await _materialized_assertion(
        store,
        event_ids=[direct_event_id, weak_event_id],
    )
    now = time.time()
    await _seed_routed_claim(
        store.db_path,
        claim_id="claim:tombstone-direct",
        event_id=direct_event_id,
        event_time=now - 120,
        created_at=1.0,
        assertion_id=assertion_id,
    )
    await _seed_routed_claim(
        store.db_path,
        claim_id="claim:tombstone-weak",
        event_id=weak_event_id,
        event_time=now - 60,
        created_at=2.0,
        assertion_id=assertion_id,
        fact_kind="explicit_fact",
        temporal_cue="one_off",
        evidence_class="external_observation",
        source_type="browser-history",
        source_domain="external_activity",
        author_type="system",
    )
    assert (
        await store.refresh_entity_snapshot(
            entity_id="user:u1",
            entity_type="user",
        )
        is not None
    )

    inserted = await store.tombstone_source_events(
        [direct_event_id],
        reason="durable_forget_admission",
    )

    tombstoned = await store.get_tom_assertion(assertion_id=assertion_id)
    assert inserted == 1
    assert tombstoned is not None
    assert tombstoned["status"] == "archived"
    assert tombstoned["evidence_events"] == [weak_event_id]
    assert tombstoned["temporal_scope"] == "momentary"
    assert tombstoned["authority_ref"] == "forget:event"
    assert (
        await store.get_tom_snapshot(
            entity_id="user:u1",
            entity_type="user",
        )
        is None
    )

    cleanup = await store.forget_source_events(
        [direct_event_id],
        reason="user_delete_event",
        persist_barrier=False,
    )
    after_cleanup = await store.get_tom_assertion(assertion_id=assertion_id)
    assert after_cleanup is not None
    assert _lifecycle_snapshot(after_cleanup) == _lifecycle_snapshot(tombstoned)
    assert cleanup["l2_grounded_claims"] == 0


@pytest.mark.asyncio
async def test_forget_keeps_durable_lifecycle_when_direct_claim_support_remains(
    l2_store_with_schema: L2CognitionStore,
) -> None:
    store = l2_store_with_schema
    forgotten_event_id = "evt-shared-direct-forget"
    retained_event_id = "evt-shared-direct-keep"
    assertion_id = await _materialized_assertion(
        store,
        event_ids=[forgotten_event_id, retained_event_id],
    )
    now = time.time()
    await _seed_routed_claim(
        store.db_path,
        claim_id="claim:shared-direct-forget",
        event_id=forgotten_event_id,
        event_time=now - 120,
        created_at=1.0,
        assertion_id=assertion_id,
    )
    await _seed_routed_claim(
        store.db_path,
        claim_id="claim:shared-direct-keep",
        event_id=retained_event_id,
        event_time=now - 60,
        created_at=2.0,
        assertion_id=assertion_id,
    )

    await store.forget_source_events(
        [forgotten_event_id],
        reason="user_delete_event",
    )

    assertion = await store.get_tom_assertion(assertion_id=assertion_id)
    assert assertion is not None
    assert assertion["status"] == "tentative"
    assert assertion["validation_state"] == "tentative"
    assert assertion["evidence_events"] == [retained_event_id]
    assert assertion["temporal_scope"] == "stable"
    assert assertion["decay_policy"] == "evidence_only"
    assert assertion["expires_at"] is None
    assert assertion["memory_subdomain"] == "semantic"
    assert assertion["authority_ref"] is None


@pytest.mark.asyncio
async def test_forget_preserves_user_confirmed_assertion_as_independent_authority(
    l2_store_with_schema: L2CognitionStore,
) -> None:
    store = l2_store_with_schema
    event_id = "evt-confirmed-direct"
    assertion_id = await _materialized_assertion(store, event_ids=[event_id])
    await _seed_routed_claim(
        store.db_path,
        claim_id="claim:confirmed-direct",
        event_id=event_id,
        event_time=time.time() - 60,
        created_at=1.0,
        assertion_id=assertion_id,
    )
    confirmed = await store.apply_user_feedback(
        assertion_id=assertion_id,
        feedback="confirmed",
    )
    assert confirmed is not None

    await store.forget_source_events([event_id], reason="user_delete_event")

    assertion = await store.get_tom_assertion(assertion_id=assertion_id)
    assert assertion is not None
    assert assertion["status"] == "stable"
    assert assertion["validation_state"] == "stable"
    assert assertion["user_feedback"] == "confirmed"
    assert assertion["evidence_events"] == []
    assert assertion["temporal_scope"] == "stable"
    assert assertion["decay_policy"] == "evidence_only"
    assert assertion["authority_ref"] is None


@pytest.mark.asyncio
async def test_forget_reactivates_recent_lifecycle_with_recomputed_validation_state(
    l2_store_with_schema: L2CognitionStore,
) -> None:
    store = l2_store_with_schema
    direct_event_id = "evt-recent-direct"
    assertion_id = await _materialized_assertion(store, event_ids=[direct_event_id])
    now = time.time()
    await _seed_routed_claim(
        store.db_path,
        claim_id="claim:recent-direct",
        event_id=direct_event_id,
        event_time=now - 60,
        created_at=1.0,
        assertion_id=assertion_id,
    )

    local_now = datetime.now().astimezone()
    boundary = local_now.replace(hour=0, minute=0, second=0, microsecond=0)
    if local_now - boundary < timedelta(minutes=1):
        boundary -= timedelta(days=1)
    weak_times = [
        boundary.timestamp() - 2 * 60 * 60,
        boundary.timestamp() - 60 * 60,
        boundary.timestamp() + 1,
    ]
    weak_event_ids = []
    for index, event_time in enumerate(weak_times):
        event_id = f"evt-recent-weak-{index}"
        weak_event_ids.append(event_id)
        await _seed_routed_claim(
            store.db_path,
            claim_id=f"claim:recent-weak-{index}",
            event_id=event_id,
            event_time=event_time,
            created_at=float(index + 2),
            assertion_id=None,
            fact_kind="interaction_evidence",
            temporal_cue="recurring",
            evidence_class="external_observation",
            source_type="browser-history",
            source_domain="external_activity",
            author_type="system",
        )

    await store.forget_source_events(
        [direct_event_id],
        reason="user_delete_event",
    )

    assertion = await store.get_tom_assertion(assertion_id=assertion_id)
    assert assertion is not None
    assert assertion["status"] == "corroborated"
    assert assertion["validation_state"] == "corroborated"
    assert assertion["evidence_events"] == weak_event_ids
    assert assertion["temporal_scope"] == "recent"
    assert assertion["decay_policy"] == "time_window"
    assert assertion["memory_subdomain"] == "state"
    assert assertion["authority_ref"] is None
    assert assertion["decay_anchor_at"] == pytest.approx(max(weak_times))
    assert assertion["expires_at"] == pytest.approx(max(weak_times) + 14 * 24 * 60 * 60)


@pytest.mark.asyncio
async def test_forget_unprojected_early_claim_reconciles_shared_route_assertion(
    l2_store_with_schema: L2CognitionStore,
) -> None:
    store = l2_store_with_schema
    event_ids = [f"evt-accumulated-weak-{index}" for index in range(3)]
    assertion_id = await _materialized_assertion(
        store,
        event_ids=event_ids,
        temporal_scope="recent",
        decay_policy="time_window",
    )
    now = time.time()
    for index, event_id in enumerate(event_ids):
        await _seed_routed_claim(
            store.db_path,
            claim_id=f"claim:accumulated-weak-{index}",
            event_id=event_id,
            event_time=now - (2 - index) * 24 * 60 * 60,
            created_at=float(index + 1),
            assertion_id=assertion_id if index == 2 else None,
            fact_kind="interaction_evidence",
            temporal_cue="recurring",
            evidence_class="external_observation",
            source_type="browser-history",
            source_domain="external_activity",
            author_type="system",
        )
    assert (
        await store.refresh_entity_snapshot(
            entity_id="user:u1",
            entity_type="user",
        )
        is not None
    )

    result = await store.forget_source_events(
        [event_ids[0]],
        reason="user_delete_event",
    )

    assertion = await store.get_tom_assertion(assertion_id=assertion_id)
    assert assertion is not None
    assert assertion["status"] == "archived"
    assert assertion["evidence_events"] == event_ids[1:]
    assert assertion["temporal_scope"] == "momentary"
    assert assertion["decay_policy"] == "fast_decay"
    assert assertion["authority_ref"] == "forget:event"
    assert result["affected_subjects"] == 1
    assert (
        await store.get_tom_snapshot(
            entity_id="user:u1",
            entity_type="user",
        )
        is None
    )


@pytest.mark.asyncio
async def test_sequential_forgets_keep_collective_promotion_recomputable(
    l2_store_with_schema: L2CognitionStore,
) -> None:
    store = l2_store_with_schema
    direct_event_id = "evt-sequential-direct"
    weak_event_ids = [f"evt-sequential-weak-{index}" for index in range(3)]
    assertion_id = await _materialized_assertion(
        store,
        event_ids=[direct_event_id, *weak_event_ids],
    )
    now = time.time()
    await _seed_routed_claim(
        store.db_path,
        claim_id="claim:sequential-direct",
        event_id=direct_event_id,
        event_time=now - 60,
        created_at=1.0,
        assertion_id=assertion_id,
    )
    for index, event_id in enumerate(weak_event_ids):
        await _seed_routed_claim(
            store.db_path,
            claim_id=f"claim:sequential-weak-{index}",
            event_id=event_id,
            event_time=now - (2 - index) * 24 * 60 * 60,
            created_at=float(index + 2),
            assertion_id=None,
            fact_kind="interaction_evidence",
            temporal_cue="recurring",
            evidence_class="external_observation",
            source_type="browser-history",
            source_domain="external_activity",
            author_type="system",
        )

    await store.forget_source_events(
        [direct_event_id],
        reason="user_delete_event",
    )
    after_direct = await store.get_tom_assertion(assertion_id=assertion_id)
    assert after_direct is not None
    assert after_direct["status"] != "archived"
    assert after_direct["temporal_scope"] == "recent"
    assert after_direct["evidence_events"] == weak_event_ids

    await store.forget_source_events(
        [weak_event_ids[0]],
        reason="user_delete_event",
    )
    after_weak = await store.get_tom_assertion(assertion_id=assertion_id)
    assert after_weak is not None
    assert after_weak["status"] == "archived"
    assert after_weak["temporal_scope"] == "momentary"
    assert after_weak["decay_policy"] == "fast_decay"
    assert after_weak["evidence_events"] == weak_event_ids[1:]


@pytest.mark.asyncio
async def test_later_forget_reactivates_assertion_after_conservative_claim_is_removed(
    l2_store_with_schema: L2CognitionStore,
) -> None:
    store = l2_store_with_schema
    first_event_id = "evt-reactivate-first"
    conservative_event_id = "evt-reactivate-conservative"
    retained_event_id = "evt-reactivate-retained"
    assertion_id = await _materialized_assertion(
        store,
        event_ids=[first_event_id, conservative_event_id, retained_event_id],
    )
    now = time.time()
    await _seed_routed_claim(
        store.db_path,
        claim_id="claim:reactivate-first",
        event_id=first_event_id,
        event_time=now - 180,
        created_at=1.0,
        assertion_id=assertion_id,
    )
    await _seed_routed_claim(
        store.db_path,
        claim_id="claim:reactivate-conservative",
        event_id=conservative_event_id,
        event_time=now - 120,
        created_at=2.0,
        assertion_id=None,
        fact_kind="explicit_fact",
        temporal_cue="one_off",
        timestamp_quality="inferred",
    )
    await _seed_routed_claim(
        store.db_path,
        claim_id="claim:reactivate-retained",
        event_id=retained_event_id,
        event_time=now - 60,
        created_at=3.0,
        assertion_id=assertion_id,
    )

    await store.forget_source_events(
        [first_event_id],
        reason="user_delete_event",
    )
    archived = await store.get_tom_assertion(assertion_id=assertion_id)
    assert archived is not None
    assert archived["status"] == "archived"
    assert archived["authority_ref"] == "forget:event"
    assert archived["evidence_events"] == [
        conservative_event_id,
        retained_event_id,
    ]

    await store.forget_source_events(
        [conservative_event_id],
        reason="user_delete_event",
    )
    reactivated = await store.get_tom_assertion(assertion_id=assertion_id)
    assert reactivated is not None
    assert reactivated["status"] == "tentative"
    assert reactivated["validation_state"] == "tentative"
    assert reactivated["authority_ref"] is None
    assert reactivated["evidence_events"] == [retained_event_id]
    assert reactivated["temporal_scope"] == "stable"
    assert reactivated["decay_policy"] == "evidence_only"
    assert reactivated["expires_at"] is None


@pytest.mark.asyncio
@pytest.mark.parametrize("tombstone_antecedent", [False, True])
async def test_occurrence_stats_exclude_claim_before_tombstone_cleanup_finishes(
    l2_store_with_schema: L2CognitionStore,
    tombstone_antecedent: bool,
) -> None:
    store = l2_store_with_schema
    supporting_event_id = "evt-barrier-support"
    await _seed_routed_claim(
        store.db_path,
        claim_id="claim:barrier-window",
        event_id=supporting_event_id,
        event_time=time.time() - 60,
        created_at=1.0,
        assertion_id=None,
    )
    tombstoned_event_id = supporting_event_id
    async with sqlite_connection_async(store.db_path) as db:
        if tombstone_antecedent:
            tombstoned_event_id = "evt-barrier-antecedent"
            await db.execute(
                """
                INSERT INTO l2_claim_evidence(
                    claim_id, event_id, link_role, required_for_grounding,
                    event_time, timestamp_confidence, timestamp_quality,
                    evidence_rule_version, evidence_mode, created_at
                ) VALUES ('claim:barrier-window', ?, 'antecedent', 1,
                          ?, 'exact', 'exact', 1, 'confirmation', 2)
                """,
                (tombstoned_event_id, time.time() - 120),
            )
        await db.execute(
            """
            INSERT INTO memory_source_event_tombstones(event_id, reason, created_at)
            VALUES (?, 'test_crash_window', ?)
            """,
            (tombstoned_event_id, time.time()),
        )
        await db.commit()

    stats = await load_routed_claim_occurrence_stats(
        store.db_path,
        keys=[_ROUTE_KEY],
    )
    restarted = L2CognitionStore(db_path=store.db_path)
    await restarted.initialize()
    restarted_stats = await load_routed_claim_occurrence_stats(
        restarted.db_path,
        keys=[_ROUTE_KEY],
    )

    assert stats == {}
    assert restarted_stats == {}


@pytest.mark.asyncio
async def test_forget_archives_goal_when_surviving_evidence_is_not_all_time_trusted(
    l2_store_with_schema: L2CognitionStore,
) -> None:
    store = l2_store_with_schema
    route_key = ClaimRouteValueKey("slot:goal", "value:goal")
    direct_event_id = "evt-goal-direct-forget"
    assertion_id = await _materialized_assertion(
        store,
        event_ids=[direct_event_id],
        route_key=route_key,
        trait_family="goal_profile",
        trait_name="goal.intent",
        trait_value="ship release",
        temporal_scope="recent",
        decay_policy="time_window",
    )
    now = time.time()
    shared_claim = {
        "route_key": route_key,
        "predicate": "PLANS_TO",
        "fact_kind": "future_intent",
        "temporal_cue": "stable",
        "object_type": "goal",
        "object_value": "ship release",
        "object_surface": "ship release",
        "target_to": now + 7 * 24 * 60 * 60,
        "raw_time_frame": {"raw": "next week", "resolution": "exact"},
    }
    await _seed_routed_claim(
        store.db_path,
        claim_id="claim:goal-direct-forget",
        event_id=direct_event_id,
        event_time=now - 180,
        created_at=1.0,
        assertion_id=assertion_id,
        **shared_claim,
    )
    await _seed_routed_claim(
        store.db_path,
        claim_id="claim:goal-trusted-keep",
        event_id="evt-goal-trusted-keep",
        event_time=now - 120,
        created_at=2.0,
        assertion_id=None,
        **shared_claim,
    )
    await _seed_routed_claim(
        store.db_path,
        claim_id="claim:goal-untrusted-keep",
        event_id="evt-goal-untrusted-keep",
        event_time=now - 60,
        created_at=3.0,
        assertion_id=None,
        timestamp_quality="inferred",
        **shared_claim,
    )

    await store.forget_source_events(
        [direct_event_id],
        reason="user_delete_event",
    )

    assertion = await store.get_tom_assertion(assertion_id=assertion_id)
    assert assertion is not None
    assert assertion["status"] == "archived"
    assert assertion["authority_ref"] == "forget:event"
    assert assertion["evidence_events"] == [
        "evt-goal-trusted-keep",
        "evt-goal-untrusted-keep",
    ]


@pytest.mark.asyncio
async def test_forget_marks_expired_recent_lifecycle_consistently(
    l2_store_with_schema: L2CognitionStore,
) -> None:
    store = l2_store_with_schema
    route_key = ClaimRouteValueKey("slot:mood", "value:calm")
    forgotten_event_id = "evt-mood-forget"
    retained_event_id = "evt-mood-expired"
    assertion_id = await _materialized_assertion(
        store,
        event_ids=[forgotten_event_id, retained_event_id],
        route_key=route_key,
        trait_family="mood",
        trait_name="mood",
        trait_value="calm",
        temporal_scope="session",
        decay_policy="session_decay",
    )
    now = time.time()
    for sequence, (claim_id, event_id, event_time) in enumerate(
        (
            ("claim:mood-forget", forgotten_event_id, now - 60),
            ("claim:mood-expired", retained_event_id, now - 2 * 24 * 60 * 60),
        ),
        start=1,
    ):
        await _seed_routed_claim(
            store.db_path,
            claim_id=claim_id,
            event_id=event_id,
            event_time=event_time,
            created_at=float(sequence),
            assertion_id=assertion_id,
            route_key=route_key,
            predicate="FEELS",
            fact_kind="explicit_fact",
            temporal_cue="stable",
            object_type="mood",
            object_value="calm",
            object_surface="calm",
        )

    await store.forget_source_events(
        [forgotten_event_id],
        reason="user_delete_event",
    )

    assertion = await store.get_tom_assertion(assertion_id=assertion_id)
    assert assertion is not None
    assert assertion["status"] == "expired"
    assert assertion["validation_state"] == "expired"
    assert assertion["evidence_events"] == [retained_event_id]
    assert assertion["temporal_scope"] == "session"
    assert assertion["decay_policy"] == "session_decay"
    assert assertion["expires_at"] < time.time()
