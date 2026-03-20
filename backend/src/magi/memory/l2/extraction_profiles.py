"""Extraction profiles for source-specific unified L2 constraints."""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from typing import Any

from ..event_contracts import MemoryEvent
from .ontology import ASSERTION_FAMILY_ALLOWLIST, ENTITY_TYPE_ALIASES, ENTITY_TYPE_REGISTRY, PREDICATE_REGISTRY


@dataclass(slots=True, frozen=True)
class DefaultSubjectPolicy:
    """Default subject bindings for a source profile."""

    default_subject_ref: str | None = None
    default_subject_type: str | None = None


@dataclass(slots=True, frozen=True)
class ExtractionProfile:
    """Resolved extraction limits for one event source/profile."""

    profile_id: str
    allowed_entity_types: frozenset[str] = field(default_factory=lambda: ENTITY_TYPE_REGISTRY)
    allowed_predicates: frozenset[str] = field(default_factory=lambda: PREDICATE_REGISTRY)
    allowed_assertion_families: frozenset[str] = field(default_factory=lambda: ASSERTION_FAMILY_ALLOWLIST)
    entity_type_aliases: dict[str, str] = field(default_factory=lambda: dict(ENTITY_TYPE_ALIASES))
    predicate_aliases: dict[str, str] = field(default_factory=dict)
    subject_policy: DefaultSubjectPolicy = field(default_factory=DefaultSubjectPolicy)
    allow_graph: bool = True
    allow_assertion: bool = True


DEFAULT_EXTRACTION_PROFILES: dict[str, ExtractionProfile] = {
    "chat.user_message": ExtractionProfile(
        profile_id="chat.user_message",
    ),
    "timeline.chrome_history": ExtractionProfile(
        profile_id="timeline.chrome_history",
        allowed_entity_types=frozenset({"product"}),
        allowed_predicates=frozenset({"VISITED"}),
        allowed_assertion_families=frozenset(),
        allow_assertion=False,
    ),
    "timeline.calendar": ExtractionProfile(
        profile_id="timeline.calendar",
        allowed_entity_types=frozenset({"activity", "event", "place", "organization"}),
        allowed_predicates=frozenset({"ATTENDED", "PLANS_TO", "VISITED"}),
        allowed_assertion_families=frozenset(),
        allow_assertion=False,
    ),
}


def resolve_extraction_profile(
    event: MemoryEvent,
    profile_registry: dict[str, ExtractionProfile] | None = None,
) -> ExtractionProfile:
    """Resolve the extraction profile for a normalized event."""

    registry = profile_registry or DEFAULT_EXTRACTION_PROFILES
    default_profile_id = _default_profile_id_for_event(event)
    return registry.get(default_profile_id, registry["chat.user_message"])


def _default_profile_id_for_event(event: MemoryEvent) -> str:
    source = (event.source or "").strip().lower()
    if source in {"timeline", "calendar"}:
        return "timeline.calendar"
    return "chat.user_message"


def _apply_overrides(profile: ExtractionProfile, overrides: dict[str, Any]) -> ExtractionProfile:
    return replace(
        profile,
        allowed_entity_types=_coerce_set(overrides.get("allowed_entity_types"), fallback=profile.allowed_entity_types),
        allowed_predicates=_coerce_predicate_set(overrides.get("allowed_predicates"), fallback=profile.allowed_predicates),
        allowed_assertion_families=_coerce_assertion_family_set(
            overrides.get("allowed_assertion_families"),
            fallback=profile.allowed_assertion_families,
        ),
        entity_type_aliases={
            **profile.entity_type_aliases,
            **_coerce_alias_map(overrides.get("entity_type_aliases")),
        },
        predicate_aliases={
            **profile.predicate_aliases,
            **_coerce_upper_alias_map(overrides.get("predicate_aliases")),
        },
        allow_graph=_coerce_bool(overrides.get("allow_graph"), default=profile.allow_graph),
        allow_assertion=_coerce_bool(overrides.get("allow_assertion"), default=profile.allow_assertion),
    )


def _coerce_set(value: Any, *, fallback: frozenset[str]) -> frozenset[str]:
    if not isinstance(value, (list, tuple, set, frozenset)):
        return fallback
    normalized = {str(item).strip().lower() for item in value if str(item).strip()}
    allowed = normalized & ENTITY_TYPE_REGISTRY
    return frozenset(allowed) if allowed else fallback


def _coerce_predicate_set(value: Any, *, fallback: frozenset[str]) -> frozenset[str]:
    if not isinstance(value, (list, tuple, set, frozenset)):
        return fallback
    normalized = {str(item).strip().upper() for item in value if str(item).strip()}
    allowed = normalized & PREDICATE_REGISTRY
    return frozenset(allowed) if allowed else fallback


def _coerce_assertion_family_set(value: Any, *, fallback: frozenset[str]) -> frozenset[str]:
    if not isinstance(value, (list, tuple, set, frozenset)):
        return fallback
    normalized = {str(item).strip().lower() for item in value if str(item).strip()}
    allowed = normalized & ASSERTION_FAMILY_ALLOWLIST
    return frozenset(allowed)


def _coerce_alias_map(value: Any) -> dict[str, str]:
    if not isinstance(value, dict):
        return {}
    normalized: dict[str, str] = {}
    for raw_key, raw_value in value.items():
        key = str(raw_key).strip().lower()
        mapped = str(raw_value).strip().lower()
        if key and mapped:
            normalized[key] = mapped
    return normalized


def _coerce_upper_alias_map(value: Any) -> dict[str, str]:
    if not isinstance(value, dict):
        return {}
    normalized: dict[str, str] = {}
    for raw_key, raw_value in value.items():
        key = str(raw_key).strip().upper()
        mapped = str(raw_value).strip().upper()
        if key and mapped:
            normalized[key] = mapped
    return normalized


def _coerce_bool(value: Any, *, default: bool) -> bool:
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() in {"1", "true", "yes", "on"}


def _coalesce_text(*values: Any) -> str | None:
    for value in values:
        text = str(value).strip() if value is not None else ""
        if text:
            return text
    return None


__all__ = [
    "DEFAULT_EXTRACTION_PROFILES",
    "DefaultSubjectPolicy",
    "ExtractionProfile",
    "resolve_extraction_profile",
]
