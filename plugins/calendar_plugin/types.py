from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import List, Optional


@dataclass
class Participant:
    """Meeting participant."""

    name: str
    email: Optional[str]
    status: str  # "accepted", "declined", "tentative", "pending"


@dataclass
class CalendarEvent:
    """Calendar event data."""

    event_id: str              # Unique identifier (EKEvent.eventIdentifier)
    title: str                 # Event title
    start_time: datetime       # Start datetime
    end_time: datetime         # End datetime
    is_all_day: bool           # All-day event flag
    location: Optional[str]    # Location string
    notes: Optional[str]       # Event notes/description
    calendar_name: str         # Source calendar name
    calendar_color: str        # Calendar color (hex)
    participants: List[Participant]  # List of participants
    is_recurring: bool         # Is this a recurring event
    recurrence_rule: Optional[str]   # Recurrence rule (if recurring)
    url: Optional[str]         # Event URL (if any)


@dataclass
class CalendarListEntry:
    """Selectable calendar source exposed to the settings UI."""

    calendar_id: str
    title: str
    source_id: str
    source_title: str
    accent_color: Optional[str]
