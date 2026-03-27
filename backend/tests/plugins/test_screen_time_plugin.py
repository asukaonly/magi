from __future__ import annotations

import asyncio
import json
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
from screen_time.reader import FrontmostAppReader
from screen_time.sensor import ScreenTimeTimelineSensor
from screen_time.types import FrontmostAppSample


class StubReader:
    def __init__(self, sample: FrontmostAppSample | None) -> None:
        self.sample = sample

    def is_available(self) -> bool:
        return True

    def read_frontmost_app(self) -> FrontmostAppSample | None:
        return self.sample


def test_reader_is_available_on_non_darwin() -> None:
    with patch("sys.platform", "win32"):
        reader = FrontmostAppReader()
        assert reader.is_available() is False


def test_reader_parses_lsappinfo_output() -> None:
    outputs = iter(
        [
            "ASN:0x0-0x91091:\n",
            '"CFBundleIdentifier"="com.apple.Safari"\n"LSDisplayName"="Safari"\n',
        ]
    )

    def _fake_check_output(*args, **kwargs) -> str:
        _ = (args, kwargs)
        return next(outputs)

    with patch("sys.platform", "darwin"):
        with patch("shutil.which", return_value="/usr/bin/lsappinfo"):
            with patch("subprocess.check_output", side_effect=_fake_check_output):
                sample = FrontmostAppReader().read_frontmost_app()

    assert sample is not None
    assert sample.bundle_id == "com.apple.Safari"
    assert sample.app_name == "Safari"


def test_sensor_collect_items_emits_completed_hourly_bucket(tmp_path: Path) -> None:
    runtime_paths = RuntimePaths(base_dir=tmp_path / ".magi")
    sensor = ScreenTimeTimelineSensor(reader=StubReader(FrontmostAppSample(bundle_id="com.openai.codex", app_name="Codex")))

    first_context = SensorSyncContext(
        source_type="screen_time",
        manual=False,
        last_cursor=None,
        last_success_at=None,
        limit=100,
        runtime_paths=runtime_paths,
        plugin_settings={"sensors": {"screen_time": {"sync_interval_minutes": 5}}},
    )

    with patch.object(sensor, "_now", return_value=datetime(2026, 3, 27, 10, 55, tzinfo=timezone.utc)):
        first_result = asyncio.run(sensor.collect_items(first_context))

    assert first_result.items == []

    state_path = runtime_paths.memories_dir / "screen_time_state.json"
    state_payload = json.loads(state_path.read_text(encoding="utf-8"))
    assert state_payload["last_sample"]["bundle_id"] == "com.openai.codex"

    sensor._reader = StubReader(FrontmostAppSample(bundle_id="com.apple.Safari", app_name="Safari"))
    second_context = SensorSyncContext(
        source_type="screen_time",
        manual=False,
        last_cursor=first_result.next_cursor,
        last_success_at=None,
        limit=100,
        runtime_paths=runtime_paths,
        plugin_settings={"sensors": {"screen_time": {"sync_interval_minutes": 5}}},
    )

    with patch.object(sensor, "_now", return_value=datetime(2026, 3, 27, 11, 5, tzinfo=timezone.utc)):
        second_result = asyncio.run(sensor.collect_items(second_context))

    assert len(second_result.items) == 1
    item = second_result.items[0]
    assert item["bucket_start"] == "2026-03-27T10:00:00+00:00"
    assert item["bucket_end"] == "2026-03-27T11:00:00+00:00"
    assert item["bundle_id"] == "com.openai.codex"
    assert item["app_name"] == "Codex"
    assert item["duration_seconds"] == 300
    assert item["sample_count"] == 1


def test_sensor_build_output() -> None:
    sensor = ScreenTimeTimelineSensor()
    item = {
        "bucket_start": "2026-03-27T10:00:00+08:00",
        "bucket_end": "2026-03-27T11:00:00+08:00",
        "bundle_id": "com.apple.Safari",
        "app_name": "Safari",
        "duration_seconds": 2280,
        "sample_count": 4,
    }

    output = asyncio.run(sensor.build_output(item))

    assert sensor.memory_event_type == "APP_USAGE_HOURLY"
    assert output.source_item_id == "app_usage:2026-03-27T10:00:00+08:00:com.apple.Safari"
    assert output.source_type == "screen_time"
    assert "Safari" in output.title
    assert output.domain_payload["duration_seconds"] == 2280
    assert output.domain_payload["sample_count"] == 4


def test_default_settings() -> None:
    assert "enabled" in DEFAULT_SETTINGS
    assert "sync_interval_minutes" in DEFAULT_SETTINGS
    assert "default_retention_mode" in DEFAULT_SETTINGS

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
        assert sensor_spec.metadata["source_type"] == "screen_time"
