"""Neutral activity snapshots derived from source event payloads."""
from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from magi.events.domain_payloads import SourceEventEmitted


ACTIVITY_SNAPSHOT_METADATA_KEY = "activity_snapshot"


def build_source_activity_snapshot(
    payload: SourceEventEmitted,
    *,
    event_id: str,
) -> dict[str, Any]:
    """Build a neutral activity snapshot from source payload context."""
    output = payload.output_dict or {}
    metadata = payload.metadata_dict or {}
    projection = payload.projection_dict or {}
    extra_entities = metadata.get("entities") or []
    extra_tags = metadata.get("tags") or []
    domain_payload = output.get("domain_payload") or {}

    return {
        "event_id": event_id,
        "source_type": output.get("source_type", ""),
        "source_item_id": output.get("source_item_id", ""),
        "occurred_at": float(output.get("occurred_at", 0.0)),
        "captured_at": float(output.get("captured_at", 0.0)),
        "title": projection.get("title", ""),
        "summary": projection.get("summary", ""),
        "retention_mode": domain_payload.get("retention_mode", "analyze_only"),
        "raw_payload_ref": output.get("raw_payload_ref"),
        "content_blocks": list(output.get("content_blocks", [])),
        "entities": list(output.get("entities", [])) + list(extra_entities),
        "tags": list(dict.fromkeys(list(output.get("tags", [])) + list(extra_tags))),
        "privacy_labels": list(domain_payload.get("privacy_labels", [])),
        "processing_status": {
            "stored": True,
            "analyzed": bool(metadata.get("relation_candidates") or metadata.get("fact_hints")),
        },
        "provenance": dict(output.get("provenance") or {}),
    }


def activity_snapshot_from_metadata(metadata: Mapping[str, Any] | None) -> Mapping[str, Any]:
    """Return the neutral activity snapshot embedded in memory metadata."""
    if not isinstance(metadata, Mapping):
        return {}
    snapshot = metadata.get(ACTIVITY_SNAPSHOT_METADATA_KEY)
    return snapshot if isinstance(snapshot, Mapping) else {}
