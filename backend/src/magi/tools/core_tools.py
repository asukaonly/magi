"""Single source of truth for official core tool classes."""
from __future__ import annotations

from .builtin.agent_tool import AgentTool
from .builtin.bash_tool import BashTool
from .builtin.capabilities_tool import CapabilitiesTool
from .builtin.file_edit_tool import FileEditTool
from .builtin.file_read_tool import FileReadTool
from .builtin.file_write_tool import FileWriteTool
from .builtin.glob_tool import GlobTool
from .builtin.grep_tool import GrepTool
from .builtin.image_generation_tool import ImageGenerationTool
from .builtin.system_settings_tool import SystemSettingsTool
from .builtin.weather_tool import WeatherTool
from .builtin.web_fetch_tool import WebFetchTool
from .builtin.web_search_tool import WebSearchTool
from .builtin.memory_query_tool import MemoryQueryTool

CORE_TOOL_CLASSES: tuple[type, ...] = (
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
    MemoryQueryTool,
    ImageGenerationTool,
)

