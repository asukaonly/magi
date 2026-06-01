"""Tests for the channel abstraction layer."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

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

# NotificationRelay tests removed in Phase G+4 — class deleted (retired by Phase G+1).
