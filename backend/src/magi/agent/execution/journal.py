"""Append-only run journal facade used by the unified agent loop."""

from __future__ import annotations

import time
from typing import Any
from uuid import uuid4

from magi.runtime_trace.run_events import AgentRunEvent, AgentRunEventType

from .contracts import RunContextManifest


class AgentRunJournal:
    """Maintain event ordering and optionally persist through RuntimeTraceStore."""

    def __init__(
        self,
        *,
        run_id: str,
        turn_id: str | None,
        session_id: str | None,
        user_id: str | None,
        store: Any | None = None,
    ) -> None:
        self.run_id = str(run_id)
        self.turn_id = turn_id
        self.session_id = session_id
        self.user_id = user_id
        self._store = store
        self._sequence = 0
        self._events: list[AgentRunEvent] = []
        self._manifest: RunContextManifest | None = None

    @property
    def events(self) -> tuple[AgentRunEvent, ...]:
        return tuple(self._events)

    @property
    def manifest(self) -> RunContextManifest | None:
        return self._manifest

    async def record_manifest(self, manifest: RunContextManifest) -> None:
        if manifest.run_id != self.run_id:
            raise ValueError("RunContextManifest run_id does not match journal run_id")
        if self._manifest is not None:
            raise ValueError("RunContextManifest may only be recorded once per run")
        self._manifest = manifest
        if self._store is not None:
            await self._store.insert_run_manifest(manifest.to_dict())

    async def resume(self) -> None:
        """Continue event numbering for an already persisted run."""
        if self._store is None:
            return
        events = await self._store.list_run_events(self.run_id)
        if events:
            self._sequence = max(int(item["sequence"]) for item in events)

    async def append(
        self,
        event_type: AgentRunEventType,
        *,
        payload: dict[str, Any] | None = None,
        step_index: int | None = None,
    ) -> AgentRunEvent:
        self._sequence += 1
        event = AgentRunEvent(
            event_id=uuid4().hex,
            run_id=self.run_id,
            sequence=self._sequence,
            event_type=event_type,
            created_at_ms=int(time.time() * 1000),
            turn_id=self.turn_id,
            session_id=self.session_id,
            user_id=self.user_id,
            step_index=step_index,
            payload=dict(payload or {}),
        )
        if self._store is not None:
            await self._store.append_run_event(event.to_dict())
        self._events.append(event)
        return event


__all__ = ["AgentRunJournal"]
