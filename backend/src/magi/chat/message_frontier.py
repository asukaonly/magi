"""Shared SQL fragments for inclusive chat-message frontier reads."""

from __future__ import annotations

from typing import Any


MESSAGE_FRONTIER_SELECT_SQL = """
SELECT created_at_ms, sequence_no
FROM chat_messages
WHERE session_id = ? AND message_id = ?
LIMIT 1
"""

MESSAGE_ORDER_SQL = "created_at_ms ASC, sequence_no ASC, message_id ASC"


def build_inclusive_frontier_filter(
    boundary: Any,
    *,
    message_id: str,
) -> tuple[str, list[object]]:
    """Return a stable inclusive ordering predicate and its parameters."""

    created_at_ms = int(boundary["created_at_ms"] or 0)
    sequence_no = int(boundary["sequence_no"] or 0)
    return (
        """
        AND (
            created_at_ms > ?
            OR (created_at_ms = ? AND sequence_no > ?)
            OR (created_at_ms = ? AND sequence_no = ? AND message_id >= ?)
        )
        """,
        [
            created_at_ms,
            created_at_ms,
            sequence_no,
            created_at_ms,
            sequence_no,
            message_id,
        ],
    )


__all__ = [
    "MESSAGE_FRONTIER_SELECT_SQL",
    "MESSAGE_ORDER_SQL",
    "build_inclusive_frontier_filter",
]
