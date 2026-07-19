"""Atomic persistence for admitted chat delivery failures."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass

import aiosqlite

from ...core.sqlite import sqlite_connection_async
from ..contracts import (
    CHAT_DELIVERY_STATE_ADMITTED,
    CHAT_DELIVERY_STATE_TERMINAL,
    ChatMessageRecord,
)
from ..rhythm_completion import complete_visible_rhythm_segments
from .messages import MESSAGE_SELECT_COLUMNS
from .serialization import row_to_message


@dataclass(frozen=True, slots=True)
class ChatDeliveryFailureFinalization:
    """Result of attempting to close one exact admitted delivery."""

    applied: bool
    message_id: str | None = None
    wrote_failure: bool = False


class ChatDeliveryFailurePersistenceMixin:
    """Persist a visible retry surface and exact delivery terminal atomically."""

    db_path: str

    async def initialize(self) -> None:
        raise NotImplementedError

    async def finalize_user_turn_delivery_failure(
        self,
        *,
        turn_id: str,
        delivery_attempt_no: int,
        command_id: int,
        user_message: str,
        failure_stage: str,
        error_type: str,
        updated_at_ms: int,
    ) -> ChatDeliveryFailureFinalization:
        """Close one exact admitted attempt without affecting a successor."""

        normalized_turn_id = str(turn_id or "").strip()
        normalized_user_message = str(user_message or "").strip()
        normalized_stage = str(failure_stage or "").strip() or "unknown"
        normalized_error_type = str(error_type or "").strip() or "Exception"
        if not normalized_turn_id:
            raise ValueError("Turn ID is required")
        if not normalized_user_message:
            raise ValueError("Delivery failure message is required")
        if isinstance(delivery_attempt_no, bool) or int(delivery_attempt_no) < 0:
            raise ValueError("Delivery attempt number must be non-negative")
        if isinstance(command_id, bool) or int(command_id) <= 0:
            raise ValueError("Runtime command ID must be positive")
        normalized_attempt_no = int(delivery_attempt_no)
        normalized_command_id = int(command_id)
        now_ms = int(updated_at_ms)

        await self.initialize()
        async with sqlite_connection_async(self.db_path, profile="mixed") as db:
            db.row_factory = aiosqlite.Row
            await db.execute("BEGIN IMMEDIATE")
            try:
                delivery_row = await self._fetch_delivery_failure_owner(
                    db,
                    turn_id=normalized_turn_id,
                )
                if delivery_row is None:
                    await db.rollback()
                    return ChatDeliveryFailureFinalization(applied=False)
                if (
                    int(delivery_row["delivery_attempt_no"] or 0)
                    != normalized_attempt_no
                    or (
                        int(delivery_row["current_command_id"])
                        if delivery_row["current_command_id"] is not None
                        else None
                    )
                    != normalized_command_id
                ):
                    await db.rollback()
                    return ChatDeliveryFailureFinalization(applied=False)

                delivery_state = str(delivery_row["delivery_state"] or "")
                if delivery_state == CHAT_DELIVERY_STATE_TERMINAL:
                    await db.commit()
                    return ChatDeliveryFailureFinalization(applied=True)
                if delivery_state != CHAT_DELIVERY_STATE_ADMITTED:
                    await db.rollback()
                    return ChatDeliveryFailureFinalization(applied=False)

                messages = await self._fetch_turn_messages(
                    db,
                    turn_id=normalized_turn_id,
                )
                visible_final = next(
                    (
                        message
                        for message in reversed(messages)
                        if message.role == "assistant"
                        and message.message_kind == "assistant_final"
                        and message.is_visible
                        and message.is_final
                    ),
                    None,
                )
                complete_rhythm = complete_visible_rhythm_segments(
                    messages,
                    turn_id=normalized_turn_id,
                )
                message_id = (
                    visible_final.message_id if visible_final is not None else None
                )
                wrote_failure = False
                transcript_changed = False
                if visible_final is None and complete_rhythm is None:
                    message_id = self._failure_message_id(
                        turn_id=normalized_turn_id,
                        delivery_attempt_no=normalized_attempt_no,
                        command_id=normalized_command_id,
                    )
                    hidden = await db.execute(
                        """
                        UPDATE chat_messages
                        SET is_visible = 0
                        WHERE turn_id = ?
                          AND role = 'assistant'
                          AND message_kind IN (
                              'assistant_final',
                              'assistant_rhythm_segment'
                          )
                          AND is_visible = 1
                        """,
                        (normalized_turn_id,),
                    )
                    transcript_changed = int(hidden.rowcount or 0) > 0
                    inserted = await self._insert_delivery_failure_message(
                        db,
                        message_id=message_id,
                        session_id=str(delivery_row["session_id"]),
                        turn_id=normalized_turn_id,
                        user_id=str(delivery_row["user_id"]),
                        content=normalized_user_message,
                        delivery_attempt_no=normalized_attempt_no,
                        command_id=normalized_command_id,
                        failure_stage=normalized_stage,
                        created_at_ms=now_ms,
                    )
                    wrote_failure = inserted
                    transcript_changed = transcript_changed or inserted

                await db.execute(
                    """
                    UPDATE chat_turns
                    SET status = 'completed',
                        response_mode = CASE
                            WHEN ? = 1 THEN 'final_only'
                            ELSE response_mode
                        END,
                        updated_at_ms = ?,
                        completed_at_ms = ?,
                        error_text = ?
                    WHERE turn_id = ?
                    """,
                    (
                        1 if wrote_failure else 0,
                        now_ms,
                        now_ms,
                        (
                            "Chat task failed during "
                            f"{normalized_stage} ({normalized_error_type})"
                        ),
                        normalized_turn_id,
                    ),
                )
                terminal = await db.execute(
                    """
                    UPDATE chat_user_turn_delivery
                    SET delivery_state = ?,
                        updated_at_ms = ?
                    WHERE turn_id = ?
                      AND delivery_attempt_no = ?
                      AND delivery_state = ?
                      AND current_command_id = ?
                    """,
                    (
                        CHAT_DELIVERY_STATE_TERMINAL,
                        now_ms,
                        normalized_turn_id,
                        normalized_attempt_no,
                        CHAT_DELIVERY_STATE_ADMITTED,
                        normalized_command_id,
                    ),
                )
                if int(terminal.rowcount or 0) != 1:
                    await db.rollback()
                    return ChatDeliveryFailureFinalization(applied=False)
                if transcript_changed:
                    await db.execute(
                        """
                        UPDATE chat_sessions
                        SET history_version = history_version + 1
                        WHERE session_id = ?
                        """,
                        (str(delivery_row["session_id"]),),
                    )
                await db.commit()
                return ChatDeliveryFailureFinalization(
                    applied=True,
                    message_id=message_id,
                    wrote_failure=wrote_failure,
                )
            except BaseException:
                await db.rollback()
                raise

    @staticmethod
    async def _fetch_delivery_failure_owner(
        db: aiosqlite.Connection,
        *,
        turn_id: str,
    ) -> aiosqlite.Row | None:
        cursor = await db.execute(
            """
            SELECT delivery.delivery_attempt_no,
                   delivery.delivery_state,
                   delivery.current_command_id,
                   turns.session_id,
                   turns.user_id
            FROM chat_user_turn_delivery AS delivery
            JOIN chat_turns AS turns
              ON turns.turn_id = delivery.turn_id
            WHERE delivery.turn_id = ?
            """,
            (turn_id,),
        )
        return await cursor.fetchone()

    @staticmethod
    async def _fetch_turn_messages(
        db: aiosqlite.Connection,
        *,
        turn_id: str,
    ) -> list[ChatMessageRecord]:
        cursor = await db.execute(
            f"""
            SELECT {MESSAGE_SELECT_COLUMNS}
            FROM chat_messages
            WHERE turn_id = ?
            ORDER BY created_at_ms ASC, sequence_no ASC, message_id ASC
            """,
            (turn_id,),
        )
        return [row_to_message(row) for row in await cursor.fetchall()]

    @staticmethod
    async def _insert_delivery_failure_message(
        db: aiosqlite.Connection,
        *,
        message_id: str,
        session_id: str,
        turn_id: str,
        user_id: str,
        content: str,
        delivery_attempt_no: int,
        command_id: int,
        failure_stage: str,
        created_at_ms: int,
    ) -> bool:
        sequence_cursor = await db.execute(
            """
            SELECT COALESCE(MAX(sequence_no), 0) + 1 AS next_sequence
            FROM chat_messages
            WHERE session_id = ?
            """,
            (session_id,),
        )
        sequence_row = await sequence_cursor.fetchone()
        sequence_no = int(sequence_row["next_sequence"] or 1)
        interim_cursor = await db.execute(
            """
            SELECT message_id, persona_id, reply_to_message_id
            FROM chat_messages
            WHERE turn_id = ?
              AND role = 'assistant'
              AND message_kind = 'assistant_interim'
              AND is_visible = 1
            ORDER BY created_at_ms DESC, sequence_no DESC, message_id DESC
            LIMIT 1
            """,
            (turn_id,),
        )
        interim = await interim_cursor.fetchone()
        payload_json = json.dumps(
            {
                "delivery_failure": {
                    "status": "failed",
                    "retryable": True,
                    "stage": failure_stage,
                    "delivery_attempt_no": delivery_attempt_no,
                    "runtime_command_id": command_id,
                }
            },
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
        inserted = await db.execute(
            """
            INSERT OR IGNORE INTO chat_messages (
                message_id, session_id, turn_id, user_id, role,
                message_kind, content_text, payload_json, is_final,
                is_visible, created_at_ms, sequence_no,
                replaces_message_id, replaced_by_message_id,
                persona_id, reply_to_message_id, label_json
            ) VALUES (?, ?, ?, ?, 'assistant', 'assistant_final',
                      ?, ?, 1, 1, ?, ?, ?, NULL, ?, ?, NULL)
            """,
            (
                message_id,
                session_id,
                turn_id,
                user_id,
                content,
                payload_json,
                created_at_ms,
                sequence_no,
                str(interim["message_id"]) if interim is not None else None,
                interim["persona_id"] if interim is not None else None,
                interim["reply_to_message_id"] if interim is not None else None,
            ),
        )
        if int(inserted.rowcount or 0) == 1 and interim is not None:
            await db.execute(
                """
                UPDATE chat_messages
                SET replaced_by_message_id = ?
                WHERE message_id = ?
                """,
                (message_id, str(interim["message_id"])),
            )
        return int(inserted.rowcount or 0) == 1

    @staticmethod
    def _failure_message_id(
        *,
        turn_id: str,
        delivery_attempt_no: int,
        command_id: int,
    ) -> str:
        digest = hashlib.sha256(
            f"{turn_id}\0{delivery_attempt_no}\0{command_id}".encode("utf-8")
        ).hexdigest()[:16]
        return f"msg_delivery_failure_{digest}"


__all__ = [
    "ChatDeliveryFailureFinalization",
    "ChatDeliveryFailurePersistenceMixin",
]
