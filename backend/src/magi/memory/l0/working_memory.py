"""L0 working memory store with in-memory state and SQLite checkpoints."""

from __future__ import annotations

import json
import time
import uuid
from pathlib import Path
from typing import Any, Dict, Optional

import aiosqlite

from ...core.sqlite import sqlite_connection_async
from ..event_contracts import MemoryEvent


MAX_CONCURRENT_SESSIONS = 64


class L0WorkingMemoryStore:
    """Maintains session-local workbench state and restores it from checkpoints."""

    def __init__(
        self,
        *,
        checkpoint_db_path: str = "~/.magi/data/memories/memory.db",
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
            await db.executescript(
                """
                CREATE TABLE IF NOT EXISTS l0_sessions (
                    session_id TEXT PRIMARY KEY,
                    user_id TEXT,
                    runtime_agent_id TEXT,
                    status TEXT NOT NULL,
                    started_at REAL NOT NULL,
                    last_active_at REAL NOT NULL,
                    last_checkpoint_at REAL,
                    metadata TEXT
                );

                CREATE TABLE IF NOT EXISTS l0_goal_stack (
                    stack_id INTEGER PRIMARY KEY AUTOINCREMENT,
                    session_id TEXT NOT NULL,
                    goal_id TEXT NOT NULL,
                    parent_goal_id TEXT,
                    goal_type TEXT NOT NULL,
                    description TEXT NOT NULL,
                    status TEXT NOT NULL,
                    priority INTEGER DEFAULT 0,
                    created_at REAL NOT NULL,
                    started_at REAL,
                    completed_at REAL,
                    result_summary TEXT,
                    metadata TEXT
                );

                CREATE TABLE IF NOT EXISTS l0_active_entities (
                    session_id TEXT NOT NULL,
                    entity_id TEXT NOT NULL,
                    entity_type TEXT NOT NULL,
                    relevance_score REAL DEFAULT 0.0,
                    snapshot_json TEXT NOT NULL,
                    loaded_at REAL NOT NULL,
                    last_accessed_at REAL NOT NULL,
                    access_count INTEGER DEFAULT 0,
                    PRIMARY KEY (session_id, entity_id, entity_type)
                );

                CREATE TABLE IF NOT EXISTS l0_temporary_tactics (
                    tactic_id TEXT PRIMARY KEY,
                    session_id TEXT NOT NULL,
                    scope_type TEXT NOT NULL,
                    scope_id TEXT NOT NULL,
                    tactic_type TEXT NOT NULL,
                    tactic_payload TEXT NOT NULL,
                    source_event_ids TEXT NOT NULL,
                    expires_at REAL,
                    created_at REAL NOT NULL
                );

                CREATE TABLE IF NOT EXISTS l0_execution_runs (
                    session_id TEXT PRIMARY KEY,
                    run_id TEXT NOT NULL,
                    status TEXT NOT NULL,
                    revision INTEGER NOT NULL,
                    root_turn_id TEXT,
                    root_user_message TEXT NOT NULL,
                    response_anchor_turn_id TEXT,
                    created_at REAL NOT NULL,
                    updated_at REAL NOT NULL
                );

                CREATE TABLE IF NOT EXISTS l0_execution_pending_turns (
                    pending_id INTEGER PRIMARY KEY AUTOINCREMENT,
                    session_id TEXT NOT NULL,
                    run_id TEXT NOT NULL,
                    turn_id TEXT NOT NULL,
                    content TEXT NOT NULL,
                    revision INTEGER NOT NULL,
                    created_at REAL NOT NULL
                );

                CREATE TABLE IF NOT EXISTS l0_execution_results (
                    result_id TEXT PRIMARY KEY,
                    session_id TEXT NOT NULL,
                    run_id TEXT NOT NULL,
                    revision INTEGER NOT NULL,
                    disposition TEXT NOT NULL,
                    payload_json TEXT NOT NULL,
                    created_at REAL NOT NULL
                );
                """
            )
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

    async def upsert_execution_run(
        self,
        *,
        session_id: str,
        run_id: str,
        status: str,
        revision: int,
        root_turn_id: Optional[str] = None,
        root_user_message: str = "",
        response_anchor_turn_id: Optional[str] = None,
    ) -> dict[str, Any]:
        """Upsert the active execution run for a session."""
        await self.start_session(session_id=session_id)
        existing = self._execution_runs.get(session_id)
        now = time.time()
        execution_run = {
            "session_id": session_id,
            "run_id": run_id,
            "status": status,
            "revision": int(revision),
            "root_turn_id": root_turn_id,
            "root_user_message": root_user_message,
            "response_anchor_turn_id": response_anchor_turn_id,
            "created_at": float(existing["created_at"]) if existing else now,
            "updated_at": now,
        }
        self._execution_runs[session_id] = execution_run
        self._execution_pending_turns.setdefault(session_id, [])
        self._execution_results.setdefault(session_id, [])
        return dict(execution_run)

    async def append_execution_pending_turn(
        self,
        *,
        session_id: str,
        run_id: str,
        turn_id: str,
        content: str,
        revision: int,
    ) -> dict[str, Any]:
        """Append one pending user turn to the execution lane."""
        await self.start_session(session_id=session_id)
        pending_turn = {
            "session_id": session_id,
            "run_id": run_id,
            "turn_id": turn_id,
            "content": content,
            "revision": int(revision),
            "created_at": time.time(),
        }
        self._execution_pending_turns.setdefault(session_id, []).append(pending_turn)
        return dict(pending_turn)

    async def record_execution_result(
        self,
        *,
        session_id: str,
        run_id: str,
        result_id: str,
        revision: int,
        disposition: str,
        payload: Dict[str, Any],
    ) -> dict[str, Any]:
        """Record one accepted or stale execution result."""
        await self.start_session(session_id=session_id)
        result = {
            "result_id": result_id,
            "session_id": session_id,
            "run_id": run_id,
            "revision": int(revision),
            "disposition": disposition,
            "payload": dict(payload),
            "created_at": time.time(),
        }
        results = self._execution_results.setdefault(session_id, [])
        results[:] = [item for item in results if str(item.get("result_id")) != result_id]
        results.append(result)
        return dict(result)

    async def get_execution_state(self, session_id: str) -> dict[str, Any]:
        """Return the restored execution-lane state for one session."""
        run = self._execution_runs.get(session_id)
        pending_turns = [dict(item) for item in self._execution_pending_turns.get(session_id, [])]
        results = [dict(item) for item in self._execution_results.get(session_id, [])]
        return {
            "run": dict(run) if run is not None else None,
            "pending_turns": pending_turns,
            "accepted_results": [item for item in results if str(item.get("disposition")) == "accepted"],
            "stale_results": [item for item in results if str(item.get("disposition")) == "stale"],
        }

    async def get_workbench(self, session_id: str) -> dict[str, Any]:
        """Return the prompt-consumable workbench for a session."""
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
                    json.dumps(session.get("metadata", {}), ensure_ascii=False),
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
                        json.dumps(goal.get("metadata", {}), ensure_ascii=False),
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
                        json.dumps(entity["snapshot"], ensure_ascii=False),
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
                        json.dumps(tactic["tactic_payload"], ensure_ascii=False),
                        json.dumps(tactic["source_event_ids"], ensure_ascii=False),
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
                        root_user_message, response_anchor_turn_id, created_at, updated_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        session_id,
                        execution_run["run_id"],
                        execution_run["status"],
                        int(execution_run["revision"]),
                        execution_run.get("root_turn_id"),
                        execution_run.get("root_user_message", ""),
                        execution_run.get("response_anchor_turn_id"),
                        float(execution_run["created_at"]),
                        float(execution_run["updated_at"]),
                    ),
                )

            await db.execute("DELETE FROM l0_execution_pending_turns WHERE session_id = ?", (session_id,))
            for pending_turn in self._execution_pending_turns.get(session_id, []):
                await db.execute(
                    """
                    INSERT INTO l0_execution_pending_turns(
                        session_id, run_id, turn_id, content, revision, created_at
                    ) VALUES (?, ?, ?, ?, ?, ?)
                    """,
                    (
                        session_id,
                        pending_turn["run_id"],
                        pending_turn["turn_id"],
                        pending_turn["content"],
                        int(pending_turn["revision"]),
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
                        json.dumps(result["payload"], ensure_ascii=False),
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
            await db.executescript(
                """
                DELETE FROM l0_sessions;
                DELETE FROM l0_goal_stack;
                DELETE FROM l0_active_entities;
                DELETE FROM l0_temporary_tactics;
                DELETE FROM l0_execution_runs;
                DELETE FROM l0_execution_pending_turns;
                DELETE FROM l0_execution_results;
                """
            )
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
                    self._sessions[str(row["session_id"])] = {
                        "session_id": str(row["session_id"]),
                        "user_id": row["user_id"],
                        "runtime_agent_id": row["runtime_agent_id"],
                        "status": str(row["status"]),
                        "started_at": float(row["started_at"]),
                        "last_active_at": float(row["last_active_at"]),
                        "last_checkpoint_at": float(row["last_checkpoint_at"]) if row["last_checkpoint_at"] else None,
                        "metadata": json.loads(row["metadata"] or "{}"),
                    }

            async with db.execute("SELECT * FROM l0_goal_stack ORDER BY created_at ASC") as cursor:
                async for row in cursor:
                    session_id = str(row["session_id"])
                    self._goal_stack.setdefault(session_id, []).append(
                        {
                            "goal_id": str(row["goal_id"]),
                            "parent_goal_id": row["parent_goal_id"],
                            "goal_type": str(row["goal_type"]),
                            "description": str(row["description"]),
                            "status": str(row["status"]),
                            "priority": int(row["priority"]),
                            "created_at": float(row["created_at"]),
                            "started_at": float(row["started_at"]) if row["started_at"] else None,
                            "completed_at": float(row["completed_at"]) if row["completed_at"] else None,
                            "result_summary": row["result_summary"],
                            "metadata": json.loads(row["metadata"] or "{}"),
                        }
                    )

            async with db.execute("SELECT * FROM l0_active_entities") as cursor:
                async for row in cursor:
                    session_id = str(row["session_id"])
                    self._active_entities.setdefault(session_id, {})[
                        (str(row["entity_id"]), str(row["entity_type"]))
                    ] = {
                        "entity_id": str(row["entity_id"]),
                        "entity_type": str(row["entity_type"]),
                        "relevance_score": float(row["relevance_score"]),
                        "snapshot": json.loads(row["snapshot_json"] or "{}"),
                        "loaded_at": float(row["loaded_at"]),
                        "last_accessed_at": float(row["last_accessed_at"]),
                        "access_count": int(row["access_count"]),
                    }

            async with db.execute("SELECT * FROM l0_temporary_tactics") as cursor:
                async for row in cursor:
                    session_id = str(row["session_id"])
                    self._temporary_tactics.setdefault(session_id, {})[str(row["tactic_id"])] = {
                        "tactic_id": str(row["tactic_id"]),
                        "scope_type": str(row["scope_type"]),
                        "scope_id": str(row["scope_id"]),
                        "tactic_type": str(row["tactic_type"]),
                        "tactic_payload": json.loads(row["tactic_payload"] or "{}"),
                        "source_event_ids": json.loads(row["source_event_ids"] or "[]"),
                        "expires_at": float(row["expires_at"]) if row["expires_at"] else None,
                        "created_at": float(row["created_at"]),
                    }

            async with db.execute("SELECT * FROM l0_execution_runs") as cursor:
                async for row in cursor:
                    session_id = str(row["session_id"])
                    self._execution_runs[session_id] = {
                        "session_id": session_id,
                        "run_id": str(row["run_id"]),
                        "status": str(row["status"]),
                        "revision": int(row["revision"]),
                        "root_turn_id": str(row["root_turn_id"]) if row["root_turn_id"] is not None else None,
                        "root_user_message": str(row["root_user_message"] or ""),
                        "response_anchor_turn_id": (
                            str(row["response_anchor_turn_id"])
                            if row["response_anchor_turn_id"] is not None
                            else None
                        ),
                        "created_at": float(row["created_at"]),
                        "updated_at": float(row["updated_at"]),
                    }

            async with db.execute(
                "SELECT * FROM l0_execution_pending_turns ORDER BY created_at ASC, pending_id ASC"
            ) as cursor:
                async for row in cursor:
                    session_id = str(row["session_id"])
                    self._execution_pending_turns.setdefault(session_id, []).append(
                        {
                            "session_id": session_id,
                            "run_id": str(row["run_id"]),
                            "turn_id": str(row["turn_id"]),
                            "content": str(row["content"]),
                            "revision": int(row["revision"]),
                            "created_at": float(row["created_at"]),
                        }
                    )

            async with db.execute(
                "SELECT * FROM l0_execution_results ORDER BY created_at ASC, result_id ASC"
            ) as cursor:
                async for row in cursor:
                    session_id = str(row["session_id"])
                    self._execution_results.setdefault(session_id, []).append(
                        {
                            "result_id": str(row["result_id"]),
                            "session_id": session_id,
                            "run_id": str(row["run_id"]),
                            "revision": int(row["revision"]),
                            "disposition": str(row["disposition"]),
                            "payload": json.loads(row["payload_json"] or "{}"),
                            "created_at": float(row["created_at"]),
                        }
                    )

    async def _expire_stale_tactics(self, session_id: str) -> None:
        now = time.time()
        tactics = self._temporary_tactics.get(session_id, {})
        for tactic_id, tactic in list(tactics.items()):
            expires_at = tactic.get("expires_at")
            if expires_at is not None and float(expires_at) <= now:
                del tactics[tactic_id]


__all__ = ["L0WorkingMemoryStore"]
