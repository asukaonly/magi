"""Unit tests for Git Activity plugin."""
from __future__ import annotations

import asyncio
import sys
from datetime import datetime
from pathlib import Path
from unittest.mock import MagicMock, patch

# Add plugins directory to sys.path
_plugins_path = Path(__file__).resolve().parents[3] / "plugins"
if str(_plugins_path) not in sys.path:
    sys.path.insert(0, str(_plugins_path))

from git_activity.types import GitActivity
from git_activity.reader import GitReflogReader, is_git_repo
from git_activity.filters import SensitiveMessageFilter
from git_activity.normalizers import normalize_git_activity
from git_activity.sensor import GitActivitySensor
from git_activity.plugin import DEFAULT_SETTINGS, _fields


# ============ Filter Tests ============

def test_filter_redact_mode():
    """Test redact mode masks sensitive values."""
    filter_obj = SensitiveMessageFilter(mode="redact")
    message = "commit: Set API_KEY=secret123"
    result = filter_obj.redact(message)
    assert result is not None
    assert "secret123" not in result
    assert "***" in result


def test_filter_block_mode():
    """Test block mode returns True for sensitive messages."""
    filter_obj = SensitiveMessageFilter(mode="block")
    message = "commit: Add password=mypassword"
    assert filter_obj.should_block(message) is True


def test_filter_passes_non_sensitive():
    """Test non-sensitive messages pass through."""
    filter_obj = SensitiveMessageFilter(mode="redact")
    message = "commit: Add new feature"
    result = filter_obj.redact(message)
    assert result == message


# ============ Normalizer Tests ============

class MockSensor:
    """Mock sensor for testing."""
    sensor_id = "timeline.git_activity"


def test_normalize_git_activity_with_object():
    """Test normalizing GitActivity object."""
    activity = GitActivity(
        repo_path="/Users/test/repo",
        activity_type="commit",
        old_sha="abc123",
        new_sha="def456",
        message="commit: Add feature",
        author="Test User <test@example.com>",
        timestamp=datetime(2026, 3, 13, 10, 0, 0),
        raw_line="abc123 def456 Test User 1741887600 +0800	commit: Add feature",
    )
    sensor = MockSensor()
    result = normalize_git_activity(activity, sensor)

    assert result["source_type"] == "git_activity"
    assert "commit" in result["title"]
    assert "git" in result["tags"]
    assert "commit" in result["tags"]


def test_normalize_git_activity_with_dict():
    """Test normalizing dict input."""
    item = {
        "repo_path": "/Users/test/repo",
        "activity_type": "merge",
        "old_sha": "aaa111",
        "new_sha": "bbb222",
        "message": "merge: Fix bug",
        "author": "Dev <dev@example.com>",
        "timestamp": datetime(2026, 3, 13, 11, 0, 0),
        "raw_line": "test line",
    }
    sensor = MockSensor()
    result = normalize_git_activity(item, sensor)

    assert result["source_type"] == "git_activity"
    assert "merge" in result["tags"]


# ============ Reader Tests ============

def test_reader_parse_line():
    """Test parsing a reflog line."""
    reader = GitReflogReader("/nonexistent/repo")
    line = "abc123 def456 John <john@example.com> 1741887600 +0800\tcommit: Add feature"

    activity = reader._parse_line(line)

    assert activity is not None
    assert activity.old_sha == "abc123"
    assert activity.new_sha == "def456"
    assert activity.activity_type == "commit"
    assert activity.author == "John <john@example.com>"
    assert "Add feature" in activity.message


def test_reader_determine_activity_type():
    """Test determining activity type from message."""
    reader = GitReflogReader("/nonexistent/repo")

    assert reader._determine_activity_type("commit: test") == "commit"
    assert reader._determine_activity_type("checkout: moving to main") == "checkout"
    assert reader._determine_activity_type("merge: merged feature") == "merge"
    assert reader._determine_activity_type("reset --hard HEAD~1") == "reset"
    assert reader._determine_activity_type("random message") == "other"


def test_is_git_repo_function():
    """Test is_git_repo utility function."""
    import tempfile

    with tempfile.TemporaryDirectory() as tmpdir:
        # Not a git repo
        assert is_git_repo(tmpdir) is False

        # Create .git directory
        git_dir = Path(tmpdir) / ".git"
        git_dir.mkdir()
        assert is_git_repo(tmpdir) is True


# ============ Sensor Tests ============

def test_sensor_source_item_identity():
    """Test source_item_identity generation."""
    sensor = GitActivitySensor()
    item = {
        "repo_path": "/Users/test/repo",
        "new_sha": "def456",
        "timestamp": datetime(2026, 3, 13, 10, 0, 0),
    }

    identity = sensor.source_item_identity(item)
    assert identity.startswith("git_")
    assert "def456"[:8] in identity


# ============ Plugin Tests ============

def test_default_settings():
    """Test DEFAULT_SETTINGS has expected structure."""
    assert "enabled" in DEFAULT_SETTINGS
    assert "repos" in DEFAULT_SETTINGS
    assert "sync_interval_minutes" in DEFAULT_SETTINGS
    assert "sensitive_mode" in DEFAULT_SETTINGS

    assert DEFAULT_SETTINGS["enabled"] is False
    assert DEFAULT_SETTINGS["sync_interval_minutes"] == 30
    assert DEFAULT_SETTINGS["sensitive_mode"] == "redact"


def test_fields_function():
    """Test _fields returns list of ExtensionFieldSpec."""
    from magi.plugins import ExtensionFieldSpec

    fields = _fields("sensors.git_activity")

    assert isinstance(fields, list)
    assert len(fields) > 0
    assert all(isinstance(f, ExtensionFieldSpec) for f in fields)

    field_keys = [f.key for f in fields]
    assert any("repos" in k for k in field_keys)
    assert any("sensitive" in k for k in field_keys)


def test_plugin_get_sensors_with_no_repos():
    """Test plugin still exposes sensor settings when no repos are configured."""
    from git_activity.plugin import GitActivityPlugin

    plugin = GitActivityPlugin()
    plugin.configure(manifest=None, settings={})
    sensors = plugin.get_sensors()
    assert len(sensors) == 1
    sensor_id, sensor_instance, sensor_spec = sensors[0]
    assert sensor_id == "timeline.git_activity"
    assert sensor_instance._repos == []
    assert sensor_spec.metadata["default_settings"]["enabled"] is False


# ============ Integration Tests ============

def test_sensor_build_output():
    """Test building a SensorOutput from git activity item."""
    sensor = GitActivitySensor()

    item = {
        "repo_path": "/Users/test/repo",
        "activity_type": "commit",
        "old_sha": "abc123",
        "new_sha": "def456",
        "message": "commit: Add feature",
        "author": "Test User <test@example.com>",
        "timestamp": datetime(2026, 3, 13, 10, 0, 0),
        "raw_line": "test line",
    }

    output = asyncio.run(sensor.build_output(item))

    assert output.source_type == "git_activity"
    assert "commit" in output.title
    assert len(output.content_blocks) > 0
    assert "git" in output.tags
    assert "commit" in output.tags
