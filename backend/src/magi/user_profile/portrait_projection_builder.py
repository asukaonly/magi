"""Build product-facing user portrait projections from L2 evidence."""

from __future__ import annotations

import inspect
import time
from dataclasses import dataclass
from typing import Any, TypedDict

from ..memory.derivation_revision import DerivationRevision
from ..memory.l2.assertion_display import (
    FactCompleteness, assertion_behavior_target, assertion_display_is_recent, assertion_fact_signature,
    assertion_value_options,
    decorate_assertion_display, render_assertion_display, render_assertion_fact,
)
from ..memory.l2.factual_rendering import assertion_evidence_basis
from ..i18n import effective_app_language_code
from .models import (
    DEFAULT_USER_ID,
    PORTRAIT_PROMPT_CONTRACT_VERSION,
    PROFILE_ASSERTION_FAMILIES,
    UserPortraitProjection,
    UserProfileProjection,
)
from .portrait_claim_query import (
    TentativePortraitClaim,
    latest_portrait_claim_change_at,
    list_tentative_portrait_claims,
)
from .projection_freshness import (
    assertion_records_highwater,
    profile_projection_highwater,
)
from .portrait_signal_policy import (
    PORTRAIT_WORLD_GROUP_IDS,
    PORTRAIT_SOURCE_STRENGTH as SOURCE_STRENGTH,
    PORTRAIT_VALIDATION_STRENGTH as VALIDATION_STRENGTH,
    assertion_portrait_role,
    classify_assertion_portrait,
)
from .portrait_values import correction_value as _correction_value
from .portrait_values import display_value as _display_value

PORTRAIT_ASSERTION_FAMILIES = (
    *PROFILE_ASSERTION_FAMILIES,
    "interest_profile",
    "project_profile",
    "routine_profile",
    "mood",
    "stress",
    "engagement",
    "goal_profile",
)
WORLD_GROUP_IDS = PORTRAIT_WORLD_GROUP_IDS
_INTERNAL_SOURCE_KEYS = {
    "external_activity",
    "photo_library",
    "photo_library_apple_photos",
    "photo_library_directory",
}
_MAX_PROMPT_SUMMARY_LINES = 4
_MAX_PROTECTED_GOAL_LINES = 2
TENTATIVE_SELECTION_REF_PREFIX = "tentative:"


@dataclass(frozen=True)
class PortraitPromptInputs:
    """Semantic facts selected from governed inputs, independent of UI items."""

    world: dict[str, tuple[str, ...]]
    recent: tuple[str, ...]
    goals: tuple[str, ...]


@dataclass(frozen=True)
class _PortraitFact:
    key: str
    text: str
    score: tuple[int, int, int]
    field: str = ""
    trait_family: str = ""


class _PortraitWorldGroup(TypedDict):
    id: str
    items: list[dict[str, Any]]
    summary: str


class UserPortraitProjectionBuilder:
    """Create a clean self-portrait projection from L2 profile evidence."""

    def __init__(
        self,
        l2_store: Any,
        *,
        profile_projection: UserProfileProjection | None = None,
    ):
        self._l2_store = l2_store
        self._profile_projection = profile_projection

    def with_profile_projection(
        self,
        profile_projection: UserProfileProjection | None,
    ) -> "UserPortraitProjectionBuilder":
        """Return a builder with the same dependencies and a fresh profile input."""
        return UserPortraitProjectionBuilder(
            self._l2_store,
            profile_projection=profile_projection,
        )

    async def build(self, user_id: str = DEFAULT_USER_ID) -> UserPortraitProjection:
        entity_id = f"user:{user_id}"
        derivation_revision = await DerivationRevision.capture(self._l2_store, entity_id)
        if self._profile_projection is not None:
            derivation_revision.ensure_matches(self._profile_projection.source_revision)
            derivation_revision.ensure_generation_matches(
                self._profile_projection.source_generation
            )
        assertions = await decorate_assertion_display(
            getattr(self._l2_store, "db_path", None), await self._list_assertions(entity_id)
        )
        profile_world = self._profile_world_items(self._profile_projection)
        world = self._build_world(assertions, profile_world)
        review = self._build_review(assertions)
        recent = self._build_recent(
            assertions=assertions,
        )
        tentative_claims = await self._list_tentative_claims(
            user_id=user_id,
            assertions=assertions,
        )
        tentative_lines = [candidate.prompt_line for candidate in tentative_claims[:2]]
        # Keep main-model context grounded in governed assertions, explicit profile
        # fields, and deterministic Claim material.
        prompt_summary = render_portrait_rule_prompt_summary(
            inputs=build_portrait_prompt_inputs(
                assertions=assertions,
                profile_projection=self._profile_projection,
            ),
            tentative_lines=tentative_lines,
        )
        selected_tentative_claims = select_rendered_tentative_portrait_claims(
            tentative_claims[:2],
            prompt_summary,
        )
        evidence_refs = self._evidence_refs(
            assertions=assertions,
            tentative_claims=selected_tentative_claims,
        )
        source_counts = self._source_counts(assertions)
        if selected_tentative_claims:
            source_counts["user_authored"] = source_counts.get("user_authored", 0) + len(
                selected_tentative_claims
            )
        assertion_highwater = assertion_records_highwater(assertions)
        claim_highwater = await latest_portrait_claim_change_at(
            self._l2_store,
            user_id=user_id,
        )
        review_highwater = await self._latest_review_change_at(entity_id)

        await derivation_revision.ensure_current(self._l2_store)
        return UserPortraitProjection(
            user_id=user_id,
            entity_id=entity_id,
            world=world,
            review=review,
            recent=recent,
            prompt_summary=prompt_summary,
            prompt_contract_version=PORTRAIT_PROMPT_CONTRACT_VERSION,
            evidence_refs=evidence_refs,
            source_counts=source_counts,
            generated_by="rule",
            input_assertion_highwater=assertion_highwater,
            input_claim_highwater=claim_highwater,
            input_review_highwater=review_highwater,
            input_profile_highwater=profile_projection_highwater(
                self._profile_projection
            ),
            source_revision=derivation_revision.source_revision,
            source_generation=int(derivation_revision.clear_generation or 0),
            generated_at=time.time(),
        )

    async def _list_assertions(self, entity_id: str) -> list[dict[str, Any]]:
        list_assertions = getattr(self._l2_store, "list_current_assertions", None)
        if not callable(list_assertions):
            raise RuntimeError("L2 current Assertion reads are unavailable")
        assertions = await list_assertions(
            entity_id=entity_id,
            entity_type="user",
            context_scope=None,
            limit=500,
        )
        return [
            assertion
            for assertion in assertions
            if assertion.get("trait_family") in PORTRAIT_ASSERTION_FAMILIES
        ]

    async def _latest_review_change_at(self, entity_id: str) -> float:
        if inspect.getattr_static(
            self._l2_store,
            "latest_pending_review_change_at",
            None,
        ) is None:
            return 0.0
        getter = getattr(self._l2_store, "latest_pending_review_change_at", None)
        if not callable(getter):
            return 0.0
        return float(await getter(subject_id=entity_id) or 0.0)

    async def _list_tentative_claims(
        self,
        *,
        user_id: str,
        assertions: list[dict[str, Any]],
    ) -> list[TentativePortraitClaim]:
        current_assertion_ids = [
            assertion_id
            for assertion in assertions
            if (assertion_id := _text(assertion.get("assertion_id")))
        ]
        visible_assertion_ids = [
            assertion_id
            for assertion in assertions
            if assertion_portrait_role(assertion) in {"world", "recent"}
            and (assertion_id := _text(assertion.get("assertion_id")))
        ]
        return await list_tentative_portrait_claims(
            self._l2_store,
            user_id=user_id,
            current_assertion_ids=current_assertion_ids,
            visible_assertion_ids=visible_assertion_ids,
        )

    def _build_world(
        self,
        assertions: list[dict[str, Any]],
        profile_world: dict[str, list[dict[str, Any]]],
    ) -> dict[str, Any]:
        groups: list[_PortraitWorldGroup] = [
            {"id": group_id, "items": [], "summary": ""} for group_id in WORLD_GROUP_IDS
        ]
        by_id: dict[str, _PortraitWorldGroup] = {group["id"]: group for group in groups}

        for group_id, items in profile_world.items():
            target = by_id.get(group_id)
            if target is not None:
                target["items"].extend(items)

        for assertion in assertions:
            if assertion_portrait_role(assertion) != "world":
                continue
            assertion_group_id = _world_group_for_assertion(assertion)
            if not assertion_group_id:
                continue
            item = _item_from_assertion(assertion)
            if item:
                by_id[assertion_group_id]["items"].append(item)

        for group in groups:
            group["items"] = _dedupe_items(group["items"])[:5]
            group["summary"] = _group_summary(group["id"], group["items"])
        return {
            "total_count": sum(len(group["items"]) for group in groups),
            "groups": groups,
        }

    @staticmethod
    def _profile_world_items(
        profile: UserProfileProjection | None,
    ) -> dict[str, list[dict[str, Any]]]:
        return {
            group_id: [{
                "id": f"profile:{fact.field}",
                "text": fact.text,
                "source": "",
                "source_key": "user_profile_projection",
                "assertion_id": None,
                "basis_count": 1,
                "basis_refs": [
                    "source:user_profile_projection",
                    f"profile:{fact.field}",
                ],
            } for fact in facts]
            for group_id, facts in _profile_facts(profile).items()
        }

    def _build_review(self, assertions: list[dict[str, Any]]) -> dict[str, Any]:
        items = []
        for assertion in assertions:
            if assertion_portrait_role(assertion) != "review":
                continue
            item = _item_from_assertion(assertion)
            if item:
                items.append(item)
        return {"items": _dedupe_items(items)[:8]}

    def _build_recent(
        self,
        *,
        assertions: list[dict[str, Any]],
    ) -> dict[str, Any]:
        items: list[dict[str, Any]] = []
        for assertion in assertions:
            if assertion_portrait_role(assertion) != "recent":
                continue
            item = _item_from_assertion(assertion)
            if item:
                items.append(item)
        return {"items": _dedupe_items_in_order(items)[:6]}

    @staticmethod
    def _evidence_refs(
        *,
        assertions: list[dict[str, Any]],
        tentative_claims: list[TentativePortraitClaim],
    ) -> list[str]:
        refs: list[str] = []
        for assertion in assertions:
            assertion_id = _text(assertion.get("assertion_id"))
            if assertion_id:
                refs.append(f"assertion:{assertion_id}")
        for candidate in tentative_claims:
            refs.extend(candidate.basis_refs)
        refs.extend(tentative_portrait_selection_refs(tentative_claims))
        return list(dict.fromkeys(refs))

    @staticmethod
    def _source_counts(assertions: list[dict[str, Any]]) -> dict[str, int]:
        counts: dict[str, int] = {}
        for assertion in assertions:
            source = _text(assertion.get("source_domain")) or "unknown"
            counts[source] = counts.get(source, 0) + 1
        return counts


def render_portrait_rule_prompt_summary(
    *,
    inputs: PortraitPromptInputs,
    tentative_lines: list[str],
) -> list[str]:
    """Render the deterministic prompt summary used by build and freshness checks."""

    lines: list[str] = []
    identity = inputs.world.get("identity", ())[:3]
    if identity:
        lines.append(f"用户资料：{'；'.join(identity)}。")
    projects = inputs.world.get("projects", ())[:3]
    if projects:
        lines.append(f"用户长期推进或反复关注：{'、'.join(projects)}。")
    preferences = inputs.world.get("preferences", ())[:4]
    if preferences:
        lines.append(f"用户关注或偏好：{'、'.join(preferences)}。")
    work_style = inputs.world.get("work_style", ())[:4]
    if work_style:
        lines.append(f"用户的工作和沟通方式：{'、'.join(work_style)}。")
    for line in tentative_lines[:2]:
        if len(lines) >= _MAX_PROMPT_SUMMARY_LINES:
            break
        lines.append(line)
    recent_items = inputs.recent[:2]
    if recent_items and len(lines) < _MAX_PROMPT_SUMMARY_LINES:
        lines.append(f"近期线索：{'、'.join(recent_items)}；不要直接当成长期结论。")
    return _merge_protected_prompt_lines(lines, list(inputs.goals))


def build_portrait_prompt_inputs(
    *,
    assertions: list[dict[str, Any]],
    profile_projection: UserProfileProjection | None = None,
) -> PortraitPromptInputs:
    """Select grounded text after the existing portrait admission policy.

    Assertion liveness, scope and evidence filtering remain owned by the current
    Assertion read. An incomplete description supplies no model fact, while the
    Assertion remains available to UI and tentative-Claim suppression rules.
    """
    grouped = _profile_facts(profile_projection)
    recent_facts: list[_PortraitFact] = []
    for assertion in assertions:
        role = assertion_portrait_role(assertion)
        if role not in {"world", "recent"}:
            continue
        description = render_assertion_fact(assertion)
        if description.completeness != FactCompleteness.COMPLETE or not description.text:
            continue
        text = description.text
        family = _text(assertion.get("trait_family"))
        if family == "goal_profile":
            text = _goal_text(text)
        source = _text(assertion.get("source_domain"))
        state = _text(assertion.get("validation_state") or assertion.get("status"))
        fact = _PortraitFact(
            key=_text(assertion.get("assertion_id")) or text.casefold(),
            text=text,
            score=(
                SOURCE_STRENGTH.get(source, 0) + VALIDATION_STRENGTH.get(state, 0),
                _evidence_count(assertion),
                len(text),
            ),
            trait_family=family,
        )
        if role == "recent":
            recent_facts.append(fact)
        elif group_id := _world_group_for_assertion(assertion):
            grouped.setdefault(group_id, []).append(fact)
    selected_recent = _dedupe_facts(recent_facts, ranked=False)[:6]
    return PortraitPromptInputs(
        world={
            group_id: tuple(fact.text for fact in _dedupe_facts(facts, ranked=True)[:5])
            for group_id, facts in grouped.items()
        },
        recent=tuple(fact.text for fact in selected_recent if fact.trait_family != "goal_profile"),
        goals=tuple(dict.fromkeys(
            fact.text for fact in selected_recent if fact.trait_family == "goal_profile"
        ))[:_MAX_PROTECTED_GOAL_LINES],
    )


def _profile_facts(
    profile: UserProfileProjection | None,
) -> dict[str, list[_PortraitFact]]:
    grouped: dict[str, list[_PortraitFact]] = {group_id: [] for group_id in WORLD_GROUP_IDS}
    if profile is None:
        return grouped

    def add(group_id: str, field: str, text: str) -> None:
        clean = _text(text)
        if clean:
            grouped[group_id].append(_PortraitFact(
                key=clean.casefold(),
                text=clean,
                score=(SOURCE_STRENGTH.get("user_profile_projection", 0), 1, len(clean)),
                field=field,
            ))

    preferred_form_of_address = _profile_field_text(profile, "preferred_form_of_address")
    if preferred_form_of_address:
        add("identity", "preferred_form_of_address", f"希望称呼为「{preferred_form_of_address}」")
    real_name = _profile_field_text(profile, "real_name")
    if real_name:
        add("identity", "real_name", f"真实姓名：{real_name}")
    birth_date = _profile_field_text(profile, "birth_date")
    if birth_date:
        add("identity", "birth_date", f"生日：{birth_date}")
    home_location = _profile_field_text(profile, "home_location")
    if home_location:
        add("identity", "home_location", f"常住地：{home_location}")

    disallowed = profile.communication.get("disallowed_forms_of_address")
    if isinstance(disallowed, list) and disallowed:
        text = "、".join(_text(item) for item in disallowed if _text(item))
        add("work_style", "disallowed_forms_of_address", f"避免这些称呼：{text}")

    for key, value in (profile.preferences or {}).items():
        text = _display_value(value)
        if text:
            add("preferences", f"preference:{key}", text)
    for key, value in (profile.communication or {}).items():
        if key != "disallowed_forms_of_address" and (text := _display_value(value)):
            add("work_style", f"communication:{key}", text)
    return grouped


def _dedupe_facts(facts: list[_PortraitFact], *, ranked: bool) -> list[_PortraitFact]:
    selected: dict[str, _PortraitFact] = {}
    for fact in facts:
        previous = selected.get(fact.key)
        if previous is None or (ranked and fact.score > previous.score):
            selected[fact.key] = fact
    return sorted(selected.values(), key=lambda fact: fact.score, reverse=True) if ranked else list(selected.values())


def select_rendered_tentative_portrait_claims(
    candidates: list[TentativePortraitClaim],
    prompt_summary: list[str],
) -> list[TentativePortraitClaim]:
    """Return tentative candidates whose deterministic lines survived rendering."""

    rendered_lines = set(_string_list(prompt_summary))
    return [candidate for candidate in candidates if candidate.prompt_line in rendered_lines]


def tentative_portrait_selection_refs(
    candidates: list[TentativePortraitClaim],
) -> list[str]:
    """Return explicit Claim and evidence refs for a rendered tentative selection."""

    refs: list[str] = []
    for candidate in candidates:
        refs.append(f"{TENTATIVE_SELECTION_REF_PREFIX}claim:{candidate.claim_id}")
        refs.extend(
            f"{TENTATIVE_SELECTION_REF_PREFIX}{basis_ref}" for basis_ref in candidate.basis_refs
        )
    return list(dict.fromkeys(refs))


def _item_from_assertion(assertion: dict[str, Any]) -> dict[str, Any] | None:
    text = render_assertion_display(assertion)
    if not text:
        return None
    expression = None
    if assertion.get("inference_depth") == "topology_only":
        recent = assertion_display_is_recent(assertion)
        value = assertion_behavior_target(assertion)
        expression = {"kind": "behavior", "value": value, "horizon": "recent" if recent else "repeated"}
    elif _text(assertion.get("trait_family")).casefold() == "goal_profile":
        text = _goal_text(text)
    assertion_id = _text(assertion.get("assertion_id"))
    raw_source_key = _text(assertion.get("source_domain"))
    source_key = None if raw_source_key in _INTERNAL_SOURCE_KEYS else (raw_source_key or None)
    refs = []
    if assertion_id:
        refs.append(f"assertion:{assertion_id}")
    family = _text(assertion.get("trait_family"))
    if family:
        refs.append(f"family:{family}")
    state = _text(assertion.get("validation_state") or assertion.get("status"))
    if state:
        refs.append(f"status:{state}")
    if raw_source_key:
        refs.append(f"source:{raw_source_key}")
    refs.extend(f"event:{event_id}" for event_id in assertion.get("evidence_events", []) if event_id)
    decision = classify_assertion_portrait(assertion)
    return {
        "id": assertion_id or f"{_text(assertion.get('trait_name'))}:{text}",
        "text": text,
        "display_status": render_assertion_fact(assertion).completeness.value,
        "fact_signature": assertion_fact_signature(assertion),
        "correction_value": _correction_value(assertion.get("trait_value")),
        "correction_value_options": assertion_value_options(assertion),
        "correction_trait_name": _text(assertion.get("trait_name")),
        "source": "",
        "source_key": source_key,
        "assertion_id": assertion_id or None,
        "evidence_basis": assertion_evidence_basis(assertion),
        "expression": expression,
        "basis_count": _evidence_count(assertion),
        "basis_refs": refs,
        "claim_kind": decision.claim_kind,
        "trait_family": _text(assertion.get("trait_family")),
        "updated_at": _optional_float(
            assertion.get("updated_at")
            or assertion.get("last_validated_at")
            or assertion.get("created_at")
        ),
    }


def _world_group_for_assertion(assertion: dict[str, Any]) -> str | None:
    group_id: str | None = classify_assertion_portrait(assertion).world_group
    return group_id


def _group_summary(group_id: str, items: list[dict[str, Any]]) -> str:
    texts = _item_texts(items)
    if not texts:
        return ""
    short = texts[:4]
    if group_id == "identity":
        return "；".join(short)
    if group_id == "projects":
        return f"长期推进或反复关注：{'、'.join(short)}"
    if group_id == "preferences":
        return f"关注或偏好：{'、'.join(short)}"
    if group_id == "work_style":
        return f"工作和沟通方式：{'、'.join(short)}"
    return "、".join(short)


def _profile_field_text(profile: UserProfileProjection, field: str) -> str:
    value = getattr(profile, field, "")
    return value.strip() if isinstance(value, str) else ""


def _dedupe_items(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    best_by_text: dict[str, dict[str, Any]] = {}
    for item in items:
        text = _text(item.get("text"))
        if not text:
            continue
        key = _text(item.get("assertion_id")) or text.casefold()
        existing = best_by_text.get(key)
        if existing is None or _item_score(item) > _item_score(existing):
            best_by_text[key] = item
    return sorted(best_by_text.values(), key=_item_score, reverse=True)


def _dedupe_items_in_order(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    seen: set[str] = set()
    result: list[dict[str, Any]] = []
    for item in items:
        text = _text(item.get("text"))
        key = _text(item.get("assertion_id")) or text.casefold()
        if not text or key in seen:
            continue
        seen.add(key)
        result.append(item)
    return result


def _item_score(item: dict[str, Any]) -> tuple[int, int, int]:
    refs = list(item.get("basis_refs") or [])
    source = ""
    state = ""
    for ref in refs:
        if str(ref).startswith("source:"):
            source = str(ref).split(":", 1)[1]
        elif str(ref).startswith("status:"):
            state = str(ref).split(":", 1)[1]
    return (
        SOURCE_STRENGTH.get(source, 0) + VALIDATION_STRENGTH.get(state, 0),
        int(item.get("basis_count") or 0),
        len(_text(item.get("text"))),
    )


def _item_texts(items: list[dict[str, Any]]) -> list[str]:
    return [_text(item.get("text")) for item in items if _text(item.get("text"))]


def _goal_text(text: str) -> str:
    prefix = "近期计划：" if effective_app_language_code().startswith("zh") else "Current plan: "
    return f"{prefix}{text}"


def _merge_protected_prompt_lines(
    candidate_lines: list[str],
    protected_lines: list[str],
) -> list[str]:
    """Keep deterministic goal lines while sharing the four-line prompt budget."""

    protected = list(dict.fromkeys(_string_list(protected_lines)))[:_MAX_PROMPT_SUMMARY_LINES]
    protected_keys = {line.casefold() for line in protected}
    candidates = [
        line
        for line in dict.fromkeys(_string_list(candidate_lines))
        if line.casefold() not in protected_keys
    ]
    candidate_budget = _MAX_PROMPT_SUMMARY_LINES - len(protected)
    return [*candidates[:candidate_budget], *protected]


def _evidence_count(assertion: dict[str, Any]) -> int:
    if "evidence_count" in assertion:
        try:
            return max(0, int(assertion["evidence_count"]))
        except (TypeError, ValueError):
            pass
    evidence = assertion.get("evidence_events")
    return len(evidence) if isinstance(evidence, list) else 0


def _string_list(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return [text for text in (_text(item) for item in value) if text]


def _text(value: Any) -> str:
    return str(value or "").strip()


def _optional_float(value: Any) -> float | None:
    try:
        return float(value) if value is not None else None
    except (TypeError, ValueError):
        return None


__all__ = [
    "TENTATIVE_SELECTION_REF_PREFIX",
    "PortraitPromptInputs",
    "UserPortraitProjectionBuilder",
    "build_portrait_prompt_inputs",
    "render_portrait_rule_prompt_summary",
    "select_rendered_tentative_portrait_claims",
    "tentative_portrait_selection_refs",
]
