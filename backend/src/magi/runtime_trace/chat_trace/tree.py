"""Runtime trace tree helpers for chat trace read models."""

from __future__ import annotations

from typing import Any

from .models import ExecutionTraceNode
from .builders.rows import build_trace_row_node
from .utils import ms_to_seconds


def build_runtime_trace_root(
    *,
    turn: dict[str, Any],
    spans: list[dict[str, Any]],
    llm_calls: list[dict[str, Any]],
    tool_calls: list[dict[str, Any]],
    intent_resolutions: list[dict[str, Any]],
) -> ExecutionTraceNode:
    turn_id = str(turn.get("turn_id") or "")
    llm_by_span = {str(item.get("span_id") or ""): item for item in llm_calls}
    tool_by_span = {str(item.get("span_id") or ""): item for item in tool_calls}
    intent_by_span = {str(item.get("span_id") or ""): item for item in intent_resolutions}
    node_by_span_id: dict[str, ExecutionTraceNode] = {}
    children_by_parent: dict[str | None, list[str]] = {}
    turn_span_id = f"{turn_id}:turn"
    for span in spans:
        span_id = str(span.get("span_id") or "").strip()
        if not span_id:
            continue
        node_by_span_id[span_id] = build_trace_row_node(
            span=span,
            llm_call=llm_by_span.get(span_id),
            tool_call=tool_by_span.get(span_id),
            intent_resolution=intent_by_span.get(span_id),
        )
        parent_span_id = str(span.get("parent_span_id") or "").strip() or None
        children_by_parent.setdefault(parent_span_id, []).append(span_id)

    for parent_span_id, child_ids in children_by_parent.items():
        if parent_span_id is None:
            continue
        parent = node_by_span_id.get(parent_span_id)
        if parent is None:
            continue
        ordered_children = sorted(
            (node_by_span_id[child_id] for child_id in child_ids if child_id in node_by_span_id),
            key=lambda item: (float(item.started_at or 0.0), item.id),
        )
        parent.children.extend(ordered_children)

    turn_node = node_by_span_id.get(turn_span_id)
    top_level_span_ids = set(children_by_parent.get(None, []))
    if turn_node is None:
        top_level_span_ids.update(children_by_parent.get(turn_span_id, []))
    top_level_nodes = [
        node_by_span_id[span_id]
        for span_id in top_level_span_ids
        if span_id in node_by_span_id and span_id != turn_span_id
    ]
    top_level_nodes.sort(key=lambda item: (float(item.started_at or 0.0), item.id))

    root = ExecutionTraceNode(
        id=f"{turn_id}:root",
        kind="root",
        label="Tool chain",
        status=str(turn.get("status") or "running"),
        started_at=ms_to_seconds(turn.get("started_at_ms")),
        ended_at=ms_to_seconds(turn.get("ended_at_ms")),
        result_preview=str(turn.get("response_preview") or ""),
        error=str(turn.get("error_summary") or "").strip() or None,
        metadata={
            "turn_id": turn_id,
            "trace_id": str(turn.get("trace_id") or f"trace:{turn_id}"),
            "normalized_trace": True,
        },
    )
    if turn_node is not None:
        root.children.extend(turn_node.children)
    root.children.extend(top_level_nodes)
    deduplicate_response_emit(root)
    redact_cancelled_response_drafts(root)
    return root


def deduplicate_response_emit(root: ExecutionTraceNode) -> None:
    if len(root.children) < 2:
        return
    last = root.children[-1]
    if last.kind != "response":
        return
    previous = root.children[-2]
    last_preview = (last.result_preview or "").strip()[:200]
    previous_preview = (previous.result_preview or "").strip()[:200]
    if last_preview and previous_preview and last_preview == previous_preview:
        root.children.pop()


def redact_cancelled_response_drafts(root: ExecutionTraceNode) -> None:
    """Keep an uncommitted assistant draft out of a cancelled trace."""

    if str(root.status or "").strip().lower() != "cancelled":
        return
    root.result_preview = ""

    def _redact_children(
        children: list[ExecutionTraceNode],
    ) -> list[ExecutionTraceNode]:
        redacted: list[ExecutionTraceNode] = []
        for node in children:
            if node.kind in {"response", "rhythm"}:
                continue
            if node.kind in {"llm", "iteration"}:
                node.result_preview = ""
                metadata = dict(node.metadata)
                for key in (
                    "output",
                    "output_preview",
                    "response_preview",
                    "thinking_content",
                ):
                    metadata.pop(key, None)
                node.metadata = metadata
            node.children = _redact_children(node.children)
            redacted.append(node)
        return redacted

    root.children = _redact_children(root.children)
