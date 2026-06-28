"""Typed orchestration plan derived from routing decisions."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from magi.tools.context_routing import RouteDecision


@dataclass(slots=True)
class OrchestrationPlan:
    """Structured orchestration plan chosen by intent routing."""

    mode: str = "direct"
    planner: str = "task_agent"
    default_leaf_type: str = "CodeExplore"
    allow_parallel: bool = True
    route_to_explore_task_agent: bool = False

    @classmethod
    def from_route_decision(cls, route_decision: "RouteDecision") -> "OrchestrationPlan":
        return cls(
            mode=route_decision.orchestration_mode,
            planner=route_decision.orchestration_planner,
            default_leaf_type=route_decision.default_leaf_type,
            allow_parallel=route_decision.allow_parallel,
        )


__all__ = ["OrchestrationPlan"]
