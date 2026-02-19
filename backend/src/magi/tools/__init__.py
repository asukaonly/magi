"""
Tool Module

Provides built-in tools and tool registry
support Claude Tool Use API format
support Claude Code Skills
"""
from .schema import (
    Tool,
    ToolSchema,
    ToolParameter,
    ToolExecutionContext,
    ToolResult,
    ToolConfigSpec,
    ParameterType,
)
from .registry import ToolRegistry, tool_registry
from .selector import ToolSelector
from .context_decider import ContextDecider, ContextDecision
from .function_calling import FunctionCallingExecutor, ToolCall, ToolCallResult
from .recommender import ToolRecommender, ScenarioType
from .planner import ExecutionPlanner, ExecutionPlan, PlanNode, TaskStatus
from .version_manager import ToolVersionManager, ToolVersion, VersionCompatibility

# importBuilt-in tools
from .builtin.bash_tool import BashTool
from .builtin.file_read_tool import FileReadTool
from .builtin.file_write_tool import FileWriteTool
from .builtin.file_list_tool import FileListTool
from .builtin.dynamic_tool import DynamicTool, create_dynamic_tool
from .builtin.capabilities_tool import CapabilitiesTool
from .builtin.web_search_tool import WebSearchTool
from .builtin.web_fetch_tool import WebFetchTool
from .builtin.skills_creator_tool import SkillsCreatorTool
from .builtin.weather_tool import WeatherTool
from .builtin.system_settings_tool import SystemSettingsTool

# import Skills module
from ..skills.indexer import SkillIndexer
from ..skills.loader import SkillLoader
from ..skills.executor import SkillExecutor
from ..skills.schema import SkillMetadata, SkillContent, SkillResult

# Register all built-in tools
_builtin_tools = [
    BashTool,
    FileReadTool,
    FileWriteTool,
    FileListTool,
    CapabilitiesTool,
    WebSearchTool,
    WebFetchTool,
    SkillsCreatorTool,
    WeatherTool,
    SystemSettingsTool,
]

for tool_class in _builtin_tools:
    try:
        tool_registry.register(tool_class)
    except Exception as e:
        import logging
        logging.ERROR(f"Failed to register tool {tool_class.__name__}: {e}")

__all__ = [
    # Base classes
    "Tool",
    "ToolSchema",
    "ToolParameter",
    "ToolExecutionContext",
    "ToolResult",
    "ToolConfigSpec",
    "ParameterType",

    # Registry
    "ToolRegistry",
    "tool_registry",

    # tool选择器
    "ToolSelector",

    # contextDecision器
    "ContextDecider",
    "ContextDecision",

    # Function调用Execute器
    "FunctionCallingExecutor",
    "ToolCall",
    "ToolCallResult",

    # recommended引擎
    "ToolRecommender",
    "ScenarioType",

    # Executeplan器
    "ExecutionPlanner",
    "ExecutionPlan",
    "PlanNode",
    "TaskStatus",

    # version管理
    "ToolVersionManager",
    "ToolVersion",
    "VersionCompatibility",

    # dynamictool
    "DynamicTool",
    "create_dynamic_tool",

    # Built-in tools
    "BashTool",
    "FileReadTool",
    "FileWriteTool",
    "FileListTool",
    "CapabilitiesTool",
    "WebSearchTool",
    "WebFetchTool",
    "SkillsCreatorTool",
    "WeatherTool",
    "SystemSettingsTool",

    # Skills
    "SkillIndexer",
    "SkillLoader",
    "SkillExecutor",
    "SkillMetadata",
    "SkillContent",
    "SkillResult",
]
