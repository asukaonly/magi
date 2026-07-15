"""Resolve turn-local recall feedback against durable chat history."""

from __future__ import annotations

import json
from typing import Any

from magi.agent.task_agents.handlers.contracts import RecallFeedbackContext
from magi.chat import ChatStore
from magi.events.recall_feedback import RecallFeedbackKind, RecallFeedbackRequest


class ChatRecallFeedbackContextMixin:
    """Hydrate recall-feedback requests from the targeted assistant message."""

    _chat_store: ChatStore | None

    async def _resolve_recall_feedback_context(
        self,
        latest_payload: object,
    ) -> RecallFeedbackContext | None:
        request = RecallFeedbackRequest.from_value(getattr(latest_payload, "recall_feedback", None))
        if request is None:
            return None
        if self._chat_store is None:
            return self._invalid_context(request, "chat_store_unavailable")

        target = await self._chat_store.get_message(request.target_message_id)
        session_id = str(getattr(latest_payload, "session_id", "") or "").strip()
        user_id = str(getattr(latest_payload, "user_id", "") or "").strip()
        if (
            target is None
            or target.role != "assistant"
            or target.session_id != session_id
            or target.user_id != user_id
        ):
            return self._invalid_context(request, "target_message_unavailable")

        target_payload = self._parse_payload(target.payload_json)
        original_question = await self._resolve_original_question(
            target=target,
            target_payload=target_payload,
            session_id=session_id,
            user_id=user_id,
        )
        if not original_question:
            return self._invalid_context(request, "original_question_unavailable")

        recalled_memories = [
            dict(item)
            for item in target_payload.get("recalled_memories", [])
            if isinstance(item, dict)
        ]
        if not recalled_memories:
            return self._invalid_context(
                request,
                "evidence_snapshot_unavailable",
                original_question=original_question,
                previous_answer_excerpt=str(target.content_text or "").strip()[:800],
            )

        if request.kind == RecallFeedbackKind.ITEM_IRRELEVANT:
            matched = any(
                str(item.get("feedback_ref") or "").strip() == request.finding_ref
                for item in recalled_memories
            )
            if not matched:
                return self._invalid_context(
                    request,
                    "finding_unavailable",
                    original_question=original_question,
                    previous_answer_excerpt=str(target.content_text or "").strip()[:800],
                )
            recalled_memories = [
                item
                for item in recalled_memories
                if str(item.get("feedback_ref") or "").strip() != request.finding_ref
            ]

        raw_summary = target_payload.get("recalled_memory_summary")
        summary = dict(raw_summary) if isinstance(raw_summary, dict) else None
        if request.kind == RecallFeedbackKind.ITEM_IRRELEVANT:
            summary = None

        return RecallFeedbackContext(
            kind=request.kind.value,
            target_message_id=request.target_message_id,
            original_question=original_question,
            previous_answer_excerpt=str(target.content_text or "").strip()[:800],
            recalled_memories=recalled_memories,
            recalled_memory_summary=summary,
            finding_ref=request.finding_ref,
        )

    async def _resolve_original_question(
        self,
        *,
        target: Any,
        target_payload: dict[str, Any],
        session_id: str,
        user_id: str,
    ) -> str:
        current = target
        current_payload = target_payload
        visited = {str(target.message_id)}
        for _ in range(8):
            parent_id = str(current_payload.get("corrects_message_id") or "").strip()
            if not parent_id:
                break
            if parent_id in visited or self._chat_store is None:
                return ""
            visited.add(parent_id)
            parent = await self._chat_store.get_message(parent_id)
            if (
                parent is None
                or parent.role != "assistant"
                or parent.session_id != session_id
                or parent.user_id != user_id
            ):
                return ""
            current = parent
            current_payload = self._parse_payload(parent.payload_json)
        else:
            if str(current_payload.get("corrects_message_id") or "").strip():
                return ""

        if not current.turn_id or self._chat_store is None:
            return ""
        original_user_message = await self._chat_store.get_latest_message_for_turn(
            current.turn_id,
            message_kind="user_text",
        )
        return str(getattr(original_user_message, "content_text", "") or "").strip()

    @staticmethod
    def _parse_payload(raw_payload: str | None) -> dict[str, Any]:
        if not raw_payload:
            return {}
        try:
            parsed = json.loads(raw_payload)
        except (TypeError, ValueError, json.JSONDecodeError):
            return {}
        return parsed if isinstance(parsed, dict) else {}

    @staticmethod
    def _invalid_context(
        request: RecallFeedbackRequest,
        error_code: str,
        *,
        original_question: str = "",
        previous_answer_excerpt: str = "",
    ) -> RecallFeedbackContext:
        return RecallFeedbackContext(
            kind=request.kind.value,
            target_message_id=request.target_message_id,
            original_question=original_question,
            previous_answer_excerpt=previous_answer_excerpt,
            finding_ref=request.finding_ref,
            valid=False,
            error_code=error_code,
        )


__all__ = ["ChatRecallFeedbackContextMixin"]
