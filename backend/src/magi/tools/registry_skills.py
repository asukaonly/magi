"""Skill index helpers for ToolRegistry."""

from __future__ import annotations

import logging
from collections.abc import Callable
from typing import TYPE_CHECKING, Any, Optional

if TYPE_CHECKING:
    from ..skills.schema import SkillMetadata

logger = logging.getLogger(__name__)


class ToolRegistrySkillMixin:
    """Manage skill metadata registered alongside tools."""

    _skills: dict[str, "SkillMetadata"]
    _skill_indexer: Any

    def register_skill_index(self, skills: dict[str, "SkillMetadata"]) -> None:
        """
        register Skill index

        Args:
            skills: {name: SkillMetadata} dictionary
        """
        self._skills = {**skills, **getattr(self, "_owned_skills", {})}
        logger.info(f"Registered {len(skills)} skills to registry")

    def register_skill(self, metadata: "SkillMetadata", *, owner_id: object) -> Callable[[], None]:
        """Register one contribution without allowing stale unloads to remove it."""
        if metadata.name in self._skills:
            raise ValueError(f"Skill is already registered: {metadata.name}")
        if not hasattr(self, "_owned_skills"):
            self._owned_skills: dict[str, "SkillMetadata"] = {}
        self._owned_skills[metadata.name] = metadata
        self._skills[metadata.name] = metadata

        def dispose() -> None:
            if self._owned_skills.get(metadata.name) is metadata:
                del self._owned_skills[metadata.name]
                if self._skills.get(metadata.name) is metadata:
                    del self._skills[metadata.name]
                self.remove_model_names(f"skill_{metadata.name}")

        return dispose

    def bind_skill_indexer(self, skill_indexer: Any) -> None:
        """Bind the skill indexer used for refresh operations."""
        self._skill_indexer = skill_indexer

    def get_skill_names(self) -> list[str]:
        """
        Get all registered skill names.

        Returns:
            List of skill names.
        """
        return list(self._skills.keys())

    def get_skill_metadata(self, name: str) -> Optional["SkillMetadata"]:
        """
        Get skill metadata by name.

        Args:
            name: Skill name.

        Returns:
            SkillMetadata or None.
        """
        return self._skills.get(name)

    def is_skill(self, name: str) -> bool:
        """
        Check if name is a skill.

        Args:
            name: Tool or skill name.

        Returns:
            True if it is a skill.
        """
        return name in self._skills

    def refresh_skills(self) -> dict[str, "SkillMetadata"]:
        """
        Refresh skills index.

        Returns:
            Updated skills dictionary.
        """
        if self._skill_indexer:
            skills = self._skill_indexer.refresh()
            self.register_skill_index(skills)
            return dict(self._skills)
        return {}


__all__ = ["ToolRegistrySkillMixin"]
