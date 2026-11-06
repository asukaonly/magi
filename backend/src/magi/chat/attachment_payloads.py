"""Public chat payload shaping independent of database and asset transport."""

from __future__ import annotations

import json

from magi_plugin_sdk.storage_models.chat_attachments import (
    build_user_message_payload_json,
    public_attachment_payloads,
)
