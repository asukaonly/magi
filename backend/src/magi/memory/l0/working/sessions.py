"""Session lifecycle helpers for L0 working memory."""

from __future__ import annotations

import time
import asyncio
from typing import Any, Dict, Optional, Protocol, cast

from ....core.sqlite import sqlite_connection_async
from ...event_contracts import MemoryEvent
from ...source_event_governance import govern_source_events_by_time_range


class _L0SessionHostProtocol(Protocol):
    checkpoint_db_path: str
    _checkpoint_lock: asyncio.Lock

    async def initialize(self) -> None: ...

    async def checkpoint_session(self, session_id: str) -> None: ...

    def _schedule_checkpoint(self, session_id: str) -> None: ...

    def _cancel_scheduled_checkpoint(self, session_id: str) -> None: ...


class L0SessionLifecycleMixin:
    """Own L0 session creation, refresh, expiry, and eviction."""

    session_timeout_seconds: int
    max_concurrent_sessions: int
    _sessions: dict[str, dict[str, Any]]
    _goal_stack: dict[str, list[dict[str, Any]]]
    _active_entities: dict[str, dict[tuple[str, str], dict[str, Any]]]
    _temporary_tactics: dict[str, dict[str, dict[str, Any]]]

    async def start_session(
        self,
        *,
        session_id: str,
        user_id: Optional[str] = None,
        runtime_agent_id: Optional[str] = None,
        status: str = "active",
        metadata: Optional[Dict[str, Any]] = None,
    ) -> dict[str, Any]:
        """Create or refresh an L0 session."""
        now = time.time()
        existing = self._sessions.get(session_id)
        if existing is not None:
            existing["last_active_at"] = now
            existing["status"] = "active"
            if user_id:
                existing["user_id"] = user_id
            if runtime_agent_id:
                existing["runtime_agent_id"] = runtime_agent_id
            if metadata:
                merged = dict(existing.get("metadata", {}))
                merged.update(metadata)
                existing["metadata"] = merged
            self._goal_stack.setdefault(session_id, [])
            self._active_entities.setdefault(session_id, {})
            self._temporary_tactics.setdefault(session_id, {})
            cast(_L0SessionHostProtocol, self)._schedule_checkpoint(session_id)
            return existing

        if len(self._sessions) >= self.max_concurrent_sessions:
            await self._evict_lru_session()

        session = {
            "session_id": session_id,
            "user_id": user_id,
            "runtime_agent_id": runtime_agent_id,
            "status": status,
            "started_at": now,
            "last_active_at": now,
            "last_checkpoint_at": None,
            "metadata": dict(metadata or {}),
        }
        self._sessions[session_id] = session
        self._goal_stack.setdefault(session_id, [])
        self._active_entities.setdefault(session_id, {})
        self._temporary_tactics.setdefault(session_id, {})
        cast(_L0SessionHostProtocol, self)._schedule_checkpoint(session_id)
        return session

    async def capture_event(self, event: MemoryEvent) -> None:
        """Refresh the runtime workbench based on the latest normalized event."""
        if not event.session_id:
            return
        host = cast(_L0SessionHostProtocol, self)
        await host.initialize()
        async with sqlite_connection_async(host.checkpoint_db_path) as db:
            await db.execute("BEGIN IMMEDIATE")
            try:
                decision = await govern_source_events_by_time_range(
                    db,
                    event_ids=(event.event_id, event.turn_id),
                    observed_from=float(event.timestamp),
                )
                await db.commit()
            except BaseException:
                await db.rollback()
                raise
        if decision.blocks_derivations:
            return

        session = await self.start_session(
            session_id=event.session_id,
            user_id=event.user_id,
            metadata={"last_event_type": event.event_type},
        )
        session["last_active_at"] = max(float(session["last_active_at"]), float(event.timestamp))

    def _ensure_session_sync(self, session_id: str) -> dict[str, Any]:
        session = self._sessions.get(session_id)
        now = time.time()
        if session is not None:
            session["last_active_at"] = now
            session["status"] = "active"
            return session
        if len(self._sessions) >= self.max_concurrent_sessions:
            raise RuntimeError(
                "L0 synchronous session admission exceeded configured capacity"
            )
        session = {
            "session_id": session_id,
            "user_id": None,
            "runtime_agent_id": None,
            "status": "active",
            "started_at": now,
            "last_active_at": now,
            "last_checkpoint_at": None,
            "metadata": {},
        }
        self._sessions[session_id] = session
        self._goal_stack.setdefault(session_id, [])
        self._active_entities.setdefault(session_id, {})
        self._temporary_tactics.setdefault(session_id, {})
        cast(_L0SessionHostProtocol, self)._schedule_checkpoint(session_id)
        return session

    async def expire_idle_sessions(self) -> list[str]:
        """Delete disposable sessions idle beyond the configured timeout."""
        now = time.time()
        expired: list[str] = []
        for session_id, session in list(self._sessions.items()):
            if now - float(session["last_active_at"]) <= self.session_timeout_seconds:
                continue
            await self.forget_session(session_id)
            expired.append(session_id)
        return expired

    async def forget_session(self, session_id: str) -> None:
        """Remove one session from memory and every restart checkpoint."""
        normalized_session_id = str(session_id or "").strip()
        if not normalized_session_id:
            raise ValueError("session_id must not be empty")
        host = cast(_L0SessionHostProtocol, self)
        await host.initialize()
        async with host._checkpoint_lock:
            async with sqlite_connection_async(host.checkpoint_db_path) as db:
                for table in (
                    "l0_goal_stack",
                    "l0_active_entities",
                    "l0_temporary_tactics",
                    "l0_sessions",
                ):
                    await db.execute(
                        f"DELETE FROM {table} WHERE session_id = ?",
                        (normalized_session_id,),
                    )
                await db.commit()
            self._remove_session_state(normalized_session_id)

    async def _evict_lru_session(self) -> Optional[str]:
        """Delete the least-recently-active disposable session."""
        if not self._sessions:
            return None
        candidates = list(self._sessions)
        if not candidates:
            return None
        lru_id = min(
            candidates,
            key=lambda sid: float(self._sessions[sid]["last_active_at"]),
        )
        await self.forget_session(lru_id)
        return lru_id

    def _remove_session_state(self, session_id: str) -> None:
        cast(_L0SessionHostProtocol, self)._cancel_scheduled_checkpoint(session_id)
        self._sessions.pop(session_id, None)
        self._goal_stack.pop(session_id, None)
        self._active_entities.pop(session_id, None)
        self._temporary_tactics.pop(session_id, None)


__all__ = ["L0SessionLifecycleMixin"]
