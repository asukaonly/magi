from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from magi.utils.runtime import RuntimePaths


def _list_tables(db_path: Path) -> set[str]:
    conn = sqlite3.connect(str(db_path))
    cur = conn.cursor()
    cur.execute("SELECT name FROM sqlite_master WHERE type = 'table'")
    rows = {str(row[0]) for row in cur.fetchall()}
    conn.close()
    return rows


def test_runtime_paths_exposes_runtime_trace_db_path(tmp_path: Path) -> None:
    runtime_paths = RuntimePaths(base_dir=tmp_path)

    assert runtime_paths.runtime_trace_db_path == tmp_path / "data" / "runtime_trace.db"


@pytest.mark.asyncio
async def test_runtime_trace_store_creates_turn_and_span_tables(tmp_path: Path) -> None:
    from magi.runtime_trace.store import RuntimeTraceStore

    db_path = tmp_path / "runtime_trace.db"
    store = RuntimeTraceStore(db_path=str(db_path))

    await store.initialize()

    try:
        tables = _list_tables(db_path)
        assert "trace_turns" in tables
        assert "trace_spans" in tables
        assert "trace_llm_calls" in tables
        assert "trace_tools" in tables
        assert "trace_intent_resolutions" in tables
        assert "runtime_notifications" in tables
    finally:
        await store.shutdown()


@pytest.mark.asyncio
async def test_runtime_trace_store_persists_notifications(tmp_path: Path) -> None:
    from magi.runtime_trace import RuntimeNotificationRecord, RuntimeTraceStore

    db_path = tmp_path / "runtime_trace.db"
    store = RuntimeTraceStore(db_path=str(db_path))
    await store.initialize()

    try:
        notification_id = await store.append_notification(
            RuntimeNotificationRecord(
                notification_id=0,
                channel="agent_response",
                user_id="user-1",
                session_id="session-1",
                turn_id="turn-1",
                payload_json='{"content":"hello"}',
                created_at_ms=123,
            )
        )

        notifications = await store.list_notifications(after_id=0)
        assert len(notifications) == 1
        assert notifications[0].notification_id == notification_id
        assert notifications[0].channel == "agent_response"
        assert notifications[0].turn_id == "turn-1"

        latest_id = await store.get_latest_notification_id()
        assert latest_id == notification_id
    finally:
        await store.shutdown()


@pytest.mark.asyncio
async def test_runtime_trace_store_persists_runtime_heartbeat(tmp_path: Path) -> None:
    from magi.runtime_trace import RuntimeHeartbeatRecord, RuntimeTraceStore

    db_path = tmp_path / "runtime_trace.db"
    store = RuntimeTraceStore(db_path=str(db_path))
    await store.initialize()

    try:
        await store.upsert_runtime_heartbeat(
            RuntimeHeartbeatRecord(
                role="runtime_worker",
                instance_id="worker-1",
                pid=1234,
                started_at_ms=100,
                last_seen_at_ms=200,
                status="ready",
                queue_backlog=3,
                active_turns=1,
                active_workers=2,
            )
        )

        heartbeat = await store.get_runtime_heartbeat(role="runtime_worker")
        assert heartbeat is not None
        assert heartbeat.role == "runtime_worker"
        assert heartbeat.instance_id == "worker-1"
        assert heartbeat.status == "ready"
        assert heartbeat.queue_backlog == 3
    finally:
        await store.shutdown()
