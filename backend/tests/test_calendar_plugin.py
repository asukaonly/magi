from __future__ import annotations

import pytest
import sys
from pathlib import Path
from unittest.mock import patch, MagicMock

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
from calendar_plugin.reader import EventKitReader


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


class MockSensor:
    """Mock sensor for testing."""
    sensor_id = "timeline.calendar"


def test_normalize_basic_event():
    """Test normalizing a basic calendar event."""
    from datetime import datetime
    from calendar_plugin.types import CalendarEvent, Participant
    from calendar_plugin.normalizers import normalize_calendar_event

    event = CalendarEvent(
        event_id="evt-001",
        title="Team Standup",
        start_time=datetime(2026, 3, 12, 9, 0),
        end_time=datetime(2026, 3, 12, 9, 15),
        is_all_day=False,
        location="Room 101",
        notes="Daily sync",
        calendar_name="Work",
        calendar_color="#FF5733",
        participants=[],
        is_recurring=True,
        recurrence_rule="FREQ=DAILY",
        url=None
    )

    sensor = MockSensor()
    result = normalize_calendar_event(event, sensor)

    assert result["event_id"] == "calendar_evt-001"
    assert result["source_type"] == "calendar"
    assert result["source_item_id"] == "calendar_evt-001"
    assert "Team Standup" in result["title"]
    assert result["occurred_at"] == datetime(2026, 3, 12, 9, 0).timestamp()
    assert "calendar" in result["tags"]
    assert "event" in result["tags"]


def test_normalize_event_with_location():
    """Test normalizing event with location."""
    from datetime import datetime
    from calendar_plugin.types import CalendarEvent, Participant
    from calendar_plugin.normalizers import normalize_calendar_event

    event = CalendarEvent(
        event_id="evt-002",
        title="Client Meeting",
        start_time=datetime(2026, 3, 12, 14, 0),
        end_time=datetime(2026, 3, 12, 15, 0),
        is_all_day=False,
        location="123 Main St",
        notes=None,
        calendar_name="Default",
        calendar_color="#00FF00",
        participants=[],
        is_recurring=False,
        recurrence_rule=None,
        url=None
    )

    sensor = MockSensor()
    result = normalize_calendar_event(event, sensor)

    assert "123 Main St" in result["summary"]
    assert any("地点" in block["value"] or "123 Main St" in block["value"]
               for block in result["content_blocks"])


def test_normalize_event_with_participants():
    """Test normalizing event with participants."""
    from datetime import datetime
    from calendar_plugin.types import CalendarEvent, Participant
    from calendar_plugin.normalizers import normalize_calendar_event

    participants = [
        Participant(name="Alice", email="alice@test.com", status="accepted"),
        Participant(name="Bob", email="bob@test.com", status="pending"),
    ]

    event = CalendarEvent(
        event_id="evt-003",
        title="Project Review",
        start_time=datetime(2026, 3, 12, 16, 0),
        end_time=datetime(2026, 3, 12, 17, 0),
        is_all_day=False,
        location=None,
        notes="Quarterly review",
        calendar_name="Work",
        calendar_color="#0000FF",
        participants=participants,
        is_recurring=False,
        recurrence_rule=None,
        url=None
    )

    sensor = MockSensor()
    result = normalize_calendar_event(event, sensor)

    # Check that participants are included in content blocks
    participant_block = next(
        (b for b in result["content_blocks"] if "Alice" in b["value"] or "Bob" in b["value"]),
        None
    )
    assert participant_block is not None


def test_normalize_all_day_event():
    """Test normalizing an all-day event."""
    from datetime import datetime
    from calendar_plugin.types import CalendarEvent, Participant
    from calendar_plugin.normalizers import normalize_calendar_event

    event = CalendarEvent(
        event_id="evt-004",
        title="Holiday",
        start_time=datetime(2026, 3, 12, 0, 0),
        end_time=datetime(2026, 3, 12, 23, 59, 59),
        is_all_day=True,
        location=None,
        notes=None,
        calendar_name="Holidays",
        calendar_color="#FFD700",
        participants=[],
        is_recurring=True,
        recurrence_rule="FREQ=YEARLY",
        url=None
    )

    sensor = MockSensor()
    result = normalize_calendar_event(event, sensor)

    assert "全天" in result["title"] or "all day" in result["title"].lower() or "Holiday" in result["title"]


def test_reader_is_available_on_non_darwin():
    """Test that reader handles non-darwin platforms gracefully."""
    with patch('sys.platform', 'win32'):
        reader = EventKitReader()
        assert reader.is_available() is False


def test_reader_get_authorization_status_unavailable():
    """Test authorization status when EventKit not available."""
    reader = EventKitReader()
    reader._is_available = False

    status = reader.get_authorization_status()
    assert status == "unavailable"


def test_reader_request_authorization_unavailable():
    """Test authorization request when EventKit not available."""
    reader = EventKitReader()
    reader._is_available = False

    result = reader.request_authorization()
    assert result is False


def test_reader_read_events_stub():
    """Test that read_events returns empty list as stub."""
    from datetime import datetime

    reader = EventKitReader()
    # Even if not available, should return empty list without error
    events = reader.read_events(
        start_date=datetime(2026, 3, 1),
        end_date=datetime(2026, 3, 12)
    )
    assert isinstance(events, list)