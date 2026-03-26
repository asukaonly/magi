"""Pull-sync contracts for sensors (L9 - Awareness layer).

Moved from timeline/sync.py to decouple sensor sync from the timeline domain.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Optional, Protocol, runtime_checkable

from ..utils.runtime import RuntimePaths


@dataclass(slots=True)
class SensorSyncContext:
    """Context passed to pull-sync capable sensors."""

    source_type: str
    manual: bool
    last_cursor: Optional[str]
    last_success_at: Optional[float]
    limit: int
    runtime_paths: RuntimePaths
    plugin_settings: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class SensorSyncResult:
    """Normalized result returned by pull-sync sensors."""

    items: list[dict[str, Any]] = field(default_factory=list)
    next_cursor: Optional[str] = None
    watermark_ts: Optional[float] = None
    stats: dict[str, Any] = field(default_factory=dict)


@runtime_checkable
class PullSyncSensor(Protocol):
    """Protocol for sensors that can actively pull source data."""

    supports_pull_sync: bool

    async def collect_items(self, context: SensorSyncContext) -> SensorSyncResult:
        """Collect normalized source items for ingestion."""
