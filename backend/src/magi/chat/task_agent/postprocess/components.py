"""Focused collaborators for chat post-processing side effects."""
from __future__ import annotations

import json
import uuid
from typing import Any, Callable

from magi.chat import ChatMessageRecord, ChatProjector, ChatStore, ChatTurnRecord
from magi.agent.task_agents.common import AssistantResponsePlan, AssistantResponseSegment
from .notifications import ChatRuntimeNotifier

REACTION_EMOJI_BY_STYLE = {
    "acknowledge": "👌",
}


class ChatOutcomeWriter:
    """Persists chat turn/message state and projects canonical outputs."""

    def __init__(
        self,
        *,
        chat_store: ChatStore | None,
        chat_projector: ChatProjector | None,
        trace_id_factory: Callable[[str], str],
    ) -> None:
        self._chat_store = chat_store
        self._chat_projector = chat_projector
        self._trace_id_factory = trace_id_factory

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
        if self._chat_store is None or not ux_plan:
            return
        existing_turn = await self._chat_store.get_turn(turn_id)
        if existing_turn is None:
            return
        response_mode = str(ux_plan.get("assistant_surface_mode") or existing_turn.response_mode or "final_only")
        await self._chat_store.upsert_turn(
            ChatTurnRecord(
                turn_id=existing_turn.turn_id,
                session_id=existing_turn.session_id,
                user_id=existing_turn.user_id,
                trace_id=existing_turn.trace_id or self._trace_id_factory(turn_id),
                orchestration_id=existing_turn.orchestration_id,
                status="running",
                response_mode=response_mode,
                execution_mode=execution_mode or existing_turn.execution_mode,
                ux_plan_json=json.dumps(ux_plan, ensure_ascii=False),
                created_at_ms=existing_turn.created_at_ms,
                updated_at_ms=updated_at_ms,
                completed_at_ms=None,
                error_text=existing_turn.error_text,
                run_id=run_id or existing_turn.run_id,
                run_revision=run_revision if run_id is not None else existing_turn.run_revision,
                run_disposition=run_disposition or existing_turn.run_disposition,
                response_anchor_turn_id=existing_turn.response_anchor_turn_id,
                superseded_by_turn_id=existing_turn.superseded_by_turn_id,
                supersession_reason=existing_turn.supersession_reason,
            )
        )
        if response_mode == "interim_then_final":
            await self._append_interim_message(
                turn=existing_turn,
                turn_id=turn_id,
                ux_plan=ux_plan,
                updated_at_ms=updated_at_ms,
            )
            return
        if response_mode == "reaction_only":
            await self._apply_reaction_label(
                turn=existing_turn,
                turn_id=turn_id,
                ux_plan=ux_plan,
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
        normalized_turn_id = str(turn_id or "").strip()
        if self._chat_store is None or not normalized_turn_id:
            return
        existing_turn = await self._chat_store.get_turn(normalized_turn_id)
        if existing_turn is None:
            return
        resolved_persona_id = await self._resolve_turn_persona_id(
            turn_id=normalized_turn_id,
            fallback_persona_id=persona_id,
        )
        normalized_ux_plan = ux_plan if isinstance(ux_plan, dict) else {}
        response_mode = str(
            normalized_ux_plan.get("assistant_surface_mode") or existing_turn.response_mode or "final_only"
        )
        await self._chat_store.upsert_turn(
            ChatTurnRecord(
                turn_id=existing_turn.turn_id,
                session_id=existing_turn.session_id,
                user_id=existing_turn.user_id,
                trace_id=existing_turn.trace_id or self._trace_id_factory(normalized_turn_id),
                orchestration_id=orchestration_id or existing_turn.orchestration_id,
                status="completed",
                response_mode=response_mode,
                execution_mode=execution_mode or existing_turn.execution_mode,
                ux_plan_json=(
                    json.dumps(normalized_ux_plan, ensure_ascii=False)
                    if normalized_ux_plan
                    else existing_turn.ux_plan_json
                ),
                created_at_ms=existing_turn.created_at_ms or started_at_ms,
                updated_at_ms=completed_at_ms,
                completed_at_ms=completed_at_ms,
                error_text=existing_turn.error_text,
                run_id=run_id or existing_turn.run_id,
                run_revision=run_revision if run_id is not None else existing_turn.run_revision,
                run_disposition=run_disposition or existing_turn.run_disposition,
                response_anchor_turn_id=existing_turn.response_anchor_turn_id,
                superseded_by_turn_id=existing_turn.superseded_by_turn_id,
                supersession_reason=existing_turn.supersession_reason,
            )
        )
        if response_mode in {"reaction_only", "none"}:
            return
        existing_final = await self._chat_store.get_latest_message_for_turn(
            normalized_turn_id,
            message_kind="assistant_final",
        )
        if existing_final is not None:
            return
        interim_message = await self._chat_store.get_latest_message_for_turn(
            normalized_turn_id,
            message_kind="assistant_interim",
        )
        final_message = ChatMessageRecord(
            message_id=f"msg_{uuid.uuid4().hex[:16]}",
            session_id=existing_turn.session_id,
            turn_id=normalized_turn_id,
            user_id=existing_turn.user_id,
            role="assistant",
            message_kind="assistant_final",
            content_text=response_text,
            payload_json=self._build_message_payload_json(attachments, message_payload),
            is_final=True,
            is_visible=True,
            created_at_ms=completed_at_ms,
            sequence_no=await self._chat_store.next_sequence_no(session_id=existing_turn.session_id),
            replaces_message_id=interim_message.message_id if interim_message is not None else None,
            replaced_by_message_id=None,
            persona_id=resolved_persona_id,
            reply_to_message_id=str(reply_to_message_id or "").strip() or None,
        )
        await self._chat_store.append_message(final_message, attachment_payloads=attachments)
        await self._chat_store.bump_history_version(existing_turn.session_id)
        if interim_message is not None:
            await self._chat_store.mark_message_replaced(
                message_id=interim_message.message_id,
                replaced_by_message_id=final_message.message_id,
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
        normalized_turn_id = str(turn_id or "").strip()
        if self._chat_store is None or not normalized_turn_id:
            return []
        existing_turn = await self._chat_store.get_turn(normalized_turn_id)
        if existing_turn is None:
            return []
        resolved_persona_id = await self._resolve_turn_persona_id(
            turn_id=normalized_turn_id,
            fallback_persona_id=persona_id,
        )
        normalized_ux_plan = ux_plan if isinstance(ux_plan, dict) else {}
        response_mode = str(
            normalized_ux_plan.get("assistant_surface_mode") or existing_turn.response_mode or "final_only"
        )
        await self._chat_store.upsert_turn(
            ChatTurnRecord(
                turn_id=existing_turn.turn_id,
                session_id=existing_turn.session_id,
                user_id=existing_turn.user_id,
                trace_id=existing_turn.trace_id or self._trace_id_factory(normalized_turn_id),
                orchestration_id=orchestration_id or existing_turn.orchestration_id,
                status="completed",
                response_mode=response_mode,
                execution_mode=execution_mode or existing_turn.execution_mode,
                ux_plan_json=(
                    json.dumps(normalized_ux_plan, ensure_ascii=False)
                    if normalized_ux_plan
                    else existing_turn.ux_plan_json
                ),
                created_at_ms=existing_turn.created_at_ms or started_at_ms,
                updated_at_ms=completed_at_ms,
                completed_at_ms=completed_at_ms,
                error_text=existing_turn.error_text,
                run_id=run_id or existing_turn.run_id,
                run_revision=run_revision if run_id is not None else existing_turn.run_revision,
                run_disposition=run_disposition or existing_turn.run_disposition,
                response_anchor_turn_id=existing_turn.response_anchor_turn_id,
                superseded_by_turn_id=existing_turn.superseded_by_turn_id,
                supersession_reason=existing_turn.supersession_reason,
            )
        )
        if response_mode in {"reaction_only", "none"}:
            return []
        existing_segments = [
            message
            for message in await self._chat_store.list_messages(session_id=existing_turn.session_id)
            if message.turn_id == normalized_turn_id and message.message_kind == "assistant_rhythm_segment"
        ]
        if existing_segments:
            return existing_segments

        sequence_no = await self._chat_store.next_sequence_no(session_id=existing_turn.session_id)
        total = len(response_plan.segments)
        records: list[ChatMessageRecord] = []
        cumulative_delay_ms = 0
        for index, segment in enumerate(response_plan.segments):
            if index > 0:
                cumulative_delay_ms += max(0, int(segment.delay_ms or 0))
            segment_attachments = attachments if index == total - 1 else None
            segment_payload = self._build_segment_payload_json(
                base_payload=message_payload,
                segment=segment,
                total_segments=total,
                attachments=segment_attachments,
            )
            segment_reply_to_message_id = (
                str(reply_to_message_id or "").strip() or None
                if index == 0
                else None
            )
            record = ChatMessageRecord(
                message_id=f"msg_{uuid.uuid4().hex[:16]}",
                session_id=existing_turn.session_id,
                turn_id=normalized_turn_id,
                user_id=existing_turn.user_id,
                role="assistant",
                message_kind="assistant_rhythm_segment",
                content_text=segment.content,
                payload_json=segment_payload,
                is_final=True,
                is_visible=True,
                created_at_ms=completed_at_ms + cumulative_delay_ms,
                sequence_no=sequence_no + index,
                replaces_message_id=None,
                replaced_by_message_id=None,
                persona_id=resolved_persona_id,
                reply_to_message_id=segment_reply_to_message_id,
            )
            await self._chat_store.append_message(
                record,
                attachment_payloads=segment_attachments,
            )
            records.append(record)
        await self._chat_store.bump_history_version(existing_turn.session_id)
        return records

    @staticmethod
    def _build_message_payload_json(
        attachments: list[dict[str, Any]] | None,
        message_payload: dict[str, Any] | None,
    ) -> str:
        payload = dict(message_payload or {})
        payload.pop("attachments", None)
        if attachments:
            payload["attachments"] = ChatStore._public_attachment_payloads(list(attachments))
        if not payload:
            return "{}"
        return json.dumps(payload, ensure_ascii=False)

    async def _resolve_turn_persona_id(
        self,
        *,
        turn_id: str,
        fallback_persona_id: str | None,
    ) -> str | None:
        normalized_fallback = str(fallback_persona_id or "").strip() or None
        if self._chat_store is None:
            return normalized_fallback
        user_message = await self._chat_store.get_latest_message_for_turn(
            turn_id,
            message_kind="user_text",
        )
        if user_message is None:
            return normalized_fallback
        return str(user_message.persona_id or "").strip() or normalized_fallback

    @staticmethod
    def _build_segment_payload_json(
        *,
        base_payload: dict[str, Any] | None,
        segment: AssistantResponseSegment,
        total_segments: int,
        attachments: list[dict[str, Any]] | None = None,
    ) -> str:
        payload = dict(base_payload or {})
        payload.pop("attachments", None)
        payload["rhythm"] = {
            "segment_index": segment.segment_index,
            "segment_count": total_segments,
            "intent": segment.intent,
            "delay_ms": segment.delay_ms,
            "source_unit_ids": list(segment.source_unit_ids),
        }
        if attachments:
            payload["attachments"] = ChatStore._public_attachment_payloads(list(attachments))
        return json.dumps(payload, ensure_ascii=False)

    async def persist_turn_supersession(
        self,
        *,
        turn_id: str,
        anchor_turn_id: str,
        reason: str,
        updated_at_ms: int,
    ) -> None:
        """Mark one turn as absorbed or interrupted by a newer turn."""
        if self._chat_store is None:
            return
        existing_turn = await self._chat_store.get_turn(turn_id)
        if existing_turn is None:
            return
        status = "merged" if reason == "augment" else "interrupted"
        await self._chat_store.upsert_turn(
            ChatTurnRecord(
                turn_id=existing_turn.turn_id,
                session_id=existing_turn.session_id,
                user_id=existing_turn.user_id,
                trace_id=existing_turn.trace_id or self._trace_id_factory(turn_id),
                orchestration_id=existing_turn.orchestration_id,
                status=status,
                response_mode=existing_turn.response_mode,
                execution_mode=existing_turn.execution_mode,
                ux_plan_json=existing_turn.ux_plan_json,
                created_at_ms=existing_turn.created_at_ms,
                updated_at_ms=updated_at_ms,
                completed_at_ms=updated_at_ms,
                error_text=existing_turn.error_text,
                run_id=existing_turn.run_id,
                run_revision=existing_turn.run_revision,
                run_disposition=existing_turn.run_disposition,
                response_anchor_turn_id=anchor_turn_id,
                superseded_by_turn_id=anchor_turn_id,
                supersession_reason=status,
            )
        )

    async def get_notification_chat_message(
        self,
        *,
        turn_id: str | None,
        ux_plan: dict[str, Any] | None,
    ) -> ChatMessageRecord | None:
        response_mode = str((ux_plan or {}).get("assistant_surface_mode") or "").strip()
        if response_mode == "reaction_only":
            return None
        return await self.get_chat_message(turn_id=turn_id, message_kind="assistant_final")

    async def get_turn_ux_chat_message(
        self,
        *,
        turn_id: str | None,
        ux_plan: dict[str, Any] | None,
    ) -> ChatMessageRecord | None:
        response_mode = str((ux_plan or {}).get("assistant_surface_mode") or "").strip()
        if response_mode == "reaction_only":
            return None
        if response_mode == "interim_then_final":
            return await self.get_chat_message(turn_id=turn_id, message_kind="assistant_interim")
        return None

    async def project_final_chat_message(
        self,
        *,
        user_id: str,
        session_id: str,
        final_message: ChatMessageRecord | None,
    ) -> None:
        if self._chat_projector is None or final_message is None or not str(final_message.content_text or "").strip():
            return
        await self._chat_projector.project_assistant_message(
            message_id=final_message.message_id,
            user_id=user_id,
            session_id=session_id,
            turn_id=str(final_message.turn_id or ""),
            content=str(final_message.content_text or ""),
            created_at_ms=final_message.created_at_ms,
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
        if self._chat_projector is None or not str(content or "").strip():
            return
        normalized_turn_id = str(turn_id or "").strip()
        normalized_message_id = str(message_id or "").strip()
        if not normalized_turn_id or not normalized_message_id:
            return
        await self._chat_projector.project_assistant_message(
            message_id=normalized_message_id,
            user_id=user_id,
            session_id=session_id,
            turn_id=normalized_turn_id,
            content=str(content or ""),
            created_at_ms=created_at_ms,
        )

    async def get_chat_message(
        self,
        *,
        turn_id: str | None,
        message_kind: str,
    ) -> ChatMessageRecord | None:
        normalized_turn_id = str(turn_id or "").strip()
        if self._chat_store is None or not normalized_turn_id:
            return None
        return await self._chat_store.get_latest_message_for_turn(
            normalized_turn_id,
            message_kind=message_kind,
        )

    async def _append_interim_message(
        self,
        *,
        turn: ChatTurnRecord,
        turn_id: str,
        ux_plan: dict[str, Any],
        updated_at_ms: int,
    ) -> None:
        interim_text = str(ux_plan.get("interim_text") or "").strip()
        if not interim_text or self._chat_store is None:
            return
        existing_interim = await self._chat_store.get_latest_message_for_turn(
            turn_id,
            message_kind="assistant_interim",
        )
        if existing_interim is not None:
            return
        await self._chat_store.append_message(
            ChatMessageRecord(
                message_id=f"msg_{uuid.uuid4().hex[:16]}",
                session_id=turn.session_id,
                turn_id=turn_id,
                user_id=turn.user_id,
                role="assistant",
                message_kind="assistant_interim",
                content_text=interim_text,
                payload_json="{}",
                is_final=False,
                is_visible=True,
                created_at_ms=updated_at_ms,
                sequence_no=await self._chat_store.next_sequence_no(session_id=turn.session_id),
                replaces_message_id=None,
                replaced_by_message_id=None,
                persona_id=await self._resolve_turn_persona_id(
                    turn_id=turn_id,
                    fallback_persona_id=None,
                ),
            )
        )

    async def _apply_reaction_label(
        self,
        *,
        turn: ChatTurnRecord,
        turn_id: str,
        ux_plan: dict[str, Any],
        updated_at_ms: int,
    ) -> None:
        reaction_text = self.resolve_reaction_text(ux_plan)
        if not reaction_text or self._chat_store is None:
            return
        target_message = await self._chat_store.get_latest_message_for_turn(
            turn_id,
            message_kind="user_text",
        )
        if target_message is None:
            return
        next_label = {
            "kind": "emoji",
            "text": reaction_text,
            "applied_by": "assistant",
            "source": "reaction_only",
            "created_at_ms": int(target_message.created_at_ms or updated_at_ms),
        }
        existing_label = target_message.label.to_dict() if target_message.label is not None else None
        if existing_label == next_label:
            return
        await self._chat_store.update_message_label(
            session_id=turn.session_id,
            message_id=target_message.message_id,
            label=next_label,
        )

    @staticmethod
    def resolve_reaction_text(ux_plan: dict[str, Any] | None) -> str:
        style = str((ux_plan or {}).get("reaction_style") or "").strip()
        return REACTION_EMOJI_BY_STYLE.get(style, "")


__all__ = ["ChatOutcomeWriter", "ChatRuntimeNotifier"]
