"""User-requested chat deletion coordinated with durable memory forgetting."""

from __future__ import annotations

from typing import Protocol

from ..events.events import EventTypes
from ..memory.forgetting import ForgetOperation, ForgetOutcome
from .projector import CHAT_MEMORY_SOURCE
from .read.models import ChatMessageSourceIdentity, ChatSessionSummary
from .session_mutations import chat_session_mutation

_CHAT_MEMORY_EVENT_TYPES_BY_ROLE = {
    "assistant": EventTypes.AI_RESPONSE,
    "user": EventTypes.USER_MESSAGE,
}


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


class _MemoryForgettingProtocol(Protocol):
    async def forget_chat_session_sources(
        self,
        *,
        user_id: str,
        session_id: str,
        turn_ids: list[str],
        reason: str,
    ) -> ForgetOutcome: ...

    async def forget_chat_message_source(
        self,
        *,
        user_id: str,
        session_id: str,
        message_id: str,
        source: str,
        event_type: str,
        reason: str,
    ) -> ForgetOutcome: ...

    async def forget_chat_history_sources(
        self,
        *,
        user_id: str,
        session_id: str,
        turn_ids: list[str],
        messages: list[dict[str, str]],
        surface_message_ids: list[str],
        reason: str,
    ) -> ForgetOutcome: ...

    async def was_chat_session_forgotten(self, *, user_id: str, session_id: str) -> bool: ...

    async def list_pending_chat_surface_finalizations(
        self,
    ) -> list[ForgetOperation]: ...

    async def mark_chat_surface_finalized(self, operation_id: str) -> None: ...


class _RuntimeForgettingProtocol(Protocol):
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
    ) -> object: ...

    async def prepare_history_clear(
        self,
        *,
        user_id: str,
        session_id: str,
        turn_ids: list[str],
        messages: list[ChatMessageSourceIdentity],
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
    ) -> None:
        self._chat_read_service = chat_read_service
        self._chat_surface_write_service = chat_surface_write_service
        self._memory = memory
        self._runtime = runtime
        self._surface_finalizer = ChatSurfaceFinalizer(
            chat_read_service=chat_read_service,
            memory=memory,
        )

    async def delete_session(self, *, user_id: str, session_id: str) -> bool:
        """Govern projected memory before removing one chat transcript."""
        session = await self._chat_read_service.aget_session_summary(user_id, session_id)
        if session is None:
            return await self._memory.was_chat_session_forgotten(
                user_id=user_id,
                session_id=session_id,
            )
        turn_ids = await self._chat_read_service.alist_session_turn_ids(user_id, session_id)
        await self._runtime.prepare_session_delete(
            user_id=user_id,
            session_id=session_id,
        )
        outcome = await self._memory.forget_chat_session_sources(
            user_id=user_id,
            session_id=session_id,
            turn_ids=turn_ids,
            reason="user_delete_chat_session",
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
        identity = await self._chat_read_service.aget_message_source_identity(
            user_id,
            session_id,
            message_id,
        )
        if identity is None:
            return False
        await self._runtime.prepare_message_delete(
            user_id=user_id,
            session_id=session_id,
            turn_id=str(identity.turn_id or ""),
            message_id=identity.message_id,
        )
        role = str(identity.role or "").strip().lower()
        event_type = _CHAT_MEMORY_EVENT_TYPES_BY_ROLE.get(role, "ChatMessage")
        outcome = await self._memory.forget_chat_message_source(
            user_id=user_id,
            session_id=session_id,
            message_id=identity.message_id,
            source=CHAT_MEMORY_SOURCE,
            event_type=event_type,
            reason="user_delete_chat_message",
        )
        await self._surface_finalizer.finalize_message(
            outcome=outcome,
            user_id=user_id,
            session_id=session_id,
            message_id=message_id,
        )
        await self._chat_surface_write_service.hide_message(
            user_id=user_id,
            session_id=session_id,
            message_id=message_id,
        )
        await self._memory.mark_chat_surface_finalized(outcome.operation_id)
        return True

    async def clear_history(self, *, user_id: str, session_id: str) -> bool:
        """Govern the current transcript snapshot while preserving the session."""
        async with chat_session_mutation(session_id):
            session = await self._chat_read_service.aget_session_summary(user_id, session_id)
            if session is None:
                return False
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
            await self._runtime.prepare_history_clear(
                user_id=user_id,
                session_id=session_id,
                turn_ids=turn_ids,
                messages=identities,
            )
            messages = [
                {
                    "message_id": identity.message_id,
                    "source": CHAT_MEMORY_SOURCE,
                    "event_type": event_type,
                }
                for identity in identities
                if (
                    event_type := _CHAT_MEMORY_EVENT_TYPES_BY_ROLE.get(
                        str(identity.role or "").strip().lower()
                    )
                )
                is not None
            ]
            outcome = await self._memory.forget_chat_history_sources(
                user_id=user_id,
                session_id=session_id,
                turn_ids=turn_ids,
                messages=messages,
                surface_message_ids=[identity.message_id for identity in identities],
                reason="user_clear_chat_history",
            )
            await self._surface_finalizer.finalize_history(
                outcome=outcome,
                user_id=user_id,
                session_id=session_id,
                message_ids=[identity.message_id for identity in identities],
                turn_ids=turn_ids,
            )
            return True

    async def recover_pending_surface_finalizations(self) -> dict[str, int]:
        """Finish completed chat deletions left visible by an interrupted process."""
        return await self._surface_finalizer.recover_pending()


class ChatSurfaceFinalizer:
    """Finalize chat-owned rows after durable memory forgetting completes."""

    def __init__(
        self,
        *,
        chat_read_service: _ChatReadServiceProtocol,
        memory: _MemoryForgettingProtocol,
    ) -> None:
        self._chat_read_service = chat_read_service
        self._memory = memory

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
        outcome: ForgetOutcome,
        user_id: str,
        session_id: str,
        message_id: str,
    ) -> None:
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
        payload = operation.selector.payload
        user_id = str(payload.get("user_id") or "").strip()
        session_id = str(payload.get("session_id") or "").strip()
        if not user_id or not session_id:
            raise RuntimeError("Completed chat forget operation has an invalid selector")
        if operation.selector.kind == "chat_session":
            await self._chat_read_service.adelete_session(user_id, session_id)
        elif operation.selector.kind == "chat_message":
            message_id = str(payload.get("message_id") or "").strip()
            if not message_id:
                raise RuntimeError("Completed chat message forget has no message ID")
            await self._chat_read_service.aforget_message_artifacts(
                user_id,
                session_id,
                message_id,
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


def get_chat_forgetting_service() -> ChatForgettingService:
    """Build the chat-owned deletion coordinator from active runtime bindings."""
    from ..core.runtime_bindings import (
        get_optional_agent_runtime,
        require_chat_read_service,
        require_chat_surface_write_service,
        require_runtime_command_queue,
    )
    from ..memory.provider import get_unified_memory
    from .runtime_forgetting import ChatRuntimeForgettingCoordinator

    agent_runtime = get_optional_agent_runtime()
    task_agent_manager = (
        agent_runtime.get_task_agent_manager() if agent_runtime is not None else None
    )
    sensor_hub = agent_runtime.get_sensor_hub() if agent_runtime is not None else None

    return ChatForgettingService(
        chat_read_service=require_chat_read_service(),
        chat_surface_write_service=require_chat_surface_write_service(),
        memory=get_unified_memory(),
        runtime=ChatRuntimeForgettingCoordinator(
            runtime_command_queue=require_runtime_command_queue(),
            task_agent_manager=task_agent_manager,
            sensor_hub=sensor_hub,
        ),
    )


__all__ = [
    "ChatForgettingService",
    "ChatSurfaceFinalizer",
    "get_chat_forgetting_service",
]
