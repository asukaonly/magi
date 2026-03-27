"""Plugin ingress event routing contracts."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol

from ..runtime_trace import PluginIngressEventRecord


class PluginIngressEventHandler(Protocol):
    """Consumes one claimed plugin ingress event."""

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
