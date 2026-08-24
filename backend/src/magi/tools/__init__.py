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
from .tool_hint_resolver import ToolHintResolver
from .recommender import ToolRecommender, ScenarioType
from .planner import ExecutionPlanner, ExecutionPlan, PlanNode, TaskStatus
from .version_manager import ToolVersionManager, ToolVersion, VersionCompatibility

# Import built-in tools
from .builtin.bash_tool import BashTool
from .builtin.file_read_tool import FileReadTool
from .builtin.file_write_tool import FileWriteTool
from .builtin.file_edit_tool import FileEditTool
from .builtin.file_rollback_tool import FileRollbackTool
from .builtin.file_diff_tool import FileDiffTool
from .builtin.verify_tool import VerifyTool
from .builtin.delegate_to_external_coder_tool import DelegateToExternalCoderTool
from .builtin.grep_tool import GrepTool
from .builtin.glob_tool import GlobTool
from .builtin.dynamic_tool import DynamicTool, create_dynamic_tool
from .builtin.capabilities_tool import CapabilitiesTool
from .builtin.find_relevant_tools_tool import FindRelevantToolsTool
from .builtin.web_search_tool import WebSearchTool
from .builtin.web_fetch_tool import WebFetchTool
from .builtin.weather_tool import WeatherTool
from .builtin.system_settings_tool import SystemSettingsTool
from .builtin.memory_query_tool import MemoryQueryTool
from .builtin.schedule_tool import ScheduleTool
from .builtin.prepare_chat_attachments_tool import PrepareChatAttachmentsTool
from .builtin.read_chat_attachment_tool import ReadChatAttachmentTool

# Import skills module
from ..skills.indexer import SkillIndexer
from ..skills.loader import SkillLoader
from ..skills.runner import SkillRunner
from ..skills.schema import SkillMetadata, SkillContent, SkillResult

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
    "ToolHintResolver",

    # Auxiliary Model (replaces old ToolSelector)

    # Recommendation engine
    "ToolRecommender",
    "ScenarioType",

    # Execution planner
    "ExecutionPlanner",
    "ExecutionPlan",
    "PlanNode",
    "TaskStatus",

    # Version management
    "ToolVersionManager",
    "ToolVersion",
    "VersionCompatibility",

    # Dynamic tool
    "DynamicTool",
    "create_dynamic_tool",

    # Built-in tools
    "BashTool",
    "FileReadTool",
    "FileWriteTool",
    "FileEditTool",
    "FileRollbackTool",
    "FileDiffTool",
    "VerifyTool",
    "DelegateToExternalCoderTool",
    "GrepTool",
    "GlobTool",
    "CapabilitiesTool",
    "FindRelevantToolsTool",
    "WebSearchTool",
    "WebFetchTool",
    "SkillsCreatorTool",
    "WeatherTool",
    "SystemSettingsTool",
    "MemoryQueryTool",
    "ScheduleTool",
    "PrepareChatAttachmentsTool",
    "ReadChatAttachmentTool",

    # Skills
    "SkillIndexer",
    "SkillLoader",
    "SkillRunner",
    "SkillMetadata",
    "SkillContent",
    "SkillResult",
]
