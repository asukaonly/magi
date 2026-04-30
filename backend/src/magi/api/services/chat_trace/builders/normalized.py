"""Builders for normalized chat trace event payloads."""
from __future__ import annotations

from typing import Any, Optional

from ..models import ExecutionTraceNode
from ..utils import (
    default_trace_label,
    derive_children_status,
    map_trace_kind,
    ms_to_seconds,
    normalize_status,
    safe_int,
    trace_span_error,
    trace_span_result_preview,
)


def build_normalized_trace_root(
    *,
    turn_id: str,
    events: list[dict[str, Any]],
    started_at: float,
    ended_at: float,
    trace_node_event_types: tuple[str, ...],
) -> Optional[ExecutionTraceNode]:
    span_payloads = collapse_trace_spans(events, trace_node_event_types=trace_node_event_types)
    if not span_payloads:
        return None

    node_by_span_id: dict[str, ExecutionTraceNode] = {}
    children_by_parent: dict[str | None, list[str]] = {}
    for span_id, payload in span_payloads.items():
        node_by_span_id[span_id] = build_trace_span_node(payload)
        parent_span_id = str(payload.get("parent_span_id") or "").strip() or None
        children_by_parent.setdefault(parent_span_id, []).append(span_id)

    for parent_span_id, child_ids in children_by_parent.items():
        if parent_span_id is None:
            continue
        parent = node_by_span_id.get(parent_span_id)
        if parent is None:
            continue
        ordered_children = sorted(
            (node_by_span_id[child_id] for child_id in child_ids if child_id in node_by_span_id),
            key=lambda item: (
                float(item.started_at or 0.0),
                item.id,
            ),
        )
        parent.children.extend(ordered_children)

    turn_span_id = f"{turn_id}:turn"
    turn_node = node_by_span_id.get(turn_span_id)
    top_level_nodes = [
        node_by_span_id[span_id]
        for span_id in children_by_parent.get(None, [])
        if span_id in node_by_span_id and span_id != turn_span_id
    ]
    top_level_nodes.sort(key=lambda item: (float(item.started_at or 0.0), item.id))

    root = ExecutionTraceNode(
        id=f"{turn_id}:root",
        kind="root",
        label="Tool chain",
        status=turn_node.status if turn_node is not None else derive_children_status(top_level_nodes),
        started_at=turn_node.started_at if turn_node is not None else started_at,
        ended_at=turn_node.ended_at if turn_node is not None else ended_at,
        result_preview=turn_node.result_preview if turn_node is not None else "",
        error=turn_node.error if turn_node is not None else None,
        metadata={
            "turn_id": turn_id,
            "trace_id": str((turn_node.metadata if turn_node is not None else {}).get("trace_id") or f"trace:{turn_id}"),
            "normalized_trace": True,
        },
    )
    if turn_node is not None:
        root.children.extend(turn_node.children)
    root.children.extend(top_level_nodes)
    return root


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