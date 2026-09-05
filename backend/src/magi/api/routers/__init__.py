"""
API Router

Contains all API route modules.
"""
from .tools import tools_router
from .memory import memory_router
from .messages import user_messages_router
from .config import config_router
from .llm import llm_router
from .personality_config import personality_config_router
from .personality_presets import personality_presets_router
from .personas import personas_router
from .skills import skills_router
from .hooks import hooks_router
from .sources import sources_router
from .timeline import timeline_router
from .plugins import plugins_router
from .local_embedding import local_embedding_router
from .local_reranker import local_reranker_router
from .background_tasks import background_tasks_router
from .commands import commands_router
from .control import control_router
from .mcp import mcp_router
from .schedules import schedules_router
from .code_agent import code_agent_router
from .profile import profile_router
from .availability_routes import availability_router
from .chat_preview_routes import chat_preview_router
from .system_suggestions_routes import system_suggestions_router
from .notifications_routes import notifications_router
from .channels_bindings import channels_bindings_router

__all__ = [
    "tools_router",
    "memory_router",
    "user_messages_router",
    "config_router",
    "llm_router",
    "personality_config_router",
    "personality_presets_router",
    "personas_router",
    "skills_router",
    "hooks_router",
    "sources_router",
    "timeline_router",
    "plugins_router",
    "local_embedding_router",
    "local_reranker_router",
    "background_tasks_router",
    "commands_router",
    "control_router",
    "mcp_router",
    "schedules_router",
    "code_agent_router",
    "profile_router",
    "availability_router",
    "chat_preview_router",
    "system_suggestions_router",
    "notifications_router",
    "channels_bindings_router",
]
