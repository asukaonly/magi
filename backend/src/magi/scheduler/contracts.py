"""Contracts for the unified scheduler runtime."""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any, Optional


class ScheduledTargetType(str, Enum):
    """Supported scheduler target families."""

    TIMELINE_SENSOR_SYNC = "timeline_sensor_sync"
    AGENT_TASK = "agent_task"
    ACTION_DISPATCH = "action_dispatch"


class TriggerType(str, Enum):
    """Supported trigger types."""

    ONCE = "once"
    INTERVAL = "interval"
    CRON = "cron"


@dataclass(slots=True)
class TriggerDefinition:
    """Trigger definition persisted by the scheduler."""

    trigger_type: TriggerType
    config: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class ScheduleDefinition:
    """Canonical persisted schedule definition."""

    schedule_id: str
    target_type: ScheduledTargetType
    target_key: str
    trigger: TriggerDefinition
    target_payload: dict[str, Any] = field(default_factory=dict)
    enabled: bool = True
    metadata: dict[str, Any] = field(default_factory=dict)
    job_id: Optional[str] = None


@dataclass(slots=True)
class ScheduledTargetState:
    """Runtime status tracked per scheduled target."""

    target_type: ScheduledTargetType
    target_key: str
    running: bool = False
    last_run_at: Optional[float] = None
    last_success_at: Optional[float] = None
    last_error: Optional[str] = None
    last_cursor: Optional[str] = None
    watermark_ts: Optional[float] = None
    next_run_at: Optional[float] = None
    scheduler_job_id: Optional[str] = None
    updated_at: Optional[float] = None
    stats: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class ScheduledExecutionContext:
    """Context passed to registered schedule handlers."""

    schedule: ScheduleDefinition
    target_state: ScheduledTargetState
    runtime_dir: Path
    triggered_at: float
    manual: bool = False


@dataclass(slots=True)
class ScheduledExecutionResult:
    """Result returned by registered schedule handlers."""

    success: bool
    message: str = ""
    next_cursor: Optional[str] = None
    watermark_ts: Optional[float] = None
    stats: dict[str, Any] = field(default_factory=dict)

