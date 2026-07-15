"""Build product-facing user portrait projections from L2 evidence."""

from __future__ import annotations

import time
from typing import Any, Protocol

from ..memory.derivation_revision import DerivationRevision
from .models import (
    DEFAULT_USER_ID,
    PROFILE_ASSERTION_FAMILIES,
    UserPortraitProjection,
    UserProfileProjection,
)
from .portrait_signal_policy import (
    PORTRAIT_WORLD_GROUP_IDS,
    PORTRAIT_SOURCE_STRENGTH as SOURCE_STRENGTH,
    PORTRAIT_VALIDATION_STRENGTH as VALIDATION_STRENGTH,
    assertion_portrait_role,
    classify_assertion_portrait,
)
from .portrait_values import display_value as _display_value

PORTRAIT_ASSERTION_FAMILIES = (
    *PROFILE_ASSERTION_FAMILIES,
    "interest_profile",
    "project_profile",
    "routine_profile",
    "mood",
    "stress",
    "engagement",
)
WORLD_GROUP_IDS = PORTRAIT_WORLD_GROUP_IDS
_INTERNAL_SOURCE_KEYS = {
    "external_activity",
    "photo_library",
    "photo_library_apple_photos",
    "photo_library_directory",
}


class UserPortraitLLMClient(Protocol):
    """Optional LLM post-processor for portrait projection wording."""

    async def generate_portrait(self, *, material: dict[str, Any]) -> dict[str, Any]:
        """Return structured portrait overrides grounded in *material*."""


class UserPortraitProjectionBuilder:
    """Create a clean self-portrait projection from L2 profile evidence."""

    def __init__(
        self,
        l2_store: Any,
        *,
        profile_projection: UserProfileProjection | None = None,
        llm_client: UserPortraitLLMClient | None = None,
    ):
        self._l2_store = l2_store
        self._profile_projection = profile_projection
        self._llm_client = llm_client

    def with_profile_projection(
        self,
        profile_projection: UserProfileProjection | None,
    ) -> "UserPortraitProjectionBuilder":
        """Return a builder with the same dependencies and a fresh profile input."""
        return UserPortraitProjectionBuilder(
            self._l2_store,
            profile_projection=profile_projection,
            llm_client=self._llm_client,
        )

    async def build(self, user_id: str = DEFAULT_USER_ID) -> UserPortraitProjection:
        entity_id = f"user:{user_id}"
        derivation_revision = await DerivationRevision.capture(self._l2_store, entity_id)
        if self._profile_projection is not None:
            derivation_revision.ensure_matches(self._profile_projection.source_revision)
            derivation_revision.ensure_generation_matches(
                self._profile_projection.source_generation
            )
        assertions = await self._list_assertions(entity_id)
        profile_world = self._profile_world_items(self._profile_projection)
        world = self._build_world(assertions, profile_world)
        review = self._build_review(assertions)
        recent = self._build_recent(
            assertions=assertions,
        )
        evidence_refs = self._evidence_refs(assertions=assertions)
        source_counts = self._source_counts(assertions)
        # Keep main-model context grounded in governed assertions and explicit profile fields.
        prompt_summary = self._rule_prompt_summary(world=world, recent=recent)
        generated_by = "rule"

        material = {
            "world": world,
            "review": review,
            "recent": recent,
            "prompt_summary": prompt_summary,
            "evidence_refs": evidence_refs,
            "source_counts": source_counts,
        }
        llm_payload = await self._llm_overrides(material)
        llm_summary = _string_list(llm_payload.get("prompt_summary"))
        if llm_summary:
            prompt_summary = llm_summary[:4]
            generated_by = "llm"

        await derivation_revision.ensure_current(self._l2_store)
        return UserPortraitProjection(
            user_id=user_id,
            entity_id=entity_id,
            world=world,
            review=review,
            recent=recent,
            prompt_summary=prompt_summary,
            evidence_refs=evidence_refs,
            source_counts=source_counts,
            generated_by=generated_by,
            source_revision=derivation_revision.source_revision,
            source_generation=int(derivation_revision.clear_generation or 0),
            generated_at=time.time(),
        )

    async def _list_assertions(self, entity_id: str) -> list[dict[str, Any]]:
        if self._l2_store is None:
            return []
        list_assertions = getattr(self._l2_store, "list_current_assertions", None)
        if list_assertions is None:
            return []
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
        ][:200]

    def _build_world(
        self,
        assertions: list[dict[str, Any]],
        profile_world: dict[str, list[dict[str, Any]]],
    ) -> dict[str, Any]:
        groups = [{"id": group_id, "items": []} for group_id in WORLD_GROUP_IDS]
        by_id = {group["id"]: group for group in groups}

        for group_id, items in profile_world.items():
            target = by_id.get(group_id)
            if target is not None:
                target["items"].extend(items)

        for assertion in assertions:
            if assertion_portrait_role(assertion) != "world":
                continue
            group_id = _world_group_for_assertion(assertion)
            if not group_id:
                continue
            item = _item_from_assertion(assertion)
            if item:
                by_id[group_id]["items"].append(item)

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
        if profile is None:
            return {}
        grouped: dict[str, list[dict[str, Any]]] = {group_id: [] for group_id in WORLD_GROUP_IDS}

        def add(group_id: str, field: str, text: str, *, basis_count: int = 1) -> None:
            clean = _text(text)
            if not clean:
                return
            grouped[group_id].append({
                "id": f"profile:{field}",
                "text": clean,
                "source": "",
                "source_key": "user_profile_projection",
                "assertion_id": None,
                "basis_count": basis_count,
                "basis_refs": [
                    "source:user_profile_projection",
                    f"profile:{field}",
                ],
            })

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
            if key == "disallowed_forms_of_address":
                continue
            text = _display_value(value)
            if text:
                add("work_style", f"communication:{key}", text)
        return grouped

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

    def _rule_prompt_summary(self, *, world: dict[str, Any], recent: dict[str, Any]) -> list[str]:
        groups = {
            group["id"]: list(group.get("items", []))
            for group in world.get("groups", [])
        }
        lines: list[str] = []
        identity = _item_texts(groups.get("identity", []))[:3]
        if identity:
            lines.append(f"用户资料：{'；'.join(identity)}。")
        projects = _item_texts(groups.get("projects", []))[:3]
        if projects:
            lines.append(f"用户长期推进或反复关注：{'、'.join(projects)}。")
        preferences = _item_texts(groups.get("preferences", []))[:4]
        if preferences:
            lines.append(f"用户关注或偏好：{'、'.join(preferences)}。")
        work_style = _item_texts(groups.get("work_style", []))[:4]
        if work_style:
            lines.append(f"用户的工作和沟通方式：{'、'.join(work_style)}。")
        recent_items = _item_texts(list(recent.get("items", [])))[:2]
        if recent_items and len(lines) < 4:
            lines.append(f"近期线索：{'、'.join(recent_items)}；不要直接当成长期结论。")
        return lines[:4]

    async def _llm_overrides(self, material: dict[str, Any]) -> dict[str, Any]:
        if self._llm_client is None:
            return {}
        try:
            payload = await self._llm_client.generate_portrait(material=material)
        except Exception:
            return {}
        return payload if isinstance(payload, dict) else {}

    @staticmethod
    def _evidence_refs(
        *,
        assertions: list[dict[str, Any]],
    ) -> list[str]:
        refs: list[str] = []
        for assertion in assertions:
            assertion_id = _text(assertion.get("assertion_id"))
            if assertion_id:
                refs.append(f"assertion:{assertion_id}")
        return list(dict.fromkeys(refs))

    @staticmethod
    def _source_counts(assertions: list[dict[str, Any]]) -> dict[str, int]:
        counts: dict[str, int] = {}
        for assertion in assertions:
            source = _text(assertion.get("source_domain")) or "unknown"
            counts[source] = counts.get(source, 0) + 1
        return counts


def _item_from_assertion(assertion: dict[str, Any]) -> dict[str, Any] | None:
    text = _display_value(assertion.get("trait_value"))
    if not text:
        return None
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
    decision = classify_assertion_portrait(assertion)
    return {
        "id": assertion_id or f"{_text(assertion.get('trait_name'))}:{text}",
        "text": text,
        "source": "",
        "source_key": source_key,
        "assertion_id": assertion_id or None,
        "basis_count": _evidence_count(assertion),
        "basis_refs": refs,
        "claim_kind": decision.claim_kind,
    }


def _world_group_for_assertion(assertion: dict[str, Any]) -> str | None:
    return classify_assertion_portrait(assertion).world_group


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
        existing = best_by_text.get(text.casefold())
        if existing is None or _item_score(item) > _item_score(existing):
            best_by_text[text.casefold()] = item
    return sorted(best_by_text.values(), key=_item_score, reverse=True)


def _dedupe_items_in_order(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    seen: set[str] = set()
    result: list[dict[str, Any]] = []
    for item in items:
        text = _text(item.get("text"))
        key = text.casefold()
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


__all__ = ["UserPortraitLLMClient", "UserPortraitProjectionBuilder"]
