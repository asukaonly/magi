"""Focused collaborators for chat post-processing side effects."""
from __future__ import annotations

from typing import Any, Callable

from magi.agent.task_agents.common import AssistantResponsePlan
from magi.chat import ChatMessageRecord, ChatStore

from .message_payloads import resolve_reaction_text
from .message_selection import ChatOutcomeMessageSelector
from .message_writes import ChatAssistantMessageWriter
from .notifications import ChatRuntimeNotifier
from .turn_writes import ChatTurnStateWriter


class ChatOutcomeWriter:
    """Facade for persisting chat outcomes without owning every write rule."""

    def __init__(
        self,
        *,
        chat_store: ChatStore | None,
        trace_id_factory: Callable[[str], str],
    ) -> None:
        self._chat_store = chat_store
        self._trace_id_factory = trace_id_factory
        self._turn_state_writer = ChatTurnStateWriter(
            chat_store=chat_store,
            trace_id_factory=trace_id_factory,
        )
        self._message_writer = ChatAssistantMessageWriter(chat_store=chat_store)
        self._message_selector = ChatOutcomeMessageSelector(chat_store=chat_store)

    async def commit_final_chat_outcome(
        self,
        *,
        turn_id: str | None,
        delivery_attempt_no: int,
        command_id: int,
        orchestration_id: str | None,
        execution_mode: str | None,
        ux_plan: dict[str, Any] | None,
        response_text: str,
        attachments: list[dict[str, Any]] | None = None,
        message_payload: dict[str, Any] | None = None,
        started_at_ms: int,
        completed_at_ms: int,
        context_usage: dict[str, Any] | None = None,
        run_id: str | None = None,
        run_revision: int = 0,
        run_disposition: str | None = None,
        reply_to_message_id: str | None = None,
        persona_id: str | None = None,
    ) -> bool:
        """Atomically commit one exact admitted final outcome."""

        if self._chat_store is None:
            await self.persist_final_chat_outcome(
                turn_id=turn_id,
                orchestration_id=orchestration_id,
                execution_mode=execution_mode,
                ux_plan=ux_plan,
                response_text=response_text,
                attachments=attachments,
                message_payload=message_payload,
                started_at_ms=started_at_ms,
                completed_at_ms=completed_at_ms,
                context_usage=context_usage,
                run_id=run_id,
                run_revision=run_revision,
                run_disposition=run_disposition,
                reply_to_message_id=reply_to_message_id,
                persona_id=persona_id,
            )
            return True
        turn_write = await self._turn_state_writer.resolve_turn_completion(
            turn_id=turn_id,
            ux_plan=ux_plan,
        )
        if turn_write is None:
            return False
        messages: list[ChatMessageRecord] = []
        if turn_write.response_mode not in {"reaction_only", "none"}:
            messages.append(
                await self._message_writer.build_final_message(
                    turn=turn_write.turn,
                    turn_id=turn_write.turn_id,
                    response_text=response_text,
                    attachments=attachments,
                    message_payload=message_payload,
                    completed_at_ms=completed_at_ms,
                    reply_to_message_id=reply_to_message_id,
                    persona_id=persona_id,
                )
            )
        committed = await self._chat_store.commit_user_turn_assistant_outcome(
            turn_id=turn_write.turn_id,
            delivery_attempt_no=delivery_attempt_no,
            command_id=command_id,
            messages=messages,
            attachment_payloads_by_message_id={
                message.message_id: (attachments or None)
                for message in messages
            },
            trace_id=self._trace_id_factory(turn_write.turn_id),
            orchestration_id=orchestration_id,
            execution_mode=execution_mode,
            ux_plan=turn_write.ux_plan,
            response_mode=turn_write.response_mode,
            started_at_ms=started_at_ms,
            completed_at_ms=completed_at_ms,
            context_usage=context_usage,
            run_id=run_id,
            run_revision=run_revision,
            run_disposition=run_disposition,
        )
        return committed is not None

    async def commit_segmented_chat_outcome(
        self,
        *,
        turn_id: str | None,
        delivery_attempt_no: int,
        command_id: int,
        orchestration_id: str | None,
        execution_mode: str | None,
        ux_plan: dict[str, Any] | None,
        response_plan: AssistantResponsePlan,
        attachments: list[dict[str, Any]] | None = None,
        message_payload: dict[str, Any] | None = None,
        started_at_ms: int,
        completed_at_ms: int,
        context_usage: dict[str, Any] | None = None,
        run_id: str | None = None,
        run_revision: int = 0,
        run_disposition: str | None = None,
        reply_to_message_id: str | None = None,
        persona_id: str | None = None,
    ) -> tuple[bool, list[ChatMessageRecord]]:
        """Atomically commit one exact admitted segmented outcome."""

        if self._chat_store is None:
            messages = await self.persist_segmented_chat_outcome(
                turn_id=turn_id,
                orchestration_id=orchestration_id,
                execution_mode=execution_mode,
                ux_plan=ux_plan,
                response_plan=response_plan,
                attachments=attachments,
                message_payload=message_payload,
                started_at_ms=started_at_ms,
                completed_at_ms=completed_at_ms,
                context_usage=context_usage,
                run_id=run_id,
                run_revision=run_revision,
                run_disposition=run_disposition,
                reply_to_message_id=reply_to_message_id,
                persona_id=persona_id,
            )
            return True, messages
        turn_write = await self._turn_state_writer.resolve_turn_completion(
            turn_id=turn_id,
            ux_plan=ux_plan,
        )
        if turn_write is None:
            return False, []
        messages: list[ChatMessageRecord] = []
        if turn_write.response_mode not in {"reaction_only", "none"}:
            messages = await self._message_writer.build_rhythm_segments(
                turn=turn_write.turn,
                turn_id=turn_write.turn_id,
                response_plan=response_plan,
                attachments=attachments,
                message_payload=message_payload,
                completed_at_ms=completed_at_ms,
                reply_to_message_id=reply_to_message_id,
                persona_id=persona_id,
            )
        attachment_payloads = {
            message.message_id: (
                (attachments or None)
                if index == len(messages) - 1
                else None
            )
            for index, message in enumerate(messages)
        }
        committed = await self._chat_store.commit_user_turn_assistant_outcome(
            turn_id=turn_write.turn_id,
            delivery_attempt_no=delivery_attempt_no,
            command_id=command_id,
            messages=messages,
            attachment_payloads_by_message_id=attachment_payloads,
            trace_id=self._trace_id_factory(turn_write.turn_id),
            orchestration_id=orchestration_id,
            execution_mode=execution_mode,
            ux_plan=turn_write.ux_plan,
            response_mode=turn_write.response_mode,
            started_at_ms=started_at_ms,
            completed_at_ms=completed_at_ms,
            context_usage=context_usage,
            run_id=run_id,
            run_revision=run_revision,
            run_disposition=run_disposition,
        )
        return (
            (False, [])
            if committed is None
            else (True, committed)
        )

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
        context_usage: dict[str, Any] | None = None,
        run_id: str | None = None,
        run_revision: int = 0,
        run_disposition: str | None = None,
        reply_to_message_id: str | None = None,
        persona_id: str | None = None,
    ) -> bool:
        if self._chat_store is None:
            return True
        turn_write = await self._turn_state_writer.resolve_turn_completion(
            turn_id=turn_id,
            ux_plan=ux_plan,
        )
        if turn_write is None:
            return False
        messages: list[ChatMessageRecord] = []
        if turn_write.response_mode not in {"reaction_only", "none"}:
            messages.append(
                await self._message_writer.build_final_message(
                    turn=turn_write.turn,
                    turn_id=turn_write.turn_id,
                    response_text=response_text,
                    attachments=attachments,
                    message_payload=message_payload,
                    completed_at_ms=completed_at_ms,
                    reply_to_message_id=reply_to_message_id,
                    persona_id=persona_id,
                )
            )
        committed = await self._chat_store.commit_unmanaged_assistant_outcome(
            turn_id=turn_write.turn_id,
            messages=messages,
            attachment_payloads_by_message_id={
                message.message_id: (attachments or None)
                for message in messages
            },
            trace_id=self._trace_id_factory(turn_write.turn_id),
            orchestration_id=orchestration_id,
            execution_mode=execution_mode,
            ux_plan=turn_write.ux_plan,
            response_mode=turn_write.response_mode,
            started_at_ms=started_at_ms,
            completed_at_ms=completed_at_ms,
            context_usage=context_usage,
            run_id=run_id,
            run_revision=run_revision,
            run_disposition=run_disposition,
        )
        return committed is not None

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
        context_usage: dict[str, Any] | None = None,
        run_id: str | None = None,
        run_revision: int = 0,
        run_disposition: str | None = None,
        reply_to_message_id: str | None = None,
        persona_id: str | None = None,
    ) -> list[ChatMessageRecord]:
        turn_write = await self._turn_state_writer.resolve_turn_completion(
            turn_id=turn_id,
            ux_plan=ux_plan,
        )
        if turn_write is None:
            return []
        messages: list[ChatMessageRecord] = []
        if turn_write.response_mode not in {"reaction_only", "none"}:
            messages = await self._message_writer.build_rhythm_segments(
                turn=turn_write.turn,
                turn_id=turn_write.turn_id,
                response_plan=response_plan,
                attachments=attachments,
                message_payload=message_payload,
                completed_at_ms=completed_at_ms,
                reply_to_message_id=reply_to_message_id,
                persona_id=persona_id,
            )
        if self._chat_store is None:
            return []
        attachment_payloads = {
            message.message_id: (
                (attachments or None)
                if index == len(messages) - 1
                else None
            )
            for index, message in enumerate(messages)
        }
        committed = await self._chat_store.commit_unmanaged_assistant_outcome(
            turn_id=turn_write.turn_id,
            messages=messages,
            attachment_payloads_by_message_id=attachment_payloads,
            trace_id=self._trace_id_factory(turn_write.turn_id),
            orchestration_id=orchestration_id,
            execution_mode=execution_mode,
            ux_plan=turn_write.ux_plan,
            response_mode=turn_write.response_mode,
            started_at_ms=started_at_ms,
            completed_at_ms=completed_at_ms,
            context_usage=context_usage,
            run_id=run_id,
            run_revision=run_revision,
            run_disposition=run_disposition,
        )
        return committed or []

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
