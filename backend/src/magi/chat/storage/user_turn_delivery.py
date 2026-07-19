"""Durable acceptance and delivery state for user chat turns."""

from __future__ import annotations

import asyncio
import hashlib
import json
from typing import Any
import uuid

import aiosqlite

from ...core.sqlite import sqlite_connection_async
from magi.core.chat_assets.mutations import chat_asset_mutation_guarded_if
from ..asset_validation import has_managed_asset_payloads
from ..contracts import (
    CHAT_DELIVERY_STATE_ADMITTED,
    CHAT_DELIVERY_STATE_QUEUED,
    CHAT_DELIVERY_STATE_READY,
    CHAT_DELIVERY_STATE_TERMINAL,
    ChatMessageRecord,
    ChatSessionRecord,
    ChatUserTurnDeliveryRecord,
    CreateUserTurnResult,
)
from ..rhythm_completion import complete_rhythm_payloads
from ..workspace_identity import claim_workspace_identity
from .messages import MESSAGE_SELECT_COLUMNS
from .serialization import build_user_message_payload_json


class ChatTurnConflictError(ValueError):
    """Raised when one client turn id is reused for different user input."""


class ChatUserTurnDeliveryPersistenceMixin:
    """Persist accepted user turns and their exact delivery attempts."""

    async def create_user_turn(
        self,
        *,
        session_id: str,
        user_id: str,
        turn_id: str,
        message_text: str,
        attachment_payloads: list[dict[str, object]] | None = None,
        message_payload: dict[str, object] | None = None,
        created_at_ms: int,
        reply_to_message_id: str | None = None,
        run_id: str | None = None,
        run_revision: int = 0,
        run_disposition: str | None = None,
        persona_id: str | None = None,
        runtime_envelope: dict[str, object] | None = None,
        request_fingerprint: str = "",
    ) -> ChatMessageRecord:
        """Create a user turn and its first transcript message transactionally."""
        result = await self.create_user_turn_once(
            session_id=session_id,
            user_id=user_id,
            turn_id=turn_id,
            message_text=message_text,
            attachment_payloads=attachment_payloads,
            message_payload=message_payload,
            created_at_ms=created_at_ms,
            reply_to_message_id=reply_to_message_id,
            run_id=run_id,
            run_revision=run_revision,
            run_disposition=run_disposition,
            persona_id=persona_id,
            runtime_envelope=runtime_envelope,
            request_fingerprint=request_fingerprint,
        )
        return result.message

    @chat_asset_mutation_guarded_if(
        "attachment_payloads",
        has_managed_asset_payloads,
    )
    async def create_user_turn_once(
        self,
        *,
        session_id: str,
        user_id: str,
        turn_id: str,
        message_text: str,
        attachment_payloads: list[dict[str, object]] | None = None,
        message_payload: dict[str, object] | None = None,
        created_at_ms: int,
        reply_to_message_id: str | None = None,
        run_id: str | None = None,
        run_revision: int = 0,
        run_disposition: str | None = None,
        persona_id: str | None = None,
        runtime_envelope: dict[str, object] | None = None,
        request_fingerprint: str = "",
    ) -> CreateUserTurnResult:
        """Create one user turn or return the matching committed retry."""
        await self.initialize()
        session_preview = str(message_text or "").strip()[:120]
        message = self._build_user_turn_message(
            session_id=session_id,
            user_id=user_id,
            turn_id=turn_id,
            message_text=message_text,
            attachment_payloads=attachment_payloads,
            message_payload=message_payload,
            created_at_ms=created_at_ms,
            persona_id=persona_id,
            reply_to_message_id=reply_to_message_id,
        )
        normalized_runtime_envelope = _normalize_runtime_envelope(runtime_envelope)
        runtime_envelope_json = _serialize_runtime_envelope(normalized_runtime_envelope)
        normalized_request_fingerprint = str(request_fingerprint or "").strip()
        committed_workspace_path: str | None = None
        previous_workspace_path: str | None = None
        async with sqlite_connection_async(self.db_path, profile="mixed") as db:
            db.row_factory = aiosqlite.Row
            await db.execute("BEGIN IMMEDIATE")
            try:
                existing_message = await self._fetch_existing_user_turn_message(
                    db,
                    turn_id=turn_id,
                )
                if existing_message is not None:
                    self._validate_user_turn_retry(
                        existing_message,
                        requested_message=message,
                    )
                    (
                        projection_completed,
                        delivery_attempt_no,
                        delivery_state,
                        current_command_id,
                        persisted_runtime_envelope,
                        persisted_request_fingerprint,
                    ) = await self._fetch_user_turn_delivery_state(
                        db,
                        turn_id=turn_id,
                    )
                    if persisted_request_fingerprint != normalized_request_fingerprint:
                        raise ChatTurnConflictError(
                            f"Turn '{turn_id}' was retried with a different delivery envelope"
                        )
                    await db.commit()
                    return CreateUserTurnResult(
                        message=existing_message,
                        created=False,
                        projection_completed=projection_completed,
                        delivery_attempt_no=delivery_attempt_no,
                        delivery_state=delivery_state,
                        current_command_id=current_command_id,
                        runtime_envelope=persisted_runtime_envelope,
                    )

                existing_session = await self._fetch_session_row(db, session_id=session_id)
                self._validate_user_turn_session(
                    existing_session,
                    session_id=session_id,
                    user_id=user_id,
                )
                previous_workspace_path = _row_optional_text(
                    existing_session,
                    "workspace_path",
                )
                committed_workspace_path = (
                    _runtime_workspace_path(normalized_runtime_envelope) or previous_workspace_path
                )
                await self._upsert_user_turn_session(
                    db,
                    existing_session=existing_session,
                    session_id=session_id,
                    user_id=user_id,
                    session_preview=session_preview,
                    created_at_ms=created_at_ms,
                    workspace_path=committed_workspace_path,
                )
                await self._insert_user_turn_row(
                    db,
                    session_id=session_id,
                    user_id=user_id,
                    turn_id=turn_id,
                    created_at_ms=created_at_ms,
                    run_id=run_id,
                    run_revision=run_revision,
                    run_disposition=run_disposition,
                )
                await self._insert_user_message_row(db, message)
                if has_managed_asset_payloads(attachment_payloads):
                    await self._replace_message_attachments(
                        db,
                        message=message,
                        attachment_payloads=attachment_payloads,
                    )
                await db.execute(
                    """
                    INSERT INTO chat_user_turn_delivery (
                        turn_id,
                        projection_completed,
                        delivery_attempt_no,
                        delivery_state,
                        current_command_id,
                        runtime_envelope_json,
                        request_fingerprint,
                        created_at_ms,
                        updated_at_ms
                    ) VALUES (?, 0, 0, ?, NULL, ?, ?, ?, ?)
                    """,
                    (
                        turn_id,
                        CHAT_DELIVERY_STATE_READY,
                        runtime_envelope_json,
                        normalized_request_fingerprint,
                        int(created_at_ms),
                        int(created_at_ms),
                    ),
                )
                await db.commit()
            except BaseException:
                await db.rollback()
                raise
        if committed_workspace_path is not None:
            await asyncio.to_thread(
                claim_workspace_identity,
                committed_workspace_path,
            )
        return CreateUserTurnResult(
            message=message,
            created=True,
            projection_completed=False,
            delivery_attempt_no=0,
            delivery_state=CHAT_DELIVERY_STATE_READY,
            current_command_id=None,
            runtime_envelope=normalized_runtime_envelope,
        )

    @staticmethod
    def _validate_user_turn_session(
        existing_session: Any,
        *,
        session_id: str,
        user_id: str,
    ) -> None:
        """Prevent a new turn from taking over or reviving an existing session."""
        if existing_session is None:
            return
        if str(existing_session["session_id"] or "") != str(session_id):
            raise ChatTurnConflictError(
                f"Session '{session_id}' conflicts with an existing session identifier"
            )
        if str(existing_session["user_id"] or "") != str(user_id):
            raise ChatTurnConflictError(f"Session '{session_id}' belongs to a different user")
        if (
            existing_session["archived_at_ms"] is not None
            or existing_session["deleted_at_ms"] is not None
        ):
            raise ChatTurnConflictError(f"Session '{session_id}' is not available")

    async def load_user_turn_once(
        self,
        *,
        turn_id: str,
        request_fingerprint: str,
    ) -> CreateUserTurnResult | None:
        """Load a committed user turn before repeating preparation side effects."""
        await self.initialize()
        async with sqlite_connection_async(self.db_path, profile="mixed") as db:
            db.row_factory = aiosqlite.Row
            existing_message = await self._fetch_existing_user_turn_message(
                db,
                turn_id=turn_id,
            )
            if existing_message is None:
                return None
            (
                projection_completed,
                delivery_attempt_no,
                delivery_state,
                current_command_id,
                runtime_envelope,
                persisted_request_fingerprint,
            ) = await self._fetch_user_turn_delivery_state(db, turn_id=turn_id)
        if persisted_request_fingerprint != str(request_fingerprint or "").strip():
            raise ChatTurnConflictError(f"Turn '{turn_id}' was retried with a different request")
        return CreateUserTurnResult(
            message=existing_message,
            created=False,
            projection_completed=projection_completed,
            delivery_attempt_no=delivery_attempt_no,
            delivery_state=delivery_state,
            current_command_id=current_command_id,
            runtime_envelope=runtime_envelope,
        )

    async def mark_user_turn_projection_completed(
        self,
        *,
        turn_id: str,
        updated_at_ms: int,
    ) -> None:
        """Mark the L1 projection stage complete for one persisted user turn."""
        await self._mark_user_turn_delivery_stage(
            turn_id=turn_id,
            column="projection_completed",
            updated_at_ms=updated_at_ms,
        )

    async def get_user_turn_delivery(
        self,
        *,
        turn_id: str,
    ) -> ChatUserTurnDeliveryRecord | None:
        """Load the current delivery attempt for one accepted user turn."""
        normalized_turn_id = str(turn_id or "").strip()
        if not normalized_turn_id:
            raise ValueError("Turn ID is required")
        await self.initialize()
        async with sqlite_connection_async(self.db_path, profile="mixed") as db:
            row = await self._fetch_user_turn_delivery_record_row(
                db,
                turn_id=normalized_turn_id,
            )
        return _row_to_user_turn_delivery_record(row) if row is not None else None

    async def prepare_user_turn_delivery_attempt(
        self,
        *,
        turn_id: str,
        expected_attempt_no: int,
        updated_at_ms: int,
    ) -> ChatUserTurnDeliveryRecord | None:
        """Atomically invalidate one non-terminal attempt and prepare its successor."""
        normalized_turn_id = str(turn_id or "").strip()
        if not normalized_turn_id:
            raise ValueError("Turn ID is required")
        normalized_attempt_no = _normalize_delivery_attempt_no(expected_attempt_no)
        await self.initialize()
        async with sqlite_connection_async(self.db_path, profile="mixed") as db:
            await db.execute("BEGIN IMMEDIATE")
            try:
                cursor = await db.execute(
                    """
                    UPDATE chat_user_turn_delivery
                    SET delivery_attempt_no = delivery_attempt_no + 1,
                        delivery_state = ?,
                        current_command_id = NULL,
                        updated_at_ms = ?
                    WHERE turn_id = ?
                      AND delivery_attempt_no = ?
                      AND delivery_state != ?
                    """,
                    (
                        CHAT_DELIVERY_STATE_READY,
                        int(updated_at_ms),
                        normalized_turn_id,
                        normalized_attempt_no,
                        CHAT_DELIVERY_STATE_TERMINAL,
                    ),
                )
                if int(cursor.rowcount or 0) != 1:
                    await db.rollback()
                    return None
                row = await self._fetch_user_turn_delivery_record_row(
                    db,
                    turn_id=normalized_turn_id,
                )
                await db.commit()
            except BaseException:
                await db.rollback()
                raise
        if row is None:
            raise ChatTurnConflictError(
                f"Turn '{normalized_turn_id}' lost its delivery state"
            )
        return _row_to_user_turn_delivery_record(row)

    async def mark_user_turn_delivery_queued(
        self,
        *,
        turn_id: str,
        delivery_attempt_no: int,
        command_id: int,
        updated_at_ms: int,
    ) -> bool:
        """Attach the runtime command that durably carries one ready attempt."""
        return await self._transition_user_turn_delivery(
            turn_id=turn_id,
            delivery_attempt_no=delivery_attempt_no,
            command_id=command_id,
            expected_state=CHAT_DELIVERY_STATE_READY,
            next_state=CHAT_DELIVERY_STATE_QUEUED,
            attach_command=True,
            updated_at_ms=updated_at_ms,
        )

    async def mark_user_turn_delivery_admitted(
        self,
        *,
        turn_id: str,
        delivery_attempt_no: int,
        command_id: int,
        updated_at_ms: int,
    ) -> bool:
        """Claim one current command before in-memory admission.

        The runtime queue and chat ledger live in separate databases.  A queue
        consumer may therefore observe a committed command before ingress has
        recorded ``queued``.  The same attempt may move directly from ``ready``
        to ``admitted`` while atomically attaching that command identity.
        """
        normalized_turn_id = str(turn_id or "").strip()
        if not normalized_turn_id:
            raise ValueError("Turn ID is required")
        normalized_attempt_no = _normalize_delivery_attempt_no(delivery_attempt_no)
        normalized_command_id = _normalize_command_id(command_id)
        await self.initialize()
        async with sqlite_connection_async(self.db_path, profile="mixed") as db:
            await db.execute("BEGIN IMMEDIATE")
            try:
                cursor = await db.execute(
                    """
                    UPDATE chat_user_turn_delivery
                    SET delivery_state = ?,
                        current_command_id = ?,
                        updated_at_ms = ?
                    WHERE turn_id = ?
                      AND delivery_attempt_no = ?
                      AND (
                          (
                              delivery_state = ?
                              AND current_command_id = ?
                          )
                          OR (
                              delivery_state = ?
                              AND current_command_id IS NULL
                          )
                      )
                    """,
                    (
                        CHAT_DELIVERY_STATE_ADMITTED,
                        normalized_command_id,
                        int(updated_at_ms),
                        normalized_turn_id,
                        normalized_attempt_no,
                        CHAT_DELIVERY_STATE_QUEUED,
                        normalized_command_id,
                        CHAT_DELIVERY_STATE_READY,
                    ),
                )
                changed = int(cursor.rowcount or 0) == 1
                await db.commit()
            except BaseException:
                await db.rollback()
                raise
        return changed

    async def mark_user_turn_delivery_terminal(
        self,
        *,
        turn_id: str,
        delivery_attempt_no: int,
        command_id: int,
        updated_at_ms: int,
    ) -> bool:
        """Mark the exact admitted attempt terminal after response completion."""
        return await self._transition_user_turn_delivery(
            turn_id=turn_id,
            delivery_attempt_no=delivery_attempt_no,
            command_id=command_id,
            expected_state=CHAT_DELIVERY_STATE_ADMITTED,
            next_state=CHAT_DELIVERY_STATE_TERMINAL,
            attach_command=False,
            updated_at_ms=updated_at_ms,
        )

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
        normalized_attempt_no = _normalize_delivery_attempt_no(expected_attempt_no)
        await self.initialize()
        async with sqlite_connection_async(self.db_path, profile="mixed") as db:
            db.row_factory = aiosqlite.Row
            await db.execute("BEGIN IMMEDIATE")
            try:
                owner_rows = await db.execute_fetchall(
                    """
                    SELECT delivery.delivery_state,
                           delivery.delivery_attempt_no,
                           turns.status,
                           turns.response_mode,
                           turns.run_disposition,
                           turns.updated_at_ms
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
                if not owner_rows:
                    await db.rollback()
                    return False
                owner = owner_rows[0]
                output_rows = await db.execute_fetchall(
                    """
                    SELECT message_kind, is_final, payload_json, created_at_ms
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
                response_mode = (
                    str(owner["response_mode"] or "").strip().lower()
                )
                run_disposition = (
                    str(owner["run_disposition"] or "").strip().lower()
                )
                has_terminal_surface = (
                    has_visible_final
                    or has_complete_rhythm
                    or turn_status in {"cancelled", "merged", "interrupted"}
                    or (
                        turn_status == "completed"
                        and run_disposition not in {"augment", "defer", "steer"}
                        and response_mode in {"none", "reaction_only"}
                    )
                )
                if not has_terminal_surface:
                    await db.rollback()
                    return False
                if (
                    turn_status in {"queued", "running"}
                    and (has_visible_final or has_complete_rhythm)
                ):
                    completed_at_ms = max(
                        int(owner["updated_at_ms"] or 0),
                        *(
                            int(row["created_at_ms"] or 0)
                            for row in output_rows
                        ),
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
        normalized_attempt_no = _normalize_delivery_attempt_no(expected_attempt_no)
        normalized_user_message = str(user_message or "").strip()
        if not normalized_user_message:
            raise ValueError("Recovery failure message is required")
        await self.initialize()
        async with sqlite_connection_async(self.db_path, profile="mixed") as db:
            db.row_factory = aiosqlite.Row
            await db.execute("BEGIN IMMEDIATE")
            try:
                delivery = await db.execute_fetchall(
                    """
                    SELECT delivery_state, delivery_attempt_no
                    FROM chat_user_turn_delivery
                    WHERE turn_id = ?
                    """,
                    (normalized_turn_id,),
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
                turn_rows = await db.execute_fetchall(
                    """
                    SELECT session_id, user_id, updated_at_ms
                    FROM chat_turns
                    WHERE turn_id = ?
                    """,
                    (normalized_turn_id,),
                )
                if not turn_rows:
                    raise ChatTurnConflictError(
                        f"Turn '{normalized_turn_id}' has no persisted state"
                    )
                turn = turn_rows[0]
                session_id = str(turn["session_id"])
                user_id = str(turn["user_id"])
                visible_final = await db.execute_fetchall(
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
                if not visible_final:
                    sequence_rows = await db.execute_fetchall(
                        """
                        SELECT COALESCE(MAX(sequence_no), 0) + 1 AS next_sequence
                        FROM chat_messages
                        WHERE session_id = ?
                        """,
                        (session_id,),
                    )
                    sequence_no = int(sequence_rows[0]["next_sequence"] or 1)
                    digest = hashlib.sha256(
                        normalized_turn_id.encode("utf-8")
                    ).hexdigest()[:16]
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
                await db.commit()
                return True
            except BaseException:
                await db.rollback()
                raise

    async def _transition_user_turn_delivery(
        self,
        *,
        turn_id: str,
        delivery_attempt_no: int,
        command_id: int,
        expected_state: str,
        next_state: str,
        attach_command: bool,
        updated_at_ms: int,
    ) -> bool:
        normalized_turn_id = str(turn_id or "").strip()
        if not normalized_turn_id:
            raise ValueError("Turn ID is required")
        normalized_attempt_no = _normalize_delivery_attempt_no(delivery_attempt_no)
        normalized_command_id = _normalize_command_id(command_id)
        await self.initialize()
        if attach_command:
            statement = """
                UPDATE chat_user_turn_delivery
                SET delivery_state = ?,
                    current_command_id = ?,
                    updated_at_ms = ?
                WHERE turn_id = ?
                  AND delivery_attempt_no = ?
                  AND delivery_state = ?
                  AND current_command_id IS NULL
            """
            params: tuple[object, ...] = (
                next_state,
                normalized_command_id,
                int(updated_at_ms),
                normalized_turn_id,
                normalized_attempt_no,
                expected_state,
            )
        else:
            statement = """
                UPDATE chat_user_turn_delivery
                SET delivery_state = ?,
                    updated_at_ms = ?
                WHERE turn_id = ?
                  AND delivery_attempt_no = ?
                  AND delivery_state = ?
                  AND current_command_id = ?
            """
            params = (
                next_state,
                int(updated_at_ms),
                normalized_turn_id,
                normalized_attempt_no,
                expected_state,
                normalized_command_id,
            )
        async with sqlite_connection_async(self.db_path, profile="mixed") as db:
            await db.execute("BEGIN IMMEDIATE")
            try:
                cursor = await db.execute(statement, params)
                changed = int(cursor.rowcount or 0) == 1
                await db.commit()
            except BaseException:
                await db.rollback()
                raise
        return changed

    async def _mark_user_turn_delivery_stage(
        self,
        *,
        turn_id: str,
        column: str,
        updated_at_ms: int,
    ) -> None:
        if column != "projection_completed":
            raise ValueError(f"Unsupported user-turn delivery stage: {column}")
        await self.initialize()
        async with sqlite_connection_async(self.db_path, profile="mixed") as db:
            await db.execute("BEGIN IMMEDIATE")
            try:
                cursor = await db.execute(
                    f"""
                    UPDATE chat_user_turn_delivery
                    SET {column} = 1, updated_at_ms = ?
                    WHERE turn_id = ?
                    """,
                    (int(updated_at_ms), turn_id),
                )
                if int(cursor.rowcount or 0) != 1:
                    raise ChatTurnConflictError(
                        f"Turn '{turn_id}' does not have a delivery state"
                    )
                await db.commit()
            except BaseException:
                await db.rollback()
                raise

    @staticmethod
    async def _fetch_user_turn_delivery_state(
        db: aiosqlite.Connection,
        *,
        turn_id: str,
    ) -> tuple[bool, int, str, int | None, dict[str, Any], str]:
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
            _deserialize_runtime_envelope(row[4]),
            str(row[5] or ""),
        )

    @staticmethod
    async def _fetch_user_turn_delivery_record_row(
        db: aiosqlite.Connection,
        *,
        turn_id: str,
    ) -> aiosqlite.Row | None:
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

    async def _fetch_existing_user_turn_message(
        self,
        db: aiosqlite.Connection,
        *,
        turn_id: str,
    ) -> ChatMessageRecord | None:
        cursor = await db.execute(
            f"""
            SELECT {MESSAGE_SELECT_COLUMNS}
            FROM chat_messages
            WHERE turn_id = ?
              AND role = 'user'
              AND message_kind = 'user_text'
            ORDER BY created_at_ms ASC, sequence_no ASC
            LIMIT 1
            """,
            (turn_id,),
        )
        row = await cursor.fetchone()
        if row is None:
            turn_cursor = await db.execute(
                "SELECT 1 FROM chat_turns WHERE turn_id = ? LIMIT 1",
                (turn_id,),
            )
            if await turn_cursor.fetchone() is not None:
                raise ChatTurnConflictError(
                    f"Turn '{turn_id}' exists without a committed user message"
                )
            return None
        return self._row_to_message(row)

    @staticmethod
    def _validate_user_turn_retry(
        existing_message: ChatMessageRecord,
        *,
        requested_message: ChatMessageRecord,
    ) -> None:
        comparable_existing = (
            existing_message.session_id,
            existing_message.user_id,
            existing_message.content_text or "",
            existing_message.payload_json,
            existing_message.reply_to_message_id,
        )
        comparable_requested = (
            requested_message.session_id,
            requested_message.user_id,
            requested_message.content_text or "",
            requested_message.payload_json,
            requested_message.reply_to_message_id,
        )
        if comparable_existing != comparable_requested:
            raise ChatTurnConflictError(
                f"Turn '{requested_message.turn_id}' was already used for different input"
            )

    def _build_user_turn_message(
        self,
        *,
        session_id: str,
        user_id: str,
        turn_id: str,
        message_text: str,
        attachment_payloads: list[dict[str, object]] | None,
        message_payload: dict[str, object] | None,
        created_at_ms: int,
        persona_id: str | None,
        reply_to_message_id: str | None,
    ) -> ChatMessageRecord:
        return ChatMessageRecord(
            message_id=f"msg_{uuid.uuid4().hex[:16]}",
            session_id=session_id,
            turn_id=turn_id,
            user_id=user_id,
            role="user",
            message_kind="user_text",
            content_text=message_text,
            payload_json=self._build_user_message_payload_json(
                attachment_payloads,
                message_payload,
            ),
            is_final=True,
            is_visible=True,
            created_at_ms=created_at_ms,
            sequence_no=1,
            replaces_message_id=None,
            replaced_by_message_id=None,
            persona_id=str(persona_id or "").strip() or None,
            reply_to_message_id=str(reply_to_message_id or "").strip() or None,
        )

    async def _upsert_user_turn_session(
        self,
        db: aiosqlite.Connection,
        *,
        existing_session: Any,
        session_id: str,
        user_id: str,
        session_preview: str,
        created_at_ms: int,
        workspace_path: str | None,
    ) -> None:
        await self._upsert_session_with_connection(
            db,
            self._build_user_turn_session_record(
                existing_session=existing_session,
                session_id=session_id,
                user_id=user_id,
                session_preview=session_preview,
                created_at_ms=created_at_ms,
                workspace_path=workspace_path,
            ),
        )

    @staticmethod
    def _build_user_turn_session_record(
        *,
        existing_session: Any,
        session_id: str,
        user_id: str,
        session_preview: str,
        created_at_ms: int,
        workspace_path: str | None,
    ) -> ChatSessionRecord:
        return ChatSessionRecord(
            session_id=session_id,
            user_id=user_id,
            title=_row_text(existing_session, "title"),
            title_overridden=_row_bool(existing_session, "title_overridden"),
            summary=_row_text(existing_session, "summary"),
            created_at_ms=_row_int(existing_session, "created_at_ms", created_at_ms),
            updated_at_ms=created_at_ms,
            last_message_at_ms=created_at_ms,
            last_user_message_at_ms=created_at_ms,
            last_message_preview=session_preview,
            last_user_message_preview=session_preview,
            message_count=_row_int(existing_session, "message_count", 0) + 1,
            workspace_path=workspace_path,
            history_version=_row_int(existing_session, "history_version", 0) + 1,
            archived_at_ms=_row_optional_int(existing_session, "archived_at_ms"),
            deleted_at_ms=_row_optional_int(existing_session, "deleted_at_ms"),
        )

    @staticmethod
    async def _insert_user_turn_row(
        db: aiosqlite.Connection,
        *,
        session_id: str,
        user_id: str,
        turn_id: str,
        created_at_ms: int,
        run_id: str | None,
        run_revision: int,
        run_disposition: str | None,
    ) -> None:
        await db.execute(
            """
            INSERT INTO chat_turns (
                turn_id,
                session_id,
                user_id,
                trace_id,
                orchestration_id,
                status,
                response_mode,
                execution_mode,
                ux_plan_json,
                created_at_ms,
                updated_at_ms,
                completed_at_ms,
                error_text,
                run_id,
                run_revision,
                run_disposition,
                response_anchor_turn_id,
                superseded_by_turn_id,
                supersession_reason
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(turn_id) DO NOTHING
            """,
            (
                turn_id,
                session_id,
                user_id,
                None,
                None,
                "queued",
                "final_only",
                None,
                "{}",
                created_at_ms,
                created_at_ms,
                None,
                None,
                run_id,
                run_revision,
                run_disposition,
                turn_id,
                None,
                None,
            ),
        )

    async def _insert_user_message_row(
        self,
        db: aiosqlite.Connection,
        message: ChatMessageRecord,
    ) -> None:
        await db.execute(
            """
            INSERT OR REPLACE INTO chat_messages (
                message_id,
                session_id,
                turn_id,
                user_id,
                role,
                message_kind,
                content_text,
                payload_json,
                is_final,
                is_visible,
                created_at_ms,
                sequence_no,
                replaces_message_id,
                replaced_by_message_id,
                persona_id,
                reply_to_message_id,
                label_json
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                message.message_id,
                message.session_id,
                message.turn_id,
                message.user_id,
                message.role,
                message.message_kind,
                message.content_text,
                message.payload_json,
                1,
                1,
                message.created_at_ms,
                message.sequence_no,
                None,
                None,
                message.persona_id,
                message.reply_to_message_id,
                self._serialize_message_label(message.label),
            ),
        )

    @staticmethod
    def _build_user_message_payload_json(
        attachment_payloads: list[dict[str, object]] | None,
        message_payload: dict[str, object] | None = None,
    ) -> str:
        return build_user_message_payload_json(attachment_payloads, message_payload)

def _row_text(row: Any, key: str) -> str:
    if row is None:
        return ""
    return str(row[key] or "")


def _row_bool(row: Any, key: str) -> bool:
    if row is None:
        return False
    return bool(int(row[key] or 0))


def _row_int(row: Any, key: str, default: int) -> int:
    if row is None:
        return default
    return int(row[key] or default)


def _row_optional_text(row: Any, key: str) -> str | None:
    if row is None or row[key] is None:
        return None
    return str(row[key])


def _row_optional_int(row: Any, key: str) -> int | None:
    if row is None or row[key] is None:
        return None
    return int(row[key])


def _normalize_delivery_attempt_no(value: object) -> int:
    if isinstance(value, bool):
        raise ValueError("Delivery attempt number must be a non-negative integer")
    try:
        normalized = int(value)
    except (TypeError, ValueError) as exc:
        raise ValueError("Delivery attempt number must be a non-negative integer") from exc
    if normalized < 0:
        raise ValueError("Delivery attempt number must be a non-negative integer")
    return normalized


def _normalize_command_id(value: object) -> int:
    if isinstance(value, bool):
        raise ValueError("Runtime command ID must be a positive integer")
    try:
        normalized = int(value)
    except (TypeError, ValueError) as exc:
        raise ValueError("Runtime command ID must be a positive integer") from exc
    if normalized <= 0:
        raise ValueError("Runtime command ID must be a positive integer")
    return normalized


def _row_to_user_turn_delivery_record(row: Any) -> ChatUserTurnDeliveryRecord:
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


def _normalize_runtime_envelope(value: object) -> dict[str, Any]:
    if value is None:
        return {}
    if not isinstance(value, dict):
        raise TypeError("Runtime delivery envelope must be an object")
    serialized = _serialize_runtime_envelope(value)
    normalized = json.loads(serialized)
    if not isinstance(normalized, dict):
        raise TypeError("Runtime delivery envelope must be an object")
    return normalized


def _runtime_workspace_path(runtime_envelope: dict[str, Any]) -> str | None:
    """Read the accepted workspace path from a normalized delivery envelope."""
    raw_path = runtime_envelope.get("workspace_path")
    if not isinstance(raw_path, str):
        return None
    return raw_path.strip() or None


def _serialize_runtime_envelope(value: object) -> str:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )


def _deserialize_runtime_envelope(value: object) -> dict[str, Any]:
    try:
        parsed = json.loads(str(value or "{}"))
    except (TypeError, ValueError, json.JSONDecodeError):
        return {}
    if not isinstance(parsed, dict):
        return {}
    return parsed
