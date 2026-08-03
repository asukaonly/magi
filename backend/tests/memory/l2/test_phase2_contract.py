"""Tests for the narrow Phase 2 inference contract."""

from types import SimpleNamespace
from typing import Any

import pytest

from magi.memory.event_contracts import MemoryDomain, TomDepth
from magi.memory.l2.assertions.occurrence_stats import (
    ClaimOccurrenceStats,
    ClaimRouteValueKey,
)
from magi.memory.l2.models import (
    L2Phase1FactClaim,
    L2Phase1Result,
    L2Phase2AssertionCandidate,
    L2Phase2ClaimAssessment,
    L2Phase2Result,
)
from magi.memory.l2.graph_conflicts import build_graph_conflict_matrix
from magi.memory.l2.phase1_models import L2TemporalCue
from magi.memory.l2.pipeline.prompts import PHASE2_INTEGRATE_SYSTEM_PROMPT
from magi.memory.l2.pipeline.validation.assertions import L2AssertionValidationMixin
from magi.memory.l2.pipeline.validation.claim_assessments import (
    AssessmentActionEligibility,
    L2ClaimAssessmentValidationMixin,
)
from magi.memory.l2.semantic_routing import SemanticRouteInput, derive_semantic_route


class _AssertionHarness(L2AssertionValidationMixin):
    def _validate_phase2_assertions(self, **kwargs):  # type: ignore[no-untyped-def]
        phase1_result = kwargs.get("phase1_result")
        kwargs.setdefault(
            "occurrence_stats_by_key",
            _synthetic_occurrence_stats(phase1_result),
        )
        return super()._validate_phase2_assertions(**kwargs)

    def _resolve_self_entity_id(self, event: object) -> str:
        _ = event
        return "user:u1"

    def _non_empty_text(self, value: Any) -> str | None:
        return str(value or "").strip() or None

    def _normalize_entity_type(self, raw_value: Any) -> str | None:
        return str(raw_value or "").strip().casefold() or None


def _routes_for(phase1_result: L2Phase1Result):  # type: ignore[no-untyped-def]
    routes = {}
    for claim in phase1_result.fact_claims:
        object_ref = str(claim.object_ref or "")
        route = derive_semantic_route(
            SemanticRouteInput(
                claim_id=claim.claim_id,
                subject_id=str(claim.subject_ref or "user:u1"),
                subject_type=str(claim.subject_type or "user"),
                canonical_predicate=str(claim.predicate or ""),
                fact_kind=str(claim.fact_kind or "explicit_fact"),
                object_type=str(claim.object_type or "other"),
                object_value=claim.object_ref,
                object_entity_id=object_ref if ":" in object_ref else None,
                temporal_cue=str(claim.temporal_cue),
            )
        )
        routes[claim.claim_id] = route
    return routes


def _synthetic_occurrence_stats(
    phase1_result: L2Phase1Result | None,
) -> dict[ClaimRouteValueKey, ClaimOccurrenceStats]:
    """Build explicit unit-test statistics without invoking durable storage."""

    if phase1_result is None:
        return {}
    routes = _routes_for(phase1_result)
    claim_ids_by_key: dict[ClaimRouteValueKey, set[str]] = {}
    event_ids_by_key: dict[ClaimRouteValueKey, set[str]] = {}
    for claim in phase1_result.fact_claims:
        route = routes.get(claim.claim_id)
        if route is None or not route.can_project_assertion or not route.value_fingerprint:
            continue
        key = ClaimRouteValueKey(str(route.slot_key), str(route.value_fingerprint))
        claim_ids_by_key.setdefault(key, set()).add(claim.claim_id)
        event_ids_by_key.setdefault(key, set()).update(claim.supporting_event_ids)
    return {
        key: ClaimOccurrenceStats(
            key=key,
            claim_ids=tuple(sorted(claim_ids)),
            supporting_event_ids=tuple(sorted(event_ids_by_key[key])),
            trusted_event_ids=tuple(sorted(event_ids_by_key[key])),
            observation_count=len(claim_ids),
            evidence_count=len(event_ids_by_key[key]),
            distinct_days=1 if event_ids_by_key[key] else 0,
            first_observed_at=1_700_000_000.0 if event_ids_by_key[key] else None,
            last_observed_at=1_700_000_000.0 if event_ids_by_key[key] else None,
            span_days=0.0,
            recency_days=0.0 if event_ids_by_key[key] else None,
        )
        for key, claim_ids in claim_ids_by_key.items()
    }


def test_phase2_result_contains_only_claim_assessments_and_assertions() -> None:
    result = L2Phase2Result.from_dict(
        {
            "claim_assessments": [
                {
                    "claim_id": "claim:diiv",
                    "relationship": "contradicts",
                    "related_record_id": "triple:old",
                }
            ],
            "assertion_candidates": [
                {
                    "entity_ref": "user:self",
                    "entity_type": "user",
                    "trait_family": "interest_profile",
                    "trait_name": "interest.music",
                    "trait_value": "DIIV",
                    "natural_summary": "喜欢 DIIV 的音乐",
                    "supporting_claim_ids": ["claim:diiv"],
                    "confidence": 0.99,
                    "volatility_index": 0.99,
                    "supporting_event_ids": ["invented-event"],
                }
            ],
            "graph_edges": [{"predicate": "LIKES"}],
            "contradiction_hints": [{"recommended_action": "mark_deprecated"}],
        }
    )

    assert [item.claim_id for item in result.claim_assessments] == ["claim:diiv"]
    assert [item.supporting_claim_ids for item in result.assertion_candidates] == [["claim:diiv"]]
    assert not hasattr(result, "graph_edges")
    assert not hasattr(result, "contradiction_hints")
    assert not hasattr(result.assertion_candidates[0], "confidence")
    assert not hasattr(result.assertion_candidates[0], "volatility_index")
    assert not hasattr(result.assertion_candidates[0], "supporting_event_ids")
    assert not hasattr(result.assertion_candidates[0], "trait_family")
    assert not hasattr(result.assertion_candidates[0], "trait_name")


def test_phase2_prompt_forbids_recreating_facts_or_evidence() -> None:
    assert "Do not recreate graph edges" in PHASE2_INTEGRATE_SYSTEM_PROMPT
    assert '"supporting_claim_ids"' in PHASE2_INTEGRATE_SYSTEM_PROMPT
    assert '"graph_edges"' not in PHASE2_INTEGRATE_SYSTEM_PROMPT
    assert '"supporting_event_ids"' not in PHASE2_INTEGRATE_SYSTEM_PROMPT
    assert '"recommended_action"' not in PHASE2_INTEGRATE_SYSTEM_PROMPT
    assert '"trait_family"' not in PHASE2_INTEGRATE_SYSTEM_PROMPT
    assert '"trait_name"' not in PHASE2_INTEGRATE_SYSTEM_PROMPT


def test_phase2_assertion_metadata_is_derived_from_grounded_claims() -> None:
    phase1_result = L2Phase1Result(
        fact_claims=[
            L2Phase1FactClaim(
                claim_id="claim:diiv",
                subject_ref="user:u1",
                predicate="LIKES",
                object_ref="group:diiv",
                object_type="group",
                fact_kind="stable_preference",
                temporal_cue=L2TemporalCue.STABLE,
                confidence=0.3,
                supporting_event_ids=["evt-diiv"],
            )
        ]
    )
    event = SimpleNamespace(
        event_id="evt-diiv",
        timestamp=1_700_000_000.0,
        source="chat",
        user_id="u1",
        memory_domain=MemoryDomain.USER_AUTHORED,
        tom_depth=TomDepth.TOPOLOGY_ONLY,
    )

    prepared, rejected = _AssertionHarness()._validate_phase2_assertions(
        event=event,
        profile=SimpleNamespace(
            allow_assertion=True,
            assertion_mode="phase2_candidate",
            allowed_assertion_families=frozenset({"preference_profile"}),
            allowed_assertion_traits="all",
        ),
        policy=SimpleNamespace(allow_assertion_write=True, assertion_scope="full"),
        graph_candidates=[],
        default_event_ids=["evt-diiv"],
        semantic_routes=_routes_for(phase1_result),
        phase1_result=phase1_result,
        phase2_assertions=[
            L2Phase2AssertionCandidate(
                entity_ref="user:self",
                trait_value="DIIV",
                natural_summary="喜欢 DIIV 的音乐",
                supporting_claim_ids=["claim:diiv"],
            )
        ],
    )

    assert rejected == 0
    assert len(prepared) == 1
    assert prepared[0]["evidence_events"] == ["evt-diiv"]
    assert prepared[0]["confidence_score"] == 0.3
    assert prepared[0]["volatility_index"] == 0.2
    assert prepared[0]["inference_depth"] == "topology_only"
    assert prepared[0]["trait_family"] == "preference_profile"
    assert prepared[0]["trait_name"] == "preference.affinity"
    assert prepared[0]["trait_value"] == "like"
    assert prepared[0]["target_entity_id"] == "group:diiv"


def test_phase2_rejects_event_only_profile_candidate() -> None:
    phase1_result = L2Phase1Result(
        fact_claims=[
            L2Phase1FactClaim(
                claim_id="claim:page",
                subject_ref="user:u1",
                predicate="VIEWED",
                object_ref="topic:memory",
                object_type="topic",
                fact_kind="explicit_fact",
                temporal_cue=L2TemporalCue.ONE_OFF,
                confidence=0.7,
                supporting_event_ids=["evt-page"],
            )
        ]
    )
    event = SimpleNamespace(
        event_id="evt-page",
        timestamp=1_700_000_000.0,
        source="chrome-history",
        user_id="u1",
        memory_domain=MemoryDomain.EXTERNAL_ACTIVITY,
        tom_depth=TomDepth.TOPOLOGY_ONLY,
    )

    prepared, rejected = _AssertionHarness()._validate_phase2_assertions(
        event=event,
        profile=SimpleNamespace(
            allow_assertion=True,
            assertion_mode="phase2_candidate",
            allowed_assertion_families=frozenset({"interest_profile"}),
            allowed_assertion_traits="all",
        ),
        policy=SimpleNamespace(
            allow_assertion_write=True,
            assertion_scope="full",
            evidence_weight=0.5,
        ),
        graph_candidates=[],
        default_event_ids=["evt-page"],
        semantic_routes=_routes_for(phase1_result),
        phase1_result=phase1_result,
        phase2_assertions=[
            L2Phase2AssertionCandidate(
                entity_ref="user:self",
                trait_value="Memory systems",
                supporting_claim_ids=["claim:page"],
            )
        ],
    )

    assert prepared == []
    assert rejected == 1


def test_phase2_uses_full_ledger_counts_for_passive_promotion() -> None:
    phase1_result = L2Phase1Result(
        fact_claims=[
            L2Phase1FactClaim(
                claim_id="claim:current",
                subject_ref="user:u1",
                predicate="INTERESTED_IN",
                object_ref="topic:memory",
                object_type="topic",
                fact_kind="explicit_fact",
                temporal_cue=L2TemporalCue.RECURRING,
                confidence=0.7,
                supporting_event_ids=["evt-current"],
            )
        ]
    )
    routes = _routes_for(phase1_result)
    route = routes["claim:current"]
    key = ClaimRouteValueKey(str(route.slot_key), str(route.value_fingerprint))
    occurrence_stats = ClaimOccurrenceStats(
        key=key,
        claim_ids=("claim:day-1", "claim:day-2", "claim:current"),
        supporting_event_ids=("evt-day-1", "evt-day-2", "evt-current"),
        trusted_event_ids=("evt-day-1", "evt-day-2", "evt-current"),
        observation_count=3,
        evidence_count=3,
        distinct_days=3,
        first_observed_at=1_699_827_200.0,
        last_observed_at=1_700_000_000.0,
        span_days=2.0,
        recency_days=0.0,
    )
    event = SimpleNamespace(
        event_id="evt-current",
        timestamp=1_700_000_000.0,
        source="browser-history",
        user_id="u1",
        memory_domain=MemoryDomain.EXTERNAL_ACTIVITY,
        tom_depth=TomDepth.TOPOLOGY_ONLY,
    )

    prepared, rejected = _AssertionHarness()._validate_phase2_assertions(
        event=event,
        profile=SimpleNamespace(
            allow_assertion=True,
            assertion_mode="phase2_candidate",
            allowed_assertion_families=frozenset({"interest_profile"}),
            allowed_assertion_traits="all",
        ),
        policy=SimpleNamespace(allow_assertion_write=True, assertion_scope="full"),
        graph_candidates=[],
        default_event_ids=["evt-current"],
        semantic_routes=routes,
        occurrence_stats_by_key={key: occurrence_stats},
        phase1_result=phase1_result,
        phase2_assertions=[
            L2Phase2AssertionCandidate(
                entity_ref="user:u1",
                trait_value="Memory systems",
                supporting_claim_ids=["claim:current"],
            )
        ],
    )

    assert rejected == 0
    assert prepared[0]["temporal_scope"] == "recent"


def test_phase2_does_not_fabricate_counts_when_ledger_stats_are_missing() -> None:
    phase1_result = L2Phase1Result(
        fact_claims=[
            L2Phase1FactClaim(
                claim_id="claim:missing-stats",
                subject_ref="user:u1",
                predicate="INTERESTED_IN",
                object_ref="topic:memory",
                object_type="topic",
                fact_kind="explicit_fact",
                temporal_cue=L2TemporalCue.RECURRING,
                confidence=0.7,
                supporting_event_ids=["evt-current"],
            )
        ]
    )
    event = SimpleNamespace(
        event_id="evt-current",
        timestamp=1_700_000_000.0,
        source="browser-history",
        user_id="u1",
        memory_domain=MemoryDomain.EXTERNAL_ACTIVITY,
        tom_depth=TomDepth.TOPOLOGY_ONLY,
    )

    with pytest.raises(RuntimeError, match="durable occurrence statistics"):
        _AssertionHarness()._validate_phase2_assertions(
            event=event,
            profile=SimpleNamespace(
                allow_assertion=True,
                assertion_mode="phase2_candidate",
                allowed_assertion_families=frozenset({"interest_profile"}),
                allowed_assertion_traits="all",
            ),
            policy=SimpleNamespace(allow_assertion_write=True, assertion_scope="full"),
            graph_candidates=[],
            default_event_ids=["evt-current"],
            semantic_routes=_routes_for(phase1_result),
            occurrence_stats_by_key={},
            phase1_result=phase1_result,
            phase2_assertions=[
                L2Phase2AssertionCandidate(
                    entity_ref="user:u1",
                    trait_value="Memory systems",
                    supporting_claim_ids=["claim:missing-stats"],
                )
            ],
        )


def test_phase2_derives_recent_profile_expiry_from_temporal_evidence() -> None:
    phase1_result = L2Phase1Result(
        fact_claims=[
            L2Phase1FactClaim(
                claim_id="claim:project",
                subject_ref="user:u1",
                predicate="WORKS_ON",
                object_ref="project:magi",
                object_type="project",
                fact_kind="explicit_fact",
                temporal_cue=L2TemporalCue.RECENT,
                confidence=0.8,
                supporting_event_ids=["evt-project"],
            )
        ]
    )
    event = SimpleNamespace(
        event_id="evt-project",
        timestamp=1_700_000_000.0,
        source="chat",
        user_id="u1",
        memory_domain=MemoryDomain.USER_AUTHORED,
        tom_depth=TomDepth.TOPOLOGY_ONLY,
    )

    prepared, rejected = _AssertionHarness()._validate_phase2_assertions(
        event=event,
        profile=SimpleNamespace(
            allow_assertion=True,
            assertion_mode="phase2_candidate",
            allowed_assertion_families=frozenset({"project_profile"}),
            allowed_assertion_traits="all",
        ),
        policy=SimpleNamespace(
            allow_assertion_write=True,
            assertion_scope="full",
            evidence_weight=1.0,
        ),
        graph_candidates=[],
        default_event_ids=["evt-project"],
        semantic_routes=_routes_for(phase1_result),
        phase1_result=phase1_result,
        phase2_assertions=[
            L2Phase2AssertionCandidate(
                entity_ref="user:self",
                trait_value="Magi",
                supporting_claim_ids=["claim:project"],
            )
        ],
    )

    assert rejected == 0
    assert prepared[0]["temporal_scope"] == "recent"
    assert prepared[0]["decay_policy"] == "time_window"
    assert prepared[0]["expires_at"] > event.timestamp
    assert prepared[0]["memory_subdomain"] == "state"
    assert prepared[0]["trait_name"] == "project.engagement.active"


def test_phase2_mixed_one_off_and_recent_evidence_cannot_become_durable() -> None:
    phase1_result = L2Phase1Result(
        fact_claims=[
            L2Phase1FactClaim(
                claim_id="claim:one-off",
                subject_ref="user:u1",
                predicate="LIKES",
                object_ref="group:diiv",
                object_type="group",
                fact_kind="stable_preference",
                temporal_cue=L2TemporalCue.ONE_OFF,
                confidence=0.8,
                supporting_event_ids=["evt-one-off"],
            ),
            L2Phase1FactClaim(
                claim_id="claim:recent",
                subject_ref="user:u1",
                predicate="LIKES",
                object_ref="group:diiv",
                object_type="group",
                fact_kind="stable_preference",
                temporal_cue=L2TemporalCue.RECENT,
                confidence=0.8,
                supporting_event_ids=["evt-recent"],
            ),
        ]
    )
    event = SimpleNamespace(
        event_id="evt-recent",
        timestamp=1_700_000_000.0,
        source="chat",
        user_id="u1",
        memory_domain=MemoryDomain.USER_AUTHORED,
        tom_depth=TomDepth.TOPOLOGY_ONLY,
    )

    prepared, rejected = _AssertionHarness()._validate_phase2_assertions(
        event=event,
        profile=SimpleNamespace(
            allow_assertion=True,
            assertion_mode="phase2_candidate",
            allowed_assertion_families=frozenset({"preference_profile"}),
            allowed_assertion_traits="all",
        ),
        policy=SimpleNamespace(
            allow_assertion_write=True,
            assertion_scope="full",
            evidence_weight=1.0,
        ),
        graph_candidates=[],
        default_event_ids=["evt-one-off", "evt-recent"],
        semantic_routes=_routes_for(phase1_result),
        phase1_result=phase1_result,
        phase2_assertions=[
            L2Phase2AssertionCandidate(
                entity_ref="user:self",
                trait_value="DIIV",
                supporting_claim_ids=["claim:one-off", "claim:recent"],
            )
        ],
    )

    assert rejected == 0
    assert prepared[0]["temporal_scope"] == "recent"
    assert prepared[0]["expires_at"] > event.timestamp


def test_phase2_external_preference_signal_is_not_durable_by_default() -> None:
    phase1_result = L2Phase1Result(
        fact_claims=[
            L2Phase1FactClaim(
                claim_id="claim:external-like",
                subject_ref="listener:u1",
                subject_type="person",
                predicate="LIKES",
                object_ref="group:diiv",
                object_type="group",
                fact_kind="stable_preference",
                temporal_cue=L2TemporalCue.STABLE,
                confidence=0.8,
                supporting_event_ids=["evt-external-like"],
            )
        ]
    )
    event = SimpleNamespace(
        event_id="evt-external-like",
        timestamp=1_700_000_000.0,
        source="play-history",
        user_id="u1",
        memory_domain=MemoryDomain.EXTERNAL_ACTIVITY,
        tom_depth=TomDepth.TOPOLOGY_ONLY,
    )

    prepared, rejected = _AssertionHarness()._validate_phase2_assertions(
        event=event,
        profile=SimpleNamespace(
            allow_assertion=True,
            assertion_mode="phase2_candidate",
            allowed_assertion_families=frozenset({"preference_profile"}),
            allowed_assertion_traits="all",
        ),
        policy=SimpleNamespace(
            allow_assertion_write=True,
            assertion_scope="full",
            evidence_weight=0.5,
        ),
        graph_candidates=[],
        default_event_ids=["evt-external-like"],
        semantic_routes=_routes_for(phase1_result),
        phase1_result=phase1_result,
        phase2_assertions=[
            L2Phase2AssertionCandidate(
                entity_ref="listener:u1",
                entity_type="person",
                trait_value="DIIV",
                supporting_claim_ids=["claim:external-like"],
            )
        ],
    )

    assert prepared == []
    assert rejected == 1


def test_phase2_rejects_interest_claim_as_preference_profile() -> None:
    phase1_result = L2Phase1Result(
        fact_claims=[
            L2Phase1FactClaim(
                claim_id="claim:interest",
                subject_ref="user:u1",
                predicate="INTERESTED_IN",
                object_ref="topic:memory",
                object_type="topic",
                fact_kind="explicit_fact",
                temporal_cue=L2TemporalCue.RECENT,
                confidence=0.8,
                supporting_event_ids=["evt-interest"],
            )
        ]
    )
    event = SimpleNamespace(
        event_id="evt-interest",
        timestamp=1_700_000_000.0,
        source="chat",
        user_id="u1",
        memory_domain=MemoryDomain.USER_AUTHORED,
        tom_depth=TomDepth.TOPOLOGY_ONLY,
    )

    prepared, rejected = _AssertionHarness()._validate_phase2_assertions(
        event=event,
        profile=SimpleNamespace(
            allow_assertion=True,
            assertion_mode="phase2_candidate",
            allowed_assertion_families=frozenset({"preference_profile"}),
            allowed_assertion_traits="all",
        ),
        policy=SimpleNamespace(
            allow_assertion_write=True,
            assertion_scope="full",
            evidence_weight=1.0,
        ),
        graph_candidates=[],
        default_event_ids=["evt-interest"],
        semantic_routes=_routes_for(phase1_result),
        phase1_result=phase1_result,
        phase2_assertions=[
            L2Phase2AssertionCandidate(
                entity_ref="user:self",
                trait_value="Memory systems",
                supporting_claim_ids=["claim:interest"],
            )
        ],
    )

    assert prepared == []
    assert rejected == 1


def test_phase2_keeps_mood_session_lifetime() -> None:
    phase1_result = L2Phase1Result(
        fact_claims=[
            L2Phase1FactClaim(
                claim_id="claim:mood",
                subject_ref="user:u1",
                predicate="FEELS",
                object_ref="calm",
                object_type="concept",
                fact_kind="explicit_fact",
                temporal_cue=L2TemporalCue.RECENT,
                confidence=0.8,
                supporting_event_ids=["evt-mood"],
            )
        ]
    )
    event = SimpleNamespace(
        event_id="evt-mood",
        timestamp=1_700_000_000.0,
        source="chat",
        user_id="u1",
        memory_domain=MemoryDomain.USER_AUTHORED,
        tom_depth=TomDepth.DEFENSIVE_PSYCHOLOGY,
    )

    prepared, rejected = _AssertionHarness()._validate_phase2_assertions(
        event=event,
        profile=SimpleNamespace(
            allow_assertion=True,
            assertion_mode="phase2_candidate",
            allowed_assertion_families=frozenset({"mood"}),
            allowed_assertion_traits="all",
        ),
        policy=SimpleNamespace(
            allow_assertion_write=True,
            assertion_scope="full",
            evidence_weight=1.0,
        ),
        graph_candidates=[],
        default_event_ids=["evt-mood"],
        semantic_routes=_routes_for(phase1_result),
        phase1_result=phase1_result,
        phase2_assertions=[
            L2Phase2AssertionCandidate(
                entity_ref="user:self",
                trait_value="calm",
                supporting_claim_ids=["claim:mood"],
            )
        ],
    )

    assert rejected == 0
    assert prepared[0]["temporal_scope"] == "session"
    assert prepared[0]["decay_policy"] == "session_decay"
    assert prepared[0]["expires_at"] == event.timestamp + 12 * 60 * 60


@pytest.mark.parametrize(
    ("trait_family", "expected_scope", "expected_ttl"),
    [
        ("stress", "daily", 24 * 60 * 60),
        ("engagement", "session", 12 * 60 * 60),
    ],
)
def test_phase2_keeps_other_short_lived_state_lifetimes(
    trait_family: str,
    expected_scope: str,
    expected_ttl: int,
) -> None:
    claim_id = f"claim:{trait_family}"
    event_id = f"evt-{trait_family}"
    phase1_result = L2Phase1Result(
        fact_claims=[
            L2Phase1FactClaim(
                claim_id=claim_id,
                subject_ref="user:u1",
                predicate="HAS_METRIC",
                object_ref=trait_family,
                object_type="concept",
                fact_kind="explicit_fact",
                temporal_cue=L2TemporalCue.RECENT,
                confidence=0.8,
                supporting_event_ids=[event_id],
            )
        ]
    )
    event = SimpleNamespace(
        event_id=event_id,
        timestamp=1_700_000_000.0,
        source="chat",
        user_id="u1",
        memory_domain=MemoryDomain.USER_AUTHORED,
        tom_depth=TomDepth.DEFENSIVE_PSYCHOLOGY,
    )

    prepared, rejected = _AssertionHarness()._validate_phase2_assertions(
        event=event,
        profile=SimpleNamespace(
            allow_assertion=True,
            assertion_mode="phase2_candidate",
            allowed_assertion_families=frozenset({trait_family}),
            allowed_assertion_traits="all",
        ),
        policy=SimpleNamespace(
            allow_assertion_write=True,
            assertion_scope="full",
            evidence_weight=1.0,
        ),
        graph_candidates=[],
        default_event_ids=[event_id],
        semantic_routes=_routes_for(phase1_result),
        phase1_result=phase1_result,
        phase2_assertions=[
            L2Phase2AssertionCandidate(
                entity_ref="user:self",
                trait_value="high",
                supporting_claim_ids=[claim_id],
            )
        ],
    )

    assert rejected == 0
    assert prepared[0]["temporal_scope"] == expected_scope
    assert prepared[0]["expires_at"] == event.timestamp + expected_ttl


def test_phase2_assertion_rejects_unknown_claim_reference() -> None:
    event = SimpleNamespace(
        event_id="evt-diiv",
        timestamp=1_700_000_000.0,
        source="chat",
        user_id="u1",
        memory_domain=MemoryDomain.USER_AUTHORED,
        tom_depth=TomDepth.TOPOLOGY_ONLY,
    )

    prepared, rejected = _AssertionHarness()._validate_phase2_assertions(
        event=event,
        profile=SimpleNamespace(
            allow_assertion=True,
            assertion_mode="phase2_candidate",
            allowed_assertion_families=frozenset({"preference_profile"}),
            allowed_assertion_traits="all",
        ),
        policy=SimpleNamespace(allow_assertion_write=True, assertion_scope="full"),
        graph_candidates=[],
        default_event_ids=["evt-diiv"],
        semantic_routes={},
        phase1_result=L2Phase1Result(),
        phase2_assertions=[
            L2Phase2AssertionCandidate(
                entity_ref="user:self",
                trait_value="DIIV",
                supporting_claim_ids=["claim:invented"],
            )
        ],
    )

    assert prepared == []
    assert rejected == 1


def test_phase2_claim_assessment_requires_host_validated_pending_action() -> None:
    phase1_result = L2Phase1Result(
        fact_claims=[
            L2Phase1FactClaim(
                claim_id="claim:diiv",
                subject_ref="user:u1",
                predicate="DISLIKES",
                object_ref="group:diiv",
                object_type="group",
                fact_kind="stable_preference",
                confidence=0.8,
                evidence_text="我现在不喜欢 DIIV 了",
                supporting_event_ids=["evt-diiv"],
            )
        ]
    )

    validated, rejected = L2ClaimAssessmentValidationMixin()._validate_phase2_claim_assessments(
        phase1_result=phase1_result,
        semantic_routes={},
        graph_candidates=[
            {
                "_claim_id": "claim:diiv",
                "subject_id": "user:u1",
                "predicate": "DISLIKES",
                "object_id": "group:diiv",
                "scope": {},
            }
        ],
        assertion_candidates=[],
        assessments=[
            L2Phase2ClaimAssessment(
                claim_id="claim:diiv",
                relationship="contradicts",
                related_record_id="triple:old-like",
            )
        ],
        existing_graph_edges=[
            {
                "triple_id": "triple:old-like",
                "subject_id": "user:u1",
                "predicate": "LIKES",
                "object_id": "group:diiv",
                "scope_key": "global",
                "evidence_event_ids": ["evt-old"],
            }
        ],
        existing_assertions=[],
        graph_conflict_rules=list(build_graph_conflict_matrix().values()),
        arbitration_min_confidence=0.75,
    )

    assert rejected == 0
    assert len(validated) == 1
    assert validated[0].action_eligibility is AssessmentActionEligibility.PENDING_ARBITRATION
    assert validated[0].hint is not None
    assert validated[0].hint.target_record_id == "triple:old-like"
    assert validated[0].hint.target_record_type == "knowledge_graph"
    assert validated[0].hint.contradiction_kind == "preference_reversal"
    assert validated[0].hint.confidence == 0.8
    assert validated[0].hint.recommended_action == "pending_arbitration"


def test_phase2_claim_assessment_rejects_unknown_records() -> None:
    validated, rejected = L2ClaimAssessmentValidationMixin()._validate_phase2_claim_assessments(
        phase1_result=L2Phase1Result(fact_claims=[L2Phase1FactClaim(claim_id="claim:diiv")]),
        semantic_routes={},
        graph_candidates=[],
        assertion_candidates=[],
        assessments=[
            L2Phase2ClaimAssessment(
                claim_id="claim:diiv",
                relationship="contradicts",
                related_record_id="triple:invented",
            )
        ],
        existing_graph_edges=[],
        existing_assertions=[],
        graph_conflict_rules=[],
        arbitration_min_confidence=0.85,
    )

    assert rejected == 1
    assert len(validated) == 1
    assert validated[0].action_eligibility is AssessmentActionEligibility.REJECTED
    assert validated[0].target_id
