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


def enrich_l2_conditions(conditions: L2Conditions) -> None:
    """Derive structural defaults only from an explicit semantic frame."""
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
