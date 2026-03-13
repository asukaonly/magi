from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, List


@dataclass
class HealthDataType:
    """Health data type configuration."""

    key: str
    hk_type: str
    display_name: str
    description: str
    unit: str | None
    aggregation: str
    hk_class: str
    edge_types: List[str]


HEALTH_DATA_TYPES: Dict[str, HealthDataType] = {
    "steps": HealthDataType(
        key="steps",
        hk_type="QuantityType",
        display_name="Steps",
        description="Daily step count",
        unit="count",
        aggregation="daily",
        hk_class="HKQuantityTypeIdentifierStepCount",
        edge_types=["steps"]
    ),
    "distance": HealthDataType(
        key="distance",
        hk_type="QuantityType",
        display_name="Distance",
        description="Distance traveled",
        unit="km",
        aggregation="daily",
        hk_class="HKQuantityTypeIdentifierDistanceWalkingRunning",
        edge_types=["distance"]
    ),
    "flights": HealthDataType(
        key="flights",
        hk_type="QuantityType",
        display_name="Flights Climbed",
        description="Number of flights of stairs climbed",
        unit="count",
        aggregation="daily",
        hk_class="HKQuantityTypeIdentifierFlightsClimbed",
        edge_types=["flights"]
    ),
    "heart_rate": HealthDataType(
        key="heart_rate",
        hk_type="QuantityType",
        display_name="Heart Rate",
        description="Heart rate measurements",
        unit="bpm",
        aggregation="sample",
        hk_class="HKQuantityTypeIdentifierHeartRate",
        edge_types=["heart_rate"]
    ),
    "sleep": HealthDataType(
        key="sleep",
        hk_type="CategoryType",
        display_name="Sleep",
        description="Sleep analysis data",
        unit=None,
        aggregation="session",
        hk_class="HKCategoryTypeIdentifierSleepAnalysis",
        edge_types=["sleep"]
    ),
    "active_energy": HealthDataType(
        key="active_energy",
        hk_type="QuantityType",
        display_name="Active Energy",
        description="Active energy burned",
        unit="kcal",
        aggregation="daily",
        hk_class="HKQuantityTypeIdentifierActiveEnergyBurned",
        edge_types=["active_energy"]
    ),
    "workout": HealthDataType(
        key="workout",
        hk_type="WorkoutType",
        display_name="Workout",
        description="Workout session data",
        unit=None,
        aggregation="session",
        hk_class="HKWorkoutTypeIdentifier",
        edge_types=["workout"]
    )
}


def get_enabled_types(settings: Dict[str, Any]) -> List[HealthDataType]:
    """Get enabled health data types from settings.

    Args:
        settings: Plugin settings dictionary

    Returns:
        List of enabled health data types
    """
    if not settings:
        return get_default_enabled_types()

    enabled_keys = settings.get("enabled_types", [])
    return [data_type for data_type in HEALTH_DATA_TYPES.values()
            if data_type.key in enabled_keys]


def get_default_enabled_types() -> List[HealthDataType]:
    """Get default enabled health data types.

    Returns:
        List of default enabled health data types
    """
    # By default, enable all types except sleep and workout
    default_enabled = [
        "steps", "distance", "flights", "heart_rate", "active_energy"
    ]
    return [HEALTH_DATA_TYPES[key] for key in default_enabled]