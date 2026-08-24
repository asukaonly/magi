"""Persistence for canonical agent run manifests and journal events."""

from __future__ import annotations

import json
from typing import Any

import aiosqlite


class RunJournalPersistenceMixin:
    """Store append-only run events next to execution observability data."""

    async def _execute_hot_write(self, *, operation: str, write: Any) -> Any:
        raise NotImplementedError

    async def _fetchone(self, sql: str, params: tuple[Any, ...]) -> aiosqlite.Row | None:
        raise NotImplementedError

    async def upsert_run_manifest(self, manifest: dict[str, Any]) -> None:
        payload = json.dumps(manifest, ensure_ascii=False, sort_keys=True, default=str)
        await self._execute_hot_write(
            operation="upsert_run_manifest",
            write=lambda db: db.execute(
                """
                INSERT INTO agent_run_manifests (
                    run_id, turn_id, session_id, user_id, manifest_json,
                    created_at_ms, updated_at_ms
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(run_id) DO UPDATE SET
                    turn_id = excluded.turn_id,
                    session_id = excluded.session_id,
                    user_id = excluded.user_id,
                    manifest_json = excluded.manifest_json,
                    updated_at_ms = excluded.updated_at_ms
                """,
                (
                    str(manifest["run_id"]),
                    manifest.get("turn_id"),
                    manifest.get("session_id"),
                    manifest.get("user_id"),
                    payload,
                    int(manifest.get("created_at_ms") or 0),
                    int(manifest.get("created_at_ms") or 0),
                ),
            ),
        )

    async def append_run_event(self, event: dict[str, Any]) -> None:
        await self._execute_hot_write(
            operation="append_run_event",
            write=lambda db: db.execute(
                """
                INSERT INTO agent_run_events (
                    event_id, run_id, sequence, turn_id, session_id, user_id,
                    event_type, step_index, payload_json, created_at_ms
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    str(event["event_id"]),
                    str(event["run_id"]),
                    int(event["sequence"]),
                    event.get("turn_id"),
                    event.get("session_id"),
                    event.get("user_id"),
                    str(event["event_type"]),
                    event.get("step_index"),
                    json.dumps(
                        event.get("payload") or {},
                        ensure_ascii=False,
                        sort_keys=True,
                        default=str,
                    ),
                    int(event["created_at_ms"]),
                ),
            ),
        )

    async def get_run_manifest(self, run_id: str) -> dict[str, Any] | None:
        row = await self._fetchone(
            "SELECT manifest_json FROM agent_run_manifests WHERE run_id = ?",
            (run_id,),
        )
        if row is None:
            return None
        value = json.loads(str(row["manifest_json"]))
        return dict(value) if isinstance(value, dict) else None

    async def list_run_events(self, run_id: str) -> list[dict[str, Any]]:
        from ..core.sqlite import sqlite_connection_async

        async with sqlite_connection_async(self.db_path, profile="hot_write") as db:
            db.row_factory = aiosqlite.Row
            cursor = await db.execute(
                """
                SELECT event_id, run_id, sequence, turn_id, session_id, user_id,
                       event_type, step_index, payload_json, created_at_ms
                FROM agent_run_events
                WHERE run_id = ?
                ORDER BY sequence ASC
                """,
                (run_id,),
            )
            rows = await cursor.fetchall()
        return [
            {
                "event_id": str(row["event_id"]),
                "run_id": str(row["run_id"]),
                "sequence": int(row["sequence"]),
                "turn_id": row["turn_id"],
                "session_id": row["session_id"],
                "user_id": row["user_id"],
                "event_type": str(row["event_type"]),
                "step_index": row["step_index"],
                "payload": json.loads(str(row["payload_json"] or "{}")),
                "created_at_ms": int(row["created_at_ms"]),
            }
            for row in rows
        ]


__all__ = ["RunJournalPersistenceMixin"]
