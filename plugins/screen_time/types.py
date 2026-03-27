from __future__ import annotations

from dataclasses import dataclass
@dataclass(slots=True)
class HourlyAppUsage:
    """Hourly aggregate for a single frontmost app."""

    bucket_start: str
    bucket_end: str
    bundle_id: str
    app_name: str
    duration_seconds: int
    session_count: int
