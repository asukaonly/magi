from __future__ import annotations

import contextlib

import pytest

from magi.chat import ChatSessionRecord, ChatStore, ChatTurnRecord
from magi.core.container import get_container


@contextlib.contextmanager
def _override(**bindings):
    container = get_container()
    providers = {key: getattr(container, key) for key in bindings}
    for key, value in bindings.items():
        providers[key].override(value)
    try:
        yield
    finally:
        for key in bindings:
            providers[key].reset_override()


async def _seed_turn(store: ChatStore, *, session_id: str = "session-1", turn_id: str = "turn-1") -> None:
    await store.upsert_session(
        ChatSessionRecord(
            session_id=session_id,
            user_id="user-1",
            title="",
            title_overridden=False,
            summary="",
            created_at_ms=100,
            updated_at_ms=100,
            last_message_at_ms=None,
            last_user_message_at_ms=None,
            last_message_preview="",
            last_user_message_preview="",
            message_count=0,
            archived_at_ms=None,
            deleted_at_ms=None,
        )
    )
    await store.upsert_turn(
        ChatTurnRecord(
            turn_id=turn_id,
            session_id=session_id,
            user_id="user-1",
            trace_id=None,
            orchestration_id=None,
            status="running",
            response_mode="final_only",
            execution_mode="orchestration",
            ux_plan_json="{}",
            created_at_ms=100,
            updated_at_ms=100,
            completed_at_ms=None,
            error_text=None,
        )
    )


@pytest.mark.asyncio
async def test_persist_plan_state_message_replaces_prior_plan_for_same_turn(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from magi.agent.control.chat_state_persister import persist_plan_state_message

    store = ChatStore(db_path=str(tmp_path / "chat.db"))
    await store.initialize()
    await _seed_turn(store)
    upserts: list[str] = []
    hidden: list[str] = []
    monkeypatch.setattr(
        "magi.agent.control.chat_state_persister.broadcast_chat_message_upsert",
        lambda **kwargs: upserts.append(str(kwargs["message_id"])) or None,
    )
    monkeypatch.setattr(
        "magi.agent.control.chat_state_persister.broadcast_chat_message_hidden",
        lambda **kwargs: hidden.append(str(kwargs["message_id"])) or None,
    )

    async def _noop_upsert(**kwargs):
        upserts.append(str(kwargs["message_id"]))

    async def _noop_hidden(**kwargs):
        hidden.append(str(kwargs["message_id"]))

    monkeypatch.setattr(
        "magi.agent.control.chat_state_persister.broadcast_chat_message_upsert",
        _noop_upsert,
    )
    monkeypatch.setattr(
        "magi.agent.control.chat_state_persister.broadcast_chat_message_hidden",
        _noop_hidden,
    )

    with _override(chat_store=store):
        first_id = await persist_plan_state_message(
            session_id="session-1",
            user_id="user-1",
            turn_id="turn-1",
            state={"active": True, "plan_text": None, "entered_at": 1.0},
        )
        second_id = await persist_plan_state_message(
            session_id="session-1",
            user_id="user-1",
            turn_id="turn-1",
            state={"active": False, "plan_text": "1. Inspect\n2. Ship", "entered_at": 1.0},
        )

    messages = await store.list_messages(session_id="session-1")
    assert first_id is not None and second_id is not None
    assert [message.message_kind for message in messages] == ["plan_state", "plan_state"]
    assert messages[0].replaced_by_message_id == second_id
    assert messages[1].replaces_message_id == first_id
    assert upserts == [first_id, second_id]
    assert hidden == [first_id]

    await store.shutdown()


@pytest.mark.asyncio
async def test_persist_todo_state_message_hides_message_when_list_clears(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from magi.agent.control.chat_state_persister import persist_todo_state_message

    store = ChatStore(db_path=str(tmp_path / "chat.db"))
    await store.initialize()
    await _seed_turn(store)
    upserts: list[str] = []
    hidden: list[str] = []

    async def _noop_upsert(**kwargs):
        upserts.append(str(kwargs["message_id"]))

    async def _noop_hidden(**kwargs):
        hidden.append(str(kwargs["message_id"]))

    monkeypatch.setattr(
        "magi.agent.control.chat_state_persister.broadcast_chat_message_upsert",
        _noop_upsert,
    )
    monkeypatch.setattr(
        "magi.agent.control.chat_state_persister.broadcast_chat_message_hidden",
        _noop_hidden,
    )

    with _override(chat_store=store):
        message_id = await persist_todo_state_message(
            session_id="session-1",
            user_id="user-1",
            turn_id="turn-1",
            items=[
                {
                    "id": "todo-1",
                    "content": "Inspect runtime drift",
                    "status": "in_progress",
                    "created_at_ms": 1,
                    "updated_at_ms": 2,
                }
            ],
        )
        cleared_id = await persist_todo_state_message(
            session_id="session-1",
            user_id="user-1",
            turn_id="turn-1",
            items=[],
        )

    messages = await store.list_messages(session_id="session-1")
    assert message_id is not None
    assert cleared_id is None
    assert len(messages) == 1
    assert messages[0].message_kind == "todo_state"
    assert messages[0].is_visible is False
    assert upserts == [message_id]
    assert hidden == [message_id]

    await store.shutdown()


@pytest.mark.asyncio
async def test_persist_todo_state_message_noops_when_payload_unchanged(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from magi.agent.control.chat_state_persister import persist_todo_state_message

    store = ChatStore(db_path=str(tmp_path / "chat.db"))
    await store.initialize()
    await _seed_turn(store)
    upserts: list[str] = []
    hidden: list[str] = []

    async def _noop_upsert(**kwargs):
        upserts.append(str(kwargs["message_id"]))

    async def _noop_hidden(**kwargs):
        hidden.append(str(kwargs["message_id"]))

    monkeypatch.setattr(
        "magi.agent.control.chat_state_persister.broadcast_chat_message_upsert",
        _noop_upsert,
    )
    monkeypatch.setattr(
        "magi.agent.control.chat_state_persister.broadcast_chat_message_hidden",
        _noop_hidden,
    )

    items = [
        {
            "id": "todo-1",
            "content": "Inspect runtime drift",
            "status": "in_progress",
            "created_at_ms": 1,
            "updated_at_ms": 2,
        }
    ]

    with _override(chat_store=store):
        first_id = await persist_todo_state_message(
            session_id="session-1",
            user_id="user-1",
            turn_id="turn-1",
            items=items,
            orchestration_id="orch-1",
        )
        second_id = await persist_todo_state_message(
            session_id="session-1",
            user_id="user-1",
            turn_id="turn-1",
            items=items,
            orchestration_id="orch-1",
        )

    messages = await store.list_messages(session_id="session-1")
    assert first_id is not None
    assert second_id == first_id
    assert len(messages) == 1
    assert messages[0].message_kind == "todo_state"
    assert messages[0].is_visible is True
    assert upserts == [first_id]
    assert hidden == []

    await store.shutdown()