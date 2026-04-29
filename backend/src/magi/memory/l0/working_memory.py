"""L0 working memory store with in-memory state and SQLite checkpoints."""

from __future__ import annotations

import time
import uuid
from pathlib import Path
from typing import Any, Dict, Optional

from ...core.sqlite import sqlite_connection_async
from ..event_contracts import MemoryEvent
from .contracts import L0PromptWorkbenchProjection
from .working.checkpoint import L0CheckpointMixin
from .working.execution import L0ExecutionStateMixin
from .working.projection import build_execution_summary
from .working.schema import ensure_l0_checkpoint_schema


MAX_CONCURRENT_SESSIONS = 64


class L0WorkingMemoryStore(L0ExecutionStateMixin, L0CheckpointMixin):
    """Maintains session-local workbench state and restores it from checkpoints."""

    def __init__(
        self,
        *,
        checkpoint_db_path: str = "~/.magi/data/memory/memory.db",
        checkpoint_interval_seconds: int = 30,
        session_timeout_seconds: int = 3600,
        restore_on_restart: bool = True,
        max_concurrent_sessions: int = MAX_CONCURRENT_SESSIONS,
    ) -> None:
        self.checkpoint_db_path = str(Path(checkpoint_db_path).expanduser())
        self.checkpoint_interval_seconds = int(checkpoint_interval_seconds)
        self.session_timeout_seconds = int(session_timeout_seconds)
        self.restore_on_restart = bool(restore_on_restart)
        self.max_concurrent_sessions = int(max_concurrent_sessions)

        self._sessions: dict[str, dict[str, Any]] = {}
        self._goal_stack: dict[str, list[dict[str, Any]]] = {}
        self._active_entities: dict[str, dict[tuple[str, str], dict[str, Any]]] = {}
        self._temporary_tactics: dict[str, dict[str, dict[str, Any]]] = {}
        self._execution_runs: dict[str, dict[str, Any]] = {}
        self._execution_pending_turns: dict[str, list[dict[str, Any]]] = {}
        self._execution_results: dict[str, list[dict[str, Any]]] = {}
        self._initialized = False

    async def initialize(self) -> None:
        """Create checkpoint schema and optionally restore previously checkpointed state."""
        if self._initialized:
            return

        Path(self.checkpoint_db_path).parent.mkdir(parents=True, exist_ok=True)
        async with sqlite_connection_async(self.checkpoint_db_path) as db:
            await ensure_l0_checkpoint_schema(db)
            await db.commit()

        if self.restore_on_restart:
            await self._restore_from_checkpoint()

        self._initialized = True

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

        # Evict the least-recently-active session when at capacity
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

    async def push_goal(
        self,
        *,
        session_id: str,
        goal_id: str,
        goal_type: str,
        description: str,
        status: str = "pending",
        priority: int = 0,
        parent_goal_id: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> dict[str, Any]:
        """Push a goal into the in-memory goal stack."""
        await self.start_session(session_id=session_id)
        now = time.time()
        goal = {
            "goal_id": goal_id,
            "parent_goal_id": parent_goal_id,
            "goal_type": goal_type,
            "description": description,
            "status": status,
            "priority": int(priority),
            "created_at": now,
            "started_at": now if status == "in_progress" else None,
            "completed_at": None,
            "result_summary": None,
            "metadata": dict(metadata or {}),
        }
        self._goal_stack[session_id].append(goal)
        return goal

    def push_goal_sync(
        self,
        *,
        session_id: str,
        goal_id: str,
        goal_type: str,
        description: str,
        status: str = "pending",
        priority: int = 0,
        parent_goal_id: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> dict[str, Any]:
        """Synchronously push a goal into the in-memory goal stack."""
        self._ensure_session_sync(session_id)
        now = time.time()
        goal = {
            "goal_id": goal_id,
            "parent_goal_id": parent_goal_id,
            "goal_type": goal_type,
            "description": description,
            "status": status,
            "priority": int(priority),
            "created_at": now,
            "started_at": now if status == "in_progress" else None,
            "completed_at": None,
            "result_summary": None,
            "metadata": dict(metadata or {}),
        }
        self._goal_stack[session_id].append(goal)
        return dict(goal)

    async def set_goal_status(
        self,
        *,
        session_id: str,
        goal_id: str,
        status: str,
        result_summary: Optional[str] = None,
    ) -> bool:
        """Update the status of an existing goal."""
        goals = self._goal_stack.get(session_id, [])
        for goal in goals:
            if goal["goal_id"] != goal_id:
                continue
            goal["status"] = status
            if status == "in_progress" and goal["started_at"] is None:
                goal["started_at"] = time.time()
            if status in {"completed", "failed", "cancelled"}:
                goal["completed_at"] = time.time()
            if result_summary is not None:
                goal["result_summary"] = result_summary
            return True
        return False

    def set_goal_status_sync(
        self,
        *,
        session_id: str,
        goal_id: str,
        status: str,
        result_summary: Optional[str] = None,
    ) -> bool:
        """Synchronously update the status of an existing goal."""
        goals = self._goal_stack.get(session_id, [])
        for goal in goals:
            if goal["goal_id"] != goal_id:
                continue
            goal["status"] = status
            if status == "in_progress" and goal["started_at"] is None:
                goal["started_at"] = time.time()
            if status in {"completed", "failed", "cancelled"}:
                goal["completed_at"] = time.time()
            if result_summary is not None:
                goal["result_summary"] = result_summary
            return True
        return False

    async def upsert_active_entity(
        self,
        *,
        session_id: str,
        entity_id: str,
        entity_type: str,
        snapshot: Dict[str, Any],
        relevance_score: float = 0.0,
    ) -> dict[str, Any]:
        """Record an active entity card for prompt-time recall."""
        await self.start_session(session_id=session_id)
        now = time.time()
        key = (entity_id, entity_type)
        previous = self._active_entities[session_id].get(key)
        access_count = int(previous["access_count"] + 1) if previous else 1
        entity = {
            "entity_id": entity_id,
            "entity_type": entity_type,
            "relevance_score": float(relevance_score),
            "snapshot": dict(snapshot),
            "loaded_at": float(previous["loaded_at"]) if previous else now,
            "last_accessed_at": now,
            "access_count": access_count,
        }
        self._active_entities[session_id][key] = entity
        return entity

    async def add_temporary_tactic(
        self,
        *,
        session_id: str,
        scope_type: str,
        scope_id: str,
        tactic_type: str,
        tactic_payload: Dict[str, Any],
        source_event_ids: list[str],
        expires_at: Optional[float] = None,
        tactic_id: Optional[str] = None,
    ) -> dict[str, Any]:
        """Add a short-lived tactic that only applies within the active session."""
        await self.start_session(session_id=session_id)
        tactic = {
            "tactic_id": tactic_id or f"tactic_{uuid.uuid4().hex}",
            "scope_type": scope_type,
            "scope_id": scope_id,
            "tactic_type": tactic_type,
            "tactic_payload": dict(tactic_payload),
            "source_event_ids": list(source_event_ids),
            "expires_at": expires_at,
            "created_at": time.time(),
        }
        self._temporary_tactics[session_id][tactic["tactic_id"]] = tactic
        return tactic

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

    async def get_workbench(self, session_id: str) -> dict[str, Any]:
        """Return the prompt-consumable workbench for a session.

        The execution lane is intentionally excluded here so prompt assembly only
        sees the curated session workbench, not raw runtime control state.
        """
        await self._expire_stale_tactics(session_id)
        session = self._sessions.get(session_id)
        return {
            "session": dict(session) if session else None,
            "goal_stack": [dict(item) for item in self._goal_stack.get(session_id, [])],
            "active_entities": [
                dict(item)
                for item in sorted(
                    self._active_entities.get(session_id, {}).values(),
                    key=lambda item: (-float(item["relevance_score"]), -float(item["last_accessed_at"])),
                )
            ],
            "temporary_tactics": [
                dict(item)
                for item in sorted(
                    self._temporary_tactics.get(session_id, {}).values(),
                    key=lambda item: float(item["created_at"]),
                )
            ],
        }

    async def get_prompt_workbench_projection(self, session_id: str) -> L0PromptWorkbenchProjection:
        """Return the prompt-facing L0 projection with execution state summarized."""
        workbench = await self.get_workbench(session_id)
        execution_state = self.get_execution_state_sync(session_id)
        run = execution_state.get("run")
        pending_turns = execution_state.get("pending_turns", [])

        projection = L0PromptWorkbenchProjection(
            session=workbench.get("session"),
            goal_stack=list(workbench.get("goal_stack", [])),
            active_entities=list(workbench.get("active_entities", [])),
            temporary_tactics=list(workbench.get("temporary_tactics", [])),
        )
        projection.execution_summary = build_execution_summary(
            run=run if isinstance(run, dict) else None,
            pending_turns=[item for item in pending_turns if isinstance(item, dict)],
            accepted_results=[
                item
                for item in execution_state.get("accepted_results", [])
                if isinstance(item, dict)
            ],
        )
        return projection

    async def expire_idle_sessions(self) -> list[str]:
        """Expire sessions that have been idle beyond the configured timeout.

        Expired sessions are checkpointed, then purged from in-memory dicts
        to prevent unbounded growth.
        """
        now = time.time()
        expired: list[str] = []
        for session_id, session in list(self._sessions.items()):
            if now - float(session["last_active_at"]) <= self.session_timeout_seconds:
                continue
            session["status"] = "expired"
            # Checkpoint before evicting from memory
            try:
                await self.checkpoint_session(session_id)
            except Exception:
                pass
            self._sessions.pop(session_id, None)
            self._goal_stack.pop(session_id, None)
            self._active_entities.pop(session_id, None)
            self._temporary_tactics.pop(session_id, None)
            self._execution_runs.pop(session_id, None)
            self._execution_pending_turns.pop(session_id, None)
            self._execution_results.pop(session_id, None)
            expired.append(session_id)
        return expired

    async def _evict_lru_session(self) -> Optional[str]:
        """Checkpoint and evict the least-recently-active session."""
        if not self._sessions:
            return None
        lru_id = min(
            self._sessions,
            key=lambda sid: float(self._sessions[sid]["last_active_at"]),
        )
        try:
            await self.checkpoint_session(lru_id)
        except Exception:
            pass
        self._sessions.pop(lru_id, None)
        self._goal_stack.pop(lru_id, None)
        self._active_entities.pop(lru_id, None)
        self._temporary_tactics.pop(lru_id, None)
        self._execution_runs.pop(lru_id, None)
        self._execution_pending_turns.pop(lru_id, None)
        self._execution_results.pop(lru_id, None)
        return lru_id

    async def _expire_stale_tactics(self, session_id: str) -> None:
        now = time.time()
        tactics = self._temporary_tactics.get(session_id, {})
        for tactic_id, tactic in list(tactics.items()):
            expires_at = tactic.get("expires_at")
            if expires_at is not None and float(expires_at) <= now:
                del tactics[tactic_id]


__all__ = ["L0WorkingMemoryStore"]
