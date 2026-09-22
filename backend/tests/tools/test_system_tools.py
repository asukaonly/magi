"""Exposure is an explicit policy, independent of tool categories."""

from types import SimpleNamespace

from magi.tools.system_tools import (
    ToolExposure,
    resolve_resident_system_tools,
    resolve_tool_exposure,
)


def test_new_control_tool_is_not_automatically_resident() -> None:
    registry = SimpleNamespace(
        list_tools=lambda: ["enter_plan_mode", "plugin_control", "file_read"]
    )
    assert resolve_resident_system_tools(registry) == ["enter_plan_mode"]
    assert resolve_tool_exposure("plugin_control") is ToolExposure.DEFERRED


def test_residency_does_not_depend_on_registry_category_filter() -> None:
    registry = SimpleNamespace(list_tools=lambda: ["memory_query", "detach_to_background", "bash"])
    assert resolve_resident_system_tools(registry) == ["detach_to_background", "memory_query"]


def test_contextual_and_deferred_tools_are_not_in_stable_core() -> None:
    names = [
        "exit_plan_mode",
        "request_reasoning_depth",
        "task_query",
        "trace_query",
        "batch_create",
    ]
    registry = SimpleNamespace(list_tools=lambda: names)
    assert resolve_resident_system_tools(registry) == []
    assert resolve_tool_exposure("task_query") is ToolExposure.CONTEXTUAL
    assert resolve_tool_exposure("batch_create") is ToolExposure.DEFERRED
