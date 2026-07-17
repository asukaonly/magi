"""Chat-owned user-message ingress service."""

from __future__ import annotations

import asyncio
import hashlib
import json
import time
import uuid
from contextlib import asynccontextmanager
from dataclasses import dataclass
from typing import Any, AsyncIterator

from ..core.logger import get_logger
from ..core.runtime_bindings import get_chat_message_notifier, require_runtime_command_queue
from ..events.contracts import UserMessageCommand
from ..events.events import EventTypes
from ..events.first_context import (
    FIRST_CONTEXT_METADATA_KEY,
    FIRST_CONTEXT_STORY_INTERACTION_KIND,
    controlled_first_context_metadata,
)
from ..events.recall_feedback import (
    RECALL_FEEDBACK_INTERACTION_KIND,
    RecallFeedbackRequest,
)
from ..events.user_message_dispatch import (
    ASK_RESPONSE_ATTACHMENTS_UNSUPPORTED,
    ASK_RESPONSE_RESOLVE_FAILED,
    BOOTSTRAP_STATE_UPDATE_FAILED,
    CHAT_STORE_NOT_INITIALIZED,
    CHAT_STORE_PERSIST_FAILED,
    CHAT_TURN_CONFLICT,
    CHAT_PROJECTION_FAILED,
    CHAT_SCOPE_DELETED,
    EMPTY_TURN,
    MALFORMED_ATTACHMENTS,
    RECALL_FEEDBACK_PENDING_ASK,
    MessageDispatchOutcome,
    RUNTIME_COMMAND_QUEUE_ENQUEUE_FAILED,
    RUNTIME_COMMAND_QUEUE_NOT_INITIALIZED,
    SESSION_ID_REQUIRED,
)
from ..i18n import t
from ..core.runtime_namespace import DEFAULT_RUNTIME_NAMESPACE
from .attachment_ingestion import LocalChatAttachmentIngestionService
from .provider import get_chat_projector, get_chat_store
from .store import ChatTurnConflictError
from .session_mutations import chat_session_mutation

logger = get_logger(__name__)

_FIRST_CONTEXT_PROJECTION_CONFIRM_TIMEOUT_SECONDS = 1.0
_FIRST_CONTEXT_PROJECTION_CONFIRM_INTERVAL_SECONDS = 0.02

_CHAT_PROJECTION_METADATA_KEYS = {
    FIRST_CONTEXT_METADATA_KEY,
    "l2_batch_owner",
    "l2_batch_catch_up_owner",
    "l2_batch_max_events",
    "l2_batch_max_estimated_tokens",
    "l2_batch_min_ready_events",
    "l2_batch_max_wait_seconds",
}
_RECOMPUTED_DELIVERY_METADATA_KEYS = frozenset(
    key for key in _CHAT_PROJECTION_METADATA_KEYS if key != FIRST_CONTEXT_METADATA_KEY
)


@dataclass(slots=True)
class _IngressDependencies:
    runtime_command_queue: Any
    chat_store: Any


@dataclass(slots=True)
class _ValidatedUserMessage:
    session_id: str
    message: str
    attachments: list[dict[str, Any]]


@dataclass(slots=True)
class _UserMessageSubmission:
    source: str
    user_id: str
    session_id: str
    turn_id: str
    message: str
    attachments: list[dict[str, Any]]
    reply_to_message_id: str | None
    workspace_path: str | None
    interaction_kind: str | None
    metadata: dict[str, Any]
    runtime_namespace: str
    request_fingerprint: str


@dataclass(slots=True)
class _PersistedUserTurn:
    created_turn: Any
    created_at: float
    created_at_ms: int
    created: bool
    projection_completed: bool
    runtime_enqueued: bool


@dataclass(slots=True)
class _TurnIngressLockState:
    lock: asyncio.Lock
    users: int = 0


_TURN_INGRESS_LOCKS: dict[str, _TurnIngressLockState] = {}


def get_chat_read_service():
    """Resolve the chat read service lazily to avoid startup cycles."""

    from .read_service import get_chat_read_service as _get_chat_read_service

    return _get_chat_read_service()


def resolve_control_session_store():
    """Resolve the control session store lazily to avoid startup cycles."""

    from ..control.provider import resolve_control_session_store as _resolve_control_session_store

    return _resolve_control_session_store()


def resolve_control_interaction_broker():
    """Resolve the control interaction broker lazily to avoid startup cycles."""

    from ..control.provider import (
        resolve_control_interaction_broker as _resolve_control_interaction_broker,
    )

    return _resolve_control_interaction_broker()


def _extract_chat_projection_metadata(metadata: dict[str, Any]) -> dict[str, Any]:
    return {
        key: value
        for key, value in metadata.items()
        if key in _CHAT_PROJECTION_METADATA_KEYS and value is not None
    }


@asynccontextmanager
async def _user_turn_ingress_lock(turn_id: str) -> AsyncIterator[None]:
    """Serialize first persistence for one client turn within the desktop runtime."""
    state = _TURN_INGRESS_LOCKS.get(turn_id)
    if state is None:
        state = _TurnIngressLockState(lock=asyncio.Lock())
        _TURN_INGRESS_LOCKS[turn_id] = state
    state.users += 1
    await state.lock.acquire()
    try:
        yield
    finally:
        state.lock.release()
        state.users -= 1
        if state.users == 0 and _TURN_INGRESS_LOCKS.get(turn_id) is state:
            _TURN_INGRESS_LOCKS.pop(turn_id, None)


def _build_incoming_request_fingerprint(
    *,
    source: str,
    user_id: str,
    validated: _ValidatedUserMessage,
    turn_id: str,
    reply_to_message_id: str | None,
    workspace_path: str | None,
    metadata: dict[str, Any] | None,
    runtime_namespace: str | None,
    interaction_kind: str | None,
    first_context: dict[str, Any] | None,
) -> str:
    """Fingerprint caller-owned input before hooks or attachment preparation."""
    controlled_metadata = controlled_first_context_metadata(
        interaction_kind=interaction_kind,
        first_context=first_context,
    )
    normalized_metadata = dict(metadata or {})
    normalized_metadata.pop("interaction_kind", None)
    normalized_metadata.pop(FIRST_CONTEXT_METADATA_KEY, None)
    normalized_context = controlled_metadata.get(FIRST_CONTEXT_METADATA_KEY)
    first_context_identity = None
    if isinstance(normalized_context, dict):
        first_context_identity = {"question_id": str(normalized_context.get("question_id") or "")}
    request_identity = {
        "source": str(source or "").strip() or "api",
        "user_id": user_id,
        "session_id": validated.session_id,
        "turn_id": turn_id,
        "message": validated.message,
        "attachments": [dict(item) for item in validated.attachments],
        "reply_to_message_id": str(reply_to_message_id or "").strip() or None,
        "workspace_path": str(workspace_path or "").strip() or None,
        "interaction_kind": (FIRST_CONTEXT_STORY_INTERACTION_KIND if controlled_metadata else None),
        "first_context": first_context_identity,
        "metadata": normalized_metadata,
        "runtime_namespace": (str(runtime_namespace or "").strip() or DEFAULT_RUNTIME_NAMESPACE),
    }
    return _build_request_fingerprint(request_identity)


async def _load_existing_user_turn(
    chat_store: Any,
    *,
    source: str,
    user_id: str,
    validated: _ValidatedUserMessage,
    turn_id: str,
    reply_to_message_id: str | None,
    workspace_path: str | None,
    metadata: dict[str, Any] | None,
    runtime_namespace: str | None,
    interaction_kind: str | None,
    request_fingerprint: str,
) -> tuple[
    _UserMessageSubmission | None,
    _PersistedUserTurn | None,
    MessageDispatchOutcome | None,
]:
    try:
        result = await chat_store.load_user_turn_once(
            turn_id=turn_id,
            request_fingerprint=request_fingerprint,
        )
    except ChatTurnConflictError:
        return (
            None,
            None,
            _turn_conflict_outcome(
                user_id=user_id,
                session_id=validated.session_id,
                turn_id=turn_id,
            ),
        )
    except Exception:
        return (
            None,
            None,
            MessageDispatchOutcome(
                success=False,
                user_id=user_id,
                session_id=validated.session_id,
                turn_id=turn_id,
                error_code=CHAT_STORE_PERSIST_FAILED,
                error_message=t(
                    "chat.dispatch.errors.persist_failed",
                    fallback="Chat turn persistence failed",
                ),
            ),
        )
    if result is None:
        return None, None, None

    submission = _UserMessageSubmission(
        source=str(source or "").strip() or "api",
        user_id=user_id,
        session_id=validated.session_id,
        turn_id=turn_id,
        message=validated.message,
        attachments=[dict(item) for item in validated.attachments],
        reply_to_message_id=str(reply_to_message_id or "").strip() or None,
        workspace_path=str(workspace_path or "").strip() or None,
        interaction_kind=str(interaction_kind or "").strip() or None,
        metadata=dict(metadata or {}),
        runtime_namespace=(str(runtime_namespace or "").strip() or DEFAULT_RUNTIME_NAMESPACE),
        request_fingerprint=request_fingerprint,
    )
    _restore_submission_from_runtime_envelope(submission, result.runtime_envelope)
    return submission, _persisted_user_turn_from_result(result), None


def _persisted_user_turn_from_result(result: Any) -> _PersistedUserTurn:
    created_turn = result.message
    persisted_at_ms = int(getattr(created_turn, "created_at_ms", 0) or 0)
    return _PersistedUserTurn(
        created_turn=created_turn,
        created_at=float(persisted_at_ms) / 1000.0,
        created_at_ms=persisted_at_ms,
        created=bool(result.created),
        projection_completed=bool(result.projection_completed),
        runtime_enqueued=bool(result.runtime_enqueued),
    )


async def _resolve_new_turn_pending_interaction(
    *,
    user_id: str,
    validated: _ValidatedUserMessage,
    metadata: dict[str, Any] | None,
) -> MessageDispatchOutcome | None:
    recall_feedback = RecallFeedbackRequest.from_value((metadata or {}).get("recall_feedback"))
    if recall_feedback is not None:
        ask_state = _active_pending_ask_state(validated.session_id)
        if ask_state is not None:
            return MessageDispatchOutcome(
                success=False,
                user_id=user_id,
                session_id=validated.session_id,
                handled_as="recall_feedback",
                ask_request_id=ask_state.request_id,
                error_code=RECALL_FEEDBACK_PENDING_ASK,
                error_message=t(
                    "chat.dispatch.errors.recall_feedback_pending_ask",
                    fallback="Answer the current question before rechecking an earlier reply.",
                ),
            )
    return await _resolve_pending_ask_response(
        user_id=user_id,
        session_id=validated.session_id,
        answer=validated.message.strip(),
        has_attachments=bool(validated.attachments),
    )


async def dispatch_user_message(
    *,
    source: str,
    user_id: str,
    message: str,
    session_id: str | None = None,
    attachments: list[dict[str, Any]] | None = None,
    reply_to_message_id: str | None = None,
    workspace_path: str | None = None,
    client_turn_id: str | None = None,
    metadata: dict[str, Any] | None = None,
    runtime_namespace: str | None = None,
    interaction_kind: str | None = None,
    first_context: dict[str, Any] | None = None,
) -> MessageDispatchOutcome:
    """Resolve chat-owned metadata and enqueue a user-message runtime command."""

    user_id, dependencies, validated, early_outcome = await _prepare_ingress_start(
        user_id=user_id,
        session_id=session_id,
        message=message,
        attachments=attachments,
    )
    if early_outcome is not None:
        return early_outcome
    assert dependencies is not None and validated is not None
    turn_id = str(client_turn_id or "").strip() or f"turn_{uuid.uuid4().hex[:12]}"
    request_fingerprint = _build_incoming_request_fingerprint(
        source=source,
        user_id=user_id,
        validated=validated,
        turn_id=turn_id,
        reply_to_message_id=reply_to_message_id,
        workspace_path=workspace_path,
        metadata=metadata,
        runtime_namespace=runtime_namespace,
        interaction_kind=interaction_kind,
        first_context=first_context,
    )

    # This shared boundary makes attachment preparation, chat persistence, L1
    # projection, and runtime enqueue one indivisible operation relative to a
    # destructive memory clear. The clear path acquires the matching exclusive
    # boundary before it enters the memory barrier, preserving lock order.
    async with chat_session_mutation(validated.session_id), dependencies.runtime_command_queue.user_message_operation():
        if await dependencies.runtime_command_queue.is_user_message_scope_blocked(
            user_id=user_id,
            session_id=validated.session_id,
            turn_id=turn_id,
        ):
            return MessageDispatchOutcome(
                success=False,
                user_id=user_id,
                session_id=validated.session_id,
                turn_id=turn_id,
                error_code=CHAT_SCOPE_DELETED,
                error_message=t(
                    "chat.dispatch.errors.scope_deleted",
                    fallback="This conversation or message was deleted. Start a new conversation.",
                ),
            )
        async with _user_turn_ingress_lock(turn_id):
            submission, persisted, retry_error = await _load_existing_user_turn(
                dependencies.chat_store,
                source=source,
                user_id=user_id,
                validated=validated,
                turn_id=turn_id,
                reply_to_message_id=reply_to_message_id,
                workspace_path=workspace_path,
                metadata=metadata,
                runtime_namespace=runtime_namespace,
                interaction_kind=interaction_kind,
                request_fingerprint=request_fingerprint,
            )
            if retry_error is not None:
                return retry_error

            if persisted is None:
                pending_outcome = await _resolve_new_turn_pending_interaction(
                    user_id=user_id,
                    validated=validated,
                    metadata=metadata,
                )
                if pending_outcome is not None:
                    return pending_outcome
                submission = await _prepare_user_message_submission(
                    source=source,
                    user_id=user_id,
                    validated=validated,
                    reply_to_message_id=reply_to_message_id,
                    workspace_path=workspace_path,
                    turn_id=turn_id,
                    metadata=metadata,
                    runtime_namespace=runtime_namespace,
                    interaction_kind=interaction_kind,
                    first_context=first_context,
                    request_fingerprint=request_fingerprint,
                )
                hook_error = await _apply_user_prompt_submit_hook(submission)
                if hook_error is not None:
                    return hook_error

                persisted, persist_error = await _persist_user_message_turn(
                    dependencies.chat_store,
                    submission,
                )
                if persist_error is not None:
                    return persist_error
            assert submission is not None and persisted is not None

            if not persisted.projection_completed:
                projection_error = await _project_user_message(submission, persisted)
                if projection_error is not None:
                    return projection_error
                stage_error = await _mark_delivery_stage(
                    dependencies.chat_store,
                    submission,
                    persisted,
                    stage="projection",
                )
                if stage_error is not None:
                    return stage_error
                persisted.projection_completed = True

            if not persisted.runtime_enqueued:
                enqueue_error = await _enqueue_runtime_user_message(
                    dependencies.runtime_command_queue,
                    submission,
                    persisted,
                )
                if enqueue_error is not None:
                    return enqueue_error
                stage_error = await _mark_delivery_stage(
                    dependencies.chat_store,
                    submission,
                    persisted,
                    stage="runtime",
                )
                if stage_error is not None:
                    return stage_error
                persisted.runtime_enqueued = True

            bootstrap_error = await _mark_first_context_bootstrap_started(
                submission,
                persisted,
            )
            if bootstrap_error is not None:
                return bootstrap_error

            return await _build_successful_dispatch_outcome(
                dependencies.runtime_command_queue,
                submission,
                persisted,
            )


async def _prepare_ingress_start(
    *,
    user_id: str,
    session_id: str | None,
    message: str,
    attachments: list[dict[str, Any]] | None,
) -> tuple[
    str,
    _IngressDependencies | None,
    _ValidatedUserMessage | None,
    MessageDispatchOutcome | None,
]:
    from ..identity import canonicalize_user_id

    user_id = str(canonicalize_user_id(user_id))
    dependencies, dependency_error = _resolve_ingress_dependencies(user_id)
    if dependency_error is not None:
        return user_id, None, None, dependency_error
    validated, validation_error = _validate_user_message_input(
        user_id=user_id,
        session_id=session_id,
        message=message,
        attachments=attachments,
    )
    if validation_error is not None:
        return user_id, dependencies, None, validation_error
    assert validated is not None
    return user_id, dependencies, validated, None


def _resolve_ingress_dependencies(
    user_id: str,
) -> tuple[_IngressDependencies | None, MessageDispatchOutcome | None]:
    try:
        runtime_command_queue = require_runtime_command_queue()
    except RuntimeError:
        return None, MessageDispatchOutcome(
            success=False,
            user_id=user_id,
            error_code=RUNTIME_COMMAND_QUEUE_NOT_INITIALIZED,
            error_message=t(
                "chat.dispatch.errors.runtime_command_queue_not_initialized",
                fallback="Runtime command queue is not initialized. Please complete onboarding or check the saved configuration.",
            ),
        )
    try:
        chat_store = get_chat_store()
    except RuntimeError:
        return None, MessageDispatchOutcome(
            success=False,
            user_id=user_id,
            error_code=CHAT_STORE_NOT_INITIALIZED,
            error_message=t(
                "chat.dispatch.errors.chat_store_not_initialized",
                fallback="Chat store is not initialized.",
            ),
        )
    return _IngressDependencies(runtime_command_queue, chat_store), None


def _validate_user_message_input(
    *,
    user_id: str,
    session_id: str | None,
    message: str,
    attachments: list[dict[str, Any]] | None,
) -> tuple[_ValidatedUserMessage | None, MessageDispatchOutcome | None]:
    resolved_session_id = str(session_id or "").strip()
    if not resolved_session_id:
        return None, MessageDispatchOutcome(
            success=False,
            user_id=user_id,
            error_code=SESSION_ID_REQUIRED,
            error_message=t(
                "chat.dispatch.errors.session_id_required",
                fallback="Session ID is required.",
            ),
        )
    try:
        normalized_attachments = _normalize_attachments(attachments)
    except ValueError as exc:
        return None, MessageDispatchOutcome(
            success=False,
            user_id=user_id,
            session_id=resolved_session_id,
            error_code=MALFORMED_ATTACHMENTS,
            error_message=str(exc),
        )
    normalized_message = str(message or "")
    if not normalized_message.strip() and not normalized_attachments:
        return None, _empty_turn_outcome(user_id, resolved_session_id)
    return (
        _ValidatedUserMessage(
            session_id=resolved_session_id,
            message=normalized_message,
            attachments=normalized_attachments,
        ),
        None,
    )


async def _prepare_user_message_submission(
    *,
    source: str,
    user_id: str,
    validated: _ValidatedUserMessage,
    reply_to_message_id: str | None,
    workspace_path: str | None,
    turn_id: str,
    metadata: dict[str, Any] | None,
    runtime_namespace: str | None,
    interaction_kind: str | None,
    first_context: dict[str, Any] | None,
    request_fingerprint: str,
) -> _UserMessageSubmission:
    prepared_attachments = await _prepare_runtime_attachments(
        session_id=validated.session_id,
        turn_id=turn_id,
        attachments=validated.attachments,
    )
    normalized_workspace_path = await _resolve_workspace_path(
        user_id=user_id,
        session_id=validated.session_id,
        workspace_path=workspace_path,
    )
    normalized_reply_to_message_id = str(reply_to_message_id or "").strip() or None
    normalized_metadata = dict(metadata or {})
    normalized_metadata.pop("interaction_kind", None)
    normalized_metadata.pop(FIRST_CONTEXT_METADATA_KEY, None)
    controlled_metadata = controlled_first_context_metadata(
        interaction_kind=interaction_kind,
        first_context=first_context,
    )
    normalized_metadata.update(controlled_metadata)
    if normalized_reply_to_message_id is not None:
        normalized_metadata["reply_to_message_id"] = normalized_reply_to_message_id
    return _UserMessageSubmission(
        source=str(source or "").strip() or "api",
        user_id=user_id,
        session_id=validated.session_id,
        turn_id=turn_id,
        message=validated.message,
        attachments=prepared_attachments,
        reply_to_message_id=normalized_reply_to_message_id,
        workspace_path=normalized_workspace_path,
        interaction_kind=(FIRST_CONTEXT_STORY_INTERACTION_KIND if controlled_metadata else None),
        metadata=normalized_metadata,
        runtime_namespace=str(runtime_namespace or "").strip() or DEFAULT_RUNTIME_NAMESPACE,
        request_fingerprint=request_fingerprint,
    )


async def _resolve_workspace_path(
    *,
    user_id: str,
    session_id: str,
    workspace_path: str | None,
) -> str | None:
    normalized_workspace_path = str(workspace_path or "").strip() or None
    if normalized_workspace_path is not None:
        return normalized_workspace_path
    try:
        read_service = get_chat_read_service()
        session_summary = await read_service.aget_session_summary(user_id, session_id)
    except Exception:
        return None
    if session_summary is None:
        return None
    return str(session_summary.workspace_path or "").strip() or None


def _empty_turn_outcome(
    user_id: str, session_id: str, turn_id: str | None = None
) -> MessageDispatchOutcome:
    return MessageDispatchOutcome(
        success=False,
        user_id=user_id,
        session_id=session_id,
        turn_id=turn_id,
        error_code=EMPTY_TURN,
        error_message=t(
            "chat.dispatch.errors.empty_turn",
            fallback="Message text or attachments are required.",
        ),
    )


async def _apply_user_prompt_submit_hook(
    submission: _UserMessageSubmission,
) -> MessageDispatchOutcome | None:
    from ..hooks.contracts import HookEventType, HookOutcome
    from ..hooks.dispatch import dispatch_hook

    submit_decision = await dispatch_hook(
        HookEventType.USER_PROMPT_SUBMIT,
        session_id=submission.session_id,
        turn_id=submission.turn_id,
        user_id=submission.user_id,
        workspace=submission.workspace_path,
        user_message=submission.message,
        extra={
            "source": submission.source,
            "has_attachments": bool(submission.attachments),
            "reply_to_message_id": submission.reply_to_message_id,
        },
    )
    if submit_decision.outcome == HookOutcome.DENY:
        return MessageDispatchOutcome(
            success=False,
            user_id=submission.user_id,
            session_id=submission.session_id,
            turn_id=submission.turn_id,
            error_code="HOOK_DENIED",
            error_message=submit_decision.reason or "User prompt rejected by hook",
        )
    if submit_decision.outcome == HookOutcome.MODIFY:
        return _apply_modified_user_message(submission, submit_decision.modified_user_message)
    if submit_decision.outcome == HookOutcome.INJECT_CONTEXT and submit_decision.additional_context:
        submission.metadata.setdefault("hook_injected_context", submit_decision.additional_context)
    return None


def _apply_modified_user_message(
    submission: _UserMessageSubmission,
    modified_message: str | None,
) -> MessageDispatchOutcome | None:
    if modified_message is None:
        return None
    submission.message = modified_message
    if not submission.message.strip() and not submission.attachments:
        return _empty_turn_outcome(
            submission.user_id,
            submission.session_id,
            submission.turn_id,
        )
    return None


async def _persist_user_message_turn(
    chat_store: Any,
    submission: _UserMessageSubmission,
) -> tuple[_PersistedUserTurn | None, MessageDispatchOutcome | None]:
    created_at = time.time()
    created_at_ms = int(created_at * 1000)
    active_persona_id = await _resolve_active_persona_id()
    recall_feedback = RecallFeedbackRequest.from_value(submission.metadata.get("recall_feedback"))
    try:
        message_payload: dict[str, object] = {}
        if recall_feedback is not None:
            message_payload["recall_feedback"] = recall_feedback.to_dict()
        if submission.interaction_kind is not None:
            message_payload["interaction_kind"] = submission.interaction_kind
            message_payload[FIRST_CONTEXT_METADATA_KEY] = dict(
                submission.metadata[FIRST_CONTEXT_METADATA_KEY]
            )
        runtime_envelope = _build_runtime_envelope(submission)
        result = await chat_store.create_user_turn_once(
            session_id=submission.session_id,
            user_id=submission.user_id,
            turn_id=submission.turn_id,
            message_text=submission.message,
            attachment_payloads=submission.attachments,
            message_payload=message_payload or None,
            created_at_ms=created_at_ms,
            reply_to_message_id=submission.reply_to_message_id,
            persona_id=active_persona_id,
            runtime_envelope=runtime_envelope,
            request_fingerprint=submission.request_fingerprint,
        )
        _restore_submission_from_runtime_envelope(
            submission,
            result.runtime_envelope,
        )
    except ChatTurnConflictError:
        return None, _turn_conflict_outcome(
            user_id=submission.user_id,
            session_id=submission.session_id,
            turn_id=submission.turn_id,
        )
    except Exception:
        return None, MessageDispatchOutcome(
            success=False,
            user_id=submission.user_id,
            session_id=submission.session_id,
            turn_id=submission.turn_id,
            error_code=CHAT_STORE_PERSIST_FAILED,
            error_message=t(
                "chat.dispatch.errors.persist_failed",
                fallback="Chat turn persistence failed",
            ),
        )
    persisted = _persisted_user_turn_from_result(result)
    if persisted.created_at_ms <= 0:
        persisted.created_at_ms = created_at_ms
        persisted.created_at = created_at
    return persisted, None


def _turn_conflict_outcome(
    *,
    user_id: str,
    session_id: str,
    turn_id: str,
) -> MessageDispatchOutcome:
    return MessageDispatchOutcome(
        success=False,
        user_id=user_id,
        session_id=session_id,
        turn_id=turn_id,
        error_code=CHAT_TURN_CONFLICT,
        error_message=t(
            "chat.dispatch.errors.turn_conflict",
            fallback=(
                "This send identifier was already used for different content. "
                "Send it again as a new message."
            ),
        ),
    )


def _build_runtime_envelope(submission: _UserMessageSubmission) -> dict[str, object]:
    return {
        "source": submission.source,
        "user_id": submission.user_id,
        "session_id": submission.session_id,
        "turn_id": submission.turn_id,
        "message": submission.message,
        "attachments": [dict(item) for item in submission.attachments],
        "reply_to_message_id": submission.reply_to_message_id,
        "workspace_path": submission.workspace_path,
        "interaction_kind": submission.interaction_kind,
        "metadata": dict(submission.metadata),
        "runtime_namespace": submission.runtime_namespace,
    }


def _build_request_fingerprint(runtime_envelope: dict[str, object]) -> str:
    request_identity = dict(runtime_envelope)
    raw_metadata = request_identity.get("metadata")
    metadata = dict(raw_metadata) if isinstance(raw_metadata, dict) else {}
    for key in _RECOMPUTED_DELIVERY_METADATA_KEYS:
        metadata.pop(key, None)
    request_identity["metadata"] = metadata
    canonical = json.dumps(
        request_identity,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _restore_submission_from_runtime_envelope(
    submission: _UserMessageSubmission,
    runtime_envelope: object,
) -> None:
    if not isinstance(runtime_envelope, dict):
        raise ValueError("Persisted runtime delivery envelope is invalid")
    raw_attachments = runtime_envelope.get("attachments")
    raw_metadata = runtime_envelope.get("metadata")
    if not isinstance(raw_attachments, list) or not all(
        isinstance(item, dict) for item in raw_attachments
    ):
        raise ValueError("Persisted runtime delivery attachments are invalid")
    if not isinstance(raw_metadata, dict):
        raise ValueError("Persisted runtime delivery metadata is invalid")

    submission.source = str(runtime_envelope.get("source") or "api")
    submission.user_id = str(runtime_envelope.get("user_id") or "")
    submission.session_id = str(runtime_envelope.get("session_id") or "")
    submission.turn_id = str(runtime_envelope.get("turn_id") or "")
    submission.message = str(runtime_envelope.get("message") or "")
    submission.attachments = [dict(item) for item in raw_attachments]
    submission.reply_to_message_id = (
        str(runtime_envelope.get("reply_to_message_id") or "").strip() or None
    )
    submission.workspace_path = str(runtime_envelope.get("workspace_path") or "").strip() or None
    submission.interaction_kind = (
        str(runtime_envelope.get("interaction_kind") or "").strip() or None
    )
    submission.metadata = dict(raw_metadata)
    submission.runtime_namespace = (
        str(runtime_envelope.get("runtime_namespace") or "").strip() or DEFAULT_RUNTIME_NAMESPACE
    )


async def _mark_delivery_stage(
    chat_store: Any,
    submission: _UserMessageSubmission,
    persisted: _PersistedUserTurn,
    *,
    stage: str,
) -> MessageDispatchOutcome | None:
    try:
        if stage == "projection":
            await chat_store.mark_user_turn_projection_completed(
                turn_id=submission.turn_id,
                updated_at_ms=int(time.time() * 1000),
            )
        elif stage == "runtime":
            await chat_store.mark_user_turn_runtime_enqueued(
                turn_id=submission.turn_id,
                updated_at_ms=int(time.time() * 1000),
            )
        else:
            raise ValueError(f"Unsupported delivery stage: {stage}")
    except Exception as exc:
        logger.warning(
            "Failed to persist user-message delivery stage %s for turn %s: %s",
            stage,
            submission.turn_id,
            exc,
        )
        return MessageDispatchOutcome(
            success=False,
            user_id=submission.user_id,
            session_id=submission.session_id,
            turn_id=submission.turn_id,
            message_id=persisted.created_turn.message_id,
            error_code=CHAT_STORE_PERSIST_FAILED,
            error_message=t(
                "chat.dispatch.errors.persist_failed",
                fallback="Chat turn persistence failed",
            ),
        )
    return None


async def _project_user_message(
    submission: _UserMessageSubmission,
    persisted: _PersistedUserTurn,
) -> MessageDispatchOutcome | None:
    recall_feedback = RecallFeedbackRequest.from_value(submission.metadata.get("recall_feedback"))
    try:
        chat_projector = get_chat_projector()
    except RuntimeError as exc:
        logger.warning("Chat projector is unavailable: %s", exc)
        if submission.interaction_kind == FIRST_CONTEXT_STORY_INTERACTION_KIND:
            return _chat_projection_failed_outcome(submission, persisted)
        return None
    try:
        await chat_projector.project_user_message(
            message_id=persisted.created_turn.message_id,
            user_id=submission.user_id,
            session_id=submission.session_id,
            turn_id=submission.turn_id,
            content=submission.message,
            created_at_ms=persisted.created_at_ms,
            interaction_kind=(
                RECALL_FEEDBACK_INTERACTION_KIND
                if recall_feedback is not None
                else submission.interaction_kind
            ),
            metadata=_extract_chat_projection_metadata(submission.metadata),
        )
        if (
            submission.interaction_kind == FIRST_CONTEXT_STORY_INTERACTION_KIND
            and not await _wait_for_first_context_memory_projection(
                message_id=persisted.created_turn.message_id,
            )
        ):
            return _chat_projection_failed_outcome(submission, persisted)
    except Exception as exc:
        logger.warning("Failed to project chat user message into L1: %s", exc)
        if submission.interaction_kind == FIRST_CONTEXT_STORY_INTERACTION_KIND:
            return _chat_projection_failed_outcome(submission, persisted)
    return None


async def _wait_for_first_context_memory_projection(*, message_id: str) -> bool:
    """Confirm the normal memory subscriber reached every required durable stage."""
    try:
        unified_memory = _resolve_projection_memory()
    except RuntimeError as exc:
        if _memory_layer_enabled("l1") is False:
            return True
        logger.warning("First-context memory confirmation is unavailable: %s", exc)
        return False

    l1_store = getattr(unified_memory, "l1", None)
    if l1_store is None:
        return _memory_layer_enabled("l1") is False
    finder = getattr(l1_store, "find_event_id_by_idempotency", None)
    event_reader = getattr(l1_store, "get_memory_event", None)
    if not callable(finder) or not callable(event_reader):
        return False

    l2_store = getattr(unified_memory, "l2", None)
    has_projection_job = getattr(l2_store, "has_projection_job", None)
    deadline = time.monotonic() + _FIRST_CONTEXT_PROJECTION_CONFIRM_TIMEOUT_SECONDS
    while True:
        event_id = await finder(
            source="chat",
            event_type=EventTypes.USER_MESSAGE,
            idempotency_key=message_id,
        )
        if event_id is not None:
            memory_event = await event_reader(event_id)
            if memory_event is not None:
                if not _event_requires_l2_projection(memory_event):
                    return True
                if _memory_layer_enabled("l2") is False:
                    return True
                if l2_store is None or not callable(has_projection_job):
                    return False
                if await has_projection_job(event_id=event_id):
                    return True
        if time.monotonic() >= deadline:
            return False
        await asyncio.sleep(_FIRST_CONTEXT_PROJECTION_CONFIRM_INTERVAL_SECONDS)


def _event_requires_l2_projection(memory_event: object) -> bool:
    from ..memory.evidence import event_allows_l2_projection

    return event_allows_l2_projection(memory_event)


def _resolve_projection_memory():
    from ..memory.provider import get_unified_memory

    return get_unified_memory()


def _memory_layer_enabled(layer_name: str) -> bool | None:
    try:
        from ..config.loader import get_config

        layer = getattr(get_config().agent.memory, layer_name)
        return bool(layer.enabled)
    except Exception:
        return None


def _chat_projection_failed_outcome(
    submission: _UserMessageSubmission,
    persisted: _PersistedUserTurn,
) -> MessageDispatchOutcome:
    return MessageDispatchOutcome(
        success=False,
        user_id=submission.user_id,
        session_id=submission.session_id,
        turn_id=submission.turn_id,
        message_id=persisted.created_turn.message_id,
        error_code=CHAT_PROJECTION_FAILED,
        error_message=t(
            "chat.dispatch.errors.projection_failed",
            fallback="The message was saved, but memory projection failed. Please retry.",
        ),
    )


async def _enqueue_runtime_user_message(
    runtime_command_queue: Any,
    submission: _UserMessageSubmission,
    persisted: _PersistedUserTurn,
) -> MessageDispatchOutcome | None:
    try:
        await runtime_command_queue.enqueue_user_message(
            UserMessageCommand(
                source=submission.source,
                user_id=submission.user_id,
                session_id=submission.session_id,
                turn_id=submission.turn_id,
                message=submission.message,
                attachments=submission.attachments,
                workspace_path=submission.workspace_path,
                runtime_namespace=submission.runtime_namespace,
                metadata=submission.metadata,
                created_at=persisted.created_at,
                correlation_id=f"user_message:{persisted.created_turn.message_id}",
            )
        )
    except Exception:
        return MessageDispatchOutcome(
            success=False,
            user_id=submission.user_id,
            session_id=submission.session_id,
            turn_id=submission.turn_id,
            error_code=RUNTIME_COMMAND_QUEUE_ENQUEUE_FAILED,
            error_message=t(
                "chat.dispatch.errors.enqueue_failed",
                fallback="Runtime command enqueue failed",
            ),
        )
    return None


async def _build_successful_dispatch_outcome(
    runtime_command_queue: Any,
    submission: _UserMessageSubmission,
    persisted: _PersistedUserTurn,
) -> MessageDispatchOutcome:
    stats = await runtime_command_queue.get_stats()
    queue_size = stats.get("pending_count") if isinstance(stats, dict) else None
    # Upserts are intentionally repeated on a successful idempotent retry. A
    # previous attempt may have committed the transcript before projection or
    # runtime enqueue failed, in which case no notification was sent yet.
    await get_chat_message_notifier().broadcast_chat_message_upsert(
        user_id=submission.user_id,
        session_id=submission.session_id,
        message_id=persisted.created_turn.message_id,
    )
    return MessageDispatchOutcome(
        success=True,
        user_id=submission.user_id,
        session_id=submission.session_id,
        turn_id=submission.turn_id,
        message_id=persisted.created_turn.message_id,
        queue_size=int(queue_size) if isinstance(queue_size, int) else None,
    )


async def _mark_first_context_bootstrap_started(
    submission: _UserMessageSubmission,
    persisted: _PersistedUserTurn,
) -> MessageDispatchOutcome | None:
    if submission.interaction_kind != FIRST_CONTEXT_STORY_INTERACTION_KIND:
        return None
    try:
        from ..personality.active_persona import get_current_personality
        from ..personality.bootstrap_service import (
            BootstrapDialogueService,
            get_shared_growth_engine,
        )

        persona_name = str(get_current_personality() or "").strip()
        if not persona_name:
            raise RuntimeError("First-context turn could not resolve the active persona")
        service = BootstrapDialogueService(
            growth_engine=await get_shared_growth_engine(),
        )
        await service.mark_bootstrap_started(
            persona_name=persona_name,
            persona_id=str(getattr(persisted.created_turn, "persona_id", "") or "").strip(),
            user_id=submission.user_id,
            session_id=submission.session_id,
            turn_id=submission.turn_id,
            message_id=persisted.created_turn.message_id,
        )
    except Exception as exc:
        logger.warning("Failed to mark first-context bootstrap as started: %s", exc)
        return MessageDispatchOutcome(
            success=False,
            user_id=submission.user_id,
            session_id=submission.session_id,
            turn_id=submission.turn_id,
            message_id=persisted.created_turn.message_id,
            error_code=BOOTSTRAP_STATE_UPDATE_FAILED,
            error_message=t(
                "chat.dispatch.errors.bootstrap_state_update_failed",
                fallback="The first conversation was saved, but onboarding state could not be updated. Please retry.",
            ),
        )
    return None


async def _resolve_pending_ask_response(
    *,
    user_id: str,
    session_id: str,
    answer: str,
    has_attachments: bool = False,
) -> MessageDispatchOutcome | None:
    if not answer:
        return None
    ask_state = _active_pending_ask_state(session_id)
    if ask_state is None:
        return None

    if has_attachments:
        return _ask_response_attachments_unsupported(user_id, session_id, ask_state.request_id)

    try:
        broker = resolve_control_interaction_broker()
    except RuntimeError:
        return _ask_response_resolve_failed(user_id, session_id, ask_state.request_id)

    resolved = await broker.resolve(
        interaction_id=ask_state.request_id,
        kind="ask",
        response=answer,
    )
    if not resolved:
        return _ask_response_resolve_failed(user_id, session_id, ask_state.request_id)

    return _ask_response_success(user_id, session_id, ask_state.request_id)


def _lookup_pending_ask_state(session_id: str) -> Any | None:
    try:
        store = resolve_control_session_store()
        return store.ask_state(session_id)
    except RuntimeError:
        return None
    except Exception:
        logger.debug(
            "message_dispatch.ask_state_lookup_failed", session_id=session_id, exc_info=True
        )
        return None


def _active_pending_ask_state(session_id: str) -> Any | None:
    ask_state = _lookup_pending_ask_state(session_id)
    if ask_state is None or ask_state.status != "pending":
        return None
    if ask_state.expires_at is not None and ask_state.expires_at <= time.time():
        return None
    return ask_state


def _ask_response_attachments_unsupported(
    user_id: str,
    session_id: str,
    ask_request_id: str,
) -> MessageDispatchOutcome:
    return MessageDispatchOutcome(
        success=False,
        user_id=user_id,
        session_id=session_id,
        handled_as="ask_response",
        ask_request_id=ask_request_id,
        error_code=ASK_RESPONSE_ATTACHMENTS_UNSUPPORTED,
        error_message=t(
            "chat.dispatch.errors.ask_response_attachments_unsupported",
            fallback="Attachments cannot be used as an answer to this question. Please send a text answer only.",
        ),
    )


def _ask_response_resolve_failed(
    user_id: str,
    session_id: str,
    ask_request_id: str,
) -> MessageDispatchOutcome:
    return MessageDispatchOutcome(
        success=False,
        user_id=user_id,
        session_id=session_id,
        handled_as="ask_response",
        ask_request_id=ask_request_id,
        error_code=ASK_RESPONSE_RESOLVE_FAILED,
        error_message=t(
            "chat.dispatch.errors.ask_response_resolve_failed",
            fallback="The question is no longer waiting for an answer.",
        ),
    )


def _ask_response_success(
    user_id: str,
    session_id: str,
    ask_request_id: str,
) -> MessageDispatchOutcome:
    return MessageDispatchOutcome(
        success=True,
        user_id=user_id,
        session_id=session_id,
        handled_as="ask_response",
        ask_request_id=ask_request_id,
    )


async def _resolve_active_persona_id() -> str | None:
    try:
        from ..personality.persona_repository import PersonaRepository
        from ..utils.runtime import get_runtime_paths

        repo = PersonaRepository(str(get_runtime_paths().persona_registry_db_path))
        await repo.init()
        active_id = await repo.get_active_id()
    except Exception:
        return None
    return str(active_id or "").strip() or None


def _normalize_attachments(attachments: list[dict[str, Any]] | None) -> list[dict[str, Any]]:
    if attachments is None:
        return []
    if not isinstance(attachments, list):
        raise ValueError(
            t(
                "chat.dispatch.errors.attachments_must_be_list",
                fallback="Attachments must be a list.",
            )
        )
    normalized: list[dict[str, Any]] = []
    for item in attachments:
        if not isinstance(item, dict):
            raise ValueError(
                t(
                    "chat.dispatch.errors.attachment_must_be_object",
                    fallback="Each attachment must be an object.",
                )
            )
        normalized_item = dict(item)
        attachment_kind = str(normalized_item.get("kind") or "").strip()
        if not attachment_kind:
            raise ValueError(
                t(
                    "chat.dispatch.errors.attachment_kind_required",
                    fallback="Each attachment must include a kind.",
                )
            )
        normalized_item["kind"] = attachment_kind
        normalized.append(normalized_item)
    return normalized


async def _prepare_runtime_attachments(
    *,
    session_id: str,
    turn_id: str,
    attachments: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    if not attachments:
        return []
    ingestion_service = LocalChatAttachmentIngestionService()
    return await asyncio.to_thread(
        _prepare_runtime_attachments_sync,
        ingestion_service,
        session_id,
        turn_id,
        attachments,
    )


def _prepare_runtime_attachments_sync(
    ingestion_service: LocalChatAttachmentIngestionService,
    session_id: str,
    turn_id: str,
    attachments: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    prepared: list[dict[str, Any]] = []
    for attachment in attachments:
        prepared.append(
            ingestion_service.prepare_runtime_attachment(
                session_id=session_id,
                turn_id=turn_id,
                attachment=attachment,
            )
        )
    return prepared


__all__ = [
    "ASK_RESPONSE_ATTACHMENTS_UNSUPPORTED",
    "ASK_RESPONSE_RESOLVE_FAILED",
    "CHAT_STORE_NOT_INITIALIZED",
    "CHAT_STORE_PERSIST_FAILED",
    "EMPTY_TURN",
    "MALFORMED_ATTACHMENTS",
    "MessageDispatchOutcome",
    "RUNTIME_COMMAND_QUEUE_ENQUEUE_FAILED",
    "RUNTIME_COMMAND_QUEUE_NOT_INITIALIZED",
    "RECALL_FEEDBACK_PENDING_ASK",
    "SESSION_ID_REQUIRED",
    "dispatch_user_message",
    "get_chat_read_service",
    "get_chat_projector",
    "get_chat_store",
    "require_runtime_command_queue",
    "resolve_control_interaction_broker",
    "resolve_control_session_store",
]
