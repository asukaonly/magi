"""Phase F: ConversationLog — typed event-sourced API over chat_messages.

Wraps the existing ChatStore message API so callers can append and read
typed :class:`ConversationEvent` objects instead of raw
:class:`ChatMessageRecord` rows. Redaction and revision propagate via
the existing SQL ``replaced_by_message_id`` / ``is_visible`` columns,
so the durable shape of the transcript is unchanged.
"""
from __future__ import annotations

import json
from typing import Any

from magi_plugin_sdk.conversation import ContentBlock, ConversationEvent

from ...core.logger import get_logger
from ..contracts import ChatMessageRecord
from .store import ChatRunConsumedEventsStore

logger = get_logger(__name__)


# ConversationEvent.event_type → (role, message_kind) for newly inserted rows.
# message_revised is handled at runtime by copying from the revised target.
_EVENT_TO_ROLE_KIND: dict[str, tuple[str, str]] = {
    "user_message":     ("user",      "user_text"),
    "agent_reply":      ("assistant", "assistant_text"),
    "tool_use_summary": ("assistant", "tool_summary"),
    "system_note":      ("system",    "system_note"),
    "message_redacted": ("system",    "redaction"),
    "delivery_receipt": ("system",    "delivery_receipt"),
}


class ConversationLog:
    """Append-only typed view over the chat_messages transcript."""

    def __init__(
        self,
        *,
        messages_repo: Any,
        consumed_events_store: ChatRunConsumedEventsStore,
    ) -> None:
        self._messages = messages_repo
        self._consumed = consumed_events_store

    # === writes ===

    async def append(self, event: ConversationEvent, *, session_id: str) -> None:
        """Persist one event. Side effects for redact/revise are applied."""
        role, message_kind = await self._resolve_role_kind(event)

        first_text: str | None = None
        if event.content:
            first_text = event.content[0].text or ""

        payload: dict[str, Any] = {
            "content_blocks": (
                [b.to_dict() for b in event.content] if event.content else []
            ),
            "event_type": event.event_type,
            "triggered_run_id": event.triggered_run_id,
            "source_channel": event.source_channel,
            "event_metadata": dict(event.metadata),
        }

        sequence_no = await self._messages.next_sequence_no(session_id=session_id)
        # The redaction event itself is not part of visible history; it
        # only exists so the audit log can show "X was redacted at T".
        is_visible = event.event_type != "message_redacted"

        record = ChatMessageRecord(
            message_id=event.event_id,
            session_id=session_id,
            # turn_id mirrors the triggering run by convention. Phase F
            # callers that need a stricter turn binding can override
            # via the source event's metadata in a follow-up.
            turn_id=event.triggered_run_id,
            user_id=event.actor,
            role=role,
            message_kind=message_kind,
            content_text=first_text,
            payload_json=json.dumps(payload, ensure_ascii=False),
            is_final=True,
            is_visible=is_visible,
            created_at_ms=int(event.timestamp_ms),
            sequence_no=sequence_no,
            replaces_message_id=event.revises,
            replaced_by_message_id=None,
            persona_id=None,
            reply_to_message_id=None,
            label=None,
        )
        await self._messages.append_message(record)

        # Side effects: a redaction event flips the target's is_visible to 0;
        # a revision event marks the previous head replaced by this event.
        if event.event_type == "message_redacted" and event.redacts:
            await self._messages.hide_message(
                session_id=session_id,
                message_id=event.redacts,
            )
        elif event.event_type == "message_revised" and event.revises:
            await self._messages.mark_message_replaced(
                message_id=event.revises,
                replaced_by_message_id=event.event_id,
            )

    async def record_consumed(
        self,
        *,
        session_id: str,
        run_id: str,
        revision: int,
        message_ids: list[str],
    ) -> None:
        await self._consumed.record_consumed(
            session_id=session_id,
            run_id=run_id,
            revision=revision,
            message_ids=message_ids,
        )

    # === reads ===

    async def materialize(
        self,
        *,
        session_id: str,
        exclude_redacted: bool = True,
    ) -> list[ContentBlock]:
        """Project the log into a flat list of ContentBlocks in order.

        Rules:
        - Skip rows whose ``message_kind == 'redaction'`` — the redaction
          marker itself never becomes a visible block.
        - Skip rows where ``is_visible = 0`` when ``exclude_redacted=True``.
        - Skip rows where ``replaced_by_message_id`` is set — only the
          head of each revision chain materializes.
        - For each surviving row, emit the blocks stored in
          ``payload_json["content_blocks"]`` (or fall back to a single
          text block synthesized from ``content_text``).
        """
        records = await self._messages.list_messages(session_id=session_id)
        out: list[ContentBlock] = []
        for rec in records:
            if rec.message_kind == "redaction":
                continue
            if exclude_redacted and not rec.is_visible:
                continue
            if rec.replaced_by_message_id is not None:
                continue
            out.extend(self._record_to_blocks(rec))
        return out

    async def find_dependents(
        self,
        *,
        session_id: str,
        message_id: str,
    ) -> list[tuple[str, int]]:
        return await self._consumed.find_runs_that_consumed(
            session_id=session_id,
            message_id=message_id,
        )

    # === internals ===

    async def _resolve_role_kind(
        self, event: ConversationEvent,
    ) -> tuple[str, str]:
        if event.event_type == "message_revised" and event.revises:
            target = await self._messages.get_message(event.revises)
            if target is not None:
                return target.role, target.message_kind
            # Fall back to a safe neutral default if the target is gone.
            return ("user", "user_text")
        return _EVENT_TO_ROLE_KIND.get(
            event.event_type, ("system", "system_note"),
        )

    @staticmethod
    def _record_to_blocks(rec: ChatMessageRecord) -> list[ContentBlock]:
        try:
            payload = json.loads(rec.payload_json or "{}")
        except (json.JSONDecodeError, TypeError):
            payload = {}
        raw_blocks = payload.get("content_blocks") if isinstance(payload, dict) else None
        if isinstance(raw_blocks, list) and raw_blocks:
            blocks: list[ContentBlock] = []
            for rb in raw_blocks:
                if not isinstance(rb, dict):
                    continue
                try:
                    blocks.append(ContentBlock.from_dict(rb))
                except Exception:  # noqa: BLE001
                    continue
            if blocks:
                return blocks
        # Fallback for pre-Phase-F rows that only have content_text set.
        if rec.content_text:
            return [ContentBlock(kind="text", text=rec.content_text)]
        return []


__all__ = ["ConversationLog"]
