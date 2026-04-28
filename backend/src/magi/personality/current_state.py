"""Compatibility facade for active persona state access.

New code should import from ``magi.personality.active_persona``. This module
remains so older call sites can keep working while the registry-backed active
persona boundary is migrated.
"""

from __future__ import annotations

from .active_persona import (
    DEFAULT_PERSONALITY,
    get_current_personality,
    get_current_personality_config,
    resolve_persona_config,
    set_current_personality,
)

__all__ = [
    "DEFAULT_PERSONALITY",
    "get_current_personality",
    "get_current_personality_config",
    "resolve_persona_config",
    "set_current_personality",
]
