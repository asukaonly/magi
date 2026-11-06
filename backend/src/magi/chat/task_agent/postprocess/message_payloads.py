"""Assistant chat message payload helpers."""
from __future__ import annotations

import json
from typing import Any

from magi.agent.task_agents.common import AssistantResponseSegment
from magi.chat.attachment_payloads import public_attachment_payloads


from magi.core.chat_expression import is_single_emoji


def build_message_payload_json(
    attachments: list[dict[str, Any]] | None,
    message_payload: dict[str, Any] | None,
) -> str:
    payload = dict(message_payload or {})
    payload.pop("attachments", None)
    if attachments:
        payload["attachments"] = public_attachment_payloads(list(attachments))
    if not payload:
        return "{}"
    return json.dumps(payload, ensure_ascii=False)


def build_segment_payload_json(
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
        payload["attachments"] = public_attachment_payloads(list(attachments))
    return json.dumps(payload, ensure_ascii=False)


def resolve_reaction_text(ux_plan: dict[str, Any] | None) -> str:
    emoji = str((ux_plan or {}).get("reaction_emoji") or "").strip()
    return emoji if is_single_emoji(emoji) else ""


__all__ = [
    "build_message_payload_json",
    "build_segment_payload_json",
    "resolve_reaction_text",
]
