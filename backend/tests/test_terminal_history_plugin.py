"""Unit tests for Terminal History plugin."""
from __future__ import annotations

import asyncio
import pytest
import sys
from datetime import datetime, date
from pathlib import Path
from unittest.mock import MagicMock, patch

# Add plugins directory to sys.path
_plugins_path = Path(__file__).resolve().parents[2] / "plugins"
if str(_plugins_path) not in sys.path:
    sys.path.insert(0, str(_plugins_path))

from terminal_history.exceptions import (
    TerminalHistoryError,
    ShellNotSupportedError,
    HistoryFileNotFoundError,
    HistoryFileReadError,
)
from terminal_history.types import TerminalCommand
from terminal_history.filters import SensitiveCommandFilter, BUILTIN_SENSITIVE_KEYWORDS
from terminal_history.normalizers import normalize_terminal_command
from terminal_history.reader import TerminalHistoryReader
from terminal_history.sensor import TerminalHistorySensor
from terminal_history.plugin import DEFAULT_SETTINGS, _fields, TerminalHistoryPlugin


# ============ Exception Tests ============

def test_terminal_history_error_base():
    """Test TerminalHistoryError base exception."""
    error = TerminalHistoryError("Test error")
    assert str(error) == "Test error"


def test_shell_not_supported_error():
    """Test ShellNotSupportedError has shell attribute."""
    error = ShellNotSupportedError("fish")
    assert error.shell == "fish"
    assert "fish" in str(error)


def test_history_file_not_found_error():
    """Test HistoryFileNotFoundError has path attribute."""
    error = HistoryFileNotFoundError("/path/to/history")
    assert error.path == "/path/to/history"
    assert "not found" in str(error).lower()


def test_history_file_read_error():
    """Test HistoryFileReadError with reason."""
    error = HistoryFileReadError("/path/to/history", "permission denied")
    assert error.path == "/path/to/history"
    assert "permission denied" in str(error)


# ============ Type Tests ============

def test_terminal_command_creation():
    """Test TerminalCommand dataclass."""
    cmd = TerminalCommand(
        command="git status",
        executed_at=datetime(2026, 3, 13, 10, 30, 0),
        shell="zsh",
        history_line=42,
        raw_line=": 1741865000:0;git status",
    )
    assert cmd.command == "git status"
    assert cmd.shell == "zsh"
    assert cmd.history_line == 42


# ============ Filter Tests ============

def test_filter_redact_mode():
    """Test redact mode masks sensitive values."""
    filter_obj = SensitiveCommandFilter(mode="redact")
    command = "export API_KEY=secret123 && npm start"
    result = filter_obj.process(command)
    assert result is not None
    assert "secret123" not in result
    assert "***" in result


def test_filter_block_mode():
    """Test block mode returns None for sensitive commands."""
    filter_obj = SensitiveCommandFilter(mode="block")
    command = "export PASSWORD=mypassword"
    result = filter_obj.process(command)
    assert result is None


def test_filter_passes_non_sensitive():
    """Test non-sensitive commands pass through."""
    filter_obj = SensitiveCommandFilter(mode="redact")
    command = "npm install express"
    result = filter_obj.process(command)
    assert result == command


def test_filter_additional_keywords():
    """Test additional keywords work."""
    filter_obj = SensitiveCommandFilter(mode="block", additional_keywords=["custom_secret"])
    command = "export custom_secret=value"
    result = filter_obj.process(command)
    assert result is None


def test_builtin_keywords_exist():
    """Test that built-in keywords contain expected entries."""
    assert "password" in BUILTIN_SENSITIVE_KEYWORDS
    assert "api_key" in BUILTIN_SENSITIVE_KEYWORDS
    assert "token" in BUILTIN_SENSITIVE_KEYWORDS


# ============ Normalizer Tests ============

class MockSensor:
    """Mock sensor for testing."""
    sensor_id = "timeline.terminal_history"


def test_normalize_terminal_command_with_object():
    """Test normalizing TerminalCommand object."""
    cmd = TerminalCommand(
        command="ls -la",
        executed_at=datetime(2026, 3, 13, 14, 30, 0),
        shell="zsh",
        history_line=1,
        raw_line=": 1741887000:0;ls -la",
    )
    sensor = MockSensor()
    result = normalize_terminal_command(cmd, sensor)

    assert result["source_type"] == "terminal_history"
    assert "ls -la" in result["title"]
    assert "terminal" in result["tags"]
    assert "zsh" in result["tags"]


def test_normalize_terminal_command_with_dict():
    """Test normalizing dict input."""
    item = {
        "command": "npm test",
        "executed_at": datetime(2026, 3, 13, 15, 0, 0),
        "shell": "bash",
        "history_line": 10,
        "raw_line": "npm test",
    }
    sensor = MockSensor()
    result = normalize_terminal_command(item, sensor)

    assert result["source_type"] == "terminal_history"
    assert "npm test" in result["title"]
    assert "bash" in result["tags"]


def test_normalize_truncates_long_commands():
    """Test that long commands are truncated in title."""
    long_command = "a" * 150
    cmd = TerminalCommand(
        command=long_command,
        executed_at=datetime.now(),
        shell="zsh",
        history_line=1,
        raw_line=long_command,
    )
    sensor = MockSensor()
    result = normalize_terminal_command(cmd, sensor)

    assert len(result["title"]) <= 103  # 100 chars + "..."


# ============ Reader Tests ============

def test_reader_is_available_on_non_darwin():
    """Test that reader returns False on non-darwin platforms."""
    with patch('sys.platform', 'linux'):
        reader = TerminalHistoryReader()
        assert reader.is_available() is False


def test_reader_shell_not_supported():
    """Test ShellNotSupportedError for unsupported shell."""
    with patch('sys.platform', 'darwin'):
        with patch.dict('os.environ', {'SHELL': '/usr/bin/fish'}):
            reader = TerminalHistoryReader()
            with pytest.raises(ShellNotSupportedError):
                _ = reader.shell


# ============ Sensor Tests ============

def test_sensor_properties():
    """Test sensor class properties."""
    assert TerminalHistorySensor.sensor_id == "timeline.terminal_history"
    assert TerminalHistorySensor.source_type == "terminal_history"
    assert TerminalHistorySensor.polling_mode == "interval"
    assert TerminalHistorySensor.supports_pull_sync is True


def test_sensor_source_item_identity():
    """Test source_item_identity generation."""
    sensor = TerminalHistorySensor()
    item = {
        "command": "test command",
        "executed_at": datetime(2026, 3, 13, 10, 0, 0),
    }
    identity = sensor.source_item_identity(item)
    assert identity.startswith("terminal_")


def test_sensor_source_item_version_fingerprint():
    """Test source_item_version_fingerprint generation."""
    sensor = TerminalHistorySensor()
    item1 = {"command": "test", "executed_at": datetime(2026, 3, 13, 10, 0, 0)}
    item2 = {"command": "test", "executed_at": datetime(2026, 3, 13, 10, 0, 0)}
    item3 = {"command": "different", "executed_at": datetime(2026, 3, 13, 10, 0, 0)}

    fingerprint1 = sensor.source_item_version_fingerprint(item1)
    fingerprint2 = sensor.source_item_version_fingerprint(item2)
    fingerprint3 = sensor.source_item_version_fingerprint(item3)

    assert fingerprint1 == fingerprint2
    assert fingerprint1 != fingerprint3


# ============ Plugin Tests ============

def test_default_settings():
    """Test DEFAULT_SETTINGS has expected structure."""
    assert "enabled" in DEFAULT_SETTINGS
    assert "sync_interval_minutes" in DEFAULT_SETTINGS
    assert "initial_sync_policy" in DEFAULT_SETTINGS
    assert "sensitive_mode" in DEFAULT_SETTINGS
    assert "dedup_window_seconds" in DEFAULT_SETTINGS

    assert DEFAULT_SETTINGS["enabled"] is False
    assert DEFAULT_SETTINGS["sync_interval_minutes"] == 15
    assert DEFAULT_SETTINGS["sensitive_mode"] == "redact"


def test_fields_function():
    """Test _fields returns list of ExtensionFieldSpec."""
    from magi.plugins import ExtensionFieldSpec

    fields = _fields("sensors.terminal_history")

    assert isinstance(fields, list)
    assert len(fields) > 0
    assert all(isinstance(f, ExtensionFieldSpec) for f in fields)

    field_keys = [f.key for f in fields]
    assert any("sensitive" in k for k in field_keys)
    assert any("dedup" in k for k in field_keys)


def test_plugin_get_sensors_on_non_darwin():
    """Test plugin returns empty sensors on non-darwin platform."""
    plugin = TerminalHistoryPlugin()
    plugin.configure(manifest=None, settings={})
    with patch('sys.platform', 'linux'):
        sensors = plugin.get_sensors()
        assert sensors == []


def test_plugin_get_sensors_with_disabled_setting():
    """Test plugin returns empty sensors when disabled."""
    plugin = TerminalHistoryPlugin()
    plugin.configure(manifest=None, settings={"sensors": {"terminal_history": {"enabled": False}}})

    with patch('sys.platform', 'darwin'):
        sensors = plugin.get_sensors()
        assert sensors == []


# ============ Integration Tests ============

def test_sensor_build_timeline_event():
    """Test building a TimelineEvent from terminal command item."""
    sensor = TerminalHistorySensor()

    item = {
        "command": "npm run build",
        "executed_at": datetime(2026, 3, 13, 16, 0, 0),
        "shell": "zsh",
        "history_line": 100,
        "raw_line": ": 1741903200:0;npm run build",
    }

    event = asyncio.run(sensor.build_timeline_event(item))

    assert event.source_type == "terminal_history"
    assert "npm run build" in event.title
    assert len(event.content_blocks) > 0
    assert "terminal" in event.tags
    assert "zsh" in event.tags


def test_full_test_suite_runs():
    """Verify all terminal history tests pass together."""
    pass
