"""Public chat page contracts and bounded snapshot reads."""

from __future__ import annotations

import sqlite3
from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from magi.api.routes import _PUBLIC_ROUTE_METHODS, _build_public_router
from magi.api.routers import messages, messages_content, messages_sessions
from magi.chat.read import pagination
from magi.chat.read.pagination import InvalidPageCursor, StalePageCursor
from test_messages_sessions import (
    _build_service,
    _init_chat_session_store,
    _insert_session,
    _insert_chat_message,
    _insert_chat_turn,
)


@pytest.fixture
def reader(tmp_path):
    service = _build_service(tmp_path)
    _init_chat_session_store(service._chat_db_path)
    _insert_session(
        service._chat_db_path, session_id="chat", user_id="user", created_at=1, updated_at=1
    )
    yield service
    service.close()


@pytest.fixture
def client(reader, monkeypatch):
    monkeypatch.setattr(messages_content, "require_chat_read_service", lambda: reader)
    monkeypatch.setattr(messages_sessions, "require_chat_read_service", lambda: reader)
    app = FastAPI()
    app.include_router(
        _build_public_router(messages.user_messages_router, _PUBLIC_ROUTE_METHODS["messages"]),
        prefix="/api/messages",
    )
    with TestClient(app) as client:
        yield client


def seed_messages(reader, count, *, turn_id=None, start=0):
    with sqlite3.connect(reader._chat_db_path) as conn:
        conn.executemany(
            """INSERT INTO chat_messages(message_id,session_id,turn_id,user_id,role,message_kind,
               content_text,created_at_ms,sequence_no) VALUES (?,'chat',?,'user','user','user_text',?,1,1)""",
            [(f"message-{i:04}", turn_id, f"Message {i}") for i in range(start, start + count)],
        )


def test_public_history_pages_return_every_message_and_bound_queries(reader, client, monkeypatch):
    seed_messages(reader, 205)
    monkeypatch.setattr(
        type(reader),
        "_query_chat_message_rows",
        lambda *_a, **_k: pytest.fail("Unbounded message query"),
    )
    monkeypatch.setattr(
        type(reader), "_query_turn_rows", lambda *_a, **_k: pytest.fail("Unbounded turn query")
    )
    before = None
    ids = []
    pages = 0
    while True:
        params = {"user_id": "user", "session_id": "chat", "limit": 50}
        if before:
            params["before"] = before
        response = client.get("/api/messages/history", params=params)
        assert response.status_code == 200, response.text
        data = response.json()
        assert data["count"] <= 50
        assert data["not_modified"] is False
        assert [m["message_id"] for m in data["messages"]] == sorted(
            m["message_id"] for m in data["messages"]
        )
        ids.extend(m["message_id"] for m in data["messages"])
        pages += 1
        if not data["has_more"]:
            assert data["next_before"] is None
            break
        before = data["next_before"]
    assert pages == 5
    assert len(set(ids)) == len(ids) == 205
    assert set(ids) == {f"message-{i:04}" for i in range(205)}


def test_session_pages_return_all_sessions_and_reject_stale_or_foreign_cursor(reader, client):
    for index in range(205):
        _insert_session(
            reader._chat_db_path,
            session_id=f"session-{index:04}",
            user_id="user",
            created_at=1,
            updated_at=1,
        )
    first = client.get("/api/messages/sessions", params={"user_id": "user", "limit": 50}).json()
    revision = first["revision"]
    unchanged = client.get(
        "/api/messages/sessions", params={"user_id": "user", "known_revision": revision}
    ).json()
    assert unchanged["not_modified"] is True
    assert unchanged["sessions"] == []
    ids = [s["session_id"] for s in first["sessions"]]
    page = first
    while page["has_more"]:
        page = client.get(
            "/api/messages/sessions",
            params={"user_id": "user", "limit": 50, "before": page["next_before"]},
        ).json()
        ids.extend(s["session_id"] for s in page["sessions"])
    assert len(ids) == len(set(ids)) == 206
    assert ids == sorted(ids, reverse=True)
    foreign = client.get(
        "/api/messages/sessions", params={"user_id": "other", "before": first["next_before"]}
    )
    assert foreign.status_code == 400
    with sqlite3.connect(reader._chat_db_path) as conn:
        conn.execute("DELETE FROM chat_sessions WHERE session_id='session-0000'")
    stale = client.get(
        "/api/messages/sessions", params={"user_id": "user", "before": first["next_before"]}
    )
    assert stale.status_code == 409
    assert stale.json()["detail"]["code"] == "stale_page_cursor"
    refreshed = client.get(
        "/api/messages/sessions", params={"user_id": "user", "known_revision": revision}
    ).json()
    assert refreshed["revision"] != revision
    assert refreshed["not_modified"] is False


def test_history_revision_is_per_session_and_invalidates_all_read_mutations(reader, monkeypatch):
    seed_messages(reader, 3)
    first = reader.get_history_page("user", "chat", 1)
    _insert_session(
        reader._chat_db_path, session_id="another", user_id="user", created_at=2, updated_at=2
    )
    _insert_chat_message(
        reader._chat_db_path,
        message_id="other",
        session_id="another",
        user_id="user",
        role="user",
        message_kind="user_text",
        content_text="Other",
        created_at_ms=2,
    )
    assert (
        reader.get_history_page("user", "chat", 1, first["next_before"])["revision"]
        == first["revision"]
    )
    monkeypatch.setattr(
        reader,
        "_row_to_display_message",
        lambda *_a: pytest.fail("Conditional hit projected content"),
    )
    assert (
        reader.get_history_page("user", "chat", known_revision=first["revision"])["not_modified"]
        is True
    )
    with sqlite3.connect(reader._chat_db_path) as conn:
        conn.execute("UPDATE chat_messages SET label_json='{}' WHERE message_id='message-0000'")
    with pytest.raises(StalePageCursor):
        reader.get_history_page("user", "chat", 1, first["next_before"])
    with pytest.raises(InvalidPageCursor):
        reader.get_history_page("user", "another", 1, first["next_before"])


def test_exact_turn_lookup_keeps_user_anchor_beyond_last_page(reader):
    _insert_chat_turn(
        reader._chat_db_path,
        turn_id="turn",
        session_id="chat",
        user_id="user",
        status="completed",
        created_at_ms=1,
    )
    _insert_chat_message(
        reader._chat_db_path,
        message_id="accepted-user",
        session_id="chat",
        turn_id="turn",
        user_id="user",
        role="user",
        message_kind="user_text",
        content_text="Accepted",
        created_at_ms=1,
    )
    for i in range(55):
        _insert_chat_message(
            reader._chat_db_path,
            message_id=f"assistant-{i:03}",
            session_id="chat",
            turn_id="turn",
            user_id="user",
            role="assistant",
            message_kind="assistant_final",
            content_text="Reply",
            created_at_ms=2 + i,
        )
    seed_messages(reader, 210)
    page = reader.get_history_page("user", "chat", 10, turn_id="turn")
    assert page["count"] == 11
    assert page["messages"][0]["message_id"] == "accepted-user"
    assert page["messages"][0]["run_state"]["state"] == "completed"
    assert all(m["turn_id"] == "turn" for m in page["messages"])
    assert page["has_more"] is True
    with pytest.raises(InvalidPageCursor):
        reader.get_history_page("user", "chat", 10, page["next_before"])


def test_synthetic_status_appears_once_and_active_turns_bypass_conditional_hit(reader, monkeypatch):
    import magi.chat.read.history_operations as history_operations

    monkeypatch.setattr(
        history_operations,
        "_get_chat_trace_read_service",
        lambda: SimpleNamespace(
            get_trace_summary=lambda **_: {"headline": "Working", "trace_available": True}
        ),
    )
    _insert_chat_turn(
        reader._chat_db_path,
        turn_id="turn",
        session_id="chat",
        user_id="user",
        status="running",
        created_at_ms=1,
    )
    seed_messages(reader, 5, turn_id="turn")
    page = reader.get_history_page("user", "chat", 2)
    revision = page["revision"]
    statuses = sum(m["kind"] == "status" for m in page["messages"])
    while page["has_more"]:
        page = reader.get_history_page("user", "chat", 2, page["next_before"])
        statuses += sum(m["kind"] == "status" for m in page["messages"])
    assert statuses == 1
    assert reader.get_history_page("user", "chat", known_revision=revision)["not_modified"] is False


def test_revision_and_page_share_a_database_snapshot(reader, monkeypatch):
    seed_messages(reader, 2)
    original = pagination.read_revision
    wrote = False

    def mutate_after_revision(conn, user_id, scope):
        nonlocal wrote
        revision = original(conn, user_id, scope)
        if not wrote:
            wrote = True
            seed_messages(reader, 1, start=2)
        return revision

    monkeypatch.setattr(pagination, "read_revision", mutate_after_revision)
    first = reader.get_history_page("user", "chat")
    assert first["count"] == 2
    second = reader.get_history_page("user", "chat", known_revision=first["revision"])
    assert second["count"] == 3
    assert second["not_modified"] is False
    assert second["revision"] != first["revision"]


def test_read_failures_are_unavailable_not_empty_success(reader, client):
    with sqlite3.connect(reader._chat_db_path) as conn:
        conn.execute("DROP TABLE chat_read_revisions")
    assert (
        client.get(
            "/api/messages/history", params={"user_id": "user", "session_id": "chat"}
        ).status_code
        == 503
    )
    assert client.get("/api/messages/sessions", params={"user_id": "user"}).status_code == 503


def test_older_user_page_does_not_invent_status_when_assistant_is_on_a_newer_page(
    reader, monkeypatch
):
    import magi.chat.read.history_operations as history_operations

    monkeypatch.setattr(
        history_operations,
        "_get_chat_trace_read_service",
        lambda: SimpleNamespace(
            get_trace_summary=lambda **_: {"headline": "Completed", "trace_available": True}
        ),
    )
    _insert_chat_turn(
        reader._chat_db_path,
        turn_id="turn",
        session_id="chat",
        user_id="user",
        status="completed",
        created_at_ms=1,
    )
    _insert_chat_message(
        reader._chat_db_path,
        message_id="user",
        session_id="chat",
        turn_id="turn",
        user_id="user",
        role="user",
        message_kind="user_text",
        content_text="Question",
        created_at_ms=1,
    )
    _insert_chat_message(
        reader._chat_db_path,
        message_id="assistant",
        session_id="chat",
        turn_id="turn",
        user_id="user",
        role="assistant",
        message_kind="assistant_final",
        content_text="Answer",
        created_at_ms=2,
    )
    latest = reader.get_history_page("user", "chat", 1)
    older = reader.get_history_page("user", "chat", 1, latest["next_before"])
    assert [message["kind"] for message in latest["messages"]] == ["assistant"]
    assert [message["kind"] for message in older["messages"]] == ["user"]


def test_history_executes_a_bounded_keyset_query_and_skips_projection_on_unchanged_page(reader):
    seed_messages(reader, 205)
    statements = []
    reader._get_conn().set_trace_callback(statements.append)
    page = reader.get_history_page("user", "chat", 20)
    selected = [sql for sql in statements if "SELECT * FROM chat_messages" in sql]
    assert len(selected) == 1
    assert "LIMIT 21" in selected[0]
    assert page["count"] == 20
    statements.clear()
    unchanged = reader.get_history_page("user", "chat", known_revision=page["revision"])
    assert unchanged["not_modified"] is True
    assert not any("FROM chat_messages" in sql for sql in statements)


def test_public_single_session_lookup_recovers_selection_outside_first_page(reader, client):
    for index in range(55):
        _insert_session(
            reader._chat_db_path,
            session_id=f"newer-{index:03}",
            user_id="user",
            created_at=index + 2,
            updated_at=index + 2,
        )
    recent = client.get("/api/messages/sessions", params={"user_id": "user", "limit": 50}).json()
    assert "chat" not in {item["session_id"] for item in recent["sessions"]}
    response = client.get("/api/messages/session/chat", params={"user_id": "user"})
    assert response.status_code == 200
    assert response.json()["session_id"] == "chat"
    assert set(response.json()) == set(reader.get_session_summary("user", "chat").to_dict())
    assert client.get("/api/messages/session/chat", params={"user_id": "other"}).status_code == 404
    assert (
        client.get("/api/messages/session/missing", params={"user_id": "user"}).status_code == 404
    )
    with sqlite3.connect(reader._chat_db_path) as conn:
        conn.execute("UPDATE chat_sessions SET deleted_at_ms=1 WHERE session_id='chat'")
        conn.execute("UPDATE chat_sessions SET archived_at_ms=1 WHERE session_id='newer-000'")
    assert client.get("/api/messages/session/chat", params={"user_id": "user"}).status_code == 404
    assert (
        client.get("/api/messages/session/newer-000", params={"user_id": "user"}).status_code == 404
    )


def test_public_single_session_lookup_reports_storage_errors(reader, client):
    with sqlite3.connect(reader._chat_db_path) as conn:
        conn.execute("DROP TABLE chat_sessions")
    assert client.get("/api/messages/session/chat", params={"user_id": "user"}).status_code == 503
