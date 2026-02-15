"""
工具模块

提供内置工具和工具注册表
支持 Claude Tool Use API 格式
支持 Claude Code Skills
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
from .selector import ToolSelector
from .context_decider import ContextDecider, ContextDecision
from .function_calling import FunctionCallingExecutor, ToolCall, ToolCallResult
from .recommender import ToolRecommender, ScenarioType
from .planner import ExecutionPlanner, ExecutionPlan, PlanNode, TaskStatus
from .version_manager import ToolVersionManager, ToolVersion, VersionCompatibility

# 导入内置工具
from .builtin.bash_tool import BashTool
from .builtin.file_read_tool import FileReadTool
from .builtin.file_write_tool import FileWriteTool
from .builtin.file_list_tool import FileListTool
from .builtin.dynamic_tool import DynamicTool, create_dynamic_tool
from .builtin.capabilities_tool import CapabilitiesTool
from .builtin.web_search_tool import WebSearchTool
from .builtin.skills_creator_tool import SkillsCreatorTool
from .builtin.weather_tool import WeatherTool

# 导入 Skills 模块
from ..skills.indexer import SkillIndexer
from ..skills.loader import SkillLoader
from ..skills.executor import SkillExecutor
from ..skills.schema import SkillMetadata, SkillContent, SkillResult

# 注册所有内置工具
_builtin_tools = [
    BashTool,
    FileReadTool,
    FileWriteTool,
    FileListTool,
    CapabilitiesTool,
    WebSearchTool,
    SkillsCreatorTool,
    WeatherTool,
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

    # 工具选择器
    "ToolSelector",

    # 上下文决策器
    "ContextDecider",
    "ContextDecision",

    # 函数调用执行器
    "FunctionCallingExecutor",
    "ToolCall",
    "ToolCallResult",

    # 推荐引擎
    "ToolRecommender",
    "ScenarioType",

    # 执行计划器
    "ExecutionPlanner",
    "ExecutionPlan",
    "PlanNode",
    "TaskStatus",

    # 版本管理
    "ToolVersionManager",
    "ToolVersion",
    "VersionCompatibility",

    # 动态工具
    "DynamicTool",
    "create_dynamic_tool",

    # 内置工具
    "BashTool",
    "FileReadTool",
    "FileWriteTool",
    "FileListTool",
    "CapabilitiesTool",
    "WebSearchTool",
    "SkillsCreatorTool",
    "WeatherTool",

    # Skills
    "SkillIndexer",
    "SkillLoader",
    "SkillExecutor",
    "SkillMetadata",
    "SkillContent",
    "SkillResult",
]
