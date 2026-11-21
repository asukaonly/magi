"""Archive search and governance contracts independent of archive storage."""

from typing import Literal, Protocol

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
        start_time: float | None = None,
        end_time: float | None = None,
        layer: Literal["l1", "l3"] | None = None,
        source_filters: tuple[str, ...] | None = None,
    ) -> ArchiveSearchResult: ...
