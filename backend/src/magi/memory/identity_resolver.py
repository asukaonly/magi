"""Runtime-to-memory identity resolution helpers."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable


@dataclass(frozen=True, slots=True)
class IdentityLink:
    """Maps a runtime account identity to a canonical memory owner id."""

    namespace: str
    runtime_user_id: str
    memory_owner_id: str


class IdentityResolver:
    """Resolves transport-facing runtime ids to canonical memory owner ids."""

    def __init__(self, *, links: Iterable[IdentityLink] | None = None, default_memory_owner_id: str = "user:self") -> None:
        self._links = {
            (link.namespace.strip().casefold(), link.runtime_user_id.strip()): link.memory_owner_id.strip()
            for link in (links or [])
            if link.namespace.strip() and link.runtime_user_id.strip() and link.memory_owner_id.strip()
        }
        self._default_memory_owner_id = default_memory_owner_id.strip() or "user:self"

    @classmethod
    def in_memory_default(
        cls,
        *,
        links: Iterable[tuple[str, str, str]] | None = None,
        default_memory_owner_id: str = "user:self",
    ) -> "IdentityResolver":
        """Create an in-memory resolver for single-user execution paths."""

        normalized_links = [
            IdentityLink(namespace=namespace, runtime_user_id=runtime_user_id, memory_owner_id=memory_owner_id)
            for namespace, runtime_user_id, memory_owner_id in (links or [])
        ]
        return cls(links=normalized_links, default_memory_owner_id=default_memory_owner_id)

    async def initialize(self) -> None:
        """Prepare resolver state."""

    async def shutdown(self) -> None:
        """Release resolver state."""

    def resolve_memory_owner_id(self, *, runtime_user_id: str | None, source: str | None) -> str:
        """Resolve the canonical memory owner for a runtime identity."""

        normalized_runtime_user_id = str(runtime_user_id or "").strip()
        normalized_source = str(source or "").strip().casefold()
        if normalized_runtime_user_id:
            linked = self._links.get((normalized_source, normalized_runtime_user_id))
            if linked:
                return linked
        return self._default_memory_owner_id


__all__ = ["IdentityLink", "IdentityResolver"]
