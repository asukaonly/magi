"""Shared contracts for sensor sync job persistence."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Optional, Protocol


class _SensorJobRepositoryHost(Protocol):
    def _connect(self) -> Any: ...

    async def get_sensor_sync_job(self, job_id: str) -> Optional[dict[str, object]]: ...


@dataclass(frozen=True, slots=True)
class SensorSyncEnqueueResult:
    """Identifiers created by one atomic sensor-sync admission."""

    job_id: str
    execution_id: str
