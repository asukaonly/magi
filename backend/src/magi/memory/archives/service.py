"""Fence historical reads against concurrent forgetting and full memory clears."""

from collections.abc import Callable
from contextlib import AbstractAsyncContextManager

from .models import ArchiveSearchResult
from .ports import ArchiveGovernanceUnavailable, ArchiveSearchRepository


class MemoryArchiveSearch:
    def __init__(
        self,
        *,
        repository: ArchiveSearchRepository,
        operation_guard: Callable[[], AbstractAsyncContextManager[None]],
        operation_epoch: Callable[[], int],
        clear_in_progress: Callable[[], bool],
    ) -> None:
        self._repository = repository
        self._operation_guard = operation_guard
        self._operation_epoch = operation_epoch
        self._clear_in_progress = clear_in_progress

    async def search(
        self,
        *,
        query: str = "",
        limit: int = 20,
        offset: int = 0,
        event_ids: tuple[str, ...] | None = None,
    ) -> ArchiveSearchResult:
        epoch = self._operation_epoch()
        self._check_epoch(epoch)
        async with self._operation_guard():
            self._check_epoch(epoch)
            result = await self._repository.search(
                query=query, limit=limit, offset=offset, event_ids=event_ids
            )
            self._check_epoch(epoch)
            return result

    def _check_epoch(self, epoch: int) -> None:
        if self._clear_in_progress() or epoch != self._operation_epoch():
            raise ArchiveGovernanceUnavailable("Memory governance changed")
