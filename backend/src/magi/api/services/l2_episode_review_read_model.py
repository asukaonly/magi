"""Read-model helpers for L2 episode review API responses."""

from __future__ import annotations

import re
from typing import Any

from magi.api.services.l2_episode_review_helpers import serialize_l1_event_preview
from magi.memory.evidence import USER_VISIBLE_L1_RETRIEVAL_SCOPES
from magi.memory.l2.entities.catalog.lookup import get_canonical_names


def get_unified_layer(unified_memory: Any, name: str) -> Any:
    attrs = getattr(unified_memory, "__dict__", {})
    if isinstance(attrs, dict) and name in attrs:
        return attrs[name]
    layer = getattr(unified_memory, name, None)
    if layer.__class__.__module__.startswith("unittest.mock"):
        return None
    return layer


def get_configured_or_real_method(obj: Any, name: str) -> Any | None:
    if obj is None:
        return None
    attrs = getattr(obj, "__dict__", {})
    if isinstance(attrs, dict) and name in attrs:
        method = attrs[name]
    elif hasattr(type(obj), name):
        method = getattr(obj, name, None)
    else:
        return None
    return method if callable(method) else None


def ordered_non_empty_strings(items: Any) -> list[str]:
    values: list[str] = []
    seen: set[str] = set()
    for item in items or []:
        value = str(item or "").strip()
        if not value or value in seen:
            continue
        values.append(value)
        seen.add(value)
    return values


async def fetch_l1_events_by_ids(
    unified_memory: Any,
    event_ids: list[str],
) -> list[dict[str, Any]]:
    l1_store = get_unified_layer(unified_memory, "l1")
    if l1_store is None or not event_ids:
        return []
    fetch_events = get_configured_or_real_method(l1_store, "fetch_events")
    if fetch_events is not None:
        return await fetch_events(
            event_ids,
            l1_retrieval_scopes=list(USER_VISIBLE_L1_RETRIEVAL_SCOPES),
        )
    return []


async def attach_episode_entity_previews(
    unified_memory: Any,
    items: list[dict[str, Any]],
) -> None:
    entity_ids = ordered_non_empty_strings(
        entity_id
        for item in items
        for entity_id in item.get("primary_entity_ids") or []
    )
    previews_by_id = await lookup_primary_entity_previews(unified_memory, entity_ids)
    for item in items:
        item["primary_entities"] = [
            previews_by_id[entity_id]
            for entity_id in ordered_non_empty_strings(item.get("primary_entity_ids"))
            if entity_id in previews_by_id
        ]


async def serialize_episode_event_previews(
    unified_memory: Any,
    event_memberships: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    event_ids = [
        str(item.get("event_id") or "").strip()
        for item in event_memberships
        if item.get("event_id")
    ]
    hydrated_events = await fetch_l1_events_by_ids(unified_memory, event_ids)
    l1_events_by_id = {
        str(item.get("event_id") or ""): item
        for item in hydrated_events
        if item.get("event_id")
    }

    events = [
        serialize_l1_event_preview(l1_events_by_id.get(str(item.get("event_id") or "")), membership=item)
        for item in event_memberships
    ]
    events.sort(key=lambda item: (
        item.get("timestamp") is None,
        float(item.get("timestamp") or item.get("added_at") or 0.0),
    ))
    return events


async def lookup_primary_entity_previews(
    unified_memory: Any,
    entity_ids: list[str],
) -> dict[str, dict[str, str]]:
    if not entity_ids:
        return {}

    records: list[dict[str, Any]] = []
    catalog = get_unified_layer(unified_memory, "l2_entity_catalog")
    list_entities = get_configured_or_real_method(catalog, "list_entities")
    if list_entities is not None:
        records = await list_entities(limit=len(entity_ids), entity_ids=entity_ids)

    if not records:
        l2_store = get_unified_layer(unified_memory, "l2")
        db_path = str(getattr(l2_store, "db_path", "") or "")
        if db_path:
            names = await get_canonical_names(db_path, entity_ids)
            records = [
                {
                    "entity_id": entity_id,
                    "canonical_name": name,
                    "entity_type": _entity_type_from_id(entity_id),
                }
                for entity_id, name in names.items()
            ]

    by_id = {str(item.get("entity_id") or ""): item for item in records if item.get("entity_id")}
    previews: dict[str, dict[str, str]] = {}
    for entity_id in entity_ids:
        record = by_id.get(entity_id) or {}
        name = str(record.get("canonical_name") or "").strip() or _fallback_entity_name(entity_id)
        if not name:
            continue
        previews[entity_id] = {
            "id": entity_id,
            "name": name,
            "type": str(record.get("entity_type") or _entity_type_from_id(entity_id) or ""),
        }
    return previews


def _entity_type_from_id(entity_id: str) -> str:
    if ":" not in entity_id:
        return ""
    return entity_id.split(":", 1)[0]


def _fallback_entity_name(entity_id: str) -> str:
    if entity_id in {"user", "user:local_user", "local_user"}:
        return ""
    value = entity_id.split(":", 1)[1] if ":" in entity_id else entity_id
    value = value.strip()
    if not value:
        return ""
    if re.fullmatch(r"[0-9a-fA-F]{10,}", value) or re.fullmatch(r"[0-9A-HJKMNP-TV-Z]{12,}", value):
        return ""
    return value.replace("-", " ").replace("_", " ")
