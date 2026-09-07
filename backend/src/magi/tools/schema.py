"""Tool contracts and the internal execution context for bundled tools."""

from enum import Enum

from magi_plugin_sdk.tools import (  # noqa: F401
    MultiProviderTool,
    ParameterType,
    Tool,
    ToolConfigSpec,
    ToolErrorCode as SDKToolErrorCode,
    ToolParameter,
    ToolResult,
    ToolSchema,
)
from ..core.tool_context import ToolExecutionContext

_TOOL_ERROR_CODE_VALUES = {
    member.name: member.value for member in SDKToolErrorCode
}
_TOOL_ERROR_CODE_VALUES.setdefault("RATE_LIMITED", "RATE_LIMITED")
_TOOL_ERROR_CODE_VALUES.setdefault("POLICY_BLOCKED", "POLICY_BLOCKED")

ToolErrorCode = Enum("ToolErrorCode", _TOOL_ERROR_CODE_VALUES, type=str)

__all__ = [
    "MultiProviderTool",
    "ParameterType",
    "Tool",
    "ToolConfigSpec",
    "ToolErrorCode",
    "ToolExecutionContext",
    "ToolParameter",
    "ToolResult",
    "ToolSchema",
]
