from __future__ import annotations

import pytest
import sys
from pathlib import Path

_plugins_path = Path(__file__).resolve().parents[2] / "plugins"
if str(_plugins_path) not in sys.path:
    sys.path.insert(0, str(_plugins_path))

from calendar_plugin.exceptions import (
    CalendarError,
    PlatformNotSupportedError,
    EventKitNotAvailableError,
    AuthorizationDeniedError,
    EventKitQueryError,
)


def test_calendar_error_base():
    """Test CalendarError base exception."""
    error = CalendarError("Test error")
    assert str(error) == "Test error"


def test_platform_not_supported_error():
    """Test PlatformNotSupportedError has default message."""
    error = PlatformNotSupportedError()
    assert "macOS" in str(error) or "iOS" in str(error)


def test_eventkit_not_available_error():
    """Test EventKitNotAvailableError has default message."""
    error = EventKitNotAvailableError()
    assert "EventKit" in str(error)


def test_authorization_denied_error():
    """Test AuthorizationDeniedError includes context."""
    error = AuthorizationDeniedError("calendar")
    assert error.resource == "calendar"
    assert "calendar" in str(error)


def test_eventkit_query_error():
    """Test EventKitQueryError with optional query type."""
    error1 = EventKitQueryError("Query failed")
    assert str(error1) == "Query failed"

    error2 = EventKitQueryError("Query failed", query_type="events")
    assert "events" in str(error2)


def test_participant_creation():
    """Test Participant dataclass creation."""
    from calendar_plugin.types import Participant

    participant = Participant(
        name="John Doe",
        email="john@example.com",
        status="accepted"
    )
    assert participant.name == "John Doe"
    assert participant.email == "john@example.com"
    assert participant.status == "accepted"


def test_participant_optional_email():
    """Test Participant with None email."""
    from calendar_plugin.types import Participant

    participant = Participant(
        name="Jane Doe",
        email=None,
        status="pending"
    )
    assert participant.name == "Jane Doe"
    assert participant.email is None
    assert participant.status == "pending"


def test_calendar_event_creation():
    """Test CalendarEvent dataclass creation."""
    from datetime import datetime
    from calendar_plugin.types import CalendarEvent

    event = CalendarEvent(
        event_id="test-123",
        title="Team Meeting",
        start_time=datetime(2026, 3, 12, 10, 0),
        end_time=datetime(2026, 3, 12, 11, 0),
        is_all_day=False,
        location="Conference Room A",
        notes="Discuss project roadmap",
        calendar_name="Work",
        calendar_color="#FF0000",
        participants=[],
        is_recurring=False,
        recurrence_rule=None,
        url=None
    )

    assert event.event_id == "test-123"
    assert event.title == "Team Meeting"
    assert event.is_all_day is False
    assert event.location == "Conference Room A"
    assert event.calendar_name == "Work"


def test_calendar_event_with_participants():
    """Test CalendarEvent with participants."""
    from datetime import datetime
    from calendar_plugin.types import CalendarEvent, Participant

    participants = [
        Participant(name="Alice", email="alice@example.com", status="accepted"),
        Participant(name="Bob", email="bob@example.com", status="declined"),
    ]

    event = CalendarEvent(
        event_id="test-456",
        title="Review Meeting",
        start_time=datetime(2026, 3, 12, 14, 0),
        end_time=datetime(2026, 3, 12, 15, 0),
        is_all_day=False,
        location=None,
        notes=None,
        calendar_name="Default",
        calendar_color="#0000FF",
        participants=participants,
        is_recurring=True,
        recurrence_rule="FREQ=WEEKLY",
        url="https://example.com/event"
    )

    assert len(event.participants) == 2
    assert event.is_recurring is True
    assert event.recurrence_rule == "FREQ=WEEKLY"