"""Pure serialization and scoring helpers for L4 procedural memory."""
from __future__ import annotations

import json
import math
from typing import Any, Mapping, Optional

from ..event_contracts import MemoryEvent
from .procedural_memory_schema import EMBEDDING_STATUS_DISABLED, _ADAPTIVE_MAX_THRESHOLD


def truncate_value(value: Any, max_chars: int) -> Optional[str]:
    if value is None:
        return None
    text = str(value).strip()
    if not text:
        return None
    if len(text) <= max_chars:
        return text
    return text[:max_chars - 3] + "..."


def extract_strategy_hint(optimized_prompt: str | None) -> str | None:
    if not optimized_prompt:
        return None
    text = str(optimized_prompt).strip()
    try:
        data = json.loads(text)
        if isinstance(data, dict):
            approach = str(data.get("recommended_approach") or "").strip()
            if approach:
                return approach
            cases = data.get("best_use_cases") or []
            if cases:
                return str(cases[0]).strip()
            return None
    except (json.JSONDecodeError, TypeError):
        pass
    if len(text) > 200:
        return text[:197] + "..."
    return text


def compute_context_fit(
    context_affinity_json: str | None,
    task_context: str | None,
) -> float | None:
    if not task_context or not context_affinity_json:
        return None
    try:
        affinity = json.loads(context_affinity_json)
        if not isinstance(affinity, dict) or not affinity:
            return None
    except (json.JSONDecodeError, TypeError):
        return None
    task_lower = task_context.lower().strip()
    for key, score in affinity.items():
        if task_lower in str(key).lower() or str(key).lower() in task_lower:
            return float(score)
    return None


def adaptive_extraction_threshold(base_threshold: int, total_attempts: int) -> int:
    if total_attempts <= base_threshold:
        return base_threshold
    scaled = int(base_threshold * math.sqrt(total_attempts / base_threshold))
    return max(base_threshold, min(scaled, _ADAPTIVE_MAX_THRESHOLD))


def rolling_average(current_value: Any, current_count: int, next_value: float) -> float:
    current = float(current_value or 0.0)
    if current_count <= 0:
        return next_value
    return ((current * current_count) + next_value) / (current_count + 1)


def row_to_skill_dict(row: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "skill_id": str(row["skill_id"]),
        "skill_name": str(row["skill_name"]),
        "skill_category": str(row["skill_category"]),
        "skill_type": str(row["skill_type"]),
        "proficiency": float(row["proficiency"]),
        "total_attempts": int(row["total_attempts"]),
        "success_count": int(row["success_count"]),
        "failure_count": int(row["failure_count"]),
        "success_rate": float(row["success_rate"]),
        "avg_execution_time_ms": float(row["avg_execution_time_ms"] or 0.0),
        "min_execution_time_ms": float(row["min_execution_time_ms"] or 0.0),
        "max_execution_time_ms": float(row["max_execution_time_ms"] or 0.0),
        "p95_execution_time_ms": float(row["p95_execution_time_ms"] or 0.0),
        "circuit_breaker_state": str(row["circuit_breaker_state"]),
        "circuit_breaker_opened_at": float(row["circuit_breaker_opened_at"]) if row["circuit_breaker_opened_at"] else None,
        "circuit_breaker_failure_count": int(row["circuit_breaker_failure_count"]),
        "circuit_breaker_success_count": int(row["circuit_breaker_success_count"]),
        "optimized_prompt": row["optimized_prompt"],
        "optimized_params": json.loads(row["optimized_params"] or "{}"),
        "optimization_score": float(row["optimization_score"]) if row["optimization_score"] is not None else None,
        "context_affinity": json.loads(row["context_affinity"] or "{}"),
        "source_event_ids": json.loads(row["source_event_ids"] or "[]"),
        "last_used_at": float(row["last_used_at"]) if row["last_used_at"] else None,
        "last_success_at": float(row["last_success_at"]) if row["last_success_at"] else None,
        "last_failure_at": float(row["last_failure_at"]) if row["last_failure_at"] else None,
        "embedding_status": str(row["embedding_status"] or EMBEDDING_STATUS_DISABLED),
        "embedding_profile_id": row["embedding_profile_id"],
        "embedding_chunk_count": int(row["embedding_chunk_count"] or 0),
        "last_embedded_at": float(row["last_embedded_at"]) if row["last_embedded_at"] else None,
        "created_at": float(row["created_at"]),
        "updated_at": float(row["updated_at"]),
        "pending_trace_count": int(row["pending_trace_count"]) if row["pending_trace_count"] is not None else 0,
    }


def row_to_execution_trace_dict(row: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "trace_id": str(row["trace_id"]),
        "skill_id": str(row["skill_id"]),
        "event_id": str(row["event_id"]),
        "turn_id": row["turn_id"],
        "success": bool(row["success"]),
        "duration_ms": float(row["duration_ms"] or 0.0),
        "error_summary": row["error_summary"],
        "input_summary": row["input_summary"],
        "output_summary": row["output_summary"],
        "task_context": row["task_context"],
        "created_at": float(row["created_at"]),
    }


def extract_skill_identity(event: MemoryEvent) -> Optional[dict[str, Any]]:
    """Extract skill identity and trace data from a memory event."""
    if event.event_type == "ActionExecuted":
        skill_name = str(event.source_item_id or event.content or "").strip()
        if not skill_name:
            return None
        meta = event.metadata_json or {}
        content_str = str(event.content or "").strip()
        optimized_prompt = content_str if content_str and content_str != skill_name else None
        success = int(event.level) < 3
        return {
            "skill_name": skill_name,
            "skill_category": "tool",
            "skill_type": "external_tool",
            "success": success,
            "duration_ms": float(meta.get("duration_ms", 0.0)),
            "error_summary": truncate_value(meta.get("error"), 500) if not success else None,
            "optimized_prompt": optimized_prompt,
            "input_summary": truncate_value(meta.get("input") or meta.get("params"), 500),
            "output_summary": truncate_value(meta.get("output") or meta.get("result"), 500),
            "task_context": meta.get("task_category") or event.task_id,
        }

    if event.event_type == "TaskCompleted":
        skill_name = str(event.task_id or "task").strip()
        content_str = str(event.content or "").strip() or None
        return {
            "skill_name": skill_name,
            "skill_category": "workflow",
            "skill_type": "composite",
            "success": True,
            "duration_ms": 0.0,
            "error_summary": None,
            "optimized_prompt": content_str,
            "input_summary": None,
            "output_summary": truncate_value(content_str, 500),
            "task_context": event.task_id,
        }

    if event.event_type == "TaskFailed":
        skill_name = str(event.task_id or "task").strip()
        content_str = str(event.content or "").strip() or None
        return {
            "skill_name": skill_name,
            "skill_category": "workflow",
            "skill_type": "composite",
            "success": False,
            "duration_ms": 0.0,
            "error_summary": truncate_value(content_str, 500),
            "optimized_prompt": content_str,
            "input_summary": None,
            "output_summary": None,
            "task_context": event.task_id,
        }

    return None
