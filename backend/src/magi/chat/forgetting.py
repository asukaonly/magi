"""User-requested chat deletion coordinated with durable memory forgetting."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Protocol

from ..core.chat_cleanup import ChatSurfaceCleanupPendingError
from ..core.logger import get_logger
from ..events.events import EventTypes
from ..memory.forgetting import ForgetOperation, ForgetOutcome
from .projector import CHAT_MEMORY_SOURCE
from .read.models import ChatMessageSourceIdentity, ChatSessionSummary
from .session_mutations import chat_session_mutation

_CHAT_MEMORY_EVENT_TYPES_BY_ROLE = {
    "assistant": EventTypes.AI_RESPONSE,
    "user": EventTypes.USER_MESSAGE,
}
logger = get_logger(__name__)


@dataclass(frozen=True, slots=True)
class ChatHistoryClearResult:
    """The immutable chat snapshot removed by one history clear."""

    message_ids: tuple[str, ...]
    turn_ids: tuple[str, ...]


class _ChatReadServiceProtocol(Protocol):
    async def aget_session_summary(
        self,
        user_id: str,
        session_id: str,
    ) -> ChatSessionSummary | None: ...

    async def alist_session_turn_ids(self, user_id: str, session_id: str) -> list[str]: ...

    async def aget_message_source_identity(
        self,
        user_id: str,
        session_id: str,
        message_id: str,
    ) -> ChatMessageSourceIdentity | None: ...

    async def alist_message_replacement_source_identities(
        self,
        user_id: str,
        session_id: str,
        message_id: str,
    ) -> list[ChatMessageSourceIdentity]: ...

    async def alist_session_message_source_identities(
        self,
        user_id: str,
        session_id: str,
    ) -> list[ChatMessageSourceIdentity]: ...

    async def aclear_conversation_history_snapshot(
        self,
        user_id: str,
        session_id: str,
        message_ids: list[str],
        turn_ids: list[str],
    ) -> None: ...

    async def aforget_message_artifacts(
        self,
        user_id: str,
        session_id: str,
        message_id: str,
    ) -> bool: ...

    async def adelete_session(self, user_id: str, session_id: str) -> None: ...


class _ChatSurfaceWriteServiceProtocol(Protocol):
    async def hide_message(
        self,
        *,
        user_id: str,
        session_id: str,
        message_id: str,
    ) -> bool: ...


class _AssistantMemoryOutboxProtocol(Protocol):
    async def cancel_assistant_memory_projections(
        self,
        *,
        canonical_message_ids: list[str] | tuple[str, ...] = (),
        session_id: str | None = None,
    ) -> int: ...


class _MemoryForgettingProtocol(Protocol):
    def chat_forget_operation_guard(self) -> object: ...

    async def prepare_chat_session_forget(
        self,
        *,
        user_id: str,
        session_id: str,
        turn_ids: list[str],
        reason: str,
    ) -> ForgetOperation: ...

    async def prepare_chat_message_forget(
        self,
        *,
        user_id: str,
        session_id: str,
        message_id: str,
        source_message_id: str,
        turn_id: str,
        source: str,
        event_type: str,
        runtime_turn_ids: list[str],
        runtime_replay_turn_ids: list[str],
        messages: list[dict[str, str]],
        surface_message_ids: list[str],
        reason: str,
    ) -> ForgetOperation: ...

    async def prepare_chat_history_forget(
        self,
        *,
        user_id: str,
        session_id: str,
        turn_ids: list[str],
        messages: list[dict[str, str]],
        surface_message_ids: list[str],
        reason: str,
    ) -> ForgetOperation: ...

    async def execute_prepared_forget(
        self,
        operation_id: str,
    ) -> ForgetOutcome: ...

    async def activate_chat_forget_intent(
        self,
        operation_id: str,
    ) -> ForgetOperation: ...

    async def list_chat_forget_intents_awaiting_runtime_barriers(
        self,
    ) -> list[ForgetOperation]: ...

    async def was_chat_session_forgotten(self, *, user_id: str, session_id: str) -> bool: ...

    async def list_pending_chat_surface_finalizations(
        self,
    ) -> list[ForgetOperation]: ...

    async def mark_chat_surface_finalized(self, operation_id: str) -> None: ...


class _RuntimeForgettingProtocol(Protocol):
    def forget_operation_boundary(self) -> object: ...

    async def prepare_session_delete(
        self,
        *,
        user_id: str,
        session_id: str,
    ) -> object: ...

    async def prepare_message_delete(
        self,
        *,
        user_id: str,
        session_id: str,
        turn_id: str,
        message_id: str,
        include_turn_scope: bool,
        run_id: str | None,
        run_revision: int,
        runtime_turn_ids: list[str],
        replay_turn_ids: list[str],
        related_message_ids: list[str] | None = None,
        background_task_ids: list[str] | None = None,
    ) -> object: ...

    def message_delete_boundary(
        self,
        *,
        user_id: str,
        session_id: str,
        turn_id: str,
        message_id: str,
        include_turn_scope: bool,
        run_id: str | None,
        run_revision: int,
        runtime_turn_ids: list[str],
        replay_turn_ids: list[str],
        related_message_ids: list[str],
        background_task_ids: list[str],
        prepare_intent: Callable[[list[str], list[str]], Awaitable[None]],
    ) -> object: ...

    def background_scope_boundary(
        self,
        *,
        user_id: str,
        session_id: str,
        turn_ids: list[str] | None,
        task_ids: list[str] | None = None,
        pending_message_ids: list[str] | None = None,
        reason: str,
    ) -> object: ...

    async def prepare_history_clear(
        self,
        *,
        user_id: str,
        session_id: str,
        turn_ids: list[str],
        message_ids: list[str],
    ) -> object: ...

    async def quiesce_history_clear(
        self,
        *,
        user_id: str,
        session_id: str,
    ) -> object: ...


class ChatForgettingService:
    """Keep chat truth visible until all projected memory is governed."""

    def __init__(
        self,
        *,
        chat_read_service: _ChatReadServiceProtocol,
        chat_surface_write_service: _ChatSurfaceWriteServiceProtocol,
        memory: _MemoryForgettingProtocol,
        runtime: _RuntimeForgettingProtocol,
        assistant_memory_outbox: _AssistantMemoryOutboxProtocol | None = None,
    ) -> None:
        self._chat_read_service = chat_read_service
        self._chat_surface_write_service = chat_surface_write_service
        self._memory = memory
        self._runtime = runtime
        self._assistant_memory_outbox = assistant_memory_outbox
        self._surface_finalizer = ChatSurfaceFinalizer(
            chat_read_service=chat_read_service,
            memory=memory,
            assistant_memory_outbox=assistant_memory_outbox,
        )

    async def delete_session(self, *, user_id: str, session_id: str) -> bool:
        """Govern projected memory before removing one chat transcript."""
        async with chat_session_mutation(session_id):
            async with self._runtime.forget_operation_boundary():
                async with self._memory.chat_forget_operation_guard():
                    async with self._runtime.background_scope_boundary(
                        user_id=user_id,
                        session_id=session_id,
                        turn_ids=None,
                        reason="user_delete_chat_session",
                    ):
                        return await self._delete_session_guarded(
                            user_id=user_id,
                            session_id=session_id,
                        )

    async def _delete_session_guarded(
        self,
        *,
        user_id: str,
        session_id: str,
    ) -> bool:
        session = await self._chat_read_service.aget_session_summary(
            user_id=user_id,
            session_id=session_id,
        )
        if session is None:
            return await self._memory.was_chat_session_forgotten(
                user_id=user_id,
                session_id=session_id,
            )
        turn_ids = await self._chat_read_service.alist_session_turn_ids(
            user_id,
            session_id,
        )
        operation = await self._memory.prepare_chat_session_forget(
            user_id=user_id,
            session_id=session_id,
            turn_ids=turn_ids,
            reason="user_delete_chat_session",
        )
        await self._runtime.prepare_session_delete(
            user_id=user_id,
            session_id=session_id,
        )
        await self._memory.activate_chat_forget_intent(operation.operation_id)
        await _cancel_assistant_memory_projection(
            self._assistant_memory_outbox,
            operation,
        )
        outcome = await self._memory.execute_prepared_forget(
            operation.operation_id,
        )
        await self._surface_finalizer.finalize_session(
            outcome=outcome,
            user_id=user_id,
            session_id=session_id,
        )
        return True

    async def delete_message(
        self,
        *,
        user_id: str,
        session_id: str,
        message_id: str,
    ) -> bool:
        """Govern one message's exact projection before hiding the message."""
        async with chat_session_mutation(session_id):
            async with self._runtime.forget_operation_boundary():
                async with self._memory.chat_forget_operation_guard():
                    return await self._delete_message_guarded(
                        user_id=user_id,
                        session_id=session_id,
                        message_id=message_id,
                    )

    async def _delete_message_guarded(
        self,
        *,
        user_id: str,
        session_id: str,
        message_id: str,
    ) -> bool:
        identity = await self._chat_read_service.aget_message_source_identity(
            user_id,
            session_id,
            message_id,
        )
        if identity is None:
            return False
        role = str(identity.role or "").strip().lower()
        event_type = _CHAT_MEMORY_EVENT_TYPES_BY_ROLE.get(role, "ChatMessage")
        operation: ForgetOperation | None = None
        replacement_identities = (
            await self._chat_read_service.alist_message_replacement_source_identities(
                user_id,
                session_id,
                identity.message_id,
            )
        )
        if not replacement_identities:
            raise RuntimeError(
                "Chat message disappeared before its replacement chain was frozen"
            )

        async def _prepare_intent(
            runtime_turn_ids: list[str],
            runtime_replay_turn_ids: list[str],
        ) -> None:
            nonlocal operation, replacement_identities
            latest_replacement_identities = (
                await self._chat_read_service.alist_message_replacement_source_identities(
                    user_id,
                    session_id,
                    identity.message_id,
                )
            )
            if not latest_replacement_identities:
                raise RuntimeError(
                    "Chat message disappeared before its replacement chain was frozen"
                )
            replacements_by_id = {
                replacement.message_id: replacement
                for replacement in replacement_identities
            }
            replacements_by_id.update(
                {
                    replacement.message_id: replacement
                    for replacement in latest_replacement_identities
                }
            )
            replacement_identities = [
                replacements_by_id[message_id]
                for message_id in dict.fromkeys(
                    [
                        *[
                            replacement.message_id
                            for replacement in replacement_identities
                        ],
                        *[
                            replacement.message_id
                            for replacement in latest_replacement_identities
                        ],
                    ]
                )
            ]
            memory_messages: list[dict[str, str]] = []
            seen_memory_sources: set[tuple[str, str]] = set()
            for replacement in replacement_identities:
                replacement_event_type = _CHAT_MEMORY_EVENT_TYPES_BY_ROLE.get(
                    str(replacement.role or "").strip().lower(),
                    "ChatMessage",
                )
                replacement_source_id = (
                    str(replacement.source_message_id or "").strip()
                    or replacement.message_id
                )
                source_key = (
                    replacement_source_id,
                    replacement_event_type,
                )
                if source_key in seen_memory_sources:
                    continue
                seen_memory_sources.add(source_key)
                memory_messages.append(
                    {
                        "message_id": replacement_source_id,
                        "source": CHAT_MEMORY_SOURCE,
                        "event_type": replacement_event_type,
                    }
                )
            operation = await self._memory.prepare_chat_message_forget(
                user_id=user_id,
                session_id=session_id,
                message_id=identity.message_id,
                source_message_id=(
                    str(identity.source_message_id or "").strip()
                    or identity.message_id
                ),
                turn_id=str(identity.turn_id or ""),
                source=CHAT_MEMORY_SOURCE,
                event_type=event_type,
                runtime_turn_ids=runtime_turn_ids,
                runtime_replay_turn_ids=runtime_replay_turn_ids,
                messages=memory_messages,
                surface_message_ids=[
                    replacement.message_id
                    for replacement in replacement_identities
                ],
                reason="user_delete_chat_message",
            )

        async with self._runtime.message_delete_boundary(
            user_id=user_id,
            session_id=session_id,
            turn_id=str(identity.turn_id or ""),
            message_id=identity.message_id,
            include_turn_scope=event_type == EventTypes.USER_MESSAGE,
            run_id=identity.run_id,
            run_revision=identity.run_revision,
            runtime_turn_ids=[str(identity.turn_id or "")],
            replay_turn_ids=[],
            related_message_ids=[
                replacement.message_id
                for replacement in replacement_identities
            ],
            background_task_ids=[
                task_id
                for task_id in dict.fromkeys(
                    replacement.background_task_id
                    for replacement in replacement_identities
                    if replacement.background_task_id
                )
            ],
            prepare_intent=_prepare_intent,
        ):
            if operation is None:
                raise RuntimeError("Chat message forget intent was not prepared")
            await self._memory.activate_chat_forget_intent(operation.operation_id)
            await _cancel_assistant_memory_projection(
                self._assistant_memory_outbox,
                operation,
            )
            outcome = await self._memory.execute_prepared_forget(
                operation.operation_id,
            )
            try:
                await self._surface_finalizer.finalize_message(
                    user_id=user_id,
                    session_id=session_id,
                    message_ids=[
                        replacement.message_id
                        for replacement in replacement_identities
                    ],
                )
            except ChatSurfaceCleanupPendingError:
                await self._hide_message_chain(
                    user_id=user_id,
                    session_id=session_id,
                    message_ids=[
                        replacement.message_id
                        for replacement in replacement_identities
                    ],
                )
                raise
            await self._hide_message_chain(
                user_id=user_id,
                session_id=session_id,
                message_ids=[
                    replacement.message_id
                    for replacement in replacement_identities
                ],
            )
            await self._memory.mark_chat_surface_finalized(outcome.operation_id)
            return True

    async def _hide_message_chain(
        self,
        *,
        user_id: str,
        session_id: str,
        message_ids: list[str],
    ) -> None:
        for message_id in reversed(list(dict.fromkeys(message_ids))):
            try:
                await self._chat_surface_write_service.hide_message(
                    user_id=user_id,
                    session_id=session_id,
                    message_id=message_id,
                )
            except Exception:
                logger.exception(
                    "Failed to publish a committed chat message removal",
                    message_id=message_id,
                )

    async def clear_history(
        self,
        *,
        user_id: str,
        session_id: str,
    ) -> ChatHistoryClearResult | None:
        """Govern the current transcript snapshot while preserving the session."""
        async with chat_session_mutation(session_id):
            async with self._runtime.forget_operation_boundary():
                async with self._memory.chat_forget_operation_guard():
                    async with self._runtime.background_scope_boundary(
                        user_id=user_id,
                        session_id=session_id,
                        turn_ids=None,
                        reason="user_clear_chat_history",
                    ):
                        return await self._clear_history_guarded(
                            user_id=user_id,
                            session_id=session_id,
                        )

    async def _clear_history_guarded(
        self,
        *,
        user_id: str,
        session_id: str,
    ) -> ChatHistoryClearResult | None:
        session = await self._chat_read_service.aget_session_summary(
            user_id,
            session_id,
        )
        if session is None:
            return None
        await self._runtime.quiesce_history_clear(
            user_id=user_id,
            session_id=session_id,
        )
        turn_ids = await self._chat_read_service.alist_session_turn_ids(
            user_id,
            session_id,
        )
        identities = await self._chat_read_service.alist_session_message_source_identities(
            user_id,
            session_id,
        )
        message_ids = [identity.message_id for identity in identities]
        messages: list[dict[str, str]] = []
        seen_memory_sources: set[tuple[str, str]] = set()
        for identity in identities:
            event_type = _CHAT_MEMORY_EVENT_TYPES_BY_ROLE.get(
                str(identity.role or "").strip().lower()
            )
            if event_type is None:
                continue
            source_message_id = (
                str(identity.source_message_id or "").strip()
                or identity.message_id
            )
            source_key = (source_message_id, event_type)
            if source_key in seen_memory_sources:
                continue
            seen_memory_sources.add(source_key)
            messages.append(
                {
                    "message_id": source_message_id,
                    "source": CHAT_MEMORY_SOURCE,
                    "event_type": event_type,
                }
            )
        operation = await self._memory.prepare_chat_history_forget(
            user_id=user_id,
            session_id=session_id,
            turn_ids=turn_ids,
            messages=messages,
            surface_message_ids=message_ids,
            reason="user_clear_chat_history",
        )
        await self._runtime.prepare_history_clear(
            user_id=user_id,
            session_id=session_id,
            turn_ids=turn_ids,
            message_ids=message_ids,
        )
        await self._memory.activate_chat_forget_intent(
            operation.operation_id
        )
        await _cancel_assistant_memory_projection(
            self._assistant_memory_outbox,
            operation,
        )
        outcome = await self._memory.execute_prepared_forget(
            operation.operation_id,
        )
        await self._surface_finalizer.finalize_history(
            outcome=outcome,
            user_id=user_id,
            session_id=session_id,
            message_ids=message_ids,
            turn_ids=turn_ids,
        )
        return ChatHistoryClearResult(
            message_ids=tuple(message_ids),
            turn_ids=tuple(turn_ids),
        )

    async def recover_pending_surface_finalizations(self) -> dict[str, int]:
        """Finish completed chat deletions left visible by an interrupted process."""
        async with self._runtime.forget_operation_boundary():
            async with self._memory.chat_forget_operation_guard():
                return await self._surface_finalizer.recover_pending()


class ChatSurfaceFinalizer:
    """Finalize chat-owned rows after durable memory forgetting completes."""

    def __init__(
        self,
        *,
        chat_read_service: _ChatReadServiceProtocol,
        memory: _MemoryForgettingProtocol,
        runtime: _RuntimeForgettingProtocol | None = None,
        assistant_memory_outbox: _AssistantMemoryOutboxProtocol | None = None,
    ) -> None:
        self._chat_read_service = chat_read_service
        self._memory = memory
        self._runtime = runtime
        self._assistant_memory_outbox = assistant_memory_outbox

    async def finalize_session(
        self,
        *,
        outcome: ForgetOutcome,
        user_id: str,
        session_id: str,
    ) -> None:
        await self._chat_read_service.adelete_session(user_id, session_id)
        await self._memory.mark_chat_surface_finalized(outcome.operation_id)

    async def finalize_message(
        self,
        *,
        user_id: str,
        session_id: str,
        message_ids: list[str],
    ) -> None:
        normalized_message_ids = list(
            dict.fromkeys(
                normalized
                for value in message_ids
                if (normalized := str(value or "").strip())
            )
        )
        if not normalized_message_ids:
            raise RuntimeError(
                "Completed chat message forget has no surface snapshot"
            )
        for message_id in reversed(normalized_message_ids):
            await self._chat_read_service.aforget_message_artifacts(
                user_id,
                session_id,
                message_id,
            )

    async def finalize_history(
        self,
        *,
        outcome: ForgetOutcome,
        user_id: str,
        session_id: str,
        message_ids: list[str],
        turn_ids: list[str],
    ) -> None:
        await self._chat_read_service.aclear_conversation_history_snapshot(
            user_id,
            session_id,
            message_ids,
            turn_ids,
        )
        await self._memory.mark_chat_surface_finalized(outcome.operation_id)

    async def recover_pending(self) -> dict[str, int]:
        stats = {"found": 0, "completed": 0}
        while True:
            operations = await self._memory.list_pending_chat_surface_finalizations()
            if not operations:
                return stats
            stats["found"] += len(operations)
            for operation in operations:
                await self._recover_operation(operation)
                stats["completed"] += 1

    async def _recover_operation(self, operation: ForgetOperation) -> None:
        if self._runtime is not None:
            await _prepare_runtime_forget_operation(
                runtime=self._runtime,
                operation=operation,
            )
        await _cancel_assistant_memory_projection(
            self._assistant_memory_outbox,
            operation,
        )
        payload = operation.selector.payload
        user_id = str(payload.get("user_id") or "").strip()
        session_id = str(payload.get("session_id") or "").strip()
        if not user_id or not session_id:
            raise RuntimeError("Completed chat forget operation has an invalid selector")
        if operation.selector.kind == "chat_session":
            await self._chat_read_service.adelete_session(user_id, session_id)
        elif operation.selector.kind == "chat_message":
            raw_message_ids = payload.get("surface_message_ids")
            if not isinstance(raw_message_ids, list):
                raise RuntimeError(
                    "Completed chat message forget has no surface snapshot"
                )
            await self.finalize_message(
                user_id=user_id,
                session_id=session_id,
                message_ids=[
                    message_id
                    for value in raw_message_ids
                    if (message_id := str(value or "").strip())
                ],
            )
        elif operation.selector.kind == "chat_history":
            raw_message_ids = payload.get("surface_message_ids")
            if not isinstance(raw_message_ids, list):
                raise RuntimeError("Completed chat history forget has no surface snapshot")
            raw_turn_ids = payload.get("turn_ids")
            if not isinstance(raw_turn_ids, list):
                raise RuntimeError("Completed chat history forget has no turn snapshot")
            message_ids = [
                message_id
                for raw_message_id in raw_message_ids
                if (message_id := str(raw_message_id or "").strip())
            ]
            turn_ids = [
                turn_id
                for raw_turn_id in raw_turn_ids
                if (turn_id := str(raw_turn_id or "").strip())
            ]
            async with chat_session_mutation(session_id):
                await self._chat_read_service.aclear_conversation_history_snapshot(
                    user_id,
                    session_id,
                    message_ids,
                    turn_ids,
                )
        else:
            raise RuntimeError("Unexpected chat surface forget selector")
        await self._memory.mark_chat_surface_finalized(operation.operation_id)


class ChatForgettingRecoveryService:
    """Activate interrupted chat deletions, then finish their chat surfaces."""

    def __init__(
        self,
        *,
        chat_read_service: _ChatReadServiceProtocol,
        memory: _MemoryForgettingProtocol,
        runtime: _RuntimeForgettingProtocol,
        assistant_memory_outbox: _AssistantMemoryOutboxProtocol | None = None,
    ) -> None:
        self._memory = memory
        self._runtime = runtime
        self._assistant_memory_outbox = assistant_memory_outbox
        self._surface_finalizer = ChatSurfaceFinalizer(
            chat_read_service=chat_read_service,
            memory=memory,
            runtime=runtime,
            assistant_memory_outbox=assistant_memory_outbox,
        )

    async def recover_pending(self) -> dict[str, int]:
        async with self._runtime.forget_operation_boundary():
            async with self._memory.chat_forget_operation_guard():
                return await self._recover_pending_guarded()

    async def _recover_pending_guarded(self) -> dict[str, int]:
        stats = {
            "intents_found": 0,
            "intents_activated": 0,
            "surfaces_found": 0,
            "surfaces_completed": 0,
        }
        while True:
            operations = (
                await self._memory.list_chat_forget_intents_awaiting_runtime_barriers()
            )
            if not operations:
                break
            stats["intents_found"] += len(operations)
            for operation in operations:
                await _prepare_runtime_forget_operation(
                    runtime=self._runtime,
                    operation=operation,
                )
                await self._memory.activate_chat_forget_intent(
                    operation.operation_id
                )
                await _cancel_assistant_memory_projection(
                    self._assistant_memory_outbox,
                    operation,
                )
                await self._memory.execute_prepared_forget(
                    operation.operation_id
                )
                stats["intents_activated"] += 1

        surface_stats = await self._surface_finalizer.recover_pending()
        stats["surfaces_found"] = surface_stats["found"]
        stats["surfaces_completed"] = surface_stats["completed"]
        return stats


async def _prepare_runtime_forget_operation(
    *,
    runtime: _RuntimeForgettingProtocol,
    operation: ForgetOperation,
) -> None:
    payload = operation.selector.payload
    user_id = str(payload.get("user_id") or "").strip()
    session_id = str(payload.get("session_id") or "").strip()
    if not user_id or not session_id:
        raise RuntimeError("Chat forget intent has an invalid owner scope")
    if operation.selector.kind == "chat_session":
        await runtime.prepare_session_delete(
            user_id=user_id,
            session_id=session_id,
        )
        return
    if operation.selector.kind == "chat_message":
        message_id = str(payload.get("message_id") or "").strip()
        turn_id = str(payload.get("turn_id") or "").strip()
        event_type = str(payload.get("event_type") or "").strip()
        raw_runtime_turn_ids = payload.get("runtime_turn_ids")
        runtime_turn_ids = (
            [
                normalized
                for value in raw_runtime_turn_ids
                if (normalized := str(value or "").strip())
            ]
            if isinstance(raw_runtime_turn_ids, list)
            else [turn_id]
        )
        raw_runtime_replay_turn_ids = payload.get(
            "runtime_replay_turn_ids"
        )
        runtime_replay_turn_ids = (
            [
                normalized
                for value in raw_runtime_replay_turn_ids
                if (normalized := str(value or "").strip())
            ]
            if isinstance(raw_runtime_replay_turn_ids, list)
            else []
        )
        if not message_id:
            raise RuntimeError("Chat message forget intent has no message ID")
        await runtime.prepare_message_delete(
            user_id=user_id,
            session_id=session_id,
            turn_id=turn_id,
            message_id=message_id,
            include_turn_scope=event_type == EventTypes.USER_MESSAGE,
            run_id=None,
            run_revision=0,
            runtime_turn_ids=runtime_turn_ids,
            replay_turn_ids=runtime_replay_turn_ids,
            related_message_ids=[
                message_id
                for value in payload.get("surface_message_ids", [])
                if (message_id := str(value or "").strip())
            ],
        )
        return
    if operation.selector.kind == "chat_history":
        raw_turn_ids = payload.get("turn_ids")
        raw_message_ids = payload.get("surface_message_ids")
        if not isinstance(raw_turn_ids, list) or not isinstance(
            raw_message_ids,
            list,
        ):
            raise RuntimeError("Chat history forget intent has no source snapshot")
        await runtime.prepare_history_clear(
            user_id=user_id,
            session_id=session_id,
            turn_ids=[
                turn_id
                for value in raw_turn_ids
                if (turn_id := str(value or "").strip())
            ],
            message_ids=[
                message_id
                for value in raw_message_ids
                if (message_id := str(value or "").strip())
            ],
        )
        return
    raise RuntimeError("Unexpected chat forget intent selector")


async def _cancel_assistant_memory_projection(
    outbox: _AssistantMemoryOutboxProtocol | None,
    operation: ForgetOperation,
) -> None:
    """Cancel projection work only after the durable forget intent is active."""

    if outbox is None:
        return
    payload = operation.selector.payload
    if operation.selector.kind == "chat_session":
        session_id = str(payload.get("session_id") or "").strip()
        if not session_id:
            raise RuntimeError("Chat session forget intent has no session ID")
        await outbox.cancel_assistant_memory_projections(session_id=session_id)
        return
    if operation.selector.kind == "chat_message":
        raw_messages = payload.get("messages")
        if not isinstance(raw_messages, list):
            raise RuntimeError("Chat message forget intent has no source snapshot")
        source_message_ids = [
            message_id
            for item in raw_messages
            if isinstance(item, dict)
            and (message_id := str(item.get("message_id") or "").strip())
        ]
        if not source_message_ids:
            raise RuntimeError("Chat message forget intent has no source messages")
        await outbox.cancel_assistant_memory_projections(
            canonical_message_ids=source_message_ids,
        )
        return
    if operation.selector.kind == "chat_history":
        raw_messages = payload.get("messages")
        if not isinstance(raw_messages, list):
            raise RuntimeError("Chat history forget intent has no source snapshot")
        canonical_message_ids = [
            message_id
            for item in raw_messages
            if isinstance(item, dict)
            and (message_id := str(item.get("message_id") or "").strip())
        ]
        await outbox.cancel_assistant_memory_projections(
            canonical_message_ids=canonical_message_ids,
        )


def get_chat_forgetting_service() -> ChatForgettingService:
    """Build the chat-owned deletion coordinator from active runtime bindings."""
    from ..core.runtime_bindings import (
        get_optional_background_task_manager,
        get_optional_agent_runtime,
        require_chat_read_service,
        require_chat_surface_write_service,
        require_runtime_command_queue,
    )
    from ..memory.provider import get_unified_memory
    from .provider import get_chat_store
    from .user_turn_delivery import ChatUserTurnDeliveryScheduler
    from .runtime_forgetting import ChatRuntimeForgettingCoordinator

    agent_runtime = get_optional_agent_runtime()
    task_agent_manager = (
        agent_runtime.get_task_agent_manager() if agent_runtime is not None else None
    )
    source_hub = agent_runtime.get_source_hub() if agent_runtime is not None else None
    post_turn_understanding_service = (
        agent_runtime.get_post_turn_understanding_service()
        if agent_runtime is not None
        and hasattr(agent_runtime, "get_post_turn_understanding_service")
        else None
    )
    runtime_command_queue = require_runtime_command_queue()
    chat_read_service = require_chat_read_service()
    unified_memory = get_unified_memory()
    chat_store = get_chat_store()

    return ChatForgettingService(
        chat_read_service=chat_read_service,
        chat_surface_write_service=require_chat_surface_write_service(),
        memory=unified_memory,
        assistant_memory_outbox=chat_store,
        runtime=ChatRuntimeForgettingCoordinator(
            runtime_command_queue=runtime_command_queue,
            task_agent_manager=task_agent_manager,
            source_hub=source_hub,
            chat_read_service=chat_read_service,
            delivery_scheduler=ChatUserTurnDeliveryScheduler(
                chat_store=chat_store,
                runtime_command_queue=runtime_command_queue,
            ),
            l0_store=unified_memory.l0,
            post_turn_understanding_service=post_turn_understanding_service,
            background_task_manager=get_optional_background_task_manager(),
        ),
    )


__all__ = [
    "ChatForgettingService",
    "ChatForgettingRecoveryService",
    "ChatSurfaceFinalizer",
    "get_chat_forgetting_service",
]
