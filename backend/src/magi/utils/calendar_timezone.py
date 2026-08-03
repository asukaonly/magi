"""Stable IANA timezone identifiers for calendar-sensitive persistence."""

from __future__ import annotations

from typing import Any, Mapping
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from tzlocal import get_localzone_name

TEMPORAL_METADATA_KEY = "_temporal"
CALENDAR_TIMEZONE_ID_KEY = "calendar_timezone_id"


def canonical_timezone_id(value: Any) -> str | None:
    """Return a validated IANA timezone identifier."""

    timezone_id = str(value or "").strip()
    if not timezone_id:
        return None
    try:
        zone = ZoneInfo(timezone_id)
    except (ValueError, ZoneInfoNotFoundError):
        return None
    return zone.key


def calendar_timezone_id_from_metadata(metadata: Mapping[str, Any] | None) -> str | None:
    """Read the host-owned calendar timezone from event metadata."""

    if not isinstance(metadata, Mapping):
        return None
    temporal = metadata.get(TEMPORAL_METADATA_KEY)
    if not isinstance(temporal, Mapping):
        return None
    return canonical_timezone_id(temporal.get(CALENDAR_TIMEZONE_ID_KEY))


def local_calendar_timezone_id() -> str | None:
    """Resolve the current system timezone as an IANA identifier."""

    try:
        return canonical_timezone_id(get_localzone_name())
    except (OSError, RuntimeError, ZoneInfoNotFoundError):
        return None


def with_calendar_timezone(
    metadata: Mapping[str, Any] | None,
    *,
    calendar_timezone_id: str | None,
) -> dict[str, Any] | None:
    """Persist a validated calendar timezone without mutating caller metadata."""

    normalized_timezone_id = canonical_timezone_id(calendar_timezone_id)
    if normalized_timezone_id is None:
        return dict(metadata) if metadata else None
    merged = dict(metadata or {})
    raw_temporal = merged.get(TEMPORAL_METADATA_KEY)
    temporal = dict(raw_temporal) if isinstance(raw_temporal, Mapping) else {}
    temporal[CALENDAR_TIMEZONE_ID_KEY] = normalized_timezone_id
    merged[TEMPORAL_METADATA_KEY] = temporal
    return merged


__all__ = [
    "CALENDAR_TIMEZONE_ID_KEY",
    "TEMPORAL_METADATA_KEY",
    "calendar_timezone_id_from_metadata",
    "canonical_timezone_id",
    "local_calendar_timezone_id",
    "with_calendar_timezone",
]
