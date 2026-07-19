"""ConversationLog integration tests against a tmp SQLite chat DB.

These tests apply the chat-domain DDL directly to a tmp sqlite file
rather than going through Alembic, mirroring the pattern used by
``test_conversation_log_store.py``. The DDL block below is a verbatim
copy of the relevant tables from
``backend/src/magi/db/migrations/chat/versions/v1_initial.py``.
"""
from __future__ import annotations

import aiosqlite
import pytest

from magi.chat.conversation_log import ChatRunConsumedEventsStore, ConversationLog
from magi.chat.store import ChatStore
from magi_plugin_sdk.conversation import ContentBlock, ConversationEvent


# Verbatim subset of magi.db.migrations.chat.versions.v1_initial.SCHEMA_SQL
# limited to the tables ConversationLog + the messages repository touch.
DDL = """
CREATE TABLE IF NOT EXISTS chat_sessions (
    session_id TEXT PRIMARY KEY,
    user_id TEXT NOT NULL,
    title TEXT NOT NULL,
    title_overridden INTEGER NOT NULL DEFAULT 0,
    summary TEXT NOT NULL DEFAULT '',
    created_at_ms INTEGER NOT NULL,
    updated_at_ms INTEGER NOT NULL,
    last_message_at_ms INTEGER,
    last_user_message_at_ms INTEGER,
    last_message_preview TEXT NOT NULL DEFAULT '',
    last_user_message_preview TEXT NOT NULL DEFAULT '',
    message_count INTEGER NOT NULL DEFAULT 0,
    workspace_path TEXT,
    history_version INTEGER NOT NULL DEFAULT 0,
    archived_at_ms INTEGER,
    deleted_at_ms INTEGER
);

CREATE TABLE IF NOT EXISTS chat_messages (
    message_id TEXT PRIMARY KEY,
    session_id TEXT NOT NULL,
    turn_id TEXT,
    user_id TEXT NOT NULL,
    role TEXT NOT NULL,
    message_kind TEXT NOT NULL,
    content_text TEXT,
    payload_json TEXT NOT NULL DEFAULT '{}',
    is_final INTEGER NOT NULL DEFAULT 1,
    is_visible INTEGER NOT NULL DEFAULT 1,
    created_at_ms INTEGER NOT NULL,
    sequence_no INTEGER NOT NULL,
    replaces_message_id TEXT,
    replaced_by_message_id TEXT,
    persona_id TEXT,
    reply_to_message_id TEXT,
    label_json TEXT
);

CREATE TABLE IF NOT EXISTS chat_attachments (
    attachment_id TEXT PRIMARY KEY,
    session_id TEXT NOT NULL,
    turn_id TEXT,
    message_id TEXT NOT NULL,
    user_id TEXT NOT NULL,
    kind TEXT NOT NULL,
    original_name TEXT NOT NULL DEFAULT '',
    mime_type TEXT NOT NULL DEFAULT 'application/octet-stream',
    size_bytes INTEGER NOT NULL DEFAULT 0,
    storage_rel_path TEXT NOT NULL,
    sha256 TEXT,
    created_at_ms INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS chat_message_asset_refs (
    message_id TEXT NOT NULL,
    asset_key TEXT NOT NULL,
    storage_rel_path TEXT NOT NULL,
    asset_kind TEXT NOT NULL,
    created_at_ms INTEGER NOT NULL,
    PRIMARY KEY (message_id, asset_key)
);

CREATE TABLE IF NOT EXISTS chat_message_code_delegation_refs (
    message_id TEXT NOT NULL,
    session_id TEXT COLLATE NOCASE NOT NULL,
    delegation_id TEXT NOT NULL,
    turn_id TEXT NOT NULL,
    workspace_path TEXT NOT NULL,
    created_at_ms INTEGER NOT NULL,
    PRIMARY KEY (message_id, delegation_id)
);

CREATE TABLE IF NOT EXISTS chat_run_consumed_events (
    session_id     TEXT    NOT NULL,
    run_id         TEXT    NOT NULL,
    revision       INTEGER NOT NULL DEFAULT 0,
    message_id     TEXT    NOT NULL,
    recorded_at_ms INTEGER NOT NULL,
    PRIMARY KEY (session_id, run_id, revision, message_id)
);
"""


@pytest.fixture
async def log(tmp_path):
    db_path = str(tmp_path / "chat.db")
    async with aiosqlite.connect(db_path) as db:
        await db.executescript(DDL)
        await db.commit()
    messages_repo = ChatStore(db_path=db_path)
    await messages_repo.initialize()
    consumed_store = ChatRunConsumedEventsStore(db_path=db_path)
    await consumed_store.initialize()
    return ConversationLog(
        messages_repo=messages_repo,
        consumed_events_store=consumed_store,
    )


def _user_event(
    event_id: str, text: str, *, ts: int = 1000, run_id: str | None = None,
) -> ConversationEvent:
    return ConversationEvent(
        event_id=event_id,
        event_type="user_message",
        timestamp_ms=ts,
        actor="u1",
        content=[ContentBlock(kind="text", text=text)],
        triggered_run_id=run_id,
    )


def _reply_event(
    event_id: str, text: str, *, ts: int = 2000, run_id: str | None = None,
) -> ConversationEvent:
    return ConversationEvent(
        event_id=event_id,
        event_type="agent_reply",
        timestamp_ms=ts,
        actor="agent",
        content=[ContentBlock(kind="text", text=text)],
        triggered_run_id=run_id,
    )


@pytest.mark.asyncio
async def test_append_then_materialize_returns_inserted_text(log):
    await log.append(_user_event("ev-1", "hello"), session_id="s1")
    await log.append(_reply_event("ev-2", "hi back"), session_id="s1")
    blocks = await log.materialize(session_id="s1")
    assert len(blocks) == 2
    assert blocks[0].text == "hello"
    assert blocks[1].text == "hi back"


@pytest.mark.asyncio
async def test_materialize_excludes_redacted_messages_by_default(log):
    await log.append(_user_event("ev-1", "first", ts=1000), session_id="s1")
    await log.append(_user_event("ev-2", "secret", ts=2000), session_id="s1")
    await log.append(_user_event("ev-3", "third", ts=3000), session_id="s1")
    redact = ConversationEvent(
        event_id="ev-r",
        event_type="message_redacted",
        timestamp_ms=4000,
        actor="system",
        content=None,
        redacts="ev-2",
    )
    await log.append(redact, session_id="s1")
    blocks = await log.materialize(session_id="s1")
    texts = [b.text for b in blocks]
    assert "secret" not in texts
    assert texts == ["first", "third"]


@pytest.mark.asyncio
async def test_materialize_with_exclude_redacted_false_includes_hidden(log):
    await log.append(_user_event("ev-1", "first", ts=1000), session_id="s1")
    await log.append(_user_event("ev-2", "secret", ts=2000), session_id="s1")
    redact = ConversationEvent(
        event_id="ev-r",
        event_type="message_redacted",
        timestamp_ms=4000,
        actor="system",
        content=None,
        redacts="ev-2",
    )
    await log.append(redact, session_id="s1")
    blocks = await log.materialize(session_id="s1", exclude_redacted=False)
    texts = [b.text for b in blocks]
    assert "secret" in texts


@pytest.mark.asyncio
async def test_materialize_revision_returns_new_content(log):
    await log.append(_user_event("ev-1", "first draft", ts=1000), session_id="s1")
    revision = ConversationEvent(
        event_id="ev-2",
        event_type="message_revised",
        timestamp_ms=2000,
        actor="u1",
        content=[ContentBlock(kind="text", text="revised version")],
        revises="ev-1",
    )
    await log.append(revision, session_id="s1")
    blocks = await log.materialize(session_id="s1")
    # The chain (ev-1 → ev-2) should produce ONE materialized block with
    # the new text; the original is no longer the "head" of its chain.
    texts = [b.text for b in blocks]
    assert "revised version" in texts
    assert "first draft" not in texts


@pytest.mark.asyncio
async def test_materialize_returns_empty_for_unknown_session(log):
    blocks = await log.materialize(session_id="empty")
    assert blocks == []


@pytest.mark.asyncio
async def test_find_dependents_returns_recorded_runs(log):
    await log.record_consumed(
        session_id="s1", run_id="r1", revision=0, message_ids=["m1", "m2"],
    )
    deps = await log.find_dependents(session_id="s1", message_id="m1")
    assert deps == [("r1", 0)]


@pytest.mark.asyncio
async def test_find_dependents_empty_when_no_runs_consumed(log):
    deps = await log.find_dependents(session_id="s1", message_id="m1")
    assert deps == []


@pytest.mark.asyncio
async def test_list_visible_message_ids_returns_ordered_visible_ids(log):
    """Phase F Task 10: ordered list of visible message_ids backs the
    coordinator's record_consumed call."""
    await log.append(_user_event("ev-1", "first", ts=1000), session_id="s1")
    await log.append(_reply_event("ev-2", "second", ts=2000), session_id="s1")
    await log.append(_user_event("ev-3", "third", ts=3000), session_id="s1")
    ids = await log.list_visible_message_ids(session_id="s1")
    assert ids == ["ev-1", "ev-2", "ev-3"]


@pytest.mark.asyncio
async def test_list_visible_message_ids_excludes_redacted(log):
    """A redacted message must not appear in the visible-id list — the
    coordinator should not tag the new run as a consumer of a hidden row."""
    await log.append(_user_event("ev-1", "first", ts=1000), session_id="s1")
    await log.append(_user_event("ev-2", "secret", ts=2000), session_id="s1")
    redact = ConversationEvent(
        event_id="ev-r",
        event_type="message_redacted",
        timestamp_ms=3000,
        actor="system",
        content=None,
        redacts="ev-2",
    )
    await log.append(redact, session_id="s1")
    ids = await log.list_visible_message_ids(session_id="s1")
    # ev-2 is is_visible=0 after redact; the ev-r row itself is a redaction
    # marker so it never surfaces. Only ev-1 remains.
    assert ids == ["ev-1"]


@pytest.mark.asyncio
async def test_list_visible_message_ids_excludes_replaced(log):
    """A revised message's chain head is the new event; the original is
    skipped because its replaced_by_message_id is set."""
    await log.append(_user_event("ev-1", "first draft", ts=1000), session_id="s1")
    revision = ConversationEvent(
        event_id="ev-2",
        event_type="message_revised",
        timestamp_ms=2000,
        actor="u1",
        content=[ContentBlock(kind="text", text="revised")],
        revises="ev-1",
    )
    await log.append(revision, session_id="s1")
    ids = await log.list_visible_message_ids(session_id="s1")
    assert ids == ["ev-2"]


@pytest.mark.asyncio
async def test_list_visible_message_ids_returns_empty_for_unknown_session(log):
    ids = await log.list_visible_message_ids(session_id="missing")
    assert ids == []
