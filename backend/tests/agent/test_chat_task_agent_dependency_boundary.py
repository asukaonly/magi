"""Boundary tests for chat task-agent runtime assembly."""

from __future__ import annotations

import inspect

from magi.chat.task_agent.chat_task_agent import ChatTaskAgent
from magi.chat.task_agent import runtime_dependencies
from magi.chat.task_agent.runtime_dependencies import (
    build_chat_task_agent_runtime_parts,
)


def test_chat_task_agent_delegates_runtime_assembly_to_chat_builder() -> None:
    source = inspect.getsource(ChatTaskAgent.__init__)

    assert "build_chat_task_agent_runtime_parts" in source
    for constructor_name in (
        "ChatContextAssembler",
        "ChatExecutionCoordinator",
        "ChatPlanningService",
        "ChatPostProcessService",
        "ChatPromptService",
        "SessionRunCoordinator",
        "SessionRunStore",
        "FunctionCallingOrchestrator",
        "ExecutionHandlerRegistry",
    ):
        assert f"{constructor_name}(" not in source


def test_chat_runtime_builder_owns_core_chat_wiring() -> None:
    source = inspect.getsource(build_chat_task_agent_runtime_parts)

    for constructor_name in (
        "ChatContextAssembler",
        "ChatExecutionCoordinator",
        "ChatPlanningService",
        "ChatPostProcessService",
        "ChatPromptService",
        "SessionRunCoordinator",
        "SessionRunStore",
        "FunctionCallingOrchestrator",
        "ExecutionHandlerRegistry",
    ):
        assert f"{constructor_name}(" in source


def test_chat_runtime_builder_does_not_pull_from_bootstrap_container() -> None:
    source = inspect.getsource(runtime_dependencies)

    assert "get_container" not in source
    assert "runtime_bootstrap_context" not in source
