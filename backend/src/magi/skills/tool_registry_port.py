"""Structural port for the tool registry, as seen by the skills layer.

The skills layer (L8) registers skill metadata into — and reads the tool
list from — the shared tool registry, which is a *sibling* L8 module
(``magi.tools.registry``). Importing ``tools`` from ``skills`` would be a
cross-sibling edge with ``tools`` ordered above ``skills``; to keep the
dependency pointing downward, ``skills`` depends only on this Protocol and
the composition root injects the concrete ``tool_registry`` (which satisfies
it structurally). This module MUST NOT import ``magi.tools``.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Optional, Protocol, runtime_checkable

if TYPE_CHECKING:
    from .schema import SkillMetadata


@runtime_checkable
class ToolRegistryPort(Protocol):
    """The subset of the tool registry that the skills layer uses."""

    def list_tools(
        self,
        category: Optional[str] = None,
        tags: Optional[list[str]] = None,
        enabled_features: Optional[list[str]] = None,
    ) -> list[str]:
        """Return the names of registered tools (subagent tool exposure)."""
        ...

    def register_skill_index(self, skills: dict[str, "SkillMetadata"]) -> None:
        """Register the enabled-skill metadata index alongside the tools."""
        ...

    def bind_skill_indexer(self, skill_indexer: object) -> None:
        """Bind the skill indexer used for refresh operations."""
        ...


__all__ = ["ToolRegistryPort"]
