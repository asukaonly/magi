from __future__ import annotations

from pathlib import Path

from magi.agent.message_utils import (
    _estimate_prompt_message_tokens,
    append_latest_user_message,
    group_prompt_history_turns,
)
from magi.agent.execution.attachment_resolver import NullAttachmentResolver
from magi.agent.task_agents.handlers.contracts import ChatReplyContext
from magi.agent.turn_input import UserTurnInput
from magi.utils.runtime import RuntimePaths

_NULL_RESOLVER = NullAttachmentResolver()


class _FakeAttachmentResolver:
    """Resolver returning a known payload for one attachment id."""

    def __init__(self, *, storage_path: str) -> None:
        self._storage_path = storage_path
        self.calls: list[tuple[str, str, str]] = []

    def get_attachment_payload(
        self, user_id: str, session_id: str, attachment_id: str
    ) -> dict[str, object] | None:
        self.calls.append((user_id, session_id, attachment_id))
        return {
            "attachment_id": attachment_id,
            "turn_id": "turn-1",
            "storage_path": self._storage_path,
        }


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
        resolver=_NULL_RESOLVER,
    )

    assert [item["content"] for item in messages] == [
        "message 1",
        "answer 1",
        "message 2",
        "answer 2",
        "message 3",
    ]


def test_prompt_history_estimate_is_more_conservative_for_chinese_text() -> None:
    ascii_tokens = _estimate_prompt_message_tokens({"role": "user", "content": "a" * 400})
    chinese_tokens = _estimate_prompt_message_tokens({"role": "user", "content": "你" * 400})

    assert chinese_tokens > ascii_tokens * 3


def test_group_prompt_history_turns_keeps_each_exchange_atomic() -> None:
    groups = group_prompt_history_turns(
        [
            {"role": "user", "content": "question 1"},
            {"role": "assistant", "content": "calling a tool"},
            {"role": "tool", "content": "tool result"},
            {"role": "assistant", "content": "answer 1"},
            {"role": "user", "content": "question 2"},
            {"role": "assistant", "content": "answer 2"},
        ]
    )

    assert groups == [
        [
            {"role": "user", "content": "question 1"},
            {"role": "assistant", "content": "calling a tool"},
            {"role": "tool", "content": "tool result"},
            {"role": "assistant", "content": "answer 1"},
        ],
        [
            {"role": "user", "content": "question 2"},
            {"role": "assistant", "content": "answer 2"},
        ],
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
        resolver=_NULL_RESOLVER,
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
        history_token_budget=None,
        history_limit=1,
        resolver=_NULL_RESOLVER,
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
        resolver=_NULL_RESOLVER,
    )

    assert [item["content"] for item in messages] == [
        "previous message",
        "previous answer",
        "Voice transcript: hello",
    ]


def test_append_latest_user_message_resumes_existing_turn_in_place() -> None:
    history = [
        {"role": "user", "content": "previous message"},
        {"role": "assistant", "content": "previous answer"},
        {"role": "user", "content": "current request"},
        {
            "role": "assistant",
            "content": "",
            "tool_calls": [{"id": "call-1", "function": {"name": "read"}}],
        },
        {"role": "tool", "content": "evidence", "tool_call_id": "call-1"},
    ]

    messages = append_latest_user_message(
        history,
        UserTurnInput(text="current request"),
        history_token_budget=10_000,
        resolver=_NULL_RESOLVER,
        latest_turn_already_present=True,
    )

    assert messages == history


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
        resolver=_NULL_RESOLVER,
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


def _image_turn(text: str) -> UserTurnInput:
    return UserTurnInput(
        text=text,
        attachments=[
            {
                "attachment_id": "att-image",
                "kind": "image",
                "mime_type": "image/png",
                # No ``storage_path``: forces resolution through the resolver.
            }
        ],
        user_id="user-1",
        session_id="session-1",
    )


def test_append_latest_user_message_resolves_image_payload_via_resolver(
    tmp_path: Path,
    monkeypatch,
) -> None:
    """A chat turn resolves an image attachment payload through the injected
    resolver and the resolved storage_path lands in the built content."""
    runtime_paths = RuntimePaths(tmp_path / "runtime")
    image_path = (
        runtime_paths.chat_images_dir
        / "session-1"
        / "turn-1"
        / "att-image__diagram.png"
    )
    image_path.parent.mkdir(parents=True, exist_ok=True)
    image_path.write_bytes(b"fake-image-bytes")
    resolver = _FakeAttachmentResolver(storage_path=str(image_path))
    monkeypatch.setattr(
        "magi.core.chat_assets.paths.get_runtime_paths",
        lambda: runtime_paths,
    )

    messages = append_latest_user_message(
        [],
        _image_turn("describe this screenshot"),
        history_token_budget=10_000,
        resolver=resolver,
    )

    assert resolver.calls == [("user-1", "session-1", "att-image")]
    content = messages[-1]["content"]
    assert content[0] == {"type": "text", "text": "describe this screenshot"}
    assert content[1]["type"] == "image"
    assert content[1]["mime_type"] == "image/png"


def test_append_latest_user_message_does_not_read_image_outside_chat_resources(
    tmp_path: Path,
    monkeypatch,
) -> None:
    runtime_paths = RuntimePaths(tmp_path / "runtime")
    outside_path = runtime_paths.base_dir / "private.png"
    outside_path.write_bytes(b"private")
    resolver = _FakeAttachmentResolver(storage_path=str(outside_path))
    monkeypatch.setattr(
        "magi.core.chat_assets.paths.get_runtime_paths",
        lambda: runtime_paths,
    )

    messages = append_latest_user_message(
        [],
        _image_turn("describe this screenshot"),
        history_token_budget=10_000,
        resolver=resolver,
    )

    assert messages[-1]["content"] == "describe this screenshot"


def test_append_latest_user_message_null_resolver_drops_unresolvable_image(
    tmp_path: Path,
) -> None:
    """NullAttachmentResolver resolves no payload, so an image attachment with
    no storage_path yields no image block (text-only content)."""
    messages = append_latest_user_message(
        [],
        _image_turn("describe this screenshot"),
        history_token_budget=10_000,
        resolver=_NULL_RESOLVER,
    )

    # Only the text block survives; no image block was built because the null
    # resolver returned no storage_path.
    assert messages[-1]["content"] == "describe this screenshot"
