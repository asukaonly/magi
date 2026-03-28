from __future__ import annotations

import asyncio
import sys
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch

import pytest

# Add plugins directory to sys.path
_plugins_path = Path(__file__).resolve().parents[3] / "plugins"
if str(_plugins_path) not in sys.path:
    sys.path.insert(0, str(_plugins_path))

from magi.timeline import SensorSyncContext
from magi.utils.runtime import RuntimePaths
from screen_time.plugin import DEFAULT_SETTINGS, _fields, ScreenTimePlugin
from screen_time.ingress import ScreenTimePluginIngressHandler
from screen_time.sensor import ScreenTimeTimelineSensor
from screen_time.state import ScreenTimeStateStore
from magi.runtime_trace import PluginIngressEventRecord


def test_sensor_collect_items_emits_completed_hourly_bucket(tmp_path: Path) -> None:
    runtime_paths = RuntimePaths(base_dir=tmp_path / ".magi")
    sensor = ScreenTimeTimelineSensor()
    state_store = ScreenTimeStateStore()
    asyncio.run(
        state_store.apply_activation(
            runtime_paths=runtime_paths,
            occurred_at=datetime(2026, 3, 27, 10, 55, tzinfo=timezone.utc),
            bundle_id="com.openai.codex",
            app_name="Codex",
        )
    )

    first_context = SensorSyncContext(
        source_type="screen_time",
        manual=False,
        last_cursor=None,
        last_success_at=None,
        limit=100,
        runtime_paths=runtime_paths,
        plugin_settings={"sensors": {"screen_time": {"sync_interval_minutes": 5}}},
    )

    with patch.object(sensor, "_now", return_value=datetime(2026, 3, 27, 10, 58, tzinfo=timezone.utc)):
        first_result = asyncio.run(sensor.collect_items(first_context))

    assert first_result.items == []

    handler = ScreenTimePluginIngressHandler(runtime_paths=runtime_paths)
    asyncio.run(
        handler.handle_event(
            PluginIngressEventRecord(
                event_id=1,
                source_kind="desktop",
                producer="frontmost_app_monitor",
                plugin_target="screen_time",
                event_type="frontmost_app_activated",
                occurred_at_ms=int(datetime(2026, 3, 27, 11, 5, tzinfo=timezone.utc).timestamp() * 1000),
                payload_json="{}",
                created_at_ms=0,
            ),
            {"bundle_id": "com.apple.Safari", "app_name": "Safari"},
        )
    )

    with patch.object(sensor, "_now", return_value=datetime(2026, 3, 27, 11, 5, tzinfo=timezone.utc)):
        second_result = asyncio.run(sensor.collect_items(first_context))

    assert len(second_result.items) == 1
    item = second_result.items[0]
    assert item["bucket_start"] == "2026-03-27T10:00:00+00:00"
    assert item["bucket_end"] == "2026-03-27T11:00:00+00:00"
    assert item["bundle_id"] == "com.openai.codex"
    assert item["app_name"] == "Codex"
    assert item["duration_seconds"] == 300
    assert item["session_count"] == 1


def test_screen_time_ingress_handler_updates_activation_state(tmp_path: Path) -> None:
    runtime_paths = RuntimePaths(base_dir=tmp_path / ".magi")
    state_store = ScreenTimeStateStore()
    handler = ScreenTimePluginIngressHandler(runtime_paths=runtime_paths, state_store=state_store)

    asyncio.run(
        handler.handle_event(
            PluginIngressEventRecord(
                event_id=1,
                source_kind="desktop",
                producer="frontmost_app_monitor",
                plugin_target="screen_time",
                event_type="frontmost_app_activated",
                occurred_at_ms=int(datetime(2026, 3, 27, 10, 15, tzinfo=timezone.utc).timestamp() * 1000),
                payload_json="{}",
                created_at_ms=0,
            ),
            {"bundle_id": "com.apple.Safari", "app_name": "Safari"},
        )
    )
    asyncio.run(
        handler.handle_event(
            PluginIngressEventRecord(
                event_id=2,
                source_kind="desktop",
                producer="frontmost_app_monitor",
                plugin_target="screen_time",
                event_type="frontmost_app_activated",
                occurred_at_ms=int(datetime(2026, 3, 27, 10, 42, tzinfo=timezone.utc).timestamp() * 1000),
                payload_json="{}",
                created_at_ms=0,
            ),
            {"bundle_id": "com.apple.Terminal", "app_name": "Terminal"},
        )
    )

    completed = asyncio.run(
        state_store.flush_completed(
            runtime_paths=runtime_paths,
            now=datetime(2026, 3, 27, 11, 5, tzinfo=timezone.utc),
        )
    )

    assert completed == [
        {
            "bucket_start": "2026-03-27T10:00:00+00:00",
            "bucket_end": "2026-03-27T11:00:00+00:00",
            "bundle_id": "com.apple.Safari",
            "app_name": "Safari",
            "duration_seconds": 1620,
            "session_count": 1,
        },
        {
            "bucket_start": "2026-03-27T10:00:00+00:00",
            "bucket_end": "2026-03-27T11:00:00+00:00",
            "bundle_id": "com.apple.Terminal",
            "app_name": "Terminal",
            "duration_seconds": 1080,
            "session_count": 1,
        },
    ]


def test_screen_time_state_reuses_session_for_consecutive_same_app_activations(tmp_path: Path) -> None:
    runtime_paths = RuntimePaths(base_dir=tmp_path / ".magi")
    state_store = ScreenTimeStateStore()
    handler = ScreenTimePluginIngressHandler(runtime_paths=runtime_paths, state_store=state_store)

    asyncio.run(
        handler.handle_event(
            PluginIngressEventRecord(
                event_id=1,
                source_kind="desktop",
                producer="frontmost_app_monitor",
                plugin_target="screen_time",
                event_type="frontmost_app_activated",
                occurred_at_ms=int(datetime(2026, 3, 27, 10, 15, tzinfo=timezone.utc).timestamp() * 1000),
                payload_json="{}",
                created_at_ms=0,
            ),
            {"bundle_id": "com.apple.Safari", "app_name": "Safari"},
        )
    )
    asyncio.run(
        handler.handle_event(
            PluginIngressEventRecord(
                event_id=2,
                source_kind="desktop",
                producer="frontmost_app_monitor",
                plugin_target="screen_time",
                event_type="frontmost_app_activated",
                occurred_at_ms=int(datetime(2026, 3, 27, 10, 20, tzinfo=timezone.utc).timestamp() * 1000),
                payload_json="{}",
                created_at_ms=0,
            ),
            {"bundle_id": "com.apple.Safari", "app_name": "Safari"},
        )
    )
    asyncio.run(
        handler.handle_event(
            PluginIngressEventRecord(
                event_id=3,
                source_kind="desktop",
                producer="frontmost_app_monitor",
                plugin_target="screen_time",
                event_type="frontmost_app_activated",
                occurred_at_ms=int(datetime(2026, 3, 27, 10, 42, tzinfo=timezone.utc).timestamp() * 1000),
                payload_json="{}",
                created_at_ms=0,
            ),
            {"bundle_id": "com.apple.Terminal", "app_name": "Terminal"},
        )
    )

    completed = asyncio.run(
        state_store.flush_completed(
            runtime_paths=runtime_paths,
            now=datetime(2026, 3, 27, 11, 5, tzinfo=timezone.utc),
        )
    )

    assert completed == [
        {
            "bucket_start": "2026-03-27T10:00:00+00:00",
            "bucket_end": "2026-03-27T11:00:00+00:00",
            "bundle_id": "com.apple.Safari",
            "app_name": "Safari",
            "duration_seconds": 1620,
            "session_count": 1,
        },
        {
            "bucket_start": "2026-03-27T10:00:00+00:00",
            "bucket_end": "2026-03-27T11:00:00+00:00",
            "bundle_id": "com.apple.Terminal",
            "app_name": "Terminal",
            "duration_seconds": 1080,
            "session_count": 1,
        },
    ]


def test_screen_time_state_store_uses_plugin_cache_directory(tmp_path: Path) -> None:
    runtime_paths = RuntimePaths(base_dir=tmp_path / ".magi")
    state_store = ScreenTimeStateStore()

    assert state_store._state_path(runtime_paths) == (
        tmp_path / ".magi" / "cache" / "plugins" / "screen_time" / "state.json"
    )


def test_sensor_build_output() -> None:
    sensor = ScreenTimeTimelineSensor()
    item = {
        "bucket_start": "2026-03-27T10:00:00+08:00",
        "bucket_end": "2026-03-27T11:00:00+08:00",
        "bundle_id": "com.apple.Safari",
        "app_name": "Safari",
        "duration_seconds": 2280,
        "session_count": 4,
    }

    output = asyncio.run(sensor.build_output(item))

    assert sensor.memory_event_type == "APP_USAGE_HOURLY"
    assert output.source_item_id == "app_usage:2026-03-27T10:00:00+08:00:com.apple.Safari"
    assert output.source_type == "screen_time"
    assert "Safari" in output.title
    assert output.domain_payload["duration_seconds"] == 2280
    assert output.domain_payload["session_count"] == 4


def test_default_settings() -> None:
    assert "enabled" in DEFAULT_SETTINGS
    assert "sync_interval_minutes" in DEFAULT_SETTINGS

    assert DEFAULT_SETTINGS["enabled"] is False
    assert DEFAULT_SETTINGS["sync_interval_minutes"] == 5


def test_fields_function() -> None:
    from magi.plugins import ExtensionFieldSpec

    fields = _fields("sensors.screen_time")

    assert isinstance(fields, list)
    assert len(fields) > 0
    assert all(isinstance(f, ExtensionFieldSpec) for f in fields)

    field_keys = [f.key for f in fields]
    assert "sensors.screen_time.sync_interval_minutes" in field_keys


def test_plugin_get_sensors_on_non_darwin() -> None:
    plugin = ScreenTimePlugin()
    plugin.configure(manifest=None, settings={})
    with patch("sys.platform", "win32"):
        sensors = plugin.get_sensors()
        assert sensors == []


def test_plugin_get_sensors_exposes_hourly_usage_source() -> None:
    plugin = ScreenTimePlugin()
    plugin.configure(manifest=None, settings={"sensors": {"screen_time": {"enabled": False}}})

    with patch("sys.platform", "darwin"):
        sensors = plugin.get_sensors()
        assert len(sensors) == 1
        sensor_id, sensor, sensor_spec = sensors[0]
        assert sensor_id == "timeline.screen_time"
        assert sensor.memory_event_type == "APP_USAGE_HOURLY"
        assert sensor_spec.metadata["default_settings"]["sync_interval_minutes"] == 5
        assert "default_retention_mode" not in sensor_spec.metadata["default_settings"]
        assert sensor_spec.metadata["source_type"] == "screen_time"
