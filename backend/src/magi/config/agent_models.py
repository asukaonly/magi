"""Agent and runtime application configuration models."""

from __future__ import annotations

from pydantic import BaseModel, Field, model_validator

from .memory_models import MemorySettings


class PersonalitySettings(BaseModel):
    """Personality configuration."""
    name: str = Field(default="default")
    path: str = Field(default="~/.magi/personalities")
    enable_evolution: bool = Field(default=True)
    enable_state_memory: bool = Field(default=True)
    enable_state_transition: bool = Field(default=True)
    enable_deep_persona: bool = Field(default=True)

    @model_validator(mode="after")
    def normalize_runtime_feature_dependencies(self) -> "PersonalitySettings":
        """Keep persona sub-features disabled when state memory is off."""
        self.enable_evolution = bool(self.enable_state_memory)
        if not self.enable_state_memory:
            self.enable_state_transition = False
            self.enable_deep_persona = False
        return self


class MessageBusSettings(BaseModel):
    """Message bus configuration."""
    max_queue_size: int = Field(default=1000, ge=1)
    num_workers: int = Field(default=4, ge=1)
    broadcast_max_concurrency: int = Field(default=8, ge=1)
    handler_timeout_seconds: float = Field(default=2.0, ge=0.1)


class MaintenanceSettings(BaseModel):
    """Maintenance daemon configuration."""
    enabled: bool = Field(default=True, description="Enable maintenance daemon")
    interval_seconds: float = Field(default=300.0, ge=10.0, description="Interval between maintenance runs")
    health_check: bool = Field(default=True, description="Enable health checks")
    log_rotation_check: bool = Field(default=True, description="Enable log rotation checks")


class RuntimeSettings(BaseModel):
    """Runtime configuration for P0/P1 features."""
    router_restart_backoff_seconds: float = Field(default=1.0, ge=0.1)
    task_agent_queue_maxsize: int = Field(default=100, ge=1)
    task_agent_enqueue_timeout_ms: float = Field(default=100.0, ge=1.0)
    task_agent_manager_idle_ttl_seconds: float = Field(default=1800.0, ge=60.0)
    task_agent_manager_max_dynamic_instances: int = Field(default=100, ge=1)
    chat_history_cache_max_sessions: int = Field(default=500, ge=1)


class BackgroundTasksSettings(BaseModel):
    """Background-task subsystem configuration.

    Controls the detach-and-run pipeline that lets a chat session spawn
    long-running work without blocking the foreground turn loop. The
    ``enabled`` flag is a hard kill-switch: when ``false`` the dispatcher
    short-circuits to a foreground decision and the manager is still
    constructed but never receives work.
    """

    enabled: bool = Field(default=True, description="Feature flag; default on.")
    max_concurrent: int = Field(default=4, ge=1, description="Hard cap on simultaneously running tasks.")
    queue_when_full: bool = Field(
        default=True,
        description="Queue tasks when at cap; when false, falls back to foreground.",
    )
    auto_detect_long_task: bool = Field(
        default=False,
        description="Automatically route likely long-running chat tasks to background.",
    )
    auto_detect_threshold: float = Field(
        default=0.7,
        ge=0.0,
        le=1.0,
        description="Minimum classifier confidence to pick background.",
    )
    default_task_timeout_seconds: int = Field(
        default=1800,
        ge=60,
        description="Wall-clock timeout applied to each attempt.",
    )
    history_retention_days: int = Field(
        default=30,
        ge=1,
        description="How long terminal rows are kept for the history tab.",
    )


class AgentSettings(BaseModel):
    """Agent configuration."""
    name: str = Field(default="magi-agent")
    num_task_agents: int = Field(default=2, ge=1)
    loop_interval: float = Field(default=1.0, ge=0.0)
    enable_monitoring: bool = Field(default=True)

    memory: MemorySettings = Field(default_factory=MemorySettings)
    personality: PersonalitySettings = Field(default_factory=PersonalitySettings)
    message_bus: MessageBusSettings = Field(default_factory=MessageBusSettings)
    runtime: RuntimeSettings = Field(default_factory=RuntimeSettings)
    maintenance: MaintenanceSettings = Field(default_factory=MaintenanceSettings)
    background_tasks: BackgroundTasksSettings = Field(default_factory=BackgroundTasksSettings)


__all__ = [
    "AgentSettings",
    "BackgroundTasksSettings",
    "MaintenanceSettings",
    "MessageBusSettings",
    "PersonalitySettings",
    "RuntimeSettings",
]
