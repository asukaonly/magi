"""Chat-owned durable handoff for accepted conversation understanding."""

from __future__ import annotations

import hashlib
import json
import time
from typing import Any
import uuid

import aiosqlite

from ...core.sqlite import sqlite_connection_async
from ...memory.post_turn_contracts import PostTurnBatchLease, PostTurnLeaseLost
from ..contracts import ChatMessageRecord


_LIVE_SOURCE_PREDICATE = """NOT EXISTS (SELECT 1 FROM chat_global_clear_intent)
AND NOT EXISTS (
    SELECT 1 FROM chat_cleared_session_scopes AS cleared_session
    WHERE cleared_session.session_id=outcomes.session_id
)
AND NOT EXISTS (
    SELECT 1 FROM chat_cleared_message_scopes AS cleared_message
    WHERE cleared_message.session_id=outcomes.session_id AND (
        cleared_message.message_id IN (SELECT value FROM json_each(outcomes.source_message_ids))
        OR EXISTS (SELECT 1 FROM chat_messages AS source_message
            WHERE source_message.session_id=outcomes.session_id
              AND source_message.turn_id=outcomes.source_turn_id AND source_message.role='user'
              AND source_message.message_id=cleared_message.message_id COLLATE NOCASE)
    )
)"""

_LIVE_BATCH_PREDICATE = f"""NOT EXISTS (SELECT 1 FROM chat_global_clear_intent)
AND NOT EXISTS (SELECT 1 FROM chat_post_turn_outcomes AS outcomes
    WHERE outcomes.batch_id=chat_post_turn_batches.batch_id AND NOT ({_LIVE_SOURCE_PREDICATE}))"""


async def insert_post_turn_intent(
    db: aiosqlite.Connection, *, messages: list[ChatMessageRecord],
    accepted_at_ms: int, execution_mode: str | None, delivery_attempt_no: int | None,
) -> None:
    """Insert references inside the transaction accepting the visible response."""
    if not messages or not any(message.content_text for message in messages):
        return
    last = messages[-1]
    payload = json.loads(last.payload_json or "{}")
    payload = payload if isinstance(payload, dict) else {}
    task_id = str(payload.get("background_task_id") or "").strip() or None
    task_attempt = payload.get("background_task_attempt") if task_id else None
    if isinstance(task_attempt, bool) or not isinstance(task_attempt, int) or task_attempt < 0:
        task_attempt = 0 if task_id else None
    await db.execute(
        """INSERT INTO chat_post_turn_outcomes (
            outcome_id, source_turn_id, session_id, user_id, persona_id,
            source_message_ids, accepted_at_ms, execution_mode, delivery_attempt_no,
            task_id, task_attempt
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?) ON CONFLICT(outcome_id) DO NOTHING""",
        (f"chat-message:{last.message_id}:accepted", last.turn_id, last.session_id,
         last.user_id, last.persona_id, json.dumps([item.message_id for item in messages]),
         int(accepted_at_ms), execution_mode, delivery_attempt_no, task_id, task_attempt),
    )


class ChatPostTurnOutboxMixin:
    """Bounded recovery, fenced ownership and settlement for post-turn batches."""

    db_path: str

    async def list_ready_post_turn_outcomes(self) -> list[dict[str, Any]]:
        """Load up to two complete frozen batches and twenty unbatched outcomes."""
        now = int(time.time() * 1000)
        async with sqlite_connection_async(self.db_path, profile="mixed") as db:
            db.row_factory = aiosqlite.Row
            await db.execute(
                """UPDATE chat_post_turn_batches SET state='failed', last_error='LeaseExpired',
                lease_token=NULL, lease_expires_at_ms=NULL WHERE state='claimed'
                AND lease_expires_at_ms <= ? AND attempt_count >= 5""", (now,),
            )
            await db.commit()
            batch_rows = await db.execute_fetchall(
                f"""SELECT batch_id FROM chat_post_turn_batches
                WHERE ((state='pending' AND next_attempt_at_ms <= ?)
                   OR (state='claimed' AND lease_expires_at_ms <= ?))
                AND {_LIVE_BATCH_PREDICATE}
                ORDER BY updated_at_ms, batch_id LIMIT 2""", (now, now),
            )
            keys = [str(row[0]) for row in batch_rows]
            bound = await db.execute_fetchall(
                "SELECT * FROM chat_post_turn_outcomes WHERE batch_id IN (?, ?) ORDER BY accepted_at_ms, outcome_id",
                tuple((keys + [None, None])[:2]),
            )
            fresh = await db.execute_fetchall(
                f"""SELECT * FROM chat_post_turn_outcomes AS outcomes WHERE batch_id IS NULL
                    AND {_LIVE_SOURCE_PREDICATE} ORDER BY accepted_at_ms, outcome_id LIMIT 20"""
            )
            outcomes: list[dict[str, Any]] = []
            for row in [*bound, *fresh]:
                ids = json.loads(row["source_message_ids"])
                messages = await db.execute_fetchall(
                    """SELECT message_id, content_text FROM chat_messages
                    WHERE message_id IN (SELECT value FROM json_each(?)) AND is_visible=1
                    ORDER BY sequence_no""", (json.dumps(ids),),
                )
                if len(messages) != len(ids):
                    continue
                user_rows = await db.execute_fetchall(
                    """SELECT content_text FROM chat_messages WHERE session_id=? AND turn_id=?
                    AND role='user' AND is_visible=1 ORDER BY sequence_no LIMIT 1""",
                    (row["session_id"], row["source_turn_id"]),
                )
                outcomes.append({**dict(row), "source_message_ids": tuple(ids),
                                 "user_message": str(user_rows[0][0] or "") if user_rows else "",
                                 "assistant_response": "\n".join(str(item["content_text"] or "") for item in messages)})
            return outcomes

    async def claim_post_turn_batch(self, outcome_ids: tuple[str, ...], *, lease_seconds: float = 300) -> PostTurnBatchLease | None:
        """Freeze membership and lease one batch; a stale worker cannot settle it."""
        if not outcome_ids or len(outcome_ids) > 20:
            raise ValueError("Post-turn batches must contain between one and twenty outcomes")
        now = int(time.time() * 1000)
        token = uuid.uuid4().hex
        async with sqlite_connection_async(self.db_path, profile="mixed") as db:
            db.row_factory = aiosqlite.Row
            await db.execute("BEGIN IMMEDIATE")
            rows = await db.execute_fetchall(
                f"""SELECT * FROM chat_post_turn_outcomes AS outcomes
                    WHERE outcome_id IN (SELECT value FROM json_each(?)) AND {_LIVE_SOURCE_PREDICATE}""",
                (json.dumps(outcome_ids),),
            )
            if (len(rows) != len(outcome_ids) or len({row["session_id"] for row in rows}) != 1
                    or len({row["persona_id"] or "" for row in rows}) != 1):
                return None
            active = await db.execute_fetchall(
                "SELECT batch_id FROM chat_post_turn_batches WHERE session_id=? AND state='claimed' AND lease_expires_at_ms > ?",
                (rows[0]["session_id"], now),
            )
            if active:
                return None
            existing_ids = {row["batch_id"] for row in rows if row["batch_id"] is not None}
            if existing_ids:
                if len(existing_ids) != 1 or any(row["batch_id"] is None for row in rows):
                    return None
                batch_id = str(next(iter(existing_ids)))
                members = await db.execute_fetchall("SELECT outcome_id FROM chat_post_turn_outcomes WHERE batch_id=?", (batch_id,))
                if {row[0] for row in members} != set(outcome_ids):
                    return None
            else:
                batch_id = hashlib.sha256(json.dumps(outcome_ids).encode()).hexdigest()
                await db.execute(
                    "INSERT INTO chat_post_turn_batches (batch_id, session_id, state, updated_at_ms) VALUES (?, ?, 'pending', ?)",
                    (batch_id, rows[0]["session_id"], now),
                )
                await db.execute(
                    "UPDATE chat_post_turn_outcomes SET batch_id=? WHERE outcome_id IN (SELECT value FROM json_each(?))",
                    (batch_id, json.dumps(outcome_ids)),
                )
            cursor = await db.execute(
                """UPDATE chat_post_turn_batches SET state='claimed', attempt_count=attempt_count+1,
                lease_token=?, lease_expires_at_ms=?, updated_at_ms=? WHERE batch_id=? AND (
                    state='pending' AND next_attempt_at_ms <= ? OR state='claimed' AND lease_expires_at_ms <= ?
                ) AND attempt_count < 5""", (token, now + int(lease_seconds * 1000), now, batch_id, now, now),
            )
            if cursor.rowcount != 1:
                return None
            batch = (await db.execute_fetchall("SELECT * FROM chat_post_turn_batches WHERE batch_id=?", (batch_id,)))[0]
            await db.commit()
            return PostTurnBatchLease(batch_id, token, outcome_ids, int(batch["attempt_count"]),
                                      json.loads(batch["analysis_json"]) if batch["analysis_json"] else None,
                                      frozenset(json.loads(batch["settled_json"])), str(rows[0]["persona_id"] or ""))

    async def ensure_post_turn_lease(self, lease: PostTurnBatchLease) -> None:
        """Renew a live lease or fail closed after revocation or replacement."""
        now = int(time.time() * 1000)
        async with sqlite_connection_async(self.db_path, profile="mixed") as db:
            cursor = await db.execute(
                f"""UPDATE chat_post_turn_batches SET lease_expires_at_ms=? WHERE batch_id=?
                AND state='claimed' AND lease_token=? AND lease_expires_at_ms > ? AND {_LIVE_BATCH_PREDICATE}""",
                (now + 300_000, lease.batch_id, lease.token, now),
            )
            await db.commit()
            if cursor.rowcount != 1:
                raise PostTurnLeaseLost("Post-turn batch lease is no longer current")

    async def save_post_turn_analysis(self, lease: PostTurnBatchLease, analysis: dict[str, Any]) -> None:
        await self.ensure_post_turn_lease(lease)
        async with sqlite_connection_async(self.db_path, profile="mixed") as db:
            cursor = await db.execute(
                """UPDATE chat_post_turn_batches SET analysis_json=? WHERE batch_id=?
                AND state='claimed' AND lease_token=? AND analysis_json IS NULL""",
                (json.dumps(analysis, ensure_ascii=False), lease.batch_id, lease.token),
            )
            await db.commit()
            if cursor.rowcount != 1:
                raise PostTurnLeaseLost("Post-turn analysis cannot replace a frozen result")

    async def settle_post_turn_effect(self, lease: PostTurnBatchLease, effect: str) -> None:
        await self.ensure_post_turn_lease(lease)
        async with sqlite_connection_async(self.db_path, profile="mixed") as db:
            cursor = await db.execute(
                """UPDATE chat_post_turn_batches SET settled_json=json_insert(settled_json, '$[#]', ?)
                WHERE batch_id=? AND state='claimed' AND lease_token=?
                AND NOT EXISTS (SELECT 1 FROM json_each(settled_json) WHERE value=?)""",
                (effect, lease.batch_id, lease.token, effect),
            )
            await db.commit()
            if cursor.rowcount != 1:
                raise PostTurnLeaseLost("Post-turn effect cannot be settled by this attempt")

    async def replace_post_turn_attention(self, lease: PostTurnBatchLease, analysis: dict[str, Any]) -> None:
        """Refresh only the L0 patch after its base changes, preserving frozen turn effects."""
        await self.ensure_post_turn_lease(lease)
        async with sqlite_connection_async(self.db_path, profile="mixed") as db:
            await db.execute("BEGIN IMMEDIATE")
            rows = await db.execute_fetchall(
                "SELECT analysis_json FROM chat_post_turn_batches WHERE batch_id=? AND state='claimed' AND lease_token=?",
                (lease.batch_id, lease.token),
            )
            if not rows or not rows[0][0]:
                raise PostTurnLeaseLost("Post-turn frozen analysis is unavailable")
            previous = json.loads(rows[0][0])
            if previous["analysis"]["turns"] != analysis["analysis"]["turns"]:
                raise ValueError("A post-turn attention refresh cannot change frozen personality effects")
            await db.execute("UPDATE chat_post_turn_batches SET analysis_json=? WHERE batch_id=?",
                             (json.dumps(analysis, ensure_ascii=False), lease.batch_id))
            await db.commit()

    async def finish_post_turn_batch(self, lease: PostTurnBatchLease, *, error: str | None = None) -> bool:
        now = int(time.time() * 1000)
        async with sqlite_connection_async(self.db_path, profile="mixed") as db:
            await db.execute("BEGIN IMMEDIATE")
            owned = await db.execute_fetchall(
                f"""SELECT 1 FROM chat_post_turn_batches WHERE batch_id=? AND state='claimed'
                    AND lease_token=? AND lease_expires_at_ms > ? AND {_LIVE_BATCH_PREDICATE}""",
                (lease.batch_id, lease.token, now),
            )
            if not owned:
                return False
            if error is None:
                await db.execute("DELETE FROM chat_post_turn_outcomes WHERE outcome_id IN (SELECT value FROM json_each(?))",
                                 (json.dumps(lease.outcome_ids),))
                await db.execute("DELETE FROM chat_post_turn_batches WHERE batch_id=?", (lease.batch_id,))
            else:
                await db.execute(
                    """UPDATE chat_post_turn_batches SET state=?, next_attempt_at_ms=?, lease_token=NULL,
                    lease_expires_at_ms=NULL, last_error=?, updated_at_ms=? WHERE batch_id=?""",
                    ("failed" if lease.attempt_count >= 5 else "pending",
                     now + min(300_000, 30_000 * 2 ** min(lease.attempt_count - 1, 9)),
                     error[:250], now, lease.batch_id),
                )
            await db.commit()
            return True

    async def cancel_post_turn_outcomes(self, *, session_id: str, turn_ids: tuple[str, ...] = (), cutoff_at: float | None = None) -> int:
        """Remove source-owned intents and invalidate any analysis using that evidence."""
        args: list[Any] = [session_id]
        clauses = ["session_id=?"]
        if turn_ids:
            clauses.append("source_turn_id IN (SELECT value FROM json_each(?))")
            args.append(json.dumps(turn_ids))
        if cutoff_at is not None:
            clauses.append("accepted_at_ms <= ?")
            args.append(int(cutoff_at * 1000))
        async with sqlite_connection_async(self.db_path, profile="mixed") as db:
            cursor = await db.execute("DELETE FROM chat_post_turn_outcomes WHERE " + " AND ".join(clauses), tuple(args))
            await db.commit()
            return max(0, cursor.rowcount)

    async def post_turn_status(self) -> dict[str, Any]:
        """Read safe queue diagnostics without exposing cached analysis or evidence."""
        async with sqlite_connection_async(self.db_path, profile="mixed") as db:
            rows = await db.execute_fetchall("""SELECT batches.state, COUNT(*) FROM chat_post_turn_outcomes AS outcomes
                JOIN chat_post_turn_batches AS batches USING(batch_id) GROUP BY batches.state""")
            counts = {str(row[0]): int(row[1]) for row in rows}
            unbatched = (await db.execute_fetchall("SELECT COUNT(*) FROM chat_post_turn_outcomes WHERE batch_id IS NULL"))[0][0]
            errors = await db.execute_fetchall("SELECT DISTINCT last_error FROM chat_post_turn_batches WHERE state='failed' AND last_error IS NOT NULL LIMIT 10")
            return {"pending": counts.get("pending", 0) + int(unbatched),
                    "claimed": counts.get("claimed", 0), "failed": counts.get("failed", 0),
                    "error_kinds": [str(row[0]) for row in errors]}

    async def retry_failed_post_turn_batches(self, *, limit: int = 100) -> int:
        """Rearm at most ``limit`` whole batches and return their outcome count."""
        async with sqlite_connection_async(self.db_path, profile="mixed") as db:
            await db.execute("BEGIN IMMEDIATE")
            cursor = await db.execute(
                f"""UPDATE chat_post_turn_batches SET state='pending', attempt_count=0,
                    next_attempt_at_ms=0, last_error=NULL
                WHERE batch_id IN (SELECT batch_id FROM chat_post_turn_batches WHERE state='failed'
                    AND {_LIVE_BATCH_PREDICATE}
                    ORDER BY updated_at_ms, batch_id LIMIT ?) RETURNING batch_id""", (max(1, min(100, int(limit))),),
            )
            batch_ids = [str(row[0]) for row in await cursor.fetchall()]
            count = await db.execute_fetchall(
                "SELECT COUNT(*) FROM chat_post_turn_outcomes WHERE batch_id IN (SELECT value FROM json_each(?))",
                (json.dumps(batch_ids),),
            )
            await db.commit()
            return int(count[0][0])
