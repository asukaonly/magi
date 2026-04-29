"""Execution trace helpers for L4 procedural memory."""
from __future__ import annotations

from collections.abc import Iterable, MutableMapping
from typing import Any, Mapping

from .procedural_memory_serialization import row_to_execution_trace_dict, truncate_value


def merge_stratified_trace_rows(
    *,
    failures: Iterable[Mapping[str, Any]],
    successes: Iterable[Mapping[str, Any]],
    recent: Iterable[Mapping[str, Any]],
    limit: int,
) -> list[dict[str, Any]]:
    seen: set[str] = set()
    result: list[dict[str, Any]] = []

    for row in list(failures) + list(successes) + list(recent):
        trace_id = str(row["trace_id"])
        if trace_id in seen:
            continue
        seen.add(trace_id)
        result.append(row_to_execution_trace_dict(row))
        if len(result) >= limit:
            break

    result.sort(key=lambda trace: trace["created_at"], reverse=True)
    return result


def duration_baseline_from_row(row: Mapping[str, Any] | None) -> dict[str, float]:
    if row is None:
        return {}
    return {
        "avg_ms": float(row["avg_execution_time_ms"] or 0.0),
        "p95_ms": float(row["p95_execution_time_ms"] or 0.0),
    }


def failure_turn_ids(traces: Iterable[Mapping[str, Any]]) -> list[str]:
    turn_ids = [
        trace["turn_id"]
        for trace in traces
        if not trace["success"] and trace.get("turn_id")
    ]
    return list(set(turn_ids))


def recovery_map_from_rows(rows: Iterable[Mapping[str, Any]]) -> dict[str, dict[str, str]]:
    recovery_map: dict[str, dict[str, str]] = {}
    for row in rows:
        turn_id = str(row["turn_id"])
        if turn_id not in recovery_map:
            recovery_map[turn_id] = {
                "recovery_tool": str(row["skill_name"]),
                "recovery_output": truncate_value(row["output_summary"], 200) or "",
            }
    return recovery_map


def apply_recovery_annotations(
    traces: Iterable[MutableMapping[str, Any]],
    recovery_map: Mapping[str, Mapping[str, str]],
) -> None:
    for trace in traces:
        turn_id = trace.get("turn_id")
        if not trace["success"] and turn_id in recovery_map:
            info = recovery_map[str(turn_id)]
            trace["recovery_tool"] = info["recovery_tool"]
            trace["recovery_output"] = info["recovery_output"]
