"""Tests for provider-neutral tool-call transcript validation."""

from magi.utils.model_message_protocol import (
    protocol_complete_message_indexes,
    repair_model_message_protocol,
)


def _assistant_tool_calls(*call_ids: str) -> dict[str, object]:
    return {
        "role": "assistant",
        "content": "",
        "tool_calls": [
            {
                "id": call_id,
                "type": "function",
                "function": {"name": "example", "arguments": "{}"},
            }
            for call_id in call_ids
        ],
    }


def test_protocol_keeps_complete_multi_call_group() -> None:
    messages = [
        {"role": "user", "content": "start"},
        _assistant_tool_calls("call-1", "call-2"),
        {"role": "tool", "tool_call_id": "call-2", "content": "two"},
        {"role": "tool", "tool_call_id": "call-1", "content": "one"},
        {"role": "assistant", "content": "done"},
    ]

    assert protocol_complete_message_indexes(messages) == (0, 1, 2, 3, 4)


def test_protocol_drops_incomplete_group_and_orphan_results() -> None:
    messages = [
        {"role": "user", "content": "start"},
        _assistant_tool_calls("call-1", "call-2"),
        {"role": "tool", "tool_call_id": "call-1", "content": "one"},
        {"role": "user", "content": "[Runtime outcome] Run cancelled."},
        {"role": "tool", "tool_call_id": "orphan", "content": "late"},
        {"role": "user", "content": "continue"},
    ]

    assert protocol_complete_message_indexes(messages) == (0, 3, 5)


def test_repair_mutates_messages_and_reports_dropped_count() -> None:
    messages = [
        {"role": "user", "content": "start"},
        _assistant_tool_calls("pending"),
        {"role": "user", "content": "[Runtime outcome] Run cancelled."},
    ]

    dropped_count = repair_model_message_protocol(messages)

    assert dropped_count == 1
    assert messages == [
        {"role": "user", "content": "start"},
        {"role": "user", "content": "[Runtime outcome] Run cancelled."},
    ]
