"""Helpers for normalizing and compacting generic assistant asset references."""

from __future__ import annotations

from typing import Any


def normalize_asset_ref_payload(payload: dict[str, Any] | None) -> dict[str, Any]:
    """Normalize assistant payloads to the generic ``asset_refs`` contract."""
    normalized = dict(payload or {})
    asset_refs = merge_asset_refs(
        normalize_asset_ref_list(normalized.get("asset_refs")),
        normalize_asset_ref_list(normalized.get("candidate_photo_refs"), resolution_state="candidate"),
        normalize_asset_ref_list(normalized.get("photo_refs"), resolution_state="resolved"),
    )
    normalized.pop("candidate_photo_refs", None)
    normalized.pop("photo_refs", None)
    if asset_refs:
        normalized["asset_refs"] = asset_refs
    else:
        normalized.pop("asset_refs", None)
    return normalized


def normalize_asset_ref_list(
    items: Any,
    *,
    resolution_state: str | None = None,
) -> list[dict[str, Any]]:
    if not isinstance(items, list):
        return []
    normalized_items: list[dict[str, Any]] = []
    for item in items:
        normalized = normalize_asset_ref_item(item, resolution_state=resolution_state)
        if normalized is not None:
            normalized_items.append(normalized)
    return normalized_items


def normalize_asset_ref_item(
    item: Any,
    *,
    resolution_state: str | None = None,
) -> dict[str, Any] | None:
    if not isinstance(item, dict):
        return None

    asset_ref_id = _coalesce_text(
        item.get("asset_ref_id"),
        item.get("photo_ref_id"),
        item.get("attachment_id"),
        item.get("source_item_id"),
        item.get("event_id"),
    )
    normalized: dict[str, Any] = {}
    if asset_ref_id:
        normalized["asset_ref_id"] = asset_ref_id

    for key in (
        "attachment_id",
        "event_id",
        "source_type",
        "source_item_id",
        "original_name",
        "display_name",
        "capture_time",
        "captured_at",
        "occurred_at",
        "kind",
        "resolver_tool",
        "resolution_state",
    ):
        value = item.get(key)
        if value is not None:
            normalized[key] = value

    if resolution_state and "resolution_state" not in normalized:
        normalized["resolution_state"] = resolution_state

    attributes = _sanitize_attributes(item.get("attributes"))
    if attributes:
        normalized["attributes"] = attributes

    return normalized or None


def merge_asset_refs(*asset_ref_groups: list[dict[str, Any]]) -> list[dict[str, Any]]:
    merged: dict[str, dict[str, Any]] = {}
    ordered_keys: list[str] = []
    for group in asset_ref_groups:
        for item in group:
            if not isinstance(item, dict):
                continue
            key = _asset_ref_key(item)
            if not key:
                continue
            if key not in merged:
                merged[key] = dict(item)
                ordered_keys.append(key)
                continue
            merged[key].update(
                {
                    field_name: value
                    for field_name, value in item.items()
                    if value not in (None, "", [], {})
                }
            )
    return [merged[key] for key in ordered_keys]


def _asset_ref_key(item: dict[str, Any]) -> str:
    return _coalesce_text(
        item.get("asset_ref_id"),
        item.get("attachment_id"),
        item.get("source_item_id"),
        item.get("event_id"),
        item.get("original_name"),
    )


def _coalesce_text(*values: Any) -> str:
    for value in values:
        if value is None:
            continue
        normalized = str(value).strip()
        if normalized:
            return normalized
    return ""


def _sanitize_attributes(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict):
        return {}
    sanitized: dict[str, Any] = {}
    for key, item in value.items():
        normalized_key = _coalesce_text(key)
        if not normalized_key:
            continue
        normalized_value = _normalize_attribute_value(item)
        if normalized_value is None:
            continue
        sanitized[normalized_key] = normalized_value
    return sanitized


def _normalize_attribute_value(value: Any) -> Any | None:
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return value
    if isinstance(value, str):
        normalized = value.strip()
        if not normalized:
            return None
        return normalized[:200]
    if isinstance(value, list):
        items: list[Any] = []
        for item in value[:8]:
            normalized_item = _normalize_attribute_value(item)
            if normalized_item is not None:
                items.append(normalized_item)
        return items or None
    return None