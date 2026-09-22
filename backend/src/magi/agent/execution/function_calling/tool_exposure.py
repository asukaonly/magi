"""Refresh contextual schemas from authoritative state at model boundaries."""

from __future__ import annotations

from dataclasses import replace
from sqlite3 import Error as SQLiteError
from typing import Any

from magi.control.provider import resolve_control_session_store
from magi.core.logger import get_logger
from magi.tools.system_tools import STATE_MANAGED_TOOLS

from ...background.contracts import BackgroundTaskStatus
from ...background.provider import resolve_background_task_manager
from ..model_capabilities import ModelCapabilityProfile
from .run_input import AgentRunRequest
from .step_models import FunctionCallingStepState

logger = get_logger(__name__)


async def refresh_contextual_tools(
    host: Any,
    *,
    state: FunctionCallingStepState,
    run_input: AgentRunRequest,
) -> bool:
    """Refresh state-owned controls without widening a child driver's tool set."""
    registry = getattr(host, "tool_registry", None)
    if registry is None or not callable(getattr(registry, "list_tools", None)):
        return False
    profile = run_input.model_capabilities or ModelCapabilityProfile.from_model_context(
        getattr(host, "_active_model_context", None)
    )
    if not profile.supports_tool_calls:
        return False

    registered = set(registry.list_tools())
    selected = set(state.selected_tool_names)
    root_chat = run_input.execution_preset == "chat" and run_input.parent_run_id is None
    contextual: set[str] = set()
    if (
        "exit_plan_mode" in registered
        and (root_chat or selected & {"enter_plan_mode", "exit_plan_mode"})
        and _plan_is_active(run_input.session_id)
    ):
        contextual.add("exit_plan_mode")
    if (
        "request_reasoning_depth" in registered
        and (root_chat or "request_reasoning_depth" in selected)
        and _can_adjust_reasoning(host, state)
    ):
        contextual.add("request_reasoning_depth")
    if root_chat and "task_query" in registered:
        # Keep an admitted query available through task completion in this run.
        if "task_query" in selected or await _has_active_tasks(run_input):
            contextual.add("task_query")

    state.contextual_resident_tools = contextual
    names = [
        name
        for name in state.selected_tool_names
        if name not in STATE_MANAGED_TOOLS or name in contextual
    ]
    names.extend(sorted(contextual - set(names) - state.suppressed_tool_names))
    if names == state.selected_tool_names:
        return False
    logger.info(
        "agent_run.contextual_tools_changed",
        run_id=run_input.run_id,
        added_tools=sorted(set(names) - selected),
        removed_tools=sorted(selected - set(names)),
    )
    state.selected_tool_names = names
    state.tools = host._build_tools_parameter(names)
    return True


def _plan_is_active(session_id: str | None) -> bool:
    if not session_id:
        return False
    try:
        store = resolve_control_session_store()
    except RuntimeError:
        return False
    return store.plan_state(session_id).active


def _can_adjust_reasoning(host: Any, state: FunctionCallingStepState) -> bool:
    policy = state.reasoning_policy
    reasoning = state.reasoning_state
    bridge = getattr(host, "provider_bridge", None)
    resolve_depth = getattr(bridge, "resolve_effective_reasoning_depth", None)
    if policy is None or reasoning is None or not callable(resolve_depth):
        return False
    current = resolve_depth(reasoning.requested_depth)
    proposed = replace(reasoning)
    # Some providers collapse adjacent depths. Keep the control if the remaining
    # budget can reach any distinct effective setting without mutating live state.
    while proposed.escalate(policy, reason="exposure_check"):
        if resolve_depth(proposed.requested_depth) != current:
            return True
    return False


async def _has_active_tasks(run_input: AgentRunRequest) -> bool:
    if not run_input.user_id or not run_input.session_id:
        return False
    try:
        manager = resolve_background_task_manager()
    except RuntimeError:
        return False
    try:
        tasks = await manager.store.list_tasks(
            user_id=run_input.user_id,
            session_id=run_input.session_id,
            statuses=[status for status in BackgroundTaskStatus if not status.is_terminal],
            limit=1,
        )
    except (SQLiteError, OSError):
        logger.warning("agent_run.task_exposure_lookup_failed", run_id=run_input.run_id)
        return False
    return bool(tasks)
