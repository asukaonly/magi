"""Shared skills service access for runtime wiring and API routes."""

from __future__ import annotations

from dataclasses import dataclass
import logging
from typing import Any

from ..config import get_config

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class SkillsRuntimeBindings:
    skill_indexer: Any
    skill_loader: Any
    skill_runner: Any


def _get_enabled_skill_names() -> set[str]:
    try:
        skills = get_config().tools.skills
        if isinstance(skills, list):
            return {str(skill) for skill in skills}
    except Exception:
        logger.exception("Failed to read enabled skills from runtime config")
    return set()


def get_enabled_skill_names() -> set[str]:
    """Get enabled skill names configured in runtime config."""

    return _get_enabled_skill_names()


def register_enabled_skills(skills: dict[str, Any]) -> dict[str, Any]:
    """Register only enabled skills into the shared tool registry."""

    return register_enabled_skills_with_indexer(skills=skills, skill_indexer=None)


def register_enabled_skills_with_indexer(*, skills: dict[str, Any], skill_indexer: Any) -> dict[str, Any]:
    """Register only enabled skills into the shared tool registry."""

    from ..tools.registry import tool_registry

    enabled_skills = _get_enabled_skill_names()
    filtered_skills = (
        {name: metadata for name, metadata in skills.items() if name in enabled_skills}
        if enabled_skills
        else {}
    )
    if skill_indexer is not None:
        tool_registry.bind_skill_indexer(skill_indexer)
    tool_registry.register_skill_index(filtered_skills)
    logger.info(
        "Registered enabled skills into tool registry | indexed=%s enabled=%s registered=%s",
        len(skills),
        len(enabled_skills),
        len(filtered_skills),
    )
    return filtered_skills


def build_skills_runtime(llm_adapter=None, permission_gateway_provider=None) -> SkillsRuntimeBindings:
    """Build shared skills runtime services without storing module-level globals."""

    from .runner import SkillRunner
    from .indexer import SkillIndexer
    from .loader import SkillLoader

    skill_indexer = SkillIndexer()
    skill_loader = SkillLoader(skill_indexer)
    skill_runner = SkillRunner(
        skill_loader,
        llm_adapter,
        permission_gateway_provider=permission_gateway_provider,
    )

    skills = skill_indexer.scan_all()
    registered_skills = register_enabled_skills_with_indexer(skills=skills, skill_indexer=skill_indexer)
    logger.info(
        "Skills module initialized | indexed=%s registered=%s",
        len(skills),
        len(registered_skills),
    )
    return SkillsRuntimeBindings(
        skill_indexer=skill_indexer,
        skill_loader=skill_loader,
        skill_runner=skill_runner,
    )
