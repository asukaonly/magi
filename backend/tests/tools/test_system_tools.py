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


def test_core_exports_registration_aliases_and_exposure_share_one_inventory():
    import magi.tools as tools
    import magi.tools.builtin as builtin
    from magi.tools.core_tools import CORE_TOOL_CLASSES
    from magi.tools.registry import ToolRegistry
    from magi.tools.system_tools import resolve_runtime_fact_tools
    rows = [
        ("CurrentTimeTool","current_time",ToolExposure.RESIDENT),
        ("EnvironmentQueryTool","environment_query",ToolExposure.RESIDENT),
        ("TaskQueryTool","task_query",ToolExposure.CONTEXTUAL),
        ("AskUserQuestionTool","ask_user_question",ToolExposure.RESIDENT),
        ("FileDiffTool","file_diff",ToolExposure.DEFERRED),
        ("FileRollbackTool","file_rollback",ToolExposure.DEFERRED),
        ("VerifyTool","verify",ToolExposure.DEFERRED),
        ("DelegateToExternalCoderTool","delegate_to_external_coder",ToolExposure.DEFERRED),
    ]
    registry = ToolRegistry()
    for exported, name, exposure in rows:
        cls = next(cls for cls in CORE_TOOL_CLASSES if cls.__name__ == exported)
        if exported in {"FileDiffTool", "FileRollbackTool", "VerifyTool", "DelegateToExternalCoderTool"}:
            assert getattr(builtin, exported) is getattr(tools, exported) is cls
        registry.register(cls)
        assert isinstance(registry.get_tool(name), cls)
        assert registry.get_tool(name).schema.name == name
        assert resolve_tool_exposure(name) is exposure
    assert set(registry.list_tools()) == {row[1] for row in rows}
    assert set(resolve_resident_system_tools(registry)) == {"current_time","environment_query","ask_user_question"}
    assert set(resolve_runtime_fact_tools(registry)) == {"current_time","environment_query"}
    assert registry.get_tool("ask") is registry.get_tool("ask_user_question")
    assert registry.get_tool_info("ask") == registry.get_tool_info("ask_user_question")
