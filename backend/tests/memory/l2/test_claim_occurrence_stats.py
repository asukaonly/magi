"""Grounded Claim history statistics used by assertion promotion."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from zoneinfo import ZoneInfo

import pytest

from magi.core.sqlite import sqlite_connection_async
from magi.memory.l2.assertions.occurrence_stats import (
    ClaimRouteValueKey,
    load_routed_claim_occurrence_stats,
    summarize_occurrence_times,
)
from magi.memory.l2.assertions.promotion import (
    AssertionPromotionInput,
    PromotionHorizon,
    SourceStrengthPreset,
    evaluate_assertion_promotion,
)
from magi.memory.l2.phase1_models import L2TemporalCue


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
                      'positive', 'concrete', 0.9, ?, 'music', 'recurring',
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
            ) VALUES (?, ?, 'supporting', 1, ?, ?, ?, 1, 'direct', 'chat',
                      'user_authored', 'user', 'user_self_report', ?)
            """,
            (
                claim_id,
                event_id,
                event_time,
                "exact" if timestamp_quality == "exact" else "inferred",
                timestamp_quality,
                created_at,
            ),
        )
        await _insert_route(
            db,
            claim_id=claim_id,
            key=key,
            outcome="routed",
            created_at=created_at,
        )
        await db.commit()


async def _insert_route(
    db,  # type: ignore[no-untyped-def]
    *,
    claim_id: str,
    key: ClaimRouteValueKey,
    outcome: str,
    created_at: float,
    invalidated_at: float | None = None,
) -> None:
    suffix = f"{outcome}:{created_at}:{invalidated_at}"
    await db.execute(
        """
        INSERT OR IGNORE INTO l2_claim_projection_outcomes(
            outcome_id, claim_id, attempt_key, target_kind, target_id,
            target_slot_key, route_contract_version, outcome, reason_code,
            details_json, created_at, invalidated_at, invalidated_reason
        ) VALUES (?, ?, ?, 'route', ?, ?, 1, ?, 'test_route', ?, ?, ?, ?)
        """,
        (
            f"outcome:{claim_id}:{suffix}",
            claim_id,
            f"attempt:{claim_id}:{suffix}",
            f"route:{claim_id}:{suffix}",
            key.target_slot_key,
            outcome,
            json.dumps({"value_fingerprint": key.value_fingerprint}),
            created_at,
            invalidated_at,
            "test_invalidated" if invalidated_at is not None else None,
        ),
    )


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
async def test_low_trust_times_count_evidence_without_inventing_timeline(
    l2_store_with_schema,
) -> None:
    key = ClaimRouteValueKey("slot:quality", "value:quality")
    now = 1_900_000_000.0
    for index, quality in enumerate(
        ("derived_order", "file_mtime", "calendar_anchor", "exact")
    ):
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
            fact_kind="interaction_evidence",
            predicate="VIEWED",
            evidence_class="external_observation",
            source_strength=SourceStrengthPreset.PASSIVE_EXPOSURE,
            temporal_cue=L2TemporalCue.RECURRING,
            **stats.promotion_fields(),
        )
    )
    assert stats.distinct_days == 3
    assert decision.horizon is PromotionHorizon.RECENT


@pytest.mark.asyncio
async def test_six_claims_spanning_fourteen_days_reach_durable_gates(
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
            object_type="project",
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
            fact_kind="interaction_evidence",
            predicate="CONTRIBUTES_TO",
            evidence_class="external_observation",
            source_strength=SourceStrengthPreset.SUSTAINED_ENGAGEMENT,
            temporal_cue=L2TemporalCue.RECURRING,
            durable_permitted=True,
            **stats.promotion_fields(),
        )
    )
    assert stats.observation_count == 6
    assert stats.evidence_count == 6
    assert stats.distinct_days == 6
    assert stats.span_days == pytest.approx(14.0)
    assert decision.horizon is PromotionHorizon.DURABLE
