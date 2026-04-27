"""Tool contracts - re-exported from magi-plugin-sdk.

Internal backend code may continue importing from this module during the
migration window. External plugin authors should prefer
``magi_plugin_sdk.tools``.
"""

from magi_plugin_sdk.tools import (  # noqa: F401
    MultiProviderTool,
    ParameterType,
    Tool,
    ToolConfigSpec,
    ToolErrorCode,
    ToolExecutionContext,
    ToolParameter,
    ToolResult,
    ToolSchema,
)

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
