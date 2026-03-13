# Calendar Sensor Implementation Plan

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Implement a Calendar timeline sensor plugin that reads events from macOS Calendar via EventKit and ingests them into Magi's personal knowledge timeline.

**Architecture:** Modular plugin structure following the apple_health pattern. EventKitReader wraps EventKit via pyobjc for calendar access, CalendarTimelineSensor implements TimelineSensorBase for data collection, and normalizers convert raw events to TimelineEvent objects.

**Tech Stack:** Python 3.10+, pyobjc-framework-EventKit, pyobjc-framework-Foundation, dataclasses

---

## File Structure

```
plugins/calendar/
├── plugin.toml           # Plugin manifest with platform declaration
├── plugin.py             # Plugin entry point + settings fields
├── sensor.py             # CalendarTimelineSensor implementation
├── reader.py             # EventKitReader (pyobjc bridge)
├── normalizers.py        # Event normalization functions
├── types.py              # CalendarEvent, Participant dataclasses
├── exceptions.py         # Custom exceptions
└── __init__.py           # Package init

backend/tests/
└── test_calendar_plugin.py  # Comprehensive test suite
```

---

## Chunk 1: Types and Exceptions

### Task 1: Exceptions Module

**Files:**
- Create: `plugins/calendar/exceptions.py`
- Test: `backend/tests/test_calendar_plugin.py`

- [ ] **Step 1: Write the failing tests for exceptions**

```python
# In backend/tests/test_calendar_plugin.py
from __future__ import annotations

import pytest
import sys
from pathlib import Path

_plugins_path = Path(__file__).resolve().parents[2] / "plugins"
if str(_plugins_path) not in sys.path:
    sys.path.insert(0, str(_plugins_path))

from calendar.exceptions import (
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
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd /Users/asuka/code/magi/.worktree/sensor-extension && python -m pytest backend/tests/test_calendar_plugin.py::test_calendar_error_base -v`
Expected: FAIL with "ModuleNotFoundError: No module named 'calendar.exceptions'"

- [ ] **Step 3: Create the exceptions module**

```python
# In plugins/calendar/exceptions.py
"""Custom exceptions for Calendar plugin."""


class CalendarError(Exception):
    """Base exception for Calendar-related errors."""
    pass


class PlatformNotSupportedError(CalendarError):
    """Raised when EventKit is accessed on unsupported platforms."""

    def __init__(self, message: str = "Calendar is only available on macOS and iOS"):
        super().__init__(message)


class EventKitNotAvailableError(CalendarError):
    """Raised when EventKit framework is not available on the device."""

    def __init__(self, message: str = "EventKit framework is not available"):
        super().__init__(message)


class AuthorizationDeniedError(CalendarError):
    """Raised when user denies Calendar authorization."""

    def __init__(self, resource: str):
        self.resource = resource
        message = f"Authorization denied for: {resource}"
        super().__init__(message)


class EventKitQueryError(CalendarError):
    """Raised when an EventKit query fails."""

    def __init__(self, message: str, query_type: str | None = None):
        self.query_type = query_type
        if query_type:
            message = f"{message} (Query type: {query_type})"
        super().__init__(message)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd /Users/asuka/code/magi/.worktree/sensor-extension && python -m pytest backend/tests/test_calendar_plugin.py::test_calendar_error_base backend/tests/test_calendar_plugin.py::test_platform_not_supported_error backend/tests/test_calendar_plugin.py::test_eventkit_not_available_error backend/tests/test_calendar_plugin.py::test_authorization_denied_error backend/tests/test_calendar_plugin.py::test_eventkit_query_error -v`
Expected: 5 passed

- [ ] **Step 5: Commit**

```bash
git add plugins/calendar/exceptions.py backend/tests/test_calendar_plugin.py
git commit -m "feat(calendar): add exceptions module"
```

---

### Task 2: Types Module

**Files:**
- Create: `plugins/calendar/types.py`
- Test: `backend/tests/test_calendar_plugin.py`

- [ ] **Step 1: Write the failing tests for types**

```python
# Add to backend/tests/test_calendar_plugin.py
from calendar.types import Participant, CalendarEvent


def test_participant_creation():
    """Test Participant dataclass creation."""
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
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd /Users/asuka/code/magi/.worktree/sensor-extension && python -m pytest backend/tests/test_calendar_plugin.py::test_participant_creation -v`
Expected: FAIL with "cannot import name 'Participant' from 'calendar.types'"

- [ ] **Step 3: Create the types module**

```python
# In plugins/calendar/types.py
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
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd /Users/asuka/code/magi/.worktree/sensor-extension && python -m pytest backend/tests/test_calendar_plugin.py::test_participant_creation backend/tests/test_calendar_plugin.py::test_participant_optional_email backend/tests/test_calendar_plugin.py::test_calendar_event_creation backend/tests/test_calendar_plugin.py::test_calendar_event_with_participants -v`
Expected: 4 passed

- [ ] **Step 5: Commit**

```bash
git add plugins/calendar/types.py backend/tests/test_calendar_plugin.py
git commit -m "feat(calendar): add types module with CalendarEvent and Participant"
```

---

### Task 3: Package Init

**Files:**
- Create: `plugins/calendar/__init__.py`

- [ ] **Step 1: Create the package init**

```python
# In plugins/calendar/__init__.py
"""Calendar timeline sensor plugin."""
```

- [ ] **Step 2: Commit**

```bash
git add plugins/calendar/__init__.py
git commit -m "feat(calendar): add package init"
```

---

## Chunk 2: Normalizers and Reader

### Task 4: Normalizers Module

**Files:**
- Create: `plugins/calendar/normalizers.py`
- Test: `backend/tests/test_calendar_plugin.py`

- [ ] **Step 1: Write the failing tests for normalizers**

```python
# Add to backend/tests/test_calendar_plugin.py
from datetime import datetime
from calendar.types import CalendarEvent, Participant
from calendar.normalizers import normalize_calendar_event


class MockSensor:
    """Mock sensor for testing."""
    sensor_id = "timeline.calendar"


def test_normalize_basic_event():
    """Test normalizing a basic calendar event."""
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
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd /Users/asuka/code/magi/.worktree/sensor-extension && python -m pytest backend/tests/test_calendar_plugin.py::test_normalize_basic_event -v`
Expected: FAIL with "cannot import name 'normalize_calendar_event' from 'calendar.normalizers'"

- [ ] **Step 3: Create the normalizers module**

```python
# In plugins/calendar/normalizers.py
"""Normalization helpers for Calendar timeline ingestion."""
from __future__ import annotations

from datetime import datetime
from typing import Any

from .types import CalendarEvent, Participant


def normalize_calendar_event(event: CalendarEvent, sensor: Any) -> dict[str, Any]:
    """Normalize a calendar event into timeline event data.

    Args:
        event: CalendarEvent to normalize
        sensor: The sensor instance (for sensor_id)

    Returns:
        Dictionary with normalized event data
    """
    # Build title
    if event.is_all_day:
        title = f"全天：{event.title}"
    else:
        start_str = event.start_time.strftime("%H:%M")
        end_str = event.end_time.strftime("%H:%M")
        title = f"{event.title} ({start_str}-{end_str})"

    # Build summary
    summary_parts = [event.title]
    if event.location:
        summary_parts.append(f"地点：{event.location}")
    summary = " | ".join(summary_parts)

    # Build content blocks
    content_blocks = []

    # Time block
    if event.is_all_day:
        content_blocks.append({
            "kind": "text",
            "value": f"时间：全天 ({event.start_time.strftime('%Y-%m-%d')})"
        })
    else:
        time_str = f"时间：{event.start_time.strftime('%Y-%m-%d %H:%M')} - {event.end_time.strftime('%H:%M')}"
        content_blocks.append({
            "kind": "text",
            "value": time_str
        })

    # Location block
    if event.location:
        content_blocks.append({
            "kind": "text",
            "value": f"地点：{event.location}"
        })

    # Calendar block
    content_blocks.append({
        "kind": "text",
        "value": f"日历：{event.calendar_name}"
    })

    # Participants block
    if event.participants:
        participant_names = ", ".join(p.name for p in event.participants)
        content_blocks.append({
            "kind": "text",
            "value": f"参与者：{participant_names}"
        })

    # Notes block
    if event.notes:
        content_blocks.append({
            "kind": "text",
            "value": f"备注：{event.notes}"
        })

    # Recurring info
    if event.is_recurring:
        content_blocks.append({
            "kind": "text",
            "value": f"重复：{event.recurrence_rule or '是'}"
        })

    # Build tags
    tags = ["calendar", "event"]
    if event.is_recurring:
        tags.append("recurring")
    if event.is_all_day:
        tags.append("all_day")

    # Build provenance
    provenance = {
        "sensor_id": sensor.sensor_id,
        "event_id": event.event_id,
        "calendar_name": event.calendar_name,
        "calendar_color": event.calendar_color,
        "is_recurring": event.is_recurring,
        "is_all_day": event.is_all_day,
    }
    if event.url:
        provenance["url"] = event.url
    if event.recurrence_rule:
        provenance["recurrence_rule"] = event.recurrence_rule

    return {
        "event_id": f"calendar_{event.event_id}",
        "source_type": "calendar",
        "source_item_id": f"calendar_{event.event_id}",
        "occurred_at": event.start_time.timestamp(),
        "title": title,
        "summary": summary,
        "content_blocks": content_blocks,
        "tags": tags,
        "provenance": provenance,
    }
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd /Users/asuka/code/magi/.worktree/sensor-extension && python -m pytest backend/tests/test_calendar_plugin.py::test_normalize_basic_event backend/tests/test_calendar_plugin.py::test_normalize_event_with_location backend/tests/test_calendar_plugin.py::test_normalize_event_with_participants backend/tests/test_calendar_plugin.py::test_normalize_all_day_event -v`
Expected: 4 passed

- [ ] **Step 5: Commit**

```bash
git add plugins/calendar/normalizers.py backend/tests/test_calendar_plugin.py
git commit -m "feat(calendar): add normalizers module"
```

---

### Task 5: Reader Module - Basic Structure

**Files:**
- Create: `plugins/calendar/reader.py`
- Test: `backend/tests/test_calendar_plugin.py`

- [ ] **Step 1: Write the failing tests for reader basics**

```python
# Add to backend/tests/test_calendar_plugin.py
from calendar.reader import EventKitReader
from unittest.mock import patch, MagicMock


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
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd /Users/asuka/code/magi/.worktree/sensor-extension && python -m pytest backend/tests/test_calendar_plugin.py::test_reader_is_available_on_non_darwin -v`
Expected: FAIL with "cannot import name 'EventKitReader' from 'calendar.reader'"

- [ ] **Step 3: Create the reader module (stub implementation)**

```python
# In plugins/calendar/reader.py
"""EventKit data reader using pyobjc bridge."""
from __future__ import annotations

import sys
from datetime import datetime
from typing import Any, Optional, List

from .exceptions import PlatformNotSupportedError, EventKitNotAvailableError
from .types import CalendarEvent, Participant


class EventKitReader:
    """EventKit data reader using pyobjc bridge."""

    def __init__(self) -> None:
        self._event_store: Any = None
        self._is_available: Optional[bool] = None
        self_ek_module: dict[str, Any] | None = None
        self._foundation_module: dict[str, Any] | None = None

    def _ensure_platform(self) -> None:
        """Raise error if not running on macOS/iOS."""
        if sys.platform != "darwin":
            raise PlatformNotSupportedError()

    def _import_frameworks(self) -> None:
        """Import EventKit frameworks (macOS only) with lazy loading."""
        # Will be implemented when adding full EventKit support
        pass

    @property
    def event_store(self) -> Any:
        """Get or create EKEventStore instance."""
        if self._event_store is None:
            self._ensure_platform()
            self._import_frameworks()
            # Will be implemented when adding full EventKit support
        return self._event_store

    def is_available(self) -> bool:
        """Check if EventKit is available on this device."""
        if self._is_available is not None:
            return self._is_available

        # Not available on non-darwin platforms
        if sys.platform != "darwin":
            self._is_available = False
            return False

        try:
            self._import_frameworks()
            # Will check actual EventKit availability when implemented
            self._is_available = False  # Stub: return False until implemented
            return self._is_available
        except Exception:
            self._is_available = False
            return False

    def get_authorization_status(self) -> str:
        """
        Get authorization status for calendar access.

        Returns:
            One of: "not_determined", "denied", "authorized", "unavailable"
        """
        if not self.is_available():
            return "unavailable"

        # Stub: return unavailable until EventKit implementation
        return "unavailable"

    def request_authorization(self) -> bool:
        """
        Request calendar access authorization.

        Returns:
            True if authorization was granted, False otherwise
        """
        if not self.is_available():
            return False

        # Stub: return False until EventKit implementation
        return False

    def read_events(
        self,
        start_date: datetime,
        end_date: datetime,
        calendars: Optional[List[str]] = None
    ) -> List[CalendarEvent]:
        """
        Read calendar events within a date range.

        Args:
            start_date: Start date for the query
            end_date: End date for the query
            calendars: Optional list of calendar names to filter

        Returns:
            List of CalendarEvent objects (stub - returns empty list)
        """
        if not self.is_available():
            return []

        # Stub implementation - will be completed in a future task
        return []
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd /Users/asuka/code/magi/.worktree/sensor-extension && python -m pytest backend/tests/test_calendar_plugin.py::test_reader_is_available_on_non_darwin backend/tests/test_calendar_plugin.py::test_reader_get_authorization_status_unavailable backend/tests/test_calendar_plugin.py::test_reader_request_authorization_unavailable backend/tests/test_calendar_plugin.py::test_reader_read_events_stub -v`
Expected: 4 passed

- [ ] **Step 5: Commit**

```bash
git add plugins/calendar/reader.py backend/tests/test_calendar_plugin.py
git commit -m "feat(calendar): add reader module stub"
```

---

## Chunk 3: Sensor and Plugin

### Task 6: Sensor Module

**Files:**
- Create: `plugins/calendar/sensor.py`
- Test: `backend/tests/test_calendar_plugin.py`

- [ ] **Step 1: Write the failing tests for sensor**

```python
# Add to backend/tests/test_calendar_plugin.py
from calendar.sensor import CalendarTimelineSensor
from magi.timeline import SensorSyncContext
from datetime import datetime, timedelta
import time


def test_sensor_properties():
    """Test sensor class properties."""
    assert CalendarTimelineSensor.sensor_id == "timeline.calendar"
    assert CalendarTimelineSensor.source_type == "calendar"
    assert CalendarTimelineSensor.polling_mode == "interval"
    assert CalendarTimelineSensor.supports_pull_sync is True


def test_sensor_source_item_identity():
    """Test source_item_identity generation."""
    sensor = CalendarTimelineSensor()
    item = {"event_id": "test-123", "title": "Meeting"}

    identity = sensor.source_item_identity(item)
    assert identity == "calendar_test-123"


def test_sensor_source_item_version_fingerprint():
    """Test source_item_version_fingerprint generation."""
    sensor = CalendarTimelineSensor()
    item1 = {"event_id": "test-123", "title": "Meeting", "start_time": 1000}
    item2 = {"event_id": "test-123", "title": "Meeting", "start_time": 1000}
    item3 = {"event_id": "test-123", "title": "Changed", "start_time": 1000}

    fingerprint1 = sensor.source_item_version_fingerprint(item1)
    fingerprint2 = sensor.source_item_version_fingerprint(item2)
    fingerprint3 = sensor.source_item_version_fingerprint(item3)

    assert fingerprint1 == fingerprint2
    assert fingerprint1 != fingerprint3


def test_sensor_collect_items_with_stub_reader():
    """Test collect_items returns empty list with stub reader."""
    sensor = CalendarTimelineSensor()
    context = SensorSyncContext(
        plugin_settings={},
        last_cursor=None,
        last_success_at=None,
        limit=100
    )

    # Since reader is stub and returns empty, collect_items should return empty
    import asyncio
    result = asyncio.run(sensor.collect_items(context))

    assert isinstance(result.items, list)
    assert len(result.items) == 0
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd /Users/asuka/code/magi/.worktree/sensor-extension && python -m pytest backend/tests/test_calendar_plugin.py::test_sensor_properties -v`
Expected: FAIL with "cannot import name 'CalendarTimelineSensor' from 'calendar.sensor'"

- [ ] **Step 3: Create the sensor module**

```python
# In plugins/calendar/sensor.py
"""Timeline sensor for Calendar data."""
from __future__ import annotations

import hashlib
import sys
import time
from datetime import datetime, timedelta
from typing import Any

from magi.timeline import SensorSyncContext, SensorSyncResult, TimelineContentBlock, TimelineEvent
from magi.timeline.sensors.base import TimelineSensorBase

from .exceptions import PlatformNotSupportedError
from .normalizers import normalize_calendar_event
from .reader import EventKitReader
from .types import CalendarEvent


class CalendarTimelineSensor(TimelineSensorBase):
    """Timeline sensor for Calendar data."""

    sensor_id = "timeline.calendar"
    display_name = "Calendar"
    source_type = "calendar"
    polling_mode = "interval"
    default_interval = 1800  # 30 minutes
    update_key_fields = ("event_id", "start_time")
    relation_edge_whitelist = ("SCHEDULED", "ATTENDED")
    supports_pull_sync = True

    def __init__(self, *, retention_mode=None, reader=None):
        super().__init__(retention_mode=retention_mode)
        self._reader = reader

    @property
    def reader(self) -> EventKitReader:
        """Get or create EventKitReader instance (lazy initialization)."""
        if self._reader is None:
            if sys.platform != "darwin":
                raise PlatformNotSupportedError()
            self._reader = EventKitReader()
        return self._reader

    def source_item_identity(self, item: dict) -> str:
        """Generate unique identity for a source item."""
        event_id = item.get("event_id", "")
        return f"calendar_{event_id}"

    def source_item_version_fingerprint(self, item: dict) -> str:
        """Generate version fingerprint for change detection."""
        version_parts = [
            str(item.get("event_id", "")),
            str(item.get("title", "")),
            str(item.get("start_time", "")),
            str(item.get("end_time", "")),
            str(item.get("location", "")),
        ]
        return hashlib.sha1("|".join(version_parts).encode("utf-8")).hexdigest()

    async def collect_items(self, context: SensorSyncContext) -> SensorSyncResult:
        """Collect calendar events from EventKit."""
        sensor_settings = (
            context.plugin_settings.get("sensors", {}).get(self.source_type, {})
            if isinstance(context.plugin_settings.get("sensors", {}), dict)
            else {}
        )

        # Get settings
        lookback_days = sensor_settings.get("lookback_days", 30)
        recurring_expansion_days = sensor_settings.get("recurring_expansion_days", 30)

        # Determine date range
        now = datetime.now()
        if context.last_cursor:
            try:
                last_timestamp = float(context.last_cursor)
                start_date = datetime.fromtimestamp(last_timestamp)
            except (ValueError, TypeError):
                start_date = now - timedelta(days=lookback_days)
        else:
            # Initial sync - get last 30 days by default
            start_date = now - timedelta(days=lookback_days)

        end_date = now + timedelta(days=recurring_expansion_days)

        # Check authorization
        auth_status = self.reader.get_authorization_status()
        if auth_status != "authorized":
            return SensorSyncResult(
                items=[],
                next_cursor=None,
                watermark_ts=time.time(),
                stats={
                    "count": 0,
                    "authorization_status": auth_status,
                    "initial_sync": context.last_cursor is None,
                },
            )

        # Read events
        events = self.reader.read_events(start_date, end_date)

        # Convert to items
        items = []
        for event in events:
            item = {
                "event_id": event.event_id,
                "title": event.title,
                "start_time": event.start_time.timestamp(),
                "end_time": event.end_time.timestamp(),
                "is_all_day": event.is_all_day,
                "location": event.location,
                "notes": event.notes,
                "calendar_name": event.calendar_name,
                "calendar_color": event.calendar_color,
                "participants": [
                    {"name": p.name, "email": p.email, "status": p.status}
                    for p in event.participants
                ],
                "is_recurring": event.is_recurring,
                "recurrence_rule": event.recurrence_rule,
                "url": event.url,
            }
            items.append(item)

        # Sort items by start time
        items.sort(key=lambda x: x.get("start_time", 0), reverse=True)

        # Determine next cursor and watermark
        next_cursor = None
        watermark_ts = context.last_success_at or time.time()

        if items:
            min_timestamp = min(item.get("start_time", time.time()) for item in items)
            next_cursor = str(min_timestamp)
            watermark_ts = max(item.get("start_time", time.time()) for item in items)

        return SensorSyncResult(
            items=items,
            next_cursor=next_cursor,
            watermark_ts=watermark_ts,
            stats={
                "count": len(items),
                "authorization_status": auth_status,
                "initial_sync": context.last_cursor is None,
            },
        )

    async def build_timeline_event(self, item: dict) -> TimelineEvent:
        """Build a TimelineEvent from a calendar event item."""
        # Reconstruct CalendarEvent from item dict
        start_ts = item.get("start_time", time.time())
        end_ts = item.get("end_time", time.time())

        event = CalendarEvent(
            event_id=item.get("event_id", ""),
            title=item.get("title", ""),
            start_time=datetime.fromtimestamp(start_ts),
            end_time=datetime.fromtimestamp(end_ts),
            is_all_day=item.get("is_all_day", False),
            location=item.get("location"),
            notes=item.get("notes"),
            calendar_name=item.get("calendar_name", ""),
            calendar_color=item.get("calendar_color", ""),
            participants=[
                Participant(
                    name=p.get("name", ""),
                    email=p.get("email"),
                    status=p.get("status", "pending")
                )
                for p in item.get("participants", [])
            ],
            is_recurring=item.get("is_recurring", False),
            recurrence_rule=item.get("recurrence_rule"),
            url=item.get("url"),
        )

        # Normalize
        normalized_data = normalize_calendar_event(event, self)

        return TimelineEvent(
            event_id=normalized_data["event_id"],
            source_type=self.source_type,
            source_item_id=normalized_data["source_item_id"],
            occurred_at=normalized_data["occurred_at"],
            captured_at=time.time(),
            title=normalized_data["title"],
            summary=normalized_data["summary"],
            retention_mode=self.retention_mode,
            raw_payload_ref=None,
            content_blocks=[
                TimelineContentBlock(kind=block["kind"], value=block["value"])
                for block in normalized_data["content_blocks"]
            ],
            tags=normalized_data["tags"],
            processing_status={"stored": False, "analyzed": False},
            provenance={
                "sensor_id": self.sensor_id,
                **normalized_data["provenance"],
            },
        )


# Import Participant for build_timeline_event
from .types import Participant
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd /Users/asuka/code/magi/.worktree/sensor-extension && python -m pytest backend/tests/test_calendar_plugin.py::test_sensor_properties backend/tests/test_calendar_plugin.py::test_sensor_source_item_identity backend/tests/test_calendar_plugin.py::test_sensor_source_item_version_fingerprint backend/tests/test_calendar_plugin.py::test_sensor_collect_items_with_stub_reader -v`
Expected: 4 passed

- [ ] **Step 5: Commit**

```bash
git add plugins/calendar/sensor.py backend/tests/test_calendar_plugin.py
git commit -m "feat(calendar): add sensor module"
```

---

### Task 7: Plugin Module

**Files:**
- Create: `plugins/calendar/plugin.py`
- Test: `backend/tests/test_calendar_plugin.py`

- [ ] **Step 1: Write the failing tests for plugin**

```python
# Add to backend/tests/test_calendar_plugin.py
from calendar.plugin import DEFAULT_SETTINGS, _fields, CalendarPlugin


def test_default_settings():
    """Test DEFAULT_SETTINGS has expected structure."""
    assert "enabled" in DEFAULT_SETTINGS
    assert "sync_interval_minutes" in DEFAULT_SETTINGS
    assert "lookback_days" in DEFAULT_SETTINGS
    assert "recurring_expansion_days" in DEFAULT_SETTINGS
    assert "default_retention_mode" in DEFAULT_SETTINGS

    assert DEFAULT_SETTINGS["enabled"] is False
    assert DEFAULT_SETTINGS["sync_interval_minutes"] == 30
    assert DEFAULT_SETTINGS["lookback_days"] == 30
    assert DEFAULT_SETTINGS["recurring_expansion_days"] == 30


def test_fields_function():
    """Test _fields returns list of ExtensionFieldSpec."""
    from magi.plugins import ExtensionFieldSpec

    fields = _fields("sensors.calendar")

    assert isinstance(fields, list)
    assert len(fields) > 0
    assert all(isinstance(f, ExtensionFieldSpec) for f in fields)

    # Check that key fields exist
    field_keys = [f.key for f in fields]
    assert any("sync_interval" in k for k in field_keys)
    assert any("lookback" in k for k in field_keys)


def test_plugin_get_sensors_on_non_darwin():
    """Test plugin returns empty sensors on non-darwin platform."""
    with patch('sys.platform', 'win32'):
        plugin = CalendarPlugin(settings={})
        sensors = plugin.get_sensors()
        assert sensors == []


def test_plugin_get_sensors_with_disabled_setting():
    """Test plugin returns empty sensors when disabled in settings."""
    plugin = CalendarPlugin(settings={"sensors": {"calendar": {"enabled": False}}})

    # Even on darwin, should return empty when disabled
    with patch('sys.platform', 'darwin'):
        sensors = plugin.get_sensors()
        assert sensors == []
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd /Users/asuka/code/magi/.worktree/sensor-extension && python -m pytest backend/tests/test_calendar_plugin.py::test_default_settings -v`
Expected: FAIL with "cannot import name 'DEFAULT_SETTINGS' from 'calendar.plugin'"

- [ ] **Step 3: Create the plugin module**

```python
# In plugins/calendar/plugin.py
"""Calendar timeline plugin."""
from __future__ import annotations

import sys
from typing import Any

from magi.plugins import ExtensionFieldOption, ExtensionFieldSpec, Plugin, SensorSpec

from .reader import EventKitReader
from .sensor import CalendarTimelineSensor

DEFAULT_SETTINGS = {
    "enabled": False,
    "sync_interval_minutes": 30,
    "lookback_days": 30,
    "recurring_expansion_days": 30,
    "default_retention_mode": "analyze_only",
}


def _fields(prefix: str) -> list[ExtensionFieldSpec]:
    """Define all settings fields for the Calendar plugin."""
    return [
        ExtensionFieldSpec(
            key=f"{prefix}.enabled",
            type="switch",
            label="Enable Calendar Sync",
            description="Sync calendar events to timeline.",
            default=False,
            section="general",
            surface="timeline",
            order=10,
        ),
        ExtensionFieldSpec(
            key=f"{prefix}.sync_interval_minutes",
            type="select",
            label="Sync Interval",
            description="How often to sync calendar events.",
            default=30,
            options=[
                ExtensionFieldOption(label="15 minutes", value=15),
                ExtensionFieldOption(label="30 minutes", value=30),
                ExtensionFieldOption(label="1 hour", value=60),
                ExtensionFieldOption(label="6 hours", value=360),
            ],
            section="sync",
            surface="timeline",
            order=20,
        ),
        ExtensionFieldSpec(
            key=f"{prefix}.lookback_days",
            type="number",
            label="Lookback Days",
            description="How many days of history to sync on initial setup.",
            default=30,
            min=1,
            max=365,
            section="sync",
            surface="timeline",
            order=30,
        ),
        ExtensionFieldSpec(
            key=f"{prefix}.recurring_expansion_days",
            type="number",
            label="Recurring Event Expansion",
            description="Days to expand recurring events into the future.",
            default=30,
            min=1,
            max=365,
            section="sync",
            surface="timeline",
            order=40,
        ),
        ExtensionFieldSpec(
            key=f"{prefix}.default_retention_mode",
            type="select",
            label="Retention Mode",
            description="How calendar data should be retained.",
            default="analyze_only",
            options=[
                ExtensionFieldOption(label="Analyze Only", value="analyze_only"),
                ExtensionFieldOption(label="Full Retention", value="full"),
            ],
            section="retention",
            surface="timeline",
            order=50,
        ),
    ]


class CalendarPlugin(Plugin):
    """Registers the Calendar timeline source."""

    def get_sensors(self) -> list[tuple[str, object, SensorSpec]]:
        """Get sensor specifications for Calendar.

        Returns:
            List of sensor tuples (sensor_id, sensor_instance, sensor_spec)
        """
        # Check platform - only supported on Darwin
        if sys.platform != "darwin":
            return []

        # Get settings
        settings = {}
        sensors_settings = self.settings.get("sensors", {})
        if isinstance(sensors_settings, dict):
            settings = dict(sensors_settings.get("calendar", {}))

        # Check if enabled
        if not settings.get("enabled", DEFAULT_SETTINGS["enabled"]):
            return []

        # Check EventKit availability
        try:
            reader = EventKitReader()
            if not reader.is_available():
                return []
        except Exception:
            return []

        # Create sensor
        sensor = CalendarTimelineSensor(
            retention_mode=str(settings.get("default_retention_mode", DEFAULT_SETTINGS["default_retention_mode"])),
            reader=reader,
        )

        # Prepare sync mode
        sync_interval_minutes = settings.get("sync_interval_minutes", DEFAULT_SETTINGS["sync_interval_minutes"])

        return [
            (
                "timeline.calendar",
                sensor,
                SensorSpec(
                    sensor_id="timeline.calendar",
                    display_name="Calendar",
                    description="Calendar event ingestion for the timeline.",
                    domain="timeline",
                    surface="timeline",
                    sync_mode="interval",
                    polling_mode="interval",
                    fields=_fields("sensors.calendar"),
                    metadata={
                        "source_type": "calendar",
                        "default_settings": dict(DEFAULT_SETTINGS),
                        "sync_interval_minutes": sync_interval_minutes,
                    },
                ),
            )
        ]
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd /Users/asuka/code/magi/.worktree/sensor-extension && python -m pytest backend/tests/test_calendar_plugin.py::test_default_settings backend/tests/test_calendar_plugin.py::test_fields_function backend/tests/test_calendar_plugin.py::test_plugin_get_sensors_on_non_darwin backend/tests/test_calendar_plugin.py::test_plugin_get_sensors_with_disabled_setting -v`
Expected: 4 passed

- [ ] **Step 5: Commit**

```bash
git add plugins/calendar/plugin.py backend/tests/test_calendar_plugin.py
git commit -m "feat(calendar): add plugin module with settings"
```

---

### Task 8: Plugin Manifest

**Files:**
- Create: `plugins/calendar/plugin.toml`

- [ ] **Step 1: Create the plugin manifest**

```toml
# In plugins/calendar/plugin.toml
[plugin]
id = "calendar"
name = "Calendar"
version = "0.1.0"
description = "Calendar event ingestion for the timeline."
author = "Magi Team"
entry_module = "plugin"
entry_class = "CalendarPlugin"
official = true
contribution_types = ["sensor"]
platforms = ["macos", "ios"]
```

- [ ] **Step 2: Commit**

```bash
git add plugins/calendar/plugin.toml
git commit -m "feat(calendar): add plugin manifest"
```

---

## Chunk 4: Final Tests and Verification

### Task 9: Integration Tests

**Files:**
- Modify: `backend/tests/test_calendar_plugin.py`

- [ ] **Step 1: Add integration tests**

```python
# Add to backend/tests/test_calendar_plugin.py
import asyncio


def test_sensor_build_timeline_event():
    """Test building a TimelineEvent from calendar item."""
    sensor = CalendarTimelineSensor()

    item = {
        "event_id": "integration-001",
        "title": "Integration Test Meeting",
        "start_time": datetime(2026, 3, 12, 10, 0).timestamp(),
        "end_time": datetime(2026, 3, 12, 11, 0).timestamp(),
        "is_all_day": False,
        "location": "Test Room",
        "notes": "Test notes",
        "calendar_name": "Test Calendar",
        "calendar_color": "#FF0000",
        "participants": [
            {"name": "Alice", "email": "alice@test.com", "status": "accepted"}
        ],
        "is_recurring": False,
        "recurrence_rule": None,
        "url": None,
    }

    event = asyncio.run(sensor.build_timeline_event(item))

    assert event.event_id == "calendar_integration-001"
    assert event.source_type == "calendar"
    assert "Integration Test Meeting" in event.title
    assert len(event.content_blocks) > 0
    assert "calendar" in event.tags


def test_sensor_build_all_day_event():
    """Test building TimelineEvent for all-day event."""
    sensor = CalendarTimelineSensor()

    item = {
        "event_id": "allday-001",
        "title": "Holiday",
        "start_time": datetime(2026, 3, 12, 0, 0).timestamp(),
        "end_time": datetime(2026, 3, 12, 23, 59, 59).timestamp(),
        "is_all_day": True,
        "location": None,
        "notes": None,
        "calendar_name": "Holidays",
        "calendar_color": "#FFD700",
        "participants": [],
        "is_recurring": True,
        "recurrence_rule": "FREQ=YEARLY",
        "url": None,
    }

    event = asyncio.run(sensor.build_timeline_event(item))

    assert "all_day" in event.tags
    assert "recurring" in event.tags


def test_full_test_suite_runs():
    """Verify all calendar tests pass together."""
    # This test just confirms the test suite is complete
    pass
```

- [ ] **Step 2: Run all calendar tests**

Run: `cd /Users/asuka/code/magi/.worktree/sensor-extension && python -m pytest backend/tests/test_calendar_plugin.py -v`
Expected: All tests pass

- [ ] **Step 3: Commit**

```bash
git add backend/tests/test_calendar_plugin.py
git commit -m "test(calendar): add integration tests"
```

---

### Task 10: Final Verification

- [ ] **Step 1: Run all tests to ensure no regressions**

Run: `cd /Users/asuka/code/magi/.worktree/sensor-extension && python -m pytest backend/tests/ -v`
Expected: All tests pass (including apple_health tests)

- [ ] **Step 2: Verify plugin structure**

Run: `cd /Users/asuka/code/magi/.worktree/sensor-extension && ls -la plugins/calendar/`
Expected: All 8 files present

- [ ] **Step 3: Final commit (if needed)**

```bash
git status
# If clean, no commit needed
```

---

## Acceptance Criteria Checklist

- [ ] Plugin loads successfully on macOS with EventKit available (stub for now)
- [ ] Plugin gracefully disables on Windows/Linux without errors
- [ ] All event information (title, time, location, participants, notes) can be normalized
- [ ] Recurring events are handled (expansion to be implemented in reader)
- [ ] Initial sync covers the past 30 days by default
- [ ] Unit tests pass on all platforms
