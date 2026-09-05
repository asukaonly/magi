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

    SOURCE_SYNC = "source_sync"
    MEMORY_L1_MAINTENANCE = "memory_l1_maintenance"
    MEMORY_L2_MAINTENANCE = "memory_l2_maintenance"
    MEMORY_L2_CONSOLIDATE = "memory_l2_consolidate"
    MEMORY_L3_SUMMARY = "memory_l3_summary"
    MEMORY_L3_MAINTENANCE = "memory_l3_maintenance"
    MEMORY_L4_MAINTENANCE = "memory_l4_maintenance"
    USER_AGENT_TASK = "user_agent_task"
    TIMELINE_DIARY_NARRATIVE = "timeline_diary_narrative"
    TIMELINE_STANDOUT_RESCORE = "timeline_standout_rescore"
    TIMELINE_MOOD_AGGREGATE = "timeline_mood_aggregate"
    TIMELINE_REPRESENTATIVE_ASSET = "timeline_representative_asset"
    LOCATION_IPGEO_POLL = "location_ipgeo_poll"
    LOCATION_WIFI_POLL = "location_wifi_poll"
    OUTREACH_OUTBOX_DRAIN = "outreach_outbox_drain"
    MEMORY_L2_DERIVE = "memory_l2_derive"
    RUNTIME_OPERATIONAL_GC = "runtime_operational_gc"
    BACKGROUND_TASK_RETENTION = "background_task_retention"


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
    # Display-only field. NOT persisted in target_state (#89: redundant mirror removed).
    # Single source of truth is the APScheduler jobstore, read via
    # ScheduleRepository.get_schedule_next_run_at -> apscheduler_jobs.next_run_time.
    # Populated by get_schedule_runtime_state; get_target_state always returns None here.
    # Do NOT build firing/decision logic on it.
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
    data_generation: int = 0


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


# --- Source schedule helpers ---

def build_source_target_key(connection_id: str, source_type: str) -> str:
    """Build a source target key scoped to one account connection."""
    return f"{connection_id}:{source_type}"


def build_source_schedule_id(connection_id: str, source_type: str) -> str:
    """Build a recurring source schedule id scoped to one account connection."""
    return f"source-sync:{connection_id}:{source_type}"
