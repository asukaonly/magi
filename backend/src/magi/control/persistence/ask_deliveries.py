"""SQLite leases for question notifications, guarded by the question owner."""
from __future__ import annotations

import hashlib
import json
import uuid

import aiosqlite
from magi_plugin_sdk.delivery import DeliveryContent, DeliveryReceipt
from magi_plugin_sdk.endpoints import EndpointRef

from ...delivery.policy import MAX_ATTEMPTS, LIFETIME_MS
from ...core.sqlite import sqlite_connection_async
from ..ask_contracts import AskState
from ..ask_delivery import AskDeliveryAttempt, AskDeliveryIntent

_ACTIVE = """EXISTS (SELECT 1 FROM control_asks a
    WHERE a.request_id=control_ask_deliveries.request_id AND a.resolution IS NULL)"""


async def insert_ask_delivery(db: aiosqlite.Connection, *, session_id: str, ask: AskState,
                              intent: AskDeliveryIntent) -> None:
    endpoint = json.dumps(intent.endpoint.to_dict(), sort_keys=True, ensure_ascii=False)
    key = hashlib.sha256(f"ask:{ask.request_id}:{endpoint}".encode()).hexdigest()
    now_ms = int(ask.asked_at * 1000)
    expiry = int(min(ask.expires_at or ask.asked_at+LIFETIME_MS/1000, ask.asked_at+LIFETIME_MS/1000)*1000)
    await db.execute("""INSERT INTO control_ask_deliveries
        (delivery_id,request_id,session_id,user_id,endpoint_json,content_json,state,
         expires_at_ms,created_at_ms,updated_at_ms) VALUES (?,?,?,?,?,?,'pending',?,?,?)""",
        (key, ask.request_id, session_id, intent.user_id, endpoint,
         json.dumps(intent.content.to_dict(), ensure_ascii=False, allow_nan=False), expiry, now_ms, now_ms))


async def cancel_closed_ask_deliveries(db: aiosqlite.Connection) -> None:
    await db.execute(f"""UPDATE control_ask_deliveries SET
        state=CASE WHEN state='sending' THEN 'uncertain' ELSE 'cancelled' END,
        lease_token=NULL,lease_expires_at_ms=NULL
        WHERE state IN ('pending','leased','sending') AND NOT ({_ACTIVE})""")


def _decode(row: aiosqlite.Row) -> AskDeliveryAttempt:
    return AskDeliveryAttempt(
        delivery_id=row["delivery_id"], request_id=row["request_id"], session_id=row["session_id"],
        intent=AskDeliveryIntent(row["user_id"], EndpointRef.from_dict(json.loads(row["endpoint_json"])),
                                 DeliveryContent.from_dict(json.loads(row["content_json"]))),
        state=row["state"], attempt_count=row["attempt_count"], lease_token=row["lease_token"],
        expires_at_ms=row["expires_at_ms"],
        receipt=DeliveryReceipt.from_dict(json.loads(row["receipt_json"])) if row["receipt_json"] else None,
    )


class SqliteAskDeliveryRepository:
    def __init__(self, db_path: str) -> None:
        self._path = db_path

    async def claim(self, *, now_ms: int, lease_ms: int) -> AskDeliveryAttempt | None:
        if lease_ms <= 0:
            raise ValueError("Question delivery lease must be positive")
        async with sqlite_connection_async(self._path, profile="hot_write") as db:
            db.row_factory = aiosqlite.Row
            await db.execute("BEGIN IMMEDIATE")
            await cancel_closed_ask_deliveries(db)
            await db.execute("""UPDATE control_ask_deliveries SET
                state=CASE WHEN state='leased' OR (retry_safe=1 AND attempt_count<?) THEN 'pending' ELSE 'uncertain' END,
                lease_token=NULL,lease_expires_at_ms=NULL WHERE state IN ('leased','sending') AND lease_expires_at_ms<=?""", (MAX_ATTEMPTS, now_ms))
            await db.execute("UPDATE control_ask_deliveries SET state='expired' WHERE state='pending' AND expires_at_ms<=?", (now_ms,))
            rows = await db.execute_fetchall(f"""SELECT * FROM control_ask_deliveries
                WHERE state='pending' AND next_attempt_at_ms<=? AND {_ACTIVE}
                ORDER BY created_at_ms,delivery_id LIMIT 1""", (now_ms,))
            if not rows:
                await db.commit()
                return None
            key, token = rows[0]["delivery_id"], uuid.uuid4().hex
            await db.execute("""UPDATE control_ask_deliveries SET state='leased',lease_token=?,
                lease_expires_at_ms=?,updated_at_ms=? WHERE delivery_id=?""", (token, now_ms+lease_ms, now_ms, key))
            row, = await db.execute_fetchall("SELECT * FROM control_ask_deliveries WHERE delivery_id=?", (key,))
            await db.commit()
            return _decode(row)

    async def begin(self, *, delivery_id: str, lease_token: str | None, retry_safe: bool, now_ms: int) -> bool:
        async with sqlite_connection_async(self._path, profile="hot_write") as db:
            changed = await db.execute(f"""UPDATE control_ask_deliveries SET state='sending',retry_safe=?,
                attempt_count=attempt_count+1,updated_at_ms=? WHERE delivery_id=? AND lease_token=?
                AND state='leased' AND lease_expires_at_ms>? AND expires_at_ms>? AND {_ACTIVE}""",
                (int(retry_safe), now_ms, delivery_id, lease_token, now_ms, now_ms))
            await db.commit()
            return changed.rowcount == 1

    async def settle(self, *, delivery_id: str, lease_token: str | None, state: str, now_ms: int,
                     receipt: DeliveryReceipt | None, error: str | None, retry_at_ms: int) -> bool:
        if state not in {"pending", "succeeded", "uncertain", "failed", "cancelled"}:
            raise ValueError("Unsupported question delivery settlement")
        if (state == "succeeded") != (receipt is not None):
            raise ValueError("Successful question delivery requires a receipt")
        async with sqlite_connection_async(self._path, profile="hot_write") as db:
            changed = await db.execute(f"""UPDATE control_ask_deliveries SET state=?,receipt_json=?,last_error=?,
                next_attempt_at_ms=?,updated_at_ms=?,lease_token=NULL,lease_expires_at_ms=NULL
                WHERE delivery_id=? AND lease_token=? AND state IN ('leased','sending')
                AND (state='sending' OR ?!='succeeded')
                AND (?!='pending' OR state='leased' OR (retry_safe=1 AND attempt_count<?))
                AND lease_expires_at_ms>? AND {_ACTIVE}""",
                (state, json.dumps(receipt.to_dict()) if receipt else None, error, retry_at_ms, now_ms,
                 delivery_id, lease_token, state, state, MAX_ATTEMPTS, now_ms))
            await db.commit()
            return changed.rowcount == 1
