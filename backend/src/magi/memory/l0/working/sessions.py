"""Session lifecycle helpers for L0 working memory."""

from __future__ import annotations

import time
from typing import Any, Dict, Optional, Protocol, cast

from ...event_contracts import MemoryEvent


class _L0SessionHostProtocol(Protocol):
    async def checkpoint_session(self, session_id: str) -> None: ...


class L0SessionLifecycleMixin:
    """Own L0 session creation, refresh, expiry, and eviction."""

    session_timeout_seconds: int
    max_concurrent_sessions: int
    _sessions: dict[str, dict[str, Any]]
    _goal_stack: dict[str, list[dict[str, Any]]]
    _active_entities: dict[str, dict[tuple[str, str], dict[str, Any]]]
    _temporary_tactics: dict[str, dict[str, dict[str, Any]]]
    _execution_runs: dict[str, dict[str, Any]]
    _execution_pending_turns: dict[str, list[dict[str, Any]]]
    _execution_results: dict[str, list[dict[str, Any]]]

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
        return session

    async def capture_event(self, event: MemoryEvent) -> None:
        """Refresh the runtime workbench based on the latest normalized event."""
        if not event.session_id:
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
            return session
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
        return session

    async def expire_idle_sessions(self) -> list[str]:
        """Checkpoint, expire, and evict sessions idle beyond the configured timeout."""
        now = time.time()
        host = cast(_L0SessionHostProtocol, self)
        expired: list[str] = []
        for session_id, session in list(self._sessions.items()):
            if now - float(session["last_active_at"]) <= self.session_timeout_seconds:
                continue
            session["status"] = "expired"
            try:
                await host.checkpoint_session(session_id)
            except Exception:
                pass
            self._remove_session_state(session_id)
            expired.append(session_id)
        return expired

    async def _evict_lru_session(self) -> Optional[str]:
        """Checkpoint and evict the least-recently-active session."""
        if not self._sessions:
            return None
        host = cast(_L0SessionHostProtocol, self)
        lru_id = min(
            self._sessions,
            key=lambda sid: float(self._sessions[sid]["last_active_at"]),
        )
        try:
            await host.checkpoint_session(lru_id)
        except Exception:
            pass
        self._remove_session_state(lru_id)
        return lru_id

    def _remove_session_state(self, session_id: str) -> None:
        self._sessions.pop(session_id, None)
        self._goal_stack.pop(session_id, None)
        self._active_entities.pop(session_id, None)
        self._temporary_tactics.pop(session_id, None)
        self._execution_runs.pop(session_id, None)
        self._execution_pending_turns.pop(session_id, None)
        self._execution_results.pop(session_id, None)


__all__ = ["L0SessionLifecycleMixin"]
