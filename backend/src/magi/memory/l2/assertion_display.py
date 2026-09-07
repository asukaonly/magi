"""Read-only fact presentation shared by memory product surfaces."""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from typing import Any

from ...i18n import effective_app_language_code
from .assertion_family_policy import get_assertion_family_policy
from .semantic_routing import ObjectRole, assertion_predicate_descriptors
from .entities.catalog.lookup import get_canonical_names
from .factual_rendering import grounded_predicate_wording, render_behavior_observation

_LITERAL_PREDICATES = {
    descriptor.trait_code: descriptor.predicate
    for descriptor in assertion_predicate_descriptors()
    if descriptor.object_role in {ObjectRole.CANONICAL_VALUE, ObjectRole.GOAL_TEXT}
}
# Personal Profile owns this additional literal field outside Claim extraction.
_LITERAL_PREDICATES["identity.location.home"] = "HOME_LOCATION"
_TARGET_PREDICATES: dict[str, dict[str, str]] = {}
for _descriptor in assertion_predicate_descriptors():
    if _descriptor.object_role in {ObjectRole.TARGET_IDENTITY, ObjectRole.TARGET_ID_OR_TEXT}:
        if _descriptor.canonical_value is not None:
            _TARGET_PREDICATES.setdefault(_descriptor.trait_code, {})[
                _descriptor.canonical_value
            ] = _descriptor.predicate

_CONTROLLED_FAMILIES = {
    "mood": ("情绪", "mood"), "stress": ("压力水平", "stress level"),
    "engagement": ("投入程度", "engagement"), "group_atmosphere": ("群体氛围", "group atmosphere"),
    "public_sentiment": ("公众评价", "public sentiment"), "state_profile": ("状态", "state"),
}
_CONTROLLED_LABELS = {
    "high": ("高", "high"), "medium": ("中", "medium"), "low": ("低", "low"),
    "positive": ("积极", "positive"), "negative": ("消极", "negative"),
    "neutral": ("中性", "neutral"), "focused": ("专注", "focused"), "calm": ("平静", "calm"),
}


def assertion_value_options(assertion: Mapping[str, Any]) -> list[str] | None:
    """Expose editable canonical values without changing their write semantics."""
    choices = _TARGET_PREDICATES.get(str(assertion.get("trait_name") or ""))
    return list(choices) if choices else None


def assertion_display_is_recent(assertion: Mapping[str, Any]) -> bool:
    """Read the retained temporal scope without choosing a new horizon."""
    return str(assertion.get("temporal_scope") or "") in {
        "recent", "session", "daily", "weekly", "temporary"
    }


def assertion_behavior_target(assertion: Mapping[str, Any], *, language: str | None = None) -> str:
    """Render the catalog target of a behavioral observation, never its storage strategy."""
    name = str(assertion.get("target_entity_name") or "").strip()
    if name:
        return name
    return "尚未解析的对象" if (language or effective_app_language_code()).startswith("zh") else "an unresolved object"


def _literal_text(value: Any, *, zh: bool) -> str:
    if isinstance(value, str):
        text = value.strip()
        if text.startswith(("{", "[", '"')):
            try:
                return _literal_text(json.loads(text), zh=zh)
            except (TypeError, ValueError):
                return text
        return text
    if isinstance(value, Mapping):
        return _literal_text(value.get("value"), zh=zh)
    if isinstance(value, list):
        return ("、" if zh else ", ").join(
            text for item in value if (text := _literal_text(item, zh=zh))
        )
    return str(value) if value is not None else ""


def render_assertion_display(
    assertion: Mapping[str, Any], *, language: str | None = None
) -> str:
    """Render a retained fact; missing endpoints never become invented names."""
    language = language or effective_app_language_code()
    zh = language.startswith("zh")
    value = _literal_text(assertion.get("trait_value", assertion.get("value")), zh=zh)
    recent = assertion_display_is_recent(assertion)
    if assertion.get("inference_depth") == "topology_only":
        subject = None if assertion.get("entity_type") == "user" else (
            str(assertion.get("entity_name") or "").strip()
            or ("主体未解析的对象" if zh else "an unresolved subject")
        )
        return render_behavior_observation(
            assertion_behavior_target(assertion, language=language), recent=recent, language=language, subject=subject
        )
    summary = str(assertion.get("natural_summary") or "").strip()
    if summary and assertion.get("source_domain") != "settings_profile":
        return summary
    trait = str(assertion.get("trait_name") or "")
    subject = str(assertion.get("entity_name") or "").strip()
    if assertion.get("entity_type") == "user":
        subject = "用户" if zh else "The user"
    if not subject:
        subject = "主体未解析的对象" if zh else "An unresolved subject"
    family = _CONTROLLED_FAMILIES.get(str(assertion.get("trait_family") or ""))
    label = _CONTROLLED_LABELS.get(value)
    policy = get_assertion_family_policy(str(assertion.get("trait_family") or ""))
    if family and label and policy and policy.value_i18n == "controlled":
        if zh:
            return f"{subject}{'近期' if recent else ''}的{family[0]}是{label[0]}。"
        return f"{subject}'s {'recent ' if recent else ''}{family[1]} is {label[1]}."
    choices = _TARGET_PREDICATES.get(trait)
    predicate = choices.get(value) if choices else _LITERAL_PREDICATES.get(trait)
    wording = ("常住地是", "lives in") if predicate == "HOME_LOCATION" else (
        grounded_predicate_wording(predicate) if predicate else None
    )
    if wording:
        target = str(assertion.get("target_entity_name") or "").strip() if choices else value
        if not target:
            target = "尚未解析的对象" if zh else "an unresolved object"
        if zh:
            return f"{subject}{'最近' if recent else ''}{wording[0]}{target}。"
        return f"{subject} {'recently ' if recent else ''}{wording[1]} {target}."
    return "这条记录缺少完整事实描述。" if zh else "A complete description of this record is unavailable."


async def decorate_assertion_display(
    db_path: str | None,
    assertions: Sequence[Mapping[str, Any]],
) -> list[dict[str, Any]]:
    """Batch-hydrate authoritative names and attach presentation-only fields."""
    entity_ids = {
        str(value)
        for assertion in assertions
        for value in (assertion.get("entity_id"), assertion.get("target_entity_id"))
        if value
    }
    names = await get_canonical_names(db_path, entity_ids) if db_path and entity_ids else {}
    user_name = "用户" if effective_app_language_code().startswith("zh") else "The user"
    result: list[dict[str, Any]] = []
    for assertion in assertions:
        item = {
            **assertion,
            "entity_name": (
                user_name if assertion.get("entity_type") == "user"
                else names.get(str(assertion.get("entity_id") or ""))
            ),
            "target_entity_name": names.get(str(assertion.get("target_entity_id") or "")),
            "value_options": assertion_value_options(assertion),
        }
        item["display_text"] = render_assertion_display(item)
        result.append(item)
    return result
