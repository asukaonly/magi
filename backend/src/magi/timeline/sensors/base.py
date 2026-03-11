"""Base contracts for timeline sensors."""
from __future__ import annotations

import hashlib
import time
from abc import ABC, abstractmethod
from typing import Any, Optional

from ..contracts import TimelineContentBlock, TimelineEvent
from ..sync import SensorSyncContext, SensorSyncResult


class TimelineSensorBase(ABC):
    """Shared contract for timeline source sensors."""

    sensor_id: str = "timeline.base"
    display_name: str = "Timeline Source"
    source_type: str = "unknown"
    polling_mode: str = "interval"
    default_interval: int = 15
    supports_retention_modes: tuple[str, ...] = ("retain_raw", "analyze_only")
    supports_content_blocks: tuple[str, ...] = ("text",)
    update_key_fields: tuple[str, ...] = ()
    config_schema: dict[str, Any] = {}
    relation_edge_whitelist: tuple[str, ...] = ()
    capabilities: dict[str, Any] = {}
    supports_pull_sync: bool = False
    supports_watch_mode: bool = False

    def __init__(
        self,
        *,
        retention_mode: Optional[str] = None,
        source_path: Optional[str] = None,
        fetch_page_content: bool = False,
    ) -> None:
        self.retention_mode = retention_mode or self.default_retention_mode
        self.source_path = source_path
        self.fetch_page_content = fetch_page_content

    @property
    def default_retention_mode(self) -> str:
        return "analyze_only"

    def source_item_identity(self, item: dict[str, Any]) -> str:
        identity_parts = [str(item.get(field, "")) for field in self.update_key_fields]
        return ":".join(identity_parts)

    def source_item_version_fingerprint(self, item: dict[str, Any]) -> str:
        version_parts = [str(item.get(field, "")) for field in self.update_key_fields]
        return hashlib.sha1("|".join(version_parts).encode("utf-8")).hexdigest()

    async def discover_changes(
        self,
        items: list[dict[str, Any]],
        known_fingerprints: set[str] | None = None,
    ) -> list[dict[str, Any]]:
        known = known_fingerprints or set()
        return [item for item in items if self.source_item_version_fingerprint(item) not in known]

    async def fetch_item(self, item: dict[str, Any]) -> dict[str, Any]:
        return dict(item)

    async def collect_items(self, context: SensorSyncContext) -> SensorSyncResult:
        _ = context
        raise NotImplementedError(f"{self.sensor_id} does not implement pull sync")

    @abstractmethod
    async def build_timeline_event(self, item: dict[str, Any]) -> TimelineEvent:
        """Convert a source item into a normalized timeline event."""

    async def resolve_retention_assets(self, item: dict[str, Any]) -> list[dict[str, Any]]:
        _ = item
        return []

    async def extract_candidates(self, item: dict[str, Any]) -> dict[str, Any]:
        _ = item
        return {"entities": [], "tags": [], "relation_candidates": []}

    def _build_event(
        self,
        *,
        source_item_id: str,
        title: str,
        summary: str,
        occurred_at: Optional[float] = None,
        raw_payload_ref: Optional[str] = None,
        content_blocks: Optional[list[TimelineContentBlock]] = None,
        tags: Optional[list[str]] = None,
        provenance: Optional[dict[str, Any]] = None,
    ) -> TimelineEvent:
        now = time.time()
        event_id = f"{self.source_type}:{source_item_id}"
        return TimelineEvent(
            event_id=event_id,
            source_type=self.source_type,
            source_item_id=source_item_id,
            occurred_at=float(occurred_at or now),
            captured_at=now,
            title=title,
            summary=summary,
            retention_mode=self.retention_mode,
            raw_payload_ref=raw_payload_ref,
            content_blocks=list(content_blocks or []),
            tags=list(tags or []),
            processing_status={"stored": False, "analyzed": False},
            provenance=provenance or {"sensor_id": self.sensor_id},
        )
