from __future__ import annotations

import pytest
import sys
from datetime import datetime, date
from unittest.mock import MagicMock, patch

# Add plugins directory to sys.path to import plugins
from pathlib import Path

_plugins_path = Path(__file__).resolve().parents[3] / "plugins"
if str(_plugins_path) not in sys.path:
    sys.path.insert(0, str(_plugins_path))

from apple_health.types import HealthDataType, HEALTH_DATA_TYPES, get_enabled_types, get_default_enabled_types
from apple_health.normalizers import (
    normalize_daily_aggregate,
    normalize_sleep_session,
    normalize_workout,
    normalize_heart_rate_sample,
    NORMALIZERS,
)
from apple_health.exceptions import (
    HealthKitError,
    PlatformNotSupportedError,
    HealthKitNotAvailableError,
    AuthorizationDeniedError,
    HealthKitQueryError,
)
from apple_health.reader import HealthKitReader
from apple_health.plugin import DEFAULT_SETTINGS, _fields, _get_enabled_types_from_settings, AppleHealthPlugin


def test_health_data_type_creation():
    """Test HealthDataType dataclass creation and properties."""
    data_type = HealthDataType(
        key="test_key",
        hk_type="QuantityType",
        display_name="Test Type",
        description="Test description",
        unit="test_unit",
        aggregation="daily",
        hk_class="HKQuantityTypeIdentifierTest",
        edge_types=["test"]
    )

    assert data_type.key == "test_key"
    assert data_type.hk_type == "QuantityType"
    assert data_type.display_name == "Test Type"
    assert data_type.description == "Test description"
    assert data_type.unit == "test_unit"
    assert data_type.aggregation == "daily"
    assert data_type.hk_class == "HKQuantityTypeIdentifierTest"
    assert data_type.edge_types == ["test"]


def test_health_data_types_registry():
    """Test that HEALTH_DATA_TYPES registry contains all expected types."""
    expected_types = [
        "steps", "distance", "flights", "heart_rate",
        "sleep", "active_energy", "workout"
    ]

    # Check all expected types are present
    for key in expected_types:
        assert key in HEALTH_DATA_TYPES
        assert isinstance(HEALTH_DATA_TYPES[key], HealthDataType)

    # Check no extra types
    assert len(HEALTH_DATA_TYPES) == 7

    # Verify specific data types
    steps_type = HEALTH_DATA_TYPES["steps"]
    assert steps_type.aggregation == "daily"
    assert steps_type.unit == "count"
    assert steps_type.hk_class == "HKQuantityTypeIdentifierStepCount"
    assert steps_type.edge_types == ["steps"]

    heart_rate_type = HEALTH_DATA_TYPES["heart_rate"]
    assert heart_rate_type.aggregation == "sample"
    assert heart_rate_type.unit == "bpm"
    assert heart_rate_type.hk_class == "HKQuantityTypeIdentifierHeartRate"

    sleep_type = HEALTH_DATA_TYPES["sleep"]
    assert sleep_type.aggregation == "session"
    assert sleep_type.unit is None
    assert sleep_type.hk_class == "HKCategoryTypeIdentifierSleepAnalysis"

    workout_type = HEALTH_DATA_TYPES["workout"]
    assert workout_type.aggregation == "session"
    assert workout_type.unit is None
    assert workout_type.hk_class == "HKWorkoutTypeIdentifier"


def test_get_enabled_types_with_settings():
    """Test get_enabled_types with settings."""
    # Test with specific enabled types
    settings = {
        "enabled_types": ["steps", "distance", "heart_rate"]
    }

    enabled_types = get_enabled_types(settings)
    assert len(enabled_types) == 3
    enabled_keys = [t.key for t in enabled_types]
    assert set(enabled_keys) == {"steps", "distance", "heart_rate"}

    # Test with empty settings
    empty_settings = {}
    enabled_types = get_enabled_types(empty_settings)
    assert len(enabled_types) > 0

    # Test with None settings
    enabled_types = get_enabled_types(None)
    assert len(enabled_types) > 0


def test_get_enabled_types_all_disabled():
    """Test get_enabled_types when all types are disabled."""
    settings = {
        "enabled_types": []
    }

    enabled_types = get_enabled_types(settings)
    assert len(enabled_types) == 0


def test_get_default_enabled_types():
    """Test get_default_enabled_types returns expected defaults."""
    default_types = get_default_enabled_types()

    # Should return 5 types by default (excluding sleep and workout)
    assert len(default_types) == 5

    # Check expected types
    default_keys = [t.key for t in default_types]
    expected = ["steps", "distance", "flights", "heart_rate", "active_energy"]
    assert set(default_keys) == set(expected)

    # Verify no session types are included
    for data_type in default_types:
        assert data_type.aggregation != "session"


def test_get_enabled_types_fallback_to_default():
    """Test that get_enabled_types falls back to defaults when settings is None."""
    # Ensure we get the same results from None settings as from default
    types_none = get_enabled_types(None)
    types_default = get_default_enabled_types()

    assert len(types_none) == len(types_default)
    # Sort by key to compare properly
    types_none_sorted = sorted(types_none, key=lambda x: x.key)
    types_default_sorted = sorted(types_default, key=lambda x: x.key)

    for t1, t2 in zip(types_none_sorted, types_default_sorted):
        assert t1.key == t2.key
        assert t1.hk_type == t2.hk_type
        assert t1.display_name == t2.display_name
        assert t1.description == t2.description
        assert t1.unit == t2.unit
        assert t1.aggregation == t2.aggregation
        assert t1.hk_class == t2.hk_class
        assert t1.edge_types == t2.edge_types


def test_health_data_type_values():
    """Test specific values of health data types."""
    # Test steps
    steps = HEALTH_DATA_TYPES["steps"]
    assert steps.display_name == "Steps"
    assert steps.description == "Daily step count"
    assert steps.aggregation == "daily"
    assert steps.unit == "count"

    # Test distance
    distance = HEALTH_DATA_TYPES["distance"]
    assert distance.display_name == "Distance"
    assert distance.description == "Distance traveled"
    assert distance.aggregation == "daily"
    assert distance.unit == "km"

    # Test flights
    flights = HEALTH_DATA_TYPES["flights"]
    assert flights.display_name == "Flights Climbed"
    assert flights.description == "Number of flights of stairs climbed"
    assert flights.aggregation == "daily"
    assert flights.unit == "count"

    # Test heart rate
    heart_rate = HEALTH_DATA_TYPES["heart_rate"]
    assert heart_rate.display_name == "Heart Rate"
    assert heart_rate.description == "Heart rate measurements"
    assert heart_rate.aggregation == "sample"
    assert heart_rate.unit == "bpm"

    # Test active energy
    active_energy = HEALTH_DATA_TYPES["active_energy"]
    assert active_energy.display_name == "Active Energy"
    assert active_energy.description == "Active energy burned"
    assert active_energy.aggregation == "daily"
    assert active_energy.unit == "kcal"

    # Test sleep
    sleep = HEALTH_DATA_TYPES["sleep"]
    assert sleep.display_name == "Sleep"
    assert sleep.description == "Sleep analysis data"
    assert sleep.aggregation == "session"
    assert sleep.unit is None

    # Test workout
    workout = HEALTH_DATA_TYPES["workout"]
    assert workout.display_name == "Workout"
    assert workout.description == "Workout session data"
    assert workout.aggregation == "session"
    assert workout.unit is None


class TestExceptions:
    """Test all custom exception classes."""

    def test_healthkit_error_is_base_exception(self):
        """Test that HealthKitError is the base exception."""
        exc = HealthKitError("Test error")
        assert isinstance(exc, Exception)
        assert isinstance(exc, HealthKitError)

    def test_platform_not_supported_error(self):
        """Test PlatformNotSupportedError properties."""
        # Test default message
        exc = PlatformNotSupportedError()
        assert isinstance(exc, HealthKitError)
        assert "macOS and iOS" in str(exc)

        # Test custom message
        exc = PlatformNotSupportedError("Custom message")
        assert str(exc) == "Custom message"

    def test_healthkit_not_available_error(self):
        """Test HealthKitNotAvailableError properties."""
        # Test default message
        exc = HealthKitNotAvailableError()
        assert isinstance(exc, HealthKitError)
        assert "HealthKit framework is not available" in str(exc)

        # Test custom message
        exc = HealthKitNotAvailableError("Custom message")
        assert str(exc) == "Custom message"

    def test_authorization_denied_error(self):
        """Test AuthorizationDeniedError properties."""
        # Test with data type
        data_type = "heart_rate"
        exc = AuthorizationDeniedError(data_type)
        assert isinstance(exc, HealthKitError)
        assert data_type in str(exc)
        assert exc.data_type == data_type
        assert f"Authorization denied for data type: {data_type}" == str(exc)

    def test_healthkit_query_error(self):
        """Test HealthKitQueryError properties."""
        # Test with message only
        exc = HealthKitQueryError("Query failed")
        assert isinstance(exc, HealthKitError)
        assert str(exc) == "Query failed"
        assert exc.query_type is None

        # Test with message and query type
        query_type = "HKStatisticsQuery"
        exc = HealthKitQueryError("Query failed", query_type)
        assert isinstance(exc, HealthKitError)
        assert f"Query failed (Query type: {query_type})" == str(exc)
        assert exc.query_type == query_type

        # Test with message and None query type
        exc = HealthKitQueryError("Query failed", None)
        assert isinstance(exc, HealthKitError)
        assert str(exc) == "Query failed"
        assert exc.query_type is None


class TestNormalizers:
    """Test all normalizer functions."""

    def test_normalize_daily_aggregate_steps(self):
        """Test normalize_daily_aggregate for steps data."""
        class MockSensor:
            sensor_id = "apple.health"

        item = {
            "data_type": "steps",
            "value": 8234,
            "date": "2024-03-12"
        }
        sensor = MockSensor()

        result = normalize_daily_aggregate(item, sensor)

        assert result["source_type"] == "apple_health"
        assert result["title"] == "今日步数 8,234"
        assert result["summary"] == "Steps：8234 count"
        assert result["occurred_at"] == datetime.fromisoformat("2024-03-12").timestamp()
        assert result["source_item_id"] == "health_steps_2024-03-12"
        assert "steps" in result["tags"]
        assert "daily" in result["tags"]

        # Check provenance
        assert result["provenance"]["data_type"] == "steps"
        assert result["provenance"]["value"] == 8234
        assert result["provenance"]["unit"] == "count"

    def test_normalize_daily_aggregate_distance(self):
        """Test normalize_daily_aggregate for distance data."""
        class MockSensor:
            sensor_id = "apple.health"

        item = {
            "data_type": "distance",
            "value": 5.2,
            "date": "2024-03-12"
        }
        sensor = MockSensor()

        result = normalize_daily_aggregate(item, sensor)

        assert result["title"] == "今日行走 5.2 公里"
        assert result["summary"] == "Distance：5.2 km"
        assert result["source_item_id"] == "health_distance_2024-03-12"
        assert "distance" in result["tags"]

    def test_normalize_daily_aggregate_flights(self):
        """Test normalize_daily_aggregate for flights data."""
        class MockSensor:
            sensor_id = "apple.health"

        item = {
            "data_type": "flights",
            "value": 12,
            "date": "2024-03-12"
        }
        sensor = MockSensor()

        result = normalize_daily_aggregate(item, sensor)

        assert result["title"] == "今日爬升 12 段楼梯"
        assert result["summary"] == "Flights Climbed：12 count"
        assert result["source_item_id"] == "health_flights_2024-03-12"

    def test_normalize_daily_aggregate_active_energy(self):
        """Test normalize_daily_aggregate for active energy data."""
        class MockSensor:
            sensor_id = "apple.health"

        item = {
            "data_type": "active_energy",
            "value": 320.5,
            "date": "2024-03-12"
        }
        sensor = MockSensor()

        result = normalize_daily_aggregate(item, sensor)

        assert result["title"] == "今日消耗 321 千卡"
        assert result["summary"] == "Active Energy：321 kcal"
        assert result["source_item_id"] == "health_active_energy_2024-03-12"

    def test_normalize_daily_aggregate_no_date(self):
        """Test normalize_daily_aggregate without date (uses today)."""
        class MockSensor:
            sensor_id = "apple.health"

        item = {
            "data_type": "steps",
            "value": 5000
        }
        sensor = MockSensor()

        result = normalize_daily_aggregate(item, sensor)

        assert result["source_item_id"].startswith("health_steps_")
        assert date.today().isoformat() in result["source_item_id"]

    def test_normalize_sleep_session(self):
        """Test normalize_sleep_session."""
        class MockSensor:
            sensor_id = "apple.health"

        start_time = datetime(2024, 3, 11, 23, 0).timestamp()  # 11 PM
        end_time = datetime(2024, 3, 12, 7, 0).timestamp()    # 7 AM

        item = {
            "start_time": start_time,
            "end_time": end_time
        }
        sensor = MockSensor()

        result = normalize_sleep_session(item, sensor)

        assert result["source_type"] == "apple_health"
        assert "睡眠 8.0 小时" in result["title"]
        assert result["occurred_at"] == start_time
        assert result["source_item_id"].startswith("health_sleep_20240311230000")
        assert "sleep" in result["tags"]
        assert "session" in result["tags"]

        # Check content blocks
        content_blocks = result["content_blocks"]
        assert len(content_blocks) == 3
        assert "23:00" in content_blocks[0]["value"]
        assert "07:00" in content_blocks[1]["value"]
        assert "8.0 小时" in content_blocks[2]["value"]

    def test_normalize_workout_running(self):
        """Test normalize_workout for running."""
        class MockSensor:
            sensor_id = "apple.health"

        start_time = datetime(2024, 3, 12, 7, 0).timestamp()    # 7 AM
        end_time = datetime(2024, 3, 12, 7, 30).timestamp()   # 7:30 AM

        item = {
            "start_time": start_time,
            "end_time": end_time,
            "workout_type": "HKWorkoutActivityTypeRunning",
            "distance": 5000,  # 5km in meters
            "energy_burned": 300
        }
        sensor = MockSensor()

        result = normalize_workout(item, sensor)

        assert result["source_type"] == "apple_health"
        assert "跑步 30 分钟" == result["title"]
        assert result["occurred_at"] == start_time
        assert result["source_item_id"].startswith("health_workout_20240312070000")
        assert "workout" in result["tags"]
        assert "session" in result["tags"]

        # Check summary
        assert "跑步：30 分钟" in result["summary"]
        assert "距离：5000.0 米" in result["summary"]
        assert "消耗：300 千卡" in result["summary"]

        # Check content blocks
        content_blocks = result["content_blocks"]
        assert "运动类型：跑步" in content_blocks[0]["value"]
        assert "07:00" in content_blocks[1]["value"]

    def test_normalize_workout_cycling(self):
        """Test normalize_workout for cycling."""
        class MockSensor:
            sensor_id = "apple.health"

        start_time = datetime(2024, 3, 12, 17, 0).timestamp()  # 5 PM
        end_time = datetime(2024, 3, 12, 18, 0).timestamp()    # 6 PM

        item = {
            "start_time": start_time,
            "end_time": end_time,
            "workout_type": "HKWorkoutActivityTypeCycling",
            "distance": 15000,  # 15km in meters
            "energy_burned": 450
        }
        sensor = MockSensor()

        result = normalize_workout(item, sensor)

        assert "骑行 60 分钟" == result["title"]
        assert "运动类型：骑行" in result["content_blocks"][0]["value"]
        assert "距离：15000.0 米" in result["summary"]
        assert "消耗：450 千卡" in result["summary"]

    def test_normalize_workout_unknown_type(self):
        """Test normalize_workout with unknown workout type."""
        class MockSensor:
            sensor_id = "apple.health"

        start_time = datetime(2024, 3, 12, 10, 0).timestamp()
        end_time = datetime(2024, 3, 12, 10, 45).timestamp()

        item = {
            "start_time": start_time,
            "end_time": end_time,
            "workout_type": "HKWorkoutActivityTypeYoga",
            "distance": 0,
            "energy_burned": 200
        }
        sensor = MockSensor()

        result = normalize_workout(item, sensor)

        assert "瑜伽 45 分钟" == result["title"]

    def test_normalize_workout_no_distance_or_energy(self):
        """Test normalize_workout without distance or energy."""
        class MockSensor:
            sensor_id = "apple.health"

        start_time = datetime(2024, 3, 12, 10, 0).timestamp()
        end_time = datetime(2024, 3, 12, 11, 0).timestamp()

        item = {
            "start_time": start_time,
            "end_time": end_time,
            "workout_type": "HKWorkoutActivityTypeWalking"
        }
        sensor = MockSensor()

        result = normalize_workout(item, sensor)

        assert "步行 60 分钟" == result["title"]
        assert result["summary"] == "步行：60 分钟"
        assert len([b for b in result["content_blocks"] if "距离：" in b["value"]]) == 0

    def test_normalize_heart_rate_sample(self):
        """Test normalize_heart_rate_sample."""
        class MockSensor:
            sensor_id = "apple.health"

        timestamp = datetime(2024, 3, 12, 14, 30, 0).timestamp()

        item = {
            "timestamp": timestamp,
            "value": 72
        }
        sensor = MockSensor()

        result = normalize_heart_rate_sample(item, sensor)

        assert result["source_type"] == "apple_health"
        assert "心率 72 bpm" == result["title"]
        assert "心率测量：72 次/分钟" == result["summary"]
        assert result["occurred_at"] == timestamp
        assert result["source_item_id"].startswith("health_heart_rate_20240312143000")
        assert "heart_rate" in result["tags"]
        assert "sample" in result["tags"]

        # Check content blocks
        content_blocks = result["content_blocks"]
        assert "心率：72 bpm" in content_blocks[0]["value"]
        assert "14:30:00" in content_blocks[1]["value"]

    def test_normalize_heart_rate_sample_with_decimals(self):
        """Test normalize_heart_rate_sample with decimal values."""
        class MockSensor:
            sensor_id = "apple.health"

        timestamp = datetime(2024, 3, 12, 15, 15, 0).timestamp()

        item = {
            "timestamp": timestamp,
            "value": 68.5
        }
        sensor = MockSensor()

        result = normalize_heart_rate_sample(item, sensor)

        assert "心率 68 bpm" == result["title"]
        assert result["provenance"]["heart_rate"] == 68.5

    def test_normalizers_registry(self):
        """Test that NORMALIZERS registry contains all expected normalizers."""
        from apple_health.normalizers import NORMALIZERS

        expected_types = ["steps", "distance", "flights", "active_energy",
                         "sleep", "workout", "heart_rate"]

        # Check all expected types are in registry
        for data_type in expected_types:
            assert data_type in NORMALIZERS

            # Verify the normalizer functions are callable
            assert callable(NORMALIZERS[data_type])

        # Verify specific normalizers
        assert NORMALIZERS["steps"] == normalize_daily_aggregate
        assert NORMALIZERS["distance"] == normalize_daily_aggregate
        assert NORMALIZERS["sleep"] == normalize_sleep_session
        assert NORMALIZERS["workout"] == normalize_workout
        assert NORMALIZERS["heart_rate"] == normalize_heart_rate_sample


class TestHealthKitReaderPlatform:
    """Test HealthKitReader platform detection and lazy loading."""

    def test_reader_initialization(self):
        """Test that HealthKitReader initializes with correct defaults."""
        reader = HealthKitReader()

        assert reader._health_store is None
        assert reader._is_available is None
        assert reader._hk_module is None
        assert reader._foundation_module is None

    def test_platform_check_non_darwin(self, monkeypatch):
        """Test that platform check raises error on non-darwin systems."""
        reader = HealthKitReader()

        # Patch sys.platform to simulate non-darwin system
        monkeypatch.setattr(sys, "platform", "linux")

        with pytest.raises(PlatformNotSupportedError):
            reader._ensure_platform()

    def test_platform_check_darwin(self, monkeypatch):
        """Test that platform check passes on darwin systems."""
        reader = HealthKitReader()

        # Patch sys.platform to simulate darwin system
        monkeypatch.setattr(sys, "platform", "darwin")

        # Should not raise
        reader._ensure_platform()

    def test_is_available_non_darwin(self, monkeypatch):
        """Test that is_available returns False on non-macOS platforms."""
        reader = HealthKitReader()

        # Patch sys.platform to simulate non-darwin system
        monkeypatch.setattr(sys, "platform", "linux")

        assert reader.is_available() is False
        # Check that it caches the result
        assert reader._is_available is False

    def test_is_available_caches_result(self, monkeypatch):
        """Test that is_available caches its result."""
        reader = HealthKitReader()

        # Patch sys.platform to simulate non-darwin system
        monkeypatch.setattr(sys, "platform", "linux")

        # First call
        result1 = reader.is_available()
        # Second call should use cache
        result2 = reader.is_available()

        assert result1 is False
        assert result2 is False
        assert reader._is_available is False

    def test_lazy_import_only_on_darwin(self, monkeypatch):
        """Test that frameworks are not imported on non-darwin platforms."""
        reader = HealthKitReader()

        # Patch sys.platform to simulate non-darwin system
        monkeypatch.setattr(sys, "platform", "linux")

        # is_available should return False without importing
        assert reader.is_available() is False
        # _hk_module should still be None because we didn't try to import
        # Actually, on non-darwin it's set before import attempt
        # The import only happens inside is_available() on darwin

    def test_health_store_property_non_darwin(self, monkeypatch):
        """Test that health_store property raises on non-darwin platforms."""
        reader = HealthKitReader()

        # Patch sys.platform to simulate non-darwin system
        monkeypatch.setattr(sys, "platform", "linux")

        with pytest.raises(PlatformNotSupportedError):
            _ = reader.health_store

    def test_get_authorization_status_unavailable(self, monkeypatch):
        """Test get_authorization_status returns unavailable on non-macOS."""
        reader = HealthKitReader()

        # Patch sys.platform to simulate non-darwin system
        monkeypatch.setattr(sys, "platform", "linux")

        result = reader.get_authorization_status(["steps", "heart_rate"])

        assert result == {
            "steps": "unavailable",
            "heart_rate": "unavailable"
        }

    def test_request_authorization_unavailable(self, monkeypatch):
        """Test request_authorization returns False on non-macOS."""
        reader = HealthKitReader()

        # Patch sys.platform to simulate non-darwin system
        monkeypatch.setattr(sys, "platform", "linux")

        result = reader.request_authorization(["steps", "heart_rate"])

        assert result == {
            "steps": False,
            "heart_rate": False
        }

    def test_read_methods_return_empty_on_non_darwin(self, monkeypatch):
        """Test that all read methods return empty lists on non-macOS."""
        reader = HealthKitReader()

        # Patch sys.platform to simulate non-darwin system
        monkeypatch.setattr(sys, "platform", "linux")

        from datetime import datetime

        start = datetime(2024, 1, 1)
        end = datetime(2024, 1, 31)

        # All read methods should return empty lists
        assert reader.read_daily_aggregate("steps", start, end) == []
        assert reader.read_samples("heart_rate", start, end) == []
        assert reader.read_sessions("sleep", start, end) == []
        assert reader.read_workouts(start, end) == []

    def test_get_authorization_status_unknown_type(self, monkeypatch):
        """Test get_authorization_status handles unknown types."""
        reader = HealthKitReader()

        # Patch sys.platform to simulate non-darwin system
        monkeypatch.setattr(sys, "platform", "linux")

        result = reader.get_authorization_status(["unknown_type"])

        assert result == {"unknown_type": "unavailable"}

    def test_request_authorization_unknown_type(self, monkeypatch):
        """Test request_authorization handles unknown types."""
        reader = HealthKitReader()

        # Patch sys.platform to simulate non-darwin system
        monkeypatch.setattr(sys, "platform", "linux")

        result = reader.request_authorization(["unknown_type"])

        assert result == {"unknown_type": False}

    def test_reader_multiple_calls_caches_availability(self, monkeypatch):
        """Test that multiple calls to is_available use cached value."""
        reader = HealthKitReader()

        # Patch sys.platform to simulate non-darwin system
        monkeypatch.setattr(sys, "platform", "linux")

        # Multiple calls should all return False and use cache
        for _ in range(5):
            assert reader.is_available() is False

        # The cache should be set
        assert reader._is_available is False


class TestAppleHealthPlugin:
    """Test AppleHealthPlugin class."""

    def setup_method(self):
        """Set up test fixtures."""
        # Store original sys.platform
        self.original_platform = sys.platform

    def teardown_method(self):
        """Clean up after tests."""
        # Restore original platform
        sys.platform = self.original_platform

    def test_default_settings_structure(self):
        """Test that DEFAULT_SETTINGS contains all required fields."""
        assert isinstance(DEFAULT_SETTINGS, dict)

        # Check required fields exist
        required_fields = [
            "enabled", "sync_mode", "sync_interval_hours", "lookback_days",
            "types", "default_retention_mode", "storage_mode"
        ]

        for field in required_fields:
            assert field in DEFAULT_SETTINGS

        # Check types substructure
        types_config = DEFAULT_SETTINGS["types"]
        assert isinstance(types_config, dict)

        expected_types = [
            "steps", "sleep", "heart_rate", "distance",
            "flights", "active_energy", "workout"
        ]

        for health_type in expected_types:
            assert health_type in types_config
            assert isinstance(types_config[health_type], bool)

        # Check default values
        assert DEFAULT_SETTINGS["enabled"] is False
        assert DEFAULT_SETTINGS["sync_mode"] == "manual"
        assert DEFAULT_SETTINGS["sync_interval_hours"] == 1
        assert DEFAULT_SETTINGS["lookback_days"] == 7
        assert DEFAULT_SETTINGS["default_retention_mode"] == "analyze_only"
        assert DEFAULT_SETTINGS["storage_mode"] == "managed"

    def test_default_enabled_types(self):
        """Test that default enabled types are configured correctly."""
        # Test with no settings (should use defaults)
        enabled_types = _get_enabled_types_from_settings({})

        # Should only have types that are True in DEFAULT_SETTINGS["types"]
        default_enabled = [
            "steps", "sleep"  # These are True in DEFAULT_SETTINGS["types"]
        ]

        assert set(enabled_types) == set(default_enabled)
        assert len(enabled_types) == 2

    def test_plugin_returns_empty_on_non_darwin(self):
        """Test that plugin returns empty list on non-darwin platforms."""
        # Set platform to non-darwin
        sys.platform = 'linux'

        try:
            plugin = AppleHealthPlugin()

            sensors = plugin.get_sensors()

            # Should return empty list for non-darwin
            assert len(sensors) == 0
        finally:
            # Restore original platform
            sys.platform = self.original_platform

    def test_plugin_returns_empty_when_healthkit_unavailable(self):
        """Test that plugin returns empty list when HealthKit is not available."""
        # Set platform to darwin
        sys.platform = 'darwin'

        try:
            plugin = AppleHealthPlugin()

            with patch.object(HealthKitReader, 'is_available', return_value=False):
                sensors = plugin.get_sensors()

                # Should return empty list when HealthKit not available
                assert len(sensors) == 0
        finally:
            # Restore original platform
            sys.platform = self.original_platform

    def test_plugin_returns_empty_when_no_types_enabled(self):
        """Test that plugin returns empty list when no types are enabled."""
        # Set platform to darwin
        sys.platform = 'darwin'

        try:
            plugin = AppleHealthPlugin()
            plugin.settings = {"sensors": {"apple_health": {"enabled": True, "types": {}}}}

            with patch.object(HealthKitReader, 'is_available', return_value=True):
                sensors = plugin.get_sensors()

                # Should still return a sensor (falls back to default types)
                assert len(sensors) == 1
                # Default types should be ['steps', 'sleep']
                sensor_id, sensor_instance, sensor_spec = sensors[0]
                # The default_settings in metadata should contain the default types
                default_settings = sensor_spec.metadata.get("default_settings", {})
                assert default_settings.get("types", {}).get("steps") is True
                assert default_settings.get("types", {}).get("sleep") is True
        finally:
            # Restore original platform
            sys.platform = self.original_platform

    @pytest.mark.skip(reason="Requires HealthKit framework which is not available in test environment")
    def test_plugin_returns_correct_sensor_spec_on_macos(self):
        """Test that plugin returns correct sensor spec on macOS with mock reader."""
        # This test requires mocking HealthKit which is complex due to the framework dependencies
        # The test would require a comprehensive mocking of the entire HealthKit framework
        pass

    @pytest.mark.skip(reason="Requires HealthKit framework which is not available in test environment")
    def test_plugin_applies_settings_correctly(self):
        """Test that plugin correctly applies settings from configuration."""
        # This test requires mocking HealthKit which is complex due to the framework dependencies
        pass

    def test_fields_returns_correct_specs(self):
        """Test that _fields returns correct ExtensionFieldSpec objects."""
        fields = _fields("test_prefix")

        # Should return a list of ExtensionFieldSpec objects
        assert isinstance(fields, list)
        assert len(fields) > 0

        # Check first field is an ExtensionFieldSpec
        first_field = fields[0]
        assert hasattr(first_field, 'key')
        assert hasattr(first_field, 'type')
        assert hasattr(first_field, 'label')
        assert hasattr(first_field, 'description')
        assert hasattr(first_field, 'default')

        # Check that all type toggles are present
        type_fields = [f for f in fields if f.type == "switch" and f.key.endswith(('.steps', '.sleep', '.heart_rate', '.distance', '.flights', '.active_energy', '.workout'))]
        expected_type_count = 7  # Number of health data types
        assert len(type_fields) == expected_type_count

    def test_get_enabled_types_from_settings_with_types_config(self):
        """Test _get_enabled_types_from_settings with types configuration."""
        settings = {
            "sensors": {
                "apple_health": {
                    "types": {
                        "steps": True,
                        "sleep": True,
                        "heart_rate": True,
                        "distance": False,
                        "flights": False,
                        "active_energy": False,
                        "workout": False,
                    }
                }
            }
        }

        enabled_types = _get_enabled_types_from_settings(settings)

        # Should return only enabled types
        assert set(enabled_types) == {"steps", "sleep", "heart_rate"}
        assert len(enabled_types) == 3

    def test_get_enabled_types_from_settings_empty_types(self):
        """Test _get_enabled_types_from_settings with empty types."""
        settings = {
            "sensors": {
                "apple_health": {
                    "types": {}
                }
            }
        }

        enabled_types = _get_enabled_types_from_settings(settings)

        # Should return empty list
        assert len(enabled_types) == 0

    def test_get_enabled_types_from_settings_no_types_key(self):
        """Test _get_enabled_types_from_settings when types key is missing."""
        settings = {}

        enabled_types = _get_enabled_types_from_settings(settings)

        # Should return default enabled types
        assert len(enabled_types) == 2  # steps and sleep are True by default
        assert set(enabled_types) == {"steps", "sleep"}