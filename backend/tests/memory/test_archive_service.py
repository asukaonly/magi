"""Archive governance fences apply to internal callers and alternate repositories."""

from contextlib import asynccontextmanager
from unittest.mock import AsyncMock

import pytest

from magi.memory.archives.models import ArchiveSearchResult
from magi.memory.archives.ports import ArchiveGovernanceUnavailable
from magi.memory.archives.service import MemoryArchiveSearch


@pytest.mark.asyncio
async def test_pathless_archive_repository_is_fenced_before_and_after_read():
    epoch = 0
    clearing = False
    guarded = False

    @asynccontextmanager
    async def guard():
        nonlocal guarded
        guarded = True
        try:
            yield
        finally:
            guarded = False

    async def search(**kwargs):
        assert guarded
        return ArchiveSearchResult(items=[], total=0, limit=kwargs["limit"], offset=kwargs["offset"])

    repository = AsyncMock()
    repository.search.side_effect = search
    service = MemoryArchiveSearch(
        repository=repository, operation_guard=guard,
        operation_epoch=lambda: epoch, clear_in_progress=lambda: clearing,
    )
    assert (await service.search(query="garden")).total == 0
    clearing = True
    with pytest.raises(ArchiveGovernanceUnavailable):
        await service.search()
    assert repository.search.await_count == 1
    clearing = False

    async def invalidating_search(**kwargs):
        nonlocal epoch
        result = await search(**kwargs)
        epoch += 1
        return result

    repository.search.side_effect = invalidating_search
    with pytest.raises(ArchiveGovernanceUnavailable):
        await service.search()
    assert not guarded
