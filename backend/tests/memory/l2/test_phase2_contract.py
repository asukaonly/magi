"""Tests for the narrow Phase 2 inference contract."""

from types import SimpleNamespace
from typing import Any

from magi.memory.event_contracts import MemoryDomain, TomDepth
from magi.memory.l2.models import (
    L2Phase1FactClaim,
    L2Phase1Result,
    L2Phase2AssertionCandidate,
    L2Phase2ClaimAssessment,
    L2Phase2Result,
)
from magi.memory.l2.pipeline.prompts import PHASE2_INTEGRATE_SYSTEM_PROMPT
from magi.memory.l2.pipeline.validation.assertions import L2AssertionValidationMixin
from magi.memory.l2.pipeline.validation.claim_assessments import (
    L2ClaimAssessmentValidationMixin,
)


class _AssertionHarness(L2AssertionValidationMixin):
    def _resolve_self_entity_id(self, event: object) -> str:
        _ = event
        return "user:u1"

    def _non_empty_text(self, value: Any) -> str | None:
        return str(value or "").strip() or None

    def _normalize_entity_type(self, raw_value: Any) -> str | None:
        return str(raw_value or "").strip().casefold() or None


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
                    "trait_family": "preference_profile",
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
    assert [item.supporting_claim_ids for item in result.assertion_candidates] == [
        ["claim:diiv"]
    ]
    assert not hasattr(result, "graph_edges")
    assert not hasattr(result, "contradiction_hints")
    assert not hasattr(result.assertion_candidates[0], "confidence")
    assert not hasattr(result.assertion_candidates[0], "volatility_index")
    assert not hasattr(result.assertion_candidates[0], "supporting_event_ids")


def test_phase2_prompt_forbids_recreating_facts_or_evidence() -> None:
    assert "Do not recreate graph edges" in PHASE2_INTEGRATE_SYSTEM_PROMPT
    assert '"supporting_claim_ids"' in PHASE2_INTEGRATE_SYSTEM_PROMPT
    assert '"graph_edges"' not in PHASE2_INTEGRATE_SYSTEM_PROMPT
    assert '"supporting_event_ids"' not in PHASE2_INTEGRATE_SYSTEM_PROMPT
    assert '"recommended_action"' not in PHASE2_INTEGRATE_SYSTEM_PROMPT


def test_phase2_assertion_metadata_is_derived_from_grounded_claims() -> None:
    phase1_result = L2Phase1Result(
        fact_claims=[
            L2Phase1FactClaim(
                claim_id="claim:diiv",
                subject_ref="user:u1",
                predicate="LIKES",
                object_ref="group:diiv",
                object_type="group",
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
        phase1_result=phase1_result,
        phase2_assertions=[
            L2Phase2AssertionCandidate(
                entity_ref="user:self",
                trait_family="preference_profile",
                trait_name="interest.music",
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
        phase1_result=L2Phase1Result(),
        phase2_assertions=[
            L2Phase2AssertionCandidate(
                entity_ref="user:self",
                trait_family="preference_profile",
                trait_name="interest.music",
                trait_value="DIIV",
                supporting_claim_ids=["claim:invented"],
            )
        ],
    )

    assert prepared == []
    assert rejected == 1


def test_phase2_claim_assessment_can_only_request_host_revalidation() -> None:
    phase1_result = L2Phase1Result(
        fact_claims=[
            L2Phase1FactClaim(
                claim_id="claim:diiv",
                predicate="DISLIKES",
                object_ref="group:diiv",
                confidence=0.8,
                evidence_text="我现在不喜欢 DIIV 了",
                supporting_event_ids=["evt-diiv"],
            )
        ]
    )

    hints, rejected = L2ClaimAssessmentValidationMixin()._validate_phase2_claim_assessments(
        phase1_result=phase1_result,
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
                "predicate": "LIKES",
                "object_id": "group:diiv",
            }
        ],
        existing_assertions=[],
    )

    assert rejected == 0
    assert len(hints) == 1
    assert hints[0].target_record_id == "triple:old-like"
    assert hints[0].target_record_type == "knowledge_graph"
    assert hints[0].contradiction_kind == "preference_reversal"
    assert hints[0].confidence == 0.8
    assert hints[0].recommended_action == "revalidate_only"


def test_phase2_claim_assessment_rejects_unknown_records() -> None:
    hints, rejected = L2ClaimAssessmentValidationMixin()._validate_phase2_claim_assessments(
        phase1_result=L2Phase1Result(
            fact_claims=[L2Phase1FactClaim(claim_id="claim:diiv")]
        ),
        assessments=[
            L2Phase2ClaimAssessment(
                claim_id="claim:diiv",
                relationship="contradicts",
                related_record_id="triple:invented",
            )
        ],
        existing_graph_edges=[],
        existing_assertions=[],
    )

    assert hints == []
    assert rejected == 1
