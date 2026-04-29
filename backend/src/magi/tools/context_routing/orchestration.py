"""Orchestration strategy policy for context routing."""

from __future__ import annotations

from typing import Any, Optional

from .research_guardrail import is_complex_research_request


def default_orchestration_strategy(
    tools: Optional[list[str]] = None,
    user_lower: str = "",
) -> dict[str, Any]:
    selected_tools = tools or []
    if is_complex_research_request(user_lower):
        return {
            "mode": "decompose",
            "planner": "task_agent",
            "default_leaf_type": "general-purpose",
            "allow_parallel": True,
        }
    if "agent" in selected_tools:
        if any(kw in user_lower for kw in ["migration", "migrate", "实施方案", "design doc", "implementation plan"]):
            return {
                "mode": "decompose",
                "planner": "plan_worker",
                "default_leaf_type": "Explore",
                "allow_parallel": True,
            }
        if any(
            kw in user_lower
            for kw in ["架构", "architecture", "设计", "方案", "codebase", "repo", "代码结构", "代码库", "跨模块", "跨子系统"]
        ):
            return {
                "mode": "decompose",
                "planner": "task_agent",
                "default_leaf_type": "Explore",
                "allow_parallel": True,
            }
        if any(kw in user_lower for kw in ["explore", "scan", "搜索", "定位", "查找", "find"]):
            return {
                "mode": "direct",
                "planner": "task_agent",
                "default_leaf_type": "Explore",
                "allow_parallel": False,
            }
    return {
        "mode": "direct",
        "planner": "task_agent",
        "default_leaf_type": "general-purpose",
        "allow_parallel": False,
    }


def normalize_orchestration_strategy(payload: Any) -> dict[str, Any]:
    strategy = default_orchestration_strategy()
    if not isinstance(payload, dict):
        return strategy
    mode = str(payload.get("mode", strategy["mode"])).strip()
    planner = str(payload.get("planner", strategy["planner"])).strip()
    default_leaf_type = str(payload.get("default_leaf_type", strategy["default_leaf_type"])).strip()
    allow_parallel = bool(payload.get("allow_parallel", strategy["allow_parallel"]))
    if mode not in {"direct", "decompose"}:
        mode = strategy["mode"]
    if planner not in {"task_agent", "plan_worker"}:
        planner = strategy["planner"]
    if default_leaf_type not in {"Explore", "general-purpose"}:
        default_leaf_type = strategy["default_leaf_type"]
    if mode == "direct":
        allow_parallel = False
    return {
        "mode": mode,
        "planner": planner,
        "default_leaf_type": default_leaf_type,
        "allow_parallel": allow_parallel,
    }


__all__ = ["default_orchestration_strategy", "normalize_orchestration_strategy"]