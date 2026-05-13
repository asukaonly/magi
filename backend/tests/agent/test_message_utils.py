from __future__ import annotations

from magi.agent.message_utils import append_latest_user_message
from magi.agent.task_agents.chat.contracts import ChatReplyContext
from magi.agent.turn_input import UserTurnInput


def _turn(text: str) -> UserTurnInput:
    return UserTurnInput(text=text, attachments=[], user_id=None, session_id=None)


def _turn_with_attachments(text: str) -> UserTurnInput:
    return UserTurnInput(
        text=text,
        attachments=[
            {
                "kind": "audio",
                "mime_type": "audio/silk",
                "parse_status": "unsupported",
            }
        ],
        user_id="user-1",
        session_id="session-1",
    )


def test_append_latest_user_message_without_limit_keeps_full_short_history() -> None:
    history = [
        {"role": "user", "content": "message 1"},
        {"role": "assistant", "content": "answer 1"},
        {"role": "user", "content": "message 2"},
        {"role": "assistant", "content": "answer 2"},
    ]

    messages = append_latest_user_message(
        history,
        _turn("message 3"),
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
        _turn("current question"),
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
        _turn("message 3"),
        history_limit=1,
    )

    assert [item["content"] for item in messages] == ["message 2", "message 3"]


def test_append_latest_user_message_removes_persisted_current_turn_with_attachment() -> None:
    history = [
        {"role": "user", "content": "previous message"},
        {"role": "assistant", "content": "previous answer"},
        {"role": "user", "content": "Voice transcript: hello"},
    ]

    messages = append_latest_user_message(
        history,
        _turn_with_attachments("Voice transcript: hello"),
        history_token_budget=10_000,
    )

    assert [item["content"] for item in messages] == [
        "previous message",
        "previous answer",
        "Voice transcript: hello",
    ]


def test_append_latest_user_message_marks_explicit_reply_target_attachments() -> None:
    reply_context = ChatReplyContext(
        message_id="msg-image",
        role="user",
        content_excerpt="这个是谁",
        is_explicit_reply=True,
        references_prior_turn=True,
        structured_payload={
            "attachments": [
                {
                    "attachment_id": "att-image",
                    "kind": "image",
                    "original_name": "image.png",
                    "mime_type": "image/png",
                    "parse_status": "not_applicable",
                }
            ]
        },
    )

    messages = append_latest_user_message(
        [{"role": "user", "content": "这个图上文字是居中的还是居左的"}],
        _turn("这个图上文字是居中的还是居左的"),
        history_token_budget=10_000,
        reply_context=reply_context,
    )

    assert len(messages) == 1
    content = messages[-1]["content"]
    assert "这个图上文字是居中的还是居左的" in content
    assert "[Current message reply target]" in content
    assert "message_id=msg-image" in content
    assert 'message="这个是谁"' in content
    assert "attachment_id=att-image" in content
    assert "name=image.png" in content
    assert "kind=image" in content
    assert "parse_status=not_applicable" in content
