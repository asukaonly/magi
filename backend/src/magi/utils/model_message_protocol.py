"""Provider-neutral validation helpers for tool-call message groups."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any


def protocol_complete_message_indexes(
    messages: Sequence[Mapping[str, Any]],
) -> tuple[int, ...]:
    """Return indexes that form a provider-valid tool-call transcript.

    Assistant tool-call messages are retained only when the immediately
    following tool messages answer every declared call exactly once. Orphaned
    tool messages are removed. Ordinary user and assistant messages remain in
    their original order.
    """

    retained: list[int] = []
    index = 0
    while index < len(messages):
        message = messages[index]
        role = str(message.get("role") or "").strip()
        tool_calls = message.get("tool_calls")
        if role == "assistant" and isinstance(tool_calls, list) and tool_calls:
            call_ids = _tool_call_ids(tool_calls)
            next_index = index + 1
            tool_indexes: list[int] = []
            tool_result_ids: list[str] = []
            while next_index < len(messages):
                candidate = messages[next_index]
                if str(candidate.get("role") or "").strip() not in {
                    "tool",
                    "tool_result",
                }:
                    break
                tool_indexes.append(next_index)
                tool_result_ids.append(
                    str(candidate.get("tool_call_id") or "").strip()
                )
                next_index += 1

            if (
                call_ids
                and len(call_ids) == len(tool_calls)
                and len(set(call_ids)) == len(call_ids)
                and len(tool_result_ids) == len(call_ids)
                and len(set(tool_result_ids)) == len(tool_result_ids)
                and set(tool_result_ids) == set(call_ids)
            ):
                retained.append(index)
                retained.extend(tool_indexes)
            index = next_index
            continue

        if role in {"tool", "tool_result"}:
            index += 1
            continue

        retained.append(index)
        index += 1

    return tuple(retained)


def repair_model_message_protocol(messages: list[dict[str, Any]]) -> int:
    """Remove incomplete tool protocol groups in place and return drop count."""

    retained_indexes = protocol_complete_message_indexes(messages)
    if len(retained_indexes) == len(messages):
        return 0
    retained = [messages[index] for index in retained_indexes]
    dropped_count = len(messages) - len(retained)
    messages[:] = retained
    return dropped_count


def _tool_call_ids(tool_calls: list[Any]) -> list[str]:
    return [
        str(call.get("id") or "").strip() if isinstance(call, Mapping) else ""
        for call in tool_calls
    ]


__all__ = [
    "protocol_complete_message_indexes",
    "repair_model_message_protocol",
]
