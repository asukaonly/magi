"""Tests for the channel abstraction layer."""

from __future__ import annotations

import asyncio
import json
import time
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from magi.channels.base import Channel
from magi.channels.contracts import (
    ChannelSessionMapping,
    ChannelTarget,
    InboundMessage,
    OutboundContent,
)
from magi.channels.registry import ChannelRegistry
from magi.channels.session_mapper import ChannelSessionMapper
from magi.channels.notification_relay import NotificationRelay


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

class FakeChannel(Channel):
    """Minimal test-only channel implementation."""

    def __init__(self, name: str = "fake") -> None:
        self._name = name
        self.started = False
        self.stopped = False
        self.sent: list[tuple[ChannelTarget, OutboundContent]] = []

    @property
    def channel_type(self) -> str:
        return self._name

    async def start(self) -> None:
        self.started = True

    async def stop(self) -> None:
        self.stopped = True

    async def send_message(self, target: ChannelTarget, content: OutboundContent) -> None:
        self.sent.append((target, content))

    async def send_typing_indicator(self, target: ChannelTarget) -> None:
        pass


# ---------------------------------------------------------------------------
# ChannelRegistry
# ---------------------------------------------------------------------------

class TestChannelRegistry:
    def test_register_and_get(self) -> None:
        reg = ChannelRegistry()
        ch = FakeChannel("telegram")
        reg.register(ch)
        assert reg.get("telegram") is ch

    def test_duplicate_register_raises(self) -> None:
        reg = ChannelRegistry()
        reg.register(FakeChannel("telegram"))
        with pytest.raises(ValueError, match="already registered"):
            reg.register(FakeChannel("telegram"))

    def test_get_unknown_returns_none(self) -> None:
        reg = ChannelRegistry()
        assert reg.get("discord") is None

    @pytest.mark.asyncio
    async def test_start_and_stop_all(self) -> None:
        reg = ChannelRegistry()
        ch1 = FakeChannel("a")
        ch2 = FakeChannel("b")
        reg.register(ch1)
        reg.register(ch2)
        await reg.start_all()
        assert ch1.started and ch2.started
        await reg.stop_all()
        assert ch1.stopped and ch2.stopped


# ---------------------------------------------------------------------------
# ChannelSessionMapper
# ---------------------------------------------------------------------------

@pytest.fixture
def mapper_db(tmp_path: Path) -> str:
    return str(tmp_path / "channels.db")


@pytest.fixture
def mock_chat_store() -> MagicMock:
    store = MagicMock()
    store.upsert_session = AsyncMock()
    return store


@pytest.mark.asyncio
class TestChannelSessionMapper:
    async def test_resolve_creates_new_session(
        self, mapper_db: str, mock_chat_store: MagicMock
    ) -> None:
        mapper = ChannelSessionMapper(db_path=mapper_db, chat_store=mock_chat_store)
        await mapper.initialize()

        mapping = await mapper.resolve_or_create(
            channel_type="telegram",
            external_chat_id="12345",
            external_user_id="user1",
            is_group=False,
            display_name="TG: @testuser",
        )

        assert mapping.channel_type == "telegram"
        assert mapping.external_chat_id == "12345"
        assert mapping.magi_session_id.startswith("chsess_")
        assert not mapping.is_group
        mock_chat_store.upsert_session.assert_called_once()

    async def test_resolve_returns_existing(
        self, mapper_db: str, mock_chat_store: MagicMock
    ) -> None:
        mapper = ChannelSessionMapper(db_path=mapper_db, chat_store=mock_chat_store)
        await mapper.initialize()

        first = await mapper.resolve_or_create(
            channel_type="telegram",
            external_chat_id="12345",
            external_user_id="user1",
        )
        second = await mapper.resolve_or_create(
            channel_type="telegram",
            external_chat_id="12345",
            external_user_id="user1",
        )

        assert first.magi_session_id == second.magi_session_id
        # upsert_session called only once (first create)
        assert mock_chat_store.upsert_session.call_count == 1

    async def test_lookup_nonexistent(
        self, mapper_db: str, mock_chat_store: MagicMock
    ) -> None:
        mapper = ChannelSessionMapper(db_path=mapper_db, chat_store=mock_chat_store)
        await mapper.initialize()
        result = await mapper.lookup("telegram", "nonexistent")
        assert result is None

    async def test_lookup_by_session(
        self, mapper_db: str, mock_chat_store: MagicMock
    ) -> None:
        mapper = ChannelSessionMapper(db_path=mapper_db, chat_store=mock_chat_store)
        await mapper.initialize()

        mapping = await mapper.resolve_or_create(
            channel_type="telegram",
            external_chat_id="12345",
            external_user_id="user1",
        )

        reverse = await mapper.lookup_by_session(mapping.magi_session_id)
        assert reverse is not None
        assert reverse.external_chat_id == "12345"

    async def test_delete_mapping(
        self, mapper_db: str, mock_chat_store: MagicMock
    ) -> None:
        mapper = ChannelSessionMapper(db_path=mapper_db, chat_store=mock_chat_store)
        await mapper.initialize()

        await mapper.resolve_or_create(
            channel_type="telegram",
            external_chat_id="12345",
            external_user_id="user1",
        )
        await mapper.delete_mapping("telegram", "12345")
        result = await mapper.lookup("telegram", "12345")
        assert result is None

    async def test_group_session(
        self, mapper_db: str, mock_chat_store: MagicMock
    ) -> None:
        mapper = ChannelSessionMapper(db_path=mapper_db, chat_store=mock_chat_store)
        await mapper.initialize()

        mapping = await mapper.resolve_or_create(
            channel_type="telegram",
            external_chat_id="-100123456",
            external_user_id="user1",
            is_group=True,
            display_name="TG Group: Test Group",
        )

        assert mapping.is_group is True

    async def test_notification_cursor(
        self, mapper_db: str, mock_chat_store: MagicMock
    ) -> None:
        mapper = ChannelSessionMapper(db_path=mapper_db, chat_store=mock_chat_store)
        await mapper.initialize()

        cursor = await mapper.get_notification_cursor("telegram", "12345")
        assert cursor == 0

        await mapper.update_notification_cursor("telegram", "12345", 42)
        cursor = await mapper.get_notification_cursor("telegram", "12345")
        assert cursor == 42


# ---------------------------------------------------------------------------
# NotificationRelay
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
class TestNotificationRelay:
    async def test_dispatches_agent_response(self) -> None:
        channel = FakeChannel("telegram")
        registry = ChannelRegistry()
        registry.register(channel)

        mapper = MagicMock(spec=ChannelSessionMapper)
        mapper.lookup_by_session = AsyncMock(
            return_value=ChannelSessionMapping(
                channel_type="telegram",
                external_chat_id="12345",
                magi_session_id="sess_abc",
                magi_user_id="user1",
            )
        )

        notif = MagicMock()
        notif.notification_id = 1
        notif.channel = "agent_response"
        notif.session_id = "sess_abc"
        notif.payload_json = json.dumps({"content": "Hello from Magi!"})

        trace_store = MagicMock()
        trace_store.get_latest_notification_id = AsyncMock(return_value=0)
        trace_store.list_notifications = AsyncMock(side_effect=[[notif], []])

        relay = NotificationRelay(
            registry=registry,
            session_mapper=mapper,
            trace_store=trace_store,
            poll_interval_s=0.01,
        )

        # Run one cycle then stop
        relay._running = True
        relay._cursor = 0
        await relay._poll_cycle()

        assert len(channel.sent) == 1
        target, content = channel.sent[0]
        assert target.channel_type == "telegram"
        assert target.external_chat_id == "12345"
        assert content.text == "Hello from Magi!"

    async def test_ignores_non_channel_sessions(self) -> None:
        channel = FakeChannel("telegram")
        registry = ChannelRegistry()
        registry.register(channel)

        mapper = MagicMock(spec=ChannelSessionMapper)
        mapper.lookup_by_session = AsyncMock(return_value=None)  # Not a channel session

        notif = MagicMock()
        notif.notification_id = 1
        notif.channel = "agent_response"
        notif.session_id = "unknown_sess"
        notif.payload_json = json.dumps({"content": "Should not be sent"})

        trace_store = MagicMock()
        trace_store.get_latest_notification_id = AsyncMock(return_value=0)
        trace_store.list_notifications = AsyncMock(side_effect=[[notif], []])

        relay = NotificationRelay(
            registry=registry,
            session_mapper=mapper,
            trace_store=trace_store,
        )

        relay._running = True
        relay._cursor = 0
        await relay._poll_cycle()

        assert len(channel.sent) == 0

    async def test_ignores_non_response_channels(self) -> None:
        channel = FakeChannel("telegram")
        registry = ChannelRegistry()
        registry.register(channel)

        mapper = MagicMock(spec=ChannelSessionMapper)

        notif = MagicMock()
        notif.notification_id = 1
        notif.channel = "turn_ux_plan"
        notif.session_id = "sess_x"
        notif.payload_json = json.dumps({})

        trace_store = MagicMock()
        trace_store.get_latest_notification_id = AsyncMock(return_value=0)
        trace_store.list_notifications = AsyncMock(side_effect=[[notif], []])

        relay = NotificationRelay(
            registry=registry,
            session_mapper=mapper,
            trace_store=trace_store,
        )

        relay._running = True
        relay._cursor = 0
        await relay._poll_cycle()

        # Mapper should not even be called for non-response channels
        mapper.lookup_by_session.assert_not_called()
        assert len(channel.sent) == 0

    async def test_assembles_streamed_chunks(self) -> None:
        """Relay accumulates content_delta from streaming chunks and sends on is_final."""
        channel = FakeChannel("telegram")
        registry = ChannelRegistry()
        registry.register(channel)

        mapper = MagicMock(spec=ChannelSessionMapper)
        mapper.lookup_by_session = AsyncMock(
            return_value=ChannelSessionMapping(
                channel_type="telegram",
                external_chat_id="12345",
                magi_session_id="sess_abc",
                magi_user_id="user1",
            )
        )

        def _make_chunk(nid: int, delta: str, is_final: bool) -> MagicMock:
            n = MagicMock()
            n.notification_id = nid
            n.channel = "agent_response_chunk"
            n.session_id = "sess_abc"
            payload: dict[str, Any] = {
                "turn_id": "turn_1",
                "content_delta": delta,
                "is_final": is_final,
            }
            n.payload_json = json.dumps(payload)
            return n

        chunks = [
            _make_chunk(1, "Hello", False),
            _make_chunk(2, " world", False),
            _make_chunk(3, "!", False),
            _make_chunk(4, "", True),  # final marker, empty delta
        ]

        trace_store = MagicMock()
        trace_store.get_latest_notification_id = AsyncMock(return_value=0)
        trace_store.list_notifications = AsyncMock(side_effect=[chunks, []])

        relay = NotificationRelay(
            registry=registry,
            session_mapper=mapper,
            trace_store=trace_store,
            poll_interval_s=0.01,
        )

        relay._running = True
        relay._cursor = 0
        await relay._poll_cycle()

        assert len(channel.sent) == 1
        _, content = channel.sent[0]
        assert content.text == "Hello world!"
        assert content.is_final is True
