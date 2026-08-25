"""Enrich canonical run-event projections with normalized trace details."""

from __future__ import annotations

from collections import defaultdict, deque
from typing import Any, Iterator

from .builders.rows import build_trace_row_node
from .models import ExecutionTraceNode, ExecutionTraceSnapshot
from .tree import redact_cancelled_response_drafts
from .utils import safe_int

_LLM_DETAIL_KEYS = {
    "trace_id",
    "span_id",
    "parent_span_id",
    "attempt_index",
    "retry_count",
    "iteration",
    "duration_ms",
    "execution_agent_id",
    "provider",
    "model",
    "input_tokens",
    "output_tokens",
    "reasoning_tokens",
    "cache_read_tokens",
    "cache_write_tokens",
    "request_preview",
    "response_preview",
    "thinking_content",
    "input",
    "output",
}
_TOOL_DETAIL_KEYS = {
    "trace_id",
    "span_id",
    "parent_span_id",
    "attempt_index",
    "retry_count",
    "iteration",
    "duration_ms",
    "execution_agent_id",
    "tool_call_id",
    "tool_name",
    "arguments",
    "execution_time",
    "result_json",
    "input",
    "output",
}
_DETAIL_OVERRIDE_KEYS = {
    "trace_id",
    "span_id",
    "parent_span_id",
    "iteration",
    "duration_ms",
    "request_preview",
    "response_preview",
    "execution_time",
    "result_json",
    "input",
    "output",
}


def enrich_projected_trace(
    snapshot: ExecutionTraceSnapshot,
    *,
    spans: list[dict[str, Any]],
    llm_calls: list[dict[str, Any]],
    tool_calls: list[dict[str, Any]],
) -> tuple[int, int]:
    """Merge detail rows into canonical nodes without changing lifecycle truth.

    Canonical run events own hierarchy and status. Normalized trace rows own
    request/response previews and provider execution details.
    """

    span_by_id = {
        str(span.get("span_id") or "").strip(): span
        for span in spans
        if str(span.get("span_id") or "").strip()
    }
    llm_by_span = {
        str(item.get("span_id") or "").strip(): item
        for item in llm_calls
        if str(item.get("span_id") or "").strip()
    }
    tool_by_span = {
        str(item.get("span_id") or "").strip(): item
        for item in tool_calls
        if str(item.get("span_id") or "").strip()
    }

    llm_details: list[tuple[int | None, ExecutionTraceNode]] = []
    tool_details: dict[str, ExecutionTraceNode] = {}
    for span in spans:
        span_id = str(span.get("span_id") or "").strip()
        llm_call = llm_by_span.get(span_id)
        tool_call = tool_by_span.get(span_id)
        if llm_call is None and tool_call is None:
            continue
        detail = build_trace_row_node(
            span=span,
            llm_call=llm_call,
            tool_call=tool_call,
        )
        iteration = _resolve_iteration(span=span, span_by_id=span_by_id)
        if iteration is not None:
            detail.metadata["iteration"] = iteration
        if llm_call is not None:
            llm_details.append((iteration, detail))
        if tool_call is not None:
            call_id = str(tool_call.get("tool_call_id") or "").strip()
            if call_id:
                tool_details[call_id] = detail

    llm_by_iteration: dict[int, deque[ExecutionTraceNode]] = defaultdict(deque)
    for iteration, detail in llm_details:
        if iteration is not None:
            llm_by_iteration[iteration].append(detail)
    unused_llm = deque(detail for _, detail in llm_details)
    merged_llm_ids: set[str] = set()
    merged_llm = 0
    merged_tools = 0

    for node, step_index in _walk_with_step(snapshot.root.children):
        if node.kind == "llm":
            detail = _take_llm_detail(
                step_index=step_index,
                by_iteration=llm_by_iteration,
                fallback=unused_llm,
                used=merged_llm_ids,
            )
            if detail is not None:
                _merge_detail(node, detail, allowed_keys=_LLM_DETAIL_KEYS)
                merged_llm += 1
        elif node.kind == "tool":
            call_id = str(node.metadata.get("tool_call_id") or "").strip()
            detail = tool_details.get(call_id)
            if detail is not None:
                _merge_detail(node, detail, allowed_keys=_TOOL_DETAIL_KEYS)
                merged_tools += 1

    redact_cancelled_response_drafts(snapshot.root)
    return merged_llm, merged_tools


def _walk_with_step(
    nodes: list[ExecutionTraceNode],
    step_index: int | None = None,
) -> Iterator[tuple[ExecutionTraceNode, int | None]]:
    for node in nodes:
        current_step = step_index
        if node.kind == "attempt":
            value = safe_int(node.metadata.get("step_index"), default=0)
            current_step = value if value > 0 else None
        yield node, current_step
        yield from _walk_with_step(node.children, current_step)


def _resolve_iteration(
    *,
    span: dict[str, Any],
    span_by_id: dict[str, dict[str, Any]],
) -> int | None:
    current = span
    visited: set[str] = set()
    while current:
        iteration = safe_int(current.get("iteration"), default=0)
        if iteration > 0:
            return iteration
        parent_id = str(current.get("parent_span_id") or "").strip()
        if not parent_id or parent_id in visited:
            return None
        visited.add(parent_id)
        current = span_by_id.get(parent_id, {})
    return None


def _take_llm_detail(
    *,
    step_index: int | None,
    by_iteration: dict[int, deque[ExecutionTraceNode]],
    fallback: deque[ExecutionTraceNode],
    used: set[str],
) -> ExecutionTraceNode | None:
    if step_index is not None:
        candidates = by_iteration.get(step_index)
        while candidates:
            detail = candidates.popleft()
            if detail.id not in used:
                used.add(detail.id)
                return detail
    while fallback:
        detail = fallback.popleft()
        if detail.id not in used:
            used.add(detail.id)
            return detail
    return None


def _merge_detail(
    node: ExecutionTraceNode,
    detail: ExecutionTraceNode,
    *,
    allowed_keys: set[str],
) -> None:
    if detail.started_at is not None:
        node.started_at = detail.started_at
    if detail.ended_at is not None:
        node.ended_at = detail.ended_at
    if detail.result_preview:
        node.result_preview = detail.result_preview
    if detail.error and not node.error:
        node.error = detail.error
    for key in allowed_keys:
        value = detail.metadata.get(key)
        if value is None or value == "":
            continue
        current_value = node.metadata.get(key)
        if (
            key in _DETAIL_OVERRIDE_KEYS
            or key not in node.metadata
            or current_value is None
            or current_value == ""
        ):
            node.metadata[key] = value


__all__ = ["enrich_projected_trace"]
