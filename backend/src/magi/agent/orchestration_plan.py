"""Typed orchestration plan for domain-owned explore task agents."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(slots=True)
class OrchestrationPlan:
    """Structured orchestration plan owned by a specialized domain driver."""

    mode: str = "direct"
    planner: str = "task_agent"
    default_leaf_type: str = "CodeExplore"
    allow_parallel: bool = True
    route_to_explore_task_agent: bool = False

__all__ = ["OrchestrationPlan"]
