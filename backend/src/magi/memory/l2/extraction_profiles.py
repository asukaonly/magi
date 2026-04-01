"""Extraction profiles for source-specific unified L2 constraints."""

from __future__ import annotations

import logging
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Any

import yaml

from ..event_contracts import MemoryEvent
from .ontology import ASSERTION_FAMILY_ALLOWLIST, ENTITY_TYPE_ALIASES, ENTITY_TYPE_REGISTRY, PREDICATE_REGISTRY

logger = logging.getLogger(__name__)


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
    structured_allowed_entity_types: frozenset[str] | None = None
    structured_allowed_predicates: frozenset[str] | None = None
    allowed_assertion_families: frozenset[str] = field(default_factory=lambda: ASSERTION_FAMILY_ALLOWLIST)
    entity_type_aliases: dict[str, str] = field(default_factory=lambda: dict(ENTITY_TYPE_ALIASES))
    predicate_aliases: dict[str, str] = field(default_factory=dict)
    subject_policy: DefaultSubjectPolicy = field(default_factory=DefaultSubjectPolicy)
    allow_graph: bool = True
    allow_assertion: bool = True
    extraction_instructions: str | None = None

    @property
    def effective_structured_allowed_entity_types(self) -> frozenset[str]:
        return self.structured_allowed_entity_types or self.allowed_entity_types

    @property
    def effective_structured_allowed_predicates(self) -> frozenset[str]:
        return self.structured_allowed_predicates or self.allowed_predicates


DEFAULT_EXTRACTION_PROFILES: dict[str, ExtractionProfile] = {
    "chat.user_message": ExtractionProfile(
        profile_id="chat.user_message",
    ),
}

_BUILTIN_YAML_PATH = Path(__file__).resolve().parents[4] / "configs" / "l2_extraction_profiles.yaml"

_loaded_profiles: dict[str, ExtractionProfile] | None = None


def _parse_profile_from_dict(profile_id: str, raw: dict[str, Any]) -> ExtractionProfile:
    """Build an ``ExtractionProfile`` from a raw YAML dict."""

    def _parse_entity_types(val: Any) -> frozenset[str]:
        if val == "all" or val is None:
            return ENTITY_TYPE_REGISTRY
        if isinstance(val, (list, tuple)):
            return frozenset(str(v).strip().lower() for v in val if str(v).strip())
        return ENTITY_TYPE_REGISTRY

    def _parse_predicates(val: Any) -> frozenset[str]:
        if val == "all" or val is None:
            return PREDICATE_REGISTRY
        if isinstance(val, (list, tuple)):
            return frozenset(str(v).strip().upper() for v in val if str(v).strip())
        return PREDICATE_REGISTRY

    def _parse_assertion_families(val: Any) -> frozenset[str]:
        if val == "all" or val is None:
            return ASSERTION_FAMILY_ALLOWLIST
        if isinstance(val, (list, tuple)):
            return frozenset(str(v).strip().lower() for v in val if str(v).strip())
        return frozenset()

    def _parse_optional_set(val: Any, parser: Any) -> frozenset[str] | None:
        if val is None:
            return None
        return parser(val)

    return ExtractionProfile(
        profile_id=profile_id,
        allowed_entity_types=_parse_entity_types(raw.get("allowed_entity_types")),
        allowed_predicates=_parse_predicates(raw.get("allowed_predicates")),
        structured_allowed_entity_types=_parse_optional_set(
            raw.get("structured_allowed_entity_types"), _parse_entity_types,
        ),
        structured_allowed_predicates=_parse_optional_set(
            raw.get("structured_allowed_predicates"), _parse_predicates,
        ),
        allowed_assertion_families=_parse_assertion_families(raw.get("allowed_assertion_families")),
        allow_graph=bool(raw.get("allow_graph", True)),
        allow_assertion=bool(raw.get("allow_assertion", True)),
        extraction_instructions=raw.get("extraction_instructions"),
    )


def _load_profiles_from_yaml(path: Path) -> dict[str, ExtractionProfile]:
    """Load extraction profiles from a YAML file.

    Returns the hardcoded fallback if the file is missing or unparseable.
    """
    if not path.exists():
        return dict(DEFAULT_EXTRACTION_PROFILES)
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = yaml.safe_load(f) or {}
    except Exception:
        logger.warning("failed to load extraction profiles from %s, using defaults", path)
        return dict(DEFAULT_EXTRACTION_PROFILES)

    raw_profiles: dict[str, Any] = data.get("profiles", {})
    if not isinstance(raw_profiles, dict) or not raw_profiles:
        return dict(DEFAULT_EXTRACTION_PROFILES)

    profiles: dict[str, ExtractionProfile] = {}
    for profile_id, raw in raw_profiles.items():
        if not isinstance(raw, dict):
            continue
        profiles[str(profile_id)] = _parse_profile_from_dict(str(profile_id), raw)

    if "chat.user_message" not in profiles:
        profiles["chat.user_message"] = DEFAULT_EXTRACTION_PROFILES["chat.user_message"]

    return profiles


def get_extraction_profiles() -> dict[str, ExtractionProfile]:
    """Return cached extraction profiles, loading from YAML on first call."""
    global _loaded_profiles
    if _loaded_profiles is None:
        _loaded_profiles = _load_profiles_from_yaml(_BUILTIN_YAML_PATH)
    return _loaded_profiles


def reload_extraction_profiles() -> dict[str, ExtractionProfile]:
    """Force reload extraction profiles from YAML."""
    global _loaded_profiles
    _loaded_profiles = _load_profiles_from_yaml(_BUILTIN_YAML_PATH)
    return _loaded_profiles


def resolve_extraction_profile(
    event: MemoryEvent,
    profile_registry: dict[str, ExtractionProfile] | None = None,
) -> ExtractionProfile:
    """Resolve the extraction profile for a normalized event."""

    registry = profile_registry or get_extraction_profiles()
    default_profile_id = _default_profile_id_for_event(event)
    return registry.get(default_profile_id, registry["chat.user_message"])


def _default_profile_id_for_event(event: MemoryEvent) -> str:
    source = (event.source or "").strip().lower()
    if source == "chrome_history":
        return "timeline.chrome_history"
    if source in {"timeline", "calendar"}:
        return "timeline.calendar"
    _sensor_profile_map = {
        "netease_music": "timeline.netease_music",
        "git_activity": "timeline.git_activity",
        "terminal_history": "timeline.terminal_history",
        "screen_time": "timeline.screen_time",
    }
    if source in _sensor_profile_map:
        return _sensor_profile_map[source]
    return "chat.user_message"


def _apply_overrides(profile: ExtractionProfile, overrides: dict[str, Any]) -> ExtractionProfile:
    extraction_instructions = profile.extraction_instructions
    override_instructions = overrides.get("extraction_instructions")
    if isinstance(override_instructions, str) and override_instructions.strip():
        extraction_instructions = override_instructions.strip()
    return replace(
        profile,
        allowed_entity_types=_coerce_set(overrides.get("allowed_entity_types"), fallback=profile.allowed_entity_types),
        allowed_predicates=_coerce_predicate_set(overrides.get("allowed_predicates"), fallback=profile.allowed_predicates),
        structured_allowed_entity_types=_coerce_optional_set(
            overrides.get("structured_allowed_entity_types"),
            fallback=profile.structured_allowed_entity_types,
        ),
        structured_allowed_predicates=_coerce_optional_predicate_set(
            overrides.get("structured_allowed_predicates"),
            fallback=profile.structured_allowed_predicates,
        ),
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
        extraction_instructions=extraction_instructions,
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


def _coerce_optional_set(value: Any, *, fallback: frozenset[str] | None) -> frozenset[str] | None:
    if value is None:
        return fallback
    if not isinstance(value, (list, tuple, set, frozenset)):
        return fallback
    normalized = {str(item).strip().lower() for item in value if str(item).strip()}
    allowed = normalized & ENTITY_TYPE_REGISTRY
    return frozenset(allowed) if allowed else frozenset()


def _coerce_optional_predicate_set(value: Any, *, fallback: frozenset[str] | None) -> frozenset[str] | None:
    if value is None:
        return fallback
    if not isinstance(value, (list, tuple, set, frozenset)):
        return fallback
    normalized = {str(item).strip().upper() for item in value if str(item).strip()}
    allowed = normalized & PREDICATE_REGISTRY
    return frozenset(allowed) if allowed else frozenset()


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
    "get_extraction_profiles",
    "reload_extraction_profiles",
    "resolve_extraction_profile",
]
