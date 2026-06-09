"""SQLite-backed stores for the outreach outbox and delivery log (channels DB)."""
from __future__ import annotations

import asyncio
import sqlite3
from typing import Any


class _SqliteBase:
    def __init__(self, *, db_path: str) -> None:
        self._db_path = db_path

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self._db_path)
        conn.row_factory = sqlite3.Row
        return conn


class OutreachOutboxStore(_SqliteBase):
    async def enqueue(self, *, intent_json: str, release_at_ms: int, created_at_ms: int) -> int:
        def _run() -> int:
            conn = self._connect()
            try:
                cur = conn.execute(
                    "INSERT INTO outreach_outbox (intent_json, release_at_ms, status, created_at_ms) "
                    "VALUES (?, ?, 'pending', ?)",
                    (intent_json, int(release_at_ms), int(created_at_ms)),
                )
                conn.commit()
                return int(cur.lastrowid)
            finally:
                conn.close()
        return await asyncio.to_thread(_run)

    async def list_due(self, *, now_ms: int) -> list[dict[str, Any]]:
        def _run() -> list[dict[str, Any]]:
            conn = self._connect()
            try:
                rows = conn.execute(
                    "SELECT id, intent_json, release_at_ms FROM outreach_outbox "
                    "WHERE status = 'pending' AND release_at_ms <= ? ORDER BY id ASC",
                    (int(now_ms),),
                ).fetchall()
                return [dict(r) for r in rows]
            finally:
                conn.close()
        return await asyncio.to_thread(_run)

    async def mark_status(self, row_id: int, status: str) -> None:
        def _run() -> None:
            conn = self._connect()
            try:
                conn.execute(
                    "UPDATE outreach_outbox SET status = ? WHERE id = ?",
                    (status, int(row_id)),
                )
                conn.commit()
            finally:
                conn.close()
        await asyncio.to_thread(_run)


class OutreachDeliveryLogStore(_SqliteBase):
    async def record(self, *, correlation_id: str, user_id: str, channel_type: str, delivered_at_ms: int) -> None:
        def _run() -> None:
            conn = self._connect()
            try:
                conn.execute(
                    "INSERT OR IGNORE INTO outreach_delivery_log "
                    "(correlation_id, user_id, channel_type, delivered_at_ms) VALUES (?, ?, ?, ?)",
                    (correlation_id, user_id, channel_type, int(delivered_at_ms)),
                )
                conn.commit()
            finally:
                conn.close()
        await asyncio.to_thread(_run)

    async def was_delivered(self, correlation_id: str) -> bool:
        def _run() -> bool:
            conn = self._connect()
            try:
                row = conn.execute(
                    "SELECT 1 FROM outreach_delivery_log WHERE correlation_id = ? LIMIT 1",
                    (correlation_id,),
                ).fetchone()
                return row is not None
            finally:
                conn.close()
        return await asyncio.to_thread(_run)

    async def count_for_user_since(self, user_id: str, since_ms: int) -> int:
        def _run() -> int:
            conn = self._connect()
            try:
                row = conn.execute(
                    "SELECT COUNT(*) FROM outreach_delivery_log WHERE user_id = ? AND delivered_at_ms >= ?",
                    (user_id, int(since_ms)),
                ).fetchone()
                return int(row[0])
            finally:
                conn.close()
        return await asyncio.to_thread(_run)
