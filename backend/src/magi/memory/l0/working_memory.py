"""L0 working memory store with in-memory state and SQLite checkpoints."""

from __future__ import annotations

import time
import uuid
from pathlib import Path
from typing import Any, Dict, Optional

import aiosqlite

from ...core.sqlite import sqlite_connection_async
from ..event_contracts import MemoryEvent
from .contracts import L0PromptWorkbenchProjection
from .working.execution import L0ExecutionStateMixin
from .working.projection import build_execution_summary
from .working.schema import (
    clear_l0_checkpoint_tables,
    ensure_execution_pending_turn_columns,
    ensure_execution_run_columns,
    ensure_l0_checkpoint_schema,
)
from .working.serialization import (
    active_entity_key,
    encode_json,
    row_to_active_entity,
    row_to_execution_result,
    row_to_execution_run,
    row_to_goal,
    row_to_pending_turn,
    row_to_session,
    row_to_tactic,
)


MAX_CONCURRENT_SESSIONS = 64


class L0WorkingMemoryStore(L0ExecutionStateMixin):
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

    async def checkpoint_session(self, session_id: str) -> None:
        """Persist a single session workbench into the checkpoint database."""
        session = self._sessions.get(session_id)
        if session is None:
            return

        now = time.time()
        session["last_checkpoint_at"] = now

        async with sqlite_connection_async(self.checkpoint_db_path) as db:
            await db.execute(
                """
                INSERT INTO l0_sessions(
                    session_id, user_id, runtime_agent_id, status,
                    started_at, last_active_at, last_checkpoint_at, metadata
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(session_id) DO UPDATE SET
                    user_id = excluded.user_id,
                    runtime_agent_id = excluded.runtime_agent_id,
                    status = excluded.status,
                    started_at = excluded.started_at,
                    last_active_at = excluded.last_active_at,
                    last_checkpoint_at = excluded.last_checkpoint_at,
                    metadata = excluded.metadata
                """,
                (
                    session["session_id"],
                    session.get("user_id"),
                    session.get("runtime_agent_id"),
                    session.get("status", "active"),
                    float(session["started_at"]),
                    float(session["last_active_at"]),
                    now,
                    encode_json(session.get("metadata", {})),
                ),
            )

            await db.execute("DELETE FROM l0_goal_stack WHERE session_id = ?", (session_id,))
            for goal in self._goal_stack.get(session_id, []):
                await db.execute(
                    """
                    INSERT INTO l0_goal_stack(
                        session_id, goal_id, parent_goal_id, goal_type, description,
                        status, priority, created_at, started_at, completed_at,
                        result_summary, metadata
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        session_id,
                        goal["goal_id"],
                        goal.get("parent_goal_id"),
                        goal["goal_type"],
                        goal["description"],
                        goal["status"],
                        int(goal["priority"]),
                        float(goal["created_at"]),
                        goal.get("started_at"),
                        goal.get("completed_at"),
                        goal.get("result_summary"),
                        encode_json(goal.get("metadata", {})),
                    ),
                )

            await db.execute("DELETE FROM l0_active_entities WHERE session_id = ?", (session_id,))
            for entity in self._active_entities.get(session_id, {}).values():
                await db.execute(
                    """
                    INSERT INTO l0_active_entities(
                        session_id, entity_id, entity_type, relevance_score,
                        snapshot_json, loaded_at, last_accessed_at, access_count
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        session_id,
                        entity["entity_id"],
                        entity["entity_type"],
                        float(entity["relevance_score"]),
                        encode_json(entity["snapshot"]),
                        float(entity["loaded_at"]),
                        float(entity["last_accessed_at"]),
                        int(entity["access_count"]),
                    ),
                )

            await db.execute("DELETE FROM l0_temporary_tactics WHERE session_id = ?", (session_id,))
            for tactic in self._temporary_tactics.get(session_id, {}).values():
                await db.execute(
                    """
                    INSERT INTO l0_temporary_tactics(
                        tactic_id, session_id, scope_type, scope_id, tactic_type,
                        tactic_payload, source_event_ids, expires_at, created_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        tactic["tactic_id"],
                        session_id,
                        tactic["scope_type"],
                        tactic["scope_id"],
                        tactic["tactic_type"],
                        encode_json(tactic["tactic_payload"]),
                        encode_json(tactic["source_event_ids"]),
                        tactic.get("expires_at"),
                        float(tactic["created_at"]),
                    ),
                )

            await db.execute("DELETE FROM l0_execution_runs WHERE session_id = ?", (session_id,))
            execution_run = self._execution_runs.get(session_id)
            if execution_run is not None:
                await db.execute(
                    """
                    INSERT INTO l0_execution_runs(
                        session_id, run_id, status, revision, root_turn_id,
                        root_user_message, response_anchor_turn_id, cancel_requested_at,
                        cancel_reason, cancel_requested_by, cancel_anchor_turn_id, created_at, updated_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        session_id,
                        execution_run["run_id"],
                        execution_run["status"],
                        int(execution_run["revision"]),
                        execution_run.get("root_turn_id"),
                        execution_run.get("root_user_message", ""),
                        execution_run.get("response_anchor_turn_id"),
                        execution_run.get("cancel_requested_at"),
                        execution_run.get("cancel_reason"),
                        execution_run.get("cancel_requested_by"),
                        execution_run.get("cancel_anchor_turn_id"),
                        float(execution_run["created_at"]),
                        float(execution_run["updated_at"]),
                    ),
                )

            await db.execute("DELETE FROM l0_execution_pending_turns WHERE session_id = ?", (session_id,))
            for pending_turn in self._execution_pending_turns.get(session_id, []):
                await db.execute(
                    """
                    INSERT INTO l0_execution_pending_turns(
                        session_id, run_id, turn_id, content, revision, disposition, created_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        session_id,
                        pending_turn["run_id"],
                        pending_turn["turn_id"],
                        pending_turn["content"],
                        int(pending_turn["revision"]),
                        str(pending_turn.get("disposition") or "augment"),
                        float(pending_turn["created_at"]),
                    ),
                )

            await db.execute("DELETE FROM l0_execution_results WHERE session_id = ?", (session_id,))
            for result in self._execution_results.get(session_id, []):
                await db.execute(
                    """
                    INSERT INTO l0_execution_results(
                        result_id, session_id, run_id, revision, disposition, payload_json, created_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        result["result_id"],
                        session_id,
                        result["run_id"],
                        int(result["revision"]),
                        result["disposition"],
                        encode_json(result["payload"]),
                        float(result["created_at"]),
                    ),
                )

            await db.commit()

    async def checkpoint_all(self) -> None:
        """Persist every active session."""
        for session_id in list(self._sessions):
            await self.checkpoint_session(session_id)

    async def clear(self) -> int:
        """Delete all L0 sessions from memory and checkpoints."""
        await self.initialize()
        count = len(self._sessions)
        self._sessions.clear()
        self._goal_stack.clear()
        self._active_entities.clear()
        self._temporary_tactics.clear()
        self._execution_runs.clear()
        self._execution_pending_turns.clear()
        self._execution_results.clear()

        async with sqlite_connection_async(self.checkpoint_db_path) as db:
            await clear_l0_checkpoint_tables(db)
            await db.commit()

        return count

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

    async def _restore_from_checkpoint(self) -> None:
        async with sqlite_connection_async(self.checkpoint_db_path) as db:
            db.row_factory = aiosqlite.Row

            async with db.execute("SELECT * FROM l0_sessions") as cursor:
                async for row in cursor:
                    session = row_to_session(row)
                    self._sessions[str(session["session_id"])] = session

            async with db.execute("SELECT * FROM l0_goal_stack ORDER BY created_at ASC") as cursor:
                async for row in cursor:
                    session_id = str(row["session_id"])
                    self._goal_stack.setdefault(session_id, []).append(row_to_goal(row))

            async with db.execute("SELECT * FROM l0_active_entities") as cursor:
                async for row in cursor:
                    session_id = str(row["session_id"])
                    self._active_entities.setdefault(session_id, {})[
                        active_entity_key(row)
                    ] = row_to_active_entity(row)

            async with db.execute("SELECT * FROM l0_temporary_tactics") as cursor:
                async for row in cursor:
                    session_id = str(row["session_id"])
                    tactic = row_to_tactic(row)
                    self._temporary_tactics.setdefault(session_id, {})[
                        str(tactic["tactic_id"])
                    ] = tactic

            async with db.execute("SELECT * FROM l0_execution_runs") as cursor:
                async for row in cursor:
                    execution_run = row_to_execution_run(row)
                    self._execution_runs[str(execution_run["session_id"])] = execution_run

            async with db.execute(
                "SELECT * FROM l0_execution_pending_turns ORDER BY created_at ASC, pending_id ASC"
            ) as cursor:
                async for row in cursor:
                    pending_turn = row_to_pending_turn(row)
                    self._execution_pending_turns.setdefault(
                        str(pending_turn["session_id"]), []
                    ).append(pending_turn)

            async with db.execute(
                "SELECT * FROM l0_execution_results ORDER BY created_at ASC, result_id ASC"
            ) as cursor:
                async for row in cursor:
                    result = row_to_execution_result(row)
                    self._execution_results.setdefault(str(result["session_id"]), []).append(result)

    async def _expire_stale_tactics(self, session_id: str) -> None:
        now = time.time()
        tactics = self._temporary_tactics.get(session_id, {})
        for tactic_id, tactic in list(tactics.items()):
            expires_at = tactic.get("expires_at")
            if expires_at is not None and float(expires_at) <= now:
                del tactics[tactic_id]

    @staticmethod
    async def _ensure_execution_run_columns(db: aiosqlite.Connection) -> None:
        await ensure_execution_run_columns(db)

    @staticmethod
    async def _ensure_execution_pending_turn_columns(db: aiosqlite.Connection) -> None:
        await ensure_execution_pending_turn_columns(db)


__all__ = ["L0WorkingMemoryStore"]
