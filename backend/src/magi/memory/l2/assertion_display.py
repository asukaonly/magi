"""Read-only fact presentation shared by memory product surfaces."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from enum import Enum
import hashlib
import json
from typing import Any

from ...i18n import effective_app_language_code
from .assertion_family_policy import get_assertion_family_policy
from .assertion_values import decode_assertion_literal
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


class SummaryPolicy(str, Enum):
    """The owning read boundary decides whether retained wording may be used."""

    RETAINED = "retained"
    STRUCTURED_ONLY = "structured_only"


class FactCompleteness(str, Enum):
    """Description completeness, independent of evidence strength or admission."""

    COMPLETE = "complete"
    PARTIAL = "partial"
    UNAVAILABLE = "unavailable"


@dataclass(frozen=True, slots=True)
class FactDescription:
    """A fact description, with no UI placeholder or prompt admission decision."""

    text: str | None
    completeness: FactCompleteness


def assertion_fact_signature(assertion: Mapping[str, Any]) -> str:
    """Fingerprint semantic wording independently of surface-specific UI copy."""
    fact = render_assertion_fact(assertion)
    payload = json.dumps([fact.text, fact.completeness.value], ensure_ascii=False)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _description(text: str, *, endpoints_resolved: bool = True) -> FactDescription:
    return FactDescription(
        text=text,
        completeness=FactCompleteness.COMPLETE if endpoints_resolved else FactCompleteness.PARTIAL,
    )


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
    name = _entity_name(assertion, "target_entity")
    if name:
        return name
    return "尚未解析的对象" if (language or effective_app_language_code()).startswith("zh") else "an unresolved object"


def _entity_name(assertion: Mapping[str, Any], field: str) -> str:
    """Reject a catalog identity used as its own supposedly readable name."""
    name = str(assertion.get(f"{field}_name") or "").strip()
    identity = str(assertion.get(f"{field}_id") or "").strip()
    return name if name and name != identity else ""


def _summary_contains_identity(
    assertion: Mapping[str, Any], summary: str, *, literal_value: str | None,
) -> bool:
    """Validate linked references by their role, never by identifier spelling."""
    subject_id = str(assertion.get("entity_id") or "").strip()
    # A known literal may legitimately equal an identifier (for example an
    # explicitly requested form of address). Its spelling does not change its role.
    if subject_id and subject_id in summary and not (
        literal_value is not None and subject_id in literal_value
    ):
        return True
    if literal_value is None:
        target_id = str(assertion.get("target_entity_id") or "").strip()
        if target_id and target_id in summary:
            return True
    return False


def _literal_text(value: Any, *, zh: bool) -> str:
    if isinstance(value, str):
        return value.strip()
    if isinstance(value, Mapping):
        return _literal_text(value.get("value"), zh=zh)
    if isinstance(value, list):
        return ("、" if zh else ", ").join(
            text for item in value if (text := _literal_text(item, zh=zh))
        )
    return str(value) if value is not None else ""


def render_assertion_fact(
    assertion: Mapping[str, Any], *, language: str | None = None,
    summary_policy: SummaryPolicy = SummaryPolicy.RETAINED,
) -> FactDescription:
    """Describe permitted fact content without choosing how consumers handle absence."""
    language = language or effective_app_language_code()
    zh = language.startswith("zh")
    trait = str(assertion.get("trait_name") or "")
    value = _literal_text(
        decode_assertion_literal(trait, assertion.get("trait_value", assertion.get("value"))),
        zh=zh,
    )
    recent = assertion_display_is_recent(assertion)
    subject_resolved = assertion.get("entity_type") == "user" or bool(_entity_name(assertion, "entity"))
    if assertion.get("inference_depth") == "topology_only":
        subject = None if assertion.get("entity_type") == "user" else (
            _entity_name(assertion, "entity")
            or ("主体未解析的对象" if zh else "an unresolved subject")
        )
        return _description(
            render_behavior_observation(
                assertion_behavior_target(assertion, language=language), recent=recent,
                language=language, subject=subject,
            ),
            endpoints_resolved=subject_resolved and bool(_entity_name(assertion, "target_entity")),
        )
    summary = str(assertion.get("natural_summary") or "").strip()
    if summary and summary_policy == SummaryPolicy.RETAINED:
        if _summary_contains_identity(
            assertion, summary, literal_value=value if trait in _LITERAL_PREDICATES else None,
        ):
            # Retention scope is not the source's linguistic time cue. Replacing
            # invalid retained wording with a structured sentence could invent
            # "recently"; the governed rebuild owns recovery from Claim evidence.
            return FactDescription(None, FactCompleteness.UNAVAILABLE)
        return _description(summary)
    subject = _entity_name(assertion, "entity")
    if assertion.get("entity_type") == "user":
        subject = "用户" if zh else "The user"
    if not subject:
        subject = "主体未解析的对象" if zh else "An unresolved subject"
    family = _CONTROLLED_FAMILIES.get(str(assertion.get("trait_family") or ""))
    label = _CONTROLLED_LABELS.get(value)
    policy = get_assertion_family_policy(str(assertion.get("trait_family") or ""))
    if family and label and policy and policy.value_i18n == "controlled":
        if zh:
            text = f"{subject}{'近期' if recent else ''}的{family[0]}是{label[0]}。"
        else:
            text = f"{subject}'s {'recent ' if recent else ''}{family[1]} is {label[1]}."
        return _description(text, endpoints_resolved=subject_resolved)
    choices = _TARGET_PREDICATES.get(trait)
    predicate = choices.get(value) if choices else _LITERAL_PREDICATES.get(trait)
    wording = ("常住地是", "lives in") if predicate == "HOME_LOCATION" else (
        grounded_predicate_wording(predicate) if predicate else None
    )
    if wording:
        target = _entity_name(assertion, "target_entity") if choices else value
        target_resolved = bool(target)
        if not target:
            if not choices:
                return FactDescription(None, FactCompleteness.UNAVAILABLE)
            target = "尚未解析的对象" if zh else "an unresolved object"
        if zh:
            text = f"{subject}{'最近' if recent else ''}{wording[0]}{target}。"
        else:
            text = f"{subject} {'recently ' if recent else ''}{wording[1]} {target}."
        return _description(text, endpoints_resolved=subject_resolved and target_resolved)
    return FactDescription(None, FactCompleteness.UNAVAILABLE)


def _display_text(fact: FactDescription, *, language: str | None = None) -> str:
    if fact.text is not None:
        return fact.text
    zh = (language or effective_app_language_code()).startswith("zh")
    return "这条记录缺少完整事实描述。" if zh else "A complete description of this record is unavailable."


def render_assertion_display(
    assertion: Mapping[str, Any], *, language: str | None = None,
    summary_policy: SummaryPolicy = SummaryPolicy.RETAINED,
) -> str:
    """Render UI text, including an explicit placeholder for unavailable facts."""
    return _display_text(
        render_assertion_fact(assertion, language=language, summary_policy=summary_policy),
        language=language,
    )


async def decorate_assertion_display(
    db_path: str | None,
    assertions: Sequence[Mapping[str, Any]],
    *, summary_policy: SummaryPolicy = SummaryPolicy.RETAINED,
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
        fact = render_assertion_fact(item, summary_policy=summary_policy)
        item["display_text"] = _display_text(fact)
        item["display_status"] = fact.completeness.value
        result.append(item)
    return result
