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
    ToolErrorCode,
)
from .registry import ToolRegistry, tool_registry
from .context_decider import ContextDecider, ContextDecision
from .recommender import ToolRecommender, ScenarioType
from .planner import ExecutionPlanner, ExecutionPlan, PlanNode, TaskStatus
from .version_manager import ToolVersionManager, ToolVersion, VersionCompatibility

# importBuilt-in tools
from .builtin.bash_tool import BashTool
from .builtin.file_read_tool import FileReadTool
from .builtin.file_write_tool import FileWriteTool
from .builtin.file_edit_tool import FileEditTool
from .builtin.grep_tool import GrepTool
from .builtin.glob_tool import GlobTool
from .builtin.dynamic_tool import DynamicTool, create_dynamic_tool
from .builtin.capabilities_tool import CapabilitiesTool
from .builtin.web_search_tool import WebSearchTool
from .builtin.web_fetch_tool import WebFetchTool
from .builtin.weather_tool import WeatherTool
from .builtin.system_settings_tool import SystemSettingsTool
from .builtin.agent_tool import AgentTool

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
    FileEditTool,
    GrepTool,
    GlobTool,
    CapabilitiesTool,
    WebSearchTool,
    WebFetchTool,
    WeatherTool,
    SystemSettingsTool,
    AgentTool,
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
    "ToolErrorCode",

    # Registry
    "ToolRegistry",
    "tool_registry",

    # Context Decider (replaces old ToolSelector)
    "ContextDecider",
    "ContextDecision",

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
    "FileEditTool",
    "GrepTool",
    "GlobTool",
    "CapabilitiesTool",
    "WebSearchTool",
    "WebFetchTool",
    "SkillsCreatorTool",
    "WeatherTool",
    "SystemSettingsTool",
    "AgentTool",

    # Skills
    "SkillIndexer",
    "SkillLoader",
    "SkillExecutor",
    "SkillMetadata",
    "SkillContent",
    "SkillResult",
]
