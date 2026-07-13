"""Host-owned promotion policy tests for L2 assertion candidates."""

from __future__ import annotations

from magi.memory.l2.assertions.promotion import (
    AssertionPromotionInput,
    PromotionHorizon,
    SourceStrengthPreset,
    evaluate_assertion_promotion,
)
from magi.memory.l2.phase1_models import L2TemporalCue


def test_one_off_interaction_remains_event_only() -> None:
    decision = evaluate_assertion_promotion(
        AssertionPromotionInput(
            trait_family="interest_profile",
            fact_kind="interaction_evidence",
            predicate="VIEWED",
            evidence_class="external_observation",
            source_strength=SourceStrengthPreset.PASSIVE_EXPOSURE,
            temporal_cue=L2TemporalCue.ONE_OFF,
        )
    )

    assert decision.horizon is PromotionHorizon.EVENT_ONLY
    assert decision.expiry.temporal_scope == "momentary"
    assert decision.expiry.ttl_seconds is not None


def test_explicit_recent_signal_is_recent() -> None:
    decision = evaluate_assertion_promotion(
        AssertionPromotionInput(
            trait_family="project_profile",
            fact_kind="interaction_evidence",
            predicate="WORKS_ON",
            evidence_class="user_self_report",
            source_strength=SourceStrengthPreset.DIRECT_USER,
            temporal_cue=L2TemporalCue.RECENT,
        )
    )

    assert decision.horizon is PromotionHorizon.RECENT
    assert decision.expiry.temporal_scope == "recent"
    assert decision.expiry.ttl_seconds is not None


def test_explicit_stable_preference_is_durable() -> None:
    decision = evaluate_assertion_promotion(
        AssertionPromotionInput(
            trait_family="preference_profile",
            fact_kind="stable_preference",
            predicate="LIKES",
            evidence_class="user_self_report",
            source_strength=SourceStrengthPreset.DIRECT_USER,
            temporal_cue=L2TemporalCue.STABLE,
        )
    )

    assert decision.horizon is PromotionHorizon.DURABLE
    assert decision.expiry.temporal_scope == "stable"
    assert decision.expiry.ttl_seconds is None


def test_direct_user_interest_is_durable_without_inventing_a_time_cue() -> None:
    decision = evaluate_assertion_promotion(
        AssertionPromotionInput(
            trait_family="interest_profile",
            fact_kind="explicit_fact",
            predicate="INTERESTED_IN",
            evidence_class="user_self_report",
            source_strength=SourceStrengthPreset.DIRECT_USER,
            temporal_cue=L2TemporalCue.UNSPECIFIED,
        )
    )

    assert decision.horizon is PromotionHorizon.DURABLE


def test_passive_exposure_can_be_recent_but_never_durable() -> None:
    decision = evaluate_assertion_promotion(
        AssertionPromotionInput(
            trait_family="interest_profile",
            fact_kind="interaction_evidence",
            predicate="VIEWED",
            evidence_class="external_observation",
            source_strength=SourceStrengthPreset.PASSIVE_EXPOSURE,
            temporal_cue=L2TemporalCue.RECURRING,
            observation_count=20,
            evidence_count=20,
            distinct_days=10,
            span_days=90,
            recency_days=1,
        )
    )

    assert decision.horizon is PromotionHorizon.RECENT
    assert decision.expiry.ttl_seconds is not None


def test_sustained_engagement_requires_explicit_durable_permission() -> None:
    base = dict(
        trait_family="project_profile",
        fact_kind="interaction_evidence",
        predicate="CONTRIBUTES_TO",
        evidence_class="external_observation",
        source_strength=SourceStrengthPreset.SUSTAINED_ENGAGEMENT,
        temporal_cue=L2TemporalCue.RECURRING,
        observation_count=8,
        evidence_count=6,
        distinct_days=4,
        span_days=30,
        recency_days=2,
    )

    recent = evaluate_assertion_promotion(
        AssertionPromotionInput(**base, durable_permitted=False)
    )
    durable = evaluate_assertion_promotion(
        AssertionPromotionInput(**base, durable_permitted=True)
    )

    assert recent.horizon is PromotionHorizon.RECENT
    assert durable.horizon is PromotionHorizon.DURABLE


def test_deliberate_choice_is_recent_or_durable_by_source_permission() -> None:
    base = dict(
        trait_family="preference_profile",
        fact_kind="stable_preference",
        predicate="LIKES",
        evidence_class="external_observation",
        source_strength=SourceStrengthPreset.DELIBERATE_CHOICE,
        temporal_cue=L2TemporalCue.UNSPECIFIED,
    )

    recent = evaluate_assertion_promotion(
        AssertionPromotionInput(**base, durable_permitted=False)
    )
    durable = evaluate_assertion_promotion(
        AssertionPromotionInput(**base, durable_permitted=True)
    )

    assert recent.horizon is PromotionHorizon.RECENT
    assert durable.horizon is PromotionHorizon.DURABLE


def test_recent_interest_and_project_use_different_expiry_windows() -> None:
    common = dict(
        fact_kind="interaction_evidence",
        predicate="INTERESTED_IN",
        evidence_class="user_self_report",
        source_strength=SourceStrengthPreset.DIRECT_USER,
        temporal_cue=L2TemporalCue.RECENT,
    )

    interest = evaluate_assertion_promotion(
        AssertionPromotionInput(**common, trait_family="interest_profile")
    )
    project = evaluate_assertion_promotion(
        AssertionPromotionInput(**common, trait_family="project_profile")
    )

    assert interest.expiry.ttl_seconds == 14 * 24 * 60 * 60
    assert project.expiry.ttl_seconds == 30 * 24 * 60 * 60


def test_confirmation_does_not_turn_recent_into_durable() -> None:
    decision = evaluate_assertion_promotion(
        AssertionPromotionInput(
            trait_family="interest_profile",
            fact_kind="explicit_fact",
            predicate="INTERESTED_IN",
            evidence_class="user_self_report",
            source_strength=SourceStrengthPreset.DIRECT_USER,
            temporal_cue=L2TemporalCue.RECENT,
            user_feedback="confirmed",
        )
    )

    assert decision.horizon is PromotionHorizon.RECENT
