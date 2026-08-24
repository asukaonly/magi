"""TDD test: magi.control.tools package (Phase 4 Task 3).

Verifies that the runtime-control tools are exported from magi.control.tools
(their new canonical location at L4) with the expected tool names.
"""

from __future__ import annotations


def test_control_tools_importable() -> None:
    from magi.control.tools import (  # noqa: F401
        EnterPlanModeTool,
        ExitPlanModeTool,
        RequestReasoningDepthTool,
        TodoWriteTool,
        CONTROL_TOOL_CLASSES,
    )


def test_control_tool_classes_tuple() -> None:
    from magi.control.tools import (
        EnterPlanModeTool,
        ExitPlanModeTool,
        RequestReasoningDepthTool,
        TodoWriteTool,
        CONTROL_TOOL_CLASSES,
    )

    assert CONTROL_TOOL_CLASSES == (
        EnterPlanModeTool,
        ExitPlanModeTool,
        TodoWriteTool,
        RequestReasoningDepthTool,
    )


def test_enter_plan_mode_schema_name() -> None:
    from magi.control.tools import EnterPlanModeTool

    tool = EnterPlanModeTool()
    assert tool.get_schema().name == "enter_plan_mode"


def test_exit_plan_mode_schema_name() -> None:
    from magi.control.tools import ExitPlanModeTool

    tool = ExitPlanModeTool()
    assert tool.get_schema().name == "exit_plan_mode"


def test_todo_write_schema_name() -> None:
    from magi.control.tools import TodoWriteTool

    tool = TodoWriteTool()
    assert tool.get_schema().name == "todo_write"
