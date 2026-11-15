"""Provider-neutral validation helpers for tool-call message groups."""

from __future__ import annotations

from magi_plugin_sdk.storage_models.model_message_protocol import (
    protocol_complete_message_indexes,
    repair_model_message_protocol,
    _tool_call_ids as _tool_call_ids,
)

__all__ = [
    "protocol_complete_message_indexes",
    "repair_model_message_protocol",
]
