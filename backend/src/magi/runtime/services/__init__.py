"""Runtime services — personality state, message bus, and skills lifecycle."""

from .personality_state import (
    get_current_personality,
    set_current_personality,
)
from .message_bus import (
    get_message_bus,
    set_message_bus,
)
from .skills import (
    ensure_skill_indexer,
    get_enabled_skill_names,
    get_skill_executor,
    get_skill_indexer,
    get_skill_loader,
    init_skills_module,
    register_enabled_skills,
)

__all__ = [
    "get_current_personality",
    "set_current_personality",
    "get_message_bus",
    "set_message_bus",
    "ensure_skill_indexer",
    "get_enabled_skill_names",
    "get_skill_executor",
    "get_skill_indexer",
    "get_skill_loader",
    "init_skills_module",
    "register_enabled_skills",
]
