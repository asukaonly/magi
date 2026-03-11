"""
APIroute器

containsallAPIroutemodule
"""
from .agents import agents_router
from .tasks import tasks_router
from .tools import tools_router
from .memory import memory_router
from .metrics import metrics_router
from .messages import user_messages_router
from .config import config_router
from .personality_config import personality_config_router
from .personality_presets import personality_presets_router
from .others import others_router
from .skills import skills_router
from .timeline import timeline_router
from .plugins import plugins_router

__all__ = [
    "agents_router",
    "tasks_router",
    "tools_router",
    "memory_router",
    "metrics_router",
    "user_messages_router",
    "config_router",
    "personality_config_router",
    "personality_presets_router",
    "others_router",
    "skills_router",
    "timeline_router",
    "plugins_router",
]
