"""Public chat payload shaping independent of database and asset transport."""

from __future__ import annotations

import json


def build_user_message_payload_json(
    attachment_payloads: list[dict[str, object]] | None,
    message_payload: dict[str, object] | None = None,
) -> str:
    payload = dict(message_payload or {})
    public_attachments = public_attachment_payloads(attachment_payloads)
    if public_attachments:
        payload["attachments"] = public_attachments
    if not payload:
        return "{}"
    return json.dumps(payload, ensure_ascii=False)


def public_attachment_payloads(
    attachment_payloads: list[dict[str, object]] | None,
) -> list[dict[str, object]]:
    if not attachment_payloads:
        return []
    allowed_keys = {
        "attachment_id",
        "kind",
        "original_name",
        "mime_type",
        "size_bytes",
        "parse_status",
        "derived_text_excerpt",
        "character_count",
        "truncated",
        "encoding",
        "page_count",
        "parse_error",
        # MCP resource attachments — references plus pre-read content.
        "server_id",
        "uri",
        "resolved_text",
        "resolved_error",
    }
    public_payloads: list[dict[str, object]] = []
    for item in attachment_payloads:
        if not isinstance(item, dict):
            continue
        public_payload = {
            key: value for key, value in item.items() if key in allowed_keys and value is not None
        }
        if public_payload:
            public_payloads.append(public_payload)
    return public_payloads
