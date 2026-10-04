"""TDD test: magi.control.tools package (Phase 4 Task 3).

Verifies that the runtime-control tools are exported from magi.control.tools
(their new canonical location at L4) with the expected tool names.
"""

from __future__ import annotations


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
