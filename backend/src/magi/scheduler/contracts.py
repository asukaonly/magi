"""Contracts for the unified scheduler runtime."""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import TYPE_CHECKING, Any, Optional, Protocol

if TYPE_CHECKING:
    from .service import SchedulerService


class ScheduledTargetType(str, Enum):
    """Supported scheduler target families."""

    SENSOR_SYNC = "sensor_sync"
    MEMORY_L2_MAINTENANCE = "memory_l2_maintenance"
    MEMORY_L3_SUMMARY = "memory_l3_summary"
    MEMORY_L4_MAINTENANCE = "memory_l4_maintenance"
    USER_AGENT_TASK = "user_agent_task"
    TIMELINE_DIARY_NARRATIVE = "timeline_diary_narrative"
    TIMELINE_STANDOUT_RESCORE = "timeline_standout_rescore"
    TIMELINE_MOOD_AGGREGATE = "timeline_mood_aggregate"
    TIMELINE_REPRESENTATIVE_ASSET = "timeline_representative_asset"
    LOCATION_IPGEO_POLL = "location_ipgeo_poll"
    LOCATION_WIFI_POLL = "location_wifi_poll"
    OUTREACH_OUTBOX_DRAIN = "outreach_outbox_drain"


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
    # Derived display cache only — NOT authoritative. The single source of truth for
    # next_run is the APScheduler jobstore (read via
    # ScheduleRepository.get_schedule_next_run_at -> apscheduler_jobs.next_run_time);
    # this mirror is written from it and used only as a status-display fallback.
    # Do not build firing/decision logic on it. Tracked for removal in #89.
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


class ScheduleContributor(Protocol):
    """Protocol for layers that contribute scheduled tasks to the scheduler.

    Each layer that needs scheduled tasks should implement this protocol
    and register itself with the scheduler during initialization.

    The scheduler orchestrator will call register_schedules() during startup
    and unregister_schedules() during shutdown.
    """

    async def register_schedules(self, scheduler: "SchedulerService") -> None:
        """Register this contributor's scheduled tasks with the scheduler.

        Args:
            scheduler: The scheduler service to register tasks with.
        """
        ...

    async def unregister_schedules(self, scheduler: "SchedulerService") -> None:
        """Unregister this contributor's scheduled tasks from the scheduler.

        Args:
            scheduler: The scheduler service to unregister tasks from.
        """
        ...


# --- Sensor schedule helpers ---

def build_sensor_target_key(plugin_id: str, source_type: str) -> str:
    """Build stable scheduler target key for a sensor source."""
    return f"{plugin_id}:{source_type}"


def build_sensor_schedule_id(plugin_id: str, source_type: str) -> str:
    """Build stable recurring schedule id for a sensor source."""
    return f"sensor-sync:{plugin_id}:{source_type}"
