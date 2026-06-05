"""Checkpoint persistence mixin for L0 working memory."""

from __future__ import annotations

import time
from typing import Any, Optional

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


__all__ = ["L0CheckpointMixin"]