"""Builders for normalized chat trace event payloads."""
from __future__ import annotations

from typing import Any

from ..models import ExecutionTraceNode
from ..utils import (
    default_trace_label,
    map_trace_kind,
    ms_to_seconds,
    normalize_status,
    safe_int,
    trace_span_error,
    trace_span_result_preview,
)


def collapse_trace_spans(
    events: list[dict[str, Any]],
    *,
    trace_node_event_types: tuple[str, ...],
) -> dict[str, dict[str, Any]]:
    span_payloads: dict[str, dict[str, Any]] = {}
    for item in events:
        if item["type"] not in trace_node_event_types:
            continue
        payload = item.get("payload", {})
        if not isinstance(payload, dict):
            continue
        span_id = str(payload.get("span_id") or "").strip()
        if not span_id:
            continue
        current = span_payloads.setdefault(span_id, {})
        merge_trace_payload(current, payload)
    return span_payloads


def merge_trace_payload(current: dict[str, Any], incoming: dict[str, Any]) -> None:
    for key in (
        "trace_id",
        "turn_id",
        "span_id",
        "parent_span_id",
        "node_type",
        "name",
        "status",
        "attempt_index",
        "retry_count",
        "started_at_ms",
        "ended_at_ms",
        "duration_ms",
    ):
        value = incoming.get(key)
        if value is not None and value != "":
            current[key] = value

    for key in ("input", "output", "metrics", "tags"):
        incoming_value = incoming.get(key)
        if not isinstance(incoming_value, dict):
            continue
        merged = dict(current.get(key) or {})
        merged.update(incoming_value)
        current[key] = merged

    if incoming.get("error") is not None:
        current["error"] = incoming.get("error")


def build_trace_span_node(payload: dict[str, Any]) -> ExecutionTraceNode:
    span_id = str(payload.get("span_id") or "")
    node_type = str(payload.get("node_type") or "step")
    status = normalize_status(str(payload.get("status") or "running"))
    metadata = {
        "trace_id": payload.get("trace_id"),
        "span_id": span_id,
        "parent_span_id": payload.get("parent_span_id"),
        "node_type": node_type,
        "attempt_index": safe_int(payload.get("attempt_index"), default=1),
        "retry_count": safe_int(payload.get("retry_count"), default=0),
        "duration_ms": safe_int(payload.get("duration_ms"), default=0),
        "input": dict(payload.get("input") or {}) if isinstance(payload.get("input"), dict) else {},
        "output": dict(payload.get("output") or {}) if isinstance(payload.get("output"), dict) else {},
        "metrics": dict(payload.get("metrics") or {}) if isinstance(payload.get("metrics"), dict) else {},
        "tags": dict(payload.get("tags") or {}) if isinstance(payload.get("tags"), dict) else {},
    }
    return ExecutionTraceNode(
        id=span_id,
        kind=map_trace_kind(node_type),
        label=str(payload.get("name") or default_trace_label(node_type)),
        status=status,
        started_at=ms_to_seconds(payload.get("started_at_ms")),
        ended_at=ms_to_seconds(payload.get("ended_at_ms")),
        result_preview=trace_span_result_preview(payload),
        error=trace_span_error(payload),
        metadata=metadata,
    )
