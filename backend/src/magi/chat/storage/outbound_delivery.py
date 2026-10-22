"""SQLite implementation of chat's durable per-endpoint delivery ledger."""
from __future__ import annotations

import hashlib
import json
import uuid

import aiosqlite
from magi_plugin_sdk.delivery import DeliveryContent, DeliveryReceipt
from magi_plugin_sdk.endpoints import EndpointRef

from ...core.sqlite import sqlite_connection_async
from ...delivery.outbox import DeliveryState, OutboundDelivery
from ...delivery.routing import DeliveryPlan

_LIVE = """NOT EXISTS (SELECT 1 FROM chat_global_clear_intent)
AND EXISTS (SELECT 1 FROM chat_sessions s WHERE s.session_id=chat_outbound_deliveries.session_id
    AND s.deleted_at_ms IS NULL AND s.archived_at_ms IS NULL)
AND EXISTS (SELECT 1 FROM chat_messages m WHERE m.message_id=chat_outbound_deliveries.message_id
    AND m.is_visible=1)
AND NOT EXISTS (SELECT 1 FROM chat_cleared_session_scopes s
    WHERE s.session_id=chat_outbound_deliveries.session_id COLLATE NOCASE)
AND NOT EXISTS (SELECT 1 FROM chat_cleared_message_scopes c
    WHERE c.session_id=chat_outbound_deliveries.session_id COLLATE NOCASE
    AND (c.message_id=chat_outbound_deliveries.message_id COLLATE NOCASE
      OR EXISTS (SELECT 1 FROM chat_messages u JOIN chat_messages m ON u.turn_id=m.turn_id
        WHERE m.message_id=chat_outbound_deliveries.message_id AND u.role='user'
          AND u.message_id=c.message_id COLLATE NOCASE)))"""


def _encode(value: dict) -> str:
    return json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":"), allow_nan=False)


async def insert_outbound_deliveries(
    db: aiosqlite.Connection, *, content: DeliveryContent, plan: DeliveryPlan,
    now_ms: int, lifetime_ms: int = 86_400_000,
) -> None:
    """Insert immutable intents in the transaction accepting the message itself."""
    if not content.message_id or lifetime_ms <= 0:
        raise ValueError("Outbound delivery requires a durable message and positive lifetime")
    for target in plan.targets:
        if target.registry_key == "chat_sse":
            continue
        endpoint = _encode(target.to_dict())
        delivery_id = hashlib.sha256(_encode({"message": content.message_id, "endpoint": target.to_dict()}).encode()).hexdigest()
        payload = _encode(content.to_dict())
        rows = await db.execute_fetchall("SELECT endpoint_json,content_json FROM chat_outbound_deliveries WHERE delivery_id=?", (delivery_id,))
        if rows:
            if tuple(rows[0]) != (endpoint, payload):
                raise ValueError("A delivery identity cannot be reused for different content")
            continue
        inserted = await db.execute("""INSERT INTO chat_outbound_deliveries
            (delivery_id,message_id,session_id,user_id,endpoint_json,content_json,state,
             expires_at_ms,created_at_ms,updated_at_ms)
            SELECT ?,?,?,?,?,?,'pending',?,?,? WHERE EXISTS (
                SELECT 1 FROM chat_messages m WHERE m.message_id=? AND m.session_id=?
                    AND m.user_id=? AND m.role='assistant' AND m.is_visible=1 AND m.is_final=1)
            """, (delivery_id, content.message_id, plan.session_id, plan.user_id, endpoint, payload,
                   now_ms+lifetime_ms, now_ms, now_ms, content.message_id, plan.session_id, plan.user_id))
        if inserted.rowcount != 1:
            raise ValueError("Delivery intent does not belong to an accepted assistant message")


def _decode(row: aiosqlite.Row) -> OutboundDelivery:
    return OutboundDelivery(
        delivery_id=row["delivery_id"], message_id=row["message_id"], session_id=row["session_id"],
        user_id=row["user_id"], endpoint=EndpointRef.from_dict(json.loads(row["endpoint_json"])),
        content=DeliveryContent.from_dict(json.loads(row["content_json"])), state=row["state"],
        attempt_count=row["attempt_count"], lease_token=row["lease_token"], expires_at_ms=row["expires_at_ms"],
        receipt=DeliveryReceipt.from_dict(json.loads(row["receipt_json"])) if row["receipt_json"] else None,
    )


class ChatOutboundDeliveryMixin:
    """Lease arbitration and evidence-preserving recovery within one logical center."""
    db_path: str

    async def claim_outbound_delivery(self, *, now_ms: int, message_id: str | None = None,
                                     lease_ms: int = 60_000) -> OutboundDelivery | None:
        if lease_ms <= 0:
            raise ValueError("Delivery lease must be positive")
        async with sqlite_connection_async(self.db_path, profile="mixed") as db:
            db.row_factory = aiosqlite.Row
            await db.execute("BEGIN IMMEDIATE")
            # In-flight calls without provider idempotency cannot be replayed safely.
            await db.execute("""UPDATE chat_outbound_deliveries SET
                state=CASE WHEN state='leased' THEN 'pending'
                           WHEN retry_safe=1 AND attempt_count<5 THEN 'pending' ELSE 'uncertain' END,
                lease_token=NULL,lease_expires_at_ms=NULL,last_error='LeaseExpired',updated_at_ms=?
                WHERE state IN ('leased','sending') AND lease_expires_at_ms<=?""", (now_ms, now_ms))
            await db.execute(f"""UPDATE chat_outbound_deliveries SET state='cancelled',content_json='{{}}',
                lease_token=NULL,lease_expires_at_ms=NULL,updated_at_ms=?
                WHERE state IN ('pending','leased','sending') AND NOT ({_LIVE})""", (now_ms,))
            await db.execute("""UPDATE chat_outbound_deliveries SET state='expired',updated_at_ms=?
                WHERE state='pending' AND expires_at_ms<=?""", (now_ms, now_ms))
            rows = await db.execute_fetchall(f"""SELECT * FROM chat_outbound_deliveries
                WHERE state='pending' AND next_attempt_at_ms<=? AND (? IS NULL OR message_id=?)
                AND {_LIVE} ORDER BY created_at_ms,delivery_id LIMIT 1""", (now_ms, message_id, message_id))
            if not rows:
                await db.commit()
                return None
            row = rows[0]
            token = uuid.uuid4().hex
            await db.execute("""UPDATE chat_outbound_deliveries SET state='leased',lease_token=?,
                lease_expires_at_ms=?,updated_at_ms=? WHERE delivery_id=?""",
                (token, now_ms+lease_ms, now_ms, row["delivery_id"]))
            result = await db.execute_fetchall("SELECT * FROM chat_outbound_deliveries WHERE delivery_id=?", (row["delivery_id"],))
            await db.commit()
            return _decode(result[0])

    async def begin_outbound_attempt(self, item: OutboundDelivery, *, retry_safe: bool, now_ms: int) -> bool:
        async with sqlite_connection_async(self.db_path, profile="mixed") as db:
            changed = await db.execute(f"""UPDATE chat_outbound_deliveries SET state='sending',
                attempt_count=attempt_count+1,retry_safe=?,updated_at_ms=?
                WHERE delivery_id=? AND lease_token=? AND state='leased'
                AND lease_expires_at_ms>? AND expires_at_ms>? AND {_LIVE}""",
                (int(retry_safe), now_ms, item.delivery_id, item.lease_token, now_ms, now_ms))
            await db.commit()
            return changed.rowcount == 1

    async def settle_outbound_delivery(self, item: OutboundDelivery, *, state: DeliveryState, now_ms: int,
                                       receipt: DeliveryReceipt | None = None, error: str | None = None,
                                       retry_at_ms: int = 0) -> bool:
        if state not in {"pending", "succeeded", "uncertain", "failed", "cancelled"}:
            raise ValueError("Unsupported delivery settlement")
        if (state == "succeeded") != (receipt is not None):
            raise ValueError("Successful delivery requires a receipt")
        async with sqlite_connection_async(self.db_path, profile="mixed") as db:
            changed = await db.execute(f"""UPDATE chat_outbound_deliveries SET state=?,receipt_json=?,last_error=?,
                next_attempt_at_ms=?,lease_token=NULL,lease_expires_at_ms=NULL,updated_at_ms=?
                WHERE delivery_id=? AND lease_token=? AND state IN ('leased','sending')
                AND (state='sending' OR ?!='succeeded')
                AND (?!='pending' OR state='leased' OR (retry_safe=1 AND attempt_count<5))
                AND lease_expires_at_ms>? AND {_LIVE}""",
                (state, _encode(receipt.to_dict()) if receipt else None, error, retry_at_ms, now_ms,
                 item.delivery_id, item.lease_token, state, state, now_ms))
            await db.commit()
            return changed.rowcount == 1

    async def list_outbound_deliveries(self, *, message_id: str) -> list[OutboundDelivery]:
        async with sqlite_connection_async(self.db_path, profile="mixed") as db:
            db.row_factory = aiosqlite.Row
            rows = await db.execute_fetchall("SELECT * FROM chat_outbound_deliveries WHERE message_id=? ORDER BY delivery_id", (message_id,))
            return [_decode(row) for row in rows]
