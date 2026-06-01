"""Active persona selection cache and registry-backed lookup."""

from __future__ import annotations

from typing import TYPE_CHECKING, Optional

from ..core.logger import get_logger

if TYPE_CHECKING:
    from .loader import PersonalityConfig

logger = get_logger(__name__)

# In-memory active persona state. Initialized from the persona registry during
# ``PersonalityModule.init()`` and kept as a runtime cache for synchronous users.
# Empty string indicates "no persona resolved yet" — callers must wait for
# ``PersonalityModule.init()`` to complete before reading.
_current_slug: str = ""
_current_config: Optional["PersonalityConfig"] = None


def get_current_personality() -> str:
    """Return the active personality slug from the runtime cache.

    Returns an empty string before ``PersonalityModule.init()`` has resolved an
    active persona from the registry. Callers should treat empty as
    "not yet initialized" rather than a valid persona slug.
    """
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

    Raises:
        ValueError: if ``name`` is empty. Use ``clear_active_persona()`` to
            reset the cache instead.
    """
    if not name:
        raise ValueError("active persona slug must be non-empty")
    global _current_slug, _current_config
    _current_slug = name
    _current_config = config
    logger.debug("In-memory active persona set to '%s'", _current_slug)
    return True


def clear_active_persona() -> None:
    """Reset the active persona cache. Intended for tests and shutdown."""
    global _current_slug, _current_config
    _current_slug = ""
    _current_config = None


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
    "clear_active_persona",
    "get_current_personality",
    "get_current_personality_config",
    "resolve_persona_config",
    "set_current_personality",
]