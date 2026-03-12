from __future__ import annotations

import pytest

# Add plugins directory to sys.path to import plugins
from pathlib import Path
import sys

_plugins_path = Path(__file__).resolve().parents[2] / "plugins"
if str(_plugins_path) not in sys.path:
    sys.path.insert(0, str(_plugins_path))

from apple_health.types import HealthDataType, HEALTH_DATA_TYPES, get_enabled_types, get_default_enabled_types
from apple_health.exceptions import (
    HealthKitError,
    PlatformNotSupportedError,
    HealthKitNotAvailableError,
    AuthorizationDeniedError,
    HealthKitQueryError,
)


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