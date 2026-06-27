"""Project sensor domain events into timeline read-model payloads."""
from __future__ import annotations

from typing import Any

from magi.events.domain_payloads import SensorEventEmitted
from magi.events.sensor_activity_snapshot import build_sensor_activity_snapshot


def build_timeline_event_dict(
    payload: SensorEventEmitted,
    *,
    event_id: str,
) -> dict[str, Any]:
    """Build the TimelineEvent dict shape from sensor payload context."""
    return build_sensor_activity_snapshot(payload, event_id=event_id)
