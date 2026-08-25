import json
import sqlite3
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest

BACKEND_SRC = Path(__file__).resolve().parents[1] / "src"
if str(BACKEND_SRC) not in sys.path:
    sys.path.insert(0, str(BACKEND_SRC))

from magi.api.routers import messages, messages_sessions  # noqa: E402
from magi.chat import ChatStore  # noqa: E402
from magi.chat.forgetting import ChatHistoryClearResult  # noqa: E402
from magi.core.chat_cleanup import ChatSurfaceCleanupPendingError  # noqa: E402
from magi.chat.read_service import (  # noqa: E402
    ChatReadService,
    ChatSessionRenameResult,
    ChatSessionSummary,
)
from magi.runtime_trace.chat_trace.read_service import ChatTraceReadService  # noqa: E402

FACT_EVENTS_TABLE = "fact_events"
CHAT_SESSIONS_TABLE = "chat_sessions"
CHAT_SESSION_CREATION_REQUESTS_TABLE = "chat_session_creation_requests"
CHAT_TURNS_TABLE = "chat_turns"
CHAT_MESSAGES_TABLE = "chat_messages"
CHAT_CONTEXT_SUMMARIES_TABLE = "chat_context_summaries"
CHAT_RUN_CONSUMED_EVENTS_TABLE = "chat_run_consumed_events"


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
            turn_id, session_id, user_id, trace_id, status,
            response_mode, execution_mode, ux_plan_json, created_at_ms, updated_at_ms,
            completed_at_ms, error_text, run_id, run_revision, run_disposition
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        tuple(payload.values()),
    )
    conn.commit()
    conn.close()


def _insert_consumed_event(
    db_path: Path,
    *,
    session_id: str,
    run_id: str,
    message_id: str,
) -> None:
    conn = sqlite3.connect(str(db_path))
    conn.execute(
        f"""
        INSERT INTO {CHAT_RUN_CONSUMED_EVENTS_TABLE} (
            session_id, run_id, revision, message_id, recorded_at_ms
        ) VALUES (?, ?, 0, ?, 1)
        """,
        (session_id, run_id, message_id),
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
            trace_id, turn_id, session_id, user_id, status, mode,
            started_at_ms, ended_at_ms, duration_ms, user_message_preview, response_preview,
            error_summary, continued_from_turn_id, continued_from_trace_id,
            superseded_by_turn_id, supersession_reason, created_at_ms, updated_at_ms
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
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
    from magi.chat.asset_gc import ChatAssetGC
    from magi.utils.runtime import RuntimePaths

    service = ChatReadService()
    db_path = tmp_path / "chat.sqlite3"
    service._chat_db_path = db_path
    service._l1_db_path = db_path
    service._asset_gc = ChatAssetGC(runtime_paths=RuntimePaths(tmp_path / "runtime"))

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
    service._runtime_trace_db_path = trace_db
    trace_service = ChatTraceReadService()
    trace_service._runtime_trace_db_path = trace_db
    trace_service._l1_db_path = tmp_path / "l1_events.db"
    container = get_container()
    container.chat_trace_read_service.reset()
    from dependency_injector import providers as _providers

    container.chat_trace_read_service.override(_providers.Object(trace_service))
    return service


def _count_table_rows(db_path: Path, table: str) -> int:
    conn = sqlite3.connect(str(db_path))
    try:
        row = conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()
        return int(row[0] if row is not None else 0)
    finally:
        conn.close()


def test_clear_all_sessions_removes_chat_traces_and_user_notifications(
    tmp_path,
    monkeypatch,
):
    service = _build_service(tmp_path)
    service._runtime_trace_db_path = tmp_path / "runtime_trace.db"
    monkeypatch.setattr(service, "_clear_all_chat_assets", lambda: None)
    _init_chat_session_store(service._chat_db_path)
    _insert_session(
        service._chat_db_path,
        session_id="s1",
        user_id="u1",
        title="Chat",
    )
    _insert_chat_turn(
        service._chat_db_path,
        turn_id="turn-1",
        session_id="s1",
        user_id="u1",
        trace_id="trace-1",
    )
    _insert_chat_message(
        service._chat_db_path,
        message_id="message-1",
        session_id="s1",
        turn_id="turn-1",
        user_id="u1",
        role="user",
        message_kind="text",
        content_text="hello",
    )
    _insert_consumed_event(
        service._chat_db_path,
        session_id="s1",
        run_id="run-1",
        message_id="message-1",
    )
    chat_conn = sqlite3.connect(str(service._chat_db_path))
    chat_conn.execute(f"""
        INSERT INTO {CHAT_SESSION_CREATION_REQUESTS_TABLE} (
            user_id, idempotency_key, session_id, created_at_ms
        ) VALUES ('u1', 'first-context-request', 's1', 1)
        """)
    chat_conn.execute(f"""
        INSERT INTO {CHAT_CONTEXT_SUMMARIES_TABLE} (
            summary_id, session_id, status, summary_kind, summary_text,
            prompt_profile, created_at_ms, updated_at_ms
        ) VALUES ('summary-1', 's1', 'active', 'rolling',
                  'private conversation summary', 'general_chat', 1, 1)
        """)
    chat_conn.commit()
    chat_conn.close()

    conn = sqlite3.connect(str(service._runtime_trace_db_path))
    conn.execute("""
        INSERT INTO trace_turns (
            trace_id, turn_id, session_id, user_id, status, mode,
            started_at_ms, created_at_ms, updated_at_ms
        ) VALUES ('trace-1', 'turn-1', 's1', 'u1', 'completed', 'chat', 1, 1, 1)
        """)
    conn.execute("""
        INSERT INTO trace_spans (
            span_id, trace_id, turn_id, node_type, name, status,
            started_at_ms, created_at_ms, updated_at_ms
        ) VALUES ('span-1', 'trace-1', 'turn-1', 'llm', 'model', 'completed', 1, 1, 1)
        """)
    conn.execute("""
        INSERT INTO trace_llm_calls (
            span_id, trace_id, turn_id, provider, model
        ) VALUES ('span-1', 'trace-1', 'turn-1', 'test', 'test-model')
        """)
    conn.execute("""
        INSERT INTO trace_tools (
            span_id, trace_id, turn_id, tool_name, arguments_json, success
        ) VALUES ('span-1', 'trace-1', 'turn-1', 'test-tool', '{}', 1)
        """)
    conn.execute("""
        INSERT INTO agent_run_manifests (
            run_id, turn_id, session_id, user_id, manifest_json,
            created_at_ms, updated_at_ms
        ) VALUES ('run-1', 'turn-1', 's1', 'u1', '{}', 1, 1)
        """)
    conn.execute("""
        INSERT INTO agent_run_events (
            event_id, run_id, sequence, turn_id, session_id, user_id,
            event_type, payload_json, created_at_ms
        ) VALUES ('event-1', 'run-1', 1, 'turn-1', 's1', 'u1',
                  'run_completed', '{}', 1)
        """)
    conn.execute("""
        INSERT INTO run_plans (
            plan_id, run_id, session_id, version, required, status,
            plan_json, created_at_ms, updated_at_ms
        ) VALUES ('plan-1', 'run-1', 's1', 1, 1, 'completed', '{}', 1, 1)
        """)
    conn.execute("""
        INSERT INTO runtime_notifications (
            channel, user_id, session_id, payload_json, created_at_ms
        ) VALUES ('chat_message_upserted', 'u1', 's1', '{}', 1)
        """)
    conn.execute("""
        INSERT INTO runtime_notifications (
            channel, user_id, session_id, turn_id, payload_json, created_at_ms
        ) VALUES ('global_control', 'u1', '', NULL, '{}', 1)
        """)
    conn.execute("""
        INSERT INTO plugin_ingress_events (
            source_kind, producer, plugin_target, event_type, occurred_at_ms,
            payload_json, status, created_at_ms
        ) VALUES ('sensor', 'plugin', 'calendar', 'event', 1, '{}', 'pending', 1)
        """)
    conn.execute("""
        INSERT INTO user_notifications (
            user_id, kind, dedupe_key, title, body, created_at_ms
        ) VALUES ('u1', 'suggestion', 'keep-me', 'title', 'body', 1)
        """)
    conn.execute("""
        INSERT INTO user_notifications (
            user_id, kind, dedupe_key, title, body, created_at_ms
        ) VALUES (
            'u1', 'suggestion', 'profile_conflict:identity.name:',
            'Private conflict', 'Private memory conflict', 1
        )
        """)
    conn.commit()
    conn.close()

    removed = service.clear_all_sessions()

    assert removed == 1
    for table in (
        CHAT_SESSIONS_TABLE,
        CHAT_SESSION_CREATION_REQUESTS_TABLE,
        CHAT_TURNS_TABLE,
        CHAT_MESSAGES_TABLE,
        CHAT_CONTEXT_SUMMARIES_TABLE,
        CHAT_RUN_CONSUMED_EVENTS_TABLE,
    ):
        assert _count_table_rows(service._chat_db_path, table) == 0
    for table in (
        "run_plans",
        "agent_run_events",
        "agent_run_manifests",
        "trace_turns",
        "trace_spans",
        "trace_llm_calls",
        "trace_tools",
    ):
        assert _count_table_rows(service._runtime_trace_db_path, table) == 0
    assert _count_table_rows(service._runtime_trace_db_path, "runtime_notifications") == 0
    assert _count_table_rows(service._runtime_trace_db_path, "plugin_ingress_events") == 1
    assert _count_table_rows(service._runtime_trace_db_path, "user_notifications") == 0


def test_runtime_trace_scope_deletion_removes_matching_run_plans(tmp_path) -> None:
    service = _build_service(tmp_path)
    conn = sqlite3.connect(str(service._runtime_trace_db_path))
    conn.executemany(
        """
        INSERT INTO agent_run_manifests (
            run_id, turn_id, session_id, user_id, manifest_json,
            created_at_ms, updated_at_ms
        ) VALUES (?, ?, ?, 'u1', '{}', 1, 1)
        """,
        (
            ("run-1", "turn-1", "s1"),
            ("run-2", "turn-2", "s1"),
            ("run-3", "turn-3", "s2"),
        ),
    )
    conn.executemany(
        """
        INSERT INTO run_plans (
            plan_id, run_id, session_id, version, required, status,
            plan_json, created_at_ms, updated_at_ms
        ) VALUES (?, ?, ?, 1, 1, 'active', '{}', 1, 1)
        """,
        (
            ("plan-1", "run-1", "s1"),
            ("plan-2", "run-2", "s1"),
            ("plan-3", "run-3", "s2"),
        ),
    )
    conn.commit()
    conn.close()

    service._delete_runtime_trace_turn_rows(
        user_id="u1",
        session_id="s1",
        turn_id="turn-1",
    )
    conn = sqlite3.connect(str(service._runtime_trace_db_path))
    assert {
        row[0] for row in conn.execute("SELECT plan_id FROM run_plans")
    } == {"plan-2", "plan-3"}
    conn.close()

    service._delete_runtime_trace_rows(user_id="u1", session_id="s1")
    conn = sqlite3.connect(str(service._runtime_trace_db_path))
    assert conn.execute("SELECT plan_id FROM run_plans").fetchall() == [("plan-3",)]
    conn.close()


def test_clear_all_sessions_keeps_chat_rows_when_trace_cleanup_fails(
    tmp_path,
    monkeypatch,
):
    service = _build_service(tmp_path)
    asset_cleanup_calls: list[bool] = []
    monkeypatch.setattr(
        service,
        "_clear_all_chat_assets",
        lambda: asset_cleanup_calls.append(True),
    )
    _init_chat_session_store(service._chat_db_path)
    _insert_session(
        service._chat_db_path,
        session_id="s1",
        user_id="u1",
        title="Chat",
    )

    def _fail_trace_cleanup() -> None:
        raise RuntimeError("trace cleanup failed")

    monkeypatch.setattr(service, "_clear_all_runtime_trace_rows", _fail_trace_cleanup)

    with pytest.raises(RuntimeError, match="trace cleanup failed"):
        service.clear_all_sessions()

    assert _count_table_rows(service._chat_db_path, CHAT_SESSIONS_TABLE) == 1
    assert asset_cleanup_calls == []


def test_clear_all_sessions_removes_traces_when_chat_database_is_absent(
    tmp_path,
    monkeypatch,
):
    service = _build_service(tmp_path)
    service._runtime_trace_db_path = tmp_path / "runtime_trace.db"
    monkeypatch.setattr(service, "_clear_all_chat_assets", lambda: None)
    assert not service._chat_db_path.exists()
    _insert_trace_turn(
        service._runtime_trace_db_path,
        trace_id="trace-orphan",
        turn_id="turn-orphan",
        session_id="session-orphan",
        user_id="u1",
    )

    removed = service.clear_all_sessions()

    assert removed == 0
    assert _count_table_rows(service._runtime_trace_db_path, "trace_turns") == 0


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


def test_create_new_session_with_idempotency_key_returns_server_id_and_is_idempotent(
    tmp_path,
):
    service = _build_service(tmp_path)
    _init_chat_session_store(service._chat_db_path)

    first = service.create_new_session(
        "u1",
        workspace_path="/tmp/magi",
        idempotency_key="first_context_1",
    )
    second = service.create_new_session(
        "u1",
        workspace_path="/tmp/changed",
        idempotency_key="first_context_1",
    )

    assert first == second
    assert first.startswith("session_")
    assert first != "first_context_1"
    with sqlite3.connect(service._chat_db_path) as conn:
        assert conn.execute(
            "SELECT COUNT(*) FROM chat_sessions WHERE session_id = ?",
            (first,),
        ).fetchone() == (1,)
        assert conn.execute(
            "SELECT workspace_path FROM chat_sessions WHERE session_id = ?",
            (first,),
        ).fetchone() == ("/tmp/magi",)
        assert conn.execute(
            """
            SELECT session_id
            FROM chat_session_creation_requests
            WHERE user_id = ? AND idempotency_key = ?
            """,
            ("u1", "first_context_1"),
        ).fetchone() == (first,)


def test_create_new_session_scopes_idempotency_key_by_user(tmp_path):
    service = _build_service(tmp_path)
    _init_chat_session_store(service._chat_db_path)
    first = service.create_new_session(
        "u1",
        idempotency_key="first_context_1",
    )
    second = service.create_new_session(
        "u2",
        idempotency_key="first_context_1",
    )

    assert first != second


def test_create_new_session_with_idempotency_key_is_idempotent_under_concurrency(
    tmp_path,
):
    first_service = _build_service(tmp_path)
    second_service = _build_service(tmp_path)
    _init_chat_session_store(first_service._chat_db_path)

    def _create_and_close(service):  # type: ignore[no-untyped-def]
        try:
            return service.create_new_session(
                "u1",
                "/tmp/magi",
                "first_context_1",
            )
        finally:
            service.close()

    with ThreadPoolExecutor(max_workers=2) as executor:
        futures = [
            executor.submit(_create_and_close, service)
            for service in (first_service, second_service)
        ]
        session_ids = [future.result(timeout=2) for future in futures]

    assert session_ids[0] == session_ids[1]
    assert session_ids[0].startswith("session_")
    with sqlite3.connect(first_service._chat_db_path) as conn:
        assert conn.execute(
            "SELECT COUNT(*) FROM chat_sessions WHERE session_id = ?",
            (session_ids[0],),
        ).fetchone() == (1,)
        assert conn.execute(
            """
            SELECT COUNT(*)
            FROM chat_session_creation_requests
            WHERE user_id = ? AND idempotency_key = ?
            """,
            ("u1", "first_context_1"),
        ).fetchone() == (1,)


@pytest.mark.parametrize("terminal_column", ["archived_at_ms", "deleted_at_ms"])
def test_create_new_session_rejects_reuse_after_terminal_state(tmp_path, terminal_column):
    service = _build_service(tmp_path)
    _init_chat_session_store(service._chat_db_path)
    session_id = service.create_new_session(
        "u1",
        idempotency_key="first_context_1",
    )
    with sqlite3.connect(service._chat_db_path) as conn:
        conn.execute(
            f"UPDATE chat_sessions SET {terminal_column} = 123 WHERE session_id = ?",
            (session_id,),
        )
        conn.commit()

    with pytest.raises(ValueError, match="not available"):
        service.create_new_session(
            "u1",
            idempotency_key="first_context_1",
        )


@pytest.mark.parametrize(
    "idempotency_key",
    ["contains space", "slash/value", "x" * 129],
)
def test_create_new_session_rejects_invalid_idempotency_key(tmp_path, idempotency_key):
    service = _build_service(tmp_path)
    _init_chat_session_store(service._chat_db_path)

    with pytest.raises(ValueError, match="Idempotency key"):
        service.create_new_session("u1", idempotency_key=idempotency_key)


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


def test_get_display_history_restores_controlled_first_context_payload(tmp_path):
    service = _build_service(tmp_path)
    _init_chat_session_store(service._chat_db_path)
    _insert_session(
        service._chat_db_path,
        session_id="s1",
        user_id="u1",
        title="First Context Chat",
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
    first_context = {
        "question_id": "preferred_name",
        "question_text": "希望 Magi 平时怎么称呼你？昵称就可以。",
    }
    _insert_chat_message(
        service._chat_db_path,
        message_id="msg-1",
        session_id="s1",
        turn_id="turn-1",
        user_id="u1",
        role="user",
        message_kind="user_text",
        content_text="明日香",
        payload_json=json.dumps(
            {
                "interaction_kind": "first_context_story",
                "first_context": first_context,
                "internal_note": "must not reach the client",
            }
        ),
        created_at_ms=1000,
    )

    history = service.get_display_history("u1", "s1", limit=10)

    assert history[0].payload == {
        "interaction_kind": "first_context_story",
        "first_context": first_context,
    }


def test_get_display_history_restores_reasoning_preference(tmp_path):
    service = _build_service(tmp_path)
    _init_chat_session_store(service._chat_db_path)
    _insert_session(
        service._chat_db_path,
        session_id="s1",
        user_id="u1",
        title="Fast Chat",
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
        content_text="Plan a day trip",
        payload_json=json.dumps(
            {
                "reasoning_preference": "fast",
                "internal_note": "must not reach the client",
            }
        ),
        created_at_ms=1000,
    )

    history = service.get_display_history("u1", "s1", limit=10)

    assert history[0].content == "Plan a day trip"
    assert history[0].payload == {"reasoning_preference": "fast"}


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
    _insert_consumed_event(
        service._chat_db_path,
        session_id="s1",
        run_id="run-keep",
        message_id="message-keep",
    )
    _insert_consumed_event(
        service._chat_db_path,
        session_id="s2",
        run_id="run-delete",
        message_id="message-delete",
    )

    service.delete_session("u1", "s2")

    remaining = service.list_sessions("u1", limit=10)
    assert [item.session_id for item in remaining] == ["s1"]

    history = service.get_conversation_history("u1", "s2", limit=20)
    assert history == []
    consumed_sessions = {
        str(row[0])
        for row in service._get_conn()
        .execute(f"SELECT session_id FROM {CHAT_RUN_CONSUMED_EVENTS_TABLE}")
        .fetchall()
    }
    assert consumed_sessions == {"s1"}


def test_explicit_session_delete_always_removes_assets(tmp_path):
    from magi.utils.runtime import RuntimePaths

    service = _build_service(tmp_path)
    _init_chat_session_store(service._chat_db_path)
    _insert_session(
        service._chat_db_path,
        session_id="s-delete-assets",
        user_id="u1",
        title="Private attachments",
        created_at=1000,
        updated_at=1000,
    )
    runtime_paths = RuntimePaths(tmp_path / "runtime")
    asset_path = runtime_paths.chat_files_dir / "s-delete-assets" / "turn-1" / "private.txt"
    asset_path.parent.mkdir(parents=True, exist_ok=True)
    asset_path.write_text("private attachment", encoding="utf-8")

    service.delete_session("u1", "s-delete-assets")

    assert not asset_path.exists()


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


def test_get_conversation_history_can_return_complete_prompt_history(tmp_path):
    service = _build_service(tmp_path)
    _init_chat_session_store(service._chat_db_path)
    _insert_session(
        service._chat_db_path,
        session_id="s-long",
        user_id="u1",
        title="Long Chat",
        created_at=1000,
        updated_at=2100,
        message_count=1005,
    )
    conn = sqlite3.connect(str(service._chat_db_path))
    conn.executemany(
        f"""
        INSERT INTO {CHAT_MESSAGES_TABLE} (
            message_id, session_id, turn_id, user_id, role, message_kind, content_text,
            payload_json, is_final, is_visible, created_at_ms, sequence_no,
            replaces_message_id, replaced_by_message_id, reply_to_message_id
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        [
            (
                f"msg-{index}",
                "s-long",
                None,
                "u1",
                "user",
                "user_text",
                f"message-{index}",
                "{}",
                1,
                1,
                1000 + index,
                index,
                None,
                None,
                None,
            )
            for index in range(1, 1006)
        ],
    )
    conn.commit()
    conn.close()

    history = service.get_conversation_history("u1", "s-long", limit=None)
    tail = service.get_conversation_history(
        "u1",
        "s-long",
        limit=None,
        start_message_id="msg-1001",
    )

    assert len(history) == 1005
    assert history[0].message_id == "msg-1"
    assert history[-1].message_id == "msg-1005"
    assert [message.message_id for message in tail] == [
        "msg-1001",
        "msg-1002",
        "msg-1003",
        "msg-1004",
        "msg-1005",
    ]


def test_get_conversation_history_does_not_hide_query_failure(tmp_path, monkeypatch):
    service = _build_service(tmp_path)
    _init_chat_session_store(service._chat_db_path)

    def _raise_query_failure(**kwargs):
        _ = kwargs
        raise sqlite3.OperationalError("database is unavailable")

    monkeypatch.setattr(service, "_query_chat_message_rows", _raise_query_failure)

    with pytest.raises(sqlite3.OperationalError, match="database is unavailable"):
        service.get_conversation_history("u1", "s1")


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


def test_chat_history_does_not_preview_hidden_reply_target(tmp_path):
    service = _build_service(tmp_path)
    _init_chat_session_store(service._chat_db_path)
    _insert_session(
        service._chat_db_path,
        session_id="s-hidden-reply",
        user_id="u1",
        title="Reply",
        created_at=1000,
        updated_at=1100,
    )
    _insert_chat_message(
        service._chat_db_path,
        message_id="msg-hidden-target",
        session_id="s-hidden-reply",
        turn_id=None,
        user_id="u1",
        role="assistant",
        message_kind="assistant_final",
        content_text="deleted private text",
        created_at_ms=1000,
        sequence_no=1,
        is_visible=False,
    )
    _insert_chat_message(
        service._chat_db_path,
        message_id="msg-visible-reply",
        session_id="s-hidden-reply",
        turn_id=None,
        user_id="u1",
        role="user",
        message_kind="user_text",
        content_text="follow-up",
        created_at_ms=1100,
        sequence_no=2,
        reply_to_message_id="msg-hidden-target",
    )

    history = service.get_conversation_history("u1", "s-hidden-reply", limit=None)

    assert [item.content for item in history] == ["follow-up"]
    assert history[0].reply_to is None


def test_chat_history_does_not_preview_reply_target_from_another_session(tmp_path):
    service = _build_service(tmp_path)
    _init_chat_session_store(service._chat_db_path)
    for session_id in ("s-current", "s-other"):
        _insert_session(
            service._chat_db_path,
            session_id=session_id,
            user_id="u1",
            title="Reply",
            created_at=1000,
            updated_at=1100,
        )
    _insert_chat_message(
        service._chat_db_path,
        message_id="msg-other-target",
        session_id="s-other",
        turn_id=None,
        user_id="u1",
        role="assistant",
        message_kind="assistant_final",
        content_text="other session private text",
        created_at_ms=1000,
        sequence_no=1,
    )
    _insert_chat_message(
        service._chat_db_path,
        message_id="msg-current-reply",
        session_id="s-current",
        turn_id=None,
        user_id="u1",
        role="user",
        message_kind="user_text",
        content_text="current follow-up",
        created_at_ms=1100,
        sequence_no=1,
        reply_to_message_id="msg-other-target",
    )

    history = service.get_conversation_history("u1", "s-current", limit=None)

    assert [item.content for item in history] == ["current follow-up"]
    assert history[0].reply_to is None


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
    _insert_consumed_event(
        service._chat_db_path,
        session_id="s-chat",
        run_id="run-delete",
        message_id="msg-user",
    )

    conn = service._get_conn()
    conn.execute(f"""
        INSERT INTO {CHAT_CONTEXT_SUMMARIES_TABLE} (
            summary_id, session_id, status, summary_kind, summary_text,
            prompt_profile, created_at_ms, updated_at_ms
        ) VALUES ('summary-delete', 's-chat', 'active', 'rolling',
                  'private summary', 'general_chat', 1, 1)
        """)
    conn.commit()
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
    assert (
        conn.execute(
            f"SELECT COUNT(*) FROM {CHAT_CONTEXT_SUMMARIES_TABLE} WHERE session_id = ?",
            ("s-chat",),
        ).fetchone()[0]
        == 0
    )
    assert (
        conn.execute(
            f"SELECT COUNT(*) FROM {CHAT_RUN_CONSUMED_EVENTS_TABLE} WHERE session_id = ?",
            ("s-chat",),
        ).fetchone()[0]
        == 0
    )


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
    class _FakeForgettingService:
        async def delete_session(self, *, user_id: str, session_id: str):
            assert user_id == "u1"
            assert session_id == "s1"
            return True

    monkeypatch.setattr(
        messages_sessions,
        "require_chat_forgetting_service",
        lambda: _FakeForgettingService(),
    )

    result = __import__("asyncio").run(messages.delete_session(session_id="s1", user_id="u1"))

    assert result["success"] is True
    assert result["deleted_session_id"] == "s1"
    assert result["cleanup_pending"] is False


def test_delete_session_router_confirms_committed_delete_with_pending_cleanup(
    monkeypatch,
):
    class _FakeForgettingService:
        async def delete_session(self, *, user_id: str, session_id: str):
            raise ChatSurfaceCleanupPendingError(
                "cleanup pending",
                user_id=user_id,
                session_id=session_id,
                message_ids=["message-1"],
                turn_ids=["turn-1"],
            )

    monkeypatch.setattr(
        messages_sessions,
        "require_chat_forgetting_service",
        lambda: _FakeForgettingService(),
    )

    result = __import__("asyncio").run(
        messages.delete_session(session_id="s1", user_id="u1")
    )

    assert result["success"] is True
    assert result["deleted_session_id"] == "s1"
    assert result["cleanup_pending"] is True


def test_delete_session_router_returns_not_found_for_unknown_owner(monkeypatch):
    class _FakeForgettingService:
        async def delete_session(self, *, user_id: str, session_id: str):
            assert user_id == "wrong-user"
            assert session_id == "s1"
            return False

    monkeypatch.setattr(
        messages_sessions,
        "require_chat_forgetting_service",
        lambda: _FakeForgettingService(),
    )

    with pytest.raises(messages.HTTPException) as exc_info:
        __import__("asyncio").run(messages.delete_session(session_id="s1", user_id="wrong-user"))

    assert exc_info.value.status_code == 404


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


def test_clear_history_route_waits_for_governed_service(monkeypatch):
    calls: list[str] = []

    class _ControlStore:
        async def clear_session(self, session_id: str) -> None:
            calls.append(f"control:{session_id}")

    class _Service:
        async def clear_history(self, *, user_id: str, session_id: str):
            calls.append(f"clear:{user_id}:{session_id}")
            return ChatHistoryClearResult(
                message_ids=("message-1",),
                turn_ids=("turn-1",),
            )

    monkeypatch.setattr(
        "magi.api.routers.messages_content.require_chat_forgetting_service",
        lambda: _Service(),
    )
    monkeypatch.setattr(
        "magi.api.routers.messages_content.resolve_control_session_store",
        lambda: _ControlStore(),
    )

    result = __import__("asyncio").run(
        messages.clear_conversation_history(user_id="u1", session_id="s1")
    )

    assert result["success"] is True
    assert result["cleared_message_ids"] == ["message-1"]
    assert result["cleared_turn_ids"] == ["turn-1"]
    assert result["cleanup_pending"] is False
    assert calls == ["clear:u1:s1", "control:s1"]


def test_clear_history_route_confirms_redaction_with_pending_cleanup(monkeypatch):
    cleared_control_sessions: list[str] = []

    class _ControlStore:
        async def clear_session(self, session_id: str) -> None:
            cleared_control_sessions.append(session_id)

    class _Service:
        async def clear_history(self, *, user_id: str, session_id: str):
            raise ChatSurfaceCleanupPendingError(
                "cleanup pending",
                user_id=user_id,
                session_id=session_id,
                message_ids=["message-1"],
                turn_ids=["turn-1"],
            )

    monkeypatch.setattr(
        "magi.api.routers.messages_content.require_chat_forgetting_service",
        lambda: _Service(),
    )
    monkeypatch.setattr(
        "magi.api.routers.messages_content.resolve_control_session_store",
        lambda: _ControlStore(),
    )

    result = __import__("asyncio").run(
        messages.clear_conversation_history(user_id="u1", session_id="s1")
    )

    assert result["success"] is True
    assert result["cleared_message_ids"] == ["message-1"]
    assert result["cleared_turn_ids"] == ["turn-1"]
    assert result["cleanup_pending"] is True
    assert cleared_control_sessions == ["s1"]


def test_clear_history_route_does_not_report_success_on_failure(monkeypatch):
    class _Service:
        async def clear_history(self, *, user_id: str, session_id: str):
            raise RuntimeError("memory cleanup failed")

    monkeypatch.setattr(
        "magi.api.routers.messages_content.require_chat_forgetting_service",
        lambda: _Service(),
    )

    with pytest.raises(RuntimeError, match="memory cleanup failed"):
        __import__("asyncio").run(
            messages.clear_conversation_history(user_id="u1", session_id="s1")
        )


def test_get_display_history_surfaces_trace_status_instead_of_worker_messages(
    tmp_path, monkeypatch
):
    service = _build_service(tmp_path)
    trace_service = ChatTraceReadService()
    trace_service._runtime_trace_db_path = tmp_path / "runtime_trace.db"
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
        execution_mode="agent_loop",
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
        mode="agent_loop",
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
        "assistant",
        "user",
    ]
    assert [item.message_kind for item in messages[1:]] == [
        "plan_state",
        "permission_request",
        "ask_request",
        "ask_response",
    ]
    assert messages[1].payload == {"active": True, "plan_text": "step 1\nstep 2"}
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
    _init_runtime_trace_store(service._runtime_trace_db_path)
    _insert_trace_turn(
        service._runtime_trace_db_path,
        trace_id="trace:turn_trace",
        turn_id="turn_trace",
        session_id="s1",
        user_id="u1",
        status="completed",
        mode="agent_loop",
        started_at_ms=3000000,
        ended_at_ms=3001200,
        duration_ms=1200,
        response_preview="done",
    )
    _insert_trace_span(
        service._runtime_trace_db_path,
        span_id="turn_trace:capabilities",
        trace_id="trace:turn_trace",
        turn_id="turn_trace",
        parent_span_id="turn_trace:turn",
        node_type="capability_resolution",
        name="Capability resolution",
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
    assert snapshot["summary"]["mode"] == "agent_loop"
    assert snapshot["summary"]["status"] == "completed"
    assert snapshot["summary"]["duration_seconds"] == 1.2

    child_kinds = {child["kind"] for child in snapshot["root"]["children"]}
    assert {"capability_resolution", "dispatch", "response"} <= child_kinds

    dispatch_node = next(
        child for child in snapshot["root"]["children"] if child["kind"] == "dispatch"
    )
    worker_node = dispatch_node["children"][0]
    assert worker_node["kind"] == "worker"
    worker_child_kinds = {child["kind"] for child in worker_node["children"]}
    assert {"llm", "tool"} <= worker_child_kinds


def test_trace_snapshot_groups_worker_retry_attempts_from_normalized_spans(tmp_path):
    service = ChatTraceReadService()
    service._runtime_trace_db_path = tmp_path / "runtime_trace.db"
    _init_runtime_trace_store(service._runtime_trace_db_path)
    _insert_trace_turn(
        service._runtime_trace_db_path,
        trace_id="trace:turn_retry",
        turn_id="turn_retry",
        session_id="s1",
        user_id="u1",
        status="completed",
        mode="agent_loop",
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
    dispatch_node = next(
        child for child in snapshot["root"]["children"] if child["kind"] == "dispatch"
    )
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
    _init_runtime_trace_store(service._runtime_trace_db_path)
    _insert_trace_turn(
        service._runtime_trace_db_path,
        trace_id="trace:turn_1",
        turn_id="turn_1",
        session_id="s1",
        user_id="u1",
        status="completed",
        mode="agent_loop",
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
    assert snapshot["summary"]["mode"] == "agent_loop"
    assert snapshot["summary"]["status"] == "completed"
    dispatch = snapshot["root"]["children"][0]
    assert dispatch["kind"] == "dispatch"
    assert dispatch["status"] == "completed"
    worker = dispatch["children"][0]
    assert worker["kind"] == "worker"
    assert worker["children"][0]["label"] == "grep tool call"


def test_trace_summary_does_not_count_capability_resolution_as_semantic_step(tmp_path):
    service = ChatTraceReadService()
    service._runtime_trace_db_path = tmp_path / "runtime_trace.db"
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
        span_id="turn_plan:capabilities",
        trace_id="trace:turn_plan",
        turn_id="turn_plan",
        parent_span_id="turn_plan:turn",
        node_type="capability_resolution",
        name="Capability resolution",
        status="completed",
        started_at_ms=1000000,
        ended_at_ms=1000100,
        duration_ms=100,
        result_preview="planning",
    )

    summary = service.get_trace_summary(user_id="u1", session_id="s1", turn_id="turn_plan")

    assert summary is not None
    assert summary["headline"] == "Thinking"
    assert summary["active_steps"] == 0
    assert summary["completed_steps"] == 0


def test_trace_snapshot_exposes_continuation_metadata(tmp_path):
    service = ChatTraceReadService()
    service._runtime_trace_db_path = tmp_path / "runtime_trace.db"
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
