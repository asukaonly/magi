"""Container-backed providers for skills-domain runtime services."""

from __future__ import annotations

from typing import TYPE_CHECKING, cast

from ..core.container import require_binding

if TYPE_CHECKING:
    from .indexer import SkillIndexer
    from .loader import SkillLoader




def resolve_skill_indexer() -> "SkillIndexer":
    """Return the active skill indexer binding."""
    return cast("SkillIndexer", require_binding("skill_indexer"))


def resolve_skill_loader() -> "SkillLoader":
    """Return the active skill loader binding."""
    return cast("SkillLoader", require_binding("skill_loader"))
