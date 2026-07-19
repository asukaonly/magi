"""Assistant chat message persistence for post-processing."""
from __future__ import annotations

import uuid
from typing import Any

from magi.agent.task_agents.common import AssistantResponsePlan
from magi.chat import ChatMessageRecord, ChatStore, ChatTurnRecord
from magi.chat.rhythm_completion import MAX_RHYTHM_SEGMENT_COUNT

from .message_payloads import (
    build_message_payload_json,
    build_segment_payload_json,
    resolve_reaction_text,
)


class ChatAssistantMessageWriter:
    """Persist assistant transcript messages and labels."""

    def __init__(self, *, chat_store: ChatStore | None) -> None:
        self._chat_store = chat_store

    async def build_final_message(
        self,
        *,
        turn: ChatTurnRecord,
        turn_id: str,
        response_text: str,
        attachments: list[dict[str, Any]] | None,
        message_payload: dict[str, Any] | None,
        completed_at_ms: int,
        reply_to_message_id: str | None,
        persona_id: str | None,
    ) -> ChatMessageRecord:
        """Build a final record without crossing the persistence boundary."""

        resolved_persona_id = await self.resolve_turn_persona_id(
            turn_id=turn_id,
            fallback_persona_id=persona_id,
        )
        interim_message = (
            await self._chat_store.get_latest_message_for_turn(
                turn_id,
                message_kind="assistant_interim",
            )
            if self._chat_store is not None
            else None
        )
        return ChatMessageRecord(
            message_id=f"msg_{uuid.uuid4().hex[:16]}",
            session_id=turn.session_id,
            turn_id=turn_id,
            user_id=turn.user_id,
            role="assistant",
            message_kind="assistant_final",
            content_text=response_text,
            payload_json=build_message_payload_json(attachments, message_payload),
            is_final=True,
            is_visible=True,
            created_at_ms=completed_at_ms,
            sequence_no=0,
            replaces_message_id=interim_message.message_id if interim_message is not None else None,
            replaced_by_message_id=None,
            persona_id=resolved_persona_id,
            reply_to_message_id=str(reply_to_message_id or "").strip() or None,
        )

    async def build_rhythm_segments(
        self,
        *,
        turn: ChatTurnRecord,
        turn_id: str,
        response_plan: AssistantResponsePlan,
        attachments: list[dict[str, Any]] | None,
        message_payload: dict[str, Any] | None,
        completed_at_ms: int,
        reply_to_message_id: str | None,
        persona_id: str | None,
    ) -> list[ChatMessageRecord]:
        """Build rhythm records without crossing the persistence boundary."""

        total = len(response_plan.segments)
        if not 1 <= total <= MAX_RHYTHM_SEGMENT_COUNT:
            raise ValueError("Conversation rhythm segment count is out of range")
        if any(
            not isinstance(segment.segment_index, int)
            or isinstance(segment.segment_index, bool)
            or segment.segment_index != index
            for index, segment in enumerate(response_plan.segments)
        ):
            raise ValueError("Conversation rhythm segment indexes are invalid")

        resolved_persona_id = await self.resolve_turn_persona_id(
            turn_id=turn_id,
            fallback_persona_id=persona_id,
        )
        records: list[ChatMessageRecord] = []
        cumulative_delay_ms = 0
        for index, segment in enumerate(response_plan.segments):
            if index > 0:
                cumulative_delay_ms += max(0, int(segment.delay_ms or 0))
            segment_attachments = attachments if index == total - 1 else None
            segment_message_payload = dict(message_payload or {})
            if index < total - 1:
                segment_message_payload.pop("recalled_memories", None)
                segment_message_payload.pop("recalled_memory_summary", None)
                segment_message_payload.pop("code_agent_delegations", None)
            segment_payload = build_segment_payload_json(
                base_payload=segment_message_payload,
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
                session_id=turn.session_id,
                turn_id=turn_id,
                user_id=turn.user_id,
                role="assistant",
                message_kind="assistant_rhythm_segment",
                content_text=segment.content,
                payload_json=segment_payload,
                is_final=True,
                is_visible=True,
                created_at_ms=completed_at_ms + cumulative_delay_ms,
                sequence_no=index,
                replaces_message_id=None,
                replaced_by_message_id=None,
                persona_id=resolved_persona_id,
                reply_to_message_id=segment_reply_to_message_id,
            )
            records.append(record)
        return records

    async def append_interim_message(
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
                persona_id=await self.resolve_turn_persona_id(
                    turn_id=turn_id,
                    fallback_persona_id=None,
                ),
            )
        )

    async def apply_reaction_label(
        self,
        *,
        turn: ChatTurnRecord,
        turn_id: str,
        ux_plan: dict[str, Any],
        updated_at_ms: int,
    ) -> None:
        reaction_text = resolve_reaction_text(ux_plan)
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

    async def resolve_turn_persona_id(
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


__all__ = ["ChatAssistantMessageWriter"]
