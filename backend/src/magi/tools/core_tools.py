"""Single source of truth for official core tool classes."""
from __future__ import annotations

from magi.control.tools import EnterPlanModeTool, ExitPlanModeTool, TodoWriteTool

from .builtin.ask_user_question_tool import AskUserQuestionTool
from .builtin.bash_tool import BashTool
from .builtin.capabilities_tool import CapabilitiesTool
from .builtin.delegate_to_external_coder_tool import DelegateToExternalCoderTool
from .builtin.detach_to_background_tool import DetachToBackgroundTool
from .builtin.file_diff_tool import FileDiffTool
from .builtin.file_edit_tool import FileEditTool
from .builtin.file_info_tool import FileInfoTool
from .builtin.file_list_tool import FileListTool
from .builtin.file_read_tool import FileReadTool
from .builtin.file_rollback_tool import FileRollbackTool
from .builtin.file_write_tool import FileWriteTool
from .builtin.find_relevant_tools_tool import FindRelevantToolsTool
from .builtin.glob_tool import GlobTool
from .builtin.grep_tool import GrepTool
from .builtin.image_generation_tool import ImageGenerationTool
from .builtin.memory_query_tool import MemoryQueryTool
from .builtin.powershell_tool import PowerShellTool
from .builtin.prepare_chat_attachments_tool import PrepareChatAttachmentsTool
from .builtin.read_chat_attachment_tool import ReadChatAttachmentTool
from .builtin.schedule_tool import ScheduleTool
from .builtin.system_settings_tool import SystemSettingsTool
from .builtin.trace_query_tool import TraceQueryTool
from .builtin.verify_tool import VerifyTool
from .builtin.weather_tool import WeatherTool
from .builtin.web_fetch_tool import WebFetchTool
from .builtin.web_search_tool import WebSearchTool
from .platform_tools import native_shell_tool_name


def core_tool_classes_for_os(os_name: str | None = None) -> tuple[type, ...]:
    """Return built-in tool classes with exactly one host-native shell."""
    shell_tool = (
        PowerShellTool if native_shell_tool_name(os_name) == "powershell" else BashTool
    )
    return (
        shell_tool,
        FileReadTool,
        FileWriteTool,
        FileEditTool,
        FileRollbackTool,
        FileDiffTool,
        VerifyTool,
        DelegateToExternalCoderTool,
        FileListTool,
        FileInfoTool,
        GrepTool,
        GlobTool,
        CapabilitiesTool,
        FindRelevantToolsTool,
        WebSearchTool,
        WebFetchTool,
        WeatherTool,
        SystemSettingsTool,
        MemoryQueryTool,
        TraceQueryTool,
        ScheduleTool,
        PrepareChatAttachmentsTool,
        ReadChatAttachmentTool,
        ImageGenerationTool,
        DetachToBackgroundTool,
        EnterPlanModeTool,
        ExitPlanModeTool,
        TodoWriteTool,
        AskUserQuestionTool,
    )


CORE_TOOL_CLASSES: tuple[type, ...] = core_tool_classes_for_os()


__all__ = ["CORE_TOOL_CLASSES", "core_tool_classes_for_os"]
