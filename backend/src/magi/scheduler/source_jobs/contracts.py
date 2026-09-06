"""Shared contracts for source sync job persistence."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Optional, Protocol


class _SourceJobRepositoryHost(Protocol):
    def _connect(self) -> Any: ...

    async def get_source_sync_job(self, job_id: str) -> Optional[dict[str, object]]: ...


@dataclass(frozen=True, slots=True)
class SourceSyncEnqueueResult:
    """Identifiers created by one atomic source-sync admission."""

    job_id: str
    execution_id: str


@dataclass(frozen=True, slots=True)
class SourceSyncSuccessSettlement:
    """Result of one idempotent source-sync success transaction."""

    committed: bool
    continuation_job_id: str | None = None
    continuation_execution_id: str | None = None
