"""
工具模块

提供内置工具和工具注册表
"""
from .schema import (
    Tool,
    ToolSchema,
    ToolParameter,
    ToolExecutionContext,
    ToolResult,
    ParameterType,
)
from .registry import ToolRegistry, tool_registry

# 导入内置工具
from .builtin.bash_tool import BashTool
from .builtin.file_read_tool import FileReadTool
from .builtin.file_write_tool import FileWriteTool
from .builtin.file_list_tool import FileListTool

# 注册所有内置工具
_builtin_tools = [
    BashTool,
    FileReadTool,
    FileWriteTool,
    FileListTool,
]

for tool_class in _builtin_tools:
    try:
        tool_registry.register(tool_class)
    except Exception as e:
        import logging
        logging.error(f"Failed to register tool {tool_class.__name__}: {e}")

__all__ = [
    # 基础类
    "Tool",
    "ToolSchema",
    "ToolParameter",
    "ToolExecutionContext",
    "ToolResult",
    "ParameterType",

    # 注册表
    "ToolRegistry",
    "tool_registry",

    # 内置工具
    "BashTool",
    "FileReadTool",
    "FileWriteTool",
    "FileListTool",
]
