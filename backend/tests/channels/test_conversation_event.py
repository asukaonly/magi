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


def test_user_message_event_construction():
    ev = _user_event()
    assert ev.event_id == "ev-1"
    assert ev.event_type == "user_message"
    assert ev.content[0].text == "hi"


def test_event_is_frozen():
    ev = _user_event()
    with pytest.raises(Exception):
        ev.actor = "no"


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


def test_message_redacted_allows_none_content():
    ev = ConversationEvent(
        event_id="ev-2", event_type="message_redacted",
        timestamp_ms=1, actor="system",
        content=None, redacts="ev-1",
    )
    assert ev.redacts == "ev-1"


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


def test_message_revised_happy_path():
    ev = ConversationEvent(
        event_id="ev-3", event_type="message_revised",
        timestamp_ms=1, actor="user-1",
        content=[ContentBlock(kind="text", text="new")],
        revises="ev-1",
    )
    assert ev.revises == "ev-1"


def test_event_to_dict_roundtrip_for_user_message():
    ev = _user_event(metadata={"k": "v"})
    d = ev.to_dict()
    assert d["event_type"] == "user_message"
    assert d["content"][0]["text"] == "hi"
    assert d["metadata"] == {"k": "v"}


def test_event_to_dict_serializes_content_blocks_to_list_of_dicts():
    ev = _user_event(content=[
        ContentBlock(kind="text", text="hello"),
        ContentBlock(kind="text", text="world"),
    ])
    d = ev.to_dict()
    assert d["content"] == [
        {"kind": "text", "text": "hello", "metadata": {}},
        {"kind": "text", "text": "world", "metadata": {}},
    ]


def test_event_to_dict_for_redaction_has_null_content():
    ev = ConversationEvent(
        event_id="ev-2", event_type="message_redacted",
        timestamp_ms=1, actor="system",
        content=None, redacts="ev-1",
    )
    d = ev.to_dict()
    assert d["content"] is None
    assert d["redacts"] == "ev-1"
