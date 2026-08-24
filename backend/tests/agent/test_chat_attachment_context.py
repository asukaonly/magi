from __future__ import annotations

from types import SimpleNamespace

from magi.agent.execution.attachment_resolver import NullAttachmentResolver
from magi.agent.task_agents.handlers.attachment_context import resolve_effective_turn_attachments
from magi.agent.task_agents.handlers.contracts import ChatReplyContext

_NULL_RESOLVER = NullAttachmentResolver()


class _FakeReadService:
    def get_attachment_payload(
        self,
        user_id: str,
        session_id: str,
        attachment_id: str,
    ) -> dict[str, object] | None:
        assert user_id == "user-1"
        assert session_id == "session-1"
        assert attachment_id == "att-image"
        return {
            "attachment_id": "att-image",
            "turn_id": "turn-1",
            "kind": "image",
            "original_name": "image.png",
            "mime_type": "image/png",
            "storage_path": "/runtime/chat/image.png",
        }


def test_effective_turn_attachments_include_explicit_reply_target_attachments() -> None:
    context = SimpleNamespace(
        latest_payload=SimpleNamespace(attachments=[]),
        reply_context=ChatReplyContext(
            message_id="msg-image",
            role="user",
            content_excerpt="这个是谁",
            is_explicit_reply=True,
            references_prior_turn=True,
            structured_payload={
                "attachments": [
                    {"attachment_id": "att-image", "kind": "image", "original_name": "image.png"}
                ]
            },
        ),
    )

    assert resolve_effective_turn_attachments(context, resolver=_NULL_RESOLVER) == [
        {"attachment_id": "att-image", "kind": "image", "original_name": "image.png"}
    ]


def test_effective_turn_attachments_ignore_non_explicit_reply_context() -> None:
    context = SimpleNamespace(
        latest_payload=SimpleNamespace(attachments=[]),
        reply_context=ChatReplyContext(
            message_id="msg-image",
            role="user",
            content_excerpt="这个是谁",
            is_explicit_reply=False,
            references_prior_turn=True,
            structured_payload={"attachments": [{"attachment_id": "att-image", "kind": "image"}]},
        ),
    )

    assert resolve_effective_turn_attachments(context, resolver=_NULL_RESOLVER) == []


def test_effective_turn_attachments_deduplicate_current_and_reply_refs() -> None:
    context = SimpleNamespace(
        latest_payload=SimpleNamespace(attachments=[{"attachment_id": "att-image", "kind": "image"}]),
        reply_context=ChatReplyContext(
            message_id="msg-image",
            role="user",
            content_excerpt="这个是谁",
            is_explicit_reply=True,
            references_prior_turn=True,
            structured_payload={"attachments": [{"attachment_id": "att-image", "kind": "image"}]},
        ),
    )

    assert resolve_effective_turn_attachments(context, resolver=_NULL_RESOLVER) == [{"attachment_id": "att-image", "kind": "image"}]


def test_effective_turn_attachments_resolve_reply_target_managed_payload() -> None:
    context = SimpleNamespace(
        user_id="user-1",
        session_id="session-1",
        latest_payload=SimpleNamespace(attachments=[]),
        reply_context=ChatReplyContext(
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
                        "parse_status": "not_applicable",
                    }
                ]
            },
        ),
    )

    attachments = resolve_effective_turn_attachments(
        context,
        resolver=_FakeReadService(),
    )

    assert attachments == [
        {
            "attachment_id": "att-image",
            "turn_id": "turn-1",
            "kind": "image",
            "original_name": "image.png",
            "mime_type": "image/png",
            "storage_path": "/runtime/chat/image.png",
            "parse_status": "not_applicable",
        }
    ]
