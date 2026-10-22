"""MySQL outbox admission, uncertain attempts and proactive delivery history."""

from __future__ import annotations

from typing import Any
from uuid import uuid4
from sqlalchemy import text

from ...db.mysql import MysqlDatabase
from ...db.identities import identity_key
from ..contracts import OutreachIntentConflictError, OutboxEnqueueResult
from ..identity import normalize_channel_scope


class MysqlOutreachOutboxRepository:
    def __init__(self, database: MysqlDatabase) -> None:
        self._database = database

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
        correlation = str(correlation_id or "").strip()
        scope = normalize_channel_scope(channel_scope)
        fingerprint = str(intent_fingerprint or "").strip()
        if not correlation or not fingerprint:
            raise ValueError("Outreach correlation and fingerprint are required")
        key, token = identity_key(correlation, scope), uuid4().hex
        async with self._database.transaction() as db:
            # The unique key serializes concurrent admissions. A private creation
            # token distinguishes insertion without depending on driver rowcount.
            await db.execute(
                text("""INSERT INTO outreach_outbox
                (identity_key,creation_token,correlation_id,channel_scope,intent_fingerprint,intent_json,release_at_ms,status,created_at_ms)
                VALUES (:key,:token,:correlation,:scope,:fingerprint,:payload,:release,'pending',:created)
                ON DUPLICATE KEY UPDATE identity_key=identity_key"""),
                {
                    "key": key,
                    "token": token,
                    "correlation": correlation,
                    "scope": scope,
                    "fingerprint": fingerprint,
                    "payload": intent_json,
                    "release": release_at_ms,
                    "created": created_at_ms,
                },
            )
            row = (
                (
                    await db.execute(
                        text("SELECT * FROM outreach_outbox WHERE identity_key=:key FOR UPDATE"),
                        {"key": key},
                    )
                )
                .mappings()
                .one()
            )
            if row["intent_fingerprint"] != fingerprint or (
                row["status"] == "pending" and row["intent_json"] != intent_json
            ):
                raise OutreachIntentConflictError(
                    "Outreach correlation ID was reused with different content"
                )
            return OutboxEnqueueResult(
                int(row["id"]), str(row["status"]), row["creation_token"] == token
            )

    async def list_due(self, *, now_ms: int) -> list[dict[str, Any]]:
        async with self._database.transaction() as db:
            rows = (
                (
                    await db.execute(
                        text("""SELECT id,correlation_id,channel_scope,intent_fingerprint,intent_json,release_at_ms
                FROM outreach_outbox WHERE status='pending' AND release_at_ms<=:now ORDER BY id"""),
                        {"now": now_ms},
                    )
                )
                .mappings()
                .all()
            )
        return [dict(row) for row in rows]

    async def mark_status(self, row_id: int, status: str) -> None:
        allowed = {
            "delivered": ("pending", "attempting"),
            "dropped": ("pending",),
            "uncertain": ("attempting",),
        }
        sources = allowed.get(status)
        if sources is None:
            raise ValueError("Outreach outbox status transition is not allowed")
        placeholders = ",".join(f":source{i}" for i in range(len(sources)))
        parameters = {
            "row_id": row_id,
            "status": status,
            **{f"source{i}": value for i, value in enumerate(sources)},
        }
        async with self._database.transaction() as db:
            await db.execute(
                text(
                    f"UPDATE outreach_outbox SET status=:status,intent_json='{{}}' WHERE id=:row_id AND status IN ({placeholders})"
                ),
                parameters,
            )

    async def begin_delivery_attempt(self, row_id: int) -> bool:
        async with self._database.transaction() as db:
            result = await db.execute(
                text(
                    "UPDATE outreach_outbox SET status='attempting',intent_json='{}' WHERE id=:row_id AND status='pending'"
                ),
                {"row_id": row_id},
            )
            return result.rowcount == 1

    async def restore_pending_after_unattempted_delivery(
        self, row_id: int, *, intent_json: str
    ) -> bool:
        async with self._database.transaction() as db:
            result = await db.execute(
                text(
                    "UPDATE outreach_outbox SET status='pending',intent_json=:payload WHERE id=:row_id AND status='attempting'"
                ),
                {"row_id": row_id, "payload": intent_json},
            )
            return result.rowcount == 1

    async def reschedule(self, row_id: int, *, release_at_ms: int) -> None:
        async with self._database.transaction() as db:
            await db.execute(
                text(
                    "UPDATE outreach_outbox SET release_at_ms=:release WHERE id=:row_id AND status='pending'"
                ),
                {"row_id": row_id, "release": release_at_ms},
            )


class MysqlOutreachDeliveryLogRepository:
    def __init__(self, database: MysqlDatabase) -> None:
        self._database = database

    async def record(
        self, *, correlation_id: str, user_id: str, channel_type: str, delivered_at_ms: int
    ) -> None:
        scope = normalize_channel_scope(channel_type)
        async with self._database.transaction() as db:
            await db.execute(
                text("""INSERT INTO outreach_delivery_log
                (identity_key,user_key,correlation_id,user_id,channel_type,delivered_at_ms)
                VALUES (:key,:user_key,:correlation,:user,:channel,:delivered)
                ON DUPLICATE KEY UPDATE identity_key=identity_key"""),
                {
                    "key": identity_key(correlation_id, scope),
                    "user_key": identity_key(user_id),
                    "correlation": correlation_id,
                    "user": user_id,
                    "channel": scope,
                    "delivered": delivered_at_ms,
                },
            )

    async def was_delivered(self, correlation_id: str, channel_type: str) -> bool:
        async with self._database.transaction() as db:
            return (
                await db.execute(
                    text("SELECT 1 FROM outreach_delivery_log WHERE identity_key=:key"),
                    {"key": identity_key(correlation_id, normalize_channel_scope(channel_type))},
                )
            ).first() is not None

    async def count_for_user_since(self, user_id: str, since_ms: int) -> int:
        async with self._database.transaction() as db:
            return int(
                (
                    await db.execute(
                        text(
                            "SELECT COUNT(*) FROM outreach_delivery_log WHERE user_key=:user AND delivered_at_ms>=:since"
                        ),
                        {"user": identity_key(user_id), "since": since_ms},
                    )
                ).scalar_one()
            )
