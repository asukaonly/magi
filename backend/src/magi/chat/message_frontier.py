"""Shared SQL fragments for inclusive chat-message frontier reads."""

from __future__ import annotations

from magi_plugin_sdk.storage_models.chat_frontier import (
    MESSAGE_FRONTIER_SELECT_SQL,
    MESSAGE_ORDER_SQL,
    build_inclusive_frontier_filter,
)

__all__ = [
    "MESSAGE_FRONTIER_SELECT_SQL",
    "MESSAGE_ORDER_SQL",
    "build_inclusive_frontier_filter",
]
