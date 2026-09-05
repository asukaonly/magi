"""Wire-safe identities and contracts for the plugin execution boundary.

The host issues connection, invocation and resource identities. Plugins declare
capabilities and return data; they never choose the authority of an invocation.
"""

from __future__ import annotations

import math
from enum import Enum
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, JsonValue, StringConstraints, field_validator

SDK_VERSION = "0.2.0"
PLUGIN_PROTOCOL_VERSION = 2
RuntimeIdentifier = Annotated[str, StringConstraints(min_length=1, max_length=128, pattern=r"^[a-zA-Z0-9][a-zA-Z0-9_.:-]*$")]


class RuntimeModel(BaseModel):
    """Reject unknown wire fields instead of silently dropping requested behavior."""

    model_config = ConfigDict(extra="forbid", frozen=True)


class ConnectionStatus(str, Enum):
    DISABLED = "disabled"
    SETUP_REQUIRED = "setup_required"
    AUTH_REQUIRED = "auth_required"
    READY = "ready"
    DEGRADED = "degraded"
    FAILED = "failed"


class PluginConnection(RuntimeModel):
    """An independently configured binding, distinct from its installed package."""

    connection_id: RuntimeIdentifier
    plugin_id: RuntimeIdentifier
    display_name: str = Field(min_length=1, max_length=256)
    enabled: bool = False
    settings: dict[str, JsonValue] = Field(default_factory=dict)
    credential_refs: dict[str, str] = Field(default_factory=dict)
    revision: int = Field(default=0, ge=0)


class CapabilityGrant(RuntimeModel):
    """Host-issued permission scoped to a connection and bounded resources."""

    grant_id: RuntimeIdentifier
    connection_id: RuntimeIdentifier
    capability: str = Field(min_length=1, max_length=128)
    scopes: list[str] = Field(default_factory=list, max_length=128)
    expires_at: float | None = None

    @field_validator("expires_at")
    @classmethod
    def finite_expiry(cls, value: float | None) -> float | None:
        if value is not None and not math.isfinite(value):
            raise ValueError("Grant expiration must be finite")
        return value


class InvocationIdentity(RuntimeModel):
    """Trusted caller identity attached by the host, never by plugin arguments."""

    invocation_id: RuntimeIdentifier
    plugin_id: RuntimeIdentifier
    connection_id: RuntimeIdentifier
    principal_id: RuntimeIdentifier
    task_id: str | None = None
    session_id: str | None = None
    trigger: Literal["user", "model", "schedule", "ingress", "system"]


class ResourceRef(RuntimeModel):
    """Opaque, revocable reference to host-managed content."""

    resource_id: RuntimeIdentifier
    connection_id: RuntimeIdentifier
    media_type: str = Field(min_length=1, max_length=256)
    size_bytes: int = Field(ge=0)
    version: str = Field(min_length=1, max_length=256)
    display_name: str = Field(default="", max_length=512)


class SourceChange(RuntimeModel):
    """A source object's revision; deletion describes source state, not forgetting."""

    object_id: str = Field(min_length=1, max_length=1024)
    version: str = Field(min_length=1, max_length=256)
    operation: Literal["upsert", "delete"] = "upsert"
    occurred_at: float | None = None
    payload: dict[str, JsonValue] = Field(default_factory=dict)
    resources: list[ResourceRef] = Field(default_factory=list)

    @field_validator("occurred_at")
    @classmethod
    def finite_timestamp(cls, value: float | None) -> float | None:
        if value is not None and not math.isfinite(value):
            raise ValueError("Source timestamp must be finite")
        return value


class SourceChangeBatch(RuntimeModel):
    """Changes and an opaque progress token acknowledged together by the host."""

    changes: list[SourceChange] = Field(default_factory=list, max_length=10000)
    next_cursor: str | None = Field(default=None, max_length=65536)
    complete: bool = True
    watermark_ts: float | None = None
    stats: dict[str, JsonValue] = Field(default_factory=dict)

    @field_validator("watermark_ts")
    @classmethod
    def finite_watermark(cls, value: float | None) -> float | None:
        if value is not None and not math.isfinite(value):
            raise ValueError("Source watermark must be finite")
        return value


class CapabilityReadiness(RuntimeModel):
    """One authoritative capability state shared by UI and execution admission."""

    capability_id: RuntimeIdentifier
    connection_id: RuntimeIdentifier
    status: ConnectionStatus
    reason_code: str | None = None
    message: str | None = None


class OperationSpec(RuntimeModel):
    """Business operation independent of the interface that invokes it."""

    operation_id: RuntimeIdentifier
    description: str = Field(min_length=1, max_length=4096)
    input_schema: dict[str, JsonValue]
    output_schema: dict[str, JsonValue]
    triggers: list[Literal["user", "model", "schedule", "ingress", "system"]] = Field(min_length=1)
    required_capabilities: list[str] = Field(default_factory=list)
    effect: Literal["read_only", "local_write", "external_write", "destructive"]
    replay: Literal["read_only", "idempotent", "idempotent_with_key", "non_idempotent", "reconcilable"]
    timeout_seconds: float = Field(default=30, gt=0, le=3600)


class OperationResult(RuntimeModel):
    """Durable outcome; timeout/cancellation cannot imply that no effect occurred."""

    status: Literal["succeeded", "failed", "cancelled", "uncertain"]
    value: JsonValue = None
    resources: list[ResourceRef] = Field(default_factory=list)
    error_code: str | None = None
    message: str | None = None


class PluginHandshake(RuntimeModel):
    """Version agreement before loading plugin code or accepting contributions."""

    protocol_version: Literal[2]
    sdk_version: Literal["0.2.0"]
    plugin_id: RuntimeIdentifier
    connection_id: RuntimeIdentifier


__all__ = [
    "SDK_VERSION", "PLUGIN_PROTOCOL_VERSION", "RuntimeIdentifier", "RuntimeModel",
    "ConnectionStatus", "PluginConnection", "CapabilityGrant", "InvocationIdentity",
    "ResourceRef", "SourceChange", "SourceChangeBatch", "CapabilityReadiness",
    "OperationSpec", "OperationResult", "PluginHandshake",
]
