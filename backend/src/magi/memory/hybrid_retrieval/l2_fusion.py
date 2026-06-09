"""L2 candidate fusion: normalize, score, filter, and rank candidates from all subdomains.

Implements:
- Work Item 9: Candidate normalization and RRF-based scoring
- Work Item 10: Query-kind domain weights
- Work Item 11: Structured filtering with hard gates and soft penalties
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any, Dict, List, Literal, Optional

from .grounding import L2GroundingPlan

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# L2Candidate (normalized candidate model)
# ---------------------------------------------------------------------------

@dataclass
class L2Candidate:
    """Normalized L2 retrieval candidate for cross-subdomain ranking."""
    candidate_id: str
    kind: Literal["knowledge_edge", "assertion", "snapshot", "snapshot_history", "episode"]
    payload: dict[str, Any]
    text: str = ""
    retrieval_channels: list[str] = field(default_factory=list)
    subject_match_score: float = 0.5
    predicate_match_score: float = 0.5
    object_constraint_score: float = 1.0
    temporal_score: float = 1.0
    status_score: float = 1.0
    evidence_score: float = 0.5
    confidence_score: float = 0.5
    domain_weight: float = 1.0
    final_score: float = 0.0
    gate_status: str = "pass"
    gate_reason: str | None = None
    trace: dict[str, Any] = field(default_factory=dict)
    predicate_missing_vector_relevance: float | None = None


# ---------------------------------------------------------------------------
# Work Item 10: Domain weights
# ---------------------------------------------------------------------------

DOMAIN_WEIGHTS: dict[str, dict[str, float]] = {
    "exact_fact": {
        "knowledge_edge": 1.0,
        "assertion": 0.3,
        "snapshot": 0.3,
        "snapshot_history": 0.2,
        "episode": 0.2,
    },
    "current_state": {
        "knowledge_edge": 0.6,
        "assertion": 1.0,
        "snapshot": 1.0,
        "snapshot_history": 0.3,
        "episode": 0.3,
    },
    "historical_state": {
        "knowledge_edge": 0.6,
        "assertion": 1.0,
        "snapshot": 0.2,
        "snapshot_history": 0.8,
        "episode": 1.0,
    },
    "preference": {
        "knowledge_edge": 1.0,
        "assertion": 0.8,
        "snapshot": 0.6,
        "snapshot_history": 0.4,
        "episode": 0.5,
    },
    "temporal_episode": {
        "knowledge_edge": 0.3,
        "assertion": 0.5,
        "snapshot": 0.2,
        "snapshot_history": 0.4,
        "episode": 1.0,
    },
}

DEFAULT_DOMAIN_WEIGHT: dict[str, float] = {
    "knowledge_edge": 0.6,
    "assertion": 0.6,
    "snapshot": 0.5,
    "snapshot_history": 0.4,
    "episode": 0.5,
}


def get_domain_weight(query_kind: str, candidate_kind: str) -> float:
    """Look up the domain weight for a query-kind x candidate-kind pair."""
    weights = DOMAIN_WEIGHTS.get(query_kind, DEFAULT_DOMAIN_WEIGHT)
    return weights.get(candidate_kind, 0.5)


# ---------------------------------------------------------------------------
# Work Item 11: Structured filtering
# ---------------------------------------------------------------------------

def apply_structured_filter(
    candidate: L2Candidate,
    plan: L2GroundingPlan,
) -> None:
    """Apply hard gates and soft penalties based on grounding plan constraints.

    Sets candidate.gate_status to 'filtered' if a high-confidence constraint fails.
    Sets gate_reason with the specific failure code.
    """
    if plan.subject_scope == "self" and plan.subject_entity_ids:
        subject_id = candidate.payload.get("subject_id", "")
        if subject_id and subject_id not in plan.subject_entity_ids:
            if candidate.kind == "knowledge_edge":
                candidate.gate_status = "filtered"
                candidate.gate_reason = "subject_scope_mismatch"
                return

    for constraint in plan.object_constraints:
        if constraint.field == "object_type" and constraint.confidence >= 0.8:
            object_type = candidate.payload.get("object_type", "")
            if object_type and object_type != constraint.value:
                candidate.gate_status = "filtered"
                candidate.gate_reason = "object_type_mismatch"
                return

    if candidate.temporal_score <= 0.0:
        if plan.temporal_context.confidence >= 0.8:
            candidate.gate_status = "filtered"
            candidate.gate_reason = "time_invalid"
            return

    if candidate.kind == "knowledge_edge":
        status = candidate.payload.get("status", "")
        if status and status not in ("active", ""):
            candidate.gate_status = "filtered"
            candidate.gate_reason = "status_invalid"
            return


# ---------------------------------------------------------------------------
# Work Item 9: Fusion scoring
# ---------------------------------------------------------------------------

RRF_K = 60


def fuse_l2_candidates(
    plan: L2GroundingPlan,
    *,
    knowledge_edges: list[dict[str, Any]],
    assertions: list[dict[str, Any]],
    snapshots: list[dict[str, Any]],
    episodes: list[dict[str, Any]],
    top_k: int = 30,
) -> list[L2Candidate]:
    """Normalize, filter, score, and rank all L2 candidates."""
    candidates: list[L2Candidate] = []

    for i, edge in enumerate(knowledge_edges):
        c = L2Candidate(
            candidate_id=edge.get("triple_id", f"ke_{i}"),
            kind="knowledge_edge",
            payload=edge,
            text=edge.get("natural_summary", ""),
            retrieval_channels=edge.get("_channels", []),
            subject_match_score=edge.get("_subject_match_score", 0.5),
            predicate_match_score=edge.get("_predicate_match_score", 0.5),
            object_constraint_score=edge.get("_object_constraint_score", 1.0),
            temporal_score=edge.get("_temporal_score", 1.0),
            status_score=1.0 if edge.get("status") == "active" else 0.3,
            evidence_score=min(1.0, (edge.get("observation_count", 1) or 1) / 5.0),
            confidence_score=edge.get("confidence", 0.5),
        )
        candidates.append(c)

    for i, assertion in enumerate(assertions):
        c = L2Candidate(
            candidate_id=assertion.get("assertion_id", f"as_{i}"),
            kind="assertion",
            payload=assertion,
            text=assertion.get("natural_summary", ""),
            temporal_score=assertion.get("_temporal_score", 1.0),
            confidence_score=assertion.get("confidence_score", 0.5),
            evidence_score=min(1.0, len(assertion.get("evidence_events", []) or []) / 3.0),
        )
        candidates.append(c)

    for i, snap in enumerate(snapshots):
        kind = snap.get("_candidate_kind", "snapshot")
        c = L2Candidate(
            candidate_id=snap.get("snapshot_id", f"sn_{i}"),
            kind=kind,
            payload=snap,
            text="",
            temporal_score=snap.get("_temporal_score", 1.0),
            confidence_score=0.8,
        )
        candidates.append(c)

    for i, ep in enumerate(episodes):
        c = L2Candidate(
            candidate_id=ep.get("episode_id", f"ep_{i}"),
            kind="episode",
            payload=ep,
            text=ep.get("summary", ""),
            temporal_score=ep.get("_temporal_score", 1.0),
            evidence_score=ep.get("_entity_overlap_score", 0.0),
            confidence_score=ep.get("confidence", 0.5),
        )
        candidates.append(c)

    for c in candidates:
        c.domain_weight = get_domain_weight(plan.query_kind, c.kind)

    for c in candidates:
        apply_structured_filter(c, plan)

    for c in candidates:
        if c.gate_status == "filtered":
            c.final_score = 0.0
            continue
        c.final_score = _compute_final_score(c, plan)
        c.trace = _build_score_trace(c)

    candidates.sort(key=lambda c: c.final_score, reverse=True)

    passed = [c for c in candidates if c.gate_status != "filtered"]
    return passed[:top_k]


def _compute_final_score(c: L2Candidate, plan: L2GroundingPlan) -> float:
    """Compute the final fusion score for a candidate."""
    if c.kind == "knowledge_edge":
        if not plan.predicate_candidates:
            # Predicate couldn't be inferred → let edge-vector SEMANTIC similarity
            # drive relevance instead of the neutral 0.5 predicate_match (which let
            # structured-fallback whole-profile edges ride high). Edges hit by the
            # edge_vector channel carry a vector_distance → real semantic score;
            # structured-only fallback edges (no vector_distance = no semantic
            # evidence) get 0 and sink. Local fix for RFC #65.
            vd = c.payload.get("vector_distance")
            vector_relevance = (1.0 / (1.0 + float(vd))) if vd is not None else 0.0
            grounding_score = (
                0.40 * c.subject_match_score
                + 0.30 * vector_relevance
                + 0.20 * c.object_constraint_score
                + 0.10 * c.status_score
            )
            c.predicate_missing_vector_relevance = round(vector_relevance, 4)
        else:
            grounding_score = (
                0.40 * c.subject_match_score
                + 0.30 * c.predicate_match_score
                + 0.20 * c.object_constraint_score
                + 0.10 * c.status_score
            )
    else:
        grounding_score = 0.7

    tc_confidence = plan.temporal_context.confidence if plan.temporal_context else 0.5
    temporal_floor = 0.5 if tc_confidence < 0.8 else 0.2

    channel_count = len(c.retrieval_channels) if c.retrieval_channels else 1
    rrf_boost = 1.0 + 0.1 * (channel_count - 1)

    evidence_boost = 0.8 + 0.2 * c.evidence_score
    confidence_boost = 0.7 + 0.3 * c.confidence_score

    final = (
        c.domain_weight
        * rrf_boost
        * (0.4 + 0.6 * grounding_score)
        * (temporal_floor + (1.0 - temporal_floor) * c.temporal_score)
        * evidence_boost
        * confidence_boost
    )
    return round(final, 4)


def _build_score_trace(c: L2Candidate) -> dict[str, Any]:
    return {
        "kind": c.kind,
        "domain_weight": c.domain_weight,
        "subject_match": c.subject_match_score,
        "predicate_match": c.predicate_match_score,
        "object_constraint": c.object_constraint_score,
        "temporal": c.temporal_score,
        "status": c.status_score,
        "evidence": c.evidence_score,
        "confidence": c.confidence_score,
        "channels": c.retrieval_channels,
        "final_score": c.final_score,
        "gate_status": c.gate_status,
        "gate_reason": c.gate_reason,
        "predicate_missing_vector_relevance": c.predicate_missing_vector_relevance,
    }


# ---------------------------------------------------------------------------
# Projection: convert ranked candidates back to typed output dicts
# ---------------------------------------------------------------------------

def project_candidates(
    candidates: list[L2Candidate],
) -> dict[str, list[dict[str, Any]]]:
    """Project ranked candidates back into typed output groups."""
    result: dict[str, list[dict[str, Any]]] = {
        "entity_cards": [],
        "relationships": [],
        "assertions": [],
        "episodes": [],
        "state_facts": [],
        "state_history": [],
        "trace": [],
    }

    for c in candidates:
        payload = dict(c.payload)
        payload["_fusion_score"] = c.final_score
        payload["_fusion_trace"] = c.trace

        if c.kind == "knowledge_edge":
            result["relationships"].append(payload)
        elif c.kind == "assertion":
            result["assertions"].append(payload)
        elif c.kind == "snapshot":
            result["entity_cards"].append(payload)
        elif c.kind == "snapshot_history":
            result["state_history"].append(payload)
        elif c.kind == "episode":
            result["episodes"].append(payload)

    return result


__all__ = [
    "DOMAIN_WEIGHTS",
    "L2Candidate",
    "apply_structured_filter",
    "fuse_l2_candidates",
    "get_domain_weight",
    "project_candidates",
]
