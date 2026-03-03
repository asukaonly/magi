import json
import sqlite3
import sys
from pathlib import Path

BACKEND_SRC = Path(__file__).resolve().parents[1] / "src"
if str(BACKEND_SRC) not in sys.path:
    sys.path.insert(0, str(BACKEND_SRC))

from magi.api.routers import messages
from magi.api.services.chat_read_service import ChatReadService


def _init_event_store(db_path: Path) -> None:
    conn = sqlite3.connect(str(db_path))
    cur = conn.cursor()
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS event_store (
            type TEXT NOT NULL,
            data TEXT NOT NULL,
            timestamp REAL NOT NULL
        )
        """
    )
    conn.commit()
    conn.close()


def _insert_event(db_path: Path, event_type: str, data: dict, timestamp: float) -> None:
    conn = sqlite3.connect(str(db_path))
    cur = conn.cursor()
    cur.execute(
        "INSERT INTO event_store (type, data, timestamp) VALUES (?, ?, ?)",
        (event_type, json.dumps(data), timestamp),
    )
    conn.commit()
    conn.close()


def _build_service(tmp_path: Path) -> ChatReadService:
    service = ChatReadService()
    service._events_db_path = tmp_path / "events.sqlite3"
    service._session_state_file = tmp_path / "chat_sessions.json"
    return service


def test_list_sessions_returns_current_session_when_no_history(tmp_path):
    service = _build_service(tmp_path)
    service._save_session_mapping({"u1": "s-current"})

    sessions = service.list_sessions("u1", limit=10)

    assert len(sessions) == 1
    assert sessions[0]["session_id"] == "s-current"
    assert sessions[0]["message_count"] == 0


def test_list_sessions_aggregates_and_sorts(tmp_path):
    service = _build_service(tmp_path)
    _init_event_store(service._events_db_path)

    _insert_event(
        service._events_db_path,
        "USER_INPUT",
        {"user_id": "u1", "session_id": "s1", "message": "hello from session one"},
        1000,
    )
    _insert_event(
        service._events_db_path,
        "AI_RESPONSE",
        {"user_id": "u1", "session_id": "s1", "response": "response one"},
        1010,
    )
    _insert_event(
        service._events_db_path,
        "USER_INPUT",
        {"user_id": "u1", "session_id": "s2", "message": "hello from session two"},
        2000,
    )
    _insert_event(
        service._events_db_path,
        "AI_RESPONSE",
        {"user_id": "u1", "session_id": "s2", "response": "response two"},
        2010,
    )
    _insert_event(
        service._events_db_path,
        "USER_INPUT",
        {"user_id": "u2", "session_id": "s-other", "message": "ignore me"},
        5000,
    )

    sessions = service.list_sessions("u1", limit=10)

    assert [item["session_id"] for item in sessions] == ["s2", "s1"]
    assert sessions[0]["message_count"] == 2
    assert sessions[1]["message_count"] == 2
    assert sessions[0]["last_timestamp"] == 2010
    assert sessions[0]["title"] == "hello from session two"


def test_list_sessions_respects_limit(tmp_path):
    service = _build_service(tmp_path)
    _init_event_store(service._events_db_path)

    for index in range(5):
        _insert_event(
            service._events_db_path,
            "USER_INPUT",
            {
                "user_id": "u1",
                "session_id": f"s{index}",
                "message": f"session {index}",
            },
            1000 + index,
        )

    sessions = service.list_sessions("u1", limit=2)
    assert len(sessions) == 2


def test_list_sessions_router_response(monkeypatch):
    class _FakeReadService:
        def list_sessions(self, user_id: str, limit: int = 30):
            assert user_id == "u1"
            assert limit == 5
            return [
                {
                    "session_id": "s1",
                    "title": "Test",
                    "last_message_preview": "Hi",
                    "last_timestamp": 123,
                    "message_count": 2,
                }
            ]

        def get_current_session_id(self, user_id: str):
            assert user_id == "u1"
            return "s1"

    monkeypatch.setattr(messages, "get_chat_read_service", lambda: _FakeReadService())

    result = __import__("asyncio").run(messages.list_sessions(user_id="u1", limit=5))
    assert result["user_id"] == "u1"
    assert result["current_session_id"] == "s1"
    assert result["count"] == 1
