"""Deleted identities cannot be re-admitted through another device or writer."""

from dataclasses import replace

import pytest

from _shared.chat_stores import build_chat_reader
from magi.chat.storage.sqlite_store import SqliteChatRepository
from _shared.db_schema import apply_chain_schema
from magi.chat.errors import ChatTurnConflictError
from magi.utils.runtime import RuntimePaths
from test_mysql_chat_repository import create_turn
from test_mysql_chat_repository import mysql_chat as mysql_chat, mysql_chat_reader as mysql_chat_reader


@pytest.fixture
def chat_owners(tmp_path):
    paths = RuntimePaths(base_dir=tmp_path)
    apply_chain_schema("chat", paths.chat_db_path)
    reader = build_chat_reader(runtime_paths=paths)
    store = SqliteChatRepository(db_path=str(paths.chat_db_path), runtime_paths=paths)
    yield store, reader
    reader.close()


async def assert_retirement(store, reader, operation):
    accepted = await create_turn(store)
    old_turn = await store.get_turn("t1")
    if operation == "history":
        await reader.aclear_conversation_history("u1", "s1")
    elif operation == "message":
        assert await reader.aforget_message_artifacts("u1", "s1", accepted.message.message_id)
    elif operation == "session":
        await reader.adelete_session("u1", "s1")
    else:
        await reader.aclear_all_sessions()
        assert await reader.acomplete_global_clear()
    await store.shutdown()
    await store.initialize()
    with pytest.raises(ChatTurnConflictError):
        await create_turn(store)
    with pytest.raises(ChatTurnConflictError, match="permanently cleared"):
        await store.upsert_turn(old_turn)
    with pytest.raises(ChatTurnConflictError, match="permanently cleared"):
        await store.append_message(replace(accepted.message, message_id="new-id-after-clear"))
    assert (await create_turn(store, session="fresh-session", turn="fresh-turn")).created


@pytest.mark.parametrize("operation", ["history", "message", "session", "global"])
async def test_sqlite_retirement(chat_owners, operation):
    await assert_retirement(*chat_owners, operation)


@pytest.mark.parametrize("operation", ["history", "message", "session", "global"])
async def test_mysql_retirement(mysql_chat, mysql_chat_reader, operation):
    await assert_retirement(mysql_chat[0], mysql_chat_reader, operation)


async def assert_snapshot_preserves_new_turn(store, reader):
    old = await create_turn(store)
    new = await create_turn(store, turn="t2")
    await reader.aclear_conversation_history_snapshot("u1", "s1", [old.message.message_id], ["t1"])
    with pytest.raises(ChatTurnConflictError):
        await create_turn(store)
    retry = await create_turn(store, turn="t2")
    assert not retry.created and retry.message.message_id == new.message.message_id


async def test_sqlite_snapshot_preserves_new_turn(chat_owners):
    await assert_snapshot_preserves_new_turn(*chat_owners)


async def test_mysql_snapshot_preserves_new_turn(mysql_chat, mysql_chat_reader):
    await assert_snapshot_preserves_new_turn(mysql_chat[0], mysql_chat_reader)
