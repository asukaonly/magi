"""Entity, asset, and plugin recall reference projection helpers."""

from __future__ import annotations

from typing import Any

from magi.events.source_activity_snapshot import activity_snapshot_from_metadata

from .entity_display import display_name_for
from .hybrid_retrieval.models import RetrievalPayload


def build_entity_refs(
    payload: RetrievalPayload,
    *,
    plugin_entity_refs: list[dict[str, Any]] | None = None,
    canonical_names: dict[str, str] | None = None,
) -> list[dict[str, Any]]:
    """Build the ``entity_refs`` array for the recall envelope.

    When ``canonical_names`` is provided, each candidate ref's ``entity_id``
    is resolved via the map. If the map has no entry AND the source row has
    no pre-resolved ``canonical_name``/``name``/``label`` field of its own,
    the ref is DROPPED — never rendered with the raw id as a chip label,
    which would otherwise leak entity hashes into the UI surface (the
    original "关系 74f953b57f75" bug).

    When ``canonical_names`` is ``None``, behavior is identical to the
    legacy projection — callers that pre-resolve names on the cards keep
    working unchanged.
    """
    refs: list[dict[str, Any]] = []
    trace = payload.trace if isinstance(payload.trace, dict) else {}
    l2_trace = trace.get("l2_query_trace") if isinstance(trace.get("l2_query_trace"), dict) else {}
    resolved_entities = l2_trace.get("resolved_entities") if isinstance(l2_trace.get("resolved_entities"), list) else []

    for item in [*resolved_entities, *payload.l2_entity_cards]:
        normalized = normalize_entity_ref(item, canonical_names=canonical_names)
        if normalized is not None:
            refs.append(normalized)

    if isinstance(plugin_entity_refs, list):
        for item in plugin_entity_refs:
            if not isinstance(item, dict):
                continue
            if canonical_names is not None:
                # Apply the same resolve-or-drop policy to plugin-supplied
                # refs so a misbehaving plugin cannot reintroduce the leak.
                normalized = normalize_entity_ref(item, canonical_names=canonical_names)
                if normalized is None:
                    continue
                refs.append(normalized)
            else:
                refs.append(item)

    return dedupe_records(refs, primary_key="entity_id")


def build_asset_refs(
    payload: RetrievalPayload,
    *,
    query: str,
    query_mode: str | None,
    plugin_asset_refs: list[dict[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    refs: list[dict[str, Any]] = []
    for event in payload.l1_events:
        normalized = normalize_asset_ref(event)
        if normalized is not None:
            refs.append(normalized)

    if isinstance(plugin_asset_refs, list):
        refs.extend(item for item in plugin_asset_refs if isinstance(item, dict))

    return dedupe_records(refs, primary_key="asset_ref_id")


def build_plugin_recall_artifacts(
    *,
    payload: RetrievalPayload,
    query: str,
    query_mode: str | None,
    plugin_projection_service: Any | None,
) -> dict[str, list[dict[str, Any]]]:
    if plugin_projection_service is None:
        return {"entity_refs": [], "asset_refs": []}
    artifacts = plugin_projection_service.build_recall_artifacts(
        events=payload.l1_events,
        query=query,
        query_mode=query_mode,
    )
    if not isinstance(artifacts, dict):
        return {"entity_refs": [], "asset_refs": []}
    return {
        "entity_refs": [item for item in artifacts.get("entity_refs", []) if isinstance(item, dict)],
        "asset_refs": [item for item in artifacts.get("asset_refs", []) if isinstance(item, dict)],
    }


def normalize_entity_ref(
    item: Any,
    *,
    canonical_names: dict[str, str] | None = None,
) -> dict[str, Any] | None:
    """Normalize a single entity ref candidate into the rendered shape.

    When ``canonical_names`` is provided, the display name is resolved via
    :func:`magi.memory.entity_display.display_name_for` (catalog → slug →
    ``(未命名 {type})``) with any pre-resolved upstream name field taking
    precedence over the slug/未命名 fallbacks. A ref is DROPPED (returns
    ``None``) only when no source produces any name — preserving Phase 5's
    safety invariant against rendering raw hashes as chip labels.

    When ``canonical_names`` is ``None`` the legacy fallback chain is
    preserved for backward compatibility.
    """
    if not isinstance(item, dict):
        return None
    entity_id = str(item.get("entity_id") or item.get("resolved_entity_id") or "").strip()
    if not entity_id:
        return None
    entity_type = str(item.get("entity_type") or _type_from_entity_id(entity_id) or "").strip() or None
    pre_canonical = str(item.get("canonical_name") or item.get("name") or item.get("label") or "").strip() or None

    if canonical_names is not None:
        # Round 4: catalog name wins, else pre-resolved upstream name (richer
        # than slug), else slug / '(未命名 {type})' via display_name_for.
        # Drop only when none of these produce a usable display string —
        # which now requires the id to lack a 'type:slug' shape entirely.
        if entity_id in canonical_names:
            canonical_name = canonical_names[entity_id]
        else:
            canonical_name = pre_canonical or display_name_for(entity_id, canonical_names)
        if not canonical_name:
            return None
    else:
        canonical_name = pre_canonical

    match_source = str(item.get("match_source") or "").strip() or None
    normalized: dict[str, Any] = {"entity_id": entity_id}
    if entity_type is not None:
        normalized["entity_type"] = entity_type
    if canonical_name is not None:
        normalized["canonical_name"] = canonical_name
    if match_source is not None:
        normalized["match_source"] = match_source
    return normalized


def normalize_asset_ref(item: Any) -> dict[str, Any] | None:
    if not isinstance(item, dict):
        return None
    metadata = item.get("metadata_json") if isinstance(item.get("metadata_json"), dict) else {}
    activity_snapshot = activity_snapshot_from_metadata(metadata)
    provenance = (
        activity_snapshot.get("provenance")
        if isinstance(activity_snapshot.get("provenance"), dict)
        else {}
    )

    source_type = str(activity_snapshot.get("source_type") or item.get("source") or "").strip()
    source_item_id = str(
        activity_snapshot.get("source_item_id")
        or item.get("source_item_id")
        or item.get("idempotency_key")
        or ""
    ).strip()
    asset_ref_id = str(
        activity_snapshot.get("asset_ref_id")
        or source_item_id
        or item.get("event_id")
        or ""
    ).strip()
    media_path = str(item.get("media_path") or "").strip()
    if not asset_ref_id and not media_path:
        return None

    kind = str(
        activity_snapshot.get("kind")
        or provenance.get("kind")
        or item.get("content_type")
        or ("file" if media_path else "")
    ).strip()
    if kind == "text":
        return None
    if not kind:
        kind = "file"

    normalized: dict[str, Any] = {
        "asset_ref_id": asset_ref_id or media_path,
        "kind": kind,
        "event_id": str(item.get("event_id") or "").strip() or None,
        "source_type": source_type or None,
        "source_item_id": source_item_id or None,
        "original_name": str(
            provenance.get("filename")
            or activity_snapshot.get("original_name")
            or activity_snapshot.get("title")
            or ""
        ).strip() or None,
        "display_name": str(
            activity_snapshot.get("title")
            or provenance.get("filename")
            or item.get("content")
            or ""
        ).strip() or None,
        "captured_at": (
            provenance.get("captured_at")
            or activity_snapshot.get("captured_at")
            or item.get("timestamp")
        ),
        "occurred_at": item.get("timestamp") or item.get("created_at"),
    }
    attributes = safe_asset_attributes(activity_snapshot, provenance)
    if attributes:
        normalized["attributes"] = attributes
    return {key: value for key, value in normalized.items() if value is not None}


def safe_asset_attributes(*mappings: Any) -> dict[str, Any]:
    blocked_keys = {
        "asset_ref_id",
        "source_type",
        "source_item_id",
        "event_id",
        "title",
        "summary",
        "content",
        "kind",
        "filename",
        "original_name",
        "file_path",
        "storage_path",
        "media_path",
        "resolver_tool",
        "captured_at",
        "occurred_at",
    }
    attributes: dict[str, Any] = {}
    for mapping in mappings:
        if not isinstance(mapping, dict):
            continue
        for key, value in mapping.items():
            normalized_key = str(key or "").strip()
            if not normalized_key or normalized_key in blocked_keys:
                continue
            safe_value = coerce_safe_attribute_value(value)
            if safe_value is None:
                continue
            attributes.setdefault(normalized_key, safe_value)
    return attributes


def coerce_safe_attribute_value(value: Any) -> Any | None:
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
        for entry in value[:8]:
            coerced = coerce_safe_attribute_value(entry)
            if coerced is not None:
                items.append(coerced)
        return items or None
    return None


def dedupe_records(items: list[dict[str, Any]], *, primary_key: str) -> list[dict[str, Any]]:
    merged: dict[str, dict[str, Any]] = {}
    ordered_keys: list[str] = []
    for item in items:
        key = str(item.get(primary_key) or "").strip()
        if not key:
            continue
        if key not in merged:
            merged[key] = dict(item)
            ordered_keys.append(key)
            continue
        merged[key].update({name: value for name, value in item.items() if value not in (None, "", [], {})})
    return [merged[key] for key in ordered_keys]


def _type_from_entity_id(entity_id: str) -> str | None:
    normalized = str(entity_id or "").strip()
    if ":" not in normalized:
        return None
    prefix, _, _ = normalized.partition(":")
    return prefix or None
