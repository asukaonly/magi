"""Runtime-control tool implementations (L4).

These tools require direct access to the control plane and therefore live
at L4 (magi.control) rather than in the plugin-isolation scope (magi.tools.builtin).
They are registered via CORE_TOOL_CLASSES in magi.tools.core_tools.
"""

from __future__ import annotations

from .plan_mode_tool import EnterPlanModeTool, ExitPlanModeTool
from .reasoning_depth_tool import RequestReasoningDepthTool
from .todo_write_tool import TodoWriteTool

CONTROL_TOOL_CLASSES: tuple[type, ...] = (
    EnterPlanModeTool,
    ExitPlanModeTool,
    TodoWriteTool,
    RequestReasoningDepthTool,
)

__all__ = [
    "EnterPlanModeTool",
    "ExitPlanModeTool",
    "TodoWriteTool",
    "RequestReasoningDepthTool",
    "CONTROL_TOOL_CLASSES",
]
