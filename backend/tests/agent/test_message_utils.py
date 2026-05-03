from __future__ import annotations

from magi.agent.message_utils import append_latest_user_message


def test_append_latest_user_message_without_limit_keeps_full_short_history() -> None:
    history = [
        {"role": "user", "content": "message 1"},
        {"role": "assistant", "content": "answer 1"},
        {"role": "user", "content": "message 2"},
        {"role": "assistant", "content": "answer 2"},
    ]

    messages = append_latest_user_message(
        history,
        "message 3",
        history_token_budget=10_000,
    )

    assert [item["content"] for item in messages] == [
        "message 1",
        "answer 1",
        "message 2",
        "answer 2",
        "message 3",
    ]


def test_append_latest_user_message_adds_origin_anchor_when_head_is_trimmed() -> None:
    history = [
        {"role": "user", "content": "the session started with the product design question"},
        {"role": "assistant", "content": "we discussed context summaries"},
        {"role": "user", "content": "recent question " + "x" * 400},
        {"role": "assistant", "content": "recent answer " + "y" * 400},
    ]

    messages = append_latest_user_message(
        history,
        "current question",
        history_token_budget=120,
    )

    assert messages[0]["role"] == "user"
    assert "# Session Origin" in str(messages[0]["content"])
    assert "the session started with the product design question" in str(messages[0]["content"])
    assert messages[-1] == {"role": "user", "content": "current question"}
    assert any("recent answer" in str(item["content"]) for item in messages)


def test_append_latest_user_message_keeps_legacy_limit_when_explicit() -> None:
    history = [
        {"role": "user", "content": "message 1"},
        {"role": "assistant", "content": "answer 1"},
        {"role": "user", "content": "message 2"},
    ]

    messages = append_latest_user_message(
        history,
        "message 3",
        history_limit=1,
    )

    assert [item["content"] for item in messages] == ["message 2", "message 3"]
