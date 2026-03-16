"""Legacy runtime services package.

Remaining modules here are pending migration into their owning layers.
"""

from .personality_state import (
    get_current_personality,
    set_current_personality,
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
    "ensure_skill_indexer",
    "get_enabled_skill_names",
    "get_skill_executor",
    "get_skill_indexer",
    "get_skill_loader",
    "init_skills_module",
    "register_enabled_skills",
]
