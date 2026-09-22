"""Trace cache revisions follow durable writes and governed erasure."""

from pathlib import Path
import sqlite3

from alembic import command
import pytest

from magi.chat.read_service import ChatReadService
from magi.db.runner import MIGRATION_TARGETS, _build_config
from magi.runtime_trace.chat_trace.read_service import ChatTraceReadService


def trace_reader(path: Path) -> ChatTraceReadService:
    reader = object.__new__(ChatTraceReadService)
    reader._runtime_trace_db_path = path
    return reader


def seed_parents(connection: sqlite3.Connection, owner: str, session: str) -> None:
    connection.execute(
        """INSERT INTO trace_turns(trace_id,turn_id,session_id,user_id,status,mode,
            started_at_ms,created_at_ms,updated_at_ms) VALUES (?,?,?,?,'completed','function_calling',1,1,1)""",
        (f"trace-{session}", f"turn-{session}", session, owner),
    )
    connection.execute(
        """INSERT INTO agent_run_manifests(run_id,turn_id,session_id,user_id,manifest_json,created_at_ms,updated_at_ms)
            VALUES (?,?,?,?,'{}',1,1)""",
        (f"run-{session}", f"turn-{session}", session, owner),
    )


@pytest.fixture
def trace_db(tmp_path, ensure_db_schema):
    path = tmp_path / "trace.db"
    ensure_db_schema("runtime_trace", path)
    with sqlite3.connect(path) as connection:
        seed_parents(connection, "user", "chat")
        seed_parents(connection, "another-user", "another-chat")
    return path


@pytest.mark.parametrize(
    ("table", "insert", "update", "where"),
    [
        (
            "trace_turns",
            "INSERT INTO trace_turns(trace_id,turn_id,session_id,user_id,status,mode,started_at_ms,created_at_ms,updated_at_ms) VALUES ('new-trace','new-turn','chat','user','completed','function_calling',1,1,1)",
            "response_preview='changed'",
            "trace_id='new-trace'",
        ),
        (
            "agent_run_manifests",
            "INSERT INTO agent_run_manifests(run_id,session_id,user_id,manifest_json,created_at_ms,updated_at_ms) VALUES ('new-run','chat','user','{}',1,1)",
            'manifest_json=\'{"status":"completed"}\'',
            "run_id='new-run'",
        ),
        (
            "trace_spans",
            "INSERT INTO trace_spans(span_id,trace_id,node_type,name,status,started_at_ms,created_at_ms,updated_at_ms) VALUES ('span','trace-chat','tool','Tool','running',1,1,1)",
            "status='completed'",
            "span_id='span'",
        ),
        (
            "trace_llm_calls",
            "INSERT INTO trace_llm_calls(span_id,trace_id,turn_id,provider,model) VALUES ('llm','trace-chat','turn-chat','provider','model')",
            "input_tokens=42",
            "span_id='llm'",
        ),
        (
            "trace_tools",
            "INSERT INTO trace_tools(span_id,trace_id,turn_id,tool_name,arguments_json,success) VALUES ('tool','trace-chat','turn-chat','search','{}',1)",
            "result_preview='changed'",
            "span_id='tool'",
        ),
        (
            "agent_run_events",
            "INSERT INTO agent_run_events(event_id,run_id,sequence,user_id,session_id,event_type,payload_json,created_at_ms) VALUES ('event','run-chat',1,'different-event-owner','different-event-session','run_completed','{}',1)",
            'payload_json=\'{"status":"completed"}\'',
            "event_id='event'",
        ),
        (
            "run_plans",
            "INSERT INTO run_plans(plan_id,run_id,session_id,version,status,plan_json,created_at_ms,updated_at_ms) VALUES ('plan','run-chat','chat',1,'active','{}',1,1)",
            'plan_json=\'{"status":"completed"}\'',
            "plan_id='plan'",
        ),
    ],
)
def test_every_trace_projection_table_invalidates_only_its_manifest_owner(
    trace_db, table, insert, update, where
):
    reader = trace_reader(trace_db)
    other = reader.get_read_revision(user_id="another-user", session_id="another-chat")
    for sql in (
        insert,
        f"UPDATE {table} SET {update} WHERE {where}",
        f"DELETE FROM {table} WHERE {where}",
    ):
        previous = reader.get_read_revision(user_id="user", session_id="chat")
        with sqlite3.connect(trace_db) as connection:
            connection.execute(sql)
        assert reader.get_read_revision(user_id="user", session_id="chat") != previous
        assert reader.get_read_revision(user_id="another-user", session_id="another-chat") == other


def test_upgrade_seeds_existing_owners_without_rewriting_trace_content(tmp_path):
    path = tmp_path / "trace.db"
    target = next(target for target in MIGRATION_TARGETS if target.name == "runtime_trace")
    config = _build_config(target, path)
    command.upgrade(config, "v8")
    with sqlite3.connect(path) as connection:
        seed_parents(connection, "user", "chat")
        connection.execute("UPDATE trace_turns SET response_preview='Saved trace'")
    command.upgrade(config, "v9")
    reader = trace_reader(path)
    assert reader.get_read_revision(user_id="user", session_id="chat") != "empty:0"
    with sqlite3.connect(path) as connection:
        assert (
            connection.execute("SELECT response_preview FROM trace_turns").fetchone()[0]
            == "Saved trace"
        )
    command.downgrade(config, "v8")
    with sqlite3.connect(path) as connection:
        assert (
            connection.execute(
                "SELECT name FROM sqlite_master WHERE name='trace_read_revisions'"
            ).fetchone()
            is None
        )
        connection.execute("UPDATE trace_turns SET response_preview='Still writable'")


def test_revision_read_is_indexed_and_never_projects_or_creates_missing_storage(
    tmp_path, trace_db, monkeypatch
):
    missing = tmp_path / "missing.db"
    absent_reader = trace_reader(missing)
    assert absent_reader.get_read_revision(user_id="user", session_id="chat") == "empty:0"
    assert (
        absent_reader.get_trace_snapshot(user_id="user", session_id="chat", turn_id="turn") is None
    )
    assert not missing.exists()
    reader = trace_reader(trace_db)
    monkeypatch.setattr(
        reader, "get_trace_snapshot", lambda **_: pytest.fail("Revision projected trace tree")
    )
    assert reader.get_read_revision(user_id="user", session_id="chat") != "empty:0"
    with sqlite3.connect(trace_db) as connection:
        plans = connection.execute(
            "EXPLAIN QUERY PLAN SELECT epoch, revision FROM trace_read_revisions WHERE user_id=? AND session_id=?",
            ("user", "chat"),
        ).fetchall()
    assert any("SEARCH" in plan[3] and "INDEX" in plan[3] for plan in plans)


def test_existing_unmigrated_storage_does_not_report_an_unchanged_empty_revision(tmp_path):
    path = tmp_path / "invalid.db"
    sqlite3.connect(path).close()
    with pytest.raises(sqlite3.OperationalError):
        trace_reader(path).get_read_revision(user_id="user", session_id="chat")


def test_global_clear_erases_revision_identity_bytes_and_recreated_owners_get_new_epochs(trace_db):
    marker = "private-trace-revision-session-marker"
    with sqlite3.connect(trace_db) as connection:
        seed_parents(connection, "private-trace-revision-user-marker", marker)
    reader = trace_reader(trace_db)
    previous = reader.get_read_revision(
        user_id="private-trace-revision-user-marker", session_id=marker
    )
    cleanup = object.__new__(ChatReadService)
    cleanup._runtime_trace_db_path = trace_db
    cleanup._clear_all_runtime_trace_rows()
    assert (
        reader.get_read_revision(user_id="private-trace-revision-user-marker", session_id=marker)
        == "empty:0"
    )
    for path in trace_db.parent.glob(f"{trace_db.name}*"):
        assert marker.encode() not in path.read_bytes()
        assert b"private-trace-revision-user-marker" not in path.read_bytes()
    with sqlite3.connect(trace_db) as connection:
        seed_parents(connection, "private-trace-revision-user-marker", marker)
    assert (
        reader.get_read_revision(user_id="private-trace-revision-user-marker", session_id=marker)
        != previous
    )


def test_session_delete_erases_only_its_trace_revision_scope(trace_db):
    cleanup = object.__new__(ChatReadService)
    cleanup._runtime_trace_db_path = trace_db
    reader = trace_reader(trace_db)
    other = reader.get_read_revision(user_id="another-user", session_id="another-chat")
    cleanup._delete_runtime_trace_rows(user_id="user", session_id="chat")
    assert reader.get_read_revision(user_id="user", session_id="chat") == "empty:0"
    assert reader.get_read_revision(user_id="another-user", session_id="another-chat") == other
