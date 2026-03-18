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

FACT_EVENTS_TABLE = "fact_events"
RUNTIME_OBSERVATIONS_TABLE = "runtime_observations"


def _init_event_store(db_path: Path) -> None:
    conn = sqlite3.connect(str(db_path))
    cur = conn.cursor()
    for table in (FACT_EVENTS_TABLE, RUNTIME_OBSERVATIONS_TABLE):
        cur.execute(
            f"""
            CREATE TABLE IF NOT EXISTS {table} (
                event_id TEXT PRIMARY KEY,
                event_type TEXT NOT NULL,
                structured_payload TEXT NOT NULL,
                timestamp REAL NOT NULL,
                user_id TEXT,
                session_id TEXT,
                deleted_at REAL
            )
            """
        )
        cur.execute(f"CREATE INDEX IF NOT EXISTS idx_{table}_user ON {table}(user_id)")
        cur.execute(f"CREATE INDEX IF NOT EXISTS idx_{table}_session ON {table}(session_id)")
    conn.commit()
    conn.close()


def _insert_event(db_path: Path, event_type: str, data: dict, timestamp: float) -> None:
    target_table = FACT_EVENTS_TABLE if event_type in {"UserMessage", "AIResponse"} else RUNTIME_OBSERVATIONS_TABLE
    conn = sqlite3.connect(str(db_path))
    cur = conn.cursor()
    cur.execute(
        f"INSERT INTO {target_table} (event_id, event_type, structured_payload, timestamp, user_id, session_id, deleted_at) VALUES (?, ?, ?, ?, ?, ?, NULL)",
        (
            f"{event_type}-{int(timestamp * 1000)}",
            event_type,
            json.dumps(data),
            timestamp,
            data.get("user_id"),
            data.get("session_id"),
        ),
    )
    conn.commit()
    conn.close()


def _build_service(tmp_path: Path) -> ChatReadService:
    service = ChatReadService()
    service._l1_db_path = tmp_path / "events.sqlite3"
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
    _init_event_store(service._l1_db_path)

    _insert_event(
        service._l1_db_path,
        "UserMessage",
        {"user_id": "u1", "session_id": "s1", "message": "hello from session one"},
        1000,
    )
    _insert_event(
        service._l1_db_path,
        "AIResponse",
        {"user_id": "u1", "session_id": "s1", "response": "response one"},
        1010,
    )
    _insert_event(
        service._l1_db_path,
        "UserMessage",
        {"user_id": "u1", "session_id": "s2", "message": "hello from session two"},
        2000,
    )
    _insert_event(
        service._l1_db_path,
        "AIResponse",
        {"user_id": "u1", "session_id": "s2", "response": "response two"},
        2010,
    )
    _insert_event(
        service._l1_db_path,
        "UserMessage",
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
    _init_event_store(service._l1_db_path)

    for index in range(5):
        _insert_event(
            service._l1_db_path,
            "UserMessage",
            {
                "user_id": "u1",
                "session_id": f"s{index}",
                "message": f"session {index}",
            },
            1000 + index,
        )

    sessions = service.list_sessions("u1", limit=2)
    assert len(sessions) == 2


def test_rename_session_persists_custom_title(tmp_path):
    service = _build_service(tmp_path)
    _init_event_store(service._l1_db_path)
    _insert_event(
        service._l1_db_path,
        "UserMessage",
        {"user_id": "u1", "session_id": "s1", "message": "原始标题"},
        1000,
    )

    service.rename_session("u1", "s1", "新的会话名")

    renamed = service.list_sessions("u1", limit=10)

    assert renamed[0]["session_id"] == "s1"
    assert renamed[0]["title"] == "新的会话名"

    reloaded = _build_service(tmp_path)
    reloaded_sessions = reloaded.list_sessions("u1", limit=10)
    assert reloaded_sessions[0]["title"] == "新的会话名"


def test_delete_session_removes_events_and_rotates_current_session(tmp_path):
    service = _build_service(tmp_path)
    _init_event_store(service._l1_db_path)
    service._save_session_mapping({"u1": "s2"})
    _insert_event(
        service._l1_db_path,
        "UserMessage",
        {"user_id": "u1", "session_id": "s1", "message": "保留会话"},
        1000,
    )
    _insert_event(
        service._l1_db_path,
        "UserMessage",
        {"user_id": "u1", "session_id": "s2", "message": "删除会话"},
        2000,
    )
    _insert_event(
        service._l1_db_path,
        "AIResponse",
        {"user_id": "u1", "session_id": "s2", "response": "需要一起删掉"},
        2010,
    )

    next_session_id = service.delete_session("u1", "s2")

    remaining = service.list_sessions("u1", limit=10)
    assert [item["session_id"] for item in remaining] == ["s1"]
    assert next_session_id == "s1"
    assert service.get_current_session_id("u1") == "s1"

    history = service.get_conversation_history("u1", "s2", limit=20)
    assert history == []


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


def test_rename_session_router_response(monkeypatch):
    class _FakeReadService:
        def rename_session(self, user_id: str, session_id: str, title: str):
            assert user_id == "u1"
            assert session_id == "s1"
            assert title == "Renamed"
            return {
                "session_id": "s1",
                "title": "Renamed",
            }

    monkeypatch.setattr(messages, "get_chat_read_service", lambda: _FakeReadService())

    result = __import__("asyncio").run(
        messages.rename_session(
            session_id="s1",
            request=messages.RenameSessionRequest(user_id="u1", title="Renamed"),
        )
    )

    assert result["success"] is True
    assert result["session"]["title"] == "Renamed"


def test_delete_session_router_response(monkeypatch):
    class _FakeReadService:
        def delete_session(self, user_id: str, session_id: str):
            assert user_id == "u1"
            assert session_id == "s1"
            return "s-next"

    monkeypatch.setattr(messages, "get_chat_read_service", lambda: _FakeReadService())

    result = __import__("asyncio").run(messages.delete_session(session_id="s1", user_id="u1"))

    assert result["success"] is True
    assert result["current_session_id"] == "s-next"


def test_get_display_history_surfaces_trace_status_instead_of_worker_messages(tmp_path, monkeypatch):
    service = _build_service(tmp_path)
    trace_service = ChatTraceReadService()
    trace_service._l1_db_path = service._l1_db_path
    trace_service._orchestrations_path = tmp_path / "task_orchestrations.json"
    monkeypatch.setattr(
        "magi.api.services.chat_read_service.get_chat_trace_read_service",
        lambda: trace_service,
    )
    _init_event_store(service._l1_db_path)

    _insert_event(
        service._l1_db_path,
        "UserMessage",
        {"user_id": "u1", "session_id": "s1", "message": "start task", "turn_id": "turn_1"},
        1000,
    )
    _insert_event(
        service._l1_db_path,
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
        service._l1_db_path,
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
    assert messages[1]["trace_summary"]["headline"] == "Running tool chain"


def test_trace_summary_reads_tool_invoked_events(tmp_path, monkeypatch):
    service = _build_service(tmp_path)
    trace_service = ChatTraceReadService()
    trace_service._l1_db_path = service._l1_db_path
    trace_service._orchestrations_path = tmp_path / "task_orchestrations.json"
    monkeypatch.setattr(
        "magi.api.services.chat_read_service.get_chat_trace_read_service",
        lambda: trace_service,
    )
    _init_event_store(service._l1_db_path)

    _insert_event(
        service._l1_db_path,
        "UserMessage",
        {"user_id": "u1", "session_id": "s1", "message": "why", "turn_id": "turn_2"},
        2000,
    )
    _insert_event(
        service._l1_db_path,
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
        service._l1_db_path,
        "AIResponse",
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
    service._l1_db_path = tmp_path / "events.sqlite3"
    service._orchestrations_path = tmp_path / "task_orchestrations.json"
    _init_event_store(service._l1_db_path)

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
        service._l1_db_path,
        "UserMessage",
        {"user_id": "u1", "session_id": "s1", "message": "analyze repo", "turn_id": "turn_1"},
        1000,
    )
    _insert_event(
        service._l1_db_path,
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
        service._l1_db_path,
        "AIResponse",
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
    service._l1_db_path = tmp_path / "events.sqlite3"
    service._orchestrations_path = tmp_path / "task_orchestrations.json"
    _init_event_store(service._l1_db_path)

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
        service._l1_db_path,
        "UserMessage",
        {"user_id": "u1", "session_id": "s1", "message": "plan this", "turn_id": "turn_plan"},
        1000,
    )
    _insert_event(
        service._l1_db_path,
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
    assert summary["headline"] == "Orchestrating tasks"
    assert summary["active_steps"] == 1
    assert summary["completed_steps"] == 0
