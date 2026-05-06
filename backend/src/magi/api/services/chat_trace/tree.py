"""Runtime trace tree helpers for chat trace read models."""

from __future__ import annotations

from typing import Any

from .models import ExecutionTraceNode
from .builders.rows import build_trace_row_node
from .utils import derive_children_status, is_terminal_status, ms_to_seconds


def _safe_ms(value: Any) -> int:
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0


def _contains_span(parent: dict[str, Any], child: dict[str, Any]) -> bool:
    child_started = _safe_ms(child.get("started_at_ms"))
    if not child_started:
        return False
    parent_started = _safe_ms(parent.get("started_at_ms"))
    parent_ended = _safe_ms(parent.get("ended_at_ms")) or child_started
    return parent_started <= child_started <= parent_ended


def _find_iteration_parent(span: dict[str, Any], spans: list[dict[str, Any]]) -> str | None:
    candidates = [
        item
        for item in spans
        if str(item.get("node_type") or "") == "iteration" and _contains_span(item, span)
    ]
    candidates.sort(key=lambda item: _safe_ms(item.get("started_at_ms")), reverse=True)
    if not candidates:
        return None
    return str(candidates[0].get("span_id") or "").strip() or None


def _find_semantic_tool_parent(span: dict[str, Any], spans: list[dict[str, Any]]) -> str | None:
    tool_name = str(span.get("name") or "").strip()
    span_started = _safe_ms(span.get("started_at_ms"))
    matches = []
    for item in spans:
        if str(item.get("node_type") or "") != "tool_call":
            continue
        item_name = str(item.get("name") or "").strip()
        if tool_name and not item_name.startswith(tool_name):
            continue
        if abs(_safe_ms(item.get("started_at_ms")) - span_started) <= 250:
            matches.append(item)
    matches.sort(key=lambda item: abs(_safe_ms(item.get("started_at_ms")) - span_started))
    if not matches:
        return None
    return str(matches[0].get("span_id") or "").strip() or None


def _effective_parent_span_id(
    span: dict[str, Any], *, spans: list[dict[str, Any]], turn_span_id: str
) -> str | None:
    parent_span_id = str(span.get("parent_span_id") or "").strip() or None
    node_type = str(span.get("node_type") or "")
    if parent_span_id not in {None, turn_span_id}:
        return parent_span_id
    if node_type == "llm_call":
        return _find_iteration_parent(span, spans) or parent_span_id
    if node_type == "tool_invocation":
        return (
            _find_semantic_tool_parent(span, spans)
            or _find_iteration_parent(span, spans)
            or parent_span_id
        )
    return parent_span_id


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
        parent_span_id = _effective_parent_span_id(
            span,
            spans=spans,
            turn_span_id=turn_span_id,
        )
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
    return root


def reshape_orchestration_trace_root(root: ExecutionTraceNode) -> ExecutionTraceNode:
    if root.kind != "root" or not root.children:
        return root

    planning_children: list[ExecutionTraceNode] = []
    preserved_children: list[ExecutionTraceNode] = []
    planning_insert_index: int | None = None
    hidden_iteration_count = 0

    for child in root.children:
        if child.kind == "dispatch":
            if planning_insert_index is None:
                planning_insert_index = len(preserved_children)
            planning_children.append(with_dispatch_label(child))
            continue
        if child.kind == "iteration":
            if planning_insert_index is None:
                planning_insert_index = len(preserved_children)
            hidden_iteration_count += 1
            continue
        preserved_children.append(child)

    if not planning_children:
        return root

    started_at = min(
        (node.started_at for node in planning_children if node.started_at is not None),
        default=root.started_at,
    )
    ended_candidates = [node.ended_at for node in planning_children if node.ended_at is not None]
    planning_status = derive_children_status(planning_children)
    planning_node = ExecutionTraceNode(
        id=f"{root.id}:planning",
        kind="planning",
        label="Task orchestration",
        status=planning_status,
        started_at=started_at,
        ended_at=(
            max(ended_candidates)
            if ended_candidates and is_terminal_status(planning_status)
            else None
        ),
        metadata={
            "synthetic": True,
            "hidden_iteration_count": hidden_iteration_count,
        },
        children=planning_children,
    )

    insert_at = (
        planning_insert_index if planning_insert_index is not None else len(preserved_children)
    )
    preserved_children.insert(insert_at, planning_node)
    root.children = preserved_children
    return root


def with_dispatch_label(node: ExecutionTraceNode) -> ExecutionTraceNode:
    description = (node.result_preview or "").strip()
    label = description or node.label
    return ExecutionTraceNode(
        id=node.id,
        kind=node.kind,
        label=label,
        status=node.status,
        started_at=node.started_at,
        ended_at=node.ended_at,
        result_preview="" if description and label == description else node.result_preview,
        error=node.error,
        metadata={**node.metadata, "dispatch_label": label},
        children=node.children,
    )


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
