"""Plugin ingress authoring contracts for Magi plugins."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol, runtime_checkable


@runtime_checkable
class PluginIngressEventRecord(Protocol):
    """Host-provided plugin ingress event envelope passed to handlers."""

    event_id: int
    source_kind: str
    producer: str
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


__all__ = [
    "PluginIngressEventHandler",
    "PluginIngressEventRecord",
    "PluginIngressHandlerRegistration",
]