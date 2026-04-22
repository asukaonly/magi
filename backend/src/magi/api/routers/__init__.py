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
from .sensors import sensors_router
from .timeline import timeline_router
from .plugins import plugins_router
from .local_embedding import local_embedding_router
from .local_reranker import local_reranker_router
from .background_tasks import background_tasks_router
from .control import control_router

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
    "sensors_router",
    "timeline_router",
    "plugins_router",
    "local_embedding_router",
    "local_reranker_router",
    "background_tasks_router",
    "control_router",
]
