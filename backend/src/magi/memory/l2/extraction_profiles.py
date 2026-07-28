"""Extraction profiles for source-specific unified L2 constraints."""

from __future__ import annotations

import logging
from collections.abc import Iterable
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Any

import yaml

from ...events.first_context import FIRST_CONTEXT_STORY_INTERACTION_KIND
from ..event_contracts import MemoryEvent
from .ontology import (
    ASSERTION_FAMILY_ALLOWLIST,
    ENTITY_TYPE_ALIASES,
    ENTITY_TYPE_REGISTRY,
    PREDICATE_REGISTRY,
)
from ...utils.packaged_paths import get_backend_root

logger = logging.getLogger(__name__)

ASSERTION_MODES: frozenset[str] = frozenset({"none", "derived", "phase2_candidate"})


@dataclass(slots=True, frozen=True)
class DefaultSubjectPolicy:
    """Default subject bindings for a source profile."""

    default_subject_ref: str | None = None
    default_subject_type: str | None = None


@dataclass(slots=True, frozen=True)
class ExtractionProfile:
    """Resolved extraction limits for one event source/profile."""

    profile_id: str
    source_types: frozenset[str] = field(default_factory=frozenset)
    allowed_entity_types: frozenset[str] = field(default_factory=lambda: ENTITY_TYPE_REGISTRY)
    allowed_predicates: frozenset[str] = field(default_factory=lambda: PREDICATE_REGISTRY)
    structured_allowed_entity_types: frozenset[str] | None = None
    structured_allowed_predicates: frozenset[str] | None = None
    allowed_assertion_families: frozenset[str] = field(
        default_factory=lambda: ASSERTION_FAMILY_ALLOWLIST
    )
    entity_type_aliases: dict[str, str] = field(default_factory=lambda: dict(ENTITY_TYPE_ALIASES))
    predicate_aliases: dict[str, str] = field(default_factory=dict)
    subject_policy: DefaultSubjectPolicy = field(default_factory=DefaultSubjectPolicy)
    allow_graph: bool = True
    allow_assertion: bool = True
    extraction_instructions: str | None = None
    phase1_instructions: str | None = None
    phase2_instructions: str | None = None
    assertion_mode: str = "phase2_candidate"
    allowed_assertion_traits: frozenset[str] | None = None
    derived_assertion_specs: tuple[dict[str, Any], ...] = field(default_factory=tuple)

    @property
    def effective_structured_allowed_entity_types(self) -> frozenset[str]:
        return self.structured_allowed_entity_types or self.allowed_entity_types

    @property
    def effective_structured_allowed_predicates(self) -> frozenset[str]:
        return self.structured_allowed_predicates or self.allowed_predicates


DEFAULT_EXTRACTION_PROFILES: dict[str, ExtractionProfile] = {
    "chat.user_message": ExtractionProfile(
        profile_id="chat.user_message",
        source_types=frozenset({"chat"}),
    ),
    "chat.first_context_story": ExtractionProfile(
        profile_id="chat.first_context_story",
        source_types=frozenset({"chat"}),
        extraction_instructions=(
            "This message was submitted while an optional onboarding question was shown; "
            "it may or may not answer that question. Use the question only when the message "
            "meaningfully answers it or needs it to interpret elliptical wording; the question "
            "is not evidence. If the message is unrelated, ignore the question and analyze the "
            "user's actual message under the normal explicit-evidence rules. "
            "Extract only explicit self-reports, durable preferences, stable profile facts, "
            "or clearly stated current/recent situations. Ignore any request or question "
            "clause in a mixed message. Return no facts, entities, relationships, or profile "
            "signals for gibberish, placeholders, numeric-only input, or content with no "
            "meaningful self-report. Do not infer stable traits from one-off behavior."
        ),
    ),
}

_BUILTIN_YAML_PATH = get_backend_root() / "configs" / "l2_extraction_profiles.yaml"

_loaded_profiles: dict[str, ExtractionProfile] | None = None


def _parse_profile_from_dict(profile_id: str, raw: dict[str, Any]) -> ExtractionProfile:
    """Build an ``ExtractionProfile`` from a raw YAML dict."""

    allow_assertion = bool(raw.get("allow_assertion", True))
    phase1_instructions = _coalesce_text(
        raw.get("phase1_instructions"),
        raw.get("extraction_instructions"),
    )

    return ExtractionProfile(
        profile_id=profile_id,
        source_types=_parse_source_types(raw.get("source_types"), profile_id=profile_id),
        allowed_entity_types=_parse_profile_entity_types(raw.get("allowed_entity_types")),
        allowed_predicates=_parse_profile_predicates(raw.get("allowed_predicates")),
        structured_allowed_entity_types=_parse_optional_set(
            raw.get("structured_allowed_entity_types"),
            _parse_profile_entity_types,
        ),
        structured_allowed_predicates=_parse_optional_set(
            raw.get("structured_allowed_predicates"),
            _parse_profile_predicates,
        ),
        allowed_assertion_families=_parse_profile_assertion_families(
            raw.get("allowed_assertion_families")
        ),
        allow_graph=bool(raw.get("allow_graph", True)),
        allow_assertion=allow_assertion,
        extraction_instructions=phase1_instructions,
        phase1_instructions=phase1_instructions,
        phase2_instructions=_coalesce_text(raw.get("phase2_instructions")),
        assertion_mode=_parse_assertion_mode(
            raw.get("assertion_mode"),
            allow_assertion=allow_assertion,
        ),
        allowed_assertion_traits=_parse_profile_assertion_traits(
            raw.get("allowed_assertion_traits")
        ),
        derived_assertion_specs=_parse_profile_derived_assertion_specs(
            raw.get("derived_assertion_specs")
        ),
    )


def _parse_profile_entity_types(val: Any) -> frozenset[str]:
    if val == "all" or val is None:
        return ENTITY_TYPE_REGISTRY
    if isinstance(val, (list, tuple)):
        return frozenset(str(v).strip().lower() for v in val if str(v).strip())
    return ENTITY_TYPE_REGISTRY


def _parse_profile_predicates(val: Any) -> frozenset[str]:
    if val == "all" or val is None:
        return PREDICATE_REGISTRY
    if isinstance(val, (list, tuple)):
        return frozenset(str(v).strip().upper() for v in val if str(v).strip())
    return PREDICATE_REGISTRY


def _parse_profile_assertion_families(val: Any) -> frozenset[str]:
    if val == "all" or val is None:
        return ASSERTION_FAMILY_ALLOWLIST
    if isinstance(val, (list, tuple)):
        return frozenset(str(v).strip().lower() for v in val if str(v).strip())
    return frozenset()


def _parse_optional_set(val: Any, parser: Any) -> frozenset[str] | None:
    if val is None:
        return None
    return parser(val)


def _parse_assertion_mode(val: Any, *, allow_assertion: bool) -> str:
    if val is None:
        return "phase2_candidate" if allow_assertion else "none"
    mode = str(val).strip().lower()
    return mode if mode in ASSERTION_MODES else ""


def _parse_profile_assertion_traits(val: Any) -> frozenset[str] | None:
    if val == "all" or val is None:
        return None
    if isinstance(val, (list, tuple, set, frozenset)):
        normalized = {str(v).strip() for v in val if str(v).strip()}
        return frozenset(normalized)
    return frozenset()


def _parse_profile_derived_assertion_specs(val: Any) -> tuple[dict[str, Any], ...]:
    if not isinstance(val, list):
        return tuple()
    return tuple(dict(item) for item in val if isinstance(item, dict))


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
    if "chat.first_context_story" not in profiles:
        profiles["chat.first_context_story"] = DEFAULT_EXTRACTION_PROFILES[
            "chat.first_context_story"
        ]

    return profiles


def _parse_source_types(value: Any, *, profile_id: str) -> frozenset[str]:
    if isinstance(value, (list, tuple, set, frozenset)):
        normalized = {str(item).strip().lower() for item in value if str(item).strip()}
        if normalized:
            return frozenset(normalized)
    if profile_id.startswith("source."):
        source_type = profile_id.removeprefix("source.").strip().lower()
        return frozenset({source_type}) if source_type else frozenset()
    if profile_id == "chat.user_message":
        return frozenset({"chat"})
    return frozenset()


def _coerce_profile_spec_data(raw_spec: Any) -> dict[str, Any]:
    if isinstance(raw_spec, dict):
        return dict(raw_spec)
    model_dump = getattr(raw_spec, "model_dump", None)
    if callable(model_dump):
        return dict(model_dump(mode="python"))
    raise TypeError(f"unsupported extraction profile spec type: {type(raw_spec).__name__}")


def _validate_profile(profile: ExtractionProfile) -> None:
    if not profile.profile_id.startswith("source."):
        raise ValueError(f"plugin profile {profile.profile_id} must use the source.* namespace")
    if not profile.source_types:
        raise ValueError(f"profile {profile.profile_id} must declare at least one source_type")
    unknown_entity_types = profile.allowed_entity_types - ENTITY_TYPE_REGISTRY
    if unknown_entity_types:
        raise ValueError(
            f"profile {profile.profile_id} declares unknown entity types: {sorted(unknown_entity_types)}"
        )
    unknown_predicates = profile.allowed_predicates - PREDICATE_REGISTRY
    if unknown_predicates:
        raise ValueError(
            f"profile {profile.profile_id} declares unknown predicates: {sorted(unknown_predicates)}"
        )
    structured_entity_types = profile.structured_allowed_entity_types
    if structured_entity_types is not None:
        unknown_structured_entity_types = structured_entity_types - ENTITY_TYPE_REGISTRY
        if unknown_structured_entity_types:
            raise ValueError(
                f"profile {profile.profile_id} declares unknown structured entity types: "
                f"{sorted(unknown_structured_entity_types)}"
            )
    structured_predicates = profile.structured_allowed_predicates
    if structured_predicates is not None:
        unknown_structured_predicates = structured_predicates - PREDICATE_REGISTRY
        if unknown_structured_predicates:
            raise ValueError(
                f"profile {profile.profile_id} declares unknown structured predicates: "
                f"{sorted(unknown_structured_predicates)}"
            )
    unknown_assertion_families = profile.allowed_assertion_families - ASSERTION_FAMILY_ALLOWLIST
    if unknown_assertion_families:
        raise ValueError(
            f"profile {profile.profile_id} declares unknown assertion families: "
            f"{sorted(unknown_assertion_families)}"
        )
    if profile.assertion_mode not in ASSERTION_MODES:
        raise ValueError(
            f"profile {profile.profile_id} declares unknown assertion_mode: {profile.assertion_mode}"
        )


def build_extraction_profile_registry(
    plugin_profile_specs: Iterable[Any] | None = None,
    *,
    base_profiles: dict[str, ExtractionProfile] | None = None,
) -> dict[str, ExtractionProfile]:
    """Merge host-owned profiles with plugin-contributed source profiles."""

    profiles = dict(base_profiles or get_extraction_profiles())
    for raw_spec in plugin_profile_specs or []:
        try:
            spec_data = _coerce_profile_spec_data(raw_spec)
            profile_id = str(spec_data.get("profile_id") or "").strip()
            if not profile_id:
                raise ValueError("profile_id is required")
            profile = _parse_profile_from_dict(profile_id, spec_data)
            _validate_profile(profile)
        except Exception as exc:
            logger.warning("skipping invalid plugin extraction profile: %s", exc)
            continue
        profiles[profile.profile_id] = profile
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
    plugin_profile_specs: Iterable[Any] | None = None,
) -> ExtractionProfile:
    """Resolve the extraction profile for a normalized event."""

    registry = profile_registry or build_extraction_profile_registry(plugin_profile_specs)
    default_profile_id = _default_profile_id_for_event(event, registry)
    return registry.get(default_profile_id, registry["chat.user_message"])


def _default_profile_id_for_event(
    event: MemoryEvent,
    profile_registry: dict[str, ExtractionProfile] | None = None,
) -> str:
    registry = profile_registry or get_extraction_profiles()
    metadata = event.metadata_json if isinstance(event.metadata_json, dict) else {}
    if (
        str(metadata.get("interaction_kind") or "").strip().lower()
        == FIRST_CONTEXT_STORY_INTERACTION_KIND
        and "chat.first_context_story" in registry
    ):
        return "chat.first_context_story"
    source = (event.source or "").strip().lower()
    for profile_id, profile in registry.items():
        if source and source in profile.source_types:
            return profile_id
    return "chat.user_message"


def _apply_overrides(profile: ExtractionProfile, overrides: dict[str, Any]) -> ExtractionProfile:
    extraction_instructions = profile.extraction_instructions
    phase1_instructions = profile.phase1_instructions
    override_instructions = overrides.get("phase1_instructions") or overrides.get(
        "extraction_instructions"
    )
    if isinstance(override_instructions, str) and override_instructions.strip():
        phase1_instructions = override_instructions.strip()
        extraction_instructions = phase1_instructions
    phase2_instructions = profile.phase2_instructions
    override_phase2_instructions = overrides.get("phase2_instructions")
    if isinstance(override_phase2_instructions, str) and override_phase2_instructions.strip():
        phase2_instructions = override_phase2_instructions.strip()
    allow_assertion = _coerce_bool(
        overrides.get("allow_assertion"), default=profile.allow_assertion
    )
    return replace(
        profile,
        source_types=_coerce_source_type_set(
            overrides.get("source_types"), fallback=profile.source_types
        ),
        allowed_entity_types=_coerce_set(
            overrides.get("allowed_entity_types"), fallback=profile.allowed_entity_types
        ),
        allowed_predicates=_coerce_predicate_set(
            overrides.get("allowed_predicates"), fallback=profile.allowed_predicates
        ),
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
        allow_assertion=allow_assertion,
        extraction_instructions=extraction_instructions,
        phase1_instructions=phase1_instructions,
        phase2_instructions=phase2_instructions,
        assertion_mode=_coerce_assertion_mode(
            overrides.get("assertion_mode"),
            fallback=profile.assertion_mode,
            allow_assertion=allow_assertion,
        ),
        allowed_assertion_traits=_coerce_assertion_traits(
            overrides.get("allowed_assertion_traits"),
            fallback=profile.allowed_assertion_traits,
        ),
        derived_assertion_specs=_coerce_derived_assertion_specs(
            overrides.get("derived_assertion_specs"),
            fallback=profile.derived_assertion_specs,
        ),
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


def _coerce_optional_predicate_set(
    value: Any, *, fallback: frozenset[str] | None
) -> frozenset[str] | None:
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


def _coerce_source_type_set(value: Any, *, fallback: frozenset[str]) -> frozenset[str]:
    if not isinstance(value, (list, tuple, set, frozenset)):
        return fallback
    normalized = {str(item).strip().lower() for item in value if str(item).strip()}
    return frozenset(normalized) if normalized else fallback


def _coerce_assertion_mode(value: Any, *, fallback: str, allow_assertion: bool) -> str:
    if value is None:
        return fallback or ("phase2_candidate" if allow_assertion else "none")
    mode = str(value).strip().lower()
    return mode if mode in ASSERTION_MODES else fallback


def _coerce_assertion_traits(
    value: Any,
    *,
    fallback: frozenset[str] | None,
) -> frozenset[str] | None:
    if value is None:
        return fallback
    if value == "all":
        return None
    if not isinstance(value, (list, tuple, set, frozenset)):
        return fallback
    normalized = {str(item).strip() for item in value if str(item).strip()}
    return frozenset(normalized)


def _coerce_derived_assertion_specs(
    value: Any,
    *,
    fallback: tuple[dict[str, Any], ...],
) -> tuple[dict[str, Any], ...]:
    if value is None:
        return fallback
    if not isinstance(value, list):
        return fallback
    return tuple(dict(item) for item in value if isinstance(item, dict))


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
    "ASSERTION_MODES",
    "DEFAULT_EXTRACTION_PROFILES",
    "DefaultSubjectPolicy",
    "ExtractionProfile",
    "build_extraction_profile_registry",
    "get_extraction_profiles",
    "reload_extraction_profiles",
    "resolve_extraction_profile",
]
