"""Reply-context projection for chat task-agent turns."""

from __future__ import annotations

import json
from typing import Any

from ...asset_refs import normalize_asset_ref_list, normalize_asset_ref_payload
from ....chat import ChatMessageRecord, ChatStore
from .contracts import ChatReplyContext


class ChatReplyContextMixin:
    """Resolve and summarize reply targets for :class:`ChatTaskAgent`."""

    _chat_store: ChatStore | None

    async def _resolve_reply_context(self, latest_payload: object) -> ChatReplyContext | None:
        if self._chat_store is None:
            return None
        session_id = str(getattr(latest_payload, "session_id", "") or "").strip()
        current_turn_id = str(getattr(latest_payload, "turn_id", "") or "").strip()
        reply_to_message_id = str(getattr(latest_payload, "reply_to_message_id", "") or "").strip()
        current_user_message = None
        if current_turn_id:
            current_user_message = await self._chat_store.get_latest_message_for_turn(
                current_turn_id,
                message_kind="user_text",
            )
            if current_user_message is not None:
                session_id = str(current_user_message.session_id or session_id or "").strip()
                reply_to_message_id = str(current_user_message.reply_to_message_id or reply_to_message_id or "").strip()
        reply_target = None
        is_explicit_reply = False
        if reply_to_message_id:
            reply_target = await self._chat_store.get_message(reply_to_message_id)
            is_explicit_reply = reply_target is not None
        if reply_target is None and session_id:
            fallback_target = await self._chat_store.get_latest_message_for_session(
                session_id,
                role="assistant",
                message_kind="assistant_final",
                exclude_turn_id=current_turn_id or None,
            )
            if self._has_reusable_recent_reply_payload(fallback_target):
                reply_target = fallback_target
        if reply_target is None:
            return None
        return self._build_reply_context(
            current_turn_id=current_turn_id,
            reply_target=reply_target,
            is_explicit_reply=is_explicit_reply,
        )

    @staticmethod
    def _build_reply_context(
        *,
        current_turn_id: str,
        reply_target: ChatMessageRecord,
        is_explicit_reply: bool,
    ) -> ChatReplyContext:
        content_excerpt = str(reply_target.content_text or "").strip()
        if len(content_excerpt) > 280:
            content_excerpt = f"{content_excerpt[:277]}..."
        return ChatReplyContext(
            message_id=reply_target.message_id,
            role=reply_target.role,
            content_excerpt=content_excerpt,
            is_explicit_reply=is_explicit_reply,
            references_prior_turn=bool(
                current_turn_id
                and reply_target.turn_id
                and str(reply_target.turn_id).strip() != current_turn_id
            ),
            structured_payload=ChatReplyContextMixin._summarize_reply_payload(reply_target.payload_json),
        )

    @staticmethod
    def _has_reusable_recent_reply_payload(reply_target: ChatMessageRecord | None) -> bool:
        if reply_target is None:
            return False
        summary = ChatReplyContextMixin._summarize_reply_payload(reply_target.payload_json)
        if not isinstance(summary, dict):
            return False
        return bool(summary.get("asset_refs"))

    @staticmethod
    def _summarize_reply_payload(raw_payload_json: str | None) -> dict[str, Any] | None:
        if not raw_payload_json:
            return None
        try:
            payload = json.loads(raw_payload_json)
        except (TypeError, ValueError, json.JSONDecodeError):
            return None
        if not isinstance(payload, dict):
            return None
        payload = normalize_asset_ref_payload(payload)

        summary: dict[str, Any] = {}
        attachments = payload.get("attachments")
        if isinstance(attachments, list):
            compact_attachments: list[dict[str, Any]] = []
            for item in attachments[:6]:
                if not isinstance(item, dict):
                    continue
                compact_item: dict[str, Any] = {}
                for key in (
                    "attachment_id",
                    "kind",
                    "original_name",
                    "mime_type",
                    "size_bytes",
                    "parse_status",
                    "page_count",
                    "character_count",
                ):
                    value = item.get(key)
                    if value is not None:
                        compact_item[key] = value
                if compact_item:
                    compact_attachments.append(compact_item)
            if compact_attachments:
                summary["attachments"] = compact_attachments

        asset_refs = payload.get("asset_refs")
        if isinstance(asset_refs, list):
            compact_refs: list[dict[str, Any]] = []
            for item in normalize_asset_ref_list(asset_refs)[:6]:
                compact_item: dict[str, Any] = {}
                for field_name in (
                    "asset_ref_id",
                    "attachment_id",
                    "event_id",
                    "source_type",
                    "source_item_id",
                    "original_name",
                    "display_name",
                    "capture_time",
                    "captured_at",
                    "occurred_at",
                    "kind",
                    "resolver_tool",
                    "resolution_state",
                ):
                    value = item.get(field_name)
                    if value is not None:
                        compact_item[field_name] = value
                attributes = item.get("attributes")
                if isinstance(attributes, dict) and attributes:
                    compact_item["attributes"] = dict(attributes)
                if compact_item:
                    compact_refs.append(compact_item)
            if compact_refs:
                summary["asset_refs"] = compact_refs

        return summary or None