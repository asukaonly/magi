"""Durable assistant-memory projection outbox persistence."""

from __future__ import annotations

import time
import uuid
from typing import Protocol, cast

import aiosqlite

from ...core.sqlite import sqlite_connection_async
from ..contracts import (
    ChatAssistantMemoryOutboxRecord,
    ChatAssistantMemoryProjection,
)


class _AssistantMemoryOutboxHost(Protocol):
    db_path: str

    async def initialize(self) -> None: ...

    def _notify_assistant_memory_outbox(self) -> None: ...


class ChatAssistantMemoryOutboxPersistenceMixin:
    """Persist, lease, retry, and cancel assistant-memory projection work."""

    async def claim_assistant_memory_projections(
        self,
        *,
        limit: int = 10,
        lease_seconds: float = 60.0,
        now_ms: int | None = None,
    ) -> list[ChatAssistantMemoryOutboxRecord]:
        """Claim a bounded due page and recover expired leases atomically."""

        host = cast(_AssistantMemoryOutboxHost, self)
        await host.initialize()
        normalized_now_ms = int(now_ms if now_ms is not None else time.time() * 1000)
        page_size = max(1, min(int(limit), 100))
        lease_ms = max(1_000, int(float(lease_seconds) * 1000))
        lease_token = uuid.uuid4().hex
        lease_expires_at_ms = normalized_now_ms + lease_ms
        async with sqlite_connection_async(host.db_path, profile="mixed") as db:
            db.row_factory = aiosqlite.Row
            await db.execute("BEGIN IMMEDIATE")
            try:
                await db.execute(
                    """
                    UPDATE chat_assistant_memory_outbox
                    SET state = 'pending',
                        lease_token = NULL,
                        lease_expires_at_ms = NULL,
                        next_attempt_at_ms = MIN(next_attempt_at_ms, ?),
                        last_error = 'CLAIM_LEASE_EXPIRED',
                        updated_at_ms = ?
                    WHERE state = 'claimed'
                      AND COALESCE(lease_expires_at_ms, 0) <= ?
                    """,
                    (normalized_now_ms, normalized_now_ms, normalized_now_ms),
                )
                cursor = await db.execute(
                    """
                    SELECT canonical_message_id
                    FROM chat_assistant_memory_outbox
                    WHERE state = 'pending'
                      AND next_attempt_at_ms <= ?
                    ORDER BY created_at_ms, canonical_message_id
                    LIMIT ?
                    """,
                    (normalized_now_ms, page_size),
                )
                message_ids = [str(row[0]) for row in await cursor.fetchall()]
                if not message_ids:
                    await db.commit()
                    return []
                placeholders = ", ".join("?" for _ in message_ids)
                await db.execute(
                    f"""
                    UPDATE chat_assistant_memory_outbox
                    SET state = 'claimed',
                        attempt_count = attempt_count + 1,
                        lease_token = ?,
                        lease_expires_at_ms = ?,
                        updated_at_ms = ?
                    WHERE state = 'pending'
                      AND canonical_message_id IN ({placeholders})
                    """,
                    (
                        lease_token,
                        lease_expires_at_ms,
                        normalized_now_ms,
                        *message_ids,
                    ),
                )
                cursor = await db.execute(
                    """
                    SELECT canonical_message_id, user_id, session_id, turn_id,
                           content_text, created_at_ms, attempt_count,
                           lease_token, lease_expires_at_ms
                    FROM chat_assistant_memory_outbox
                    WHERE state = 'claimed' AND lease_token = ?
                    ORDER BY created_at_ms, canonical_message_id
                    """,
                    (lease_token,),
                )
                rows = await cursor.fetchall()
                await db.commit()
            except BaseException:
                await db.rollback()
                raise
        return [self._row_to_assistant_memory_outbox(row) for row in rows]

    async def complete_assistant_memory_projection(
        self,
        *,
        canonical_message_id: str,
        lease_token: str,
    ) -> bool:
        """Delete one confirmed row only while the caller still owns its lease."""

        host = cast(_AssistantMemoryOutboxHost, self)
        await host.initialize()
        async with sqlite_connection_async(host.db_path, profile="mixed") as db:
            cursor = await db.execute(
                """
                DELETE FROM chat_assistant_memory_outbox
                WHERE canonical_message_id = ?
                  AND state = 'claimed'
                  AND lease_token = ?
                """,
                (canonical_message_id, lease_token),
            )
            await db.commit()
        return int(cursor.rowcount or 0) == 1

    async def retry_assistant_memory_projection(
        self,
        *,
        canonical_message_id: str,
        lease_token: str,
        retry_delay_ms: int,
        error: str,
        now_ms: int | None = None,
    ) -> bool:
        """Release one owned lease back to pending with bounded retry metadata."""

        host = cast(_AssistantMemoryOutboxHost, self)
        await host.initialize()
        normalized_now_ms = int(now_ms if now_ms is not None else time.time() * 1000)
        next_attempt_at_ms = normalized_now_ms + max(0, int(retry_delay_ms))
        async with sqlite_connection_async(host.db_path, profile="mixed") as db:
            cursor = await db.execute(
                """
                UPDATE chat_assistant_memory_outbox
                SET state = 'pending',
                    next_attempt_at_ms = ?,
                    lease_token = NULL,
                    lease_expires_at_ms = NULL,
                    last_error = ?,
                    updated_at_ms = ?
                WHERE canonical_message_id = ?
                  AND state = 'claimed'
                  AND lease_token = ?
                """,
                (
                    next_attempt_at_ms,
                    str(error or "")[:500] or None,
                    normalized_now_ms,
                    canonical_message_id,
                    lease_token,
                ),
            )
            await db.commit()
        return int(cursor.rowcount or 0) == 1

    async def cancel_assistant_memory_projection(
        self,
        *,
        canonical_message_id: str,
    ) -> bool:
        """Cancel pending or claimed work after a durable forget barrier exists."""

        return bool(
            await self.cancel_assistant_memory_projections(
                canonical_message_ids=[canonical_message_id],
            )
        )

    async def cancel_assistant_memory_projections(
        self,
        *,
        canonical_message_ids: list[str] | tuple[str, ...] = (),
        session_id: str | None = None,
    ) -> int:
        """Delete exact or session-scoped outbox rows."""

        host = cast(_AssistantMemoryOutboxHost, self)
        await host.initialize()
        normalized_ids = tuple(
            dict.fromkeys(
                value
                for raw in canonical_message_ids
                if (value := str(raw or "").strip())
            )
        )
        normalized_session_id = str(session_id or "").strip()
        if not normalized_ids and not normalized_session_id:
            return 0
        clauses: list[str] = []
        args: list[object] = []
        if normalized_ids:
            placeholders = ", ".join("?" for _ in normalized_ids)
            clauses.append(f"canonical_message_id IN ({placeholders})")
            args.extend(normalized_ids)
        if normalized_session_id:
            clauses.append("session_id = ?")
            args.append(normalized_session_id)
        async with sqlite_connection_async(host.db_path, profile="mixed") as db:
            cursor = await db.execute(
                "DELETE FROM chat_assistant_memory_outbox WHERE "
                + " OR ".join(clauses),
                tuple(args),
            )
            await db.commit()
        return int(cursor.rowcount or 0)

    async def count_assistant_memory_projections(self) -> int:
        """Return the current pending and claimed outbox size."""

        host = cast(_AssistantMemoryOutboxHost, self)
        await host.initialize()
        async with sqlite_connection_async(host.db_path, profile="mixed") as db:
            cursor = await db.execute(
                "SELECT COUNT(*) FROM chat_assistant_memory_outbox"
            )
            row = await cursor.fetchone()
        return int(row[0] or 0) if row is not None else 0

    async def get_assistant_memory_projection(
        self,
        canonical_message_id: str,
    ) -> ChatAssistantMemoryProjection | None:
        """Load one outbox projection for validation and diagnostics."""

        host = cast(_AssistantMemoryOutboxHost, self)
        await host.initialize()
        async with sqlite_connection_async(host.db_path, profile="mixed") as db:
            db.row_factory = aiosqlite.Row
            cursor = await db.execute(
                """
                SELECT canonical_message_id, user_id, session_id, turn_id,
                       content_text, created_at_ms
                FROM chat_assistant_memory_outbox
                WHERE canonical_message_id = ?
                """,
                (canonical_message_id,),
            )
            row = await cursor.fetchone()
        if row is None:
            return None
        return self._row_to_assistant_memory_projection(row)

    async def _insert_assistant_memory_projection(
        self,
        db: aiosqlite.Connection,
        projection: ChatAssistantMemoryProjection,
        *,
        updated_at_ms: int,
    ) -> None:
        """Insert one immutable projection intent inside an owning transaction."""

        normalized = self._normalize_assistant_memory_projection(projection)
        await db.execute(
            """
            INSERT INTO chat_assistant_memory_outbox (
                canonical_message_id,
                user_id,
                session_id,
                turn_id,
                content_text,
                created_at_ms,
                state,
                attempt_count,
                next_attempt_at_ms,
                lease_token,
                lease_expires_at_ms,
                last_error,
                updated_at_ms
            ) VALUES (?, ?, ?, ?, ?, ?, 'pending', 0, 0, NULL, NULL, NULL, ?)
            ON CONFLICT(canonical_message_id) DO NOTHING
            """,
            (
                normalized.canonical_message_id,
                normalized.user_id,
                normalized.session_id,
                normalized.turn_id,
                normalized.content,
                normalized.created_at_ms,
                int(updated_at_ms),
            ),
        )
        cursor = await db.execute(
            """
            SELECT user_id, session_id, turn_id, content_text, created_at_ms
            FROM chat_assistant_memory_outbox
            WHERE canonical_message_id = ?
            """,
            (normalized.canonical_message_id,),
        )
        row = await cursor.fetchone()
        if row is None or tuple(row) != (
            normalized.user_id,
            normalized.session_id,
            normalized.turn_id,
            normalized.content,
            normalized.created_at_ms,
        ):
            raise RuntimeError(
                "Assistant-memory projection identity was reused for different content"
            )

    @staticmethod
    def _normalize_assistant_memory_projection(
        projection: ChatAssistantMemoryProjection,
    ) -> ChatAssistantMemoryProjection:
        canonical_message_id = str(projection.canonical_message_id or "").strip()
        user_id = str(projection.user_id or "").strip()
        session_id = str(projection.session_id or "").strip()
        turn_id = str(projection.turn_id or "").strip()
        content = str(projection.content or "").strip()
        if not all((canonical_message_id, user_id, session_id, turn_id, content)):
            raise ValueError(
                "Assistant-memory projection requires message, owner, turn, and content"
            )
        return ChatAssistantMemoryProjection(
            canonical_message_id=canonical_message_id,
            user_id=user_id,
            session_id=session_id,
            turn_id=turn_id,
            content=content,
            created_at_ms=int(projection.created_at_ms),
        )

    @classmethod
    def _row_to_assistant_memory_outbox(
        cls,
        row: aiosqlite.Row,
    ) -> ChatAssistantMemoryOutboxRecord:
        return ChatAssistantMemoryOutboxRecord(
            projection=cls._row_to_assistant_memory_projection(row),
            attempt_count=int(row["attempt_count"] or 0),
            lease_token=str(row["lease_token"] or ""),
            lease_expires_at_ms=int(row["lease_expires_at_ms"] or 0),
        )

    @staticmethod
    def _row_to_assistant_memory_projection(
        row: aiosqlite.Row,
    ) -> ChatAssistantMemoryProjection:
        return ChatAssistantMemoryProjection(
            canonical_message_id=str(row["canonical_message_id"]),
            user_id=str(row["user_id"]),
            session_id=str(row["session_id"]),
            turn_id=str(row["turn_id"]),
            content=str(row["content_text"]),
            created_at_ms=int(row["created_at_ms"]),
        )


__all__ = ["ChatAssistantMemoryOutboxPersistenceMixin"]
