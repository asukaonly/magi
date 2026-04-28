"""Active persona selection cache and registry-backed lookup."""

from __future__ import annotations

from typing import TYPE_CHECKING, Optional

from ..core.logger import get_logger

if TYPE_CHECKING:
    from .loader import PersonalityConfig

logger = get_logger(__name__)

DEFAULT_PERSONALITY = "default"

# In-memory active persona state. Initialized from the persona registry during
# ``PersonalityModule.init()`` and kept as a runtime cache for synchronous users.
_current_slug: str = DEFAULT_PERSONALITY
_current_config: Optional["PersonalityConfig"] = None


def get_current_personality() -> str:
    """Return the active personality slug from the runtime cache."""
    return _current_slug


def get_current_personality_config() -> Optional["PersonalityConfig"]:
    """Return the cached config for the active persona, if loaded."""
    return _current_config


def set_current_personality(
    name: str,
    config: Optional["PersonalityConfig"] = None,
) -> bool:
    """Update the in-memory active persona cache.

    This does not write durable state. Callers that need persistence should
    update ``PersonaRepository`` as the source of truth.
    """
    global _current_slug, _current_config
    _current_slug = name or DEFAULT_PERSONALITY
    _current_config = config
    logger.debug("In-memory active persona set to '%s'", _current_slug)
    return True


async def resolve_persona_config(slug: str) -> Optional["PersonalityConfig"]:
    """Resolve ``PersonalityConfig`` by slug from cache or registry."""
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


__all__ = [
    "DEFAULT_PERSONALITY",
    "get_current_personality",
    "get_current_personality_config",
    "resolve_persona_config",
    "set_current_personality",
]