"""Helpers for turning persisted runtime trace rows into UI trace nodes."""
from __future__ import annotations

from typing import Any

from .chat_trace_models import ExecutionTraceNode
from .chat_trace_utils import (
    default_trace_label,
    map_trace_kind,
    ms_to_seconds,
    normalize_status,
    parse_json_object,
    parse_json_value,
    safe_int,
)


def resolve_result_preview(
    *,
    span: dict[str, Any],
    llm_call: dict[str, Any] | None,
    tool_call: dict[str, Any] | None,
) -> str:
    preview = str(span.get("result_preview") or "").strip()
    if preview:
        return preview
    if tool_call is not None:
        preview = str(tool_call.get("result_preview") or "").strip()
        if preview:
            return preview
    if llm_call is not None:
        preview = str(llm_call.get("response_preview") or "").strip()
        if preview:
            return preview
    return ""


def build_trace_row_node(
    *,
    span: dict[str, Any],
    llm_call: dict[str, Any] | None,
    tool_call: dict[str, Any] | None,
    intent_resolution: dict[str, Any] | None = None,
) -> ExecutionTraceNode:
    node_type = str(span.get("node_type") or "step")
    metadata = {
        "trace_id": span.get("trace_id"),
        "span_id": span.get("span_id"),
        "parent_span_id": span.get("parent_span_id"),
        "node_type": node_type,
        "attempt_index": safe_int(span.get("attempt_index"), default=1),
        "retry_count": safe_int(span.get("retry_count"), default=0),
        "iteration": safe_int(span.get("iteration"), default=0),
        "duration_ms": safe_int(span.get("duration_ms"), default=0),
        "execution_agent_id": span.get("execution_agent_id"),
    }
    if llm_call is not None:
        metadata.update(
            {
                "provider": llm_call.get("provider"),
                "model": llm_call.get("model"),
                "input_tokens": safe_int(llm_call.get("input_tokens"), default=0),
                "output_tokens": safe_int(llm_call.get("output_tokens"), default=0),
                "reasoning_tokens": safe_int(llm_call.get("reasoning_tokens"), default=0),
                "cache_read_tokens": safe_int(llm_call.get("cache_read_tokens"), default=0),
                "cache_write_tokens": safe_int(llm_call.get("cache_write_tokens"), default=0),
                "thinking_enabled": bool(llm_call.get("thinking_enabled")),
                "request_preview": llm_call.get("request_preview") or None,
                "response_preview": llm_call.get("response_preview") or None,
                "thinking_content": llm_call.get("thinking_content") or None,
            }
        )
    if tool_call is not None:
        metadata.update(
            {
                "tool_call_id": tool_call.get("tool_call_id"),
                "tool_name": tool_call.get("tool_name"),
                "arguments": parse_json_object(tool_call.get("arguments_json")),
                "execution_time": tool_call.get("execution_time_ms"),
                "result_json": parse_json_value(tool_call.get("result_json")),
            }
        )
    if intent_resolution is not None:
        selected_tools = parse_json_value(intent_resolution.get("selected_tools_json"))
        selected_tool_list = selected_tools if isinstance(selected_tools, list) else None
        router_tools = None
        task_hint = None
        recommended_tools = None
        if isinstance(selected_tools, dict):
            selected_tool_list = selected_tools.get("selected_tools") if isinstance(selected_tools.get("selected_tools"), list) else None
            router_tools = selected_tools.get("router_tools") if isinstance(selected_tools.get("router_tools"), list) else None
            task_hint = selected_tools.get("task_hint") if isinstance(selected_tools.get("task_hint"), dict) else None
            recommended_tools = selected_tools.get("recommended_tools") if isinstance(selected_tools.get("recommended_tools"), list) else None
        metadata.update(
            {
                "intent_label": intent_resolution.get("intent") or None,
                "execution_mode": intent_resolution.get("execution_mode") or None,
                "route_reason": intent_resolution.get("route_reason") or None,
                "selected_tools": selected_tool_list,
                "router_tools": router_tools,
                "task_hint": task_hint,
                "recommended_tools": recommended_tools,
                "selected_worker_type": intent_resolution.get("selected_worker_type") or None,
            }
        )

    return ExecutionTraceNode(
        id=str(span.get("span_id") or ""),
        kind=map_trace_kind(node_type),
        label=str(span.get("name") or default_trace_label(node_type)),
        status=normalize_status(str(span.get("status") or "running")),
        started_at=ms_to_seconds(span.get("started_at_ms")),
        ended_at=ms_to_seconds(span.get("ended_at_ms")),
        result_preview=resolve_result_preview(
            span=span,
            llm_call=llm_call,
            tool_call=tool_call,
        ),
        error=str(span.get("error_text") or (tool_call or {}).get("error_message") or "").strip() or None,
        metadata=metadata,
    )