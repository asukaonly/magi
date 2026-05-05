"""Pure helper functions for chat post-processing."""

from __future__ import annotations

import time
from typing import Any

from .....agent.runtime.contracts import FactRecord
from ...common import ExecutionResult


def build_trace_id(turn_id: str) -> str:
    return f"trace:{turn_id}"


def build_root_span_id(turn_id: str) -> str:
    return f"{turn_id}:turn"


def build_span_id(turn_id: str, suffix: str) -> str:
    return f"{turn_id}:{suffix}"


def serialize_ux_plan(decision: Any) -> dict[str, Any] | None:
    plan = getattr(decision, "ux_plan", None)
    if plan is None:
        return None
    to_dict = getattr(plan, "to_dict", None)
    if callable(to_dict):
        payload = to_dict()
        return payload if isinstance(payload, dict) else None
    return plan if isinstance(plan, dict) else None


def resolve_started_at_ms(result: ExecutionResult | None, latest_fact: FactRecord) -> int:
    raw_timestamp = (
        float(result.message_started_at)
        if result is not None and result.message_started_at is not None
        else float(latest_fact.timestamp or time.time())
    )
    return max(0, int(raw_timestamp * 1000))


def normalize_mode(mode: Any) -> str:
    return str(getattr(mode, "value", mode) or "unknown")


def resolve_event_bus() -> Any | None:
    """Backward-compatible thin wrapper.

    Phase 6 moved the canonical implementation to
    :mod:`magi.runtime_trace.span_publisher`; this wrapper is kept so existing
    chat post-process callers continue to work without churn. New callers
    (worker-trace, etc.) should import from ``span_publisher`` directly.
    """
    from .....runtime_trace.span_publisher import resolve_event_bus as _resolve

    return _resolve()
