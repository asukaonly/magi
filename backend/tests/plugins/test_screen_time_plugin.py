from __future__ import annotations

import asyncio
import pytest
import sys
from datetime import date, datetime, timedelta
from unittest.mock import MagicMock, patch
from pathlib import Path

# Add plugins directory to sys.path
_plugins_path = Path(__file__).resolve().parents[3] / "plugins"
if str(_plugins_path) not in sys.path:
    sys.path.insert(0, str(_plugins_path))

from screen_time.exceptions import DatabaseNotFoundError
from screen_time.types import AppUsage, DailyScreenTime
from screen_time.normalizers import normalize_daily_screen_time
from screen_time.reader import ScreenTimeReader
from screen_time.plugin import DEFAULT_SETTINGS, _fields, ScreenTimePlugin


from screen_time.sensor import ScreenTimeTimelineSensor
from magi.timeline import SensorSyncContext


# ============ Normalizer Tests ============

class MockSensor:
    """Mock sensor for testing."""
    sensor_id = "timeline.screen_time"


def test_normalize_daily_screen_time():
    """Test normalizing daily screen time data."""
    daily = DailyScreenTime(
        date=date(2026, 3, 12),
        total_duration=7200,  # 2 hours
        app_usages=[
            AppUsage(bundle_id="com.apple.Safari", app_name="Safari", usage_seconds=3600, category="productivity"),
            AppUsage(bundle_id="com.apple.Mail", app_name="邮件", usage_seconds=1800, category="communication"),
        ]
    )

    sensor = MockSensor()
    result = normalize_daily_screen_time(daily, sensor)

    assert result["event_id"] == "screen_time_2026-03-12"
    assert result["source_type"] == "screen_time"
    assert "2.0 小时" in result["title"]
    assert "Safari" in result["summary"]
    assert len(result["content_blocks"]) >= 2
    assert "screen_time" in result["tags"]


def test_normalize_screen_time_short():
    """Test normalizing short duration."""
    daily = DailyScreenTime(
        date=date(2026, 3, 12),
        total_duration=1800,  # 30 minutes
        app_usages=[]
    )

    sensor = MockSensor()
    result = normalize_daily_screen_time(daily, sensor)

    assert "30.0 分钟" in result["title"]


# ============ Reader Tests ============

def test_reader_is_available_on_non_darwin():
    """Test that reader handles non-darwin platforms gracefully."""
    with patch('sys.platform', 'win32'):
        reader = ScreenTimeReader()
        assert reader.is_available() is False


def test_reader_is_available_on_darwin_no_db():
    """Test that reader returns False when database not found."""
    with patch('sys.platform', 'darwin'):
        with patch.object(ScreenTimeReader, '_find_database') as mock_find_db:
            mock_find_db.side_effect = DatabaseNotFoundError()
            reader = ScreenTimeReader()
            assert reader.is_available() is False


def test_reader_read_daily_screen_time_stub():
    """Test that read_daily_screen_time returns empty list when not available."""
    reader = ScreenTimeReader()
    reader._is_available = False

    results = reader.read_daily_screen_time(
        date(2026, 3, 1),
        date(2026, 3, 12)
    )
    assert results == []


# ============ Sensor Tests ============

def test_sensor_source_item_identity():
    """Test source_item_identity generation."""
    sensor = ScreenTimeTimelineSensor()
    item = {"date": "2026-03-12"}

    identity = sensor.source_item_identity(item)
    assert identity == "screen_time_2026-03-12"


def test_sensor_source_item_version_fingerprint():
    """Test source_item_version_fingerprint generation."""
    sensor = ScreenTimeTimelineSensor()
    item1 = {"date": "2026-03-12", "total_duration": 7200, "app_usages": []}
    item2 = {"date": "2026-03-12", "total_duration": 7200, "app_usages": []}
    item3 = {"date": "2026-03-12", "total_duration": 3600, "app_usages": []}

    fingerprint1 = sensor.source_item_version_fingerprint(item1)
    fingerprint2 = sensor.source_item_version_fingerprint(item2)
    fingerprint3 = sensor.source_item_version_fingerprint(item3)

    assert fingerprint1 == fingerprint2
    assert fingerprint1 != fingerprint3


def test_sensor_collect_items_with_stub_reader():
    """Test collect_items returns empty list with stub reader."""
    from magi.utils.runtime import RuntimePaths

    sensor = ScreenTimeTimelineSensor()
    runtime_paths = RuntimePaths()
    context = SensorSyncContext(
        source_type="screen_time",
        manual=False,
        last_cursor=None,
        last_success_at=None,
        limit=100,
        runtime_paths=runtime_paths,
        plugin_settings={}
    )

    result = asyncio.run(sensor.collect_items(context))

    assert isinstance(result.items, list)
    assert len(result.items) == 0


# ============ Plugin Tests ============

def test_default_settings():
    """Test DEFAULT_SETTINGS has expected structure."""
    assert "enabled" in DEFAULT_SETTINGS
    assert "sync_interval_hours" in DEFAULT_SETTINGS
    assert "lookback_days" in DEFAULT_SETTINGS
    assert "default_retention_mode" in DEFAULT_SETTINGS

    assert DEFAULT_SETTINGS["enabled"] is False
    assert DEFAULT_SETTINGS["sync_interval_hours"] == 1
    assert DEFAULT_SETTINGS["lookback_days"] == 30


def test_fields_function():
    """Test _fields returns list of ExtensionFieldSpec."""
    from magi.plugins import ExtensionFieldSpec

    fields = _fields("sensors.screen_time")

    assert isinstance(fields, list)
    assert len(fields) > 0
    assert all(isinstance(f, ExtensionFieldSpec) for f in fields)

    field_keys = [f.key for f in fields]
    assert any("sync_interval" in k for k in field_keys)
    assert any("lookback" in k for k in field_keys)


def test_plugin_get_sensors_on_non_darwin():
    """Test plugin returns empty sensors on non-darwin platform."""
    plugin = ScreenTimePlugin()
    plugin.configure(manifest=None, settings={})
    with patch('sys.platform', 'win32'):
        sensors = plugin.get_sensors()
        assert sensors == []


def test_plugin_get_sensors_with_disabled_setting():
    """Test plugin still exposes sensor settings when disabled in settings."""
    plugin = ScreenTimePlugin()
    plugin.configure(manifest=None, settings={"sensors": {"screen_time": {"enabled": False}}})

    with patch('sys.platform', 'darwin'):
        sensors = plugin.get_sensors()
        assert len(sensors) == 1
        sensor_id, _, sensor_spec = sensors[0]
        assert sensor_id == "timeline.screen_time"
        assert sensor_spec.metadata["default_settings"]["enabled"] is False


# ============ Integration Tests ============

def test_sensor_build_timeline_event():
    """Test building a TimelineEvent from screen time item."""
    sensor = ScreenTimeTimelineSensor()

    item = {
        "date": date(2026, 3, 12),
        "total_duration": 7200,
        "app_usages": [
            {"bundle_id": "com.apple.Safari", "app_name": "Safari", "usage_seconds": 3600, "category": "productivity"},
            {"bundle_id": "com.apple.Mail", "app_name": "邮件", "usage_seconds": 1800, "category": "communication"},
        ]
    }

    event = asyncio.run(sensor.build_timeline_event(item))

    assert event.event_id == "screen_time_2026-03-12"
    assert event.source_type == "screen_time"
    assert "屏幕使用" in event.title
    assert len(event.content_blocks) > 0
    assert "screen_time" in event.tags
