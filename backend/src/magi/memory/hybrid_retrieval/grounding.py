"""L2 query grounding: deterministic resolution of user queries into structured retrieval plans."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, List, Literal, Optional

from ..l2.predicate_catalog import (
    expand_predicates_via_catalog,
    get_answer_kinds,
    get_family_predicates,
    get_spec,
)
from .models import L2Conditions, L2SemanticFrame, TemporalContext


@dataclass
class GroundedEntityCandidate:
    """A resolved entity candidate with provenance."""
    entity_id: str
    entity_type: str
    surface: str
    score: float
    source: Literal["exact", "alias", "vector", "llm", "rule"] = "rule"


@dataclass
class GroundedPredicateCandidate:
    """A resolved predicate candidate with provenance."""
    predicate: str
    family: str | None = None
    score: float = 1.0
    source: Literal["alias", "family", "vector", "llm", "rule"] = "rule"


@dataclass
class GroundedConstraint:
    """A structured constraint from grounding."""
    field: str
    operator: str
    value: Any
    confidence: float = 1.0


@dataclass
class L2GroundingPlan:
    """Fully grounded L2 retrieval plan.

    Built deterministically from L2Conditions + entity catalog + predicate catalog.
    No LLM call in the critical path.
    """
    query_kind: str = "unknown"
    subject_candidates: List[GroundedEntityCandidate] = field(default_factory=list)
    object_candidates: List[GroundedEntityCandidate] = field(default_factory=list)
    predicate_candidates: List[GroundedPredicateCandidate] = field(default_factory=list)
    predicate_family: str | None = None
    answer_kind: str = "unknown"
    relation_direction: str = "outgoing"
    subject_scope: str = "none"
    object_constraints: List[GroundedConstraint] = field(default_factory=list)
    temporal_context: TemporalContext = field(default_factory=TemporalContext)
    confidence: float = 0.5
    allowed_evidence_classes: Optional[set[str]] = None
    evidence_focus_source: Optional[str] = None  # "llm" | "rule_heuristic" | "family_fallback" | None
    predicate_source: Optional[str] = None  # "explicit"|"embedding"|"llm_family"|"keyword_fallback" (RFC #65 P1)
    allow_soft_edges: bool = True  # RFC #65 P2

    @property
    def expanded_predicates(self) -> list[str]:
        """Return all candidate predicates expanded by synonym groups."""
        raw = [c.predicate for c in self.predicate_candidates]
        if not raw:
            return []
        return expand_predicates_via_catalog(raw)

    @property
    def subject_entity_ids(self) -> list[str]:
        return [c.entity_id for c in self.subject_candidates]

    @property
    def object_entity_ids(self) -> list[str]:
        return [c.entity_id for c in self.object_candidates]


# ---------------------------------------------------------------------------
# Grounding builder
# ---------------------------------------------------------------------------

_FAMILY_TO_QUERY_KIND: dict[str, str] = {
    "preference": "preference",
    "relationship": "exact_fact",
    "activity": "temporal_episode",
    "profile_fact": "exact_fact",
    "topology": "exact_fact",
}

_ANSWER_KIND_ALIASES: dict[str, str] = {
    "creator": "creator",
    "place": "place",
    "topic": "topic",
    "person": "person",
    "software": "software",
    "food": "preference",
    "media": "preference",
}


def build_grounding_plan(
    conditions: L2Conditions,
    *,
    resolved_entities: list[dict[str, Any]],
    user_id: str | None = None,
    time_range: Any | None = None,
) -> L2GroundingPlan:
    """Build an L2GroundingPlan deterministically from L2Conditions and catalog lookups.

    This is Phase 1 grounding: no LLM call, purely deterministic rules + catalog.
    """
    plan = L2GroundingPlan()

    _ground_subjects(plan, conditions, resolved_entities, user_id)
    _ground_predicates(plan, conditions)
    plan.query_kind = _infer_query_kind(plan, conditions)
    plan.answer_kind = _infer_answer_kind(plan, conditions)
    plan.relation_direction = conditions.relation_direction or "outgoing"
    _ground_object_constraints(plan, conditions, resolved_entities)
    plan.temporal_context = _build_temporal_context(conditions, time_range)
    plan.confidence = _compute_plan_confidence(plan)
    plan.allowed_evidence_classes = conditions.allowed_evidence_classes
    plan.evidence_focus_source = conditions.evidence_focus_source
    plan.predicate_source = conditions.predicate_source
    plan.allow_soft_edges = conditions.allow_soft_edges

    return plan


def _ground_subjects(
    plan: L2GroundingPlan,
    conditions: L2Conditions,
    resolved_entities: list[dict[str, Any]],
    user_id: str | None,
) -> None:
    semantic_frame = conditions.semantic_frame
    if semantic_frame and semantic_frame.subject_scope == "self" and user_id:
        plan.subject_scope = "self"
        plan.subject_candidates.append(GroundedEntityCandidate(
            entity_id=f"user:{user_id}",
            entity_type="person",
            surface="self",
            score=1.0,
            source="rule",
        ))
    elif conditions.subject_hint:
        plan.subject_scope = "explicit"
        for entity in resolved_entities:
            eid = entity.get("entity_id", "")
            if conditions.subject_hint.lower() in eid.lower():
                plan.subject_candidates.append(GroundedEntityCandidate(
                    entity_id=eid,
                    entity_type=entity.get("entity_type", "other"),
                    surface=entity.get("canonical_name", eid),
                    score=entity.get("confidence", 0.8),
                    source=_map_match_source(entity.get("match_source")),
                ))

    if not plan.subject_candidates and user_id and not conditions.entities:
        plan.subject_scope = "self"
        plan.subject_candidates.append(GroundedEntityCandidate(
            entity_id=f"user:{user_id}",
            entity_type="person",
            surface="self",
            score=0.6,
            source="rule",
        ))


def _ground_predicates(
    plan: L2GroundingPlan,
    conditions: L2Conditions,
) -> None:
    if conditions.predicates:
        for pred in conditions.predicates:
            spec = get_spec(pred)
            plan.predicate_candidates.append(GroundedPredicateCandidate(
                predicate=spec.canonical if spec else pred.upper(),
                family=spec.family if spec else None,
                score=1.0 if spec else 0.5,
                source="alias" if spec else "rule",
            ))
        if plan.predicate_candidates:
            plan.predicate_family = plan.predicate_candidates[0].family

    elif conditions.predicate_family:
        plan.predicate_family = conditions.predicate_family
        family_preds = get_family_predicates(conditions.predicate_family)
        for pred in family_preds:
            plan.predicate_candidates.append(GroundedPredicateCandidate(
                predicate=pred,
                family=conditions.predicate_family,
                score=0.8,
                source="family",
            ))


def _infer_query_kind(plan: L2GroundingPlan, conditions: L2Conditions) -> str:
    semantic_frame = conditions.semantic_frame
    if semantic_frame:
        family = semantic_frame.query_family
        if family == "affinity":
            return "preference"
        if family in ("relationship", "profile"):
            return "exact_fact"
        if family == "activity":
            return "temporal_episode"
        if family == "lookup":
            return "exact_fact"

    if plan.predicate_family:
        return _FAMILY_TO_QUERY_KIND.get(plan.predicate_family, "unknown")

    if conditions.trait_families:
        return "current_state"

    return "unknown"


def _infer_answer_kind(plan: L2GroundingPlan, conditions: L2Conditions) -> str:
    semantic_frame = conditions.semantic_frame
    if semantic_frame and semantic_frame.answer_kind != "unknown":
        return semantic_frame.answer_kind

    if plan.predicate_candidates:
        for candidate in plan.predicate_candidates:
            kinds = get_answer_kinds(candidate.predicate)
            if kinds:
                return kinds[0]

    if conditions.entity_types:
        return conditions.entity_types[0]

    return "unknown"


def _ground_object_constraints(
    plan: L2GroundingPlan,
    conditions: L2Conditions,
    resolved_entities: list[dict[str, Any]],
) -> None:
    semantic_frame = conditions.semantic_frame
    if semantic_frame:
        for constraint in semantic_frame.constraints:
            plan.object_constraints.append(GroundedConstraint(
                field=constraint.facet,
                operator="eq",
                value=constraint.resolved_entity_id or constraint.raw_value,
                confidence=0.9 if constraint.resolved_entity_id else 0.6,
            ))

    if conditions.entity_types:
        for et in conditions.entity_types:
            plan.object_constraints.append(GroundedConstraint(
                field="object_type",
                operator="in",
                value=et,
                confidence=0.8,
            ))

    for entity in resolved_entities:
        if entity.get("entity_id") not in plan.subject_entity_ids:
            plan.object_candidates.append(GroundedEntityCandidate(
                entity_id=entity["entity_id"],
                entity_type=entity.get("entity_type", "other"),
                surface=entity.get("canonical_name", entity["entity_id"]),
                score=entity.get("confidence", 0.7),
                source=_map_match_source(entity.get("match_source")),
            ))


def _build_temporal_context(
    conditions: L2Conditions,
    time_range: Any | None,
) -> TemporalContext:
    if time_range is None:
        return TemporalContext(mode="none")

    start = getattr(time_range, "start", None)
    end = getattr(time_range, "end", None)

    if start is not None and end is not None:
        return TemporalContext(
            mode="during",
            start=start,
            end=end,
            confidence=0.8,
        )
    if start is not None:
        return TemporalContext(
            mode="since",
            start=start,
            confidence=0.7,
        )
    if end is not None:
        return TemporalContext(
            mode="before",
            end=end,
            confidence=0.7,
        )
    return TemporalContext(mode="none")


def _compute_plan_confidence(plan: L2GroundingPlan) -> float:
    scores: list[float] = []
    if plan.subject_candidates:
        scores.append(max(c.score for c in plan.subject_candidates))
    if plan.predicate_candidates:
        scores.append(max(c.score for c in plan.predicate_candidates))
    if plan.temporal_context.mode != "none":
        scores.append(plan.temporal_context.confidence)
    if not scores:
        return 0.3
    return sum(scores) / len(scores)


def _map_match_source(source: str | None) -> Literal["exact", "alias", "vector", "llm", "rule"]:
    if source == "exact":
        return "exact"
    if source == "alias":
        return "alias"
    if source == "vector":
        return "vector"
    return "rule"


__all__ = [
    "GroundedConstraint",
    "GroundedEntityCandidate",
    "GroundedPredicateCandidate",
    "L2GroundingPlan",
    "build_grounding_plan",
]
