"""Container-backed providers for skills-domain runtime services."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, cast

from ..core.container import get_container

if TYPE_CHECKING:
    from .indexer import SkillIndexer
    from .loader import SkillLoader


def _require_skills_binding(provider_name: str) -> Any:
    provider = getattr(get_container(), provider_name)
    instance = provider()
    if instance is None:
        raise RuntimeError(f"{provider_name} binding is not initialized")
    if type(instance).__name__ == "object" and not provider.overridden:
        raise RuntimeError(f"{provider_name} binding is not initialized")
    return instance


def resolve_skill_indexer() -> "SkillIndexer":
    """Return the active skill indexer binding."""
    return cast("SkillIndexer", _require_skills_binding("skill_indexer"))


def resolve_skill_loader() -> "SkillLoader":
    """Return the active skill loader binding."""
    return cast("SkillLoader", _require_skills_binding("skill_loader"))
