"""Timeline application configuration models."""

from __future__ import annotations

from enum import Enum
from typing import List, Optional

from pydantic import BaseModel, Field


class TimelineSyncMode(str, Enum):
    """Timeline source sync mode."""

    MANUAL = "manual"
    INTERVAL = "interval"
    WATCH = "watch"


class TimelineRetentionMode(str, Enum):
    """Timeline raw-data retention behavior."""

    RETAIN_RAW = "retain_raw"
    ANALYZE_ONLY = "analyze_only"


class TimelineStorageMode(str, Enum):
    """Timeline asset storage mode."""

    MANAGED = "managed"
    EXTERNAL_REFERENCE = "external_reference"


class TimelineSourceSettings(BaseModel):
    """Per-source timeline ingestion settings."""

    enabled: bool = Field(default=True)
    sync_mode: TimelineSyncMode = Field(default=TimelineSyncMode.INTERVAL)
    sync_interval_minutes: int = Field(default=15, ge=1)
    default_retention_mode: TimelineRetentionMode = Field(default=TimelineRetentionMode.ANALYZE_ONLY)
    storage_mode: TimelineStorageMode = Field(default=TimelineStorageMode.MANAGED)
    source_path: Optional[str] = Field(default=None)
    fetch_page_content: bool = Field(default=False)
    edge_whitelist: List[str] = Field(default_factory=list)


class TimelineSourcesSettings(BaseModel):
    """Timeline source collection settings."""

    photo_library: TimelineSourceSettings = Field(
        default_factory=lambda: TimelineSourceSettings(
            enabled=False,
            sync_mode=TimelineSyncMode.MANUAL,
            sync_interval_minutes=60,
            default_retention_mode=TimelineRetentionMode.ANALYZE_ONLY,
            storage_mode=TimelineStorageMode.EXTERNAL_REFERENCE,
            edge_whitelist=["CAPTURED", "RELATED_TO", "INTERACTED_WITH", "CREATED"],
        )
    )


class TimelineSettings(BaseModel):
    """Timeline domain settings."""

    sources: TimelineSourcesSettings = Field(default_factory=TimelineSourcesSettings)


__all__ = [
    "TimelineRetentionMode",
    "TimelineSettings",
    "TimelineSourceSettings",
    "TimelineSourcesSettings",
    "TimelineStorageMode",
    "TimelineSyncMode",
]