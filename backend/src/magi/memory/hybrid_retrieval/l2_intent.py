"""L2 intent enrichment and semantic frame parsing."""

from __future__ import annotations

from .models import L2Conditions, L2SemanticFrame, SemanticConstraint

_VALID_SUBJECT_HINTS = {"self", "explicit", "none"}
_VALID_PREDICATE_FAMILIES = {"preference", "relationship", "profile_fact", "activity", "unknown"}
_VALID_QUERY_FAMILIES = {"affinity", "relationship", "profile", "activity", "lookup"}
_VALID_SUBJECT_SCOPES = {"self", "explicit", "multi", "none"}
_VALID_SUBJECT_MODES = {"self", "single", "multi", "none"}
_VALID_RELATION_SHAPES = {
    "single_fact",
    "shared_fact",
    "between_people",
    "comparison",
    "two_hop",
    "unknown",
}
_VALID_ANSWER_KINDS = {"creator", "place", "topic", "person", "software", "media", "unknown"}
_VALID_ANSWER_UNITS = {"identity", "presence", "place", "topic", "mixed"}
_VALID_CONSTRAINT_SCOPES = {"target", "interaction"}
_VALID_CONSTRAINT_FACETS = {"platform", "located_in", "category"}

_QUERY_FAMILY_TO_PREDICATE_FAMILY = {
    "affinity": "preference",
    "relationship": "relationship",
    "profile": "profile_fact",
    "activity": "activity",
    "lookup": "unknown",
}


def enrich_l2_conditions(
    conditions: L2Conditions,
    query: str,
) -> None:
    """Fill missing L2 structural fields using rule-based inference."""
    if not conditions.entities:
        conditions.entities = None

    _apply_semantic_frame_defaults(conditions)

    if conditions.semantic_frame is None and (
        not conditions.subject_hint or conditions.subject_hint == "none"
    ):
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

    _apply_semantic_frame_defaults(conditions)


def _apply_semantic_frame_defaults(conditions: L2Conditions) -> None:
    frame = conditions.semantic_frame
    if frame is None:
        return
    if not conditions.entities:
        conditions.entities = mentions_from_semantic_frame(frame) or None
    if not conditions.subject_hint or conditions.subject_hint == "none":
        conditions.subject_hint = subject_hint_from_semantic_frame(frame)
    if not conditions.predicate_family or conditions.predicate_family == "unknown":
        conditions.predicate_family = predicate_family_from_query_family(
            frame.query_family
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
        subject_mode=_subject_mode_from_hint(subject_hint),
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


def _validated(raw: object, valid_values: set[str], default: str) -> str:
    if isinstance(raw, str) and raw in valid_values:
        return raw
    return default


def _string_list(raw: object) -> list[str]:
    if not isinstance(raw, list):
        return []
    values: list[str] = []
    for item in raw:
        if not isinstance(item, (str, int, float)):
            continue
        value = str(item).strip()
        if value:
            values.append(value)
    return values


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
        subject_scope = _validated(raw.get("subject_scope"), _VALID_SUBJECT_SCOPES, "none")
        subject_mode = _validated(raw.get("subject_mode"), _VALID_SUBJECT_MODES, "none")
        if subject_scope == "multi" and subject_mode == "none":
            subject_mode = "multi"
        elif subject_scope == "self" and subject_mode == "none":
            subject_mode = "self"
        elif subject_scope == "explicit" and subject_mode == "none":
            subject_mode = "single"
        return L2SemanticFrame(
            query_family=_validated(raw.get("query_family"), _VALID_QUERY_FAMILIES, "lookup"),
            subject_scope=subject_scope,
            answer_kind=_validated(raw.get("answer_kind"), _VALID_ANSWER_KINDS, "unknown"),
            answer_unit=_validated(raw.get("answer_unit"), _VALID_ANSWER_UNITS, "mixed"),
            subject_mode=subject_mode,
            relation_shape=_validated(raw.get("relation_shape"), _VALID_RELATION_SHAPES, "unknown"),
            subject_mentions=_string_list(raw.get("subject_mentions")),
            object_mentions=_string_list(raw.get("object_mentions")),
            entity_mentions=_string_list(raw.get("entity_mentions")),
            constraints=constraints,
            ranking_mode=_validated(raw.get("ranking_mode"), {"affinity", "confidence", "recency"}, "confidence"),
        )
    except (TypeError, KeyError):
        return None


def _subject_mode_from_hint(subject_hint: str) -> str:
    if subject_hint == "self":
        return "self"
    if subject_hint == "explicit":
        return "single"
    return "none"


def predicate_family_from_query_family(query_family: str) -> str:
    return _QUERY_FAMILY_TO_PREDICATE_FAMILY.get(query_family, "unknown")


def subject_hint_from_semantic_frame(frame: L2SemanticFrame) -> str:
    if frame.subject_mode == "self" or frame.subject_scope == "self":
        return "self"
    if frame.subject_mode in {"single", "multi"} or frame.subject_scope in {"explicit", "multi"}:
        return "explicit"
    return "none"


def mentions_from_semantic_frame(frame: L2SemanticFrame) -> list[str]:
    seen: set[str] = set()
    mentions: list[str] = []
    for value in [*frame.subject_mentions, *frame.object_mentions, *frame.entity_mentions]:
        normalized = str(value).strip()
        if not normalized or normalized in seen:
            continue
        seen.add(normalized)
        mentions.append(normalized)
    return mentions
