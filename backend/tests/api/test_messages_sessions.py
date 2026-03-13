import json
import sqlite3
import sys
from pathlib import Path

BACKEND_SRC = Path(__file__).resolve().parents[1] / "src"
if str(BACKEND_SRC) not in sys.path:
    sys.path.insert(0, str(BACKEND_SRC))

from magi.api.routers import messages
from magi.api.services.chat_read_service import ChatReadService
from magi.api.services.chat_trace_read_service import ChatTraceReadService


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


def test_get_display_history_surfaces_trace_status_instead_of_worker_messages(tmp_path, monkeypatch):
    service = _build_service(tmp_path)
    trace_service = ChatTraceReadService()
    trace_service._events_db_path = service._events_db_path
    trace_service._orchestrations_path = tmp_path / "task_orchestrations.json"
    monkeypatch.setattr(
        "magi.api.services.chat_read_service.get_chat_trace_read_service",
        lambda: trace_service,
    )
    _init_event_store(service._events_db_path)

    _insert_event(
        service._events_db_path,
        "USER_INPUT",
        {"user_id": "u1", "session_id": "s1", "message": "start task", "turn_id": "turn_1"},
        1000,
    )
    _insert_event(
        service._events_db_path,
        "WORKER_AGENT_PROGRESS",
        {
            "user_id": "u1",
            "session_id": "s1",
            "turn_id": "turn_1",
            "worker_id": "worker_abc1234567",
            "worker_subagent_type": "Explore",
            "stage": "started",
            "description": "scan codebase",
        },
        1010,
    )
    _insert_event(
        service._events_db_path,
        "WORKER_AGENT_COMPLETED",
        {
            "user_id": "u1",
            "session_id": "s1",
            "turn_id": "turn_1",
            "worker_id": "worker_abc1234567",
            "worker_subagent_type": "Explore",
        },
        1020,
    )

    messages = service.get_display_history("u1", "s1", limit=20)

    assert [item["kind"] for item in messages] == ["user", "status"]
    assert messages[1]["turn_id"] == "turn_1"
    assert messages[1]["trace_available"] is True
    assert messages[1]["trace_summary"]["headline"] == "正在执行工具链"


def test_trace_summary_reads_tool_invoked_events(tmp_path, monkeypatch):
    service = _build_service(tmp_path)
    trace_service = ChatTraceReadService()
    trace_service._events_db_path = service._events_db_path
    trace_service._orchestrations_path = tmp_path / "task_orchestrations.json"
    monkeypatch.setattr(
        "magi.api.services.chat_read_service.get_chat_trace_read_service",
        lambda: trace_service,
    )
    _init_event_store(service._events_db_path)

    _insert_event(
        service._events_db_path,
        "USER_INPUT",
        {"user_id": "u1", "session_id": "s1", "message": "why", "turn_id": "turn_2"},
        2000,
    )
    _insert_event(
        service._events_db_path,
        "TOOL_INVOKED",
        {
            "user_id": "u1",
            "session_id": "s1",
            "turn_id": "turn_2",
            "tool_name": "grep",
            "tool_params": {"path": "/tmp/demo.py", "pattern": "qweather"},
            "result": "success",
            "execution_time_ms": 3.2,
        },
        2005,
    )
    _insert_event(
        service._events_db_path,
        "AI_RESPONSE",
        {"user_id": "u1", "session_id": "s1", "turn_id": "turn_2", "response": "answer"},
        2010,
    )

    messages = service.get_display_history("u1", "s1", limit=20)

    assert [item["kind"] for item in messages] == ["user", "assistant"]
    assert messages[1]["trace_available"] is True
    assert messages[1]["trace_summary"]["mode"] == "function_calling"

    snapshot = trace_service.get_trace_snapshot(user_id="u1", session_id="s1", turn_id="turn_2")

    assert snapshot is not None
    assert snapshot["summary"]["trace_available"] is True
    assert snapshot["root"]["children"][0]["children"][0]["label"] == "grep"
    assert snapshot["root"]["children"][0]["children"][0]["metadata"]["arguments"]["pattern"] == "qweather"


def test_trace_snapshot_groups_parallel_workers_and_tools(tmp_path):
    service = ChatTraceReadService()
    service._events_db_path = tmp_path / "events.sqlite3"
    service._orchestrations_path = tmp_path / "task_orchestrations.json"
    _init_event_store(service._events_db_path)

    service._orchestrations_path.write_text(
        json.dumps(
            {
                "orchestrations": {
                    "orch_1": {
                        "orchestration_id": "orch_1",
                        "user_id": "u1",
                        "session_id": "s1",
                        "root_user_message": "analyze repo",
                        "planner": "task_agent",
                        "turn_id": "turn_1",
                        "status": "running",
                        "allow_parallel": True,
                        "subtasks": [
                            {
                                "subtask_id": "sub_1",
                                "description": "scan backend",
                                "subagent_type": "Explore",
                                "prompt": "scan backend",
                                "parallel_group": "group_a",
                                "status": "running",
                                "worker_id": "worker_1",
                                "created_at": 1000,
                                "updated_at": 1015,
                            },
                            {
                                "subtask_id": "sub_2",
                                "description": "scan frontend",
                                "subagent_type": "Explore",
                                "prompt": "scan frontend",
                                "parallel_group": "group_a",
                                "status": "completed",
                                "worker_id": "worker_2",
                                "worker_result": {"summary": "frontend summary"},
                                "created_at": 1001,
                                "updated_at": 1020,
                            },
                        ],
                    }
                }
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )

    _insert_event(
        service._events_db_path,
        "USER_INPUT",
        {"user_id": "u1", "session_id": "s1", "message": "analyze repo", "turn_id": "turn_1"},
        1000,
    )
    _insert_event(
        service._events_db_path,
        "WORKER_AGENT_PROGRESS",
        {
            "user_id": "u1",
            "session_id": "s1",
            "turn_id": "turn_1",
            "orchestration_id": "orch_1",
            "subtask_id": "sub_1",
            "worker_id": "worker_1",
            "worker_description": "scan backend",
            "worker_subagent_type": "Explore",
            "stage": "tool_result",
            "tool_name": "grep",
            "success": True,
            "result_preview": "match count: 3",
            "timestamp": 1015,
        },
        1015,
    )
    _insert_event(
        service._events_db_path,
        "AI_RESPONSE",
        {"user_id": "u1", "session_id": "s1", "turn_id": "turn_1", "response": "final answer"},
        1030,
    )

    snapshot = service.get_trace_snapshot(user_id="u1", session_id="s1", turn_id="turn_1")

    assert snapshot is not None
    assert snapshot["summary"]["trace_available"] is True
    assert snapshot["summary"]["mode"] == "orchestration"
    assert snapshot["summary"]["status"] == "completed"
    planning = snapshot["root"]["children"][0]
    assert planning["kind"] == "planning"
    assert planning["status"] == "completed"
    group = planning["children"][0]
    assert group["kind"] == "parallel_group"
    assert group["status"] == "completed"
    worker = group["children"][0]
    assert worker["kind"] == "worker"
    assert worker["children"][0]["label"] == "grep"


def test_trace_summary_counts_planning_as_active_before_workers_exist(tmp_path):
    service = ChatTraceReadService()
    service._events_db_path = tmp_path / "events.sqlite3"
    service._orchestrations_path = tmp_path / "task_orchestrations.json"
    _init_event_store(service._events_db_path)

    service._orchestrations_path.write_text(
        json.dumps(
            {
                "orchestrations": {
                    "orch_plan": {
                        "orchestration_id": "orch_plan",
                        "user_id": "u1",
                        "session_id": "s1",
                        "turn_id": "turn_plan",
                        "status": "running",
                        "planner": "task_agent",
                        "allow_parallel": True,
                        "subtasks": [],
                    }
                }
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )

    _insert_event(
        service._events_db_path,
        "USER_INPUT",
        {"user_id": "u1", "session_id": "s1", "message": "plan this", "turn_id": "turn_plan"},
        1000,
    )
    _insert_event(
        service._events_db_path,
        "WORKER_AGENT_PROGRESS",
        {
            "user_id": "u1",
            "session_id": "s1",
            "turn_id": "turn_plan",
            "orchestration_id": "orch_plan",
            "stage": "planning",
        },
        1005,
    )

    summary = service.get_trace_summary(user_id="u1", session_id="s1", turn_id="turn_plan")

    assert summary is not None
    assert summary["headline"] == "正在编排任务"
    assert summary["active_steps"] == 1
    assert summary["completed_steps"] == 0
