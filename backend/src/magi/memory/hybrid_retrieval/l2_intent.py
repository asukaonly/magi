"""L2 intent enrichment and semantic frame parsing."""

from __future__ import annotations

from .models import L2Conditions, L2SemanticFrame, SemanticConstraint

_VALID_SUBJECT_HINTS = {"self", "explicit", "none"}
_VALID_PREDICATE_FAMILIES = {"preference", "relationship", "profile_fact", "activity", "unknown"}
_VALID_QUERY_FAMILIES = {"affinity", "relationship", "profile", "activity", "lookup"}
_VALID_ANSWER_KINDS = {"creator", "place", "topic", "person", "software", "unknown"}
_VALID_ANSWER_UNITS = {"identity", "presence", "place", "topic", "mixed"}
_VALID_CONSTRAINT_SCOPES = {"target", "interaction"}
_VALID_CONSTRAINT_FACETS = {"platform", "located_in", "category"}


def enrich_l2_conditions(
    conditions: L2Conditions,
    query: str,
) -> None:
    """Fill missing L2 structural fields using rule-based inference."""
    if not conditions.entities:
        conditions.entities = None

    if not conditions.subject_hint or conditions.subject_hint == "none":
        family = conditions.predicate_family or "unknown"
        if family == "unknown":
            family = _infer_predicate_family(query)
            conditions.predicate_family = family
        if family in {"preference", "profile_fact"}:
            conditions.subject_hint = "self"
        else:
            conditions.subject_hint = "none"

    if not conditions.predicate_family or conditions.predicate_family == "unknown":
        conditions.predicate_family = _infer_predicate_family(query)

    if conditions.semantic_frame is None:
        conditions.semantic_frame = _infer_semantic_frame(
            query=query,
            subject_hint=conditions.subject_hint or "none",
            predicate_family=conditions.predicate_family or "unknown",
        )


def _infer_predicate_family(
    query: str,
) -> str:
    """Infer the broad predicate family for L2 graph planning."""
    lowered = query.lower()
    preference_keywords = (
        "喜欢", "讨厌", "偏好", "偏爱", "感兴趣", "关注",
        "like", "dislike", "prefer", "favorite", "interested",
        "follow", "hate",
    )
    if any(keyword in lowered for keyword in preference_keywords):
        return "preference"
    relationship_keywords = (
        "关系", "约定", "认识",
        "relationship", "agreement", "know",
    )
    if any(keyword in lowered for keyword in relationship_keywords):
        return "relationship"
    profile_keywords = (
        "默认", "设置", "工作目录", "常用",
        "default", "setting", "workspace", "configuration",
    )
    if any(keyword in lowered for keyword in profile_keywords):
        return "profile_fact"
    return "unknown"


def _infer_semantic_frame(
    *,
    query: str,
    subject_hint: str,
    predicate_family: str,
) -> L2SemanticFrame | None:
    """Infer a minimal semantic frame for L2 graph search."""
    query_family = _infer_query_family(predicate_family)
    if query_family == "lookup":
        return None

    return L2SemanticFrame(
        query_family=query_family,
        subject_scope=subject_hint if subject_hint in _VALID_SUBJECT_HINTS else "none",
        answer_kind="unknown",
        answer_unit="mixed",
        entity_mentions=[],
        constraints=[],
        ranking_mode="affinity" if query_family == "affinity" else "confidence",
    )


def _infer_query_family(predicate_family: str) -> str:
    if predicate_family == "preference":
        return "affinity"
    if predicate_family == "relationship":
        return "relationship"
    if predicate_family == "profile_fact":
        return "profile"
    if predicate_family == "activity":
        return "activity"
    return "lookup"


def _parse_semantic_frame(raw: dict | None) -> L2SemanticFrame | None:
    """Parse an LLM-returned semantic_frame dict into a typed dataclass."""
    if not raw or not isinstance(raw, dict):
        return None
    try:
        constraints: list[SemanticConstraint] = []
        for item in raw.get("constraints") or []:
            if not isinstance(item, dict):
                continue
            scope = item.get("scope", "")
            facet = item.get("facet", "")
            if scope not in _VALID_CONSTRAINT_SCOPES or facet not in _VALID_CONSTRAINT_FACETS:
                continue
            constraints.append(SemanticConstraint(
                scope=scope,
                facet=facet,
                raw_value=item.get("raw_value", ""),
                resolved_entity_id=item.get("resolved_entity_id"),
                resolved_facet_value=item.get("resolved_facet_value"),
            ))
        return L2SemanticFrame(
            query_family=raw.get("query_family", "lookup"),
            subject_scope=raw.get("subject_scope", "none"),
            answer_kind=raw.get("answer_kind", "unknown"),
            answer_unit=raw.get("answer_unit", "mixed"),
            entity_mentions=raw.get("entity_mentions") or [],
            constraints=constraints,
            ranking_mode=raw.get("ranking_mode", "confidence"),
        )
    except (TypeError, KeyError):
        return None