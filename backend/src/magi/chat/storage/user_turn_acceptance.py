"""Atomic acceptance of user chat turns and their first delivery record."""

from __future__ import annotations

import asyncio

import aiosqlite

from ...core.sqlite import sqlite_connection_async
from magi.core.chat_assets.mutations import chat_asset_mutation_guarded_if
from ..asset_validation import has_managed_asset_payloads
from ..contracts import (
    CHAT_DELIVERY_STATE_READY,
    ChatMessageRecord,
    ChatSessionRecord,
    CreateUserTurnResult,
)
from ..user_turn_delivery.envelope import (
    normalize_runtime_envelope,
    runtime_workspace_path,
    serialize_runtime_envelope,
)
from ..workspace_identity import claim_workspace_identity
from .user_turn_acceptance_rows import (
    build_user_turn_message,
    build_user_turn_session_record,
    existing_session_workspace_path,
    fetch_existing_user_turn_message,
    insert_user_message_row,
    insert_user_turn_row,
    validate_user_turn_retry,
    validate_user_turn_session,
)
from .user_turn_delivery_errors import ChatTurnConflictError
from .user_turn_delivery_rows import fetch_user_turn_delivery_state


class ChatUserTurnAcceptancePersistenceMixin:
    """Persist one accepted user turn as a single chat transaction."""

    db_path: str

    async def initialize(self) -> None:
        raise NotImplementedError

    async def _fetch_session_row(
        self,
        db: aiosqlite.Connection,
        *,
        session_id: str,
    ) -> aiosqlite.Row | None:
        raise NotImplementedError

    async def _upsert_session_with_connection(
        self,
        db: aiosqlite.Connection,
        record: ChatSessionRecord,
    ) -> None:
        raise NotImplementedError

    async def _replace_message_attachments(
        self,
        db: aiosqlite.Connection,
        *,
        message: ChatMessageRecord,
        attachment_payloads: list[dict[str, object]] | None,
    ) -> None:
        raise NotImplementedError

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
        message = build_user_turn_message(
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
        normalized_runtime_envelope = normalize_runtime_envelope(runtime_envelope)
        runtime_envelope_json = serialize_runtime_envelope(normalized_runtime_envelope)
        normalized_request_fingerprint = str(request_fingerprint or "").strip()
        committed_workspace_path: str | None = None
        async with sqlite_connection_async(self.db_path, profile="mixed") as db:
            await db.execute("BEGIN IMMEDIATE")
            try:
                existing_message = await fetch_existing_user_turn_message(
                    db,
                    turn_id=turn_id,
                )
                if existing_message is not None:
                    validate_user_turn_retry(
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
                    ) = await fetch_user_turn_delivery_state(
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

                existing_session = await self._fetch_session_row(
                    db,
                    session_id=session_id,
                )
                validate_user_turn_session(
                    existing_session,
                    session_id=session_id,
                    user_id=user_id,
                )
                committed_workspace_path = runtime_workspace_path(
                    normalized_runtime_envelope
                ) or existing_session_workspace_path(existing_session)
                await self._upsert_session_with_connection(
                    db,
                    build_user_turn_session_record(
                        existing_session=existing_session,
                        session_id=session_id,
                        user_id=user_id,
                        session_preview=session_preview,
                        created_at_ms=created_at_ms,
                        workspace_path=committed_workspace_path,
                    ),
                )
                await insert_user_turn_row(
                    db,
                    session_id=session_id,
                    user_id=user_id,
                    turn_id=turn_id,
                    created_at_ms=created_at_ms,
                    run_id=run_id,
                    run_revision=run_revision,
                    run_disposition=run_disposition,
                )
                await insert_user_message_row(db, message)
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

    async def load_user_turn_once(
        self,
        *,
        turn_id: str,
        request_fingerprint: str,
    ) -> CreateUserTurnResult | None:
        """Load a committed user turn before repeating preparation side effects."""

        await self.initialize()
        async with sqlite_connection_async(self.db_path, profile="mixed") as db:
            existing_message = await fetch_existing_user_turn_message(
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
            ) = await fetch_user_turn_delivery_state(db, turn_id=turn_id)
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


__all__ = ["ChatUserTurnAcceptancePersistenceMixin"]
