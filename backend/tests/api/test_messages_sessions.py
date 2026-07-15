import json
import sqlite3
import sys
from pathlib import Path

import pytest

BACKEND_SRC = Path(__file__).resolve().parents[1] / "src"
if str(BACKEND_SRC) not in sys.path:
    sys.path.insert(0, str(BACKEND_SRC))

from magi.api.routers import messages, messages_sessions
from magi.chat import ChatStore
from magi.chat.read_service import (
    ChatDisplayMessage,
    ChatReadService,
    ChatSessionRenameResult,
    ChatSessionSummary,
)
from magi.runtime_trace.chat_trace.read_service import ChatTraceReadService

FACT_EVENTS_TABLE = "fact_events"
CHAT_SESSIONS_TABLE = "chat_sessions"
CHAT_TURNS_TABLE = "chat_turns"
CHAT_MESSAGES_TABLE = "chat_messages"


def _init_event_store(db_path: Path) -> None:
    conn = sqlite3.connect(str(db_path))
    cur = conn.cursor()
    cur.execute(f"""
        CREATE TABLE IF NOT EXISTS {FACT_EVENTS_TABLE} (
            event_id TEXT PRIMARY KEY,
            event_type TEXT NOT NULL,
            content TEXT NOT NULL,
            timestamp REAL NOT NULL,
            user_id TEXT,
            session_id TEXT,
            turn_id TEXT,
            deleted_at REAL
        )
        """)
    cur.execute(
        f"CREATE INDEX IF NOT EXISTS idx_{FACT_EVENTS_TABLE}_user ON {FACT_EVENTS_TABLE}(user_id)"
    )
    cur.execute(
        f"CREATE INDEX IF NOT EXISTS idx_{FACT_EVENTS_TABLE}_session ON {FACT_EVENTS_TABLE}(session_id)"
    )
    conn.commit()
    conn.close()


def _init_chat_session_store(db_path: Path) -> None:
    from magi.chat.storage.schema import CHAT_STORE_SCHEMA_SQL

    conn = sqlite3.connect(str(db_path))
    conn.executescript(CHAT_STORE_SCHEMA_SQL)
    conn.commit()
    conn.close()


def _insert_session(db_path: Path, **values) -> None:
    payload = {
        "session_id": values.get("session_id"),
        "user_id": values.get("user_id"),
        "title": values.get("title", ""),
        "title_overridden": int(values.get("title_overridden", False)),
        "summary": values.get("summary", ""),
        "created_at_ms": values.get("created_at", 0),
        "updated_at_ms": values.get("updated_at", values.get("created_at", 0)),
        "last_message_at_ms": values.get("last_message_at"),
        "last_user_message_at_ms": values.get("last_user_message_at"),
        "last_message_preview": values.get("last_message_preview", ""),
        "last_user_message_preview": values.get("last_user_message_preview", ""),
        "message_count": values.get("message_count", 0),
        "history_version": values.get("history_version", 0),
        "workspace_path": values.get("workspace_path"),
        "archived_at_ms": values.get("archived_at"),
        "deleted_at_ms": values.get("deleted_at"),
    }
    conn = sqlite3.connect(str(db_path))
    cur = conn.cursor()
    cur.execute(
        f"""
        INSERT INTO {CHAT_SESSIONS_TABLE} (
            session_id, user_id, title, title_overridden, summary, created_at_ms, updated_at_ms,
            last_message_at_ms, last_user_message_at_ms, last_message_preview,
            last_user_message_preview, message_count, history_version, workspace_path, archived_at_ms, deleted_at_ms
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        tuple(payload.values()),
    )
    conn.commit()
    conn.close()


def _insert_chat_turn(db_path: Path, **values) -> None:
    payload = {
        "turn_id": values.get("turn_id"),
        "session_id": values.get("session_id"),
        "user_id": values.get("user_id"),
        "trace_id": values.get("trace_id"),
        "orchestration_id": values.get("orchestration_id"),
        "status": values.get("status", "queued"),
        "response_mode": values.get("response_mode", "final_only"),
        "execution_mode": values.get("execution_mode"),
        "ux_plan_json": values.get("ux_plan_json", "{}"),
        "created_at_ms": values.get("created_at_ms", 0),
        "updated_at_ms": values.get("updated_at_ms", values.get("created_at_ms", 0)),
        "completed_at_ms": values.get("completed_at_ms"),
        "error_text": values.get("error_text"),
        "run_id": values.get("run_id"),
        "run_revision": values.get("run_revision", 0),
        "run_disposition": values.get("run_disposition"),
    }
    conn = sqlite3.connect(str(db_path))
    cur = conn.cursor()
    cur.execute(
        f"""
        INSERT INTO {CHAT_TURNS_TABLE} (
            turn_id, session_id, user_id, trace_id, orchestration_id, status,
            response_mode, execution_mode, ux_plan_json, created_at_ms, updated_at_ms,
            completed_at_ms, error_text, run_id, run_revision, run_disposition
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        tuple(payload.values()),
    )
    conn.commit()
    conn.close()


def _insert_chat_message(db_path: Path, **values) -> None:
    payload = {
        "message_id": values.get("message_id"),
        "session_id": values.get("session_id"),
        "turn_id": values.get("turn_id"),
        "user_id": values.get("user_id"),
        "role": values.get("role"),
        "message_kind": values.get("message_kind"),
        "content_text": values.get("content_text"),
        "payload_json": values.get("payload_json", "{}"),
        "is_final": int(values.get("is_final", True)),
        "is_visible": int(values.get("is_visible", True)),
        "created_at_ms": values.get("created_at_ms", 0),
        "sequence_no": values.get("sequence_no", 1),
        "replaces_message_id": values.get("replaces_message_id"),
        "replaced_by_message_id": values.get("replaced_by_message_id"),
        "reply_to_message_id": values.get("reply_to_message_id"),
    }
    conn = sqlite3.connect(str(db_path))
    cur = conn.cursor()
    cur.execute(
        f"""
        INSERT INTO {CHAT_MESSAGES_TABLE} (
            message_id, session_id, turn_id, user_id, role, message_kind, content_text,
            payload_json, is_final, is_visible, created_at_ms, sequence_no,
            replaces_message_id, replaced_by_message_id, reply_to_message_id
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        tuple(payload.values()),
    )
    conn.commit()
    conn.close()


def _init_runtime_trace_store(db_path: Path) -> None:
    conn = sqlite3.connect(str(db_path))
    cur = conn.cursor()
    cur.executescript("""
        CREATE TABLE IF NOT EXISTS trace_turns (
            trace_id TEXT PRIMARY KEY,
            turn_id TEXT NOT NULL UNIQUE,
            session_id TEXT NOT NULL,
            user_id TEXT NOT NULL,
            status TEXT NOT NULL,
            mode TEXT NOT NULL,
            orchestration_id TEXT,
            started_at_ms INTEGER NOT NULL,
            ended_at_ms INTEGER,
            duration_ms INTEGER,
            user_message_preview TEXT,
            response_preview TEXT,
            error_summary TEXT,
            continued_from_turn_id TEXT,
            continued_from_trace_id TEXT,
            superseded_by_turn_id TEXT,
            supersession_reason TEXT,
            created_at_ms INTEGER NOT NULL,
            updated_at_ms INTEGER NOT NULL
        );
        CREATE TABLE IF NOT EXISTS trace_spans (
            span_id TEXT PRIMARY KEY,
            trace_id TEXT NOT NULL,
            turn_id TEXT NOT NULL,
            parent_span_id TEXT,
            node_type TEXT NOT NULL,
            name TEXT NOT NULL,
            status TEXT NOT NULL,
            attempt_index INTEGER NOT NULL DEFAULT 1,
            retry_count INTEGER NOT NULL DEFAULT 0,
            iteration INTEGER,
            execution_agent_id TEXT,
            result_preview TEXT,
            error_text TEXT,
            started_at_ms INTEGER NOT NULL,
            ended_at_ms INTEGER,
            duration_ms INTEGER,
            created_at_ms INTEGER NOT NULL,
            updated_at_ms INTEGER NOT NULL
        );
        CREATE TABLE IF NOT EXISTS trace_intent_resolutions (
            span_id TEXT PRIMARY KEY,
            trace_id TEXT NOT NULL,
            turn_id TEXT NOT NULL,
            intent TEXT NOT NULL,
            execution_mode TEXT NOT NULL,
            route_reason TEXT,
            selected_tools_json TEXT NOT NULL,
            selected_worker_type TEXT
        );
        CREATE TABLE IF NOT EXISTS trace_llm_calls (
            span_id TEXT PRIMARY KEY,
            trace_id TEXT NOT NULL,
            turn_id TEXT NOT NULL,
            provider TEXT NOT NULL,
            model TEXT NOT NULL,
            input_tokens INTEGER NOT NULL DEFAULT 0,
            output_tokens INTEGER NOT NULL DEFAULT 0,
            reasoning_tokens INTEGER NOT NULL DEFAULT 0,
            cache_read_tokens INTEGER NOT NULL DEFAULT 0,
            cache_write_tokens INTEGER NOT NULL DEFAULT 0,
            thinking_enabled INTEGER NOT NULL DEFAULT 0,
            request_preview TEXT,
            response_preview TEXT
        );
        CREATE TABLE IF NOT EXISTS trace_tools (
            span_id TEXT PRIMARY KEY,
            trace_id TEXT NOT NULL,
            turn_id TEXT NOT NULL,
            tool_name TEXT NOT NULL,
            tool_call_id TEXT,
            arguments_json TEXT NOT NULL,
            success INTEGER NOT NULL,
            execution_time_ms INTEGER,
            error_code TEXT,
            error_message TEXT,
            result_preview TEXT
        );
        """)
    conn.commit()
    conn.close()


def _insert_trace_turn(db_path: Path, **values) -> None:
    payload = {
        "trace_id": values.get("trace_id"),
        "turn_id": values.get("turn_id"),
        "session_id": values.get("session_id"),
        "user_id": values.get("user_id"),
        "status": values.get("status", "running"),
        "mode": values.get("mode", "function_calling"),
        "orchestration_id": values.get("orchestration_id"),
        "started_at_ms": values.get("started_at_ms", 0),
        "ended_at_ms": values.get("ended_at_ms"),
        "duration_ms": values.get("duration_ms"),
        "user_message_preview": values.get("user_message_preview"),
        "response_preview": values.get("response_preview"),
        "error_summary": values.get("error_summary"),
        "continued_from_turn_id": values.get("continued_from_turn_id"),
        "continued_from_trace_id": values.get("continued_from_trace_id"),
        "superseded_by_turn_id": values.get("superseded_by_turn_id"),
        "supersession_reason": values.get("supersession_reason"),
        "created_at_ms": values.get("created_at_ms", values.get("started_at_ms", 0)),
        "updated_at_ms": values.get(
            "updated_at_ms", values.get("ended_at_ms", values.get("started_at_ms", 0))
        ),
    }
    conn = sqlite3.connect(str(db_path))
    cur = conn.cursor()
    cur.execute(
        """
        INSERT INTO trace_turns (
            trace_id, turn_id, session_id, user_id, status, mode, orchestration_id,
            started_at_ms, ended_at_ms, duration_ms, user_message_preview, response_preview,
            error_summary, continued_from_turn_id, continued_from_trace_id,
            superseded_by_turn_id, supersession_reason, created_at_ms, updated_at_ms
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        tuple(payload.values()),
    )
    conn.commit()
    conn.close()


def _insert_trace_span(db_path: Path, **values) -> None:
    payload = {
        "span_id": values.get("span_id"),
        "trace_id": values.get("trace_id"),
        "turn_id": values.get("turn_id"),
        "parent_span_id": values.get("parent_span_id"),
        "node_type": values.get("node_type"),
        "name": values.get("name"),
        "status": values.get("status", "completed"),
        "attempt_index": values.get("attempt_index", 1),
        "retry_count": values.get("retry_count", 0),
        "iteration": values.get("iteration"),
        "execution_agent_id": values.get("execution_agent_id"),
        "result_preview": values.get("result_preview"),
        "error_text": values.get("error_text"),
        "started_at_ms": values.get("started_at_ms", 0),
        "ended_at_ms": values.get("ended_at_ms"),
        "duration_ms": values.get("duration_ms"),
        "created_at_ms": values.get("created_at_ms", values.get("started_at_ms", 0)),
        "updated_at_ms": values.get(
            "updated_at_ms", values.get("ended_at_ms", values.get("started_at_ms", 0))
        ),
    }
    conn = sqlite3.connect(str(db_path))
    cur = conn.cursor()
    cur.execute(
        """
        INSERT INTO trace_spans (
            span_id, trace_id, turn_id, parent_span_id, node_type, name, status,
            attempt_index, retry_count, iteration, execution_agent_id, result_preview,
            error_text, started_at_ms, ended_at_ms, duration_ms, created_at_ms, updated_at_ms
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        tuple(payload.values()),
    )
    conn.commit()
    conn.close()


def _insert_trace_llm_call(db_path: Path, **values) -> None:
    payload = {
        "span_id": values.get("span_id"),
        "trace_id": values.get("trace_id"),
        "turn_id": values.get("turn_id"),
        "provider": values.get("provider", "openai"),
        "model": values.get("model", "fake-model"),
        "input_tokens": values.get("input_tokens", 0),
        "output_tokens": values.get("output_tokens", 0),
        "reasoning_tokens": values.get("reasoning_tokens", 0),
        "cache_read_tokens": values.get("cache_read_tokens", 0),
        "cache_write_tokens": values.get("cache_write_tokens", 0),
        "thinking_enabled": int(values.get("thinking_enabled", False)),
        "request_preview": values.get("request_preview"),
        "response_preview": values.get("response_preview"),
    }
    conn = sqlite3.connect(str(db_path))
    cur = conn.cursor()
    cur.execute(
        """
        INSERT INTO trace_llm_calls (
            span_id, trace_id, turn_id, provider, model, input_tokens, output_tokens,
            reasoning_tokens, cache_read_tokens, cache_write_tokens, thinking_enabled,
            request_preview, response_preview
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        tuple(payload.values()),
    )
    conn.commit()
    conn.close()


def _insert_trace_tool(db_path: Path, **values) -> None:
    payload = {
        "span_id": values.get("span_id"),
        "trace_id": values.get("trace_id"),
        "turn_id": values.get("turn_id"),
        "tool_name": values.get("tool_name"),
        "tool_call_id": values.get("tool_call_id"),
        "arguments_json": json.dumps(values.get("arguments", {}), ensure_ascii=False),
        "success": int(values.get("success", True)),
        "execution_time_ms": values.get("execution_time_ms", 0),
        "error_code": values.get("error_code"),
        "error_message": values.get("error_message"),
        "result_preview": values.get("result_preview"),
    }
    conn = sqlite3.connect(str(db_path))
    cur = conn.cursor()
    cur.execute(
        """
        INSERT INTO trace_tools (
            span_id, trace_id, turn_id, tool_name, tool_call_id, arguments_json, success,
            execution_time_ms, error_code, error_message, result_preview
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        tuple(payload.values()),
    )
    conn.commit()
    conn.close()


def _insert_event(db_path: Path, event_type: str, data: dict, timestamp: float) -> None:
    target_table = FACT_EVENTS_TABLE
    content = str(data.get("content") or "")
    conn = sqlite3.connect(str(db_path))
    cur = conn.cursor()
    cur.execute(
        f"INSERT INTO {target_table} (event_id, event_type, content, timestamp, user_id, session_id, turn_id, deleted_at) VALUES (?, ?, ?, ?, ?, ?, ?, NULL)",
        (
            f"{event_type}-{int(timestamp * 1000)}",
            event_type,
            content,
            timestamp,
            data.get("user_id"),
            data.get("session_id"),
            data.get("turn_id"),
        ),
    )
    conn.commit()
    conn.close()


def _build_service(tmp_path: Path) -> ChatReadService:
    service = ChatReadService()
    db_path = tmp_path / "chat.sqlite3"
    service._chat_db_path = db_path
    service._l1_db_path = db_path

    # Hermeticity: display-history now joins chat-trace data through the
    # container's ChatTraceReadService singleton, whose db paths freeze at
    # construction (the developer's real ~/.magi when run standalone, or a
    # stale tmp dir mid-suite). Pin it to THIS tmp dir with real schema.
    from _shared.db_schema import apply_chain_schema
    from magi.core.container import get_container
    from magi.runtime_trace.chat_trace.read_service import ChatTraceReadService

    trace_db = tmp_path / "runtime_trace.db"
    apply_chain_schema("runtime_trace", trace_db)
    apply_chain_schema("l1", tmp_path / "l1_events.db")
    trace_service = ChatTraceReadService()
    trace_service._runtime_trace_db_path = trace_db
    trace_service._l1_db_path = tmp_path / "l1_events.db"
    container = get_container()
    container.chat_trace_read_service.reset()
    from dependency_injector import providers as _providers

    container.chat_trace_read_service.override(_providers.Object(trace_service))
    return service


def test_list_sessions_reads_from_canonical_session_rows(tmp_path):
    service = _build_service(tmp_path)
    _init_chat_session_store(service._l1_db_path)
    _insert_session(
        service._l1_db_path,
        session_id="s-current",
        user_id="u1",
        title="Current Chat",
        created_at=1000,
        updated_at=1010,
    )

    sessions = service.list_sessions("u1", limit=10)

    assert len(sessions) == 1
    assert sessions[0].session_id == "s-current"
    assert sessions[0].message_count == 0
    assert sessions[0].title == "Current Chat"


def test_list_sessions_orders_by_session_metadata(tmp_path):
    service = _build_service(tmp_path)
    _init_chat_session_store(service._l1_db_path)
    _insert_session(
        service._l1_db_path,
        session_id="s1",
        user_id="u1",
        title="Session One",
        last_message_preview="response one",
        last_user_message_preview="hello from session one",
        message_count=2,
        created_at=1000,
        updated_at=1010,
        last_message_at=1010,
        last_user_message_at=1000,
    )
    _insert_session(
        service._l1_db_path,
        session_id="s2",
        user_id="u1",
        title="Session Two",
        last_message_preview="response two",
        last_user_message_preview="hello from session two",
        message_count=2,
        history_version=7,
        created_at=2000,
        updated_at=2010,
        last_message_at=2010,
        last_user_message_at=2000,
    )
    _insert_session(
        service._l1_db_path,
        session_id="s-other",
        user_id="u2",
        title="Ignore Me",
        created_at=5000,
        updated_at=5000,
    )

    sessions = service.list_sessions("u1", limit=10)

    assert [item.session_id for item in sessions] == ["s2", "s1"]
    assert sessions[0].message_count == 2
    assert sessions[0].history_version == 7
    assert sessions[1].message_count == 2
    assert sessions[0].last_timestamp == 2010
    assert sessions[0].title == "Session Two"


def test_list_sessions_respects_limit(tmp_path):
    service = _build_service(tmp_path)
    _init_chat_session_store(service._l1_db_path)

    for index in range(5):
        _insert_session(
            service._l1_db_path,
            session_id=f"s{index}",
            user_id="u1",
            title=f"session {index}",
            created_at=1000 + index,
            updated_at=1000 + index,
        )

    sessions = service.list_sessions("u1", limit=2)
    assert len(sessions) == 2


def test_create_new_session_persists_workspace_path(tmp_path):
    service = _build_service(tmp_path)
    # The service no longer creates its own schema (alembic-owned); seed it
    # like the sibling tests do.
    _init_chat_session_store(service._chat_db_path)

    session_id = service.create_new_session("u1", workspace_path="/tmp/magi")

    sessions = service.list_sessions("u1", limit=10)

    assert sessions[0].session_id == session_id
    assert sessions[0].workspace_path == "/tmp/magi"


def test_get_display_history_returns_attachment_metadata_for_user_message(tmp_path):
    service = _build_service(tmp_path)
    _init_chat_session_store(service._chat_db_path)
    _insert_session(
        service._chat_db_path,
        session_id="s1",
        user_id="u1",
        title="Attachment Chat",
        created_at=1000,
        updated_at=1000,
        message_count=1,
    )
    _insert_chat_turn(
        service._chat_db_path,
        turn_id="turn-1",
        session_id="s1",
        user_id="u1",
        created_at_ms=1000,
        updated_at_ms=1000,
    )
    _insert_chat_message(
        service._chat_db_path,
        message_id="msg-1",
        session_id="s1",
        turn_id="turn-1",
        user_id="u1",
        role="user",
        message_kind="user_text",
        content_text="",
        payload_json=json.dumps({"attachments": [{"kind": "pdf", "attachment_id": "att-1"}]}),
        created_at_ms=1000,
    )

    history = service.get_display_history("u1", "s1", limit=10)

    assert history[0].attachments == [{"kind": "pdf", "attachment_id": "att-1"}]
    assert history[0].content == ""


def test_get_display_history_restores_only_public_user_feedback_payload(tmp_path):
    service = _build_service(tmp_path)
    _init_chat_session_store(service._chat_db_path)
    _insert_session(
        service._chat_db_path,
        session_id="s1",
        user_id="u1",
        title="Feedback Chat",
        created_at=1000,
        updated_at=1000,
        message_count=1,
    )
    _insert_chat_turn(
        service._chat_db_path,
        turn_id="turn-1",
        session_id="s1",
        user_id="u1",
        created_at_ms=1000,
        updated_at_ms=1000,
    )
    feedback = {
        "kind": "item_irrelevant",
        "target_message_id": "assistant-1",
        "finding_ref": "event:event-1",
    }
    _insert_chat_message(
        service._chat_db_path,
        message_id="msg-1",
        session_id="s1",
        turn_id="turn-1",
        user_id="u1",
        role="user",
        message_kind="user_text",
        content_text="Leave this record out.",
        payload_json=json.dumps(
            {
                "attachments": [{"kind": "pdf", "attachment_id": "att-1"}],
                "recall_feedback": feedback,
                "internal_note": "must not reach the client",
            }
        ),
        created_at_ms=1000,
    )

    history = service.get_display_history("u1", "s1", limit=10)

    assert history[0].attachments == [{"kind": "pdf", "attachment_id": "att-1"}]
    assert history[0].payload == {"recall_feedback": feedback}


def test_get_display_history_includes_turn_run_state(tmp_path):
    service = _build_service(tmp_path)
    _init_chat_session_store(service._chat_db_path)
    _insert_session(
        service._chat_db_path,
        session_id="s1",
        user_id="u1",
        title="Run State Chat",
        created_at=1000,
        updated_at=1000,
        message_count=1,
    )
    _insert_chat_turn(
        service._chat_db_path,
        turn_id="turn-1",
        session_id="s1",
        user_id="u1",
        status="cancelled",
        run_id="run-1",
        run_revision=2,
        run_disposition="root",
        completed_at_ms=1200,
        created_at_ms=1000,
        updated_at_ms=1200,
    )
    _insert_chat_message(
        service._chat_db_path,
        message_id="msg-1",
        session_id="s1",
        turn_id="turn-1",
        user_id="u1",
        role="assistant",
        message_kind="assistant_final",
        content_text="cancelled",
        created_at_ms=1200,
    )

    history = service.get_display_history("u1", "s1", limit=10)

    assert history[0].run_state == {
        "state": "cancelled",
        "run_id": "run-1",
        "run_revision": 2,
        "run_disposition": "root",
        "can_cancel": False,
        "can_detach": False,
        "error_text": None,
        "completed_at_ms": 1200,
    }


def test_update_session_workspace_persists_and_allows_clearing(tmp_path):
    service = _build_service(tmp_path)
    _init_chat_session_store(service._chat_db_path)
    _insert_session(
        service._chat_db_path,
        session_id="s1",
        user_id="u1",
        title="Workspace Chat",
        created_at=1000,
        updated_at=1000,
    )

    updated = service.update_session_workspace("u1", "s1", "/tmp/magi")
    cleared = service.update_session_workspace("u1", "s1", "")
    sessions = service.list_sessions("u1", limit=10)

    assert updated.workspace_path == "/tmp/magi"
    assert cleared.workspace_path is None
    assert sessions[0].workspace_path is None


def test_rename_session_persists_custom_title(tmp_path):
    service = _build_service(tmp_path)
    _init_chat_session_store(service._l1_db_path)
    _insert_session(
        service._l1_db_path,
        session_id="s1",
        user_id="u1",
        title="原始标题",
        created_at=1000,
        updated_at=1000,
    )

    service.rename_session("u1", "s1", "新的会话名")

    renamed = service.list_sessions("u1", limit=10)

    assert renamed[0].session_id == "s1"
    assert renamed[0].title == "新的会话名"

    reloaded = _build_service(tmp_path)
    _init_chat_session_store(reloaded._l1_db_path)
    reloaded_sessions = reloaded.list_sessions("u1", limit=10)
    assert reloaded_sessions[0].title == "新的会话名"


def test_delete_session_removes_session_row_and_related_data(tmp_path):
    service = _build_service(tmp_path)
    _init_event_store(service._l1_db_path)
    _init_chat_session_store(service._l1_db_path)
    _insert_session(
        service._l1_db_path,
        session_id="s1",
        user_id="u1",
        title="保留会话",
        created_at=1000,
        updated_at=1000,
    )
    _insert_session(
        service._l1_db_path,
        session_id="s2",
        user_id="u1",
        title="删除会话",
        created_at=2000,
        updated_at=2010,
    )
    _insert_event(
        service._l1_db_path,
        "UserMessage",
        {"user_id": "u1", "session_id": "s2", "content": "删除会话"},
        2000,
    )
    _insert_event(
        service._l1_db_path,
        "AIResponse",
        {"user_id": "u1", "session_id": "s2", "content": "需要一起删掉"},
        2010,
    )

    service.delete_session("u1", "s2")

    remaining = service.list_sessions("u1", limit=10)
    assert [item.session_id for item in remaining] == ["s1"]

    history = service.get_conversation_history("u1", "s2", limit=20)
    assert history == []


def test_get_conversation_history_reads_from_chat_store_not_fact_events(tmp_path):
    service = _build_service(tmp_path)
    _init_chat_session_store(service._chat_db_path)
    _insert_session(
        service._chat_db_path,
        session_id="s-chat",
        user_id="u1",
        title="Chat",
        created_at=1000,
        updated_at=1020,
        message_count=2,
    )
    _insert_chat_turn(
        service._chat_db_path,
        turn_id="turn-1",
        session_id="s-chat",
        user_id="u1",
        status="completed",
        response_mode="final_only",
        created_at_ms=1000,
        updated_at_ms=1020,
        completed_at_ms=1020,
    )
    _insert_chat_message(
        service._chat_db_path,
        message_id="msg-user",
        session_id="s-chat",
        turn_id="turn-1",
        user_id="u1",
        role="user",
        message_kind="user_text",
        content_text="chat-store user",
        created_at_ms=1000,
        sequence_no=1,
    )
    _insert_chat_message(
        service._chat_db_path,
        message_id="msg-assistant",
        session_id="s-chat",
        turn_id="turn-1",
        user_id="u1",
        role="assistant",
        message_kind="assistant_final",
        content_text="chat-store reply",
        created_at_ms=1020,
        sequence_no=2,
    )
    _init_event_store(service._l1_db_path)
    _insert_event(
        service._l1_db_path,
        "UserMessage",
        {"user_id": "u1", "session_id": "s-chat", "turn_id": "turn-1", "content": "legacy user"},
        1,
    )

    messages = service.get_conversation_history("u1", "s-chat", limit=20)

    assert [item.content for item in messages] == ["chat-store user", "chat-store reply"]
    assert messages[0].message_id == "msg-user"
    assert messages[1].message_kind == "assistant_final"


def test_get_conversation_history_collapses_rhythm_segments_for_prompt(tmp_path):
    service = _build_service(tmp_path)
    _init_chat_session_store(service._chat_db_path)
    _insert_session(
        service._chat_db_path,
        session_id="s-rhythm",
        user_id="u1",
        title="Rhythm",
        created_at=1000,
        updated_at=1300,
        message_count=3,
    )
    _insert_chat_turn(
        service._chat_db_path,
        turn_id="turn-rhythm",
        session_id="s-rhythm",
        user_id="u1",
        status="completed",
        response_mode="final_only",
        created_at_ms=1000,
        updated_at_ms=1300,
        completed_at_ms=1300,
    )
    _insert_chat_message(
        service._chat_db_path,
        message_id="msg-user-rhythm",
        session_id="s-rhythm",
        turn_id="turn-rhythm",
        user_id="u1",
        role="user",
        message_kind="user_text",
        content_text="怎么做节奏感回复？",
        created_at_ms=1000,
        sequence_no=1,
    )
    _insert_chat_message(
        service._chat_db_path,
        message_id="msg-rhythm-1",
        session_id="s-rhythm",
        turn_id="turn-rhythm",
        user_id="u1",
        role="assistant",
        message_kind="assistant_rhythm_segment",
        content_text="先接住用户的问题。",
        payload_json=json.dumps({"rhythm": {"segment_index": 0, "segment_count": 2}}),
        created_at_ms=1200,
        sequence_no=2,
    )
    _insert_chat_message(
        service._chat_db_path,
        message_id="msg-rhythm-2",
        session_id="s-rhythm",
        turn_id="turn-rhythm",
        user_id="u1",
        role="assistant",
        message_kind="assistant_rhythm_segment",
        content_text="再给出核心实现方案。",
        payload_json=json.dumps({"rhythm": {"segment_index": 1, "segment_count": 2}}),
        created_at_ms=1300,
        sequence_no=3,
    )

    prompt_history = service.get_conversation_history("u1", "s-rhythm", limit=20)
    display_history = service.get_display_history("u1", "s-rhythm", limit=20)

    assert [message.content for message in prompt_history] == [
        "怎么做节奏感回复？",
        "先接住用户的问题。\n\n再给出核心实现方案。",
    ]
    assert prompt_history[1].message_kind == "assistant_final"
    assert [message.message_kind for message in display_history] == [
        "user_text",
        "assistant_rhythm_segment",
        "assistant_rhythm_segment",
    ]


def test_create_user_turn_persists_reply_target_and_display_history_returns_preview(tmp_path):
    service = _build_service(tmp_path)
    _init_chat_session_store(service._chat_db_path)
    _insert_session(
        service._chat_db_path,
        session_id="s-reply",
        user_id="u1",
        title="Reply Chat",
        created_at=1000,
        updated_at=1050,
        message_count=2,
        last_message_at=1050,
        last_user_message_at=1000,
        last_message_preview="Can you clarify the build step?",
        last_user_message_preview="How should I package this?",
    )
    _insert_chat_turn(
        service._chat_db_path,
        turn_id="turn-assistant",
        session_id="s-reply",
        user_id="u1",
        status="completed",
        response_mode="final_only",
        created_at_ms=1000,
        updated_at_ms=1050,
        completed_at_ms=1050,
    )
    _insert_chat_message(
        service._chat_db_path,
        message_id="msg-user-root",
        session_id="s-reply",
        turn_id="turn-assistant",
        user_id="u1",
        role="user",
        message_kind="user_text",
        content_text="How should I package this?",
        created_at_ms=1000,
        sequence_no=1,
    )
    _insert_chat_message(
        service._chat_db_path,
        message_id="msg-assistant-root",
        session_id="s-reply",
        turn_id="turn-assistant",
        user_id="u1",
        role="assistant",
        message_kind="assistant_final",
        content_text="Can you clarify the build step?",
        created_at_ms=1050,
        sequence_no=2,
    )

    store = ChatStore(db_path=str(service._chat_db_path))
    __import__("asyncio").run(
        store.create_user_turn(
            session_id="s-reply",
            user_id="u1",
            turn_id="turn-reply",
            message_text="I mean the release artifact format.",
            created_at_ms=1100,
            reply_to_message_id="msg-assistant-root",
        )
    )

    history = service.get_display_history("u1", "s-reply", limit=10)

    assert [item.content for item in history][-1] == "I mean the release artifact format."
    assert history[-1].to_dict()["reply_to"] == {
        "message_id": "msg-assistant-root",
        "role": "assistant",
        "message_kind": "assistant_final",
        "content_excerpt": "Can you clarify the build step?",
    }
    assert history[0].to_dict().get("reply_to") is None


def test_clear_conversation_history_bumps_history_version(tmp_path):
    service = _build_service(tmp_path)
    _init_chat_session_store(service._chat_db_path)
    _insert_session(
        service._chat_db_path,
        session_id="s-chat",
        user_id="u1",
        title="Chat",
        created_at=1000,
        updated_at=1020,
        message_count=2,
    )
    _insert_chat_turn(
        service._chat_db_path,
        turn_id="turn-1",
        session_id="s-chat",
        user_id="u1",
        status="completed",
        response_mode="final_only",
        created_at_ms=1000,
        updated_at_ms=1020,
        completed_at_ms=1020,
    )
    _insert_chat_message(
        service._chat_db_path,
        message_id="msg-user",
        session_id="s-chat",
        turn_id="turn-1",
        user_id="u1",
        role="user",
        message_kind="user_text",
        content_text="chat-store user",
        created_at_ms=1000,
        sequence_no=1,
    )

    conn = service._get_conn()
    before_version = int(
        conn.execute(
            f"SELECT history_version FROM {CHAT_SESSIONS_TABLE} WHERE session_id = ?",
            ("s-chat",),
        ).fetchone()[0]
    )

    service.clear_conversation_history("u1", "s-chat")

    after_version = int(
        conn.execute(
            f"SELECT history_version FROM {CHAT_SESSIONS_TABLE} WHERE session_id = ?",
            ("s-chat",),
        ).fetchone()[0]
    )

    assert after_version == before_version + 1


def test_update_message_label_persists_and_display_history_returns_label(tmp_path, monkeypatch):
    chat_db_path = tmp_path / "chat.db"
    store = ChatStore(db_path=str(chat_db_path))
    __import__("asyncio").run(store.initialize())

    user_message = __import__("asyncio").run(
        store.create_user_turn(
            session_id="s-label",
            user_id="u1",
            turn_id="turn-label",
            message_text="Useful answer",
            created_at_ms=100,
        )
    )

    __import__("asyncio").run(
        store.update_message_label(
            session_id="s-label",
            message_id=user_message.message_id,
            label={
                "kind": "emoji",
                "text": "👍",
                "applied_by": "user",
                "source": "manual",
                "created_at_ms": 200,
            },
        )
    )

    service = ChatReadService()
    service._chat_db_path = chat_db_path
    service._l1_db_path = tmp_path / "l1.sqlite3"
    service._runtime_trace_db_path = tmp_path / "runtime_trace.sqlite3"
    # display-history reads trace data through get_chat_trace_read_service();
    # pin it to a schema-backed tmp trace db like the sibling tests do.
    from _shared.db_schema import apply_chain_schema

    apply_chain_schema("runtime_trace", service._runtime_trace_db_path)
    trace_service = ChatTraceReadService()
    trace_service._runtime_trace_db_path = service._runtime_trace_db_path
    trace_service._l1_db_path = service._l1_db_path
    monkeypatch.setattr(
        "magi.chat.read_service.get_chat_trace_read_service",
        lambda: trace_service,
    )

    history = service.get_display_history("u1", "s-label", limit=20)

    assert history[-1].to_dict()["label"] == {
        "kind": "emoji",
        "text": "👍",
        "applied_by": "user",
        "source": "manual",
        "created_at_ms": 200,
    }


def test_hide_message_excludes_it_from_display_history(tmp_path, monkeypatch):
    chat_db_path = tmp_path / "chat.db"
    store = ChatStore(db_path=str(chat_db_path))
    __import__("asyncio").run(store.initialize())

    user_message = __import__("asyncio").run(
        store.create_user_turn(
            session_id="s-hide",
            user_id="u1",
            turn_id="turn-hide",
            message_text="hide me",
            created_at_ms=100,
        )
    )

    __import__("asyncio").run(
        store.hide_message(
            session_id="s-hide",
            message_id=user_message.message_id,
        )
    )

    service = ChatReadService()
    service._chat_db_path = chat_db_path
    service._l1_db_path = tmp_path / "l1.sqlite3"
    service._runtime_trace_db_path = tmp_path / "runtime_trace.sqlite3"
    # display-history reads trace data through get_chat_trace_read_service();
    # pin it to a schema-backed tmp trace db like the sibling tests do.
    from _shared.db_schema import apply_chain_schema

    apply_chain_schema("runtime_trace", service._runtime_trace_db_path)
    trace_service = ChatTraceReadService()
    trace_service._runtime_trace_db_path = service._runtime_trace_db_path
    trace_service._l1_db_path = service._l1_db_path
    monkeypatch.setattr(
        "magi.chat.read_service.get_chat_trace_read_service",
        lambda: trace_service,
    )

    history = service.get_display_history("u1", "s-hide", limit=20)

    assert history == []


def test_delete_session_bumps_history_version(tmp_path):
    service = _build_service(tmp_path)
    _init_chat_session_store(service._chat_db_path)
    _insert_session(
        service._chat_db_path,
        session_id="s-chat",
        user_id="u1",
        title="Chat",
        created_at=1000,
        updated_at=1020,
        message_count=2,
    )
    _insert_chat_turn(
        service._chat_db_path,
        turn_id="turn-1",
        session_id="s-chat",
        user_id="u1",
        status="completed",
        response_mode="final_only",
        created_at_ms=1000,
        updated_at_ms=1020,
        completed_at_ms=1020,
    )
    _insert_chat_message(
        service._chat_db_path,
        message_id="msg-user",
        session_id="s-chat",
        turn_id="turn-1",
        user_id="u1",
        role="user",
        message_kind="user_text",
        content_text="chat-store user",
        created_at_ms=1000,
        sequence_no=1,
    )

    conn = service._get_conn()
    before_version = int(
        conn.execute(
            f"SELECT history_version FROM {CHAT_SESSIONS_TABLE} WHERE session_id = ?",
            ("s-chat",),
        ).fetchone()[0]
    )

    service.delete_session("u1", "s-chat")

    after_version = int(
        conn.execute(
            f"SELECT history_version FROM {CHAT_SESSIONS_TABLE} WHERE session_id = ?",
            ("s-chat",),
        ).fetchone()[0]
    )

    assert after_version == before_version + 1


def test_get_display_history_prefers_chat_store_transcript(tmp_path, monkeypatch):
    service = _build_service(tmp_path)
    trace_service = ChatTraceReadService()
    trace_service._runtime_trace_db_path = tmp_path / "runtime_trace.db"
    trace_service._orchestrations_path = tmp_path / "task_orchestrations.json"
    monkeypatch.setattr(
        "magi.chat.read_service.get_chat_trace_read_service",
        lambda: trace_service,
    )
    _init_chat_session_store(service._chat_db_path)
    _insert_session(
        service._chat_db_path,
        session_id="s-chat",
        user_id="u1",
        title="Chat",
        created_at=1000,
        updated_at=1020,
        message_count=2,
    )
    _insert_chat_turn(
        service._chat_db_path,
        turn_id="turn-1",
        session_id="s-chat",
        user_id="u1",
        status="completed",
        response_mode="final_only",
        created_at_ms=1000,
        updated_at_ms=1020,
        completed_at_ms=1020,
    )
    _insert_chat_message(
        service._chat_db_path,
        message_id="msg-user",
        session_id="s-chat",
        turn_id="turn-1",
        user_id="u1",
        role="user",
        message_kind="user_text",
        content_text="chat-store user",
        created_at_ms=1000,
        sequence_no=1,
    )
    _insert_chat_message(
        service._chat_db_path,
        message_id="msg-assistant",
        session_id="s-chat",
        turn_id="turn-1",
        user_id="u1",
        role="assistant",
        message_kind="assistant_final",
        content_text="chat-store reply",
        created_at_ms=1020,
        sequence_no=2,
    )
    _init_event_store(service._l1_db_path)
    _insert_event(
        service._l1_db_path,
        "AIResponse",
        {"user_id": "u1", "session_id": "s-chat", "turn_id": "turn-1", "content": "legacy reply"},
        2,
    )

    messages = service.get_display_history("u1", "s-chat", limit=20)

    assert [item.kind for item in messages] == ["user", "assistant"]
    assert [item.content for item in messages] == ["chat-store user", "chat-store reply"]


def test_get_display_history_includes_turn_ux_trace_preferences(tmp_path, monkeypatch):
    service = _build_service(tmp_path)
    trace_service = ChatTraceReadService()
    trace_service._runtime_trace_db_path = tmp_path / "runtime_trace.db"
    trace_service._orchestrations_path = tmp_path / "task_orchestrations.json"
    monkeypatch.setattr(
        "magi.chat.read_service.get_chat_trace_read_service",
        lambda: trace_service,
    )
    _init_chat_session_store(service._chat_db_path)
    _insert_session(
        service._chat_db_path,
        session_id="s-chat",
        user_id="u1",
        title="Chat",
        created_at=1000,
        updated_at=1020,
        message_count=2,
    )
    _insert_chat_turn(
        service._chat_db_path,
        turn_id="turn-1",
        session_id="s-chat",
        user_id="u1",
        status="completed",
        response_mode="final_only",
        ux_plan_json='{"trace_display_mode":"none","allow_trace_collapse":false}',
        created_at_ms=1000,
        updated_at_ms=1020,
        completed_at_ms=1020,
    )
    _insert_chat_message(
        service._chat_db_path,
        message_id="msg-user",
        session_id="s-chat",
        turn_id="turn-1",
        user_id="u1",
        role="user",
        message_kind="user_text",
        content_text="chat-store user",
        created_at_ms=1000,
        sequence_no=1,
    )
    _insert_chat_message(
        service._chat_db_path,
        message_id="msg-assistant",
        session_id="s-chat",
        turn_id="turn-1",
        user_id="u1",
        role="assistant",
        message_kind="assistant_final",
        content_text="chat-store reply",
        created_at_ms=1020,
        sequence_no=2,
    )

    messages = service.get_display_history("u1", "s-chat", limit=20)

    assert messages[1].trace_display_mode == "none"
    assert messages[1].allow_trace_collapse is False


def test_get_display_history_keeps_replaced_interim_message_for_reload(tmp_path):
    service = _build_service(tmp_path)
    _init_chat_session_store(service._chat_db_path)
    _insert_session(
        service._chat_db_path,
        session_id="s-chat",
        user_id="u1",
        title="Chat",
        created_at=1000,
        updated_at=1030,
        message_count=3,
    )
    _insert_chat_turn(
        service._chat_db_path,
        turn_id="turn-1",
        session_id="s-chat",
        user_id="u1",
        status="completed",
        response_mode="final_only",
        created_at_ms=1000,
        updated_at_ms=1030,
        completed_at_ms=1030,
    )
    _insert_chat_message(
        service._chat_db_path,
        message_id="msg-user",
        session_id="s-chat",
        turn_id="turn-1",
        user_id="u1",
        role="user",
        message_kind="user_text",
        content_text="chat-store user",
        created_at_ms=1000,
        sequence_no=1,
    )
    _insert_chat_message(
        service._chat_db_path,
        message_id="msg-interim",
        session_id="s-chat",
        turn_id="turn-1",
        user_id="u1",
        role="assistant",
        message_kind="assistant_interim",
        content_text="让我仔细想想再回复你。",
        is_final=False,
        created_at_ms=1010,
        sequence_no=2,
        replaced_by_message_id="msg-final",
    )
    _insert_chat_message(
        service._chat_db_path,
        message_id="msg-final",
        session_id="s-chat",
        turn_id="turn-1",
        user_id="u1",
        role="assistant",
        message_kind="assistant_final",
        content_text="chat-store reply",
        created_at_ms=1030,
        sequence_no=3,
        replaces_message_id="msg-interim",
    )

    messages = service.get_display_history("u1", "s-chat", limit=20)

    assert [item.kind for item in messages] == ["user", "assistant", "assistant"]
    assert [item.message_kind for item in messages] == [
        "user_text",
        "assistant_interim",
        "assistant_final",
    ]
    assert [item.content for item in messages] == [
        "chat-store user",
        "让我仔细想想再回复你。",
        "chat-store reply",
    ]


def test_list_sessions_router_response(monkeypatch):
    class _FakeReadService:
        async def alist_sessions(self, user_id: str, limit: int = 30):
            assert user_id == "u1"
            assert limit == 5
            return [
                ChatSessionSummary(
                    session_id="s1",
                    title="Test",
                    last_message_preview="Hi",
                    last_user_message_preview="Hi",
                    title_overridden=False,
                    last_timestamp=123,
                    message_count=2,
                    workspace_path="/tmp/magi",
                    history_version=9,
                )
            ]

    monkeypatch.setattr(messages_sessions, "require_chat_read_service", lambda: _FakeReadService())

    result = __import__("asyncio").run(messages.list_sessions(user_id="u1", limit=5))
    assert result["user_id"] == "u1"
    assert result["count"] == 1
    assert result["sessions"][0]["history_version"] == 9


def test_list_sessions_exposes_workspace_path(tmp_path):
    service = _build_service(tmp_path)
    _init_chat_session_store(service._l1_db_path)
    _insert_session(
        service._l1_db_path,
        session_id="s1",
        user_id="u1",
        title="Workspace Chat",
        created_at=1000,
        updated_at=1010,
        workspace_path="/tmp/magi",
    )

    sessions = service.list_sessions("u1", limit=10)

    assert len(sessions) == 1
    assert sessions[0].workspace_path == "/tmp/magi"


def test_rename_session_router_response(monkeypatch):
    class _FakeReadService:
        async def arename_session(self, user_id: str, session_id: str, title: str):
            assert user_id == "u1"
            assert session_id == "s1"
            assert title == "Renamed"
            return ChatSessionRenameResult(session_id="s1", title="Renamed")

    monkeypatch.setattr(messages_sessions, "require_chat_read_service", lambda: _FakeReadService())

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
        async def adelete_session(self, user_id: str, session_id: str):
            assert user_id == "u1"
            assert session_id == "s1"
            return None

    monkeypatch.setattr(messages_sessions, "require_chat_read_service", lambda: _FakeReadService())

    result = __import__("asyncio").run(messages.delete_session(session_id="s1", user_id="u1"))

    assert result["success"] is True
    assert result["deleted_session_id"] == "s1"


def test_history_requires_explicit_session_id():
    with pytest.raises(messages.HTTPException) as exc_info:
        __import__("asyncio").run(messages.get_conversation_history(user_id="u1", session_id=None))

    assert exc_info.value.status_code == 400


def test_trace_requires_explicit_session_id():
    with pytest.raises(messages.HTTPException) as exc_info:
        __import__("asyncio").run(
            messages.get_execution_trace(user_id="u1", session_id=None, turn_id="turn-1")
        )

    assert exc_info.value.status_code == 400


def test_clear_history_requires_explicit_session_id():
    with pytest.raises(messages.HTTPException) as exc_info:
        __import__("asyncio").run(
            messages.clear_conversation_history(user_id="u1", session_id=None)
        )

    assert exc_info.value.status_code == 400


def test_get_display_history_surfaces_trace_status_instead_of_worker_messages(
    tmp_path, monkeypatch
):
    service = _build_service(tmp_path)
    trace_service = ChatTraceReadService()
    trace_service._runtime_trace_db_path = tmp_path / "runtime_trace.db"
    trace_service._orchestrations_path = tmp_path / "task_orchestrations.json"
    monkeypatch.setattr(
        "magi.chat.read_service.get_chat_trace_read_service",
        lambda: trace_service,
    )
    _init_chat_session_store(service._chat_db_path)
    _init_runtime_trace_store(trace_service._runtime_trace_db_path)

    _insert_session(
        service._chat_db_path,
        session_id="s1",
        user_id="u1",
        title="Task Chat",
        created_at=1000,
        updated_at=1010,
        message_count=1,
        last_message_at=1000,
        last_user_message_at=1000,
        last_message_preview="start task",
        last_user_message_preview="start task",
    )
    _insert_chat_turn(
        service._chat_db_path,
        turn_id="turn_1",
        session_id="s1",
        user_id="u1",
        status="running",
        response_mode="final_only",
        execution_mode="orchestration",
        created_at_ms=1000,
        updated_at_ms=1010,
    )
    _insert_chat_message(
        service._chat_db_path,
        message_id="msg-turn-1-user",
        session_id="s1",
        turn_id="turn_1",
        user_id="u1",
        role="user",
        message_kind="user_text",
        content_text="start task",
        created_at_ms=1000,
        sequence_no=1,
    )
    _insert_trace_turn(
        trace_service._runtime_trace_db_path,
        trace_id="trace:turn_1",
        turn_id="turn_1",
        session_id="s1",
        user_id="u1",
        status="running",
        mode="orchestration",
        started_at_ms=1000000,
        updated_at_ms=1010000,
        user_message_preview="start task",
    )
    _insert_trace_span(
        trace_service._runtime_trace_db_path,
        span_id="turn_1:worker_dispatch:subtask-1",
        trace_id="trace:turn_1",
        turn_id="turn_1",
        parent_span_id="turn_1:turn",
        node_type="worker_dispatch",
        name="Worker dispatch",
        status="completed",
        started_at_ms=1000000,
        ended_at_ms=1000000,
        duration_ms=0,
    )
    _insert_trace_span(
        trace_service._runtime_trace_db_path,
        span_id="turn_1:worker:subtask-1:1",
        trace_id="trace:turn_1",
        turn_id="turn_1",
        parent_span_id="turn_1:worker_dispatch:subtask-1",
        node_type="worker",
        name="Explore worker",
        status="running",
        started_at_ms=1000000,
        updated_at_ms=1010000,
        result_preview="scan codebase",
    )

    messages = service.get_display_history("u1", "s1", limit=20)

    assert [item.kind for item in messages] == ["user", "status"]
    assert messages[1].turn_id == "turn_1"
    assert messages[1].trace_available is True
    assert messages[1].trace_summary["headline"] == "Running tool chain"


def test_get_display_history_includes_control_status_messages(tmp_path, monkeypatch):
    service = _build_service(tmp_path)
    trace_service = ChatTraceReadService()
    trace_service._runtime_trace_db_path = tmp_path / "runtime_trace.db"
    trace_service._orchestrations_path = tmp_path / "task_orchestrations.json"
    monkeypatch.setattr(
        "magi.chat.read_service.get_chat_trace_read_service",
        lambda: trace_service,
    )
    _init_chat_session_store(service._chat_db_path)

    _insert_session(
        service._chat_db_path,
        session_id="s-control",
        user_id="u1",
        title="Control Chat",
        created_at=1000,
        updated_at=1040,
        message_count=5,
        last_message_at=1040,
        last_user_message_at=1000,
        last_message_preview="done",
        last_user_message_preview="please do the task",
    )
    _insert_chat_turn(
        service._chat_db_path,
        turn_id="turn-control",
        session_id="s-control",
        user_id="u1",
        status="completed",
        response_mode="final_only",
        created_at_ms=1000,
        updated_at_ms=1040,
        completed_at_ms=1040,
    )
    _insert_chat_message(
        service._chat_db_path,
        message_id="msg-user",
        session_id="s-control",
        turn_id="turn-control",
        user_id="u1",
        role="user",
        message_kind="user_text",
        content_text="please do the task",
        created_at_ms=1000,
        sequence_no=1,
    )
    _insert_chat_message(
        service._chat_db_path,
        message_id="msg-plan",
        session_id="s-control",
        turn_id="turn-control",
        user_id="u1",
        role="assistant",
        message_kind="plan_state",
        content_text="step 1\nstep 2",
        payload_json=json.dumps({"active": True, "plan_text": "step 1\nstep 2"}),
        created_at_ms=1010,
        sequence_no=2,
    )
    _insert_chat_message(
        service._chat_db_path,
        message_id="msg-todo",
        session_id="s-control",
        turn_id="turn-control",
        user_id="u1",
        role="assistant",
        message_kind="todo_state",
        content_text="first\nsecond",
        payload_json=json.dumps(
            {"items": [{"id": "1", "content": "first", "status": "in_progress"}]}
        ),
        created_at_ms=1020,
        sequence_no=3,
    )
    _insert_chat_message(
        service._chat_db_path,
        message_id="msg-permission",
        session_id="s-control",
        turn_id="turn-control",
        user_id="u1",
        role="assistant",
        message_kind="permission_request",
        content_text="bash",
        payload_json=json.dumps({"permission_request_id": "perm-1", "tool": "bash"}),
        created_at_ms=1030,
        sequence_no=4,
    )
    _insert_chat_message(
        service._chat_db_path,
        message_id="msg-ask",
        session_id="s-control",
        turn_id="turn-control",
        user_id="u1",
        role="assistant",
        message_kind="ask_request",
        content_text="Need confirmation?",
        payload_json=json.dumps({"ask_request_id": "ask-1", "question": "Need confirmation?"}),
        created_at_ms=1040,
        sequence_no=5,
    )
    _insert_chat_message(
        service._chat_db_path,
        message_id="msg-ask-response",
        session_id="s-control",
        turn_id="turn-control",
        user_id="u1",
        role="user",
        message_kind="ask_response",
        content_text="yes",
        payload_json=json.dumps({"ask_request_id": "ask-1", "answer": "yes"}),
        created_at_ms=1041,
        sequence_no=6,
        reply_to_message_id="msg-ask",
    )

    messages = service.get_display_history("u1", "s-control", limit=20)

    assert [item.kind for item in messages] == [
        "user",
        "status",
        "status",
        "status",
        "assistant",
        "user",
    ]
    assert [item.message_kind for item in messages[1:]] == [
        "plan_state",
        "todo_state",
        "permission_request",
        "ask_request",
        "ask_response",
    ]
    assert messages[1].payload == {"active": True, "plan_text": "step 1\nstep 2"}
    assert messages[2].payload == {
        "items": [{"id": "1", "content": "first", "status": "in_progress"}]
    }
    assert messages[-1].reply_to == {
        "message_id": "msg-ask",
        "role": "assistant",
        "message_kind": "ask_request",
        "content_excerpt": "Need confirmation?",
    }


def test_trace_summary_reads_runtime_trace_tool_rows(tmp_path, monkeypatch):
    service = _build_service(tmp_path)
    trace_service = ChatTraceReadService()
    trace_service._runtime_trace_db_path = tmp_path / "runtime_trace.db"
    trace_service._orchestrations_path = tmp_path / "task_orchestrations.json"
    monkeypatch.setattr(
        "magi.chat.read_service.get_chat_trace_read_service",
        lambda: trace_service,
    )
    _init_chat_session_store(service._chat_db_path)
    _init_runtime_trace_store(trace_service._runtime_trace_db_path)

    _insert_session(
        service._chat_db_path,
        session_id="s1",
        user_id="u1",
        title="Trace Chat",
        created_at=2000,
        updated_at=2010,
        message_count=2,
        last_message_at=2010,
        last_user_message_at=2000,
        last_message_preview="answer",
        last_user_message_preview="why",
    )
    _insert_chat_turn(
        service._chat_db_path,
        turn_id="turn_2",
        session_id="s1",
        user_id="u1",
        status="completed",
        response_mode="final_only",
        execution_mode="function_calling",
        created_at_ms=2000,
        updated_at_ms=2010,
        completed_at_ms=2010,
    )
    _insert_chat_message(
        service._chat_db_path,
        message_id="msg-turn-2-user",
        session_id="s1",
        turn_id="turn_2",
        user_id="u1",
        role="user",
        message_kind="user_text",
        content_text="why",
        created_at_ms=2000,
        sequence_no=1,
    )
    _insert_chat_message(
        service._chat_db_path,
        message_id="msg-turn-2-assistant",
        session_id="s1",
        turn_id="turn_2",
        user_id="u1",
        role="assistant",
        message_kind="assistant_final",
        content_text="answer",
        created_at_ms=2010,
        sequence_no=2,
    )
    _insert_trace_turn(
        trace_service._runtime_trace_db_path,
        trace_id="trace:turn_2",
        turn_id="turn_2",
        session_id="s1",
        user_id="u1",
        status="completed",
        mode="function_calling",
        started_at_ms=2000000,
        ended_at_ms=2010000,
        duration_ms=10000,
        user_message_preview="why",
        response_preview="answer",
    )
    _insert_trace_span(
        trace_service._runtime_trace_db_path,
        span_id="turn_2:iteration:1",
        trace_id="trace:turn_2",
        turn_id="turn_2",
        parent_span_id="turn_2:turn",
        node_type="iteration",
        name="Iteration 1",
        status="completed",
        iteration=1,
        started_at_ms=2000000,
        ended_at_ms=2008000,
        duration_ms=8000,
    )
    _insert_trace_span(
        trace_service._runtime_trace_db_path,
        span_id="turn_2:tool_call:1:call-1",
        trace_id="trace:turn_2",
        turn_id="turn_2",
        parent_span_id="turn_2:iteration:1",
        node_type="tool_call",
        name="grep",
        status="completed",
        iteration=1,
        started_at_ms=2005000,
        ended_at_ms=2005200,
        duration_ms=200,
        result_preview="success",
    )
    _insert_trace_tool(
        trace_service._runtime_trace_db_path,
        span_id="turn_2:tool_call:1:call-1",
        trace_id="trace:turn_2",
        turn_id="turn_2",
        tool_name="grep",
        tool_call_id="call-1",
        arguments={"path": "/tmp/demo.py", "pattern": "qweather"},
        execution_time_ms=3,
        result_preview="success",
    )

    messages = service.get_display_history("u1", "s1", limit=20)

    assert [item.kind for item in messages] == ["user", "assistant"]
    assert messages[1].trace_available is True
    assert messages[1].trace_summary["mode"] == "function_calling"

    snapshot = trace_service.get_trace_snapshot(user_id="u1", session_id="s1", turn_id="turn_2")

    assert snapshot is not None
    assert snapshot["summary"]["trace_available"] is True
    assert snapshot["root"]["children"][0]["children"][0]["label"] == "grep"
    assert (
        snapshot["root"]["children"][0]["children"][0]["metadata"]["arguments"]["pattern"]
        == "qweather"
    )


def test_trace_snapshot_reads_runtime_trace_store_without_ai_response(tmp_path):
    service = ChatTraceReadService()
    service._runtime_trace_db_path = tmp_path / "runtime_trace.db"
    service._orchestrations_path = tmp_path / "task_orchestrations.json"
    _init_runtime_trace_store(service._runtime_trace_db_path)
    _insert_trace_turn(
        service._runtime_trace_db_path,
        trace_id="trace:turn_trace",
        turn_id="turn_trace",
        session_id="s1",
        user_id="u1",
        status="completed",
        mode="orchestration",
        orchestration_id="orch_trace",
        started_at_ms=3000000,
        ended_at_ms=3001200,
        duration_ms=1200,
        response_preview="done",
    )
    _insert_trace_span(
        service._runtime_trace_db_path,
        span_id="turn_trace:intent",
        trace_id="trace:turn_trace",
        turn_id="turn_trace",
        parent_span_id="turn_trace:turn",
        node_type="intent_resolution",
        name="Intent resolution",
        status="completed",
        started_at_ms=3000000,
        ended_at_ms=3000100,
        duration_ms=100,
        result_preview="code_research",
    )
    _insert_trace_span(
        service._runtime_trace_db_path,
        span_id="turn_trace:worker_dispatch:worker_1",
        trace_id="trace:turn_trace",
        turn_id="turn_trace",
        parent_span_id="turn_trace:turn",
        node_type="worker_dispatch",
        name="Worker dispatch",
        status="completed",
        started_at_ms=3000200,
        ended_at_ms=3000200,
        duration_ms=0,
    )
    _insert_trace_span(
        service._runtime_trace_db_path,
        span_id="turn_trace:worker:worker_1",
        trace_id="trace:turn_trace",
        turn_id="turn_trace",
        parent_span_id="turn_trace:worker_dispatch:worker_1",
        node_type="worker",
        name="Explore worker",
        status="completed",
        started_at_ms=3000200,
        ended_at_ms=3000900,
        duration_ms=700,
        result_preview="worker finished",
    )
    _insert_trace_span(
        service._runtime_trace_db_path,
        span_id="turn_trace:worker_llm:worker_1:final_response:1",
        trace_id="trace:turn_trace",
        turn_id="turn_trace",
        parent_span_id="turn_trace:worker:worker_1",
        node_type="llm_call",
        name="Explore worker LLM call",
        status="completed",
        started_at_ms=3000300,
        ended_at_ms=3000810,
        duration_ms=510,
    )
    _insert_trace_llm_call(
        service._runtime_trace_db_path,
        span_id="turn_trace:worker_llm:worker_1:final_response:1",
        trace_id="trace:turn_trace",
        turn_id="turn_trace",
        model="fake-model",
        input_tokens=30,
        output_tokens=12,
    )
    _insert_trace_span(
        service._runtime_trace_db_path,
        span_id="turn_trace:worker_tool:worker_1:grep",
        trace_id="trace:turn_trace",
        turn_id="turn_trace",
        parent_span_id="turn_trace:worker:worker_1",
        node_type="tool_call",
        name="grep tool call",
        status="completed",
        started_at_ms=3000820,
        ended_at_ms=3000850,
        duration_ms=30,
        result_preview="match count: 3",
    )
    _insert_trace_tool(
        service._runtime_trace_db_path,
        span_id="turn_trace:worker_tool:worker_1:grep",
        trace_id="trace:turn_trace",
        turn_id="turn_trace",
        tool_name="grep",
        tool_call_id="grep-call",
        result_preview="match count: 3",
    )
    _insert_trace_span(
        service._runtime_trace_db_path,
        span_id="turn_trace:response_emit",
        trace_id="trace:turn_trace",
        turn_id="turn_trace",
        parent_span_id="turn_trace:turn",
        node_type="response_emit",
        name="Response emitted",
        status="completed",
        started_at_ms=3001000,
        ended_at_ms=3001100,
        duration_ms=100,
        result_preview="done",
    )

    snapshot = service.get_trace_snapshot(user_id="u1", session_id="s1", turn_id="turn_trace")

    assert snapshot is not None
    assert snapshot["summary"]["trace_available"] is True
    assert snapshot["summary"]["mode"] == "orchestration"
    assert snapshot["summary"]["status"] == "completed"
    assert snapshot["summary"]["duration_seconds"] == 1.2

    child_kinds = {child["kind"] for child in snapshot["root"]["children"]}
    assert {"intent", "planning", "response"} <= child_kinds

    planning_node = next(
        child for child in snapshot["root"]["children"] if child["kind"] == "planning"
    )
    dispatch_node = planning_node["children"][0]
    assert dispatch_node["kind"] == "dispatch"
    worker_node = dispatch_node["children"][0]
    assert worker_node["kind"] == "worker"
    worker_child_kinds = {child["kind"] for child in worker_node["children"]}
    assert {"llm", "tool"} <= worker_child_kinds


def test_trace_snapshot_groups_worker_retry_attempts_from_normalized_spans(tmp_path):
    service = ChatTraceReadService()
    service._runtime_trace_db_path = tmp_path / "runtime_trace.db"
    service._orchestrations_path = tmp_path / "task_orchestrations.json"
    _init_runtime_trace_store(service._runtime_trace_db_path)
    _insert_trace_turn(
        service._runtime_trace_db_path,
        trace_id="trace:turn_retry",
        turn_id="turn_retry",
        session_id="s1",
        user_id="u1",
        status="completed",
        mode="orchestration",
        orchestration_id="orch_retry",
        started_at_ms=4000000,
        ended_at_ms=4001000,
        duration_ms=1000,
    )
    _insert_trace_span(
        service._runtime_trace_db_path,
        span_id="turn_retry:worker_dispatch:subtask_1",
        trace_id="trace:turn_retry",
        turn_id="turn_retry",
        parent_span_id="turn_retry:turn",
        node_type="worker_dispatch",
        name="Worker dispatch",
        status="completed",
        started_at_ms=4000000,
        ended_at_ms=4000000,
        duration_ms=0,
    )
    _insert_trace_span(
        service._runtime_trace_db_path,
        span_id="turn_retry:worker_attempt:subtask_1:1",
        trace_id="trace:turn_retry",
        turn_id="turn_retry",
        parent_span_id="turn_retry:worker_dispatch:subtask_1",
        node_type="worker_attempt",
        name="Attempt 1",
        status="failed",
        attempt_index=1,
        retry_count=0,
        started_at_ms=4000000,
        ended_at_ms=4000300,
        duration_ms=300,
        error_text="rate limited",
    )
    _insert_trace_span(
        service._runtime_trace_db_path,
        span_id="turn_retry:worker_attempt:subtask_1:2",
        trace_id="trace:turn_retry",
        turn_id="turn_retry",
        parent_span_id="turn_retry:worker_dispatch:subtask_1",
        node_type="worker_attempt",
        name="Attempt 2",
        status="completed",
        attempt_index=2,
        retry_count=1,
        started_at_ms=4000400,
        ended_at_ms=4000900,
        duration_ms=500,
    )

    snapshot = service.get_trace_snapshot(user_id="u1", session_id="s1", turn_id="turn_retry")

    assert snapshot is not None
    planning_node = next(
        child for child in snapshot["root"]["children"] if child["kind"] == "planning"
    )
    dispatch_node = planning_node["children"][0]
    attempt_nodes = dispatch_node["children"]
    assert len(attempt_nodes) == 2
    assert [item["kind"] for item in attempt_nodes] == ["attempt", "attempt"]
    assert attempt_nodes[0]["status"] == "failed"
    assert attempt_nodes[1]["status"] == "completed"
    assert attempt_nodes[1]["metadata"]["attempt_index"] == 2
    assert attempt_nodes[1]["metadata"]["retry_count"] == 1


def test_trace_snapshot_groups_parallel_workers_and_tools(tmp_path):
    service = ChatTraceReadService()
    service._runtime_trace_db_path = tmp_path / "runtime_trace.db"
    service._orchestrations_path = tmp_path / "task_orchestrations.json"
    _init_runtime_trace_store(service._runtime_trace_db_path)
    _insert_trace_turn(
        service._runtime_trace_db_path,
        trace_id="trace:turn_1",
        turn_id="turn_1",
        session_id="s1",
        user_id="u1",
        status="completed",
        mode="orchestration",
        orchestration_id="orch_1",
        started_at_ms=1000000,
        ended_at_ms=1030000,
        duration_ms=30000,
        response_preview="final answer",
    )
    _insert_trace_span(
        service._runtime_trace_db_path,
        span_id="turn_1:worker_dispatch:sub_1",
        trace_id="trace:turn_1",
        turn_id="turn_1",
        parent_span_id="turn_1:turn",
        node_type="worker_dispatch",
        name="Worker dispatch",
        status="completed",
        started_at_ms=1000000,
        ended_at_ms=1000000,
        duration_ms=0,
    )
    _insert_trace_span(
        service._runtime_trace_db_path,
        span_id="turn_1:worker:sub_1:1",
        trace_id="trace:turn_1",
        turn_id="turn_1",
        parent_span_id="turn_1:worker_dispatch:sub_1",
        node_type="worker",
        name="scan backend",
        status="completed",
        started_at_ms=1001000,
        ended_at_ms=1015000,
        duration_ms=14000,
        result_preview="backend summary",
    )
    _insert_trace_span(
        service._runtime_trace_db_path,
        span_id="turn_1:worker_tool:sub_1:1:call-1",
        trace_id="trace:turn_1",
        turn_id="turn_1",
        parent_span_id="turn_1:worker:sub_1:1",
        node_type="tool_call",
        name="grep tool call",
        status="completed",
        started_at_ms=1014000,
        ended_at_ms=1015000,
        duration_ms=1000,
        result_preview="match count: 3",
    )
    _insert_trace_tool(
        service._runtime_trace_db_path,
        span_id="turn_1:worker_tool:sub_1:1:call-1",
        trace_id="trace:turn_1",
        turn_id="turn_1",
        tool_name="grep",
        tool_call_id="call-1",
        result_preview="match count: 3",
    )

    snapshot = service.get_trace_snapshot(user_id="u1", session_id="s1", turn_id="turn_1")

    assert snapshot is not None
    assert snapshot["summary"]["trace_available"] is True
    assert snapshot["summary"]["mode"] == "orchestration"
    assert snapshot["summary"]["status"] == "completed"
    planning = snapshot["root"]["children"][0]
    assert planning["kind"] == "planning"
    dispatch = planning["children"][0]
    assert dispatch["kind"] == "dispatch"
    assert dispatch["status"] == "completed"
    worker = dispatch["children"][0]
    assert worker["kind"] == "worker"
    assert worker["children"][0]["label"] == "grep tool call"


def test_trace_summary_counts_active_intent_before_response(tmp_path):
    service = ChatTraceReadService()
    service._runtime_trace_db_path = tmp_path / "runtime_trace.db"
    service._orchestrations_path = tmp_path / "task_orchestrations.json"
    _init_runtime_trace_store(service._runtime_trace_db_path)
    _insert_trace_turn(
        service._runtime_trace_db_path,
        trace_id="trace:turn_plan",
        turn_id="turn_plan",
        session_id="s1",
        user_id="u1",
        status="running",
        mode="function_calling",
        started_at_ms=1000000,
        updated_at_ms=1005000,
        user_message_preview="plan this",
    )
    _insert_trace_span(
        service._runtime_trace_db_path,
        span_id="turn_plan:intent",
        trace_id="trace:turn_plan",
        turn_id="turn_plan",
        parent_span_id="turn_plan:turn",
        node_type="intent_resolution",
        name="Intent resolution",
        status="completed",
        started_at_ms=1000000,
        ended_at_ms=1000100,
        duration_ms=100,
        result_preview="planning",
    )

    summary = service.get_trace_summary(user_id="u1", session_id="s1", turn_id="turn_plan")

    assert summary is not None
    assert summary["headline"] == "Running tool chain"
    assert summary["active_steps"] == 0
    assert summary["completed_steps"] == 1


def test_trace_summary_exposes_orchestration_plan_preview(tmp_path):
    service = ChatTraceReadService()
    service._runtime_trace_db_path = tmp_path / "runtime_trace.db"
    service._orchestrations_path = tmp_path / "task_orchestrations.json"
    _init_runtime_trace_store(service._runtime_trace_db_path)
    _insert_trace_turn(
        service._runtime_trace_db_path,
        trace_id="trace:turn_plan_preview",
        turn_id="turn_plan_preview",
        session_id="s1",
        user_id="u1",
        status="running",
        mode="orchestration",
        orchestration_id="orch_plan_preview",
        started_at_ms=1000000,
        updated_at_ms=1005000,
        user_message_preview="plan this",
    )
    service._orchestrations_path.write_text(
        json.dumps(
            {
                "orchestrations": {
                    "orch_plan_preview": {
                        "planner": "task_agent",
                        "allow_parallel": True,
                        "subtasks": [
                            {
                                "subtask_id": "subtask_1",
                                "description": "梳理现有文档和范围",
                                "status": "completed",
                            },
                            {
                                "subtask_id": "subtask_2",
                                "description": "盘点代码结构与运行方式",
                                "status": "running",
                            },
                            {
                                "subtask_id": "subtask_3",
                                "description": "整理 MVP 验收清单",
                                "status": "pending",
                            },
                            {
                                "subtask_id": "subtask_4",
                                "description": "输出优先级建议",
                                "status": "pending",
                            },
                        ],
                    }
                }
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    summary = service.get_trace_summary(user_id="u1", session_id="s1", turn_id="turn_plan_preview")

    assert summary is not None
    assert summary["plan_summary"] == {
        "planner": "task_agent",
        "parallel_mode": "parallel",
        "total_steps": 4,
        "remaining_steps": 1,
        "steps": [
            {
                "subtask_id": "subtask_1",
                "label": "梳理现有文档和范围",
                "status": "completed",
            },
            {
                "subtask_id": "subtask_2",
                "label": "盘点代码结构与运行方式",
                "status": "running",
            },
            {
                "subtask_id": "subtask_3",
                "label": "整理 MVP 验收清单",
                "status": "pending",
            },
        ],
    }


def test_trace_snapshot_exposes_continuation_metadata(tmp_path):
    service = ChatTraceReadService()
    service._runtime_trace_db_path = tmp_path / "runtime_trace.db"
    service._orchestrations_path = tmp_path / "task_orchestrations.json"
    _init_runtime_trace_store(service._runtime_trace_db_path)
    _insert_trace_turn(
        service._runtime_trace_db_path,
        trace_id="trace:turn_2",
        turn_id="turn_2",
        session_id="s1",
        user_id="u1",
        status="interrupted",
        mode="function_calling",
        started_at_ms=1000000,
        ended_at_ms=1002000,
        duration_ms=2000,
        continued_from_turn_id="turn_1",
        continued_from_trace_id="trace:turn_1",
        superseded_by_turn_id="turn_3",
        supersession_reason="interrupted",
    )
    _insert_trace_span(
        service._runtime_trace_db_path,
        span_id="turn_2:turn",
        trace_id="trace:turn_2",
        turn_id="turn_2",
        parent_span_id=None,
        node_type="turn",
        name="Chat turn",
        status="interrupted",
        started_at_ms=1000000,
        ended_at_ms=1002000,
        duration_ms=2000,
    )

    snapshot = service.get_trace_snapshot(user_id="u1", session_id="s1", turn_id="turn_2")

    assert snapshot is not None
    assert snapshot["status"] == "interrupted"
    assert snapshot["continued_from_turn_id"] == "turn_1"
    assert snapshot["continued_from_trace_id"] == "trace:turn_1"
    assert snapshot["superseded_by_turn_id"] == "turn_3"
    assert snapshot["supersession_reason"] == "interrupted"
    assert snapshot["summary"]["continued_from_turn_id"] == "turn_1"
    assert snapshot["summary"]["superseded_by_turn_id"] == "turn_3"
