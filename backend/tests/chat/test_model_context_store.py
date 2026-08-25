from __future__ import annotations

import sqlite3

import pytest

from magi.chat.model_context import (
    ModelContextItem,
    ModelContextItemKind,
    ModelContextRevisionConflictError,
    ModelContextScope,
)
from magi.chat.store import ChatStore
from magi.chat.contracts import ChatSessionRecord


def _item(
    role: str,
    content: str,
    *,
    kind: ModelContextItemKind | None = None,
    source: str = "test",
) -> ModelContextItem:
    return ModelContextItem.from_prompt_message(
        {"role": role, "content": content},
        source=source,
        kind=kind,
        scope=ModelContextScope.SESSION,
    )


async def _create_session(store: ChatStore, session_id: str = "session-1") -> None:
    await store.upsert_session(
        ChatSessionRecord(
            session_id=session_id,
            user_id="user-1",
            title="Test",
            title_overridden=False,
            summary="",
            created_at_ms=1,
            updated_at_ms=1,
            last_message_at_ms=None,
            last_user_message_at_ms=None,
            last_message_preview="",
            last_user_message_preview="",
            message_count=0,
            archived_at_ms=None,
            deleted_at_ms=None,
        )
    )


@pytest.mark.asyncio
async def test_append_and_load_model_context(tmp_path) -> None:
    store = ChatStore(db_path=str(tmp_path / "chat.db"))
    await _create_session(store)

    snapshot = await store.append_model_context(
        session_id="session-1",
        items=(
            _item(
                "user",
                "<turn_context>snapshot</turn_context>",
                kind=ModelContextItemKind.TURN_CONTEXT,
            ),
            _item("user", "hello"),
        ),
        expected_revision=0,
        turn_id="turn-1",
        run_id="run-1",
        step_index=0,
    )

    assert snapshot.revision == 1
    assert [item.kind for item in snapshot.items] == [
        ModelContextItemKind.TURN_CONTEXT,
        ModelContextItemKind.USER_MESSAGE,
    ]
    assert snapshot.to_prompt_messages() == [
        {"role": "user", "content": "<turn_context>snapshot</turn_context>"},
        {"role": "user", "content": "hello"},
    ]
    assert {event.turn_id for event in snapshot.events} == {"turn-1"}
    assert {event.run_id for event in snapshot.events} == {"run-1"}


@pytest.mark.asyncio
async def test_sync_appends_suffix_and_replaces_changed_surface(tmp_path) -> None:
    store = ChatStore(db_path=str(tmp_path / "chat.db"))
    await _create_session(store)
    first = await store.append_model_context(
        session_id="session-1",
        items=(_item("user", "hello"),),
        expected_revision=0,
    )

    unchanged = await store.sync_model_context_surface(
        session_id="session-1",
        items=first.items,
        expected_revision=first.revision,
    )
    assert unchanged.revision == 1

    appended = await store.sync_model_context_surface(
        session_id="session-1",
        items=(*first.items, _item("assistant", "hi")),
        expected_revision=first.revision,
        turn_id="turn-1",
        run_id="run-1",
        step_index=1,
    )
    assert appended.revision == 2
    assert [event.operation for event in appended.events] == ["append", "append"]

    replacement_item = _item(
        "user",
        "[context compacted]\nsummary",
        kind=ModelContextItemKind.COMPACTION_SUMMARY,
        source="context_compactor",
    )
    replaced = await store.sync_model_context_surface(
        session_id="session-1",
        items=(replacement_item, _item("assistant", "hi")),
        expected_revision=appended.revision,
        turn_id="turn-1",
        run_id="run-1",
        step_index=2,
    )
    assert replaced.revision == 3
    assert [item.kind for item in replaced.items] == [
        ModelContextItemKind.COMPACTION_SUMMARY,
        ModelContextItemKind.ASSISTANT_MESSAGE,
    ]
    assert all(event.operation == "surface_replace" for event in replaced.events)

    with sqlite3.connect(store.db_path) as conn:
        event_count = conn.execute(
            "SELECT COUNT(*) FROM chat_model_context_events"
        ).fetchone()[0]
    assert event_count == 4


@pytest.mark.asyncio
async def test_model_context_revision_conflict_is_rejected(tmp_path) -> None:
    store = ChatStore(db_path=str(tmp_path / "chat.db"))
    await _create_session(store)
    await store.append_model_context(
        session_id="session-1",
        items=(_item("user", "hello"),),
        expected_revision=0,
    )

    with pytest.raises(ModelContextRevisionConflictError):
        await store.append_model_context(
            session_id="session-1",
            items=(_item("assistant", "stale"),),
            expected_revision=0,
        )


@pytest.mark.asyncio
async def test_reset_physically_removes_model_context(tmp_path) -> None:
    store = ChatStore(db_path=str(tmp_path / "chat.db"))
    await _create_session(store)
    await store.append_model_context(
        session_id="session-1",
        items=(_item("user", "hello"),),
    )

    await store.reset_model_context(session_id="session-1")

    snapshot = await store.load_model_context(session_id="session-1")
    assert snapshot.revision == 0
    assert snapshot.events == ()


@pytest.mark.asyncio
async def test_cleared_session_rejects_late_model_context_write(tmp_path) -> None:
    store = ChatStore(db_path=str(tmp_path / "chat.db"))
    await _create_session(store)
    with sqlite3.connect(store.db_path) as conn:
        conn.execute(
            "INSERT INTO chat_cleared_session_scopes(session_id, cleared_at_ms) VALUES (?, ?)",
            ("session-1", 10),
        )
        conn.commit()

    with pytest.raises(sqlite3.IntegrityError):
        await store.append_model_context(
            session_id="session-1",
            items=(_item("user", "late"),),
        )
