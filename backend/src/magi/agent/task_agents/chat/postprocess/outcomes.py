"""Chat outcome persistence helpers for post-processing."""

from __future__ import annotations

import json
from typing import Any, Protocol, cast

from .....chat import ChatMessageRecord
from ...common import AssistantResponsePlan, IncomingFactKind
from ..contracts import ChatRuntimeContext
from .components import ChatOutcomeWriter


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
        orchestration_id: str | None,
        execution_mode: str | None,
        ux_plan: dict[str, Any] | None,
        run_id: str | None = None,
        run_revision: int = 0,
        run_disposition: str | None = None,
        reply_to_message_id: str | None = None,
        persona_id: str | None = None,
    ) -> None:
        host = cast(_OutcomePostprocessHostProtocol, self)
        await host._chat_outcome_writer.persist_final_chat_outcome(
            turn_id=turn_id,
            orchestration_id=orchestration_id,
            execution_mode=execution_mode,
            ux_plan=ux_plan,
            response_text=response_text,
            attachments=attachments,
            message_payload=message_payload,
            started_at_ms=started_at_ms,
            completed_at_ms=completed_at_ms,
            run_id=run_id,
            run_revision=run_revision,
            run_disposition=run_disposition,
            reply_to_message_id=reply_to_message_id,
            persona_id=persona_id,
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
        orchestration_id: str | None,
        execution_mode: str | None,
        ux_plan: dict[str, Any] | None,
        run_id: str | None = None,
        run_revision: int = 0,
        run_disposition: str | None = None,
        reply_to_message_id: str | None = None,
        persona_id: str | None = None,
    ) -> list[ChatMessageRecord]:
        host = cast(_OutcomePostprocessHostProtocol, self)
        return await host._chat_outcome_writer.persist_segmented_chat_outcome(
            turn_id=turn_id,
            orchestration_id=orchestration_id,
            execution_mode=execution_mode,
            ux_plan=ux_plan,
            response_plan=response_plan,
            attachments=attachments,
            message_payload=message_payload,
            started_at_ms=started_at_ms,
            completed_at_ms=completed_at_ms,
            run_id=run_id,
            run_revision=run_revision,
            run_disposition=run_disposition,
            reply_to_message_id=reply_to_message_id,
            persona_id=persona_id,
        )

    async def _resolve_result_reply_anchor_message_id(
        self,
        *,
        context: ChatRuntimeContext,
        turn_id: str | None,
    ) -> str | None:
        host = cast(_OutcomePostprocessHostProtocol, self)
        normalized_turn_id = str(turn_id or "").strip()
        if host._chat_store is None or not normalized_turn_id:
            return None
        if context.incoming_fact_kind not in {
            IncomingFactKind.WORKER_UPDATE,
            IncomingFactKind.EXPLORE_TASK_COMPLETED,
        }:
            return None
        turn = await host._chat_store.get_turn(normalized_turn_id)
        anchor_turn_id = str(
            (turn.response_anchor_turn_id if turn is not None else normalized_turn_id) or normalized_turn_id
        ).strip()
        if not anchor_turn_id:
            return None
        anchor_message = await host._chat_store.get_latest_message_for_turn(
            anchor_turn_id,
            message_kind="user_text",
        )
        if anchor_message is None:
            return None
        message_id = str(getattr(anchor_message, "message_id", "") or "").strip()
        return message_id or None

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
        return str(ChatOutcomeWriter.resolve_reaction_text(ux_plan) or "")

    @staticmethod
    def _serialize_selected_tools_payload(
        *,
        router_tools: list[str],
        selected_tools: list[str],
        task_hint: Any,
        recommended_tools: list[dict[str, Any]],
    ) -> str:
        return json.dumps(
            {
                "router_tools": list(router_tools or []),
                "selected_tools": list(selected_tools or []),
                "task_hint": dict(task_hint or {}),
                "recommended_tools": list(recommended_tools or []),
            },
            ensure_ascii=False,
        )

    async def _project_final_chat_message(
        self,
        *,
        context: ChatRuntimeContext,
        final_message: ChatMessageRecord | None,
    ) -> None:
        host = cast(_OutcomePostprocessHostProtocol, self)
        await host._chat_outcome_writer.project_final_chat_message(
            user_id=context.user_id,
            session_id=context.session_id,
            final_message=final_message,
        )

    async def _project_canonical_assistant_response(
        self,
        *,
        context: ChatRuntimeContext,
        turn_id: str | None,
        message_id: str | None,
        response_text: str,
        created_at_ms: int,
    ) -> None:
        host = cast(_OutcomePostprocessHostProtocol, self)
        await host._chat_outcome_writer.project_canonical_assistant_response(
            user_id=context.user_id,
            session_id=context.session_id,
            turn_id=turn_id,
            message_id=message_id,
            content=response_text,
            created_at_ms=created_at_ms,
        )
