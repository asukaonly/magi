"""Checkpoint persistence for L0 session attention."""

from __future__ import annotations

import asyncio
import time
from typing import Any

import aiosqlite

from ....core.sqlite import sqlite_connection_async
from .schema import clear_l0_checkpoint_tables
from .serialization import (
    encode_json,
    row_to_attention_item,
    row_to_session,
)
from .source_forgetting import filter_attention_items_by_governance


class L0CheckpointMixin:
    """Persist and restore disposable session attention."""

    checkpoint_db_path: str
    _sessions: dict[str, dict[str, Any]]
    _attention_items: dict[str, dict[str, dict[str, Any]]]
    _checkpoint_lock: asyncio.Lock

    async def checkpoint_session(self, session_id: str) -> None:
        """Persist one session attention frame."""

        scheduled = getattr(self, "_checkpoint_tasks", {}).get(session_id)
        if scheduled is not None and scheduled is not asyncio.current_task():
            getattr(self, "_cancel_scheduled_checkpoint")(session_id)
        async with self._checkpoint_lock:
            session = self._sessions.get(session_id)
            if session is None:
                return
            now = time.time()
            async with sqlite_connection_async(self.checkpoint_db_path) as db:
                await self._upsert_checkpoint_session(
                    db,
                    session=session,
                    now=now,
                )
                await self._replace_checkpoint_attention(
                    db,
                    session_id=session_id,
                )
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

    async def _replace_checkpoint_attention(
        self,
        db: aiosqlite.Connection,
        *,
        session_id: str,
    ) -> None:
        await db.execute(
            "DELETE FROM l0_attention_items WHERE session_id = ?",
            (session_id,),
        )
        for item in self._attention_items.get(session_id, {}).values():
            await db.execute(
                """
                INSERT INTO l0_attention_items(
                    item_id, session_id, kind, summary, status,
                    salience, confidence, evidence_mode,
                    source_turn_ids, source_event_ids,
                    entity_id, task_id, task_attempt,
                    first_seen_at, last_reinforced_at,
                    expires_at, supersedes_item_id, metadata
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    item["item_id"],
                    session_id,
                    item["kind"],
                    item["summary"],
                    item["status"],
                    float(item["salience"]),
                    float(item["confidence"]),
                    item["evidence_mode"],
                    encode_json(item.get("source_turn_ids", [])),
                    encode_json(item.get("source_event_ids", [])),
                    item.get("entity_id"),
                    item.get("task_id"),
                    item.get("task_attempt"),
                    float(item["first_seen_at"]),
                    float(item["last_reinforced_at"]),
                    item.get("expires_at"),
                    item.get("supersedes_item_id"),
                    encode_json(item.get("metadata", {})),
                ),
            )

    async def checkpoint_all(self) -> None:
        """Persist every active attention frame."""

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
        """Delete all L0 sessions, attention, and local barriers."""

        await self.initialize()
        async with self._checkpoint_lock:
            count = len(self._sessions)
            async with sqlite_connection_async(self.checkpoint_db_path) as db:
                await clear_l0_checkpoint_tables(db)
                await db.commit()
            for session_id in list(self._sessions):
                getattr(self, "_cancel_scheduled_checkpoint")(session_id)
            self._sessions.clear()
            self._attention_items.clear()
        return count

    async def _restore_from_checkpoint(self) -> None:
        async with self._checkpoint_lock:
            await self._restore_checkpoint_under_lock()

    async def _restore_checkpoint_under_lock(self) -> None:
        async with sqlite_connection_async(self.checkpoint_db_path) as db:
            db.row_factory = aiosqlite.Row
            await self._delete_malformed_checkpoint_rows(db)
            async with db.execute("SELECT * FROM l0_sessions") as cursor:
                session_rows = await cursor.fetchall()

            now = time.time()
            await db.execute(
                """
                DELETE FROM l0_attention_items
                WHERE expires_at IS NOT NULL AND expires_at <= ?
                """,
                (now,),
            )
            async with db.execute(
                "SELECT DISTINCT session_id FROM l0_attention_items"
            ) as cursor:
                sessions_with_live_attention = {
                    str(row["session_id"])
                    for row in await cursor.fetchall()
                }
            idle_cutoff = now - float(
                getattr(self, "session_timeout_seconds", 3600)
            )
            disposable_rows = sorted(
                (
                    row
                    for row in session_rows
                    if str(row["status"] or "") == "active"
                    and (
                        float(row["last_active_at"] or 0.0) >= idle_cutoff
                        or str(row["session_id"]) in sessions_with_live_attention
                    )
                ),
                key=lambda row: float(row["last_active_at"] or 0.0),
                reverse=True,
            )
            capacity = max(
                0,
                int(getattr(self, "max_concurrent_sessions", 64)),
            )
            selected_rows = disposable_rows[:capacity]
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
            await db.commit()

            for row in selected_rows:
                session = row_to_session(row)
                session["status"] = "active"
                session_id = str(session["session_id"])
                self._sessions[session_id] = session
                self._attention_items.setdefault(session_id, {})

            async with db.execute(
                "SELECT * FROM l0_attention_items"
            ) as cursor:
                rows = await cursor.fetchall()
            restored_items: list[tuple[str, dict[str, Any]]] = []
            for row in rows:
                session_id = str(row["session_id"])
                if session_id not in restored_session_ids:
                    continue
                try:
                    restored_items.append(
                        (session_id, row_to_attention_item(row))
                    )
                except (TypeError, ValueError):
                    await db.execute(
                        "DELETE FROM l0_attention_items WHERE item_id = ?",
                        (str(row["item_id"]),),
                    )
            governed = await filter_attention_items_by_governance(
                db,
                (item for _, item in restored_items),
            )
            governed_ids = {str(item["item_id"]) for item in governed}
            for session_id, item in restored_items:
                item_id = str(item["item_id"])
                if item_id in governed_ids:
                    self._attention_items.setdefault(session_id, {})[
                        item_id
                    ] = item
            await db.commit()

    @staticmethod
    async def _delete_checkpoint_sessions(
        db: aiosqlite.Connection,
        session_ids: set[str],
    ) -> None:
        params = [(session_id,) for session_id in sorted(session_ids)]
        for table in ("l0_attention_items", "l0_sessions"):
            await db.executemany(
                f"DELETE FROM {table} WHERE session_id = ?",
                params,
            )

    async def _delete_malformed_checkpoint_rows(
        self,
        db: aiosqlite.Connection,
    ) -> None:
        """Discard malformed JSON rows without failing the remaining restore."""

        async with db.execute(
            """
            SELECT session_id
            FROM l0_sessions
            WHERE CASE
                WHEN json_valid(metadata) THEN json_type(metadata) != 'object'
                ELSE 1
            END
            """
        ) as cursor:
            malformed_session_ids = {
                str(row["session_id"])
                for row in await cursor.fetchall()
            }
        if malformed_session_ids:
            await self._delete_checkpoint_sessions(
                db,
                malformed_session_ids,
            )

        await db.execute(
            """
            DELETE FROM l0_attention_items
            WHERE CASE
                WHEN json_valid(source_turn_ids)
                THEN json_type(source_turn_ids) != 'array'
                ELSE 1
            END
            OR CASE
                WHEN json_valid(source_event_ids)
                THEN json_type(source_event_ids) != 'array'
                ELSE 1
            END
            OR CASE
                WHEN json_valid(metadata)
                THEN json_type(metadata) != 'object'
                ELSE 1
            END
            """
        )
        await db.commit()


__all__ = ["L0CheckpointMixin"]
