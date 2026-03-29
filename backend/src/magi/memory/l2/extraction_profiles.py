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
    extraction_instructions: str | None = None


DEFAULT_EXTRACTION_PROFILES: dict[str, ExtractionProfile] = {
    "chat.user_message": ExtractionProfile(
        profile_id="chat.user_message",
    ),
    "timeline.chrome_history": ExtractionProfile(
        profile_id="timeline.chrome_history",
        allowed_entity_types=frozenset({
            "product", "software", "technology", "media",
            "person", "organization", "topic",
        }),
        allowed_predicates=frozenset({
            "VISITED", "USES", "INTERESTED_IN", "FOLLOWS",
            "VIEWED", "WORKS_WITH",
        }),
        allowed_assertion_families=frozenset(),
        allow_assertion=False,
        extraction_instructions=(
            "These events are browser history page titles, NOT user-authored messages.\n"
            "Page titles often follow patterns like '{content} - {platform}' or "
            "'{content} | {platform}'. Treat the platform part (YouTube, 哔哩哔哩, "
            "GitHub, etc.) as a `software` entity, and the content part as the "
            "actual subject (media, person, project, topic).\n\n"
            "Predicate guidance for browsing behavior:\n"
            "- USES: only for tool/platform usage (e.g., user uses GitHub, ChatGPT)\n"
            "- INTERESTED_IN: when the user repeatedly browses content on a topic "
            "(e.g., AI papers, a TV show, a game)\n"
            "- VIEWED: for individual content consumption (a specific video, article)\n"
            "- FOLLOWS: when visiting a specific creator or person's page\n"
            "- WORKS_WITH: for professional tools/technologies seen in work context\n\n"
            "Entity extraction rules (IMPORTANT):\n"
            "- Be SELECTIVE: only extract entities that reveal user interests, "
            "habits, or tool usage. Not every page title deserves an entity.\n"
            "- SKIP noise: error messages, email addresses, IP addresses, "
            "UI element names (Home, Inbox, Schema Panel), authentication pages, "
            "and generic navigation titles are NOT entities.\n"
            "- MERGE related content: multiple pages about the same game, show, "
            "or topic should map to ONE entity with a concise canonical name, "
            "not one entity per page title. E.g., '燕云十六声射覆答案', "
            "'燕云十六声攻略', '燕云十六声金明池' → single entity '燕云十六声'.\n"
            "- Keep canonical names SHORT: use the core subject name, not the "
            "full page title. E.g., 'Joe Pera Talks With You' not "
            "'Joe Pera Talks With You 豆瓣'.\n"
            "- Only use allowed entity types: software, product, technology, "
            "media, person, organization, topic. Do NOT use virtual_object, "
            "activity, concept, skill, food, health_metric, or other.\n"
            "- Do NOT use platform names as alias_signals for content entities.\n"
            "- Keep entity types consistent: a website/app is always `software`, "
            "not `activity` or `organization`."
        ),
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
    if source == "chrome_history":
        return "timeline.chrome_history"
    if source in {"timeline", "calendar"}:
        return "timeline.calendar"
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
