"""Plugin ingress authoring contracts for Magi plugins."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol, runtime_checkable


class IngressProcessingError(RuntimeError):
    """Report a safe processing category without persisting credentials or payloads."""

    CODES = frozenset({"permission_required", "invalid_payload", "unsupported_schema", "temporarily_unavailable", "handler_timeout", "handler_failed"})
    PERMANENT = frozenset({"permission_required", "invalid_payload", "unsupported_schema"})

    def __init__(self, code: str) -> None:
        if code not in self.CODES:
            raise ValueError("Unsupported ingress failure category")
        self.code = code
        super().__init__(code)


def classify_ingress_error(error: BaseException) -> str:
    if isinstance(error, IngressProcessingError):
        return error.code
    if isinstance(error, PermissionError):
        return "permission_required"
    if isinstance(error, (ValueError, TypeError)):
        return "invalid_payload"
    if isinstance(error, TimeoutError):
        return "handler_timeout"
    if isinstance(error, OSError):
        return "temporarily_unavailable"
    return "handler_failed"


@runtime_checkable
class PluginIngressEventRecord(Protocol):
    """Host-provided plugin ingress event envelope passed to handlers."""

    event_id: int
    source_kind: str
    producer: str
    connection_id: str
    connection_epoch: str
    plugin_target: str
    event_type: str
    occurred_at_ms: int
    payload_json: str
    cursor_key: str | None
    status: str
    claimed_by: str | None
    claimed_at_ms: int | None
    processed_at_ms: int | None
    last_error: str | None
    created_at_ms: int


@runtime_checkable
class PluginIngressEventHandler(Protocol):
    """Consume one claimed plugin ingress event."""

    async def handle_event(
        self,
        event: PluginIngressEventRecord,
        payload: dict[str, Any],
    ) -> None:
        """Process one ingress event payload."""


@dataclass(frozen=True, slots=True)
class PluginIngressHandlerRegistration:
    """Static routing entry for the plugin ingress processor."""

    plugin_target: str
    event_type: str
    handler: PluginIngressEventHandler
    # Opt in only when repeating the same event_id cannot repeat an external effect.
    replay_safe: bool = False


__all__ = [
    "IngressProcessingError",
    "PluginIngressEventHandler",
    "PluginIngressEventRecord",
    "PluginIngressHandlerRegistration",
    "classify_ingress_error",
]
