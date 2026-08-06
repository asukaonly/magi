from __future__ import annotations

from dataclasses import replace

from magi.memory.l2.assertions.materialize import MaterializationInput, materialize_assertion
from magi.memory.l2.assertions.occurrence_stats import (
    ClaimOccurrenceStats,
    ClaimRouteValueKey,
)
from magi.memory.l2.phase1_models import L2Phase1FactClaim
from magi.memory.l2.semantic_routing import SemanticRouteInput, derive_semantic_route


NOW = 1_800_000_000.0


def _claim(
    *,
    predicate: str = "LIKES",
    object_ref: str = "咖啡",
    object_type: str = "concept",
    fact_kind: str = "stable_preference",
) -> L2Phase1FactClaim:
    return L2Phase1FactClaim(
        claim_id="clm_1",
        subject_ref="user:local_user",
        subject_type="user",
        predicate=predicate,
        object_ref=object_ref,
        object_type=object_type,
        fact_kind=fact_kind,
        temporal_cue="stable" if fact_kind != "future_intent" else "recent",
        evidence_text=f"我喜欢{object_ref}" if predicate == "LIKES" else object_ref,
        confidence=0.91,
        supporting_event_ids=["evt_1"],
    )


def _route(claim: L2Phase1FactClaim, *, object_entity_id: str | None = "concept:coffee"):
    return derive_semantic_route(
        SemanticRouteInput(
            claim_id=claim.claim_id,
            canonical_predicate=claim.predicate,
            fact_kind=str(claim.fact_kind),
            temporal_cue=claim.temporal_cue.value,
            subject_id=claim.subject_ref,
            subject_type=claim.subject_type,
            object_value=claim.object_ref,
            object_type=claim.object_type,
            object_entity_id=object_entity_id,
            specificity=claim.specificity,
            raw_time_expression=claim.raw_time_expression,
            target_from=claim.target_from,
            target_to=claim.target_to,
            time_resolution=str((claim.raw_time_frame or {}).get("resolution") or "unscheduled"),
            time_frame=claim.raw_time_frame,
        )
    )


def _stats(route, claim: L2Phase1FactClaim) -> ClaimOccurrenceStats:
    return ClaimOccurrenceStats(
        key=ClaimRouteValueKey(route.slot_key, route.value_fingerprint),
        fact_kind=str(claim.fact_kind),
        canonical_predicate=claim.predicate,
        temporal_cue=str(claim.temporal_cue.value),
        evidence_class="user_self_report",
        source_strength="direct_user",
        durable_permitted=True,
        claim_ids=(claim.claim_id,),
        supporting_event_ids=("evt_1",),
        trusted_event_ids=("evt_1",),
        recent_policy_event_ids=("evt_1",) if claim.temporal_cue.value == "recent" else (),
        observation_count=1,
        evidence_count=1,
        distinct_days=1,
        first_observed_at=NOW - 60,
        last_observed_at=NOW - 60,
        span_days=0.0,
        recency_days=0.0,
    )


def _input(claim: L2Phase1FactClaim, route, **overrides):
    values = {
        "route": route,
        "claims": (claim,),
        "occurrence_stats": _stats(route, claim),
        "self_entity_id": "user:local_user",
        "direct_assertion_write_allowed": True,
        "profile_allows_assertion": True,
        "allowed_families": frozenset({route.family}),
        "allowed_traits": None,
        "source_domain": "personal",
        "inference_depth": "self_report",
        "observed_at": NOW - 60,
        "now": NOW,
    }
    values.update(overrides)
    return MaterializationInput(**values)


def test_direct_preference_materializes_without_phase2_candidate() -> None:
    claim = _claim()
    route = _route(claim)

    decision = materialize_assertion(_input(claim, route))

    assert decision.action == "write"
    assert decision.candidate is not None
    assert decision.candidate["trait_name"] == "preference.affinity"
    assert decision.candidate["trait_value"] == "like"
    assert decision.candidate["target_entity_id"] == "concept:coffee"
    assert decision.candidate["supporting_claim_ids"] == ["clm_1"]
    assert decision.natural_summary == "我喜欢咖啡"


def test_text_target_preference_survives_entity_resolution_failure() -> None:
    claim = _claim(object_ref="一种很小众的手冲方法")
    route = _route(claim, object_entity_id=None)

    decision = materialize_assertion(_input(claim, route))

    assert decision.action == "write"
    assert decision.candidate is not None
    assert decision.candidate["target_entity_id"] == ""
    assert decision.candidate["semantic_route_slot_key"] == route.slot_key
    assert decision.natural_summary == "我喜欢一种很小众的手冲方法"


def test_model_summary_changes_copy_but_not_materialization_semantics() -> None:
    claim = _claim()
    route = _route(claim)
    baseline = materialize_assertion(_input(claim, route))
    summarized = materialize_assertion(
        _input(claim, route, natural_summary="用户明确喜欢咖啡。")
    )

    assert baseline.action == summarized.action == "write"
    assert baseline.candidate is not None and summarized.candidate is not None
    semantic_keys = set(baseline.candidate).difference({"natural_summary"})
    assert {key: baseline.candidate[key] for key in semantic_keys} == {
        key: summarized.candidate[key] for key in semantic_keys
    }
    assert summarized.natural_summary == "用户明确喜欢咖啡。"


def test_policy_denial_is_terminal_event_only() -> None:
    claim = _claim()
    route = _route(claim)

    decision = materialize_assertion(
        _input(claim, route, direct_assertion_write_allowed=False)
    )

    assert decision.action == "event_only"
    assert decision.reason_code == "direct_assertion_write_disabled"
    assert decision.candidate is None


def test_non_self_profile_claim_is_not_materialized() -> None:
    claim = replace(_claim(), subject_ref="person:someone_else")
    route = _route(claim)

    decision = materialize_assertion(_input(claim, route))

    assert decision.action == "event_only"
    assert decision.reason_code == "non_self_profile_subject"


def test_historical_goal_with_untrusted_time_requires_review() -> None:
    claim = _claim(
        predicate="PLANS_TO",
        object_ref="今年秋天去一次海边",
        object_type="activity",
        fact_kind="future_intent",
    )
    claim.raw_time_expression = "今年秋天"
    claim.raw_time_frame = {"resolution": "calendar_anchor"}
    claim.target_from = NOW + 10_000
    claim.target_to = NOW + 20_000
    route = _route(claim, object_entity_id=None)
    stats = replace(_stats(route, claim), trusted_event_ids=())

    decision = materialize_assertion(_input(claim, route, occurrence_stats=stats))

    assert decision.action == "review"
    assert decision.reason_code == "goal_low_time_confidence"


def test_current_goal_writes_lineage_and_target_window() -> None:
    claim = _claim(
        predicate="PLANS_TO",
        object_ref="今年秋天去一次海边",
        object_type="activity",
        fact_kind="future_intent",
    )
    claim.raw_time_expression = "今年秋天"
    claim.raw_time_frame = {"resolution": "calendar_anchor", "precision": "season"}
    claim.target_from = NOW + 10_000
    claim.target_to = NOW + 20_000
    route = _route(claim, object_entity_id=None)

    decision = materialize_assertion(_input(claim, route))

    assert decision.action == "write"
    assert decision.candidate is not None
    assert decision.candidate["trait_value"] == "今年秋天去一次海边"
    assert decision.candidate["semantic_lineage_key"] == route.goal_lineage_key
    assert decision.candidate["target_window"]["target_to"] == NOW + 20_000
    assert decision.expires_at == NOW + 20_000
