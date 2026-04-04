"""
API Router

Contains all API route modules.
"""
from .tools import tools_router
from .memory import memory_router
from .metrics import metrics_router
from .messages import user_messages_router
from .config import config_router
from .llm import llm_router
from .personality_config import personality_config_router
from .personality_presets import personality_presets_router
from .skills import skills_router
from .sensors import sensors_router
from .timeline import timeline_router
from .plugins import plugins_router
from .schedules import schedules_router
from .tasks import tasks_router
from .local_embedding import local_embedding_router
from .local_reranker import local_reranker_router

__all__ = [
    "tools_router",
    "memory_router",
    "metrics_router",
    "user_messages_router",
    "config_router",
    "llm_router",
    "personality_config_router",
    "personality_presets_router",
    "skills_router",
    "sensors_router",
    "timeline_router",
    "plugins_router",
    "schedules_router",
    "tasks_router",
    "local_embedding_router",
    "local_reranker_router",
]
