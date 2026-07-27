"""Session lifecycle helpers for L0 working memory."""

from __future__ import annotations

import time
import asyncio
from typing import Any, Dict, Optional, Protocol, cast

from ....core.sqlite import sqlite_connection_async

class _L0SessionHostProtocol(Protocol):
    checkpoint_db_path: str
    _checkpoint_lock: asyncio.Lock

    async def initialize(self) -> None: ...

    async def checkpoint_session(self, session_id: str) -> None: ...

    def _schedule_checkpoint(self, session_id: str) -> None: ...

    def _cancel_scheduled_checkpoint(self, session_id: str) -> None: ...

    def _schedule_checkpoint_session_delete(self, session_id: str) -> None: ...


class L0SessionLifecycleMixin:
    """Own L0 session creation, refresh, expiry, and eviction."""

    session_timeout_seconds: int
    max_concurrent_sessions: int
    _sessions: dict[str, dict[str, Any]]
    _attention_items: dict[str, dict[str, dict[str, Any]]]

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
        host = cast(_L0SessionHostProtocol, self)
        async with host._checkpoint_lock:
            return await self._start_session_locked(
                host,
                session_id=session_id,
                user_id=user_id,
                runtime_agent_id=runtime_agent_id,
                status=status,
                metadata=metadata,
            )

    async def _start_session_locked(
        self,
        host: _L0SessionHostProtocol,
        *,
        session_id: str,
        user_id: Optional[str] = None,
        runtime_agent_id: Optional[str] = None,
        status: str = "active",
        metadata: Optional[Dict[str, Any]] = None,
    ) -> dict[str, Any]:
        """Create or refresh a session while the checkpoint lock is held."""

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
            self._attention_items.setdefault(session_id, {})
            host._schedule_checkpoint(session_id)
            return existing

        if len(self._sessions) >= self.max_concurrent_sessions:
            await self._evict_lru_session_locked(host)

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
        self._attention_items.setdefault(session_id, {})
        host._schedule_checkpoint(session_id)
        return session

    def _ensure_session_sync(self, session_id: str) -> dict[str, Any]:
        session = self._sessions.get(session_id)
        now = time.time()
        if session is not None:
            session["last_active_at"] = now
            session["status"] = "active"
            return session
        if len(self._sessions) >= self.max_concurrent_sessions:
            self._evict_lru_session_sync()
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
        self._attention_items.setdefault(session_id, {})
        cast(_L0SessionHostProtocol, self)._schedule_checkpoint(session_id)
        return session

    async def expire_idle_sessions(self) -> list[str]:
        """Delete idle sessions only after their attention has also expired."""
        host = cast(_L0SessionHostProtocol, self)
        await host.initialize()
        async with host._checkpoint_lock:
            now = time.time()
            expired = [
                session_id
                for session_id, session in self._sessions.items()
                if (
                    now - float(session["last_active_at"])
                    > self.session_timeout_seconds
                    and not any(
                        item.get("expires_at") is None
                        or float(item["expires_at"]) > now
                        for item in self._attention_items.get(
                            session_id,
                            {},
                        ).values()
                    )
                )
            ]
            if not expired:
                return []
            async with sqlite_connection_async(host.checkpoint_db_path) as db:
                await db.execute("BEGIN IMMEDIATE")
                try:
                    for table in (
                        "l0_attention_items",
                        "l0_sessions",
                    ):
                        await db.executemany(
                            f"DELETE FROM {table} WHERE session_id = ?",
                            [(session_id,) for session_id in expired],
                        )
                    await db.commit()
                except BaseException:
                    await db.rollback()
                    raise
            for session_id in expired:
                self._remove_session_state(session_id)
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
                    "l0_attention_items",
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
        host = cast(_L0SessionHostProtocol, self)
        async with host._checkpoint_lock:
            return await self._evict_lru_session_locked(host)

    async def _evict_lru_session_locked(
        self,
        host: _L0SessionHostProtocol,
    ) -> Optional[str]:
        """Evict one LRU session while the checkpoint lock is held."""

        if not self._sessions:
            return None
        candidates = list(self._sessions)
        if not candidates:
            return None
        lru_id = min(
            candidates,
            key=lambda sid: float(self._sessions[sid]["last_active_at"]),
        )
        async with sqlite_connection_async(host.checkpoint_db_path) as db:
            for table in (
                "l0_attention_items",
                "l0_sessions",
            ):
                await db.execute(
                    f"DELETE FROM {table} WHERE session_id = ?",
                    (lru_id,),
                )
            await db.commit()
        self._remove_session_state(lru_id)
        return lru_id

    def _evict_lru_session_sync(self) -> Optional[str]:
        """Evict disposable L0 state without blocking synchronous chat routing."""

        if not self._sessions:
            return None
        lru_id = min(
            self._sessions,
            key=lambda sid: float(self._sessions[sid]["last_active_at"]),
        )
        self._remove_session_state(lru_id)
        cast(_L0SessionHostProtocol, self)._schedule_checkpoint_session_delete(
            lru_id
        )
        return lru_id

    def _remove_session_state(self, session_id: str) -> None:
        cast(_L0SessionHostProtocol, self)._cancel_scheduled_checkpoint(session_id)
        self._sessions.pop(session_id, None)
        self._attention_items.pop(session_id, None)


__all__ = ["L0SessionLifecycleMixin"]
