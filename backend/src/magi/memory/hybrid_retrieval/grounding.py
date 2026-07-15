"""L2 query grounding: deterministic resolution of user queries into structured retrieval plans."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, List, Literal, Optional

from ..l2.predicate_catalog import (
    expand_predicates_via_catalog,
    get_answer_kinds,
    get_family_predicates,
    get_spec,
)
from .l2_relationship_utils import infer_relation_direction
from .l2_semantic_utils import predicates_for_semantic_frame
from .models import L2Conditions, TemporalContext


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
    content_query: str = ""
    subject_candidates: List[GroundedEntityCandidate] = field(default_factory=list)
    object_candidates: List[GroundedEntityCandidate] = field(default_factory=list)
    predicate_candidates: List[GroundedPredicateCandidate] = field(default_factory=list)
    predicate_family: str | None = None
    answer_kind: str = "unknown"
    relation_direction: str = "outgoing"
    subject_scope: str = "none"
    object_constraints: List[GroundedConstraint] = field(default_factory=list)
    temporal_context: TemporalContext = field(default_factory=TemporalContext)
    context_scope: dict[str, Any] = field(default_factory=dict)
    confidence: float = 0.5
    allowed_evidence_classes: Optional[set[str]] = None
    evidence_focus_source: Optional[str] = None  # "llm" | "rule_heuristic" | "family_fallback" | None
    predicate_source: Optional[str] = None  # "explicit"|"embedding"|"llm_family"|"keyword_fallback" (RFC #65 P1)
    allow_soft_edges: bool = True  # RFC #65 P2
    hop2_target_type: Optional[str] = None  # RFC #65 P3

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
    plan.content_query = conditions.content_query

    _ground_subjects(plan, conditions, resolved_entities, user_id)
    _ground_predicates(plan, conditions)
    plan.query_kind = _infer_query_kind(plan, conditions)
    plan.answer_kind = _infer_answer_kind(plan, conditions)
    plan.relation_direction = conditions.relation_direction or infer_relation_direction(
        conditions.content_query
    )
    _ground_object_constraints(plan, conditions, resolved_entities)
    plan.temporal_context = _build_temporal_context(conditions, time_range)
    plan.context_scope = dict(conditions.context_scope or {})
    plan.confidence = _compute_plan_confidence(plan)
    plan.allowed_evidence_classes = conditions.allowed_evidence_classes
    plan.evidence_focus_source = conditions.evidence_focus_source
    plan.predicate_source = conditions.predicate_source
    plan.allow_soft_edges = conditions.allow_soft_edges
    plan.hop2_target_type = conditions.hop2_target_type

    return plan


def _ground_subjects(
    plan: L2GroundingPlan,
    conditions: L2Conditions,
    resolved_entities: list[dict[str, Any]],
    user_id: str | None,
) -> None:
    if _should_bind_self_subject(conditions, resolved_entities, user_id):
        plan.subject_scope = "self"
        plan.subject_candidates.append(GroundedEntityCandidate(
            entity_id=f"user:{user_id}",
            entity_type="person",
            surface="self",
            score=1.0,
            source="rule",
        ))
    elif _wants_multi_subject(conditions, resolved_entities):
        subjects = _pick_multi_subject_entities(conditions, resolved_entities)
        if subjects:
            plan.subject_scope = "multi"
            plan.subject_candidates.extend(_entity_candidate(subject) for subject in subjects)
    elif _is_collective_person_query(conditions, resolved_entities):
        subjects = _person_entities(resolved_entities)
        if subjects:
            plan.subject_scope = "multi"
            plan.subject_candidates.extend(_entity_candidate(subject) for subject in subjects)
    elif _wants_explicit_subject(conditions):
        subject = _pick_explicit_subject_entity(conditions, resolved_entities)
        if subject is not None:
            plan.subject_scope = "explicit"
            plan.subject_candidates.append(_entity_candidate(subject))
    elif conditions.subject_hint:
        plan.subject_scope = "explicit"
        for entity in resolved_entities:
            eid = entity.get("entity_id", "")
            if conditions.subject_hint.lower() in str(eid).lower():
                plan.subject_candidates.append(_entity_candidate(entity))

    if (
        not plan.subject_candidates
        and user_id
        and not conditions.entities
        and not resolved_entities
    ):
        plan.subject_scope = "self"
        plan.subject_candidates.append(GroundedEntityCandidate(
            entity_id=f"user:{user_id}",
            entity_type="person",
            surface="self",
            score=0.6,
            source="rule",
        ))


def _should_bind_self_subject(
    conditions: L2Conditions,
    resolved_entities: list[dict[str, Any]],
    user_id: str | None,
) -> bool:
    if not user_id:
        return False
    semantic_frame = conditions.semantic_frame
    wants_self = (
        conditions.subject_hint == "self"
        or (
            semantic_frame is not None
            and semantic_frame.subject_scope == "self"
        )
        or (
            conditions.predicate_family == "relationship"
            and _query_has_self_reference(conditions.content_query)
        )
    )
    if not wants_self:
        return False
    if not _person_entities(resolved_entities):
        return True
    return _query_has_self_reference(conditions.content_query)


def _wants_explicit_subject(conditions: L2Conditions) -> bool:
    semantic_frame = conditions.semantic_frame
    return (
        conditions.subject_hint == "explicit"
        or (
            bool(conditions.entities)
            and conditions.subject_hint in (None, "explicit")
        )
        or (
            semantic_frame is not None
            and semantic_frame.subject_scope == "explicit"
        )
    )


def _wants_multi_subject(
    conditions: L2Conditions,
    resolved_entities: list[dict[str, Any]],
) -> bool:
    if len(_person_entities(resolved_entities)) < 2:
        return False
    semantic_frame = conditions.semantic_frame
    if semantic_frame is None:
        return False
    return (
        semantic_frame.subject_scope == "multi"
        or semantic_frame.subject_mode == "multi"
        or semantic_frame.relation_shape == "shared_fact"
    )


def _is_collective_person_query(
    conditions: L2Conditions,
    resolved_entities: list[dict[str, Any]],
) -> bool:
    if len(_person_entities(resolved_entities)) < 2:
        return False
    query = str(conditions.content_query or "").lower()
    markers = (
        "both",
        "share",
        "shared",
        "in common",
        "common",
        "mutual",
        "together",
        "共同",
        "都",
        "一起",
        "共有",
        "相同",
    )
    return any(marker in query for marker in markers)


def _person_entities(resolved_entities: list[dict[str, Any]]) -> list[dict[str, Any]]:
    people: list[dict[str, Any]] = []
    for entity in resolved_entities:
        entity_type = str(entity.get("entity_type") or "").lower()
        entity_id = str(entity.get("entity_id") or "").lower()
        if entity_type in {"person", "user"} or entity_id.startswith(("person:", "user:")):
            people.append(entity)
    return people


def _query_has_self_reference(query: str) -> bool:
    lowered = str(query or "").lower()
    if re.search(r"\b(i|me|my|mine|myself|we|us|our|ours|ourselves)\b", lowered):
        return True
    return any(marker in lowered for marker in ("我", "我的", "我们", "咱", "咱们"))


def _pick_explicit_subject_entity(
    conditions: L2Conditions,
    resolved_entities: list[dict[str, Any]],
) -> dict[str, Any] | None:
    if not resolved_entities:
        return None

    semantic_frame = conditions.semantic_frame
    mentions = list(semantic_frame.subject_mentions if semantic_frame else [])
    if not mentions and semantic_frame is not None:
        mentions = list(semantic_frame.entity_mentions)
    for mention in mentions:
        for entity in resolved_entities:
            if _entity_matches_surface(entity, mention):
                return entity

    return resolved_entities[0]


def _pick_multi_subject_entities(
    conditions: L2Conditions,
    resolved_entities: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    semantic_frame = conditions.semantic_frame
    people = _person_entities(resolved_entities)
    if semantic_frame is None or not semantic_frame.subject_mentions:
        return people

    ordered: list[dict[str, Any]] = []
    seen: set[str] = set()
    for mention in semantic_frame.subject_mentions:
        for entity in people:
            entity_id = str(entity.get("entity_id") or "")
            if entity_id in seen:
                continue
            if _entity_matches_surface(entity, mention):
                ordered.append(entity)
                seen.add(entity_id)
                break
    return ordered or people


def _entity_matches_surface(entity: dict[str, Any], surface: str) -> bool:
    wanted = _normalize_surface(surface)
    if not wanted:
        return False

    entity_id = str(entity.get("entity_id") or "")
    _, _, entity_slug = entity_id.partition(":")
    candidates = [
        entity_id,
        entity_slug,
        str(entity.get("canonical_name") or ""),
        str(entity.get("name") or ""),
        str(entity.get("surface") or ""),
    ]
    normalized_candidates = [_normalize_surface(candidate) for candidate in candidates]
    return any(
        candidate
        and (candidate == wanted or candidate in wanted or wanted in candidate)
        for candidate in normalized_candidates
    )


def _normalize_surface(value: str) -> str:
    return "".join(ch for ch in str(value).lower() if ch.isalnum())


def _entity_candidate(entity: dict[str, Any]) -> GroundedEntityCandidate:
    entity_id = str(entity.get("entity_id") or "")
    return GroundedEntityCandidate(
        entity_id=entity_id,
        entity_type=str(entity.get("entity_type") or "other"),
        surface=str(entity.get("canonical_name") or entity.get("name") or entity_id),
        score=float(entity.get("confidence", 0.8)),
        source=_map_match_source(entity.get("match_source")),
    )


def _ground_predicates(
    plan: L2GroundingPlan,
    conditions: L2Conditions,
) -> None:
    if conditions.predicates:
        _append_predicate_candidates(plan, conditions.predicates, source="alias", score=1.0)
        if plan.predicate_candidates:
            plan.predicate_family = plan.predicate_candidates[0].family

    if conditions.semantic_frame is not None and not plan.predicate_candidates:
        frame_preds = predicates_for_semantic_frame(conditions.semantic_frame)
        if frame_preds:
            _append_predicate_candidates(plan, frame_preds, source="rule", score=0.9)
            plan.predicate_family = conditions.predicate_family or plan.predicate_candidates[0].family

    if conditions.predicate_family and not plan.predicate_candidates:
        plan.predicate_family = conditions.predicate_family
        family_preds = get_family_predicates(conditions.predicate_family)
        _append_predicate_candidates(plan, family_preds, source="family", score=0.8)


def _append_predicate_candidates(
    plan: L2GroundingPlan,
    predicates: list[str],
    *,
    source: Literal["alias", "family", "vector", "llm", "rule"],
    score: float,
) -> None:
    for pred in predicates:
        spec = get_spec(pred)
        plan.predicate_candidates.append(GroundedPredicateCandidate(
            predicate=spec.canonical if spec else pred.upper(),
            family=spec.family if spec else None,
            score=score if spec else 0.5,
            source=source if spec else "rule",
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

    explicit_objects = _pick_object_mention_entities(conditions, resolved_entities)
    if explicit_objects:
        for entity in explicit_objects:
            if entity.get("entity_id") not in plan.subject_entity_ids:
                plan.object_candidates.append(_entity_candidate(entity))
        return

    for entity in resolved_entities:
        if entity.get("entity_id") not in plan.subject_entity_ids:
            plan.object_candidates.append(GroundedEntityCandidate(
                entity_id=entity["entity_id"],
                entity_type=entity.get("entity_type", "other"),
                surface=entity.get("canonical_name", entity["entity_id"]),
                score=entity.get("confidence", 0.7),
                source=_map_match_source(entity.get("match_source")),
            ))


def _pick_object_mention_entities(
    conditions: L2Conditions,
    resolved_entities: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    semantic_frame = conditions.semantic_frame
    if semantic_frame is None or not semantic_frame.object_mentions:
        return []

    ordered: list[dict[str, Any]] = []
    seen: set[str] = set()
    for mention in semantic_frame.object_mentions:
        for entity in resolved_entities:
            entity_id = str(entity.get("entity_id") or "")
            if entity_id in seen:
                continue
            if _entity_matches_surface(entity, mention):
                ordered.append(entity)
                seen.add(entity_id)
                break
    return ordered


def _build_temporal_context(
    conditions: L2Conditions,
    time_range: Any | None,
) -> TemporalContext:
    if time_range is None:
        return TemporalContext(mode="none")

    start = getattr(time_range, "start", None)
    end = getattr(time_range, "end", None)
    as_of = getattr(time_range, "as_of", None)

    if as_of is not None:
        return TemporalContext(
            mode="as_of",
            anchor=as_of,
            confidence=1.0,
        )

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
