"""Load optional companion-repository fixtures only for native MySQL cases."""
import pytest


@pytest.fixture
async def mysql_chat(monkeypatch, tmp_path):
    from test_mysql_chat_repository import mysql_chat as fixture
    async for value in fixture.__wrapped__(monkeypatch, tmp_path):
        yield value


@pytest.fixture
async def mysql_chat_reader(mysql_chat, monkeypatch):
    from test_mysql_chat_repository import mysql_chat_reader as fixture
    async for value in fixture.__wrapped__(mysql_chat, monkeypatch):
        yield value


@pytest.fixture
async def mysql_environment(monkeypatch):
    from memory.l1.test_mysql_event_repository import mysql_environment as fixture
    async for value in fixture.__wrapped__(monkeypatch):
        yield value


async def create_turn(store, *, turn="t1", session="s1"):
    return await store.create_user_turn_once(session_id=session, user_id="u1", turn_id=turn,
        message_text="Turn on the living room light", created_at_ms=100,
        runtime_envelope={"session_id": session, "turn_id": turn, "message": "light", "attachments": [], "metadata": {}},
        request_fingerprint="fingerprint-"+turn)
