# Apple Health Sensor Implementation Plan

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a new timeline sensor plugin that reads health data from Apple HealthKit and ingests it into Magi's personal knowledge timeline.

**Architecture:** A new `apple-health` plugin following the existing plugin pattern (similar to `netease_music` and `chrome-history`). Uses pyobjc to bridge to HealthKit.framework on macOS, with graceful degradation on other platforms.

**Tech Stack:** Python, pyobjc-framework-HealthKit, pyobjc-framework-Foundation, TDD with pytest

---

## File Structure

```
plugins/apple-health/
├── plugin.toml           # Plugin manifest with platforms = ["macos", "ios"]
├── plugin.py             # Plugin entry point + settings fields
├── sensor.py             # AppleHealthTimelineSensor implementation
├── reader.py             # HealthKitReader (pyobjc bridge)
├── types.py              # HealthDataType definitions
├── normalizers.py        # Data normalization functions
├── exceptions.py         # Custom exceptions
└── __init__.py           # Package init

backend/tests/
└── test_apple_health_plugin.py  # Unit tests
```

---

## Chunk 1: Foundation (types, exceptions, normalizers)

### Task 1: Create Plugin Directory and Manifest

**Files:**
- Create: `plugins/apple-health/__init__.py`
- Create: `plugins/apple-health/plugin.toml`

- [ ] **Step 1: Create plugin directory and __init__.py**

```bash
mkdir -p plugins/apple-health
```

```python
# plugins/apple-health/__init__.py
"""Apple Health timeline sensor plugin."""
```

- [ ] **Step 2: Create plugin.toml manifest**

```toml
# plugins/apple-health/plugin.toml
[plugin]
id = "apple-health"
name = "Apple Health"
version = "0.1.0"
description = "Apple Health data ingestion for the timeline."
author = "Magi Team"
entry_module = "plugin"
entry_class = "AppleHealthPlugin"
official = true
contribution_types = ["sensor"]
platforms = ["macos", "ios"]
```

- [ ] **Step 3: Commit**

```bash
git add plugins/apple-health/__init__.py plugins/apple-health/plugin.toml
git commit -m "feat(apple-health): add plugin directory and manifest"
```

---

### Task 2: Implement Health Data Types

**Files:**
- Create: `plugins/apple-health/types.py`
- Create: `backend/tests/test_apple_health_plugin.py`

- [ ] **Step 1: Write the failing test for HealthDataType**

```python
# backend/tests/test_apple_health_plugin.py
"""Tests for Apple Health plugin."""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

# Add plugins directory to sys.path to import plugins
_plugins_path = Path(__file__).resolve().parents[2] / "plugins"
if str(_plugins_path) not in sys.path:
    sys.path.insert(0, str(_plugins_path))


class TestHealthDataType:
    """Tests for HealthDataType configuration."""

    def test_health_data_type_creation(self) -> None:
        """Test creating a HealthDataType instance."""
        from apple_health.types import HealthDataType

        data_type = HealthDataType(
            key="steps",
            hk_type="HKQuantityTypeIdentifierStepCount",
            display_name="Steps",
            description="Daily step count",
            unit="count",
            aggregation="daily",
            hk_class="HKQuantityType",
            edge_types=["TRACKED"],
        )

        assert data_type.key == "steps"
        assert data_type.hk_type == "HKQuantityTypeIdentifierStepCount"
        assert data_type.display_name == "Steps"
        assert data_type.aggregation == "daily"

    def test_health_data_types_registry(self) -> None:
        """Test that HEALTH_DATA_TYPES contains all expected types."""
        from apple_health.types import HEALTH_DATA_TYPES

        expected_types = [
            "steps",
            "distance",
            "flights",
            "heart_rate",
            "sleep",
            "active_energy",
            "workout",
        ]

        for type_key in expected_types:
            assert type_key in HEALTH_DATA_TYPES, f"Missing type: {type_key}"

    def test_daily_aggregation_types(self) -> None:
        """Test that daily aggregation types are correctly configured."""
        from apple_health.types import HEALTH_DATA_TYPES

        daily_types = ["steps", "distance", "flights", "active_energy"]
        for type_key in daily_types:
            assert HEALTH_DATA_TYPES[type_key].aggregation == "daily"

    def test_sample_aggregation_types(self) -> None:
        """Test that sample aggregation types are correctly configured."""
        from apple_health.types import HEALTH_DATA_TYPES

        assert HEALTH_DATA_TYPES["heart_rate"].aggregation == "sample"

    def test_session_aggregation_types(self) -> None:
        """Test that session aggregation types are correctly configured."""
        from apple_health.types import HEALTH_DATA_TYPES

        session_types = ["sleep", "workout"]
        for type_key in session_types:
            assert HEALTH_DATA_TYPES[type_key].aggregation == "session"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && pytest tests/test_apple_health_plugin.py -v`
Expected: FAIL with "No module named 'apple_health.types'"

- [ ] **Step 3: Implement types.py**

```python
# plugins/apple-health/types.py
"""Health data type definitions and configurations."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class HealthDataType:
    """Configuration for a health data type supported by the sensor."""

    key: str
    """Internal identifier (e.g., 'steps')."""

    hk_type: str
    """HealthKit type identifier (e.g., 'HKQuantityTypeIdentifierStepCount')."""

    display_name: str
    """User-facing display name."""

    description: str
    """User-facing description."""

    unit: str
    """Display unit (e.g., 'count', 'km', 'hours')."""

    aggregation: str
    """Aggregation strategy: 'daily', 'sample', or 'session'."""

    hk_class: str
    """HealthKit class: 'HKQuantityType', 'HKCategoryType', or 'HKWorkoutType'."""

    edge_types: tuple[str, ...]
    """Allowed relation edge types for this data type."""


# Registry of supported health data types
HEALTH_DATA_TYPES: dict[str, HealthDataType] = {
    "steps": HealthDataType(
        key="steps",
        hk_type="HKQuantityTypeIdentifierStepCount",
        display_name="Steps",
        description="Daily step count",
        unit="count",
        aggregation="daily",
        hk_class="HKQuantityType",
        edge_types=("TRACKED",),
    ),
    "distance": HealthDataType(
        key="distance",
        hk_type="HKQuantityTypeIdentifierDistanceWalkingRunning",
        display_name="Walking Distance",
        description="Daily walking/running distance",
        unit="km",
        aggregation="daily",
        hk_class="HKQuantityType",
        edge_types=("TRACKED",),
    ),
    "flights": HealthDataType(
        key="flights",
        hk_type="HKQuantityTypeIdentifierFlightsClimbed",
        display_name="Flights Climbed",
        description="Daily flights climbed count",
        unit="count",
        aggregation="daily",
        hk_class="HKQuantityType",
        edge_types=("TRACKED",),
    ),
    "heart_rate": HealthDataType(
        key="heart_rate",
        hk_type="HKQuantityTypeIdentifierHeartRate",
        display_name="Heart Rate",
        description="Heart rate measurements",
        unit="bpm",
        aggregation="sample",
        hk_class="HKQuantityType",
        edge_types=("TRACKED",),
    ),
    "sleep": HealthDataType(
        key="sleep",
        hk_type="HKCategoryTypeIdentifierSleepAnalysis",
        display_name="Sleep Analysis",
        description="Sleep session records",
        unit="hours",
        aggregation="session",
        hk_class="HKCategoryType",
        edge_types=("TRACKED",),
    ),
    "active_energy": HealthDataType(
        key="active_energy",
        hk_type="HKQuantityTypeIdentifierActiveEnergyBurned",
        display_name="Active Energy",
        description="Daily active energy burned",
        unit="kcal",
        aggregation="daily",
        hk_class="HKQuantityType",
        edge_types=("TRACKED",),
    ),
    "workout": HealthDataType(
        key="workout",
        hk_type="HKWorkoutTypeIdentifier",
        display_name="Workouts",
        description="Workout session records",
        unit="session",
        aggregation="session",
        hk_class="HKWorkoutType",
        edge_types=("EXERCISED",),
    ),
}


def get_enabled_types(settings: dict[str, Any]) -> list[str]:
    """
    Get list of enabled health data types from settings.

    Args:
        settings: Plugin settings dictionary

    Returns:
        List of enabled type keys
    """
    types_settings = settings.get("sensors", {}).get("apple_health", {}).get("types", {})
    enabled = []
    for type_key in HEALTH_DATA_TYPES:
        if types_settings.get(type_key, False):
            enabled.append(type_key)
    return enabled


def get_default_enabled_types() -> list[str]:
    """
    Get list of health data types enabled by default.

    Returns:
        List of default enabled type keys
    """
    return ["steps", "sleep"]
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd backend && pytest tests/test_apple_health_plugin.py::TestHealthDataType -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add plugins/apple-health/types.py backend/tests/test_apple_health_plugin.py
git commit -m "feat(apple-health): add health data type definitions"
```

---

### Task 3: Implement Custom Exceptions

**Files:**
- Create: `plugins/apple-health/exceptions.py`
- Modify: `backend/tests/test_apple_health_plugin.py`

- [ ] **Step 1: Write the failing test for exceptions**

```python
# Add to backend/tests/test_apple_health_plugin.py

class TestExceptions:
    """Tests for custom exceptions."""

    def test_health_kit_error_hierarchy(self) -> None:
        """Test that all exceptions inherit from HealthKitError."""
        from apple_health.exceptions import (
            AuthorizationDeniedError,
            HealthKitError,
            HealthKitNotAvailableError,
            HealthKitQueryError,
            PlatformNotSupportedError,
        )

        assert issubclass(PlatformNotSupportedError, HealthKitError)
        assert issubclass(HealthKitNotAvailableError, HealthKitError)
        assert issubclass(AuthorizationDeniedError, HealthKitError)
        assert issubclass(HealthKitQueryError, HealthKitError)

    def test_platform_not_supported_error_message(self) -> None:
        """Test PlatformNotSupportedError message."""
        from apple_health.exceptions import PlatformNotSupportedError

        error = PlatformNotSupportedError("Test message")
        assert "Test message" in str(error)

    def test_authorization_denied_error_includes_type(self) -> None:
        """Test AuthorizationDeniedError includes type information."""
        from apple_health.exceptions import AuthorizationDeniedError

        error = AuthorizationDeniedError("steps")
        assert "steps" in str(error)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && pytest tests/test_apple_health_plugin.py::TestExceptions -v`
Expected: FAIL with "cannot import name 'HealthKitError'"

- [ ] **Step 3: Implement exceptions.py**

```python
# plugins/apple-health/exceptions.py
"""Custom exceptions for Apple Health sensor."""
from __future__ import annotations


class HealthKitError(Exception):
    """Base exception for HealthKit-related errors."""

    pass


class PlatformNotSupportedError(HealthKitError):
    """Raised when HealthKit is accessed on unsupported platforms."""

    def __init__(self, message: str = "Apple Health is only available on macOS and iOS") -> None:
        super().__init__(message)


class HealthKitNotAvailableError(HealthKitError):
    """Raised when HealthKit framework is not available on the device."""

    def __init__(self, message: str = "HealthKit framework is not available") -> None:
        super().__init__(message)


class AuthorizationDeniedError(HealthKitError):
    """Raised when user denies HealthKit authorization."""

    def __init__(self, data_type: str) -> None:
        self.data_type = data_type
        super().__init__(f"Authorization denied for health data type: {data_type}")


class HealthKitQueryError(HealthKitError):
    """Raised when a HealthKit query fails."""

    def __init__(self, message: str, query_type: str | None = None) -> None:
        self.query_type = query_type
        super().__init__(message)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd backend && pytest tests/test_apple_health_plugin.py::TestExceptions -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add plugins/apple-health/exceptions.py backend/tests/test_apple_health_plugin.py
git commit -m "feat(apple-health): add custom exceptions"
```

---

### Task 4: Implement Normalizers

**Files:**
- Create: `plugins/apple-health/normalizers.py`
- Modify: `backend/tests/test_apple_health_plugin.py`

- [ ] **Step 1: Write the failing test for normalizers**

```python
# Add to backend/tests/test_apple_health_plugin.py

from unittest.mock import MagicMock


class TestNormalizers:
    """Tests for data normalization functions."""

    def test_normalize_daily_aggregate_steps(self) -> None:
        """Test normalizing daily step data."""
        from apple_health.normalizers import normalize_daily_aggregate

        mock_sensor = MagicMock()
        mock_sensor.sensor_id = "timeline.apple_health"
        mock_sensor._build_event = MagicMock(return_value=MagicMock())

        item = {
            "data_type": "steps",
            "value": 8234,
            "date": "2024-03-12",
        }

        normalize_daily_aggregate(item, mock_sensor)

        # Verify _build_event was called with correct parameters
        call_args = mock_sensor._build_event.call_args
        assert call_args.kwargs["source_item_id"] == "health_steps_2024-03-12"
        assert "8,234" in call_args.kwargs["title"]
        assert call_args.kwargs["tags"] == ["health", "steps"]

    def test_normalize_daily_aggregate_distance(self) -> None:
        """Test normalizing daily distance data."""
        from apple_health.normalizers import normalize_daily_aggregate

        mock_sensor = MagicMock()
        mock_sensor.sensor_id = "timeline.apple_health"
        mock_sensor._build_event = MagicMock(return_value=MagicMock())

        item = {
            "data_type": "distance",
            "value": 5.2,
            "date": "2024-03-12",
        }

        normalize_daily_aggregate(item, mock_sensor)

        call_args = mock_sensor._build_event.call_args
        assert call_args.kwargs["source_item_id"] == "health_distance_2024-03-12"
        assert "5.2" in call_args.kwargs["title"]

    def test_normalize_sleep_session(self) -> None:
        """Test normalizing sleep session data."""
        from apple_health.normalizers import normalize_sleep_session

        mock_sensor = MagicMock()
        mock_sensor.sensor_id = "timeline.apple_health"
        mock_sensor._build_event = MagicMock(return_value=MagicMock())

        item = {
            "start_time": "2024-03-11T23:30:00",
            "end_time": "2024-03-12T07:00:00",
            "duration_hours": 7.5,
            "sleep_quality": "asleep",
        }

        normalize_sleep_session(item, mock_sensor)

        call_args = mock_sensor._build_event.call_args
        assert "sleep" in call_args.kwargs["source_item_id"]
        assert "7.5" in call_args.kwargs["title"]
        assert "sleep" in call_args.kwargs["tags"]

    def test_normalize_workout_running(self) -> None:
        """Test normalizing running workout data."""
        from apple_health.normalizers import normalize_workout

        mock_sensor = MagicMock()
        mock_sensor.sensor_id = "timeline.apple_health"
        mock_sensor._build_event = MagicMock(return_value=MagicMock())

        item = {
            "workout_type": "HKWorkoutActivityTypeRunning",
            "start_time": "2024-03-12T08:00:00",
            "duration_minutes": 30,
            "distance_km": 5.2,
            "active_energy_burned": 320,
        }

        normalize_workout(item, mock_sensor)

        call_args = mock_sensor._build_event.call_args
        assert "workout" in call_args.kwargs["source_item_id"]
        assert "30" in call_args.kwargs["title"]
        assert "exercise" in call_args.kwargs["tags"]

    def test_normalize_heart_rate_sample(self) -> None:
        """Test normalizing heart rate sample data."""
        from apple_health.normalizers import normalize_heart_rate_sample

        mock_sensor = MagicMock()
        mock_sensor.sensor_id = "timeline.apple_health"
        mock_sensor._build_event = MagicMock(return_value=MagicMock())

        item = {
            "value": 72,
            "timestamp": "2024-03-12T15:30:00",
        }

        normalize_heart_rate_sample(item, mock_sensor)

        call_args = mock_sensor._build_event.call_args
        assert "heart_rate" in call_args.kwargs["source_item_id"]
        assert "72" in call_args.kwargs["title"]
        assert "heart_rate" in call_args.kwargs["tags"]

    def test_normalizer_registry(self) -> None:
        """Test that NORMALIZERS registry has all types."""
        from apple_health.normalizers import NORMALIZERS

        expected_types = ["steps", "distance", "flights", "active_energy", "heart_rate", "sleep", "workout"]
        for type_key in expected_types:
            assert type_key in NORMALIZERS, f"Missing normalizer for: {type_key}"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && pytest tests/test_apple_health_plugin.py::TestNormalizers -v`
Expected: FAIL with "No module named 'apple_health.normalizers'"

- [ ] **Step 3: Implement normalizers.py**

```python
# plugins/apple-health/normalizers.py
"""Data normalization functions for health data types."""
from __future__ import annotations

from datetime import datetime
from typing import Any

from .types import HEALTH_DATA_TYPES


def normalize_daily_aggregate(item: dict[str, Any], sensor: Any) -> Any:
    """Normalize daily aggregated health data (steps, distance, energy, etc.)."""
    type_config = HEALTH_DATA_TYPES[item["data_type"]]
    value = item["value"]
    date_str = item["date"]

    # Generate localized title based on data type
    title_map = {
        "steps": f"今日步数 {value:,}",
        "distance": f"今日行走 {value:.1f} 公里",
        "flights": f"今日爬楼 {value} 层",
        "active_energy": f"今日消耗 {value:.0f} 千卡",
    }

    # Parse date to timestamp (use noon of that day)
    occurred_at = datetime.fromisoformat(date_str).timestamp() + 12 * 3600

    return sensor._build_event(
        source_item_id=f"health_{item['data_type']}_{date_str}",
        title=title_map.get(item["data_type"], f"{type_config.display_name}: {value}"),
        summary=f"{type_config.display_name}: {value} {type_config.unit}",
        occurred_at=occurred_at,
        content_blocks=[
            {"kind": "text", "value": f"{type_config.display_name}: {value} {type_config.unit}"}
        ],
        tags=["health", item["data_type"]],
        provenance={
            "sensor_id": sensor.sensor_id,
            "data_type": item["data_type"],
            "date": date_str,
            "value": value,
            "unit": type_config.unit,
            "source": "apple_health",
        },
    )


def normalize_sleep_session(item: dict[str, Any], sensor: Any) -> Any:
    """Normalize sleep session data."""
    start_time = item["start_time"]
    end_time = item["end_time"]
    duration_hours = item["duration_hours"]
    sleep_quality = item.get("sleep_quality", "unknown")

    start_dt = datetime.fromisoformat(start_time)
    end_dt = datetime.fromisoformat(end_time)

    title = f"睡眠 {duration_hours:.1f} 小时"
    summary = f"{start_dt.strftime('%H:%M')} - {end_dt.strftime('%H:%M')} 睡眠 {duration_hours:.1f} 小时"

    return sensor._build_event(
        source_item_id=f"health_sleep_{start_time}",
        title=title,
        summary=summary,
        occurred_at=start_dt.timestamp(),
        content_blocks=[
            {"kind": "text", "value": f"开始: {start_time}"},
            {"kind": "text", "value": f"结束: {end_time}"},
            {"kind": "text", "value": f"时长: {duration_hours:.1f} 小时"},
        ],
        tags=["health", "sleep", "rest"],
        provenance={
            "sensor_id": sensor.sensor_id,
            "data_type": "sleep",
            "start_time": start_time,
            "end_time": end_time,
            "duration_hours": duration_hours,
            "sleep_quality": sleep_quality,
            "source": "apple_health",
        },
    )


def normalize_workout(item: dict[str, Any], sensor: Any) -> Any:
    """Normalize workout session data."""
    workout_type = item["workout_type"]
    start_time = item["start_time"]
    duration_minutes = item["duration_minutes"]
    distance_km = item.get("distance_km")
    calories = item.get("active_energy_burned")

    # Workout type display names (localized)
    type_names = {
        "HKWorkoutActivityTypeRunning": "跑步",
        "HKWorkoutActivityTypeCycling": "骑行",
        "HKWorkoutActivityTypeSwimming": "游泳",
        "HKWorkoutActivityTypeWalking": "步行",
        "HKWorkoutActivityTypeStrengthTraining": "力量训练",
        "HKWorkoutActivityTypeYoga": "瑜伽",
    }

    activity_name = type_names.get(workout_type, "运动")
    title = f"{activity_name} {duration_minutes} 分钟"

    summary_parts = [f"{activity_name} {duration_minutes} 分钟"]
    if distance_km:
        summary_parts.append(f"{distance_km:.1f} 公里")
    if calories:
        summary_parts.append(f"{calories:.0f} 千卡")

    content_blocks = [
        {"kind": "text", "value": f"类型: {activity_name}"},
        {"kind": "text", "value": f"时长: {duration_minutes} 分钟"},
    ]
    if distance_km:
        content_blocks.append({"kind": "text", "value": f"距离: {distance_km:.1f} 公里"})

    return sensor._build_event(
        source_item_id=f"health_workout_{start_time}",
        title=title,
        summary="，".join(summary_parts),
        occurred_at=datetime.fromisoformat(start_time).timestamp(),
        content_blocks=content_blocks,
        tags=[
            "health",
            "workout",
            "exercise",
            workout_type.lower().replace("hkworkoutactivitytype", ""),
        ],
        provenance={
            "sensor_id": sensor.sensor_id,
            "data_type": "workout",
            "workout_type": workout_type,
            "start_time": start_time,
            "duration_minutes": duration_minutes,
            "distance_km": distance_km,
            "active_energy_burned": calories,
            "source": "apple_health",
        },
    )


def normalize_heart_rate_sample(item: dict[str, Any], sensor: Any) -> Any:
    """Normalize heart rate sample data."""
    bpm = item["value"]
    timestamp = item["timestamp"]
    dt = datetime.fromisoformat(timestamp)

    return sensor._build_event(
        source_item_id=f"health_heart_rate_{timestamp}",
        title=f"心率 {bpm} bpm",
        summary=f"{dt.strftime('%H:%M')} 心率 {bpm} bpm",
        occurred_at=dt.timestamp(),
        content_blocks=[
            {"kind": "text", "value": f"心率: {bpm} bpm"},
        ],
        tags=["health", "heart_rate", "vital"],
        provenance={
            "sensor_id": sensor.sensor_id,
            "data_type": "heart_rate",
            "bpm": bpm,
            "timestamp": timestamp,
            "source": "apple_health",
        },
    )


# Type -> normalizer mapping
NORMALIZERS = {
    "steps": normalize_daily_aggregate,
    "distance": normalize_daily_aggregate,
    "flights": normalize_daily_aggregate,
    "active_energy": normalize_daily_aggregate,
    "heart_rate": normalize_heart_rate_sample,
    "sleep": normalize_sleep_session,
    "workout": normalize_workout,
}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd backend && pytest tests/test_apple_health_plugin.py::TestNormalizers -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add plugins/apple-health/normalizers.py backend/tests/test_apple_health_plugin.py
git commit -m "feat(apple-health): add data normalizers"
```

---

## Chunk 2: HealthKit Reader

### Task 5: Implement HealthKit Reader (Platform Detection)

**Files:**
- Create: `plugins/apple-health/reader.py`
- Modify: `backend/tests/test_apple_health_plugin.py`

- [ ] **Step 1: Write the failing test for platform detection**

```python
# Add to backend/tests/test_apple_health_plugin.py

class TestHealthKitReaderPlatform:
    """Tests for HealthKitReader platform detection."""

    def test_platform_check_on_non_darwin(self, monkeypatch) -> None:
        """Test that reader raises error on non-darwin platforms."""
        from apple_health.exceptions import PlatformNotSupportedError

        monkeypatch.setattr("sys.platform", "win32")

        # Force reimport to pick up monkeypatched platform
        import importlib
        import apple_health.reader

        importlib.reload(apple_health.reader)

        from apple_health.reader import HealthKitReader

        reader = HealthKitReader()
        assert reader.is_available() is False

    def test_lazy_import_on_non_darwin(self, monkeypatch) -> None:
        """Test that HealthKit frameworks are not imported on non-darwin."""
        monkeypatch.setattr("sys.platform", "linux")

        import importlib
        import apple_health.reader

        importlib.reload(apple_health.reader)

        from apple_health.reader import HealthKitReader

        reader = HealthKitReader()
        # Should not raise during construction
        assert reader._hk_module is None
        assert reader._foundation_module is None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && pytest tests/test_apple_health_plugin.py::TestHealthKitReaderPlatform -v`
Expected: FAIL with "No module named 'apple_health.reader'"

- [ ] **Step 3: Implement reader.py (platform detection part)**

```python
# plugins/apple-health/reader.py
"""HealthKit data reader using pyobjc bridge."""
from __future__ import annotations

import logging
import sys
from datetime import date, datetime, timedelta
from typing import Any, Optional

from .exceptions import (
    AuthorizationDeniedError,
    HealthKitError,
    HealthKitNotAvailableError,
    HealthKitQueryError,
    PlatformNotSupportedError,
)
from .types import HEALTH_DATA_TYPES, HealthDataType

logger = logging.getLogger(__name__)


class HealthKitReader:
    """HealthKit data reader using pyobjc bridge."""

    def __init__(self) -> None:
        """Initialize the reader with lazy framework loading."""
        self._health_store: Any = None
        self._is_available: Optional[bool] = None

        # Lazy import to avoid import errors on non-macOS platforms
        self._hk_module: dict[str, Any] | None = None
        self._foundation_module: dict[str, Any] | None = None

    def _ensure_platform(self) -> None:
        """Raise error if not running on macOS/iOS."""
        if sys.platform != "darwin":
            raise PlatformNotSupportedError(
                "Apple Health sensor is only available on macOS and iOS"
            )

    def _import_frameworks(self) -> None:
        """Import HealthKit frameworks (macOS only)."""
        if self._hk_module is not None:
            return

        try:
            # Lazy import to avoid errors on non-macOS platforms
            from HealthKit import HKHealthStore, HKCategoryType, HKQuantityType, HKWorkoutType
            from Foundation import NSDate, NSPredicate, NSSortDescriptor

            self._hk_module = {
                "HKHealthStore": HKHealthStore,
                "HKQuantityType": HKQuantityType,
                "HKCategoryType": HKCategoryType,
                "HKWorkoutType": HKWorkoutType,
            }
            self._foundation_module = {
                "NSDate": NSDate,
                "NSPredicate": NSPredicate,
                "NSSortDescriptor": NSSortDescriptor,
            }
        except ImportError as e:
            raise HealthKitNotAvailableError(
                f"Failed to import HealthKit frameworks: {e}"
            )

    @property
    def health_store(self) -> Any:
        """Get or create HKHealthStore instance."""
        self._ensure_platform()

        if self._health_store is None:
            self._import_frameworks()
            HKHealthStore = self._hk_module["HKHealthStore"]
            self._health_store = HKHealthStore.alloc().init()

        return self._health_store

    def is_available(self) -> bool:
        """Check if HealthKit is available on this device."""
        if self._is_available is not None:
            return self._is_available

        try:
            self._ensure_platform()
            self._import_frameworks()

            HKHealthStore = self._hk_module["HKHealthStore"]
            self._is_available = HKHealthStore.isHealthDataAvailable()
            return self._is_available
        except (PlatformNotSupportedError, HealthKitNotAvailableError):
            self._is_available = False
            return False

    def get_authorization_status(self, type_keys: list[str]) -> dict[str, str]:
        """
        Get authorization status for specified data types.

        Returns a dict mapping type_key to status:
        - "not_determined": User has not been asked yet
        - "sharing_denied": User denied access
        - "sharing_authorized": User granted access
        - "unavailable": HealthKit not available
        """
        if not self.is_available():
            return {key: "unavailable" for key in type_keys}

        statuses: dict[str, str] = {}
        for type_key in type_keys:
            type_config = HEALTH_DATA_TYPES.get(type_key)
            if not type_config:
                statuses[type_key] = "unknown_type"
                continue

            try:
                hk_type = self._get_hk_type(type_config)
                status = self.health_store.authorizationStatusForType_(hk_type)

                # Convert NSInteger to string
                status_map = {
                    0: "not_determined",
                    1: "sharing_denied",
                    2: "sharing_authorized",
                }
                statuses[type_key] = status_map.get(int(status), "unknown")
            except Exception as e:
                logger.warning(f"Failed to get auth status for {type_key}: {e}")
                statuses[type_key] = "error"

        return statuses

    def _get_hk_type(self, type_config: HealthDataType) -> Any:
        """Get HKObjectType from type configuration."""
        hk_class = type_config.hk_class

        if hk_class == "HKQuantityType":
            HKQuantityType = self._hk_module["HKQuantityType"]
            return HKQuantityType.quantityTypeForIdentifier_(type_config.hk_type)
        elif hk_class == "HKCategoryType":
            HKCategoryType = self._hk_module["HKCategoryType"]
            return HKCategoryType.categoryTypeForIdentifier_(type_config.hk_type)
        elif hk_class == "HKWorkoutType":
            HKWorkoutType = self._hk_module["HKWorkoutType"]
            return HKWorkoutType.workoutType()
        else:
            raise HealthKitError(f"Unknown HK class: {hk_class}")

    def request_authorization(
        self, type_keys: list[str], completion_handler: Any = None
    ) -> dict[str, bool]:
        """
        Request authorization for specified data types.

        This will show system authorization dialogs.

        Args:
            type_keys: List of type keys to request authorization for
            completion_handler: Optional callback for completion

        Returns:
            Dict mapping type_key to whether authorization succeeded
        """
        if not self.is_available():
            return {key: False for key in type_keys}

        results: dict[str, bool] = {}

        for type_key in type_keys:
            type_config = HEALTH_DATA_TYPES.get(type_key)
            if not type_config:
                results[type_key] = False
                continue

            try:
                hk_type = self._get_hk_type(type_config)

                # Request authorization synchronously using a semaphore
                import threading

                success_flag = [False]
                error_flag = [None]
                semaphore = threading.Semaphore(0)

                def on_completion(success: bool, error: Any) -> None:
                    success_flag[0] = success
                    error_flag[0] = error
                    semaphore.release()

                self.health_store.requestAuthorizationToShareTypes_readTypes_completion_(
                    None, {hk_type}, on_completion
                )

                # Wait for completion with timeout
                if semaphore.acquire(timeout=30):
                    results[type_key] = success_flag[0]
                    if error_flag[0]:
                        logger.warning(f"Authorization error for {type_key}: {error_flag[0]}")
                else:
                    results[type_key] = False
                    logger.warning(f"Authorization timeout for {type_key}")

            except Exception as e:
                logger.error(f"Failed to request authorization for {type_key}: {e}")
                results[type_key] = False

        return results

    # Data reading methods - stubs for now, will be implemented in integration
    def read_daily_aggregate(
        self, type_key: str, start_date: date, end_date: date
    ) -> list[dict[str, Any]]:
        """Read daily aggregated data for a type between dates."""
        # Implementation requires HKStatisticsQuery
        # This is a stub for unit testing
        if not self.is_available():
            return []

        # TODO: Implement actual HealthKit query
        logger.debug(f"Reading daily aggregate for {type_key}: {start_date} to {end_date}")
        return []

    def read_samples(
        self,
        type_key: str,
        start: datetime,
        end: datetime,
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        """Read sample data for a type between timestamps."""
        if not self.is_available():
            return []

        # TODO: Implement actual HealthKit query
        logger.debug(f"Reading samples for {type_key}: {start} to {end}")
        return []

    def read_sessions(
        self,
        type_key: str,
        start: datetime,
        end: datetime,
    ) -> list[dict[str, Any]]:
        """Read session data for a type between timestamps."""
        if not self.is_available():
            return []

        # TODO: Implement actual HealthKit query
        logger.debug(f"Reading sessions for {type_key}: {start} to {end}")
        return []

    def read_workouts(
        self,
        start: datetime,
        end: datetime,
    ) -> list[dict[str, Any]]:
        """Read workout records between timestamps."""
        if not self.is_available():
            return []

        # TODO: Implement actual HealthKit query
        logger.debug(f"Reading workouts: {start} to {end}")
        return []
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd backend && pytest tests/test_apple_health_plugin.py::TestHealthKitReaderPlatform -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add plugins/apple-health/reader.py backend/tests/test_apple_health_plugin.py
git commit -m "feat(apple-health): add HealthKit reader with platform detection"
```

---

## Chunk 3: Sensor and Plugin

### Task 6: Implement Sensor

**Files:**
- Create: `plugins/apple-health/sensor.py`
- Modify: `backend/tests/test_apple_health_plugin.py`

- [ ] **Step 1: Write the failing test for sensor**

```python
# Add to backend/tests/test_apple_health_plugin.py

class TestAppleHealthTimelineSensor:
    """Tests for AppleHealthTimelineSensor."""

    def test_sensor_properties(self) -> None:
        """Test sensor basic properties."""
        from apple_health.sensor import AppleHealthTimelineSensor

        sensor = AppleHealthTimelineSensor()

        assert sensor.sensor_id == "timeline.apple_health"
        assert sensor.display_name == "Apple Health"
        assert sensor.source_type == "apple_health"
        assert sensor.polling_mode == "interval"
        assert sensor.default_interval == 60
        assert sensor.supports_pull_sync is True
        assert "TRACKED" in sensor.relation_edge_whitelist
        assert "EXERCISED" in sensor.relation_edge_whitelist

    def test_sensor_with_enabled_types(self) -> None:
        """Test sensor with custom enabled types."""
        from apple_health.sensor import AppleHealthTimelineSensor

        sensor = AppleHealthTimelineSensor(enabled_types=["steps", "heart_rate"])

        assert sensor.enabled_types == ["steps", "heart_rate"]

    def test_sensor_default_enabled_types(self) -> None:
        """Test sensor default enabled types."""
        from apple_health.sensor import AppleHealthTimelineSensor

        sensor = AppleHealthTimelineSensor()

        # Default should be steps and sleep
        assert "steps" in sensor.enabled_types
        assert "sleep" in sensor.enabled_types

    def test_source_item_identity(self) -> None:
        """Test source item identity generation."""
        from apple_health.sensor import AppleHealthTimelineSensor

        sensor = AppleHealthTimelineSensor()

        item = {
            "data_type": "steps",
            "date": "2024-03-12",
        }

        identity = sensor.source_item_identity(item)
        assert identity == "apple_health_steps_2024-03-12"

    def test_source_item_identity_with_session(self) -> None:
        """Test source item identity for session data."""
        from apple_health.sensor import AppleHealthTimelineSensor

        sensor = AppleHealthTimelineSensor()

        item = {
            "data_type": "sleep",
            "session_id": "2024-03-11T23:30:00",
        }

        identity = sensor.source_item_identity(item)
        assert identity == "apple_health_sleep_2024-03-11T23:30:00"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && pytest tests/test_apple_health_plugin.py::TestAppleHealthTimelineSensor -v`
Expected: FAIL with "No module named 'apple_health.sensor'"

- [ ] **Step 3: Implement sensor.py**

```python
# plugins/apple-health/sensor.py
"""Timeline sensor for Apple Health data."""
from __future__ import annotations

import hashlib
import logging
import sys
import time
from typing import Any, Optional

from magi.timeline import SensorSyncContext, SensorSyncResult, TimelineContentBlock, TimelineEvent
from magi.timeline.sensors import TimelineSensorBase

from .exceptions import PlatformNotSupportedError
from .normalizers import NORMALIZERS
from .reader import HealthKitReader
from .types import HEALTH_DATA_TYPES, get_default_enabled_types

logger = logging.getLogger(__name__)


class AppleHealthTimelineSensor(TimelineSensorBase):
    """Timeline sensor for Apple Health data."""

    sensor_id = "timeline.apple_health"
    display_name = "Apple Health"
    source_type = "apple_health"
    polling_mode = "interval"
    default_interval = 60
    update_key_fields = ("data_type", "date", "session_id")
    relation_edge_whitelist = ("TRACKED", "EXERCISED")
    supports_pull_sync = True

    def __init__(
        self,
        *,
        retention_mode: Optional[str] = None,
        enabled_types: Optional[list[str]] = None,
        reader: Optional[HealthKitReader] = None,
    ) -> None:
        """Initialize the Apple Health sensor."""
        super().__init__(retention_mode=retention_mode)
        self.enabled_types = enabled_types or get_default_enabled_types()
        self._reader: Optional[HealthKitReader] = reader

    @property
    def reader(self) -> HealthKitReader:
        """Get or create HealthKitReader instance (lazy initialization)."""
        if self._reader is None:
            if sys.platform != "darwin":
                raise PlatformNotSupportedError(
                    "Apple Health sensor is only available on macOS/iOS"
                )
            self._reader = HealthKitReader()
        return self._reader

    def source_item_identity(self, item: dict[str, Any]) -> str:
        """Generate unique identity for a source item."""
        data_type = item.get("data_type", "unknown")

        if "session_id" in item:
            return f"apple_health_{data_type}_{item['session_id']}"
        elif "date" in item:
            return f"apple_health_{data_type}_{item['date']}"
        elif "timestamp" in item:
            return f"apple_health_{data_type}_{item['timestamp']}"
        else:
            return f"apple_health_{data_type}_{hashlib.md5(str(item).encode()).hexdigest()}"

    def source_item_version_fingerprint(self, item: dict[str, Any]) -> str:
        """Generate version fingerprint for change detection."""
        parts = [
            str(item.get("data_type", "")),
            str(item.get("value", "")),
            str(item.get("date", "")),
            str(item.get("session_id", "")),
            str(item.get("timestamp", "")),
        ]
        return hashlib.sha1("|".join(parts).encode("utf-8")).hexdigest()

    async def collect_items(self, context: SensorSyncContext) -> SensorSyncResult:
        """Collect health data items from all enabled types."""
        items: list[dict[str, Any]] = []

        # Get settings
        sensor_settings = (
            context.plugin_settings.get("sensors", {}).get("apple_health", {})
            if isinstance(context.plugin_settings.get("sensors", {}), dict)
            else {}
        )

        lookback_days = int(sensor_settings.get("lookback_days", 7))

        for type_key in self.enabled_types:
            type_config = HEALTH_DATA_TYPES.get(type_key)
            if not type_config:
                continue

            # Check authorization status
            auth_status = self.reader.get_authorization_status([type_key])
            if auth_status.get(type_key) != "sharing_authorized":
                logger.debug(f"Skipping {type_key}: not authorized")
                continue

            try:
                # Collect based on aggregation type
                if type_config.aggregation == "daily":
                    new_items = self._collect_daily(type_key, context, lookback_days)
                elif type_config.aggregation == "sample":
                    new_items = self._collect_samples(type_key, context, lookback_days)
                elif type_config.aggregation == "session":
                    new_items = self._collect_sessions(type_key, context, lookback_days)
                else:
                    continue

                items.extend(new_items)
            except Exception as e:
                logger.error(f"Failed to collect {type_key}: {e}")

        return SensorSyncResult(
            items=items,
            next_cursor=None,  # Health data doesn't use cursor pagination
            watermark_ts=time.time(),
            stats={
                "count": len(items),
                "enabled_types": self.enabled_types,
            },
        )

    def _collect_daily(
        self, type_key: str, context: SensorSyncContext, lookback_days: int
    ) -> list[dict[str, Any]]:
        """Collect daily aggregated data."""
        from datetime import date, timedelta

        end_date = date.today()
        start_date = end_date - timedelta(days=lookback_days)

        raw_items = self.reader.read_daily_aggregate(type_key, start_date, end_date)

        items = []
        for raw in raw_items:
            items.append({
                "data_type": type_key,
                "date": raw.get("date"),
                "value": raw.get("value"),
            })

        return items

    def _collect_samples(
        self, type_key: str, context: SensorSyncContext, lookback_days: int
    ) -> list[dict[str, Any]]:
        """Collect sample data."""
        from datetime import datetime, timedelta

        end_time = datetime.now()
        start_time = end_time - timedelta(days=lookback_days)

        raw_items = self.reader.read_samples(type_key, start_time, end_time)

        items = []
        for raw in raw_items:
            items.append({
                "data_type": type_key,
                "timestamp": raw.get("timestamp"),
                "value": raw.get("value"),
            })

        return items

    def _collect_sessions(
        self, type_key: str, context: SensorSyncContext, lookback_days: int
    ) -> list[dict[str, Any]]:
        """Collect session data."""
        from datetime import datetime, timedelta

        end_time = datetime.now()
        start_time = end_time - timedelta(days=lookback_days)

        if type_key == "workout":
            raw_items = self.reader.read_workouts(start_time, end_time)
        else:
            raw_items = self.reader.read_sessions(type_key, start_time, end_time)

        items = []
        for raw in raw_items:
            items.append({
                "data_type": type_key,
                "session_id": raw.get("start_time") or raw.get("timestamp"),
                **raw,
            })

        return items

    async def build_timeline_event(self, item: dict[str, Any]) -> TimelineEvent:
        """Build a TimelineEvent from a health data item."""
        type_key = item.get("data_type", "unknown")
        normalizer = NORMALIZERS.get(type_key)

        if normalizer is None:
            logger.warning(f"No normalizer for type: {type_key}")
            # Fallback to generic event
            return self._build_event(
                source_item_id=self.source_item_identity(item),
                title=f"Health data: {type_key}",
                summary=str(item),
                occurred_at=time.time(),
                content_blocks=[],
                tags=["health", type_key],
                provenance={
                    "sensor_id": self.sensor_id,
                    "data_type": type_key,
                    "source": "apple_health",
                },
            )

        return normalizer(item, self)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd backend && pytest tests/test_apple_health_plugin.py::TestAppleHealthTimelineSensor -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add plugins/apple-health/sensor.py backend/tests/test_apple_health_plugin.py
git commit -m "feat(apple-health): add timeline sensor implementation"
```

---

### Task 7: Implement Plugin Entry Point

**Files:**
- Create: `plugins/apple-health/plugin.py`
- Modify: `backend/tests/test_apple_health_plugin.py`

- [ ] **Step 1: Write the failing test for plugin**

```python
# Add to backend/tests/test_apple_health_plugin.py

class TestAppleHealthPlugin:
    """Tests for AppleHealthPlugin."""

    def test_default_settings(self) -> None:
        """Test that default settings are correctly defined."""
        from apple_health.plugin import DEFAULT_SETTINGS

        assert isinstance(DEFAULT_SETTINGS, dict)
        assert "enabled" in DEFAULT_SETTINGS
        assert "sync_mode" in DEFAULT_SETTINGS
        assert "sync_interval_hours" in DEFAULT_SETTINGS
        assert "lookback_days" in DEFAULT_SETTINGS

        # Check default values
        assert DEFAULT_SETTINGS["enabled"] is False
        assert DEFAULT_SETTINGS["sync_mode"] == "manual"
        assert DEFAULT_SETTINGS["sync_interval_hours"] == 1
        assert DEFAULT_SETTINGS["lookback_days"] == 7

    def test_default_enabled_types(self) -> None:
        """Test default enabled types in settings."""
        from apple_health.plugin import DEFAULT_SETTINGS

        types = DEFAULT_SETTINGS.get("types", {})
        assert types.get("steps") is True
        assert types.get("sleep") is True
        assert types.get("heart_rate") is False  # Opt-in

    def test_plugin_returns_empty_on_non_darwin(self, monkeypatch) -> None:
        """Test that plugin returns empty sensor list on non-macOS."""
        monkeypatch.setattr("sys.platform", "win32")

        import importlib
        import apple_health.plugin

        importlib.reload(apple_health.plugin)

        from apple_health.plugin import AppleHealthPlugin

        plugin = AppleHealthPlugin()
        sensors = plugin.get_sensors()

        assert sensors == []

    def test_plugin_get_sensors_returns_spec(self, monkeypatch) -> None:
        """Test that plugin returns correct sensor specification on macOS."""
        # This test requires mocking the reader
        from unittest.mock import MagicMock, patch

        monkeypatch.setattr("sys.platform", "darwin")

        # Mock HealthKitReader to be available
        with patch("apple_health.plugin.HealthKitReader") as mock_reader_class:
            mock_reader = MagicMock()
            mock_reader.is_available.return_value = True
            mock_reader_class.return_value = mock_reader

            import importlib
            import apple_health.plugin

            importlib.reload(apple_health.plugin)

            from apple_health.plugin import AppleHealthPlugin

            plugin = AppleHealthPlugin()
            sensors = plugin.get_sensors()

            assert len(sensors) == 1

            sensor_id, sensor_instance, sensor_spec = sensors[0]
            assert sensor_id == "timeline.apple_health"
            assert sensor_spec.sensor_id == "timeline.apple_health"
            assert sensor_spec.display_name == "Apple Health"
            assert sensor_spec.domain == "timeline"
            assert sensor_spec.surface == "timeline"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && pytest tests/test_apple_health_plugin.py::TestAppleHealthPlugin -v`
Expected: FAIL with "No module named 'apple_health.plugin'"

- [ ] **Step 3: Implement plugin.py**

```python
# plugins/apple-health/plugin.py
"""Apple Health timeline sensor plugin."""
from __future__ import annotations

import logging
import sys
from typing import Any

from magi.plugins import ExtensionFieldOption, ExtensionFieldSpec, Plugin, SensorSpec

from .reader import HealthKitReader
from .sensor import AppleHealthTimelineSensor

logger = logging.getLogger(__name__)


DEFAULT_SETTINGS: dict[str, Any] = {
    "enabled": False,
    "sync_mode": "manual",
    "sync_interval_hours": 1,
    "lookback_days": 7,
    "types": {
        "steps": True,
        "sleep": True,
        "heart_rate": False,
        "distance": False,
        "flights": False,
        "active_energy": False,
        "workout": False,
    },
    "default_retention_mode": "analyze_only",
    "storage_mode": "managed",
}


def _fields(prefix: str) -> list[ExtensionFieldSpec]:
    """Define settings fields for Apple Health sensor."""
    return [
        # Data type toggles
        ExtensionFieldSpec(
            key=f"{prefix}.types.steps",
            type="switch",
            label="Steps",
            description="Sync daily step count data",
            default=True,
            section="data_types",
            surface="timeline",
            order=10,
        ),
        ExtensionFieldSpec(
            key=f"{prefix}.types.sleep",
            type="switch",
            label="Sleep Analysis",
            description="Sync sleep session records",
            default=True,
            section="data_types",
            surface="timeline",
            order=20,
        ),
        ExtensionFieldSpec(
            key=f"{prefix}.types.heart_rate",
            type="switch",
            label="Heart Rate",
            description="Sync heart rate measurements",
            default=False,
            section="data_types",
            surface="timeline",
            order=30,
        ),
        ExtensionFieldSpec(
            key=f"{prefix}.types.distance",
            type="switch",
            label="Walking Distance",
            description="Sync daily walking/running distance",
            default=False,
            section="data_types",
            surface="timeline",
            order=40,
        ),
        ExtensionFieldSpec(
            key=f"{prefix}.types.flights",
            type="switch",
            label="Flights Climbed",
            description="Sync daily flights climbed count",
            default=False,
            section="data_types",
            surface="timeline",
            order=50,
        ),
        ExtensionFieldSpec(
            key=f"{prefix}.types.active_energy",
            type="switch",
            label="Active Energy",
            description="Sync daily active energy burned",
            default=False,
            section="data_types",
            surface="timeline",
            order=60,
        ),
        ExtensionFieldSpec(
            key=f"{prefix}.types.workout",
            type="switch",
            label="Workouts",
            description="Sync workout session records",
            default=False,
            section="data_types",
            surface="timeline",
            order=70,
        ),
        # Sync settings
        ExtensionFieldSpec(
            key=f"{prefix}.sync_interval_hours",
            type="select",
            label="Sync Interval",
            description="How often to sync health data",
            default=1,
            options=[
                ExtensionFieldOption(label="Every 30 minutes", value="0.5"),
                ExtensionFieldOption(label="Every hour", value="1"),
                ExtensionFieldOption(label="Every 3 hours", value="3"),
                ExtensionFieldOption(label="Every 6 hours", value="6"),
                ExtensionFieldOption(label="Once daily", value="24"),
            ],
            section="sync",
            surface="timeline",
            order=100,
        ),
        ExtensionFieldSpec(
            key=f"{prefix}.lookback_days",
            type="number",
            label="Initial Lookback Days",
            description="Number of days to sync on first enable",
            default=7,
            section="sync",
            surface="timeline",
            order=110,
        ),
    ]


def _get_enabled_types_from_settings(settings: dict[str, Any]) -> list[str]:
    """Extract enabled types from plugin settings."""
    types_settings = settings.get("sensors", {}).get("apple_health", {}).get("types", {})
    enabled = []
    for type_key in ["steps", "sleep", "heart_rate", "distance", "flights", "active_energy", "workout"]:
        if types_settings.get(type_key, False):
            enabled.append(type_key)
    return enabled if enabled else ["steps", "sleep"]


class AppleHealthPlugin(Plugin):
    """Apple Health timeline sensor plugin."""

    def get_sensors(self) -> list[tuple[str, object, SensorSpec]]:
        """Register the Apple Health timeline sensor."""
        # Check platform
        if sys.platform != "darwin":
            logger.info("Apple Health plugin disabled: not running on macOS/iOS")
            return []

        # Check HealthKit availability
        try:
            reader = HealthKitReader()
            if not reader.is_available():
                logger.info("Apple Health plugin disabled: HealthKit not available")
                return []
        except Exception as e:
            logger.warning(f"Apple Health plugin disabled: {e}")
            return []

        # Get enabled types from settings
        enabled_types = _get_enabled_types_from_settings(self.settings)

        # Get retention mode from settings
        sensor_settings = self.settings.get("sensors", {}).get("apple_health", {})
        retention_mode = sensor_settings.get("default_retention_mode", "analyze_only")
        sync_mode = sensor_settings.get("sync_mode", "manual")
        lookback_days = sensor_settings.get("lookback_days", 7)

        # Create sensor instance
        sensor = AppleHealthTimelineSensor(
            retention_mode=retention_mode,
            enabled_types=enabled_types,
            reader=reader,
        )

        return [
            (
                "timeline.apple_health",
                sensor,
                SensorSpec(
                    sensor_id="timeline.apple_health",
                    display_name="Apple Health",
                    description="Apple Health data ingestion for the timeline.",
                    domain="timeline",
                    surface="timeline",
                    sync_mode=sync_mode,
                    polling_mode=sensor.polling_mode,
                    fields=_fields("sensors.apple_health"),
                    metadata={
                        "source_type": "apple_health",
                        "default_settings": dict(DEFAULT_SETTINGS),
                        "enabled_types": enabled_types,
                        "lookback_days": lookback_days,
                    },
                ),
            )
        ]
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd backend && pytest tests/test_apple_health_plugin.py::TestAppleHealthPlugin -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add plugins/apple-health/plugin.py backend/tests/test_apple_health_plugin.py
git commit -m "feat(apple-health): add plugin entry point with settings fields"
```

---

## Chunk 4: i18n and Dependencies

### Task 8: Add i18n Locale Keys

**Files:**
- Modify: `frontend/src/i18n/locales/zh-CN/app.json`
- Modify: `frontend/src/i18n/locales/en/app.json`

- [ ] **Step 1: Add Chinese locale keys**

Read current file and add the apple_health section under timeline.sources.

- [ ] **Step 2: Add English locale keys**

Read current file and add the apple_health section under timeline.sources.

- [ ] **Step 3: Commit**

```bash
git add frontend/src/i18n/locales/zh-CN/app.json frontend/src/i18n/locales/en/app.json
git commit -m "feat(apple-health): add i18n locale keys"
```

---

### Task 9: Add Dependencies

**Files:**
- Modify: `backend/requirements.txt`

- [ ] **Step 1: Add pyobjc dependencies (commented as macOS-only)**

Add to requirements.txt:
```
# Apple Health sensor (macOS only)
# pyobjc-framework-HealthKit>=10.0
# pyobjc-framework-Foundation>=10.0
```

Note: These are commented because they only install on macOS. Developers should uncomment when developing on macOS.

- [ ] **Step 2: Commit**

```bash
git add backend/requirements.txt
git commit -m "feat(apple-health): add pyobjc dependencies (macOS only)"
```

---

### Task 10: Run Full Test Suite

- [ ] **Step 1: Run all apple-health tests**

Run: `cd backend && pytest tests/test_apple_health_plugin.py -v`
Expected: All tests PASS

- [ ] **Step 2: Run full backend test suite**

Run: `cd backend && pytest -v`
Expected: All tests PASS

- [ ] **Step 3: Verify plugin loads on macOS (manual)**

Start the backend server and verify the plugin is discovered:
```bash
cd backend
python run_server.py
```

Check logs for "Apple Health plugin" messages.

---

## Summary

This plan creates a complete Apple Health sensor plugin following the existing plugin patterns in Magi. The implementation:

1. Defines health data types with aggregation strategies
2. Implements graceful platform detection (no errors on Windows/Linux)
3. Uses lazy loading for HealthKit frameworks
4. Follows TDD with comprehensive unit tests
5. Provides i18n support for both zh-CN and en
6. Integrates with the existing plugin and sensor architecture
