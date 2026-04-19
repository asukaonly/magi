"""Current personality selection state access (in-memory).

The active persona slug is held in a module-level variable and
synchronized with the persona registry at boot time.  No filesystem
I/O is performed; the registry (SQLite) is the durable source of
truth.
"""

from __future__ import annotations

from ..core.logger import get_logger

logger = get_logger(__name__)

DEFAULT_PERSONALITY = "default"

# In-memory active persona slug.  Initialized from the persona
# registry during ``PersonalityModule.init()``.
_current_slug: str = DEFAULT_PERSONALITY


def get_current_personality() -> str:
    """Return the active personality slug (in-memory)."""
    return _current_slug


def set_current_personality(name: str) -> bool:
    """Update the in-memory active personality slug.

    This does **not** write to the filesystem.  Callers that need
    durable persistence should also update ``PersonaRepository``.
    """
    global _current_slug
    _current_slug = name or DEFAULT_PERSONALITY
    logger.debug("In-memory active personality set to '%s'", _current_slug)
    return True
