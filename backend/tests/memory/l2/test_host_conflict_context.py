"""Regression tests for exhaustive host-owned Phase 2 conflict context."""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import pytest

from magi.memory.l2.graph_conflicts import build_graph_conflict_matrix
from magi.memory.l2.models import L2Phase1FactClaim, L2Phase1Result
from magi.memory.l2.pipeline.context import L2PipelineContextMixin
from magi.memory.l2.pipeline.extraction_contracts import (
    _Phase1ExtractionFlow,
    _Phase2Context,
)
from magi.memory.l2.pipeline.phase2_flow import L2Phase2FlowMixin
from magi.memory.l2.pipeline.validation.claim_assessments import (
    AssessmentActionEligibility,
    L2ClaimAssessmentValidationMixin,
)
from magi.memory.l2.semantic_routing import SemanticRouteInput, derive_semantic_route


class _PagedCognitionStore:
    def __init__(
        self,
        *,
        relationships: list[dict[str, Any]] | None = None,
        assertions: list[dict[str, Any]] | None = None,
    ) -> None:
        self.relationships = relationships or []
        self.assertions = assertions or []
        self.relationship_calls: list[dict[str, Any]] = []
        self.assertion_calls: list[dict[str, Any]] = []

    async def get_relationships(self, **kwargs: Any) -> list[dict[str, Any]]:
        self.relationship_calls.append(dict(kwargs))
        rows = [
            row
            for row in self.relationships
            if row.get("subject_id") == kwargs.get("subject_id")
            and row.get("status", "active") == kwargs.get("status", "active")
        ]
        offset = int(kwargs.get("offset", 0))
        limit = int(kwargs.get("limit", 100))
        return rows[offset : offset + limit]

    async def list_tom_assertions(self, **kwargs: Any) -> list[dict[str, Any]]:
        self.assertion_calls.append(dict(kwargs))
        families = set(kwargs.get("trait_families") or [])
        target_entity_id = kwargs.get("target_entity_id")
        rows = [
            row
            for row in self.assertions
            if row.get("entity_id") == kwargs.get("entity_id")
            and row.get("entity_type") == kwargs.get("entity_type")
            and row.get("trait_family") in families
            and (target_entity_id is None or row.get("target_entity_id") == target_entity_id)
            and row.get("status", "active") == "active"
            and not row.get("expired", False)
        ]
        offset = int(kwargs.get("offset", 0))
        limit = int(kwargs.get("limit", 100))
        return rows[offset : offset + limit]


class _ValidationHarness(
    L2PipelineContextMixin,
    L2Phase2FlowMixin,
    L2ClaimAssessmentValidationMixin,
):
    def __init__(
        self,
        store: _PagedCognitionStore,
        *,
        assertion_candidates: list[dict[str, Any]] | None = None,
    ) -> None:
        self._cognition_store = store
        self._l1_store = None
        self._entity_catalog = None
        self._conflict_arbitration_min_confidence = 0.85
        self._assertion_candidates = assertion_candidates or []

    async def _load_phase2_occurrence_stats(self, phase1_flow: Any) -> dict[Any, Any]:
        return {}

    def _validate_phase2_assertion_output(self, *args: Any, **kwargs: Any):
        return list(self._assertion_candidates), 0

    def _build_structured_facet_candidates(self, **kwargs: Any) -> list[dict[str, Any]]:
        return []

    def _log_phase2_candidate_validation(self, batch: Any, candidates: Any) -> None:
        return None


def _claim(
    *,
    predicate: str,
    object_ref: str = "topic:jazz",
) -> L2Phase1FactClaim:
    return L2Phase1FactClaim(
        claim_id=f"claim:{predicate.casefold()}",
        subject_ref="user:u1",
        subject_type="user",
        predicate=predicate,
        object_ref=object_ref,
        object_type="topic",
        fact_kind="stable_preference",
        confidence=0.95,
        evidence_text=f"evidence for {predicate}",
        supporting_event_ids=["evt-new"],
    )


def _route(claim: L2Phase1FactClaim):
    return derive_semantic_route(
        SemanticRouteInput(
            claim_id=claim.claim_id,
            subject_id="user:u1",
            subject_type="user",
            canonical_predicate=claim.predicate,
            fact_kind=claim.fact_kind,
            object_type=claim.object_type,
            object_value=claim.object_ref,
            object_entity_id=claim.object_ref,
            temporal_cue="stable",
            specificity="concrete",
            target_from=None,
            target_to=None,
            raw_time_expression="",
            time_resolution="unscheduled",
        )
    )


def _phase1_flow(
    claim: L2Phase1FactClaim,
    *,
    routes: dict[str, Any] | None = None,
) -> _Phase1ExtractionFlow:
    return _Phase1ExtractionFlow(
        phase1_result=L2Phase1Result(fact_claims=[claim]),
        resolved_mentions=[],
        profile_signal_object_refs=set(),
        semantic_routes=routes or {},
        claim_outcomes=[],
    )


def _phase2_context(
    *,
    graph_edges: list[dict[str, Any]] | None = None,
    assertions: list[dict[str, Any]] | None = None,
) -> _Phase2Context:
    return _Phase2Context(
        focal_entities=[],
        existing_graph_edges=graph_edges or [],
        existing_assertions=assertions or [],
        graph_conflict_rules=[
            rule.to_record() for rule in build_graph_conflict_matrix().values()
        ],
    )


@pytest.mark.asyncio
async def test_graph_conflict_beyond_model_context_cap_is_host_validated() -> None:
    claim = _claim(predicate="DISLIKES")
    decoys = [
        {
            "triple_id": f"triple:decoy:{index}",
            "subject_id": "user:u1",
            "predicate": "KNOWS",
            "object_id": f"person:{index}",
            "scope_key": "global",
            "evidence_event_ids": [f"evt-decoy:{index}"],
            "status": "active",
        }
        for index in range(131)
    ]
    conflict = {
        "triple_id": "triple:old-like",
        "subject_id": "user:u1",
        "predicate": "LIKES",
        "object_id": "topic:jazz",
        "scope_key": "global",
        "evidence_event_ids": ["evt-old"],
        "status": "active",
    }
    store = _PagedCognitionStore(relationships=[*decoys, conflict])
    harness = _ValidationHarness(store)

    candidates = await harness._validate_phase2_outputs(
        batch=SimpleNamespace(stored_event=SimpleNamespace(), batch_event_ids=["evt-new"]),
        phase1_flow=_phase1_flow(claim),
        phase2_context=_phase2_context(graph_edges=decoys[:30]),
        phase2_result=SimpleNamespace(claim_assessments=[]),
        graph_candidates=[
            {
                "_claim_id": claim.claim_id,
                "subject_id": "user:u1",
                "predicate": "DISLIKES",
                "object_id": "topic:jazz",
                "object_type": "topic",
                "scope": {},
            }
        ],
        rejected_graph_count=0,
    )

    assert len(candidates.validated_claim_assessments) == 1
    assessment = candidates.validated_claim_assessments[0]
    assert assessment.related_record_id == "triple:old-like"
    assert assessment.action_eligibility is AssessmentActionEligibility.PENDING_ARBITRATION
    assert [call["offset"] for call in store.relationship_calls] == [0, 100]
    assert all(call["limit"] == 100 for call in store.relationship_calls)


@pytest.mark.asyncio
async def test_assertion_conflict_beyond_model_context_cap_is_host_validated() -> None:
    claim = _claim(predicate="LIKES")
    route = _route(claim)
    assertion_candidate = {
        "supporting_claim_ids": [claim.claim_id],
        "semantic_route_slot_key": route.slot_key,
        "trait_value": "like",
    }
    decoys = [
        {
            "assertion_id": f"assert:decoy:{index}",
            "entity_id": "user:u1",
            "entity_type": "user",
            "trait_family": route.family,
            "trait_name": "preference.unrelated",
            "trait_value": "unknown",
            "target_entity_id": route.target_entity_id,
            "target_entity_type": route.target_entity_type,
            "slot_key": f"slt_decoy_{index}",
            "scope_key": "global",
            "evidence_events": [f"evt-decoy:{index}"],
            "status": "active",
        }
        for index in range(121)
    ]
    conflict = {
        "assertion_id": "assert:old-dislike",
        "entity_id": "user:u1",
        "entity_type": "user",
        "trait_family": route.family,
        "trait_name": route.trait_code,
        "trait_value": "dislike",
        "target_entity_id": route.target_entity_id,
        "target_entity_type": route.target_entity_type,
        "slot_key": route.slot_key,
        "scope_key": "global",
        "evidence_events": ["evt-old"],
        "status": "active",
    }
    store = _PagedCognitionStore(assertions=[*decoys, conflict])
    harness = _ValidationHarness(store, assertion_candidates=[assertion_candidate])

    candidates = await harness._validate_phase2_outputs(
        batch=SimpleNamespace(stored_event=SimpleNamespace(), batch_event_ids=["evt-new"]),
        phase1_flow=_phase1_flow(claim, routes={claim.claim_id: route}),
        phase2_context=_phase2_context(assertions=decoys[:20]),
        phase2_result=SimpleNamespace(claim_assessments=[]),
        graph_candidates=[],
        rejected_graph_count=0,
    )

    assert len(candidates.validated_claim_assessments) == 1
    assessment = candidates.validated_claim_assessments[0]
    assert assessment.related_record_id == "assert:old-dislike"
    assert assessment.action_eligibility is AssessmentActionEligibility.PENDING_ARBITRATION
    assert [call["offset"] for call in store.assertion_calls] == [0, 100]
    assert all(call["include_expired"] is False for call in store.assertion_calls)
    assert all(call["include_inactive"] is False for call in store.assertion_calls)
    assert all(call["include_superseded"] is False for call in store.assertion_calls)
