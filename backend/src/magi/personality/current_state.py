"""Current personality selection state access (in-memory).

The active persona slug and its ``PersonalityConfig`` are held in
module-level variables and synchronized with the persona registry at
boot time.  No filesystem I/O is performed; the registry (SQLite) is
the durable source of truth.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Optional

from ..core.logger import get_logger

if TYPE_CHECKING:
    from .loader import PersonalityConfig

logger = get_logger(__name__)

DEFAULT_PERSONALITY = "default"

# In-memory active persona state.  Initialized from the persona
# registry during ``PersonalityModule.init()``.
_current_slug: str = DEFAULT_PERSONALITY
_current_config: Optional["PersonalityConfig"] = None


def get_current_personality() -> str:
    """Return the active personality slug (in-memory)."""
    return _current_slug


def get_current_personality_config() -> Optional["PersonalityConfig"]:
    """Return the cached ``PersonalityConfig`` for the active persona.

    Returns ``None`` when no config has been loaded yet (e.g. before
    ``PersonalityModule.init()`` completes).
    """
    return _current_config


def set_current_personality(
    name: str,
    config: Optional["PersonalityConfig"] = None,
) -> bool:
    """Update the in-memory active personality slug and config cache.

    This does **not** write to the filesystem.  Callers that need
    durable persistence should also update ``PersonaRepository``.
    """
    global _current_slug, _current_config
    _current_slug = name or DEFAULT_PERSONALITY
    _current_config = config
    logger.debug("In-memory active personality set to '%s'", _current_slug)
    return True


async def resolve_persona_config(slug: str) -> Optional["PersonalityConfig"]:
    """Resolve ``PersonalityConfig`` by slug from cache or registry.

    Returns the in-memory cached config when *slug* matches the active
    persona, otherwise queries the persona registry (SQLite).
    """
    if slug == _current_slug and _current_config is not None:
        return _current_config

    from .persona_repository import PersonaRepository
    from ..utils.runtime import get_runtime_paths

    try:
        repo = PersonaRepository(str(get_runtime_paths().persona_registry_db_path))
        await repo.init()
        record = await repo.get_by_slug(slug)
        return record.config
    except Exception:
        logger.debug("Could not resolve persona config for slug '%s' from registry", slug)
        return None
