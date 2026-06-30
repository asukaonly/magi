"""Fallback subtask recipes for chat task planning."""

from __future__ import annotations

from magi.agent.orchestration import PlannedSubtask

from .planning_heuristics import build_research_seed_subtasks

CODE_EXPLORE_LEAF_TYPE = "CodeExplore"
GENERAL_PURPOSE_LEAF_TYPE = "general-purpose"
LEAF_SUBAGENT_TYPES = {CODE_EXPLORE_LEAF_TYPE, GENERAL_PURPOSE_LEAF_TYPE}

_REPO_ARCHITECTURE_KEYWORDS = [
    "architecture",
    "codebase",
    "repo",
    "代码架构",
    "项目架构",
    "代码库",
    "目录结构",
]


def build_fallback_subtask_plan(
    user_message: str,
    default_leaf_type: str,
    *,
    request_profile: str,
) -> list[PlannedSubtask]:
    """Build deterministic fallback subtasks for chat planning."""
    if request_profile == "research":
        return build_research_seed_subtasks(user_message)
    if is_repo_architecture_request(user_message):
        return build_repo_architecture_subtasks()
    return build_generic_fallback_subtasks(_normalize_fallback_leaf_type(default_leaf_type))


def is_repo_architecture_request(user_message: str) -> bool:
    lowered = user_message.lower()
    return any(keyword in lowered for keyword in _REPO_ARCHITECTURE_KEYWORDS)


def build_repo_architecture_subtasks() -> list[PlannedSubtask]:
    return [
        PlannedSubtask(
            description="Map repository layout",
            subagent_type=CODE_EXPLORE_LEAF_TYPE,
            prompt="Analyze the top-level directory structure, major modules, and entry folders.",
            parallel_group="group_a",
        ),
        PlannedSubtask(
            description="Identify technology stack",
            subagent_type=CODE_EXPLORE_LEAF_TYPE,
            prompt="Inspect dependency manifests and boot files to identify the backend, frontend, storage, and runtime stack.",
            parallel_group="group_a",
        ),
        PlannedSubtask(
            description="Analyze frontend structure",
            subagent_type=CODE_EXPLORE_LEAF_TYPE,
            prompt="Focus on frontend organization, bootstrap flow, routing, and the main UI entry points.",
            parallel_group="group_a",
        ),
        PlannedSubtask(
            description="Analyze backend modules",
            subagent_type=CODE_EXPLORE_LEAF_TYPE,
            prompt="Focus on backend module boundaries, runtime startup, task agent chain, and the main execution flow.",
            parallel_group="group_a",
        ),
        PlannedSubtask(
            description="Inspect project progress",
            subagent_type=CODE_EXPLORE_LEAF_TYPE,
            prompt="Look for docs, progress trackers, release notes, or TODO-style files that indicate the current project status and recent progress.",
            parallel_group="group_a",
        ),
    ]


def build_generic_fallback_subtasks(leaf_type: str) -> list[PlannedSubtask]:
    return [
        PlannedSubtask(
            description="Locate the primary anchor",
            subagent_type=leaf_type,
            prompt="Find the smallest set of files, symbols, or entry modules most likely to control the requested behavior or answer.",
            parallel_group="group_a",
        ),
        PlannedSubtask(
            description="Trace the owning implementation path",
            subagent_type=leaf_type,
            prompt="Follow the code path that directly computes, routes, or controls the requested behavior, pulling in only the nearby dependencies needed to explain it.",
            parallel_group="group_a",
        ),
        PlannedSubtask(
            description="Validate gaps and edge cases",
            subagent_type=leaf_type,
            prompt="Validate important edge cases, unresolved assumptions, and remaining gaps from source evidence instead of repeating broad summary prose.",
            parallel_group="group_b",
        ),
    ]


def _normalize_fallback_leaf_type(default_leaf_type: str) -> str:
    if default_leaf_type in LEAF_SUBAGENT_TYPES:
        return default_leaf_type
    return CODE_EXPLORE_LEAF_TYPE
