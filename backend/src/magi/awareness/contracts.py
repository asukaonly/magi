"""Contracts for awareness-owned sensor and action runtime primitives."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict
import time
import uuid


@dataclass
class SensorEvent:
    """Normalized event emitted by sensor hub."""

    sensor_name: str
    event_type: str
    payload: Dict[str, Any]
    timestamp: float = field(default_factory=time.time)
    correlation_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    user_message_generation: int | None = None
