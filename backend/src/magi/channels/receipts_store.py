"""DeliveryReceiptsStore — Phase G+3 storage for delivery receipts.

Receipts live independent of the run snapshot. The snapshot's job is
to resume execution; receipts' job is to support retract / revise via
the channel-native message identifier. Coupling them on a single
``node_states`` blob created the failure mode where clearing a stale
snapshot also dropped retract capability — this store fixes that.

Schema is alembic-managed; see
``backend/src/magi/db/migrations/channels/versions/0002_delivery_receipts.py``.
"""
from __future__ import annotations

import time
from pathlib import Path

import aiosqlite

from ..core.logger import get_logger
from magi_plugin_sdk.delivery import DeliveryReceipt

logger = get_logger(__name__)


class DeliveryReceiptsStore:
    """Persists DeliveryReceipts keyed by (session_id, run_id, revision)."""

    def __init__(self, *, db_path: str) -> None:
        self._db_path = str(Path(db_path).expanduser())
        self._initialized = False

    async def initialize(self) -> None:
        Path(self._db_path).parent.mkdir(parents=True, exist_ok=True)
        self._initialized = True

    async def save_receipts(
        self,
        *,
        session_id: str,
        run_id: str,
        revision: int,
        receipts: list[DeliveryReceipt],
    ) -> None:
        if not receipts:
            return
        now_ms = int(time.time() * 1000)
        async with aiosqlite.connect(self._db_path) as db:
            await db.executemany(
                """
                INSERT INTO delivery_receipts(
                    session_id, run_id, revision, channel_id,
                    external_message_id, magi_session_id,
                    delivered_at_ms, created_at_ms
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                [
                    (
                        session_id,
                        run_id,
                        int(revision),
                        r.channel_id,
                        r.external_message_id,
                        r.magi_session_id,
                        int(r.delivered_at_ms),
                        now_ms,
                    )
                    for r in receipts
                ],
            )
            await db.commit()

    async def list_receipts(
        self,
        *,
        session_id: str,
        run_id: str,
        revision: int | None = None,
    ) -> list[DeliveryReceipt]:
        sql = (
            "SELECT channel_id, external_message_id, delivered_at_ms, magi_session_id "
            "FROM delivery_receipts WHERE session_id = ? AND run_id = ?"
        )
        params: list = [session_id, run_id]
        if revision is not None:
            sql += " AND revision = ?"
            params.append(int(revision))
        sql += " ORDER BY receipt_id ASC"
        async with aiosqlite.connect(self._db_path) as db:
            async with db.execute(sql, params) as cursor:
                rows = await cursor.fetchall()
        return [
            DeliveryReceipt(
                channel_id=row[0],
                external_message_id=row[1],
                delivered_at_ms=int(row[2]),
                magi_session_id=row[3] or "",
            )
            for row in rows
        ]

    async def clear_receipts(
        self,
        *,
        session_id: str,
        run_id: str,
    ) -> None:
        async with aiosqlite.connect(self._db_path) as db:
            await db.execute(
                "DELETE FROM delivery_receipts WHERE session_id = ? AND run_id = ?",
                (session_id, run_id),
            )
            await db.commit()


__all__ = ["DeliveryReceiptsStore"]
