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
    """Best-effort resolution of the global message bus for trace publishing.

    Used by chat post-process trace migrations to publish SpanCompleted events
    without threading the bus through every constructor. Returns None if the
    container isn't configured (callers must handle the no-bus case).
    """
    try:
        from .....core.container import Container

        bus = Container.message_bus()
    except Exception:
        return None
    if bus is None or type(bus).__name__ == "object":
        return None
    if not hasattr(bus, "publish"):
        return None
    return bus
