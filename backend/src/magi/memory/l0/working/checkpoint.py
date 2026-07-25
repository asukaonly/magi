"""Checkpoint persistence mixin for L0 working memory."""

from __future__ import annotations

import asyncio
import time
from typing import Any

import aiosqlite

from ....core.sqlite import sqlite_connection_async
from .schema import clear_l0_checkpoint_tables
from .serialization import (
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
from .source_forgetting import (
    filter_active_entities_by_governance,
    forgotten_tactic_source_references,
    tactic_source_references,
)


class L0CheckpointMixin:
    """Persist and restore L0 working-memory checkpoint state."""

    checkpoint_db_path: str
    _sessions: dict[str, dict[str, Any]]
    _goal_stack: dict[str, list[dict[str, Any]]]
    _active_entities: dict[str, dict[tuple[str, str], dict[str, Any]]]
    _temporary_tactics: dict[str, dict[str, dict[str, Any]]]
    _execution_runs: dict[str, dict[str, Any]]
    _execution_pending_turns: dict[str, list[dict[str, Any]]]
    _execution_results: dict[str, list[dict[str, Any]]]
    _checkpoint_lock: asyncio.Lock

    async def checkpoint_session(self, session_id: str) -> None:
        """Persist a single session workbench into the checkpoint database."""
        scheduled = getattr(self, "_checkpoint_tasks", {}).get(session_id)
        if scheduled is not None and scheduled is not asyncio.current_task():
            getattr(self, "_cancel_scheduled_checkpoint")(session_id)
        async with self._checkpoint_lock:
            session = self._sessions.get(session_id)
            if session is None:
                return
            now = time.time()

            async with sqlite_connection_async(self.checkpoint_db_path) as db:
                await self._upsert_checkpoint_session(db, session=session, now=now)
                await self._replace_checkpoint_goals(db, session_id=session_id)
                await self._replace_checkpoint_active_entities(db, session_id=session_id)
                await self._replace_checkpoint_tactics(db, session_id=session_id)
                await self._replace_checkpoint_execution_run(db, session_id=session_id)
                await self._replace_checkpoint_pending_turns(db, session_id=session_id)
                await self._replace_checkpoint_execution_results(db, session_id=session_id)
                await db.commit()
            session["last_checkpoint_at"] = now

    async def _upsert_checkpoint_session(
        self,
        db: aiosqlite.Connection,
        *,
        session: dict[str, Any],
        now: float,
    ) -> None:
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

    async def _replace_checkpoint_goals(
        self,
        db: aiosqlite.Connection,
        *,
        session_id: str,
    ) -> None:
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

    async def _replace_checkpoint_active_entities(
        self,
        db: aiosqlite.Connection,
        *,
        session_id: str,
    ) -> None:
        await db.execute("DELETE FROM l0_active_entities WHERE session_id = ?", (session_id,))
        for entity in self._active_entities.get(session_id, {}).values():
            await db.execute(
                """
                INSERT INTO l0_active_entities(
                    session_id, entity_id, entity_type, relevance_score,
                    snapshot_json, source_event_ids, loaded_at,
                    last_accessed_at, access_count
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    session_id,
                    entity["entity_id"],
                    entity["entity_type"],
                    float(entity["relevance_score"]),
                    encode_json(entity["snapshot"]),
                    encode_json(entity.get("source_event_ids", [])),
                    float(entity["loaded_at"]),
                    float(entity["last_accessed_at"]),
                    int(entity["access_count"]),
                ),
            )

    async def _replace_checkpoint_tactics(
        self,
        db: aiosqlite.Connection,
        *,
        session_id: str,
    ) -> None:
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

    async def _replace_checkpoint_execution_run(
        self,
        db: aiosqlite.Connection,
        *,
        session_id: str,
    ) -> None:
        await db.execute("DELETE FROM l0_execution_runs WHERE session_id = ?", (session_id,))
        execution_run = self._execution_runs.get(session_id)
        if execution_run is None:
            return
        await db.execute(
            """
            INSERT INTO l0_execution_runs(
                session_id, run_id, status, revision, root_turn_id,
                root_user_message, response_anchor_turn_id, cancel_requested_at,
                cancel_reason, cancel_requested_by, cancel_anchor_turn_id,
                trigger_json, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
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
                (
                    encode_json(execution_run["trigger"])
                    if execution_run.get("trigger") is not None
                    else None
                ),
                float(execution_run["created_at"]),
                float(execution_run["updated_at"]),
            ),
        )

    async def _replace_checkpoint_pending_turns(
        self,
        db: aiosqlite.Connection,
        *,
        session_id: str,
    ) -> None:
        await db.execute(
            "DELETE FROM l0_execution_pending_turns WHERE session_id = ?",
            (session_id,),
        )
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

    async def _replace_checkpoint_execution_results(
        self,
        db: aiosqlite.Connection,
        *,
        session_id: str,
    ) -> None:
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

    async def checkpoint_all(self) -> None:
        """Persist every active session."""
        first_error: Exception | None = None
        for session_id in list(self._sessions):
            try:
                await self.checkpoint_session(session_id)
            except Exception as exc:
                if first_error is None:
                    first_error = exc
        if first_error is not None:
            raise first_error

    async def clear(self) -> int:
        """Delete all L0 sessions from memory and checkpoints."""
        await self.initialize()
        async with self._checkpoint_lock:
            count = len(self._sessions)
            async with sqlite_connection_async(self.checkpoint_db_path) as db:
                await clear_l0_checkpoint_tables(db)
                await db.commit()

            for session_id in list(self._sessions):
                getattr(self, "_cancel_scheduled_checkpoint")(session_id)
            self._sessions.clear()
            self._goal_stack.clear()
            self._active_entities.clear()
            self._temporary_tactics.clear()
            self._execution_runs.clear()
            self._execution_pending_turns.clear()
            self._execution_results.clear()

        return count

    async def _restore_from_checkpoint(self) -> None:
        async with self._checkpoint_lock:
            await self._restore_checkpoint_under_lock()

    async def _restore_checkpoint_under_lock(self) -> None:
        async with sqlite_connection_async(self.checkpoint_db_path) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute(
                "SELECT DISTINCT session_id FROM l0_execution_runs"
            ) as cursor:
                execution_session_ids = {
                    str(row["session_id"]) for row in await cursor.fetchall()
                }
            async with db.execute("SELECT * FROM l0_sessions") as cursor:
                session_rows = await cursor.fetchall()

            now = time.time()
            idle_cutoff = now - float(getattr(self, "session_timeout_seconds", 3600))
            protected_rows = [
                row
                for row in session_rows
                if str(row["session_id"]) in execution_session_ids
            ]
            disposable_rows = sorted(
                (
                    row
                    for row in session_rows
                    if str(row["session_id"]) not in execution_session_ids
                    and str(row["status"] or "") == "active"
                    and float(row["last_active_at"] or 0.0) >= idle_cutoff
                ),
                key=lambda row: float(row["last_active_at"] or 0.0),
                reverse=True,
            )
            disposable_capacity = max(
                0,
                int(getattr(self, "max_concurrent_sessions", 64))
                - len(protected_rows),
            )
            selected_rows = [*protected_rows, *disposable_rows[:disposable_capacity]]
            restored_session_ids = {
                str(row["session_id"]) for row in selected_rows
            }
            rejected_session_ids = {
                str(row["session_id"]) for row in session_rows
            } - restored_session_ids
            if rejected_session_ids:
                await self._delete_checkpoint_sessions(
                    db,
                    rejected_session_ids,
                )
            if restored_session_ids:
                await db.executemany(
                    "UPDATE l0_sessions SET status = 'active' WHERE session_id = ?",
                    [(session_id,) for session_id in sorted(restored_session_ids)],
                )
            await db.execute(
                """
                DELETE FROM l0_goal_stack
                WHERE status IN ('completed', 'failed', 'cancelled')
                """
            )
            await db.execute(
                """
                DELETE FROM l0_temporary_tactics
                WHERE expires_at IS NOT NULL AND expires_at <= ?
                """,
                (now,),
            )
            await db.commit()

            for row in selected_rows:
                session = row_to_session(row)
                session["status"] = "active"
                self._sessions[str(session["session_id"])] = session
            for session_id in restored_session_ids:
                self._goal_stack.setdefault(session_id, [])
                self._active_entities.setdefault(session_id, {})
                self._temporary_tactics.setdefault(session_id, {})

            async with db.execute("SELECT * FROM l0_goal_stack ORDER BY created_at ASC") as cursor:
                async for row in cursor:
                    session_id = str(row["session_id"])
                    if session_id not in restored_session_ids:
                        continue
                    self._goal_stack.setdefault(session_id, []).append(row_to_goal(row))

            async with db.execute("SELECT * FROM l0_active_entities") as cursor:
                active_entity_rows = await cursor.fetchall()
            restored_entities = [
                (str(row["session_id"]), active_entity_key(row), row_to_active_entity(row))
                for row in active_entity_rows
            ]
            governed_entities = await filter_active_entities_by_governance(
                db,
                (entity for _, _, entity in restored_entities),
            )
            governed_object_ids = {id(entity) for entity in governed_entities}
            for session_id, key, entity in restored_entities:
                if session_id not in restored_session_ids:
                    continue
                if id(entity) not in governed_object_ids:
                    continue
                self._active_entities.setdefault(session_id, {})[key] = entity

            async with db.execute("SELECT * FROM l0_temporary_tactics") as cursor:
                tactic_rows = await cursor.fetchall()
            tactics = [(str(row["session_id"]), row_to_tactic(row)) for row in tactic_rows]
            forgotten_references = await forgotten_tactic_source_references(
                db,
                {
                    reference
                    for _, tactic in tactics
                    for reference in tactic_source_references(tactic)
                },
            )
            for session_id, tactic in tactics:
                if session_id not in restored_session_ids:
                    continue
                if tactic_source_references(tactic) & forgotten_references:
                    continue
                self._temporary_tactics.setdefault(session_id, {})[
                    str(tactic["tactic_id"])
                ] = tactic

            async with db.execute("SELECT * FROM l0_execution_runs") as cursor:
                async for row in cursor:
                    execution_run = row_to_execution_run(row)
                    session_id = str(execution_run["session_id"])
                    if session_id in restored_session_ids:
                        self._execution_runs[session_id] = execution_run

            async with db.execute(
                "SELECT * FROM l0_execution_pending_turns ORDER BY created_at ASC, pending_id ASC"
            ) as cursor:
                async for row in cursor:
                    pending_turn = row_to_pending_turn(row)
                    if str(pending_turn["session_id"]) not in restored_session_ids:
                        continue
                    self._execution_pending_turns.setdefault(
                        str(pending_turn["session_id"]), []
                    ).append(pending_turn)

            async with db.execute(
                "SELECT * FROM l0_execution_results ORDER BY created_at ASC, result_id ASC"
            ) as cursor:
                async for row in cursor:
                    result = row_to_execution_result(row)
                    if str(result["session_id"]) not in restored_session_ids:
                        continue
                    self._execution_results.setdefault(str(result["session_id"]), []).append(result)

    @staticmethod
    async def _delete_checkpoint_sessions(
        db: aiosqlite.Connection,
        session_ids: set[str],
    ) -> None:
        params = [(session_id,) for session_id in sorted(session_ids)]
        for table in (
            "l0_goal_stack",
            "l0_active_entities",
            "l0_temporary_tactics",
            "l0_execution_runs",
            "l0_execution_pending_turns",
            "l0_execution_results",
            "l0_sessions",
        ):
            await db.executemany(
                f"DELETE FROM {table} WHERE session_id = ?",
                params,
            )


__all__ = ["L0CheckpointMixin"]
