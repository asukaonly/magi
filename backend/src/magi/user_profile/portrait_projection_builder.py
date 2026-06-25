"""Build product-facing user portrait projections from L2 evidence."""

from __future__ import annotations

import json
import time
from typing import Any, Protocol

from .models import DEFAULT_USER_ID, PROFILE_ASSERTION_FAMILIES, UserPortraitProjection
from .portrait_signal_policy import (
    PORTRAIT_RECENT_FAMILIES,
    PORTRAIT_SOURCE_STRENGTH as SOURCE_STRENGTH,
    PORTRAIT_VALIDATION_STRENGTH as VALIDATION_STRENGTH,
    assertion_portrait_role,
)

PORTRAIT_ASSERTION_FAMILIES = (*PROFILE_ASSERTION_FAMILIES, "routine_profile")
WORLD_GROUP_IDS = ("identity", "preferences", "routine", "places", "communication")
WORLD_GROUP_BY_FAMILY = {
    "identity_profile": "identity",
    "preference_profile": "preferences",
    "routine_profile": "routine",
    "communication_profile": "communication",
}


class UserPortraitLLMClient(Protocol):
    """Optional LLM post-processor for portrait projection wording."""

    async def generate_portrait(self, *, material: dict[str, Any]) -> dict[str, Any]:
        """Return structured portrait overrides grounded in *material*."""


class UserPortraitProjectionBuilder:
    """Create a clean self-portrait projection from L2 profile evidence."""

    def __init__(self, l2_store: Any, *, llm_client: UserPortraitLLMClient | None = None):
        self._l2_store = l2_store
        self._llm_client = llm_client

    async def build(self, user_id: str = DEFAULT_USER_ID) -> UserPortraitProjection:
        entity_id = f"user:{user_id}"
        assertions = await self._list_assertions(entity_id)
        snapshot = await self._latest_snapshot(entity_id)

        world = self._build_world(assertions)
        review = self._build_review(assertions)
        recent = self._build_recent(assertions=assertions, snapshot=snapshot)
        evidence_refs = self._evidence_refs(assertions=assertions, snapshot=snapshot)
        source_counts = self._source_counts(assertions)
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
            generated_at=time.time(),
        )

    async def _list_assertions(self, entity_id: str) -> list[dict[str, Any]]:
        if self._l2_store is None:
            return []
        list_assertions = getattr(self._l2_store, "list_tom_assertions", None)
        if list_assertions is None:
            return []
        try:
            return await list_assertions(
                entity_id=entity_id,
                entity_type="user",
                trait_families=PORTRAIT_ASSERTION_FAMILIES,
                include_expired=False,
                limit=200,
            )
        except Exception:
            return []

    async def _latest_snapshot(self, entity_id: str) -> dict[str, Any] | None:
        if self._l2_store is None:
            return None
        list_snapshots = getattr(self._l2_store, "list_tom_snapshots", None)
        if list_snapshots is not None:
            try:
                snapshots = await list_snapshots(entity_id=entity_id, entity_type="user", limit=1)
            except TypeError:
                snapshots = await list_snapshots(entity_id=entity_id, limit=1)
            except Exception:
                snapshots = []
            if snapshots:
                return dict(snapshots[0])
        get_snapshot = getattr(self._l2_store, "get_tom_snapshot", None)
        if get_snapshot is None:
            return None
        try:
            snapshot = await get_snapshot(entity_id=entity_id, entity_type="user")
        except Exception:
            return None
        return dict(snapshot) if isinstance(snapshot, dict) else None

    def _build_world(self, assertions: list[dict[str, Any]]) -> dict[str, Any]:
        groups = [{"id": group_id, "items": []} for group_id in WORLD_GROUP_IDS]
        by_id = {group["id"]: group for group in groups}

        for assertion in assertions:
            if assertion_portrait_role(assertion) != "world":
                continue
            family = _text(assertion.get("trait_family"))
            group_id = WORLD_GROUP_BY_FAMILY.get(family)
            if not group_id:
                continue
            item = _item_from_assertion(assertion)
            if item:
                by_id[group_id]["items"].append(item)

        for group in groups:
            group["items"] = _dedupe_items(group["items"])[:5]
        return {
            "total_count": sum(len(group["items"]) for group in groups),
            "groups": groups,
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
        snapshot: dict[str, Any] | None,
    ) -> dict[str, Any]:
        items: list[dict[str, Any]] = []
        if snapshot is not None:
            core_traits = snapshot.get("core_traits")
            if isinstance(core_traits, dict):
                for value in core_traits.values():
                    text = _display_value(value)
                    if text:
                        items.append({
                            "id": f"snapshot-{snapshot.get('snapshot_id') or 'latest'}-{text}",
                            "text": text,
                            "source": "",
                            "source_key": None,
                            "assertion_id": None,
                            "basis_refs": [f"snapshot:{snapshot.get('snapshot_id') or 'latest'}"],
                        })
            else:
                text = _display_value(core_traits)
                if text:
                    items.append({
                        "id": f"snapshot-{snapshot.get('snapshot_id') or 'latest'}",
                        "text": text,
                        "source": "",
                        "source_key": None,
                        "assertion_id": None,
                        "basis_refs": [f"snapshot:{snapshot.get('snapshot_id') or 'latest'}"],
                    })

        for assertion in assertions:
            family = _text(assertion.get("trait_family"))
            if family not in PORTRAIT_RECENT_FAMILIES:
                continue
            if assertion_portrait_role(assertion) != "recent":
                continue
            item = _item_from_assertion(assertion)
            if item:
                items.append(item)
        return {"items": _dedupe_items_in_order(items)[:6]}

    def _rule_prompt_summary(self, *, world: dict[str, Any], recent: dict[str, Any]) -> list[str]:
        groups = {group["id"]: group.get("items", []) for group in world.get("groups", [])}
        lines: list[str] = []
        preferences = _item_texts(groups.get("preferences", []))[:4]
        if preferences:
            lines.append(f"用户关注或偏好：{'、'.join(preferences)}。")
        routines = _item_texts(groups.get("routine", []))[:3]
        if routines:
            lines.append(f"用户常用或反复出现的工具/习惯：{'、'.join(routines)}。")
        communication = _item_texts(groups.get("communication", []))[:2]
        if communication:
            lines.append(f"用户偏好的沟通方式：{'、'.join(communication)}。")
        recent_items = _item_texts(recent.get("items", []))[:2]
        if recent_items:
            lines.append(f"近期线索：{'、'.join(recent_items)}；不要直接当成长长期结论。")
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
        snapshot: dict[str, Any] | None,
    ) -> list[str]:
        refs: list[str] = []
        for assertion in assertions:
            assertion_id = _text(assertion.get("assertion_id"))
            if assertion_id:
                refs.append(f"assertion:{assertion_id}")
        if snapshot is not None:
            snapshot_id = _text(snapshot.get("snapshot_id"))
            if snapshot_id:
                refs.append(f"snapshot:{snapshot_id}")
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
    source_key = _text(assertion.get("source_domain")) or None
    refs = []
    if assertion_id:
        refs.append(f"assertion:{assertion_id}")
    family = _text(assertion.get("trait_family"))
    if family:
        refs.append(f"family:{family}")
    state = _text(assertion.get("validation_state") or assertion.get("status"))
    if state:
        refs.append(f"status:{state}")
    if source_key:
        refs.append(f"source:{source_key}")
    return {
        "id": assertion_id or f"{_text(assertion.get('trait_name'))}:{text}",
        "text": text,
        "source": "",
        "source_key": source_key,
        "assertion_id": assertion_id or None,
        "basis_count": _evidence_count(assertion),
        "basis_refs": refs,
    }


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


def _display_value(value: Any) -> str:
    parsed = _parse_value(value)
    if isinstance(parsed, dict):
        if "value" in parsed:
            return _display_value(parsed.get("value"))
        return ""
    if isinstance(parsed, list):
        return "、".join(text for text in (_display_value(item) for item in parsed) if text)
    return _text(parsed)


def _parse_value(value: Any) -> Any:
    if not isinstance(value, str):
        return value
    text = value.strip()
    if not text or text[0] not in "[{\"":
        return value
    try:
        return json.loads(text)
    except (TypeError, ValueError, json.JSONDecodeError):
        return value


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
