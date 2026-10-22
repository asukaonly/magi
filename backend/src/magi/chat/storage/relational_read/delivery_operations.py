"""Durable user-turn delivery recovery operations."""

from __future__ import annotations

from ..statements import statement

from ..relational import ChatRow, ChatReadConnection, ChatReadDatabase

import json
from typing import Any, Protocol, cast

from ...contracts import (
    CHAT_DELIVERY_STATE_READY,
    CHAT_RECOVERABLE_DELIVERY_STATES,
    ChatUserTurnDeliveryRecord,
)
from ...rhythm_completion import complete_rhythm_payloads
from .schema import (
    CHAT_MESSAGES_TABLE,
    CHAT_SESSIONS_TABLE,
    CHAT_TURNS_TABLE,
    CHAT_USER_TURN_DELIVERY_TABLE,
)

_BUMP_TARGETS_TABLE = "chat_delivery_attempt_bump_targets"
_BUMP_EXCLUSIONS_TABLE = "chat_delivery_attempt_bump_exclusions"
_BUMP_TERMINAL_RHYTHMS_TABLE = "chat_delivery_terminal_rhythms"
_DELIVERY_SELECT = statement("""
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
    FROM {part0} AS delivery
    JOIN {part1} AS messages
      ON messages.turn_id = delivery.turn_id
     AND messages.role = 'user'
     AND messages.message_kind = 'user_text'
     AND messages.message_id = (
         SELECT first_message.message_id
         FROM {part2} AS first_message
         WHERE first_message.turn_id = delivery.turn_id
           AND first_message.role = 'user'
           AND first_message.message_kind = 'user_text'
         ORDER BY first_message.created_at_ms ASC,
                  first_message.sequence_no ASC,
                  first_message.message_id ASC
         LIMIT 1
     )
    JOIN {part3} AS sessions
      ON sessions.session_id = messages.session_id
     AND sessions.user_id = messages.user_id
""", part0=CHAT_USER_TURN_DELIVERY_TABLE, part1=CHAT_MESSAGES_TABLE, part2=CHAT_MESSAGES_TABLE, part3=CHAT_SESSIONS_TABLE)
_DELIVERY_ORDER = """
    ORDER BY messages.created_at_ms ASC,
             messages.sequence_no ASC,
             messages.message_id ASC,
             delivery.turn_id ASC
"""


class _ChatDeliveryOperationsHost(Protocol):
    database: ChatReadDatabase

    def _get_conn(self) -> ChatReadConnection: ...


def _normalize_optional_identity(value: str | None, *, label: str) -> str | None:
    if value is None:
        return None
    normalized = str(value).strip()
    if not normalized:
        raise ValueError(f"{label} cannot be empty")
    return normalized


def _deserialize_runtime_envelope(value: object) -> dict[str, Any]:
    try:
        parsed = json.loads(str(value or "{}"))
    except (TypeError, ValueError, json.JSONDecodeError):
        return {}
    if not isinstance(parsed, dict):
        return {}
    return parsed


def _row_to_delivery_record(row: ChatRow) -> ChatUserTurnDeliveryRecord:
    return ChatUserTurnDeliveryRecord(
        user_id=str(row["user_id"]),
        session_id=str(row["session_id"]),
        turn_id=str(row["turn_id"]),
        message_id=str(row["message_id"]),
        projection_completed=bool(int(row["projection_completed"] or 0)),
        delivery_attempt_no=int(row["delivery_attempt_no"] or 0),
        delivery_state=str(row["delivery_state"]),
        current_command_id=(
            int(row["current_command_id"])
            if row["current_command_id"] is not None
            else None
        ),
        runtime_envelope=_deserialize_runtime_envelope(
            row["runtime_envelope_json"]
        ),
        request_fingerprint=str(row["request_fingerprint"] or ""),
        created_at_ms=int(row["created_at_ms"]),
        sequence_no=int(row["sequence_no"]),
    )


class ChatDeliveryOperationsMixin:
    """Query and invalidate durable user-turn delivery attempts."""

    def list_recoverable_user_turn_deliveries(
        self,
        user_id: str | None = None,
        session_id: str | None = None,
        limit: int = 1000,
        after: ChatUserTurnDeliveryRecord | None = None,
    ) -> list[ChatUserTurnDeliveryRecord]:
        """Return one keyset-paginated page in stable chat order."""
        host = cast(_ChatDeliveryOperationsHost, self)
        if not host.database.is_present():
            return []
        normalized_user_id = _normalize_optional_identity(user_id, label="User ID")
        normalized_session_id = _normalize_optional_identity(
            session_id,
            label="Session ID",
        )
        safe_limit = max(1, min(int(limit), 5000))
        states = sorted(CHAT_RECOVERABLE_DELIVERY_STATES)
        predicates = [
            f"(delivery.delivery_state IN ({', '.join('?' for _ in states)}) OR delivery.projection_completed = 0)",
            "messages.is_visible = 1",
            "sessions.deleted_at_ms IS NULL",
            "sessions.archived_at_ms IS NULL",
        ]
        params: list[object] = [*states]
        if normalized_user_id is not None:
            predicates.append("messages.user_id = ?")
            params.append(normalized_user_id)
        if normalized_session_id is not None:
            predicates.append("messages.session_id = ?")
            params.append(normalized_session_id)
        if after is not None:
            predicates.append(
                """
                (
                    messages.created_at_ms,
                    messages.sequence_no,
                    messages.message_id,
                    delivery.turn_id
                ) > (?, ?, ?, ?)
                """
            )
            params.extend(
                (
                    int(after.created_at_ms),
                    int(after.sequence_no),
                    str(after.message_id),
                    str(after.turn_id),
                )
            )
        params.append(safe_limit)
        rows = host._get_conn().execute(
            statement('\n            {part0}\n            WHERE {part1}\n            {part2}\n            LIMIT ?\n            ', part0=_DELIVERY_SELECT, part1=' AND '.join(predicates), part2=_DELIVERY_ORDER),
            tuple(params),
        ).fetchall()
        return [_row_to_delivery_record(row) for row in rows]

    def bump_nonterminal_user_turn_delivery_attempts(
        self,
        user_id: str,
        session_id: str,
        excluded_turn_ids: list[str],
        updated_at_ms: int,
        bump_survivors: bool = True,
    ) -> list[ChatUserTurnDeliveryRecord]:
        """Atomically terminate exclusions and optionally invalidate survivors."""
        host = cast(_ChatDeliveryOperationsHost, self)
        normalized_user_id = str(user_id or "").strip()
        normalized_session_id = str(session_id or "").strip()
        if not normalized_user_id or not normalized_session_id:
            raise ValueError("User ID and session ID are required")
        normalized_exclusions = sorted(
            {
                normalized
                for value in excluded_turn_ids
                if (normalized := str(value or "").strip())
            }
        )
        if not host.database.is_present():
            return []

        conn = host._get_conn()
        conn.begin_write()
        try:
            conn.execute(
                statement("""
                CREATE TEMP TABLE IF NOT EXISTS {part0} (
                    turn_id TEXT PRIMARY KEY
                )
                """, mysql="""
                CREATE TEMPORARY TABLE IF NOT EXISTS {part0} (
                    turn_id LONGTEXT CHARACTER SET utf8mb4 COLLATE utf8mb4_0900_bin NOT NULL,
            __key CHAR(64) CHARACTER SET ascii COLLATE ascii_bin GENERATED ALWAYS AS (SHA2(HEX(turn_id),256)) STORED,
            UNIQUE KEY(__key)
                )
                """, part0=_BUMP_TARGETS_TABLE)
            )
            conn.execute(
                statement("""
                CREATE TEMP TABLE IF NOT EXISTS {part0} (
                    turn_id TEXT PRIMARY KEY
                )
                """, mysql="""
                CREATE TEMPORARY TABLE IF NOT EXISTS {part0} (
                    turn_id LONGTEXT CHARACTER SET utf8mb4 COLLATE utf8mb4_0900_bin NOT NULL,
            __key CHAR(64) CHARACTER SET ascii COLLATE ascii_bin GENERATED ALWAYS AS (SHA2(HEX(turn_id),256)) STORED,
            UNIQUE KEY(__key)
                )
                """, part0=_BUMP_EXCLUSIONS_TABLE)
            )
            conn.execute(
                statement("""
                CREATE TEMP TABLE IF NOT EXISTS {part0} (
                    turn_id TEXT PRIMARY KEY
                )
                """, mysql="""
                CREATE TEMPORARY TABLE IF NOT EXISTS {part0} (
                    turn_id LONGTEXT CHARACTER SET utf8mb4 COLLATE utf8mb4_0900_bin NOT NULL,
            __key CHAR(64) CHARACTER SET ascii COLLATE ascii_bin GENERATED ALWAYS AS (SHA2(HEX(turn_id),256)) STORED,
            UNIQUE KEY(__key)
                )
                """, part0=_BUMP_TERMINAL_RHYTHMS_TABLE)
            )
            conn.execute(statement("""DELETE FROM {part0}""", part0=_BUMP_TARGETS_TABLE))
            conn.execute(statement("""DELETE FROM {part0}""", part0=_BUMP_EXCLUSIONS_TABLE))
            conn.execute(statement("""DELETE FROM {part0}""", part0=_BUMP_TERMINAL_RHYTHMS_TABLE))
            if normalized_exclusions:
                conn.executemany(
                    statement("""INSERT INTO {part0}(turn_id) VALUES (?)""", part0=_BUMP_EXCLUSIONS_TABLE),
                    ((turn_id,) for turn_id in normalized_exclusions),
                )
            recoverable_states = sorted(CHAT_RECOVERABLE_DELIVERY_STATES)
            rhythm_rows = conn.execute(
                statement("""
                SELECT rhythm_messages.turn_id,
                       rhythm_messages.payload_json
                FROM {part0} AS rhythm_messages
                JOIN {part1} AS delivery
                  ON delivery.turn_id = rhythm_messages.turn_id
                WHERE delivery.delivery_state IN (
                    {part2}
                )
                  AND rhythm_messages.role = 'assistant'
                  AND rhythm_messages.message_kind =
                      'assistant_rhythm_segment'
                  AND rhythm_messages.is_final = 1
                  AND rhythm_messages.is_visible = 1
                  AND EXISTS (
                      SELECT 1
                      FROM {part3} AS owner_messages
                      WHERE owner_messages.turn_id = delivery.turn_id
                        AND owner_messages.role = 'user'
                        AND owner_messages.message_kind = 'user_text'
                        AND owner_messages.user_id = ?
                        AND owner_messages.session_id = ?
                  )
                ORDER BY rhythm_messages.turn_id,
                         rhythm_messages.sequence_no,
                         rhythm_messages.message_id
                """, part0=CHAT_MESSAGES_TABLE, part1=CHAT_USER_TURN_DELIVERY_TABLE, part2=", ".join("?" for _ in recoverable_states), part3=CHAT_MESSAGES_TABLE),
                (
                    *recoverable_states,
                    normalized_user_id,
                    normalized_session_id,
                ),
            ).fetchall()
            rhythm_payloads_by_turn: dict[str, list[str]] = {}
            for row in rhythm_rows:
                rhythm_payloads_by_turn.setdefault(
                    str(row["turn_id"]),
                    [],
                ).append(str(row["payload_json"] or "{}"))
            complete_rhythm_turn_ids = [
                turn_id
                for turn_id, payloads in rhythm_payloads_by_turn.items()
                if complete_rhythm_payloads(payloads)
            ]
            if complete_rhythm_turn_ids:
                conn.executemany(
                    statement("""
                    INSERT INTO {part0}(turn_id)
                    VALUES (?)
                    """, part0=_BUMP_TERMINAL_RHYTHMS_TABLE),
                    ((turn_id,) for turn_id in complete_rhythm_turn_ids),
                )
            conn.execute(
                statement("""
                UPDATE {part0}
                SET status = 'completed',
                    updated_at_ms = MAX(
                        updated_at_ms,
                        COALESCE(
                            (
                                SELECT MAX(output_messages.created_at_ms)
                                FROM {part1} AS output_messages
                                WHERE output_messages.turn_id =
                                      {part2}.turn_id
                                  AND output_messages.role = 'assistant'
                                  AND output_messages.is_visible = 1
                                  AND output_messages.is_final = 1
                                  AND output_messages.message_kind IN (
                                      'assistant_final',
                                      'assistant_rhythm_segment'
                                  )
                            ),
                            ?
                        )
                    ),
                    completed_at_ms = MAX(
                        COALESCE(completed_at_ms, 0),
                        updated_at_ms,
                        COALESCE(
                            (
                                SELECT MAX(output_messages.created_at_ms)
                                FROM {part3} AS output_messages
                                WHERE output_messages.turn_id =
                                      {part4}.turn_id
                                  AND output_messages.role = 'assistant'
                                  AND output_messages.is_visible = 1
                                  AND output_messages.is_final = 1
                                  AND output_messages.message_kind IN (
                                      'assistant_final',
                                      'assistant_rhythm_segment'
                                  )
                            ),
                            ?
                        )
                    )
                WHERE status IN ('queued', 'running')
                  AND user_id = ?
                  AND session_id = ?
                  AND NOT EXISTS (
                      SELECT 1
                      FROM {part5} AS excluded
                      WHERE excluded.turn_id = {part6}.turn_id
                  )
                  AND (
                      EXISTS (
                          SELECT 1
                          FROM {part7} AS assistant_messages
                          WHERE assistant_messages.turn_id =
                                {part8}.turn_id
                            AND assistant_messages.role = 'assistant'
                            AND assistant_messages.message_kind =
                                'assistant_final'
                            AND assistant_messages.is_final = 1
                            AND assistant_messages.is_visible = 1
                      )
                      OR EXISTS (
                          SELECT 1
                          FROM {part9} AS rhythms
                          WHERE rhythms.turn_id = {part10}.turn_id
                      )
                  )
                  AND EXISTS (
                      SELECT 1
                      FROM {part11} AS delivery
                      WHERE delivery.turn_id = {part12}.turn_id
                        AND delivery.delivery_state IN (
                            {part13}
                        )
                  )
                """, mysql="""
                UPDATE {part0}
                SET status = 'completed',
                    updated_at_ms = GREATEST(
                        updated_at_ms,
                        COALESCE(
                            (
                                SELECT MAX(output_messages.created_at_ms)
                                FROM {part1} AS output_messages
                                WHERE output_messages.turn_id =
                                      {part2}.turn_id
                                  AND output_messages.role = 'assistant'
                                  AND output_messages.is_visible = 1
                                  AND output_messages.is_final = 1
                                  AND output_messages.message_kind IN (
                                      'assistant_final',
                                      'assistant_rhythm_segment'
                                  )
                            ),
                            ?
                        )
                    ),
                    completed_at_ms = GREATEST(
                        COALESCE(completed_at_ms, 0),
                        updated_at_ms,
                        COALESCE(
                            (
                                SELECT MAX(output_messages.created_at_ms)
                                FROM {part3} AS output_messages
                                WHERE output_messages.turn_id =
                                      {part4}.turn_id
                                  AND output_messages.role = 'assistant'
                                  AND output_messages.is_visible = 1
                                  AND output_messages.is_final = 1
                                  AND output_messages.message_kind IN (
                                      'assistant_final',
                                      'assistant_rhythm_segment'
                                  )
                            ),
                            ?
                        )
                    )
                WHERE status IN ('queued', 'running')
                  AND user_id = ?
                  AND session_id = ?
                  AND NOT EXISTS (
                      SELECT 1
                      FROM {part5} AS excluded
                      WHERE excluded.turn_id = {part6}.turn_id
                  )
                  AND (
                      EXISTS (
                          SELECT 1
                          FROM {part7} AS assistant_messages
                          WHERE assistant_messages.turn_id =
                                {part8}.turn_id
                            AND assistant_messages.role = 'assistant'
                            AND assistant_messages.message_kind =
                                'assistant_final'
                            AND assistant_messages.is_final = 1
                            AND assistant_messages.is_visible = 1
                      )
                      OR EXISTS (
                          SELECT 1
                          FROM {part9} AS rhythms
                          WHERE rhythms.turn_id = {part10}.turn_id
                      )
                  )
                  AND EXISTS (
                      SELECT 1
                      FROM {part11} AS delivery
                      WHERE delivery.turn_id = {part12}.turn_id
                        AND delivery.delivery_state IN (
                            {part13}
                        )
                  )
                """, part0=CHAT_TURNS_TABLE, part1=CHAT_MESSAGES_TABLE, part2=CHAT_TURNS_TABLE, part3=CHAT_MESSAGES_TABLE, part4=CHAT_TURNS_TABLE, part5=_BUMP_EXCLUSIONS_TABLE, part6=CHAT_TURNS_TABLE, part7=CHAT_MESSAGES_TABLE, part8=CHAT_TURNS_TABLE, part9=_BUMP_TERMINAL_RHYTHMS_TABLE, part10=CHAT_TURNS_TABLE, part11=CHAT_USER_TURN_DELIVERY_TABLE, part12=CHAT_TURNS_TABLE, part13=", ".join("?" for _ in recoverable_states)),
                (
                    int(updated_at_ms),
                    int(updated_at_ms),
                    normalized_user_id,
                    normalized_session_id,
                    *recoverable_states,
                ),
            )
            conn.execute(
                statement("""
                UPDATE {part0}
                SET delivery_state = 'terminal',
                    updated_at_ms = ?
                WHERE delivery_state IN (
                    {part1}
                )
                  AND NOT EXISTS (
                      SELECT 1
                      FROM {part2} AS excluded
                      WHERE excluded.turn_id =
                            {part3}.turn_id
                  )
                  AND EXISTS (
                      SELECT 1
                      FROM {part4} AS owner_messages
                      WHERE owner_messages.turn_id =
                            {part5}.turn_id
                        AND owner_messages.role = 'user'
                        AND owner_messages.message_kind = 'user_text'
                        AND owner_messages.user_id = ?
                        AND owner_messages.session_id = ?
                  )
                  AND (
                      EXISTS (
                          SELECT 1
                          FROM {part6} AS turns
                          WHERE turns.turn_id =
                                {part7}.turn_id
                            AND (
                                turns.status IN (
                                    'cancelled', 'merged', 'interrupted'
                                )
                                OR (
                                    turns.status = 'completed'
                                    AND LOWER(
                                        TRIM(COALESCE(turns.run_disposition, ''))
                                    ) != 'message'
                                    AND LOWER(
                                        TRIM(COALESCE(turns.response_mode, ''))
                                    ) IN ('none', 'reaction_only')
                                )
                            )
                      )
                      OR EXISTS (
                          SELECT 1
                          FROM {part8} AS assistant_messages
                          WHERE assistant_messages.turn_id =
                                {part9}.turn_id
                            AND assistant_messages.role = 'assistant'
                            AND assistant_messages.message_kind = 'assistant_final'
                            AND assistant_messages.is_final = 1
                            AND assistant_messages.is_visible = 1
                      )
                      OR EXISTS (
                          SELECT 1
                          FROM {part10} AS rhythms
                          WHERE rhythms.turn_id =
                                {part11}.turn_id
                      )
                  )
                """, part0=CHAT_USER_TURN_DELIVERY_TABLE, part1=", ".join("?" for _ in recoverable_states), part2=_BUMP_EXCLUSIONS_TABLE, part3=CHAT_USER_TURN_DELIVERY_TABLE, part4=CHAT_MESSAGES_TABLE, part5=CHAT_USER_TURN_DELIVERY_TABLE, part6=CHAT_TURNS_TABLE, part7=CHAT_USER_TURN_DELIVERY_TABLE, part8=CHAT_MESSAGES_TABLE, part9=CHAT_USER_TURN_DELIVERY_TABLE, part10=_BUMP_TERMINAL_RHYTHMS_TABLE, part11=CHAT_USER_TURN_DELIVERY_TABLE),
                (
                    int(updated_at_ms),
                    *recoverable_states,
                    normalized_user_id,
                    normalized_session_id,
                ),
            )
            conn.execute(
                statement("""
                UPDATE {part0}
                SET delivery_state = 'terminal',
                    updated_at_ms = ?
                WHERE delivery_state IN (
                    {part1}
                )
                  AND EXISTS (
                      SELECT 1
                      FROM {part2} AS excluded
                      WHERE excluded.turn_id = {part3}.turn_id
                  )
                  AND EXISTS (
                      SELECT 1
                      FROM {part4} AS messages
                      WHERE messages.turn_id = {part5}.turn_id
                        AND messages.role = 'user'
                        AND messages.message_kind = 'user_text'
                        AND messages.user_id = ?
                        AND messages.session_id = ?
                  )
                """, part0=CHAT_USER_TURN_DELIVERY_TABLE, part1=", ".join("?" for _ in recoverable_states), part2=_BUMP_EXCLUSIONS_TABLE, part3=CHAT_USER_TURN_DELIVERY_TABLE, part4=CHAT_MESSAGES_TABLE, part5=CHAT_USER_TURN_DELIVERY_TABLE),
                (
                    int(updated_at_ms),
                    *recoverable_states,
                    normalized_user_id,
                    normalized_session_id,
                ),
            )
            conn.execute(
                statement("""
                UPDATE {part0}
                SET status = 'cancelled',
                    updated_at_ms = ?,
                    completed_at_ms = COALESCE(completed_at_ms, ?),
                    error_text = COALESCE(error_text, 'privacy_delete')
                WHERE status IN ('queued', 'running', 'cancelling')
                  AND EXISTS (
                      SELECT 1
                      FROM {part1} AS excluded
                      WHERE excluded.turn_id = {part2}.turn_id
                  )
                  AND EXISTS (
                      SELECT 1
                      FROM {part3} AS messages
                      WHERE messages.turn_id = {part4}.turn_id
                        AND messages.role = 'user'
                        AND messages.message_kind = 'user_text'
                        AND messages.user_id = ?
                        AND messages.session_id = ?
                  )
                """, part0=CHAT_TURNS_TABLE, part1=_BUMP_EXCLUSIONS_TABLE, part2=CHAT_TURNS_TABLE, part3=CHAT_MESSAGES_TABLE, part4=CHAT_TURNS_TABLE),
                (
                    int(updated_at_ms),
                    int(updated_at_ms),
                    normalized_user_id,
                    normalized_session_id,
                ),
            )
            if not bump_survivors:
                conn.execute(statement("""DELETE FROM {part0}""", part0=_BUMP_TARGETS_TABLE))
                conn.execute(statement("""DELETE FROM {part0}""", part0=_BUMP_EXCLUSIONS_TABLE))
                conn.execute(statement("""DELETE FROM {part0}""", part0=_BUMP_TERMINAL_RHYTHMS_TABLE))
                conn.commit()
                return []
            conn.execute(
                statement("""
                INSERT INTO {part0}(turn_id)
                SELECT delivery.turn_id
                FROM {part1} AS delivery
                WHERE delivery.delivery_state IN (
                    {part2}
                )
                  AND NOT EXISTS (
                      SELECT 1
                      FROM {part3} AS excluded
                      WHERE excluded.turn_id = delivery.turn_id
                  )
                  AND EXISTS (
                      SELECT 1
                      FROM {part4} AS messages
                      JOIN {part5} AS sessions
                        ON sessions.session_id = messages.session_id
                       AND sessions.user_id = messages.user_id
                      WHERE messages.turn_id = delivery.turn_id
                        AND messages.role = 'user'
                        AND messages.message_kind = 'user_text'
                        AND messages.is_visible = 1
                        AND messages.user_id = ?
                        AND messages.session_id = ?
                        AND sessions.deleted_at_ms IS NULL
                        AND sessions.archived_at_ms IS NULL
                  )
                """, part0=_BUMP_TARGETS_TABLE, part1=CHAT_USER_TURN_DELIVERY_TABLE, part2=", ".join("?" for _ in recoverable_states), part3=_BUMP_EXCLUSIONS_TABLE, part4=CHAT_MESSAGES_TABLE, part5=CHAT_SESSIONS_TABLE),
                (*recoverable_states, normalized_user_id, normalized_session_id),
            )
            conn.execute(
                statement("""
                UPDATE {part0}
                SET delivery_attempt_no = delivery_attempt_no + 1,
                    delivery_state = ?,
                    current_command_id = NULL,
                    updated_at_ms = ?
                WHERE EXISTS (
                    SELECT 1
                    FROM {part1} AS targets
                    WHERE targets.turn_id = {part2}.turn_id
                )
                """, part0=CHAT_USER_TURN_DELIVERY_TABLE, part1=_BUMP_TARGETS_TABLE, part2=CHAT_USER_TURN_DELIVERY_TABLE),
                (CHAT_DELIVERY_STATE_READY, int(updated_at_ms)),
            )
            rows = conn.execute(
                statement('\n                {part0}\n                WHERE EXISTS (\n                    SELECT 1\n                    FROM {part1} AS targets\n                    WHERE targets.turn_id = delivery.turn_id\n                )\n                {part2}\n                ', part0=_DELIVERY_SELECT, part1=_BUMP_TARGETS_TABLE, part2=_DELIVERY_ORDER)
            ).fetchall()
            conn.execute(statement("""DELETE FROM {part0}""", part0=_BUMP_TARGETS_TABLE))
            conn.execute(statement("""DELETE FROM {part0}""", part0=_BUMP_EXCLUSIONS_TABLE))
            conn.execute(statement("""DELETE FROM {part0}""", part0=_BUMP_TERMINAL_RHYTHMS_TABLE))
            conn.commit()
        except BaseException:
            conn.rollback()
            raise
        return [_row_to_delivery_record(row) for row in rows]


__all__ = ["ChatDeliveryOperationsMixin"]
