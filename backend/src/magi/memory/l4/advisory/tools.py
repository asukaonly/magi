"""Tool advisory helpers for L4 procedural memory."""
from __future__ import annotations

from typing import Any, Mapping

from ..storage.serialization import compute_context_fit, extract_strategy_hint


def build_tool_advisory(
    *,
    row: Mapping[str, Any],
    tool_name: str,
    task_context: str | None,
) -> dict[str, Any]:
    breaker = str(row["circuit_breaker_state"])
    success_rate = float(row["success_rate"])
    total_attempts = int(row["total_attempts"])
    return {
        "tool_name": tool_name,
        "available": breaker != "open",
        "breaker_state": breaker,
        "success_rate": success_rate,
        "total_attempts": total_attempts,
        "strategy_hint": extract_strategy_hint(row["optimized_prompt"]),
        "context_fit": compute_context_fit(row["context_affinity"], task_context),
        "risk_note": build_tool_risk_note(
            breaker=breaker,
            success_rate=success_rate,
            total_attempts=total_attempts,
        ),
    }


def build_tool_risk_note(
    *,
    breaker: str,
    success_rate: float,
    total_attempts: int,
) -> str | None:
    if breaker == "open":
        return "Circuit breaker open: consecutive failures detected"
    if breaker == "half_open":
        return "Circuit breaker recovering: recent failures observed"
    if success_rate < 0.5 and total_attempts >= 3:
        return f"Low success rate ({success_rate:.0%} over {total_attempts} attempts)"
    return None


def is_tool_advisory_notable(advisory: Mapping[str, Any]) -> bool:
    return (
        advisory["breaker_state"] != "closed"
        or advisory["strategy_hint"] is not None
        or (float(advisory["success_rate"]) < 0.7 and int(advisory["total_attempts"]) >= 3)
    )
