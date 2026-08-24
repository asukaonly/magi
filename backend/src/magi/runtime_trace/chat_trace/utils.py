"""Pure helper functions for chat execution trace read models."""

from __future__ import annotations

import json
from typing import Any, Optional


def parse_json_object(raw_value: Any) -> dict[str, Any]:
    if not raw_value:
        return {}
    try:
        parsed = json.loads(str(raw_value))
    except Exception:
        return {}
    return parsed if isinstance(parsed, dict) else {}


def parse_json_value(raw_value: Any) -> Any:
    if not raw_value:
        return None
    if not isinstance(raw_value, str):
        return raw_value
    try:
        return json.loads(raw_value)
    except Exception:
        return raw_value


def map_trace_kind(node_type: str) -> str:
    mapping = {
        "intent_resolution": "intent",
        "llm_call": "llm",
        "tool_call": "tool",
        "worker_dispatch": "dispatch",
        "worker_attempt": "attempt",
        "response_emit": "response",
        "rhythm_processing": "rhythm",
        "skill_call": "skill",
    }
    return mapping.get(node_type, node_type or "step")


def default_trace_label(node_type: str) -> str:
    return str(node_type or "step").replace("_", " ").strip().title() or "Step"


def compact_value(value: Any) -> str:
    if isinstance(value, dict):
        summary = str(value.get("summary") or value.get("result_preview") or "").strip()
        if summary:
            return summary[:240]
        content_preview = str(
            value.get("content_preview") or value.get("stdout_preview") or ""
        ).strip()
        if content_preview:
            return content_preview[:240]
    if isinstance(value, list):
        return f"{len(value)} items"
    text = str(value or "").strip()
    return text[:240]


def trace_span_result_preview(payload: dict[str, Any]) -> str:
    output = payload.get("output")
    if isinstance(output, dict):
        for key in ("response_preview", "result_preview", "intent", "result"):
            preview = compact_value(output.get(key))
            if preview:
                return preview
    return ""


def trace_span_error(payload: dict[str, Any]) -> Optional[str]:
    error = payload.get("error")
    if isinstance(error, dict):
        return str(error.get("message") or error.get("failure_reason") or "").strip() or None
    return str(error or "").strip() or None


def ms_to_seconds(value: Any) -> Optional[float]:
    if value is None:
        return None
    try:
        return max(0.0, float(value) / 1000.0)
    except (TypeError, ValueError):
        return None


def tool_event_status(payload: dict[str, Any]) -> str:
    if "success" in payload:
        return "completed" if bool(payload.get("success")) else "failed"
    result = str(payload.get("result") or "").strip().lower()
    return "completed" if result == "success" else "failed" if result == "failed" else "running"


def tool_event_result_preview(payload: dict[str, Any]) -> str:
    if "data" in payload:
        return compact_value(payload.get("data"))
    result = str(payload.get("result") or "").strip()
    if result:
        return result
    return compact_value(payload.get("tool_params"))


def tool_event_arguments(payload: dict[str, Any]) -> dict[str, Any]:
    if isinstance(payload.get("arguments"), dict):
        return payload["arguments"]
    if isinstance(payload.get("tool_params"), dict):
        return payload["tool_params"]
    return {}


def normalize_status(status: str) -> str:
    lowered = str(status or "running").strip().lower()
    if lowered in {"completed", "ok", "success", "succeeded", "done"}:
        return "completed"
    if lowered in {"failed", "error", "errored", "timeout", "timed_out"}:
        return "failed"
    if lowered == "interrupted":
        return "interrupted"
    if lowered == "merged":
        return "merged"
    if lowered in {"pending"}:
        return "pending"
    return "running"


def derive_children_status(children: list[Any]) -> str:
    if not children:
        return "running"
    statuses = {child.status for child in children}
    if "running" in statuses or "pending" in statuses:
        return "running"
    if "completed" in statuses:
        return "completed"
    if "failed" in statuses:
        return "failed"
    return "completed"


def is_terminal_status(status: str) -> bool:
    return status in {"completed", "failed", "interrupted", "merged"}


def optional_text(value: Any) -> Optional[str]:
    text = str(value or "").strip()
    return text or None


def safe_int(value: Any, *, default: int) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default
