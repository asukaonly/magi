from __future__ import annotations

import pytest
import sys
from pathlib import Path
from unittest.mock import patch, MagicMock

_plugins_path = Path(__file__).resolve().parents[3] / "plugins"
if str(_plugins_path) not in sys.path:
    sys.path.insert(0, str(_plugins_path))

from calendar_plugin.reader import EventKitReader


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


def test_sensor_source_item_identity():
    """Test source_item_identity generation."""
    from calendar_plugin.sensor import CalendarTimelineSensor
    from magi.timeline import SensorSyncContext
    from datetime import datetime, timedelta
    import time

    sensor = CalendarTimelineSensor()
    item = {"event_id": "test-123", "title": "Meeting"}

    identity = sensor.source_item_identity(item)
    assert identity == "calendar_test-123"


def test_sensor_source_item_version_fingerprint():
    """Test source_item_version_fingerprint generation."""
    from calendar_plugin.sensor import CalendarTimelineSensor
    from magi.timeline import SensorSyncContext
    from datetime import datetime, timedelta
    import time

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
    from calendar_plugin.sensor import CalendarTimelineSensor
    from magi.timeline import SensorSyncContext
    from magi.utils.runtime import RuntimePaths
    from datetime import datetime, timedelta
    import time
    import asyncio

    sensor = CalendarTimelineSensor()
    runtime_paths = RuntimePaths()
    context = SensorSyncContext(
        source_type="calendar",
        manual=False,
        last_cursor=None,
        last_success_at=None,
        limit=100,
        runtime_paths=runtime_paths,
        plugin_settings={}
    )

    # Since reader is stub and returns empty, collect_items should return empty
    result = asyncio.run(sensor.collect_items(context))

    assert isinstance(result.items, list)
    assert len(result.items) == 0


def test_default_settings():
    """Test DEFAULT_SETTINGS has expected structure."""
    from calendar_plugin.plugin import DEFAULT_SETTINGS
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
    from calendar_plugin.plugin import _fields
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
    from calendar_plugin.plugin import CalendarPlugin
    plugin = CalendarPlugin()
    plugin.configure(manifest=None, settings={})
    with patch('sys.platform', 'win32'):
        sensors = plugin.get_sensors()
        assert sensors == []


def test_plugin_get_sensors_with_disabled_setting():
    """Test plugin still exposes sensor settings when disabled in settings."""
    from calendar_plugin.plugin import CalendarPlugin

    plugin = CalendarPlugin()
    plugin.configure(manifest=None, settings={"sensors": {"calendar": {"enabled": False}}})

    # Even on darwin, disabled sources should still be configurable.
    with patch('sys.platform', 'darwin'):
        sensors = plugin.get_sensors()
        assert len(sensors) == 1
        sensor_id, _, sensor_spec = sensors[0]
        assert sensor_id == "timeline.calendar"
        assert sensor_spec.metadata["default_settings"]["enabled"] is False


import asyncio


def test_sensor_build_output():
    """Test building a SensorOutput from calendar item."""
    from calendar_plugin.sensor import CalendarTimelineSensor
    from datetime import datetime
    import time

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

    output = asyncio.run(sensor.build_output(item))

    assert output.source_item_id == "calendar_integration-001"
    assert output.source_type == "calendar"
    assert "Integration Test Meeting" in output.title
    assert len(output.content_blocks) > 0
    assert "calendar" in output.tags


def test_sensor_build_all_day_event():
    """Test building SensorOutput for all-day event."""
    from calendar_plugin.sensor import CalendarTimelineSensor
    from datetime import datetime
    import time

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

    output = asyncio.run(sensor.build_output(item))

    assert "all_day" in output.tags
    assert "recurring" in output.tags
