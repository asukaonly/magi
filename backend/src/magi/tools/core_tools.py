"""Single source of truth for official core tool classes."""
from __future__ import annotations

from .builtin.agent_tool import AgentTool
from .builtin.ask_user_question_tool import AskUserQuestionTool
from .builtin.bash_tool import BashTool
from .builtin.capabilities_tool import CapabilitiesTool
from .builtin.detach_to_background_tool import DetachToBackgroundTool
from .builtin.file_diff_tool import FileDiffTool
from .builtin.file_edit_tool import FileEditTool
from .builtin.file_info_tool import FileInfoTool
from .builtin.file_list_tool import FileListTool
from .builtin.file_read_tool import FileReadTool
from .builtin.file_rollback_tool import FileRollbackTool
from .builtin.file_write_tool import FileWriteTool
from .builtin.verify_tool import VerifyTool
from .builtin.glob_tool import GlobTool
from .builtin.grep_tool import GrepTool
from .builtin.image_generation_tool import ImageGenerationTool
from .builtin.plan_mode_tool import EnterPlanModeTool, ExitPlanModeTool
from .builtin.powershell_tool import PowerShellTool
from .builtin.prepare_chat_attachments_tool import PrepareChatAttachmentsTool
from .builtin.schedule_tool import ScheduleTool
from .builtin.system_settings_tool import SystemSettingsTool
from .builtin.todo_write_tool import TodoWriteTool
from .builtin.trace_query_tool import TraceQueryTool
from .builtin.weather_tool import WeatherTool
from .builtin.web_fetch_tool import WebFetchTool
from .builtin.web_search_tool import WebSearchTool
from .builtin.memory_query_tool import MemoryQueryTool

CORE_TOOL_CLASSES: tuple[type, ...] = (
    BashTool,
    PowerShellTool,
    FileReadTool,
    FileWriteTool,
    FileEditTool,
    FileRollbackTool,
    FileDiffTool,
    VerifyTool,
    FileListTool,
    FileInfoTool,
    GrepTool,
    GlobTool,
    CapabilitiesTool,
    WebSearchTool,
    WebFetchTool,
    WeatherTool,
    SystemSettingsTool,
    AgentTool,
    MemoryQueryTool,
    TraceQueryTool,
    ScheduleTool,
    PrepareChatAttachmentsTool,
    ImageGenerationTool,
    DetachToBackgroundTool,
    EnterPlanModeTool,
    ExitPlanModeTool,
    TodoWriteTool,
    AskUserQuestionTool,
)

