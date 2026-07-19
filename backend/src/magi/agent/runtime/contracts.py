"""Contracts for agent runtime orchestration."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, Optional
import time


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
    user_message_generation: Optional[int] = None
    delivery_attempt_no: Optional[int] = None
    runtime_command_id: Optional[int] = None
