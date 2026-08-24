"""Atomic persistence for accepted chat outcomes and cancellation."""

from __future__ import annotations

import json
from dataclasses import replace
from typing import Any, Protocol, cast

import aiosqlite

from ...core.sqlite import sqlite_connection_async
from magi.core.chat_assets.mutations import chat_asset_mutation_guarded_if
from ..asset_validation import has_explicit_asset_payload_map
from ..contracts import (
    CHAT_DELIVERY_STATE_ADMITTED,
    CHAT_DELIVERY_STATE_QUEUED,
    CHAT_DELIVERY_STATE_READY,
    CHAT_DELIVERY_STATE_TERMINAL,
    ChatAssistantMemoryProjection,
    ChatMessageRecord,
)
from .context_usage import (
    insert_context_usage_snapshot,
    normalize_context_usage_snapshot,
)


_ACTIVE_TURN_STATUSES = ("queued", "running")
_NONTERMINAL_DELIVERY_STATES = (
    CHAT_DELIVERY_STATE_READY,
    CHAT_DELIVERY_STATE_QUEUED,
    CHAT_DELIVERY_STATE_ADMITTED,
)


class _ChatAssistantOutcomeHost(Protocol):
    db_path: str

    async def initialize(self) -> None: ...

    async def _replace_message_attachments(
        self,
        db: aiosqlite.Connection,
        *,
        message: ChatMessageRecord,
        attachment_payloads: list[dict[str, object]] | None,
    ) -> None: ...

    async def _insert_assistant_memory_projection(
        self,
        db: aiosqlite.Connection,
        projection: ChatAssistantMemoryProjection,
        *,
        updated_at_ms: int,
    ) -> None: ...

    def _notify_assistant_memory_outbox(self) -> None: ...


class ChatDeliveryOutcomePersistenceMixin:
    """Linearize assistant completion and cancellation in ``chat.db``."""

    @chat_asset_mutation_guarded_if(
        "attachment_payloads_by_message_id",
        has_explicit_asset_payload_map,
    )
    async def commit_user_turn_assistant_outcome(
        self,
        *,
        turn_id: str,
        delivery_attempt_no: int,
        command_id: int,
        messages: list[ChatMessageRecord],
        attachment_payloads_by_message_id: dict[
            str,
            list[dict[str, object]] | None,
        ],
        trace_id: str | None,
        execution_mode: str | None,
        ux_plan: dict[str, Any] | None,
        response_mode: str,
        started_at_ms: int,
        completed_at_ms: int,
        context_usage: dict[str, Any] | None = None,
        run_id: str | None = None,
        run_revision: int = 0,
        run_disposition: str | None = None,
    ) -> list[ChatMessageRecord] | None:
        """Commit visible output, turn completion, and exact delivery terminality.

        ``None`` means another terminal outcome won before this transaction.
        An empty list is a successfully committed no-message outcome.
        """

        return await self._commit_assistant_outcome(
            turn_id=turn_id,
            messages=messages,
            attachment_payloads_by_message_id=attachment_payloads_by_message_id,
            trace_id=trace_id,
            execution_mode=execution_mode,
            ux_plan=ux_plan,
            response_mode=response_mode,
            started_at_ms=started_at_ms,
            completed_at_ms=completed_at_ms,
            context_usage=context_usage,
            run_id=run_id,
            run_revision=run_revision,
            run_disposition=run_disposition,
            delivery_attempt_no=int(delivery_attempt_no),
            command_id=int(command_id),
        )

    @chat_asset_mutation_guarded_if(
        "attachment_payloads_by_message_id",
        has_explicit_asset_payload_map,
    )
    async def commit_unmanaged_assistant_outcome(
        self,
        *,
        turn_id: str,
        messages: list[ChatMessageRecord],
        attachment_payloads_by_message_id: dict[
            str,
            list[dict[str, object]] | None,
        ],
        trace_id: str | None,
        execution_mode: str | None,
        ux_plan: dict[str, Any] | None,
        response_mode: str,
        started_at_ms: int,
        completed_at_ms: int,
        context_usage: dict[str, Any] | None = None,
        run_id: str | None = None,
        run_revision: int = 0,
        run_disposition: str | None = None,
    ) -> list[ChatMessageRecord] | None:
        """Atomically commit an assistant outcome without a delivery ledger."""

        return await self._commit_assistant_outcome(
            turn_id=turn_id,
            messages=messages,
            attachment_payloads_by_message_id=attachment_payloads_by_message_id,
            trace_id=trace_id,
            execution_mode=execution_mode,
            ux_plan=ux_plan,
            response_mode=response_mode,
            started_at_ms=started_at_ms,
            completed_at_ms=completed_at_ms,
            context_usage=context_usage,
            run_id=run_id,
            run_revision=run_revision,
            run_disposition=run_disposition,
            delivery_attempt_no=None,
            command_id=None,
        )

    async def _commit_assistant_outcome(
        self,
        *,
        turn_id: str,
        messages: list[ChatMessageRecord],
        attachment_payloads_by_message_id: dict[
            str,
            list[dict[str, object]] | None,
        ],
        trace_id: str | None,
        execution_mode: str | None,
        ux_plan: dict[str, Any] | None,
        response_mode: str,
        started_at_ms: int,
        completed_at_ms: int,
        context_usage: dict[str, Any] | None,
        run_id: str | None,
        run_revision: int,
        run_disposition: str | None,
        delivery_attempt_no: int | None,
        command_id: int | None,
    ) -> list[ChatMessageRecord] | None:
        host = cast(_ChatAssistantOutcomeHost, self)
        normalized_turn_id = str(turn_id or "").strip()
        if not normalized_turn_id:
            raise ValueError("Turn ID is required")
        if delivery_attempt_no is not None and delivery_attempt_no < 0:
            raise ValueError("Delivery attempt number must be non-negative")
        if command_id is not None and command_id <= 0:
            raise ValueError("Runtime command ID must be positive")
        if (delivery_attempt_no is None) != (command_id is None):
            raise ValueError("Delivery attempt and command identity must be paired")
        if any(
            message.turn_id != normalized_turn_id
            or message.role != "assistant"
            or message.message_kind
            not in {"assistant_final", "assistant_rhythm_segment"}
            or not message.is_final
            or not message.is_visible
            for message in messages
        ):
            raise ValueError(
                "Assistant outcome messages must be visible final rows for their turn"
            )

        await host.initialize()
        should_notify_projection = False
        committed_messages: list[ChatMessageRecord] = []
        async with sqlite_connection_async(host.db_path, profile="mixed") as db:
            db.row_factory = aiosqlite.Row
            await db.execute("BEGIN IMMEDIATE")
            try:
                owner = (
                    await self._fetch_outcome_owner(db, turn_id=normalized_turn_id)
                    if delivery_attempt_no is not None
                    else await self._fetch_unmanaged_outcome_owner(
                        db,
                        turn_id=normalized_turn_id,
                    )
                )
                if delivery_attempt_no is not None:
                    owner_matches = self._outcome_owner_matches(
                        owner,
                        delivery_attempt_no=delivery_attempt_no,
                        command_id=int(command_id or 0),
                        run_id=run_id,
                        run_revision=run_revision,
                    )
                else:
                    owner_matches = self._unmanaged_outcome_owner_matches(
                        owner,
                        run_id=run_id,
                        run_revision=run_revision,
                    )
                if owner is None or not owner_matches:
                    await db.rollback()
                    return None

                session_id = str(owner["session_id"])
                user_id = str(owner["user_id"])
                if any(
                    message.session_id != session_id or message.user_id != user_id
                    for message in messages
                ):
                    raise ValueError(
                        "Assistant outcome messages do not match their session owner"
                    )
                if await self._has_visible_final(db, turn_id=normalized_turn_id):
                    await db.rollback()
                    return None

                transcript_changed = False
                if messages and all(
                    message.message_kind == "assistant_rhythm_segment"
                    for message in messages
                ):
                    hidden = await db.execute(
                        """
                        UPDATE chat_messages
                        SET is_visible = 0
                        WHERE turn_id = ?
                          AND role = 'assistant'
                          AND message_kind = 'assistant_rhythm_segment'
                          AND is_visible = 1
                        """,
                        (normalized_turn_id,),
                    )
                    transcript_changed = int(hidden.rowcount or 0) > 0

                committed_messages = await self._insert_outcome_messages(
                    host,
                    db,
                    session_id=session_id,
                    messages=messages,
                    attachment_payloads_by_message_id=(
                        attachment_payloads_by_message_id
                    ),
                )
                transcript_changed = transcript_changed or bool(committed_messages)
                usage_snapshot = (
                    normalize_context_usage_snapshot(
                        turn_id=normalized_turn_id,
                        session_id=session_id,
                        user_id=user_id,
                        context_usage=context_usage,
                        updated_at_ms=completed_at_ms,
                    )
                    if committed_messages
                    else None
                )
                if usage_snapshot is not None:
                    await insert_context_usage_snapshot(db, usage_snapshot)
                assistant_memory_projection = self._derive_assistant_memory_projection(
                    committed_messages
                )
                if assistant_memory_projection is not None:
                    await host._insert_assistant_memory_projection(
                        db,
                        assistant_memory_projection,
                        updated_at_ms=int(completed_at_ms),
                    )
                    should_notify_projection = True

                normalized_ux_plan = ux_plan if isinstance(ux_plan, dict) else {}
                completed_turn = await db.execute(
                    """
                    UPDATE chat_turns
                    SET trace_id = COALESCE(trace_id, ?),
                        status = 'completed',
                        response_mode = ?,
                        execution_mode = COALESCE(?, execution_mode),
                        ux_plan_json = CASE
                            WHEN ? != '{}' THEN ?
                            ELSE ux_plan_json
                        END,
                        created_at_ms = CASE
                            WHEN created_at_ms > 0 THEN created_at_ms
                            ELSE ?
                        END,
                        updated_at_ms = ?,
                        completed_at_ms = ?,
                        run_id = COALESCE(?, run_id),
                        run_revision = CASE
                            WHEN ? IS NOT NULL THEN ?
                            ELSE run_revision
                        END,
                        run_disposition = COALESCE(?, run_disposition)
                    WHERE turn_id = ?
                      AND status IN ('queued', 'running')
                    """,
                    (
                        trace_id,
                        str(response_mode or "final_only"),
                        execution_mode,
                        json.dumps(normalized_ux_plan, ensure_ascii=False),
                        json.dumps(normalized_ux_plan, ensure_ascii=False),
                        int(started_at_ms),
                        int(completed_at_ms),
                        int(completed_at_ms),
                        run_id,
                        run_id,
                        int(run_revision),
                        run_disposition,
                        normalized_turn_id,
                    ),
                )
                if int(completed_turn.rowcount or 0) != 1:
                    await db.rollback()
                    return None
                if delivery_attempt_no is not None:
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
                            int(completed_at_ms),
                            normalized_turn_id,
                            delivery_attempt_no,
                            CHAT_DELIVERY_STATE_ADMITTED,
                            int(command_id or 0),
                        ),
                    )
                    if int(terminal.rowcount or 0) != 1:
                        await db.rollback()
                        return None
                if transcript_changed:
                    await db.execute(
                        """
                        UPDATE chat_sessions
                        SET history_version = history_version + 1
                        WHERE session_id = ?
                        """,
                        (session_id,),
                    )
                await db.commit()
            except BaseException:
                await db.rollback()
                raise
        if should_notify_projection:
            host._notify_assistant_memory_outbox()
        return committed_messages

    async def cancel_user_turn_delivery_if_active(
        self,
        *,
        turn_id: str,
        expected_session_id: str | None = None,
        expected_user_id: str | None = None,
        run_id: str | None,
        run_revision: int,
        reason: str,
        updated_at_ms: int,
    ) -> bool:
        """Atomically persist cancellation only while completion is still open.

        Optional owner constraints are checked inside the same write
        transaction as the state transition.  This lets an API request safely
        cancel work that has not created an in-memory run yet without trusting
        a caller-supplied turn ID on its own.
        """

        host = cast(_ChatAssistantOutcomeHost, self)
        normalized_turn_id = str(turn_id or "").strip()
        normalized_session_id = str(expected_session_id or "").strip()
        normalized_user_id = str(expected_user_id or "").strip()
        if not normalized_turn_id:
            return False
        await host.initialize()
        async with sqlite_connection_async(host.db_path, profile="mixed") as db:
            db.row_factory = aiosqlite.Row
            await db.execute("BEGIN IMMEDIATE")
            try:
                owner = await self._fetch_outcome_owner(
                    db,
                    turn_id=normalized_turn_id,
                )
                if owner is None or str(owner["status"]) not in _ACTIVE_TURN_STATUSES:
                    await db.rollback()
                    return False
                if (
                    normalized_session_id
                    and str(owner["session_id"]) != normalized_session_id
                ):
                    await db.rollback()
                    return False
                if normalized_user_id and str(owner["user_id"]) != normalized_user_id:
                    await db.rollback()
                    return False
                if str(owner["delivery_state"]) not in _NONTERMINAL_DELIVERY_STATES:
                    await db.rollback()
                    return False
                if not self._run_identity_matches(
                    owner,
                    run_id=run_id,
                    run_revision=run_revision,
                ):
                    await db.rollback()
                    return False

                cancelled = await db.execute(
                    """
                    UPDATE chat_turns
                    SET status = 'cancelled',
                        updated_at_ms = ?,
                        completed_at_ms = ?,
                        error_text = COALESCE(error_text, ?)
                    WHERE turn_id = ?
                      AND status IN ('queued', 'running')
                    """,
                    (
                        int(updated_at_ms),
                        int(updated_at_ms),
                        str(reason or "user_cancel"),
                        normalized_turn_id,
                    ),
                )
                terminal = await db.execute(
                    """
                    UPDATE chat_user_turn_delivery
                    SET delivery_state = ?,
                        updated_at_ms = ?
                    WHERE turn_id = ?
                      AND delivery_state IN (?, ?, ?)
                    """,
                    (
                        CHAT_DELIVERY_STATE_TERMINAL,
                        int(updated_at_ms),
                        normalized_turn_id,
                        CHAT_DELIVERY_STATE_READY,
                        CHAT_DELIVERY_STATE_QUEUED,
                        CHAT_DELIVERY_STATE_ADMITTED,
                    ),
                )
                if (
                    int(cancelled.rowcount or 0) != 1
                    or int(terminal.rowcount or 0) != 1
                ):
                    await db.rollback()
                    return False
                await db.commit()
                return True
            except BaseException:
                await db.rollback()
                raise

    @staticmethod
    async def _fetch_outcome_owner(
        db: aiosqlite.Connection,
        *,
        turn_id: str,
    ) -> aiosqlite.Row | None:
        cursor = await db.execute(
            """
            SELECT turns.session_id,
                   turns.user_id,
                   turns.status,
                   turns.run_id,
                   turns.run_revision,
                   delivery.delivery_attempt_no,
                   delivery.delivery_state,
                   delivery.current_command_id
            FROM chat_turns AS turns
            JOIN chat_user_turn_delivery AS delivery
              ON delivery.turn_id = turns.turn_id
            WHERE turns.turn_id = ?
            """,
            (turn_id,),
        )
        return await cursor.fetchone()

    @staticmethod
    async def _fetch_unmanaged_outcome_owner(
        db: aiosqlite.Connection,
        *,
        turn_id: str,
    ) -> aiosqlite.Row | None:
        cursor = await db.execute(
            """
            SELECT session_id, user_id, status, run_id, run_revision
            FROM chat_turns
            WHERE turn_id = ?
            """,
            (turn_id,),
        )
        return await cursor.fetchone()

    @classmethod
    def _outcome_owner_matches(
        cls,
        owner: aiosqlite.Row | None,
        *,
        delivery_attempt_no: int,
        command_id: int,
        run_id: str | None,
        run_revision: int,
    ) -> bool:
        if owner is None:
            return False
        return (
            str(owner["status"]) in _ACTIVE_TURN_STATUSES
            and str(owner["delivery_state"]) == CHAT_DELIVERY_STATE_ADMITTED
            and int(owner["delivery_attempt_no"] or 0) == delivery_attempt_no
            and (
                int(owner["current_command_id"])
                if owner["current_command_id"] is not None
                else None
            )
            == command_id
            and cls._run_identity_matches(
                owner,
                run_id=run_id,
                run_revision=run_revision,
            )
        )

    @classmethod
    def _unmanaged_outcome_owner_matches(
        cls,
        owner: aiosqlite.Row | None,
        *,
        run_id: str | None,
        run_revision: int,
    ) -> bool:
        return bool(
            owner is not None
            and str(owner["status"]) in _ACTIVE_TURN_STATUSES
            and cls._run_identity_matches(
                owner,
                run_id=run_id,
                run_revision=run_revision,
            )
        )

    @staticmethod
    def _derive_assistant_memory_projection(
        messages: list[ChatMessageRecord],
    ) -> ChatAssistantMemoryProjection | None:
        content = "\n".join(
            str(message.content_text or "").strip()
            for message in messages
            if str(message.content_text or "").strip()
        )
        if not messages or not content:
            return None
        canonical = messages[0]
        return ChatAssistantMemoryProjection(
            canonical_message_id=canonical.message_id,
            user_id=canonical.user_id,
            session_id=canonical.session_id,
            turn_id=str(canonical.turn_id or ""),
            content=content,
            created_at_ms=canonical.created_at_ms,
        )

    @staticmethod
    def _run_identity_matches(
        owner: aiosqlite.Row,
        *,
        run_id: str | None,
        run_revision: int,
    ) -> bool:
        persisted_run_id = str(owner["run_id"] or "").strip()
        normalized_run_id = str(run_id or "").strip()
        if persisted_run_id and normalized_run_id and persisted_run_id != normalized_run_id:
            return False
        return not (
            persisted_run_id
            and normalized_run_id
            and int(owner["run_revision"] or 0) != int(run_revision)
        )

    @staticmethod
    async def _has_visible_final(
        db: aiosqlite.Connection,
        *,
        turn_id: str,
    ) -> bool:
        cursor = await db.execute(
            """
            SELECT 1
            FROM chat_messages
            WHERE turn_id = ?
              AND role = 'assistant'
              AND message_kind = 'assistant_final'
              AND is_visible = 1
              AND is_final = 1
            LIMIT 1
            """,
            (turn_id,),
        )
        return await cursor.fetchone() is not None

    @staticmethod
    async def _insert_outcome_messages(
        host: _ChatAssistantOutcomeHost,
        db: aiosqlite.Connection,
        *,
        session_id: str,
        messages: list[ChatMessageRecord],
        attachment_payloads_by_message_id: dict[
            str,
            list[dict[str, object]] | None,
        ],
    ) -> list[ChatMessageRecord]:
        if not messages:
            return []
        sequence_cursor = await db.execute(
            """
            SELECT COALESCE(MAX(sequence_no), 0) + 1 AS next_sequence
            FROM chat_messages
            WHERE session_id = ?
            """,
            (session_id,),
        )
        sequence_row = await sequence_cursor.fetchone()
        next_sequence = int(sequence_row["next_sequence"] or 1)
        committed: list[ChatMessageRecord] = []
        for offset, source in enumerate(messages):
            message = replace(source, sequence_no=next_sequence + offset)
            await db.execute(
                """
                INSERT INTO chat_messages (
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
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, NULL)
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
                    1 if message.is_final else 0,
                    1 if message.is_visible else 0,
                    message.created_at_ms,
                    message.sequence_no,
                    message.replaces_message_id,
                    message.replaced_by_message_id,
                    message.persona_id,
                    message.reply_to_message_id,
                ),
            )
            await host._replace_message_attachments(
                db,
                message=message,
                attachment_payloads=attachment_payloads_by_message_id.get(
                    message.message_id
                ),
            )
            if message.replaces_message_id:
                await db.execute(
                    """
                    UPDATE chat_messages
                    SET replaced_by_message_id = ?
                    WHERE message_id = ?
                    """,
                    (message.message_id, message.replaces_message_id),
                )
            committed.append(message)
        return committed


__all__ = ["ChatDeliveryOutcomePersistenceMixin"]
