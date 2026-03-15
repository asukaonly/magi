"""Runtime skill module lifecycle service."""

from __future__ import annotations

from typing import Any, Dict
import logging

import yaml

from ...config.loader import get_config_file_path

logger = logging.getLogger(__name__)

_skill_indexer = None
_skill_loader = None
_skill_executor = None


def _get_enabled_skill_names() -> set[str]:
    config_path = get_config_file_path()
    if not config_path.exists():
        return set()
    try:
        with open(config_path, "r", encoding="utf-8") as f:
            raw = yaml.safe_load(f) or {}
        tools = raw.get("tools", {}) if isinstance(raw.get("tools"), dict) else {}
        skills = tools.get("skills", [])
        if isinstance(skills, list):
            return set(str(s) for s in skills)
    except Exception:
        logger.exception("Failed to read enabled skills from config file")
    return set()


def get_enabled_skill_names() -> set[str]:
    """Get enabled skill names configured in runtime config."""
    return _get_enabled_skill_names()


def register_enabled_skills(skills: Dict[str, Any]) -> Dict[str, Any]:
    """Register only enabled skills into the shared tool registry."""
    from ...tools.registry import tool_registry

    enabled_skills = _get_enabled_skill_names()
    filtered_skills = (
        {name: metadata for name, metadata in skills.items() if name in enabled_skills}
        if enabled_skills
        else {}
    )
    if _skill_indexer is not None:
        tool_registry.bind_skill_indexer(_skill_indexer)
    tool_registry.register_skill_index(filtered_skills)
    logger.info(
        "Registered enabled skills into tool registry | indexed=%s enabled=%s registered=%s",
        len(skills),
        len(enabled_skills),
        len(filtered_skills),
    )
    return filtered_skills


def init_skills_module(llm_adapter=None) -> None:
    """Initialize skills runtime module."""
    global _skill_indexer, _skill_loader, _skill_executor

    from ...skills.executor import SkillExecutor
    from ...skills.indexer import SkillIndexer
    from ...skills.loader import SkillLoader

    _skill_indexer = SkillIndexer()
    _skill_loader = SkillLoader(_skill_indexer)
    _skill_executor = SkillExecutor(_skill_loader, llm_adapter)

    skills = _skill_indexer.scan_all()
    registered_skills = register_enabled_skills(skills)
    logger.info(
        "Skills module initialized | indexed=%s registered=%s",
        len(skills),
        len(registered_skills),
    )


def get_skill_indexer():
    """Get active skill indexer instance."""
    return _skill_indexer


def ensure_skill_indexer():
    """Get or create a shared skill indexer for metadata-only APIs."""
    global _skill_indexer
    if _skill_indexer is None:
        from ...skills.indexer import SkillIndexer

        _skill_indexer = SkillIndexer()
    return _skill_indexer


def get_skill_loader():
    """Get active skill loader instance."""
    return _skill_loader


def get_skill_executor():
    """Get active skill executor instance."""
    return _skill_executor
