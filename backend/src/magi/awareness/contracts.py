"""Contracts for awareness-owned source and action runtime primitives."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict
import time
import uuid


@dataclass
class SourceEvent:
    """Normalized event emitted by source hub."""

    source_name: str
    event_type: str
    payload: Dict[str, Any]
    timestamp: float = field(default_factory=time.time)
    correlation_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    user_message_generation: int | None = None
    delivery_attempt_no: int | None = None
    runtime_command_id: int | None = None
