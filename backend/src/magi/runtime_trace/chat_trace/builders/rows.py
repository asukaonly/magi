"""Helpers for turning persisted runtime trace rows into UI trace nodes."""

from __future__ import annotations

from typing import Any

from ..models import ExecutionTraceNode
from ..utils import (
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


def _base_metadata(span: dict[str, Any], node_type: str) -> dict[str, Any]:
    return {
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


def _apply_span_previews(metadata: dict[str, Any], span: dict[str, Any]) -> None:
    input_preview = str(span.get("input_preview") or "").strip()
    output_preview = str(span.get("output_preview") or "").strip()
    if input_preview:
        metadata["input"] = {"preview": input_preview}
    if output_preview:
        metadata["output"] = {"preview": output_preview}


def _apply_llm_metadata(metadata: dict[str, Any], llm_call: dict[str, Any]) -> None:
    request_preview = str(llm_call.get("request_preview") or "").strip()
    response_preview = str(llm_call.get("response_preview") or "").strip()
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
            "request_preview": request_preview or None,
            "response_preview": response_preview or None,
            "thinking_content": llm_call.get("thinking_content") or None,
        }
    )
    if request_preview:
        metadata["input"] = {"preview": request_preview}
    if response_preview:
        metadata["output"] = {"preview": response_preview}


def _apply_tool_metadata(metadata: dict[str, Any], tool_call: dict[str, Any]) -> None:
    metadata.update(
        {
            "tool_call_id": tool_call.get("tool_call_id"),
            "tool_name": tool_call.get("tool_name"),
            "arguments": parse_json_object(tool_call.get("arguments_json")),
            "execution_time": tool_call.get("execution_time_ms"),
            "result_json": parse_json_value(tool_call.get("result_json")),
        }
    )


def _row_metadata(
    *,
    span: dict[str, Any],
    node_type: str,
    llm_call: dict[str, Any] | None,
    tool_call: dict[str, Any] | None,
) -> dict[str, Any]:
    metadata = _base_metadata(span, node_type)
    _apply_span_previews(metadata, span)
    if llm_call is not None:
        _apply_llm_metadata(metadata, llm_call)
    if tool_call is not None:
        _apply_tool_metadata(metadata, tool_call)
    return metadata


def _row_error(span: dict[str, Any], tool_call: dict[str, Any] | None) -> str | None:
    error = str(span.get("error_text") or (tool_call or {}).get("error_message") or "")
    return error.strip() or None


def build_trace_row_node(
    *,
    span: dict[str, Any],
    llm_call: dict[str, Any] | None,
    tool_call: dict[str, Any] | None,
) -> ExecutionTraceNode:
    node_type = str(span.get("node_type") or "step")
    metadata = _row_metadata(
        span=span,
        node_type=node_type,
        llm_call=llm_call,
        tool_call=tool_call,
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
        error=_row_error(span, tool_call),
        metadata=metadata,
    )
