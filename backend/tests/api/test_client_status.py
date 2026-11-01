"""Exact product receipts through the allowlisted public router."""

import json
import sqlite3

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from magi.api.routers import messages, messages_status
from magi.api.routes import _PUBLIC_ROUTE_METHODS, _build_public_router
from magi.control.session_store import ControlSessionStore
from magi.db.identities import identity_key
from test_messages_sessions import _build_service, _init_chat_session_store, _insert_session, _insert_chat_message, _insert_chat_turn


@pytest.fixture
def setup(tmp_path, monkeypatch):
    reader = _build_service(tmp_path)
    path = reader.repository.database.path
    _init_chat_session_store(path)
    _insert_session(path, session_id="chat", user_id="local_user")
    monkeypatch.setattr(messages_status, "require_chat_read_service", lambda: reader)
    app = FastAPI()
    app.include_router(_build_public_router(messages.user_messages_router, _PUBLIC_ROUTE_METHODS["messages"]), prefix="/api/messages")
    with TestClient(app) as client:
        yield reader, client, path
    reader.close()


def anchor(path, turn_id="turn", **fields):
    _insert_chat_message(path, message_id=turn_id, session_id="chat", user_id="local_user", turn_id=turn_id,
                         role="user", message_kind="user_text", content_text="Hello", **fields)


def test_receipt_uses_exact_anchor_and_refuses_retired_turns(setup):
    reader, client, path = setup
    body = dict(kind="turn", session_id="chat", turn_id="turn")
    assert client.post("/api/messages/confirmation", json=body).json()["safe_to_retry"] is True
    anchor(path)
    for i in range(60):
        anchor(path, f"later-{i}", created_at_ms=i + 1)
    assert client.post("/api/messages/confirmation", json=body).json() == {
        "session_id": "chat", "identity": "turn", "status": "confirmed", "safe_to_retry": False,
    }
    snapshot = client.get("/api/messages/session/chat/turn/turn").json()
    assert snapshot["state"] == "queued" and snapshot["terminal"] is False
    with sqlite3.connect(path) as db:
        db.execute("INSERT INTO chat_retired_turns(turn_key,retired_at_ms) VALUES (?,1)", (identity_key("chat-turn", "turn"),))
    assert client.post("/api/messages/confirmation", json=body).json()["status"] == "concluded"
    assert client.get("/api/messages/session/foreign/turn/turn").json()["can_resubmit"] is False


def test_execution_completion_does_not_skip_incomplete_or_future_bubbles(setup):
    _, client, path = setup
    anchor(path)
    _insert_chat_turn(path, turn_id="turn", session_id="chat", user_id="local_user", status="completed")
    def segment(index):
        _insert_chat_message(path, message_id=f"bubble-{index}", session_id="chat", user_id="local_user", turn_id="turn",
            role="assistant", message_kind="assistant_rhythm_segment", content_text="answer", created_at_ms=4000 + index,
            payload_json=json.dumps({"rhythm": {"segment_index": index, "segment_count": 2}}))
    segment(0)
    incomplete = client.get("/api/messages/session/chat/turn/turn").json()
    assert incomplete["terminal"] is True and incomplete["response_complete"] is False
    segment(1)
    complete = client.get("/api/messages/session/chat/turn/turn").json()
    assert complete["response_complete"] is True and complete["presentation_ends_at_ms"] == 4001


def test_unavailable_storage_never_means_safe_to_retry(setup, monkeypatch):
    _, client, _ = setup
    def unavailable():
        raise RuntimeError("offline")
    monkeypatch.setattr(messages_status, "require_chat_read_service", unavailable)
    assert client.post("/api/messages/confirmation", json=dict(kind="turn", session_id="chat", turn_id="turn")).status_code == 503


@pytest.mark.parametrize("body", [
    {"kind": "turn", "session_id": "chat"},
    {"kind": "turn", "session_id": "chat", "turn_id": "t", "answer": "x"},
    {"kind": "ask_response", "session_id": "chat", "request_id": "a"},
])
def test_confirmation_rejects_invalid_identity(setup, body):
    assert setup[1].post("/api/messages/confirmation", json=body).status_code == 422


@pytest.mark.asyncio
async def test_answer_receipt_survives_a_new_question_and_restart(tmp_path, ensure_db_schema):
    path = tmp_path / "runtime.db"
    ensure_db_schema("runtime_trace", path)
    store = ControlSessionStore(db_path=path)
    await store.initialize()
    await store.open_ask("chat", request_id="old", question="Choose")
    assert await store.confirm_answer("chat", "old", "yes") == ("absent", True)
    assert await store.accept_ask_answer("old", "yes")
    await store.open_ask("chat", request_id="new", question="Again")
    restarted = ControlSessionStore(db_path=path)
    await restarted.initialize()
    assert await restarted.confirm_answer("chat", "old", "yes") == ("confirmed", False)
    assert await restarted.confirm_answer("chat", "old", "no") == ("concluded", False)
    assert await restarted.confirm_answer("other", "old", "yes") == ("concluded", False)
    assert await restarted.confirm_answer("chat", "new", "yes") == ("concluded", False)
