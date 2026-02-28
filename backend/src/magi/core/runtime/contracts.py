"""
Contracts for runtime-based agent orchestration.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, Optional
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


@dataclass
class FactRecord:
    """Fact record attached to a target runtime agent."""

    agent_id: str
    event_type: str
    payload: Dict[str, Any]
    agent_type: Optional[str] = None
    agent_instance_id: Optional[str] = None
    timestamp: float = field(default_factory=time.time)
    correlation_id: Optional[str] = None
