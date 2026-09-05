"""Verbose retrieval debug logging helpers.

These helpers intentionally emit rich, user-data-bearing records. They are
temporary investigation aids for retrieval debugging and should not become the
default observability contract.
"""

from __future__ import annotations

import datetime as _dt
import json
import logging
from typing import Any, Iterable

from magi.utils.diagnostic_logging import full_content_logging_enabled
from magi.events.source_activity_snapshot import activity_snapshot_from_metadata


DETAIL_LIMIT = 120


def log_detail(logger: logging.Logger, message: str, payload: dict[str, Any]) -> None:
    """Emit a JSON payload at INFO level for grep-friendly retrieval tracing."""
    if not full_content_logging_enabled():
        logger.info(
            "%s | detail omitted by diagnostics setting | fields=%s",
            message,
            sorted(str(key) for key in payload),
        )
        return
    logger.info("%s | detail=%s", message, to_json(payload))


def to_json(payload: Any) -> str:
    return json.dumps(payload, ensure_ascii=False, default=_json_default)


def event_record(
    event: dict[str, Any] | None,
    *,
    rank: int | None = None,
    path: str | None = None,
    path_rank: int | None = None,
    path_score: float | None = None,
    fused_score: float | None = None,
) -> dict[str, Any]:
    """Return a stable debug shape for an L1 event row."""
    if not isinstance(event, dict):
        return {"rank": rank, "path": path, "missing": True}

    metadata = event.get("metadata_json")
    metadata_text = _metadata_text(metadata)
    trace = event.get("retrieval_trace") if isinstance(event.get("retrieval_trace"), dict) else {}
    matched_chunks = event.get("matched_chunks") if isinstance(event.get("matched_chunks"), list) else []

    return _drop_empty({
        "rank": rank,
        "path": path,
        "path_rank": path_rank,
        "path_score": path_score,
        "fused_score": fused_score,
        "event_id": event.get("event_id"),
        "timestamp": event.get("timestamp"),
        "when": _format_when(event.get("timestamp")),
        "event_type": event.get("event_type"),
        "source": event.get("source"),
        "source_item_id": event.get("source_item_id"),
        "user_id": event.get("user_id"),
        "session_id": event.get("session_id"),
        "memory_domain": event.get("memory_domain"),
        "evidence_class": event.get("evidence_class"),
        "l1_retrieval_scope": event.get("l1_retrieval_scope"),
        "importance_score": event.get("importance_score"),
        "retrieval_score": event.get("retrieval_score"),
        "reranker_score": event.get("reranker_score"),
        "distance": event.get("distance"),
        "event_object_chars": len(str(event)),
        "field_char_sizes": {
            key: len(str(value))
            for key, value in event.items()
            if len(str(value)) > 500
        },
        "content_chars": len(str(event.get("content") or "")),
        "content": event.get("content"),
        "metadata_json_chars": len(metadata_text),
        "metadata_summary": _metadata_summary(metadata),
        "media_path": event.get("media_path"),
        "matched_chunks": [
            _drop_empty({
                "chunk_id": chunk.get("chunk_id"),
                "chunk_index": chunk.get("chunk_index"),
                "distance": chunk.get("distance"),
                "text": chunk.get("text"),
            })
            for chunk in matched_chunks[:8]
            if isinstance(chunk, dict)
        ],
        "retrieval_trace": trace,
    })


def event_records(
    events: Iterable[dict[str, Any]],
    *,
    path: str | None = None,
    limit: int = DETAIL_LIMIT,
) -> list[dict[str, Any]]:
    return [
        event_record(event, rank=index, path=path)
        for index, event in enumerate(list(events)[:limit], start=1)
    ]


def relationship_record(rel: dict[str, Any], *, rank: int | None = None) -> dict[str, Any]:
    return _drop_empty({
        "rank": rank,
        "triple_id": rel.get("triple_id") or rel.get("id"),
        "subject_id": rel.get("subject_id"),
        "subject_name": rel.get("subject_name"),
        "predicate": rel.get("predicate"),
        "object_id": rel.get("object_id"),
        "object_name": rel.get("object_name"),
        "confidence": rel.get("confidence"),
        "natural_summary": rel.get("natural_summary"),
        "evidence_text": rel.get("evidence_text"),
    })


def relationship_records(rels: Iterable[dict[str, Any]], *, limit: int = DETAIL_LIMIT) -> list[dict[str, Any]]:
    return [
        relationship_record(rel, rank=index)
        for index, rel in enumerate(list(rels)[:limit], start=1)
    ]


def _metadata_summary(metadata_value: Any) -> dict[str, Any] | None:
    metadata_text = _metadata_text(metadata_value)
    if not metadata_text and not isinstance(metadata_value, dict):
        return None
    if isinstance(metadata_value, dict):
        metadata = metadata_value
    else:
        try:
            metadata = json.loads(metadata_text)
        except Exception:
            return {"parse_error": True, "preview": metadata_text[:1000]}
    if not isinstance(metadata, dict):
        return {"type": type(metadata).__name__}

    representative_photos = metadata.get("representative_photos")
    if not isinstance(representative_photos, list):
        representative_photos = []
    activity_snapshot = activity_snapshot_from_metadata(metadata)
    provenance = (
        activity_snapshot.get("provenance")
        if isinstance(activity_snapshot.get("provenance"), dict)
        else {}
    )
    return _drop_empty({
        "plugin_id": metadata.get("plugin_id"),
        "source_id": metadata.get("source_id"),
        "photo_count": provenance.get("photo_count"),
        "location_name": provenance.get("location_name"),
        "apple_photos_place_name": provenance.get("apple_photos_place_name"),
        "apple_photos_place_address": provenance.get("apple_photos_place_address"),
        "device_name": provenance.get("device_name"),
        "representative_photos": [
            _drop_empty({
                "asset_local_id": photo.get("asset_local_id"),
                "path": photo.get("path"),
                "capture_ts": photo.get("capture_ts"),
                "location_name": photo.get("location_name"),
                "latitude": photo.get("latitude"),
                "longitude": photo.get("longitude"),
            })
            for photo in representative_photos[:5]
            if isinstance(photo, dict)
        ],
    })


def _metadata_text(metadata_value: Any) -> str:
    if isinstance(metadata_value, str):
        return metadata_value
    if isinstance(metadata_value, dict):
        return json.dumps(metadata_value, ensure_ascii=False, default=_json_default)
    return ""


def _format_when(ts: Any) -> str | None:
    if not isinstance(ts, (int, float)):
        return None
    try:
        return _dt.datetime.fromtimestamp(float(ts)).strftime("%Y-%m-%d %H:%M:%S")
    except (OSError, OverflowError, ValueError):
        return None


def _json_default(value: Any) -> str:
    return repr(value)


def _drop_empty(payload: dict[str, Any]) -> dict[str, Any]:
    return {
        key: value
        for key, value in payload.items()
        if value not in (None, "", [], {})
    }
