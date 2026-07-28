"""Typed row conversion for the durable user-turn delivery ledger."""

from __future__ import annotations

import aiosqlite

from ..contracts import (
    CHAT_DELIVERY_STATE_ADMITTED,
    CHAT_DELIVERY_STATE_QUEUED,
    CHAT_DELIVERY_STATE_READY,
    CHAT_DELIVERY_STATE_TERMINAL,
    ChatUserTurnDeliveryRecord,
)
from ..user_turn_delivery.envelope import deserialize_runtime_envelope
from .user_turn_delivery_errors import ChatTurnConflictError


def normalize_delivery_attempt_no(value: object) -> int:
    """Require a non-negative integer delivery attempt."""

    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ValueError("Delivery attempt number must be a non-negative integer")
    return value


def normalize_command_id(value: object) -> int:
    """Require a positive integer runtime command identity."""

    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise ValueError("Runtime command ID must be a positive integer")
    return value


async def fetch_user_turn_delivery_state(
    db: aiosqlite.Connection,
    *,
    turn_id: str,
) -> tuple[bool, int, str, int | None, dict[str, object], str]:
    """Load the compact delivery state used by idempotent acceptance."""

    cursor = await db.execute(
        """
        SELECT projection_completed, delivery_attempt_no,
               delivery_state, current_command_id,
               runtime_envelope_json, request_fingerprint
        FROM chat_user_turn_delivery
        WHERE turn_id = ?
        """,
        (turn_id,),
    )
    row = await cursor.fetchone()
    if row is None:
        raise ChatTurnConflictError(f"Turn '{turn_id}' does not have a delivery state")
    return (
        bool(int(row[0])),
        int(row[1]),
        str(row[2]),
        int(row[3]) if row[3] is not None else None,
        deserialize_runtime_envelope(row[4]),
        str(row[5] or ""),
    )


async def fetch_user_turn_delivery_record_row(
    db: aiosqlite.Connection,
    *,
    turn_id: str,
) -> aiosqlite.Row | None:
    """Load the first user message joined to its delivery ledger row."""

    cursor = await db.execute(
        """
        SELECT messages.user_id,
               messages.session_id,
               delivery.turn_id,
               messages.message_id,
               delivery.projection_completed,
               delivery.delivery_attempt_no,
               delivery.delivery_state,
               delivery.current_command_id,
               delivery.runtime_envelope_json,
               delivery.request_fingerprint,
               messages.created_at_ms,
               messages.sequence_no
        FROM chat_user_turn_delivery AS delivery
        JOIN chat_messages AS messages
          ON messages.turn_id = delivery.turn_id
         AND messages.role = 'user'
         AND messages.message_kind = 'user_text'
        WHERE delivery.turn_id = ?
        ORDER BY messages.created_at_ms ASC,
                 messages.sequence_no ASC,
                 messages.message_id ASC
        LIMIT 1
        """,
        (turn_id,),
    )
    return await cursor.fetchone()


def row_to_user_turn_delivery_record(
    row: aiosqlite.Row,
) -> ChatUserTurnDeliveryRecord:
    """Convert one validated delivery row into its domain record."""

    delivery_state = str(row["delivery_state"] or "").strip()
    if delivery_state not in {
        CHAT_DELIVERY_STATE_READY,
        CHAT_DELIVERY_STATE_QUEUED,
        CHAT_DELIVERY_STATE_ADMITTED,
        CHAT_DELIVERY_STATE_TERMINAL,
    }:
        raise ValueError("Persisted user-turn delivery state is invalid")
    return ChatUserTurnDeliveryRecord(
        user_id=str(row["user_id"]),
        session_id=str(row["session_id"]),
        turn_id=str(row["turn_id"]),
        message_id=str(row["message_id"]),
        projection_completed=bool(int(row["projection_completed"] or 0)),
        delivery_attempt_no=int(row["delivery_attempt_no"] or 0),
        delivery_state=delivery_state,
        current_command_id=(
            int(row["current_command_id"]) if row["current_command_id"] is not None else None
        ),
        runtime_envelope=deserialize_runtime_envelope(row["runtime_envelope_json"]),
        request_fingerprint=str(row["request_fingerprint"] or ""),
        created_at_ms=int(row["created_at_ms"]),
        sequence_no=int(row["sequence_no"]),
    )


__all__ = [
    "fetch_user_turn_delivery_record_row",
    "fetch_user_turn_delivery_state",
    "normalize_command_id",
    "normalize_delivery_attempt_no",
    "row_to_user_turn_delivery_record",
]
