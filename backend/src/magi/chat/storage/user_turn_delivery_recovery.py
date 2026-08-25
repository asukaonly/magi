"""Atomic recovery transactions for durable user-turn delivery."""

from __future__ import annotations

import hashlib
import json

from ...core.sqlite import sqlite_connection_async
from ..contracts import (
    CHAT_DELIVERY_STATE_ADMITTED,
    CHAT_DELIVERY_STATE_QUEUED,
    CHAT_DELIVERY_STATE_READY,
    CHAT_DELIVERY_STATE_TERMINAL,
)
from ..rhythm_completion import complete_rhythm_payloads
from .user_turn_delivery_errors import ChatTurnConflictError
from .user_turn_delivery_rows import normalize_delivery_attempt_no


class ChatUserTurnDeliveryRecoveryPersistenceMixin:
    """Reconcile durable outcomes and quarantine unreplayable accepted turns."""

    db_path: str

    async def initialize(self) -> None:
        raise NotImplementedError

    async def reconcile_user_turn_terminal_surface(
        self,
        *,
        turn_id: str,
        expected_attempt_no: int,
        updated_at_ms: int,
    ) -> bool:
        """Atomically reconcile a durable final surface with its turn and delivery."""

        normalized_turn_id = str(turn_id or "").strip()
        if not normalized_turn_id:
            raise ValueError("Turn ID is required")
        normalized_attempt_no = normalize_delivery_attempt_no(expected_attempt_no)
        await self.initialize()
        async with sqlite_connection_async(self.db_path, profile="mixed") as db:
            await db.execute("BEGIN IMMEDIATE")
            try:
                owner_rows = list(
                    await db.execute_fetchall(
                        """
                    SELECT delivery.delivery_state,
                           delivery.delivery_attempt_no,
                           turns.status,
                           turns.response_mode,
                           turns.run_disposition,
                           turns.updated_at_ms,
                           turns.session_id,
                           turns.run_id
                    FROM chat_user_turn_delivery AS delivery
                    JOIN chat_turns AS turns
                      ON turns.turn_id = delivery.turn_id
                    JOIN chat_sessions AS sessions
                      ON sessions.session_id = turns.session_id
                     AND sessions.user_id = turns.user_id
                    WHERE delivery.turn_id = ?
                      AND delivery.delivery_attempt_no = ?
                      AND delivery.delivery_state IN (?, ?, ?)
                      AND sessions.deleted_at_ms IS NULL
                      AND sessions.archived_at_ms IS NULL
                      AND EXISTS (
                          SELECT 1
                          FROM chat_messages AS user_messages
                          WHERE user_messages.turn_id = delivery.turn_id
                            AND user_messages.session_id = turns.session_id
                            AND user_messages.user_id = turns.user_id
                            AND user_messages.role = 'user'
                            AND user_messages.message_kind = 'user_text'
                            AND user_messages.is_visible = 1
                      )
                    """,
                        (
                            normalized_turn_id,
                            normalized_attempt_no,
                            CHAT_DELIVERY_STATE_READY,
                            CHAT_DELIVERY_STATE_QUEUED,
                            CHAT_DELIVERY_STATE_ADMITTED,
                        ),
                    )
                )
                if not owner_rows:
                    await db.rollback()
                    return False
                owner = owner_rows[0]
                output_rows = list(
                    await db.execute_fetchall(
                        """
                    SELECT message_kind, is_final, payload_json, created_at_ms,
                           content_text, persona_id
                    FROM chat_messages
                    WHERE turn_id = ?
                      AND role = 'assistant'
                      AND is_visible = 1
                      AND message_kind IN (
                          'assistant_final',
                          'assistant_rhythm_segment'
                      )
                    ORDER BY sequence_no, message_id
                    """,
                        (normalized_turn_id,),
                    )
                )
                has_visible_final = any(
                    str(row["message_kind"]) == "assistant_final"
                    and bool(int(row["is_final"] or 0))
                    for row in output_rows
                )
                rhythm_rows = [
                    row
                    for row in output_rows
                    if str(row["message_kind"]) == "assistant_rhythm_segment"
                    and bool(int(row["is_final"] or 0))
                ]
                has_complete_rhythm = complete_rhythm_payloads(
                    [str(row["payload_json"] or "{}") for row in rhythm_rows]
                )
                turn_status = str(owner["status"] or "").strip().lower()
                response_mode = str(owner["response_mode"] or "").strip().lower()
                run_disposition = str(owner["run_disposition"] or "").strip().lower()
                has_terminal_surface = (
                    has_visible_final
                    or has_complete_rhythm
                    or turn_status in {"cancelled", "merged", "interrupted"}
                    or (
                        turn_status == "completed"
                        and run_disposition != "message"
                        and response_mode in {"none", "reaction_only"}
                    )
                )
                if not has_terminal_surface:
                    await db.rollback()
                    return False
                if turn_status in {"queued", "running"} and (
                    has_visible_final or has_complete_rhythm
                ):
                    completed_at_ms = max(
                        int(owner["updated_at_ms"] or 0),
                        *(int(row["created_at_ms"] or 0) for row in output_rows),
                    )
                    await db.execute(
                        """
                        UPDATE chat_turns
                        SET status = 'completed',
                            updated_at_ms = ?,
                            completed_at_ms = ?
                        WHERE turn_id = ?
                          AND status IN ('queued', 'running')
                        """,
                        (
                            completed_at_ms,
                            completed_at_ms,
                            normalized_turn_id,
                        ),
                    )
                cursor = await db.execute(
                    """
                    UPDATE chat_user_turn_delivery
                    SET delivery_state = ?,
                        updated_at_ms = ?
                    WHERE turn_id = ?
                      AND delivery_attempt_no = ?
                      AND delivery_state IN (?, ?, ?)
                    """,
                    (
                        CHAT_DELIVERY_STATE_TERMINAL,
                        int(updated_at_ms),
                        normalized_turn_id,
                        normalized_attempt_no,
                        CHAT_DELIVERY_STATE_READY,
                        CHAT_DELIVERY_STATE_QUEUED,
                        CHAT_DELIVERY_STATE_ADMITTED,
                    ),
                )
                changed = int(cursor.rowcount or 0) == 1
                effective_run_id = str(owner["run_id"] or "").strip()
                if changed and effective_run_id:
                    visible_text = "\n".join(
                        str(row["content_text"] or "").strip()
                        for row in output_rows
                        if str(row["content_text"] or "").strip()
                    )
                    await self._promote_model_context_run_with_connection(
                        db,
                        session_id=str(owner["session_id"]),
                        run_id=effective_run_id,
                        turn_id=normalized_turn_id,
                        outcome_text=(
                            visible_text
                            or "[Runtime outcome] The recovered turn had no visible assistant message."
                        ),
                        outcome_kind="assistant" if visible_text else "runtime",
                        persona_id=next(
                            (
                                str(row["persona_id"])
                                for row in output_rows
                                if row["persona_id"] is not None
                            ),
                            None,
                        ),
                        completed_at_ms=int(updated_at_ms),
                    )
                await db.commit()
            except BaseException:
                await db.rollback()
                raise
        return changed

    async def quarantine_invalid_user_turn_delivery(
        self,
        *,
        turn_id: str,
        expected_attempt_no: int,
        user_message: str,
        updated_at_ms: int,
    ) -> bool:
        """Atomically close one corrupt replay record with a visible retry prompt."""

        normalized_turn_id = str(turn_id or "").strip()
        if not normalized_turn_id:
            raise ValueError("Turn ID is required")
        normalized_attempt_no = normalize_delivery_attempt_no(expected_attempt_no)
        normalized_user_message = str(user_message or "").strip()
        if not normalized_user_message:
            raise ValueError("Recovery failure message is required")
        await self.initialize()
        async with sqlite_connection_async(self.db_path, profile="mixed") as db:
            await db.execute("BEGIN IMMEDIATE")
            try:
                delivery = list(
                    await db.execute_fetchall(
                        """
                    SELECT delivery_state, delivery_attempt_no
                    FROM chat_user_turn_delivery
                    WHERE turn_id = ?
                    """,
                        (normalized_turn_id,),
                    )
                )
                if not delivery:
                    await db.rollback()
                    return False
                delivery_row = delivery[0]
                if str(delivery_row["delivery_state"]) == CHAT_DELIVERY_STATE_TERMINAL:
                    await db.commit()
                    return True
                if int(delivery_row["delivery_attempt_no"] or 0) != normalized_attempt_no:
                    await db.rollback()
                    return False
                turn_rows = list(
                    await db.execute_fetchall(
                        """
                    SELECT session_id, user_id, updated_at_ms, run_id
                    FROM chat_turns
                    WHERE turn_id = ?
                    """,
                        (normalized_turn_id,),
                    )
                )
                if not turn_rows:
                    raise ChatTurnConflictError(
                        f"Turn '{normalized_turn_id}' has no persisted state"
                    )
                turn = turn_rows[0]
                session_id = str(turn["session_id"])
                user_id = str(turn["user_id"])
                visible_final = list(
                    await db.execute_fetchall(
                        """
                    SELECT message_id
                    FROM chat_messages
                    WHERE turn_id = ?
                      AND role = 'assistant'
                      AND message_kind = 'assistant_final'
                      AND is_final = 1
                      AND is_visible = 1
                    LIMIT 1
                    """,
                        (normalized_turn_id,),
                    )
                )
                if not visible_final:
                    sequence_rows = list(
                        await db.execute_fetchall(
                            """
                        SELECT COALESCE(MAX(sequence_no), 0) + 1 AS next_sequence
                        FROM chat_messages
                        WHERE session_id = ?
                        """,
                            (session_id,),
                        )
                    )
                    sequence_no = int(sequence_rows[0]["next_sequence"] or 1)
                    digest = hashlib.sha256(normalized_turn_id.encode("utf-8")).hexdigest()[:16]
                    await db.execute(
                        """
                        INSERT OR IGNORE INTO chat_messages (
                            message_id, session_id, turn_id, user_id, role,
                            message_kind, content_text, payload_json, is_final,
                            is_visible, created_at_ms, sequence_no,
                            replaces_message_id, replaced_by_message_id,
                            persona_id, reply_to_message_id, label_json
                        ) VALUES (?, ?, ?, ?, 'assistant', 'assistant_final',
                                  ?, ?, 1, 1, ?, ?, NULL, NULL, NULL, NULL, NULL)
                        """,
                        (
                            f"msg_delivery_recovery_{digest}",
                            session_id,
                            normalized_turn_id,
                            user_id,
                            normalized_user_message,
                            '{"delivery_recovery":{"status":"failed"}}',
                            int(updated_at_ms),
                            sequence_no,
                        ),
                    )
                    await db.execute(
                        """
                        UPDATE chat_sessions
                        SET history_version = history_version + 1
                        WHERE session_id = ?
                        """,
                        (session_id,),
                    )
                await db.execute(
                    """
                    UPDATE chat_turns
                    SET status = 'failed',
                        updated_at_ms = ?,
                        completed_at_ms = ?,
                        error_text = ?
                    WHERE turn_id = ?
                    """,
                    (
                        int(updated_at_ms),
                        int(updated_at_ms),
                        "Accepted user turn could not be recovered",
                        normalized_turn_id,
                    ),
                )
                quarantined_envelope = json.dumps(
                    {
                        "source": "delivery_recovery",
                        "user_id": user_id,
                        "session_id": session_id,
                        "turn_id": normalized_turn_id,
                        "message": normalized_user_message,
                        "attachments": [],
                        "metadata": {"quarantined": True},
                    },
                    ensure_ascii=False,
                    sort_keys=True,
                    separators=(",", ":"),
                )
                cursor = await db.execute(
                    """
                    UPDATE chat_user_turn_delivery
                    SET delivery_state = ?,
                        runtime_envelope_json = ?,
                        updated_at_ms = ?
                    WHERE turn_id = ?
                      AND delivery_attempt_no = ?
                      AND delivery_state IN (?, ?, ?)
                    """,
                    (
                        CHAT_DELIVERY_STATE_TERMINAL,
                        quarantined_envelope,
                        int(updated_at_ms),
                        normalized_turn_id,
                        normalized_attempt_no,
                        CHAT_DELIVERY_STATE_READY,
                        CHAT_DELIVERY_STATE_QUEUED,
                        CHAT_DELIVERY_STATE_ADMITTED,
                    ),
                )
                if int(cursor.rowcount or 0) != 1:
                    await db.rollback()
                    return False
                effective_run_id = str(turn["run_id"] or "").strip()
                if effective_run_id:
                    await self._promote_model_context_run_with_connection(
                        db,
                        session_id=session_id,
                        run_id=effective_run_id,
                        turn_id=normalized_turn_id,
                        outcome_text=normalized_user_message,
                        outcome_kind="assistant",
                        persona_id=None,
                        completed_at_ms=int(updated_at_ms),
                    )
                await db.commit()
                return True
            except BaseException:
                await db.rollback()
                raise


__all__ = ["ChatUserTurnDeliveryRecoveryPersistenceMixin"]
