"""Plugin ingress handler for frontmost-app activation events."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from magi.runtime_trace import PluginIngressEventRecord

from .state import ScreenTimeStateStore


class ScreenTimePluginIngressHandler:
    """Reduce raw activation events into shared screen-time state."""

    def __init__(self, *, runtime_paths: Any, state_store: ScreenTimeStateStore | None = None) -> None:
        self._runtime_paths = runtime_paths
        self._state_store = state_store or ScreenTimeStateStore()

    async def handle_event(
        self,
        event: PluginIngressEventRecord,
        payload: dict[str, object],
    ) -> None:
        bundle_id = str(payload.get("bundle_id", "")).strip()
        if not bundle_id:
            raise ValueError("screen_time ingress event is missing bundle_id")

        app_name = str(payload.get("app_name") or bundle_id)
        occurred_at = datetime.fromtimestamp(event.occurred_at_ms / 1000, tz=timezone.utc)
        await self._state_store.apply_activation(
            runtime_paths=self._runtime_paths,
            occurred_at=occurred_at,
            bundle_id=bundle_id,
            app_name=app_name,
        )
