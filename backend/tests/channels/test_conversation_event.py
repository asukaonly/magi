import pytest

from magi_plugin_sdk.conversation import ContentBlock, ConversationEvent


def _user_event(**overrides):
    base = dict(
        event_id="ev-1",
        event_type="user_message",
        timestamp_ms=1000,
        actor="user-1",
        content=[ContentBlock(kind="text", text="hi")],
    )
    base.update(overrides)
    return ConversationEvent(**base)


def test_unknown_event_type_rejected():
    with pytest.raises(ValueError, match="event_type"):
        _user_event(event_type="not_a_real_type")


def test_user_message_requires_content():
    with pytest.raises(ValueError, match="user_message"):
        _user_event(content=None)
    with pytest.raises(ValueError, match="user_message"):
        _user_event(content=[])


def test_message_redacted_requires_redacts_field():
    with pytest.raises(ValueError, match="message_redacted"):
        ConversationEvent(
            event_id="ev-2", event_type="message_redacted",
            timestamp_ms=1, actor="system",
            content=None, redacts=None,
        )


def test_message_revised_requires_revises_and_content():
    with pytest.raises(ValueError, match="message_revised"):
        ConversationEvent(
            event_id="ev-3", event_type="message_revised",
            timestamp_ms=1, actor="user-1",
            content=[ContentBlock(kind="text", text="new")],
            revises=None,
        )
    with pytest.raises(ValueError, match="message_revised"):
        ConversationEvent(
            event_id="ev-3", event_type="message_revised",
            timestamp_ms=1, actor="user-1",
            content=None, revises="ev-1",
        )


@pytest.mark.parametrize("event_type", ["user_message", "message_revised", "message_redacted"])
def test_conversation_event_wire_payload_preserves_content_and_revision_identity(event_type):
    first = ContentBlock(kind="text", text="hello")
    second = ContentBlock.from_dict({"kind": "text", "text": "world", "metadata": {"part": 2}})
    assert ContentBlock.from_dict({"kind": "text", "text": "hello"}) == first
    redaction = event_type == "message_redacted"
    revises = "old-1" if event_type == "message_revised" else None
    redacts = "old-1" if redaction else None
    event = ConversationEvent(
        event_id="ev-2",
        event_type=event_type,
        timestamp_ms=1000,
        actor="user-1",
        content=None if redaction else [first, second],
        revises=revises,
        redacts=redacts,
        triggered_run_id="run-1",
        source_channel="telegram",
        metadata={"source_id": "msg-1"},
    )
    payload = event.to_dict()
    assert payload == {
        "event_id": "ev-2",
        "event_type": event_type,
        "timestamp_ms": 1000,
        "actor": "user-1",
        "content": (
            None
            if redaction
            else [
                {"kind": "text", "text": "hello", "metadata": {}},
                {"kind": "text", "text": "world", "metadata": {"part": 2}},
            ]
        ),
        "revises": revises,
        "redacts": redacts,
        "triggered_run_id": "run-1",
        "source_channel": "telegram",
        "metadata": {"source_id": "msg-1"},
    }
    if not redaction:
        assert [ContentBlock.from_dict(block) for block in payload["content"]] == [first, second]
