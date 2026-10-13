"""Read-only historical archive search for Memory Recall."""

from __future__ import annotations

from pathlib import Path

from fastapi import HTTPException
from pydantic import BaseModel, ConfigDict, Field

from magi.memory.archives.models import ArchiveSearchResult
from magi.memory.archives.reader import ArchiveGovernanceUnavailable, ArchiveReader

from .dependencies import _resolve_unified_memory
from .helpers import memory_t
from .router import memory_router


class ArchiveSearchRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    query: str = Field(default="", max_length=2000)
    limit: int = Field(default=20, ge=1, le=100)
    offset: int = Field(default=0, ge=0, le=10000)


@memory_router.post("/archives/search", response_model=ArchiveSearchResult)
async def search_archives(request: ArchiveSearchRequest) -> ArchiveSearchResult:
    memory = _resolve_unified_memory()
    archive_dir = getattr(memory, "_archive_dir", None)
    memory_db_path = getattr(memory, "memory_db_path", None)
    if archive_dir is None or not memory_db_path:
        raise HTTPException(
            status_code=503,
            detail=memory_t(
                "memory.errors.system_uninitialized",
                "Memory system not initialized",
            ),
        )
    captured_epoch = memory.memory_operation_epoch()
    try:
        if memory.memory_clear_in_progress():
            raise ArchiveGovernanceUnavailable("Memory clear is in progress")
        async with memory.memory_operation_guard():
            if (
                memory.memory_clear_in_progress()
                or captured_epoch != memory.memory_operation_epoch()
            ):
                raise ArchiveGovernanceUnavailable("Memory governance changed")
            result = await ArchiveReader(
                archive_dir=Path(archive_dir),
                memory_db_path=memory_db_path,
            ).search(query=request.query, limit=request.limit, offset=request.offset)
            if (
                memory.memory_clear_in_progress()
                or captured_epoch != memory.memory_operation_epoch()
            ):
                raise ArchiveGovernanceUnavailable("Memory governance changed")
            return result
    except ArchiveGovernanceUnavailable as exc:
        raise HTTPException(
            status_code=503,
            detail=memory_t(
                "memory.errors.archive_unavailable",
                "Historical archive access is temporarily unavailable",
            ),
        ) from exc
