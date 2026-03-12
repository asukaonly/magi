from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import List, Optional


@dataclass
class AppUsage:
    """Application usage data."""

    bundle_id: str                    # Application bundle ID
    app_name: str                  # Application name
    usage_seconds: int              # Usage duration in seconds
    category: Optional[str]        # Category (social, productivity, entertainment, etc)


@dataclass
class DailyScreenTime:
    """Daily screen time summary."""

    date: date                          # Date
    total_duration: int             # Total usage duration in seconds
    app_usages: List[AppUsage]   # Per-application usage details
