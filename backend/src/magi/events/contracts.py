"""Typed contracts for runtime command and notification channels."""

from __future__ import annotations

import json
import time
import uuid
from dataclasses import asdict, dataclass, field
from enum import Enum
from typing import Any


class RuntimeCommandType(str, Enum):
    """Supported persisted runtime command types."""

    USER_MESSAGE = "user_message"
    REFRESH_LLM_CONFIG = "refresh_llm_config"
    REFRESH_CHANNELS = "refresh_channels"
    SENSOR_SYNC = "sensor_sync"
    SENSOR_STATE_FLUSH = "sensor_state_flush"


@dataclass(slots=True)
class UserMessageCommand:
    """Persisted command payload for a user message turn."""

    source: str
    user_id: str
    session_id: str
    turn_id: str
    message: str
    attachments: list[dict[str, Any]] = field(default_factory=list)
    workspace_path: str | None = None
    runtime_namespace: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)
    created_at: float = field(default_factory=time.time)
    correlation_id: str = field(default_factory=lambda: f"cmd_{uuid.uuid4().hex[:16]}")
    delivery_attempt_no: int = 0
    runtime_command_id: int | None = None

    def to_payload(self) -> dict[str, Any]:
        payload = asdict(self)
        payload.pop("delivery_attempt_no")
        payload.pop("runtime_command_id")
        return payload


@dataclass(slots=True)
class RefreshLLMConfigCommand:
    """Persisted command payload for reloading runtime LLM configuration."""

    source: str
    reason: str | None = None
    created_at: float = field(default_factory=time.time)
    correlation_id: str = field(default_factory=lambda: f"cmd_{uuid.uuid4().hex[:16]}")

    def to_payload(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True)
class RefreshChannelsCommand:
    """Persisted command payload for reloading channel adapters."""

    source: str
    reason: str | None = None
    created_at: float = field(default_factory=time.time)
    correlation_id: str = field(default_factory=lambda: f"cmd_{uuid.uuid4().hex[:16]}")

    def to_payload(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True)
class SensorSyncCommand:
    """Persisted command payload for queueing a sensor sync on the runtime worker."""

    source: str
    source_name: str
    connection_id: str
    first_context: bool = False
    sync_mode: str = "latest"
    backfill_scope: str | None = None
    backfill_days: int | None = None
    backfill_start_date: str | None = None
    backfill_end_date: str | None = None
    created_at: float = field(default_factory=time.time)
    correlation_id: str = field(default_factory=lambda: f"cmd_{uuid.uuid4().hex[:16]}")

    def __post_init__(self) -> None:
        if not self.connection_id.strip():
            raise ValueError("Sensor command requires an explicit connection identity")

    def to_payload(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True)
class SensorStateFlushCommand:
    """Persisted command payload for flushing in-progress sensor state."""

    source: str
    source_name: str
    connection_id: str
    created_at: float = field(default_factory=time.time)
    correlation_id: str = field(default_factory=lambda: f"cmd_{uuid.uuid4().hex[:16]}")

    def __post_init__(self) -> None:
        if not self.connection_id.strip():
            raise ValueError("Sensor command requires an explicit connection identity")

    def to_payload(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True)
class RuntimeQueuedCommand:
    """One claimed runtime command."""

    command_id: int
    command_type: RuntimeCommandType
    payload: dict[str, Any]
    correlation_id: str
    retry_count: int = 0
    user_message_generation: int = 0
    delivery_attempt_no: int = 0

    @property
    def runtime_command_id(self) -> int:
        """Return the durable identity of this physical delivery command."""
        return self.command_id

    def as_user_message(self) -> UserMessageCommand:
        """Convert the queued payload into a typed user-message command."""
        return UserMessageCommand(
            **self.payload,
            delivery_attempt_no=self.delivery_attempt_no,
            runtime_command_id=self.runtime_command_id,
        )

    def as_refresh_llm_config(self) -> RefreshLLMConfigCommand:
        """Convert the queued payload into a typed config-refresh command."""
        return RefreshLLMConfigCommand(**self.payload)

    def as_sensor_sync(self) -> SensorSyncCommand:
        """Convert the queued payload into a typed sensor-sync command."""
        return SensorSyncCommand(**self.payload)

    def as_refresh_channels(self) -> RefreshChannelsCommand:
        """Convert the queued payload into a typed channel-refresh command."""
        return RefreshChannelsCommand(**self.payload)

    def as_sensor_state_flush(self) -> SensorStateFlushCommand:
        """Convert the queued payload into a typed sensor-state-flush command."""
        return SensorStateFlushCommand(**self.payload)


@dataclass(slots=True)
class RuntimeNotificationPayload:
    """Serialized websocket-facing notification entry."""

    channel: str
    user_id: str
    session_id: str
    turn_id: str | None = None
    payload: dict[str, Any] = field(default_factory=dict)
    created_at_ms: int = field(default_factory=lambda: int(time.time() * 1000))

    def to_json(self) -> str:
        return json.dumps(self.payload, ensure_ascii=False)
