"""Stable turn identity at the inbound channel boundary."""

from __future__ import annotations

import re
from types import SimpleNamespace

import pytest

from magi.channels.dispatcher import ChannelMessageDispatcher


class _RecordingDispatch:
    def __init__(self) -> None:
        self.requests: list[dict[str, object]] = []

    async def __call__(self, **kwargs: object) -> SimpleNamespace:
        self.requests.append(dict(kwargs))
        return SimpleNamespace(
            success=True,
            user_id=kwargs["user_id"],
            session_id=kwargs["session_id"],
            turn_id=kwargs["client_turn_id"],
            message_id="message-1",
            error_code=None,
            error_message=None,
            queue_size=0,
        )


async def _forwarded_turn_id(
    recorder: _RecordingDispatch,
    *,
    source: str = "telegram",
    client_turn_id: str | None = None,
    metadata: dict[str, object] | None = None,
) -> object:
    dispatcher = ChannelMessageDispatcher(message_dispatcher=recorder)
    await dispatcher.dispatch_user_message(
        source=source,
        user_id="local_user",
        message="hello",
        session_id="session-1",
        client_turn_id=client_turn_id,
        metadata=metadata,
    )
    return recorder.requests[-1]["client_turn_id"]


@pytest.mark.asyncio
async def test_derives_stable_safe_turn_id_from_external_message_identity() -> None:
    recorder = _RecordingDispatch()
    metadata = {
        "account_id": "bot-account-1",
        "external_chat_id": "chat/@with unsafe characters",
        "external_message_id": "message:42/7",
        "transport_timestamp": 12345,
    }

    first = await _forwarded_turn_id(recorder, metadata=metadata)
    second = await _forwarded_turn_id(
        recorder,
        metadata={**metadata, "transport_timestamp": 99999},
    )

    assert first == second
    assert isinstance(first, str)
    assert len(first) <= 128
    assert re.fullmatch(r"[A-Za-z0-9_-]{1,128}", first)
    assert "chat" not in first
    assert "message" not in first


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("changed_source", "changed_metadata"),
    [
        ("slack", {}),
        ("telegram", {"account_id": "bot-account-2"}),
        ("telegram", {"external_chat_id": "chat-2"}),
        ("telegram", {"external_message_id": "message-2"}),
    ],
)
async def test_external_turn_id_is_scoped_to_channel_account_chat_and_message(
    changed_source: str,
    changed_metadata: dict[str, object],
) -> None:
    recorder = _RecordingDispatch()
    base_metadata = {
        "account_id": "bot-account-1",
        "external_chat_id": "chat-1",
        "external_message_id": "message-1",
    }
    baseline = await _forwarded_turn_id(
        recorder,
        source="telegram",
        metadata=base_metadata,
    )
    changed = await _forwarded_turn_id(
        recorder,
        source=changed_source,
        metadata={**base_metadata, **changed_metadata},
    )

    assert changed != baseline


@pytest.mark.asyncio
async def test_explicit_client_turn_id_takes_priority() -> None:
    recorder = _RecordingDispatch()

    forwarded = await _forwarded_turn_id(
        recorder,
        client_turn_id="turn_plugin_supplied",
        metadata={
            "account_id": "bot-account-1",
            "external_chat_id": "chat-1",
            "external_message_id": "message-1",
        },
    )

    assert forwarded == "turn_plugin_supplied"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "metadata",
    [
        None,
        {},
        {"external_chat_id": "chat-1"},
        {"external_chat_id": "chat-1", "external_message_id": ""},
        {"external_chat_id": "chat-1", "external_message_id": True},
        {"external_chat_id": "chat-1", "external_message_id": {"id": "1"}},
        {"external_message_id": "message-1"},
    ],
)
async def test_keeps_existing_random_turn_behavior_without_reliable_identity(
    metadata: dict[str, object] | None,
) -> None:
    recorder = _RecordingDispatch()

    forwarded = await _forwarded_turn_id(recorder, metadata=metadata)

    assert forwarded is None


@pytest.mark.asyncio
async def test_numeric_external_ids_are_stable() -> None:
    recorder = _RecordingDispatch()

    first = await _forwarded_turn_id(
        recorder,
        metadata={
            "account_id": 7,
            "external_chat_id": -100123,
            "external_message_id": 42,
        },
    )
    second = await _forwarded_turn_id(
        recorder,
        metadata={
            "account_id": "7",
            "external_chat_id": "-100123",
            "external_message_id": "42",
        },
    )

    assert first == second
