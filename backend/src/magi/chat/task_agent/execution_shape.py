"""Compatibility exports for per-turn execution shape derivation."""
from __future__ import annotations

from magi.agent.task_agents.handlers.turn_route_resolver import (
    ORCH_MAYBE,
    ORCH_NONE,
    ORCH_REQUIRED,
    SHAPE_PLAN_FANOUT,
    SHAPE_REPLY,
    SHAPE_TOOL_LOOP,
    derive_execution_shape,
)


__all__ = [
    "derive_execution_shape",
    "SHAPE_REPLY",
    "SHAPE_TOOL_LOOP",
    "SHAPE_PLAN_FANOUT",
    "ORCH_NONE",
    "ORCH_MAYBE",
    "ORCH_REQUIRED",
]
