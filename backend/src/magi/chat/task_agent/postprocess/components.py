"""Focused collaborators for chat post-processing side effects."""
from __future__ import annotations

from typing import Any, Callable

from magi.agent.task_agents.common import AssistantResponsePlan
from magi.chat import ChatMessageRecord, ChatProjector, ChatStore

from .message_payloads import resolve_reaction_text
from .message_selection import ChatOutcomeMessageSelector
from .message_writes import ChatAssistantMessageWriter
from .notifications import ChatRuntimeNotifier
from .projection_writes import ChatMessageProjectionWriter
from .turn_writes import ChatTurnStateWriter


class ChatOutcomeWriter:
    """Facade for persisting chat outcomes without owning every write rule."""

    def __init__(
        self,
        *,
        chat_store: ChatStore | None,
        chat_projector: ChatProjector | None,
        trace_id_factory: Callable[[str], str],
    ) -> None:
        self._turn_state_writer = ChatTurnStateWriter(
            chat_store=chat_store,
            trace_id_factory=trace_id_factory,
        )
        self._message_writer = ChatAssistantMessageWriter(chat_store=chat_store)
        self._message_selector = ChatOutcomeMessageSelector(chat_store=chat_store)
        self._projection_writer = ChatMessageProjectionWriter(chat_projector=chat_projector)

    async def persist_turn_ux_plan(
        self,
        *,
        turn_id: str,
        execution_mode: str | None,
        ux_plan: dict[str, Any] | None,
        updated_at_ms: int,
        run_id: str | None = None,
        run_revision: int = 0,
        run_disposition: str | None = None,
    ) -> None:
        turn_write = await self._turn_state_writer.persist_turn_ux_plan(
            turn_id=turn_id,
            execution_mode=execution_mode,
            ux_plan=ux_plan,
            updated_at_ms=updated_at_ms,
            run_id=run_id,
            run_revision=run_revision,
            run_disposition=run_disposition,
        )
        if turn_write is None:
            return
        if turn_write.response_mode == "interim_then_final":
            await self._message_writer.append_interim_message(
                turn=turn_write.turn,
                turn_id=turn_write.turn_id,
                ux_plan=turn_write.ux_plan,
                updated_at_ms=updated_at_ms,
            )
            return
        if turn_write.response_mode == "reaction_only":
            await self._message_writer.apply_reaction_label(
                turn=turn_write.turn,
                turn_id=turn_write.turn_id,
                ux_plan=turn_write.ux_plan,
                updated_at_ms=updated_at_ms,
            )

    async def persist_final_chat_outcome(
        self,
        *,
        turn_id: str | None,
        orchestration_id: str | None,
        execution_mode: str | None,
        ux_plan: dict[str, Any] | None,
        response_text: str,
        attachments: list[dict[str, Any]] | None = None,
        message_payload: dict[str, Any] | None = None,
        started_at_ms: int,
        completed_at_ms: int,
        run_id: str | None = None,
        run_revision: int = 0,
        run_disposition: str | None = None,
        reply_to_message_id: str | None = None,
        persona_id: str | None = None,
    ) -> None:
        turn_write = await self._turn_state_writer.complete_turn(
            turn_id=turn_id,
            orchestration_id=orchestration_id,
            execution_mode=execution_mode,
            ux_plan=ux_plan,
            started_at_ms=started_at_ms,
            completed_at_ms=completed_at_ms,
            run_id=run_id,
            run_revision=run_revision,
            run_disposition=run_disposition,
        )
        if turn_write is None or turn_write.response_mode in {"reaction_only", "none"}:
            return
        await self._message_writer.append_final_message(
            turn=turn_write.turn,
            turn_id=turn_write.turn_id,
            response_text=response_text,
            attachments=attachments,
            message_payload=message_payload,
            completed_at_ms=completed_at_ms,
            reply_to_message_id=reply_to_message_id,
            persona_id=persona_id,
        )

    async def persist_segmented_chat_outcome(
        self,
        *,
        turn_id: str | None,
        orchestration_id: str | None,
        execution_mode: str | None,
        ux_plan: dict[str, Any] | None,
        response_plan: AssistantResponsePlan,
        attachments: list[dict[str, Any]] | None = None,
        message_payload: dict[str, Any] | None = None,
        started_at_ms: int,
        completed_at_ms: int,
        run_id: str | None = None,
        run_revision: int = 0,
        run_disposition: str | None = None,
        reply_to_message_id: str | None = None,
        persona_id: str | None = None,
    ) -> list[ChatMessageRecord]:
        turn_write = await self._turn_state_writer.complete_turn(
            turn_id=turn_id,
            orchestration_id=orchestration_id,
            execution_mode=execution_mode,
            ux_plan=ux_plan,
            started_at_ms=started_at_ms,
            completed_at_ms=completed_at_ms,
            run_id=run_id,
            run_revision=run_revision,
            run_disposition=run_disposition,
        )
        if turn_write is None or turn_write.response_mode in {"reaction_only", "none"}:
            return []
        return await self._message_writer.append_rhythm_segments(
            turn=turn_write.turn,
            turn_id=turn_write.turn_id,
            response_plan=response_plan,
            attachments=attachments,
            message_payload=message_payload,
            completed_at_ms=completed_at_ms,
            reply_to_message_id=reply_to_message_id,
            persona_id=persona_id,
        )

    async def persist_turn_supersession(
        self,
        *,
        turn_id: str,
        anchor_turn_id: str,
        reason: str,
        updated_at_ms: int,
    ) -> None:
        await self._turn_state_writer.persist_turn_supersession(
            turn_id=turn_id,
            anchor_turn_id=anchor_turn_id,
            reason=reason,
            updated_at_ms=updated_at_ms,
        )

    async def get_notification_chat_message(
        self,
        *,
        turn_id: str | None,
        ux_plan: dict[str, Any] | None,
    ) -> ChatMessageRecord | None:
        return await self._message_selector.get_notification_chat_message(
            turn_id=turn_id,
            ux_plan=ux_plan,
        )

    async def get_turn_ux_chat_message(
        self,
        *,
        turn_id: str | None,
        ux_plan: dict[str, Any] | None,
    ) -> ChatMessageRecord | None:
        return await self._message_selector.get_turn_ux_chat_message(
            turn_id=turn_id,
            ux_plan=ux_plan,
        )

    async def project_final_chat_message(
        self,
        *,
        user_id: str,
        session_id: str,
        final_message: ChatMessageRecord | None,
    ) -> None:
        await self._projection_writer.project_final_chat_message(
            user_id=user_id,
            session_id=session_id,
            final_message=final_message,
        )

    async def project_canonical_assistant_response(
        self,
        *,
        user_id: str,
        session_id: str,
        turn_id: str | None,
        message_id: str | None,
        content: str,
        created_at_ms: int,
    ) -> None:
        await self._projection_writer.project_canonical_assistant_response(
            user_id=user_id,
            session_id=session_id,
            turn_id=turn_id,
            message_id=message_id,
            content=content,
            created_at_ms=created_at_ms,
        )

    async def get_chat_message(
        self,
        *,
        turn_id: str | None,
        message_kind: str,
    ) -> ChatMessageRecord | None:
        return await self._message_selector.get_chat_message(
            turn_id=turn_id,
            message_kind=message_kind,
        )

    @staticmethod
    def resolve_reaction_text(ux_plan: dict[str, Any] | None) -> str:
        return resolve_reaction_text(ux_plan)


__all__ = ["ChatOutcomeWriter", "ChatRuntimeNotifier"]
