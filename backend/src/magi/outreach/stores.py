"""SQLite-backed stores for the outreach outbox and delivery log (channels DB)."""
from __future__ import annotations

import asyncio
import sqlite3
from dataclasses import dataclass
from typing import Any

from .contracts import OutreachIntentConflictError
from .identity import normalize_channel_scope


@dataclass(frozen=True, slots=True)
class OutboxEnqueueResult:
    """Result of atomically creating or reusing one logical outbox row."""

    row_id: int
    status: str
    created: bool


class _SqliteBase:
    def __init__(self, *, db_path: str) -> None:
        self._db_path = db_path

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self._db_path)
        conn.row_factory = sqlite3.Row
        return conn


class OutreachOutboxStore(_SqliteBase):
    async def enqueue(
        self,
        *,
        correlation_id: str,
        channel_scope: str,
        intent_fingerprint: str,
        intent_json: str,
        release_at_ms: int,
        created_at_ms: int,
    ) -> OutboxEnqueueResult:
        """Create one row per logical intent and channel, or reuse it exactly."""

        normalized_correlation_id = str(correlation_id or "").strip()
        normalized_channel_scope = normalize_channel_scope(channel_scope)
        normalized_fingerprint = str(intent_fingerprint or "").strip()
        if not normalized_correlation_id:
            raise ValueError("Outreach correlation ID is required")
        if not normalized_fingerprint:
            raise ValueError("Outreach intent fingerprint is required")

        def _run() -> OutboxEnqueueResult:
            conn = self._connect()
            try:
                conn.execute("BEGIN IMMEDIATE")
                existing = conn.execute(
                    """
                    SELECT id, intent_json, intent_fingerprint, status
                    FROM outreach_outbox
                    WHERE correlation_id = ? AND channel_scope = ?
                    """,
                    (
                        normalized_correlation_id,
                        normalized_channel_scope,
                    ),
                ).fetchone()
                if existing is not None:
                    if (
                        str(existing["intent_fingerprint"]) != normalized_fingerprint
                        or (
                            str(existing["status"]) == "pending"
                            and str(existing["intent_json"]) != intent_json
                        )
                    ):
                        raise OutreachIntentConflictError(
                            "Outreach correlation ID was reused with different content "
                            f"for channel {normalized_channel_scope!r}"
                        )
                    conn.commit()
                    return OutboxEnqueueResult(
                        row_id=int(existing["id"]),
                        status=str(existing["status"]),
                        created=False,
                    )
                cur = conn.execute(
                    """
                    INSERT INTO outreach_outbox (
                        correlation_id,
                        channel_scope,
                        intent_fingerprint,
                        intent_json,
                        release_at_ms,
                        status,
                        created_at_ms
                    )
                    VALUES (?, ?, ?, ?, ?, 'pending', ?)
                    """,
                    (
                        normalized_correlation_id,
                        normalized_channel_scope,
                        normalized_fingerprint,
                        intent_json,
                        int(release_at_ms),
                        int(created_at_ms),
                    ),
                )
                conn.commit()
                return OutboxEnqueueResult(
                    row_id=int(cur.lastrowid),
                    status="pending",
                    created=True,
                )
            except Exception:
                conn.rollback()
                raise
            finally:
                conn.close()
        return await asyncio.to_thread(_run)

    async def list_due(self, *, now_ms: int) -> list[dict[str, Any]]:
        def _run() -> list[dict[str, Any]]:
            conn = self._connect()
            try:
                rows = conn.execute(
                    "SELECT id, correlation_id, channel_scope, intent_fingerprint, "
                    "intent_json, release_at_ms FROM outreach_outbox "
                    "WHERE status = 'pending' AND release_at_ms <= ? ORDER BY id ASC",
                    (int(now_ms),),
                ).fetchall()
                return [dict(r) for r in rows]
            finally:
                conn.close()
        return await asyncio.to_thread(_run)

    async def mark_status(self, row_id: int, status: str) -> None:
        allowed_sources = {
            "delivered": ("pending", "attempting"),
            "dropped": ("pending",),
            "uncertain": ("attempting",),
        }
        source_statuses = allowed_sources.get(status)
        if source_statuses is None:
            raise ValueError("Outreach outbox status transition is not allowed")
        placeholders = ", ".join("?" for _ in source_statuses)

        def _run() -> None:
            conn = self._connect()
            try:
                conn.execute(
                    "UPDATE outreach_outbox SET status = ?, intent_json = '{}' "
                    f"WHERE id = ? AND status IN ({placeholders})",
                    (status, int(row_id), *source_statuses),
                )
                conn.commit()
            finally:
                conn.close()
        await asyncio.to_thread(_run)

    async def begin_delivery_attempt(self, row_id: int) -> bool:
        """Claim one pending row before invoking an external channel."""

        def _run() -> bool:
            conn = self._connect()
            try:
                cursor = conn.execute(
                    "UPDATE outreach_outbox "
                    "SET status = 'attempting', intent_json = '{}' "
                    "WHERE id = ? AND status = 'pending'",
                    (int(row_id),),
                )
                conn.commit()
                return int(cursor.rowcount or 0) == 1
            finally:
                conn.close()

        return await asyncio.to_thread(_run)

    async def restore_pending_after_unattempted_delivery(
        self,
        row_id: int,
        *,
        intent_json: str,
    ) -> bool:
        """Retry only when the delivery router confirms no channel was called."""

        def _run() -> bool:
            conn = self._connect()
            try:
                cursor = conn.execute(
                    "UPDATE outreach_outbox "
                    "SET status = 'pending', intent_json = ? "
                    "WHERE id = ? AND status = 'attempting'",
                    (intent_json, int(row_id)),
                )
                conn.commit()
                return int(cursor.rowcount or 0) == 1
            finally:
                conn.close()

        return await asyncio.to_thread(_run)

    async def reschedule(self, row_id: int, *, release_at_ms: int) -> None:
        """Move one pending row to its next governor-provided release time."""

        def _run() -> None:
            conn = self._connect()
            try:
                conn.execute(
                    "UPDATE outreach_outbox SET release_at_ms = ? "
                    "WHERE id = ? AND status = 'pending'",
                    (int(release_at_ms), int(row_id)),
                )
                conn.commit()
            finally:
                conn.close()

        await asyncio.to_thread(_run)


class OutreachDeliveryLogStore(_SqliteBase):
    async def record(self, *, correlation_id: str, user_id: str, channel_type: str, delivered_at_ms: int) -> None:
        channel_scope = normalize_channel_scope(channel_type)

        def _run() -> None:
            conn = self._connect()
            try:
                conn.execute(
                    "INSERT OR IGNORE INTO outreach_delivery_log "
                    "(correlation_id, user_id, channel_type, delivered_at_ms) VALUES (?, ?, ?, ?)",
                    (correlation_id, user_id, channel_scope, int(delivered_at_ms)),
                )
                conn.commit()
            finally:
                conn.close()
        await asyncio.to_thread(_run)

    async def was_delivered(self, correlation_id: str, channel_type: str) -> bool:
        channel_scope = normalize_channel_scope(channel_type)

        def _run() -> bool:
            conn = self._connect()
            try:
                row = conn.execute(
                    "SELECT 1 FROM outreach_delivery_log "
                    "WHERE correlation_id = ? AND channel_type = ? LIMIT 1",
                    (correlation_id, channel_scope),
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
