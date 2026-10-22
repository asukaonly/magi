"""Archive search and governance contracts independent of archive storage."""

from typing import Protocol

from .models import ArchiveSearchResult


class ArchiveGovernanceUnavailable(RuntimeError):
    """The current governance snapshot could not authorize historical disclosure."""


class ArchiveSearchRepository(Protocol):
    async def search(
        self,
        *,
        query: str = "",
        limit: int = 20,
        offset: int = 0,
        event_ids: tuple[str, ...] | None = None,
    ) -> ArchiveSearchResult: ...
