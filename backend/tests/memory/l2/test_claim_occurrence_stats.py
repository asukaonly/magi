"""Grounded Claim history statistics used by assertion promotion."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from zoneinfo import ZoneInfo

import pytest

from magi.core.sqlite import sqlite_connection_async
from magi.memory.l2.assertions.occurrence_stats import (
    ClaimRouteValueKey,
    MAX_FUTURE_CLOCK_SKEW_SECONDS,
    load_routed_claim_occurrence_stats,
    summarize_occurrence_times,
)
from magi.memory.l2.assertions.promotion import (
    AssertionPromotionInput,
    PromotionHorizon,
    evaluate_assertion_promotion,
)
from magi.memory.l2.semantic_routing import ROUTE_CONTRACT_VERSION


async def _seed_claim(
    db_path: str,
    *,
    claim_id: str,
    event_id: str,
    key: ClaimRouteValueKey,
    event_time: float,
    timestamp_quality: str = "exact",
    created_at: float = 1.0,
    predicate: str = "INTERESTED_IN",
    fact_kind: str = "explicit_fact",
    object_type: str = "topic",
    temporal_cue: str = "recurring",
    evidence_class: str = "user_self_report",
    source_type: str = "chat",
    source_domain: str = "user_authored",
    author_type: str = "user",
    route_contract_version: int = 1,
) -> None:
    async with sqlite_connection_async(db_path) as db:
        await db.execute(
            """
            INSERT OR IGNORE INTO l2_grounded_claims(
                claim_id, identity_key, extractor_contract_version,
                evidence_rule_version, origin_attempt_key, profile_id,
                user_id, subject_ref, subject_type, canonical_predicate,
                fact_kind, object_type, polarity, specificity, confidence,
                object_value_json, object_surface, temporal_cue,
                availability, created_at, updated_at
            ) VALUES (?, ?, 1, 1, ?, 'chat.user_message', 'u1', 'user:u1',
                      'user', ?, ?, ?,
                      'positive', 'concrete', 0.9, ?, 'music', ?,
                      'active', ?, ?)
            """,
            (
                claim_id,
                f"identity:{claim_id}",
                f"attempt:{claim_id}",
                predicate,
                fact_kind,
                object_type,
                json.dumps("music"),
                temporal_cue,
                created_at,
                created_at,
            ),
        )
        await db.execute(
            """
            INSERT OR IGNORE INTO l2_claim_evidence(
                claim_id, event_id, link_role, required_for_grounding,
                event_time, timestamp_confidence, timestamp_quality,
                evidence_rule_version, evidence_mode, source_type,
                source_domain, author_type, evidence_class, created_at
            ) VALUES (?, ?, 'supporting', 1, ?, ?, ?, 1, 'direct', ?,
                      ?, ?, ?, ?)
            """,
            (
                claim_id,
                event_id,
                event_time,
                "exact" if timestamp_quality == "exact" else "inferred",
                timestamp_quality,
                source_type,
                source_domain,
                author_type,
                evidence_class,
                created_at,
            ),
        )
        await _insert_route(
            db,
            claim_id=claim_id,
            key=key,
            outcome="routed",
            created_at=created_at,
            route_contract_version=route_contract_version,
        )
        await db.commit()


async def _insert_route(
    db,  # type: ignore[no-untyped-def]
    *,
    claim_id: str,
    key: ClaimRouteValueKey,
    outcome: str,
    created_at: float,
    route_contract_version: int = 1,
    invalidated_at: float | None = None,
) -> None:
    suffix = f"v{route_contract_version}:{outcome}:{created_at}:{invalidated_at}"
    await db.execute(
        """
        INSERT OR IGNORE INTO l2_claim_projection_outcomes(
            outcome_id, claim_id, attempt_key, target_kind, target_id,
            target_slot_key, route_contract_version, outcome, reason_code,
            details_json, created_at, invalidated_at, invalidated_reason
        ) VALUES (?, ?, ?, 'route', ?, ?, ?, ?, 'test_route', ?, ?, ?, ?)
        """,
        (
            f"outcome:{claim_id}:{suffix}",
            claim_id,
            f"attempt:{claim_id}:{suffix}",
            f"route:{claim_id}:{suffix}",
            key.target_slot_key,
            route_contract_version,
            outcome,
            json.dumps({"value_fingerprint": key.value_fingerprint}),
            created_at,
            invalidated_at,
            "test_invalidated" if invalidated_at is not None else None,
        ),
    )


@pytest.mark.asyncio
async def test_latest_route_prefers_contract_version_over_future_created_at(
    l2_store_with_schema,
) -> None:
    old_key = ClaimRouteValueKey("slot:old", "value:old")
    current_key = ClaimRouteValueKey("slot:current", "value:current")
    now = 1_900_000_000.0
    await _seed_claim(
        l2_store_with_schema.db_path,
        claim_id="claim:clock-rollback",
        event_id="event:clock-rollback",
        key=old_key,
        event_time=now - 86_400,
        created_at=now + 10_000,
        route_contract_version=ROUTE_CONTRACT_VERSION - 1,
    )
    async with sqlite_connection_async(l2_store_with_schema.db_path) as db:
        await _insert_route(
            db,
            claim_id="claim:clock-rollback",
            key=current_key,
            outcome="routed",
            created_at=now,
            route_contract_version=ROUTE_CONTRACT_VERSION,
        )
        await db.commit()

    stats = await load_routed_claim_occurrence_stats(
        l2_store_with_schema.db_path,
        keys=[old_key, current_key],
        now=now,
        local_timezone=UTC,
    )

    assert old_key not in stats
    assert stats[current_key].claim_ids == ("claim:clock-rollback",)
    assert stats[current_key].supporting_event_ids == ("event:clock-rollback",)


@pytest.mark.asyncio
async def test_stats_use_active_claims_and_latest_non_invalidated_routed_outcome(
    l2_store_with_schema,
) -> None:
    key = ClaimRouteValueKey("slot:music", "value:jazz")
    now = 2_000_000_000.0
    await _seed_claim(
        l2_store_with_schema.db_path,
        claim_id="claim:kept",
        event_id="event:kept",
        key=key,
        event_time=now - 86_400,
        created_at=1.0,
    )
    await _seed_claim(
        l2_store_with_schema.db_path,
        claim_id="claim:latest-unrouted",
        event_id="event:latest-unrouted",
        key=key,
        event_time=now - 86_400,
        created_at=2.0,
    )
    await _seed_claim(
        l2_store_with_schema.db_path,
        claim_id="claim:invalidated-latest",
        event_id="event:invalidated-latest",
        key=key,
        event_time=now,
        created_at=3.0,
    )
    async with sqlite_connection_async(l2_store_with_schema.db_path) as db:
        await db.execute(
            """
            INSERT INTO l2_claim_evidence(
                claim_id, event_id, link_role, required_for_grounding,
                event_time, timestamp_confidence, timestamp_quality,
                evidence_rule_version, evidence_mode, created_at
            ) VALUES ('claim:kept', 'event:antecedent', 'antecedent', 1,
                      ?, 'exact', 'exact', 1, 'confirmation', 4.0)
            """,
            (now - 10 * 86_400,),
        )
        await _insert_route(
            db,
            claim_id="claim:latest-unrouted",
            key=key,
            outcome="unrouted",
            created_at=20.0,
        )
        await _insert_route(
            db,
            claim_id="claim:invalidated-latest",
            key=key,
            outcome="unrouted",
            created_at=30.0,
            invalidated_at=31.0,
        )
        await db.commit()

    stats = (
        await load_routed_claim_occurrence_stats(
            l2_store_with_schema.db_path,
            keys=[key],
            now=now,
            local_timezone=UTC,
        )
    )[key]
    assert stats.claim_ids == ("claim:invalidated-latest", "claim:kept")
    assert stats.observation_count == 2
    assert stats.evidence_count == 2
    assert "event:antecedent" not in stats.supporting_event_ids

    forgotten = await l2_store_with_schema.forget_source_events(
        ["event:kept"],
        reason="user_request",
    )
    assert forgotten["l2_grounded_claims"] == 1
    after_forget = (
        await load_routed_claim_occurrence_stats(
            l2_store_with_schema.db_path,
            keys=[key],
            now=now,
            local_timezone=UTC,
        )
    )[key]
    assert after_forget.claim_ids == ("claim:invalidated-latest",)
    assert after_forget.observation_count == 1


@pytest.mark.asyncio
async def test_replay_does_not_increase_claim_or_evidence_counts(
    l2_store_with_schema,
) -> None:
    key = ClaimRouteValueKey("slot:replay", "value:replay")
    seed = dict(
        db_path=l2_store_with_schema.db_path,
        claim_id="claim:replay",
        event_id="event:replay",
        key=key,
        event_time=1_900_000_000.0,
        created_at=1.0,
    )
    await _seed_claim(**seed)
    await _seed_claim(**seed)

    stats = (
        await load_routed_claim_occurrence_stats(
            l2_store_with_schema.db_path,
            keys=[key, key],
            now=1_900_000_000.0,
            local_timezone=UTC,
        )
    )[key]
    assert stats.claim_ids == ("claim:replay",)
    assert stats.supporting_event_ids == ("event:replay",)
    assert stats.observation_count == 1
    assert stats.evidence_count == 1

    await _seed_claim(
        l2_store_with_schema.db_path,
        claim_id="claim:same-event-new-observation",
        event_id="event:replay",
        key=key,
        event_time=1_900_000_000.0,
        created_at=2.0,
    )
    shared_evidence = (
        await load_routed_claim_occurrence_stats(
            l2_store_with_schema.db_path,
            keys=[key],
            now=1_900_000_000.0,
            local_timezone=UTC,
        )
    )[key]
    assert shared_evidence.observation_count == 2
    assert shared_evidence.evidence_count == 1


@pytest.mark.asyncio
async def test_direct_policy_survives_weak_replay_and_restart_recomputation(
    l2_store_with_schema,
) -> None:
    from magi.memory.l2.store import L2CognitionStore

    key = ClaimRouteValueKey("slot:preference", "value:like:jazz")
    now = 1_900_000_000.0
    await _seed_claim(
        l2_store_with_schema.db_path,
        claim_id="claim:direct",
        event_id="event:direct",
        key=key,
        event_time=now - 86_400,
        created_at=1.0,
        predicate="LIKES",
        fact_kind="stable_preference",
        temporal_cue="stable",
    )
    await _seed_claim(
        l2_store_with_schema.db_path,
        claim_id="claim:weak-replay",
        event_id="event:weak-replay",
        key=key,
        event_time=now,
        created_at=2.0,
        predicate="LIKES",
        fact_kind="explicit_fact",
        temporal_cue="one_off",
        evidence_class="external_observation",
        source_type="browser-history",
        source_domain="external_activity",
        author_type="system",
    )

    initial = (
        await load_routed_claim_occurrence_stats(
            l2_store_with_schema.db_path,
            keys=[key],
            now=now,
            local_timezone=UTC,
        )
    )[key]
    initial_decision = evaluate_assertion_promotion(
        AssertionPromotionInput(
            trait_family="preference_profile",
            **initial.promotion_fields(),
        )
    )

    assert initial.fact_kind == "stable_preference"
    assert initial.canonical_predicate == "LIKES"
    assert initial.temporal_cue == "stable"
    assert initial.evidence_class == "user_self_report"
    assert initial.source_strength == "direct_user"
    assert initial.durable_permitted is True
    assert initial_decision.horizon is PromotionHorizon.DURABLE

    restarted_store = L2CognitionStore(db_path=l2_store_with_schema.db_path)
    await restarted_store.initialize()
    recomputed = (
        await load_routed_claim_occurrence_stats(
            restarted_store.db_path,
            keys=[key],
            now=now,
            local_timezone=UTC,
        )
    )[key]
    assert recomputed == initial

    await l2_store_with_schema.forget_source_events(
        ["event:direct"],
        reason="user_request",
    )
    after_forget = (
        await load_routed_claim_occurrence_stats(
            restarted_store.db_path,
            keys=[key],
            now=now,
            local_timezone=UTC,
        )
    )[key]
    downgraded = evaluate_assertion_promotion(
        AssertionPromotionInput(
            trait_family="preference_profile",
            **after_forget.promotion_fields(),
        )
    )
    assert after_forget.source_strength == "passive_exposure"
    assert after_forget.durable_permitted is False
    assert after_forget.temporal_cue == "one_off"
    assert downgraded.horizon is PromotionHorizon.EVENT_ONLY


@pytest.mark.asyncio
async def test_structured_fact_cannot_invent_durable_permission(
    l2_store_with_schema,
) -> None:
    key = ClaimRouteValueKey("slot:form-of-address", "value:doctor")
    now = 1_900_000_000.0
    await _seed_claim(
        l2_store_with_schema.db_path,
        claim_id="claim:structured",
        event_id="event:structured",
        key=key,
        event_time=now,
        predicate="PREFERRED_FORM_OF_ADDRESS",
        fact_kind="explicit_fact",
        temporal_cue="stable",
        evidence_class="structured_record",
        source_type="history-import",
        source_domain="imported_document",
        author_type="unknown",
    )

    stats = (
        await load_routed_claim_occurrence_stats(
            l2_store_with_schema.db_path,
            keys=[key],
            now=now,
            local_timezone=UTC,
        )
    )[key]
    decision = evaluate_assertion_promotion(
        AssertionPromotionInput(
            trait_family="identity_profile",
            **stats.promotion_fields(),
        )
    )

    assert stats.source_strength == "structured_source"
    assert stats.durable_permitted is False
    assert decision.horizon is PromotionHorizon.EVENT_ONLY


@pytest.mark.asyncio
async def test_low_trust_times_count_evidence_without_inventing_timeline(
    l2_store_with_schema,
) -> None:
    key = ClaimRouteValueKey("slot:quality", "value:quality")
    now = 1_900_000_000.0
    for index, quality in enumerate(("derived_order", "file_mtime", "calendar_anchor", "exact")):
        await _seed_claim(
            l2_store_with_schema.db_path,
            claim_id=f"claim:quality:{index}",
            event_id=f"event:quality:{index}",
            key=key,
            event_time=now - (4 - index) * 86_400,
            timestamp_quality=quality,
            created_at=float(index + 1),
        )

    stats = (
        await load_routed_claim_occurrence_stats(
            l2_store_with_schema.db_path,
            keys=[key],
            now=now,
            local_timezone=UTC,
        )
    )[key]
    assert stats.observation_count == 4
    assert stats.evidence_count == 4
    assert stats.trusted_event_ids == ("event:quality:2", "event:quality:3")
    assert stats.distinct_days == 2
    assert stats.span_days == pytest.approx(1.0)
    assert stats.recency_days == pytest.approx(1.0)


def test_occurrence_days_follow_user_timezone() -> None:
    shanghai = ZoneInfo("Asia/Shanghai")
    first = datetime(2026, 1, 1, 15, 30, tzinfo=UTC).timestamp()
    second = datetime(2026, 1, 1, 16, 30, tzinfo=UTC).timestamp()

    stats = summarize_occurrence_times(
        [("event:1", first), ("event:2", second)],
        now=second,
        local_timezone=shanghai,
    )

    assert stats.distinct_days == 2
    assert stats.span_days == pytest.approx(1 / 24)


def test_occurrence_timeline_ignores_nonpositive_and_nonfinite_times() -> None:
    stats = summarize_occurrence_times(
        [
            ("event:zero", 0.0),
            ("event:negative", -1.0),
            ("event:nan", float("nan")),
            ("event:valid", 1_900_000_000.0),
        ],
        now=1_900_000_000.0,
        local_timezone=UTC,
    )

    assert stats.trusted_event_ids == ("event:valid",)
    assert stats.distinct_days == 1


def test_occurrence_timeline_rejects_future_anchors_beyond_clock_skew() -> None:
    now = 1_900_000_000.0
    stats = summarize_occurrence_times(
        [
            ("event:valid", now - 86_400),
            ("event:clock-drift", now + MAX_FUTURE_CLOCK_SKEW_SECONDS),
            ("event:future", now + MAX_FUTURE_CLOCK_SKEW_SECONDS + 1),
        ],
        now=now,
        local_timezone=UTC,
    )

    assert stats.trusted_event_ids == ("event:valid", "event:clock-drift")
    assert "event:future" not in stats.trusted_event_ids
    assert stats.last_observed_at == now + MAX_FUTURE_CLOCK_SKEW_SECONDS
    assert stats.recency_days == 0.0


@pytest.mark.asyncio
async def test_third_day_history_reaches_recent_promotion(l2_store_with_schema) -> None:
    key = ClaimRouteValueKey("slot:recent", "value:recent")
    now = 1_900_000_000.0
    for index, days_ago in enumerate((2, 1, 0)):
        await _seed_claim(
            l2_store_with_schema.db_path,
            claim_id=f"claim:recent:{index}",
            event_id=f"event:recent:{index}",
            key=key,
            event_time=now - days_ago * 86_400,
            created_at=float(index + 1),
            predicate="VIEWED",
            fact_kind="interaction_evidence",
            evidence_class="external_observation",
            source_type="browser-history",
            source_domain="external_activity",
            author_type="system",
        )
    stats = (
        await load_routed_claim_occurrence_stats(
            l2_store_with_schema.db_path,
            keys=[key],
            now=now,
            local_timezone=UTC,
        )
    )[key]

    decision = evaluate_assertion_promotion(
        AssertionPromotionInput(
            trait_family="interest_profile",
            **stats.promotion_fields(),
        )
    )
    assert stats.distinct_days == 3
    assert decision.horizon is PromotionHorizon.RECENT


@pytest.mark.asyncio
async def test_sustained_claims_remain_recent_without_direct_durable_permission(
    l2_store_with_schema,
) -> None:
    key = ClaimRouteValueKey("slot:durable", "value:durable")
    now = 1_900_000_000.0
    for index, days_ago in enumerate((14, 10, 7, 3, 1, 0)):
        await _seed_claim(
            l2_store_with_schema.db_path,
            claim_id=f"claim:durable:{index}",
            event_id=f"event:durable:{index}",
            key=key,
            event_time=now - days_ago * 86_400,
            created_at=float(index + 1),
            predicate="CONTRIBUTES_TO",
            fact_kind="interaction_evidence",
            object_type="project",
            evidence_class="external_observation",
            source_type="git-activity",
            source_domain="external_activity",
            author_type="system",
        )
    stats = (
        await load_routed_claim_occurrence_stats(
            l2_store_with_schema.db_path,
            keys=[key],
            now=now,
            local_timezone=UTC,
        )
    )[key]

    decision = evaluate_assertion_promotion(
        AssertionPromotionInput(
            trait_family="project_profile",
            **stats.promotion_fields(),
        )
    )
    assert stats.observation_count == 6
    assert stats.evidence_count == 6
    assert stats.distinct_days == 6
    assert stats.span_days == pytest.approx(14.0)
    assert stats.source_strength == "sustained_engagement"
    assert stats.durable_permitted is False
    assert decision.horizon is PromotionHorizon.RECENT
