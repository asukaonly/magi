"""Chat outcome persistence helpers for post-processing."""

from __future__ import annotations

from typing import Any, Protocol, cast

from magi.chat import ChatMessageRecord
from magi.agent.task_agents.common import AssistantResponsePlan
from .components import ChatOutcomeWriter
from .message_payloads import resolve_reaction_text


class _OutcomePostprocessHostProtocol(Protocol):
    _chat_outcome_writer: ChatOutcomeWriter
    _chat_store: Any


class ChatPostprocessOutcomeMixin:
    """Persist, fetch, and project chat outcome records."""

    async def _persist_turn_ux_plan(
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
        host = cast(_OutcomePostprocessHostProtocol, self)
        await host._chat_outcome_writer.persist_turn_ux_plan(
            turn_id=turn_id,
            execution_mode=execution_mode,
            ux_plan=ux_plan,
            updated_at_ms=updated_at_ms,
            run_id=run_id,
            run_revision=run_revision,
            run_disposition=run_disposition,
        )

    async def _persist_final_chat_outcome(
        self,
        *,
        turn_id: str | None,
        response_text: str,
        attachments: list[dict[str, Any]] | None = None,
        message_payload: dict[str, Any] | None = None,
        started_at_ms: int,
        completed_at_ms: int,
        context_usage: dict[str, Any] | None,
        execution_mode: str | None,
        ux_plan: dict[str, Any] | None,
        run_id: str | None = None,
        run_revision: int = 0,
        run_disposition: str | None = None,
        reply_to_message_id: str | None = None,
        persona_id: str | None = None,
        terminal_status: str = "completed",
        terminal_error: str | None = None,
    ) -> bool:
        host = cast(_OutcomePostprocessHostProtocol, self)
        return await host._chat_outcome_writer.persist_final_chat_outcome(
            turn_id=turn_id,
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
            terminal_status=terminal_status,
            terminal_error=terminal_error,
        )

    async def _commit_final_chat_outcome(
        self,
        *,
        turn_id: str | None,
        delivery_attempt_no: int,
        command_id: int,
        response_text: str,
        attachments: list[dict[str, Any]] | None = None,
        message_payload: dict[str, Any] | None = None,
        started_at_ms: int,
        completed_at_ms: int,
        context_usage: dict[str, Any] | None,
        execution_mode: str | None,
        ux_plan: dict[str, Any] | None,
        run_id: str | None = None,
        run_revision: int = 0,
        run_disposition: str | None = None,
        reply_to_message_id: str | None = None,
        persona_id: str | None = None,
        terminal_status: str = "completed",
        terminal_error: str | None = None,
    ) -> bool:
        """Commit one exact final delivery outcome."""

        host = cast(_OutcomePostprocessHostProtocol, self)
        return await host._chat_outcome_writer.commit_final_chat_outcome(
            turn_id=turn_id,
            delivery_attempt_no=delivery_attempt_no,
            command_id=command_id,
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
            terminal_status=terminal_status,
            terminal_error=terminal_error,
        )

    async def _persist_segmented_chat_outcome(
        self,
        *,
        turn_id: str | None,
        response_plan: AssistantResponsePlan,
        attachments: list[dict[str, Any]] | None = None,
        message_payload: dict[str, Any] | None = None,
        started_at_ms: int,
        completed_at_ms: int,
        context_usage: dict[str, Any] | None,
        execution_mode: str | None,
        ux_plan: dict[str, Any] | None,
        run_id: str | None = None,
        run_revision: int = 0,
        run_disposition: str | None = None,
        reply_to_message_id: str | None = None,
        persona_id: str | None = None,
        terminal_status: str = "completed",
        terminal_error: str | None = None,
    ) -> list[ChatMessageRecord]:
        host = cast(_OutcomePostprocessHostProtocol, self)
        return await host._chat_outcome_writer.persist_segmented_chat_outcome(
            turn_id=turn_id,
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
            terminal_status=terminal_status,
            terminal_error=terminal_error,
        )

    async def _commit_segmented_chat_outcome(
        self,
        *,
        turn_id: str | None,
        delivery_attempt_no: int,
        command_id: int,
        response_plan: AssistantResponsePlan,
        attachments: list[dict[str, Any]] | None = None,
        message_payload: dict[str, Any] | None = None,
        started_at_ms: int,
        completed_at_ms: int,
        context_usage: dict[str, Any] | None,
        execution_mode: str | None,
        ux_plan: dict[str, Any] | None,
        run_id: str | None = None,
        run_revision: int = 0,
        run_disposition: str | None = None,
        reply_to_message_id: str | None = None,
        persona_id: str | None = None,
        terminal_status: str = "completed",
        terminal_error: str | None = None,
    ) -> tuple[bool, list[ChatMessageRecord]]:
        """Commit one exact segmented delivery outcome."""

        host = cast(_OutcomePostprocessHostProtocol, self)
        return await host._chat_outcome_writer.commit_segmented_chat_outcome(
            turn_id=turn_id,
            delivery_attempt_no=delivery_attempt_no,
            command_id=command_id,
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
            terminal_status=terminal_status,
            terminal_error=terminal_error,
        )

    async def _get_chat_message(
        self,
        *,
        turn_id: str | None,
        message_kind: str,
    ) -> ChatMessageRecord | None:
        host = cast(_OutcomePostprocessHostProtocol, self)
        return await host._chat_outcome_writer.get_chat_message(
            turn_id=turn_id,
            message_kind=message_kind,
        )

    async def _get_final_chat_message(self, turn_id: str | None) -> ChatMessageRecord | None:
        return await self._get_chat_message(
            turn_id=turn_id,
            message_kind="assistant_final",
        )

    async def _get_notification_chat_message(
        self,
        *,
        turn_id: str | None,
        ux_plan: dict[str, Any] | None,
    ) -> ChatMessageRecord | None:
        host = cast(_OutcomePostprocessHostProtocol, self)
        return await host._chat_outcome_writer.get_notification_chat_message(
            turn_id=turn_id,
            ux_plan=ux_plan,
        )

    async def _get_turn_ux_chat_message(
        self,
        *,
        turn_id: str | None,
        ux_plan: dict[str, Any] | None,
    ) -> ChatMessageRecord | None:
        host = cast(_OutcomePostprocessHostProtocol, self)
        return await host._chat_outcome_writer.get_turn_ux_chat_message(
            turn_id=turn_id,
            ux_plan=ux_plan,
        )

    @staticmethod
    def _resolve_reaction_text(ux_plan: dict[str, Any] | None) -> str:
        return str(resolve_reaction_text(ux_plan) or "")
