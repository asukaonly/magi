"""Contracts for timeline projection queries and items."""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass, field
from typing import Any


PROJECTION_VERSION = 1


def build_window_key(*, start: float | None, end: float | None) -> str:
    """Build a stable cache key for one requested time window."""
    start_key = "open" if start is None else str(int(start))
    end_key = "open" if end is None else str(int(end))
    return f"{start_key}:{end_key}"


def build_filter_hash(*, source_type: str | None = None) -> str:
    """Build a stable hash for query-time filters."""
    payload = {"source_type": source_type or None}
    raw = json.dumps(payload, ensure_ascii=False, sort_keys=True)
    return hashlib.sha1(raw.encode("utf-8")).hexdigest()


@dataclass(slots=True)
class TimelineProjectionQuery:
    """Normalized query for one timeline projection window."""

    start: float | None = None
    end: float | None = None
    source_type: str | None = None
    limit: int = 200
    projection_version: int = PROJECTION_VERSION

    @property
    def window_key(self) -> str:
        return build_window_key(start=self.start, end=self.end)

    @property
    def filter_hash(self) -> str:
        return build_filter_hash(source_type=self.source_type)


@dataclass(slots=True)
class TimelineProjectionItem:
    """Cacheable timeline read-model item."""

    item_id: str
    window_key: str
    filter_hash: str
    item_type: str
    time_start: float
    time_end: float
    sort_time: float
    primary_event_id: str | None = None
    primary_summary_id: str | None = None
    source_event_ids: list[str] = field(default_factory=list)
    source_summary_ids: list[str] = field(default_factory=list)
    display_payload: dict[str, Any] = field(default_factory=dict)
    projection_version: int = PROJECTION_VERSION
    generated_at: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        """Return a JSON-friendly representation."""
        return asdict(self)

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "TimelineProjectionItem":
        """Create an item from a JSON-friendly representation."""
        return cls(
            item_id=str(payload["item_id"]),
            window_key=str(payload["window_key"]),
            filter_hash=str(payload["filter_hash"]),
            item_type=str(payload["item_type"]),
            time_start=float(payload["time_start"]),
            time_end=float(payload["time_end"]),
            sort_time=float(payload["sort_time"]),
            primary_event_id=payload.get("primary_event_id"),
            primary_summary_id=payload.get("primary_summary_id"),
            source_event_ids=[str(value) for value in payload.get("source_event_ids", [])],
            source_summary_ids=[str(value) for value in payload.get("source_summary_ids", [])],
            display_payload=dict(payload.get("display_payload", {})),
            projection_version=int(payload.get("projection_version", PROJECTION_VERSION)),
            generated_at=float(payload.get("generated_at", 0.0)),
        )


__all__ = [
    "PROJECTION_VERSION",
    "TimelineProjectionItem",
    "TimelineProjectionQuery",
    "build_filter_hash",
    "build_window_key",
]
