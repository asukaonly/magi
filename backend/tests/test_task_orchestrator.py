from __future__ import annotations

import os

from magi.agent.task_orchestrator import TaskOrchestrator
from magi.tools.registry import ToolRegistry


async def _fake_plan_subtasks(*args, **kwargs):  # type: ignore[no-untyped-def]
    _ = (args, kwargs)
    raise AssertionError("plan_subtasks should not be called in this test")


async def _fake_aggregate(*args, **kwargs):  # type: ignore[no-untyped-def]
    _ = (args, kwargs)
    raise AssertionError("aggregate_orchestration should not be called in this test")


def _fake_register_user_message(*args, **kwargs) -> None:  # type: ignore[no-untyped-def]
    _ = (args, kwargs)


def test_build_agent_tool_context_includes_workspace_and_agent_metadata() -> None:
    orchestrator = TaskOrchestrator(
        runtime_key="explore:user-1",
        tool_registry=ToolRegistry(),
        plan_subtasks=_fake_plan_subtasks,
        aggregate_orchestration=_fake_aggregate,
        register_user_message=_fake_register_user_message,
        parent_task_agent_type="explore",
    )

    context = orchestrator._build_agent_tool_context("user-1", "session-1")

    assert context.agent_id == "explore:user-1"
    expected_workspace = os.path.dirname(os.getcwd()) if os.path.basename(os.getcwd()) == "backend" else os.getcwd()
    assert context.workspace == expected_workspace
    assert context.permissions == ["authenticated"]
    assert context.env_vars == {
        "user_id": "user-1",
        "session_id": "session-1",
        "target_task_agent_type": "explore",
        "target_task_agent_id": "user-1",
        "parent_task_agent_type": "explore",
        "parent_task_agent_id": "user-1",
    }


def test_resolve_workspace_root_prefers_explicit_user_scope() -> None:
    orchestrator = TaskOrchestrator(
        runtime_key="explore:user-1",
        tool_registry=ToolRegistry(),
        plan_subtasks=_fake_plan_subtasks,
        aggregate_orchestration=_fake_aggregate,
        register_user_message=_fake_register_user_message,
        parent_task_agent_type="explore",
    )

    resolved = orchestrator._resolve_workspace_root("看下~/code/magi下的代码，分析下代码架构")

    assert resolved == "/Users/asuka/code/magi"
