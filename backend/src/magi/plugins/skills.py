"""Plugin skill contributions connected to the shared index, loader and tools."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import Any

from ..skills.indexer import SkillIndexer
from ..skills.loader import SkillLoader


class PluginSkillRegistry:
    """Register packaged skills for the existing discovery and execution flow."""

    def __init__(
        self, tool_registry: Any, indexer: SkillIndexer, loader: SkillLoader
    ) -> None:
        if loader.indexer is not indexer:
            raise ValueError("Plugin skills must use the shared skill loader index")
        self._tool_registry = tool_registry
        self._indexer = indexer
        self._loader = loader

    def register(
        self,
        plugin_id: str,
        skill_id: str,
        path: Path,
        *,
        plugin_dir: Path,
        connection_id: str | None = None,
    ) -> Callable[[], None]:
        """Validate package containment and return an idempotent disposer."""
        valid, reason = self._indexer.validate_skill_name(skill_id)
        if not valid:
            raise ValueError(reason)
        root = Path(plugin_dir).resolve(strict=True)
        target = Path(path)
        target = target if target.is_absolute() else root / target
        target = target / "SKILL.md" if target.is_dir() else target
        target = target.resolve(strict=True)
        if not target.is_relative_to(root) or target.name != "SKILL.md":
            raise ValueError("Plugin skill must be a SKILL.md file inside its package")
        if target.parent.name != skill_id:
            raise ValueError("Plugin skill identifier must match its directory name")
        name = f"{connection_id or plugin_id}:{skill_id}"
        metadata, dispose_index = self._indexer.register_plugin_skill(name, target)
        try:
            dispose_tool = self._tool_registry.register_skill(
                metadata, owner_id=plugin_id
            )
        except BaseException:
            dispose_index()
            raise
        self._loader.clear_cache(name)

        def dispose() -> None:
            if self._indexer.get_metadata(name) is metadata:
                self._loader.clear_cache(name)
            dispose_tool()
            dispose_index()

        return dispose


__all__ = ["PluginSkillRegistry"]
