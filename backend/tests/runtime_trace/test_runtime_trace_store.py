from __future__ import annotations

from contextlib import asynccontextmanager
import sqlite3
from pathlib import Path
from typing import Any

import pytest

from magi.utils.runtime import RuntimePaths


def _list_tables(db_path: Path) -> set[str]:
    conn = sqlite3.connect(str(db_path))
    cur = conn.cursor()
    cur.execute("SELECT name FROM sqlite_master WHERE type = 'table'")
    rows = {str(row[0]) for row in cur.fetchall()}
    conn.close()
    return rows


def _list_columns(db_path: Path, table_name: str) -> set[str]:
    conn = sqlite3.connect(str(db_path))
    cur = conn.cursor()
    cur.execute(f"PRAGMA table_info({table_name})")
    rows = {str(row[1]) for row in cur.fetchall()}
    conn.close()
    return rows


def _read_journal_mode(db_path: Path) -> str:
    conn = sqlite3.connect(str(db_path))
    try:
        return str(conn.execute("PRAGMA journal_mode").fetchone()[0]).lower()
    finally:
        conn.close()


def _patch_one_locked_hot_write(
    monkeypatch: pytest.MonkeyPatch,
    *,
    target_sql: str,
) -> dict[str, Any]:
    from magi.runtime_trace import store as store_module

    original_sqlite_connection_async = store_module.sqlite_connection_async
    state: dict[str, Any] = {
        "failures": 0,
        "sleep_delays": [],
    }

    class _FailOnceConnection:
        def __init__(self, inner: Any) -> None:
            self._inner = inner

        async def execute(self, sql: str, parameters: Any = ()) -> Any:
            if target_sql in sql and state["failures"] == 0:
                state["failures"] += 1
                raise sqlite3.OperationalError("database is locked")
            return await self._inner.execute(sql, parameters)

        def __getattr__(self, name: str) -> Any:
            return getattr(self._inner, name)

    @asynccontextmanager
    async def _flaky_connection(*args: Any, **kwargs: Any):
        async with original_sqlite_connection_async(*args, **kwargs) as db:
            yield _FailOnceConnection(db)

    async def _fake_sleep(delay: float) -> None:
        state["sleep_delays"].append(delay)

    monkeypatch.setattr(store_module, "sqlite_connection_async", _flaky_connection)
    monkeypatch.setattr(store_module.asyncio, "sleep", _fake_sleep)
    return state


def test_runtime_paths_exposes_runtime_trace_db_path(tmp_path: Path) -> None:
    runtime_paths = RuntimePaths(base_dir=tmp_path)

    assert runtime_paths.runtime_trace_db_path == tmp_path / "runtime" / "runtime_trace.db"


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
        assert {"run_id", "run_revision"}.issubset(_list_columns(db_path, "trace_turns"))
        assert {"run_id", "run_revision", "input_preview", "output_preview"}.issubset(
            _list_columns(db_path, "trace_spans")
        )
        assert "thinking_depth" in _list_columns(db_path, "trace_llm_calls")
        assert {"run_id", "run_revision"}.issubset(_list_columns(db_path, "runtime_notifications"))
        journal_mode = _read_journal_mode(db_path)
        assert journal_mode == "wal"
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
                run_id="run-1",
                run_revision=2,
                payload_json='{"content":"hello"}',
                created_at_ms=123,
            )
        )

        notifications = await store.list_notifications(after_id=0)
        assert len(notifications) == 1
        assert notifications[0].notification_id == notification_id
        assert notifications[0].channel == "agent_response"
        assert notifications[0].turn_id == "turn-1"
        assert notifications[0].run_id == "run-1"
        assert notifications[0].run_revision == 2

        latest_id = await store.get_latest_notification_id()
        assert latest_id == notification_id
    finally:
        await store.shutdown()


@pytest.mark.asyncio
async def test_runtime_trace_store_retries_transient_locked_notification_write(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from magi.runtime_trace import RuntimeNotificationRecord, RuntimeTraceStore
    from magi.runtime_trace import store as store_module

    db_path = tmp_path / "runtime_trace.db"
    store = RuntimeTraceStore(db_path=str(db_path))
    await store.initialize()
    retry_state = _patch_one_locked_hot_write(
        monkeypatch,
        target_sql="INSERT INTO runtime_notifications",
    )

    try:
        notification_id = await store.append_notification(
            RuntimeNotificationRecord(
                notification_id=0,
                channel="trace_update",
                user_id="user-1",
                session_id="session-1",
                turn_id="turn-1",
                payload_json='{"headline":"retry"}',
                created_at_ms=456,
            )
        )

        notifications = await store.list_notifications(after_id=0)
        assert notification_id > 0
        assert [item.channel for item in notifications] == ["trace_update"]
        assert retry_state["failures"] == 1
        assert retry_state["sleep_delays"] == [store_module._SQLITE_LOCK_RETRY_DELAYS_SECONDS[0]]
    finally:
        await store.shutdown()


@pytest.mark.asyncio
async def test_runtime_trace_store_round_trips_turn_continuation_metadata(tmp_path: Path) -> None:
    from magi.runtime_trace import RuntimeTraceStore, TraceTurnRecord

    db_path = tmp_path / "runtime_trace.db"
    store = RuntimeTraceStore(db_path=str(db_path))
    await store.initialize()

    try:
        await store.upsert_turn(
            TraceTurnRecord(
                trace_id="trace-turn-2",
                turn_id="turn-2",
                session_id="session-1",
                user_id="user-1",
                status="running",
                mode="function_calling",
                continued_from_turn_id="turn-1",
                continued_from_trace_id="trace-turn-1",
                superseded_by_turn_id=None,
                supersession_reason=None,
                started_at_ms=100,
                created_at_ms=100,
                updated_at_ms=100,
            )
        )

        turn = await store.get_turn("turn-2")

        assert turn is not None
        assert turn.continued_from_turn_id == "turn-1"
        assert turn.continued_from_trace_id == "trace-turn-1"
    finally:
        await store.shutdown()


@pytest.mark.asyncio
async def test_runtime_trace_store_preserves_latest_run_revision(tmp_path: Path) -> None:
    from magi.runtime_trace import RuntimeTraceStore, TraceSpanRecord, TraceTurnRecord

    db_path = tmp_path / "runtime_trace.db"
    store = RuntimeTraceStore(db_path=str(db_path))
    await store.initialize()

    try:
        await store.upsert_turn(
            TraceTurnRecord(
                trace_id="trace-turn-3",
                turn_id="turn-3",
                session_id="session-1",
                user_id="user-1",
                status="running",
                mode="function_calling",
                run_id="run-1",
                run_revision=3,
                started_at_ms=100,
                created_at_ms=100,
                updated_at_ms=100,
            )
        )
        await store.upsert_turn(
            TraceTurnRecord(
                trace_id="trace-turn-3",
                turn_id="turn-3",
                session_id="session-1",
                user_id="user-1",
                status="completed",
                mode="function_calling",
                run_revision=0,
                started_at_ms=100,
                ended_at_ms=200,
                duration_ms=100,
                created_at_ms=100,
                updated_at_ms=200,
            )
        )

        await store.upsert_span(
            TraceSpanRecord(
                span_id="span-1",
                trace_id="trace-turn-3",
                turn_id="turn-3",
                parent_span_id=None,
                node_type="llm_call",
                name="LLM call",
                status="running",
                input_preview="User asks for a recommendation",
                output_preview="Draft recommendation",
                run_id="run-1",
                run_revision=3,
                started_at_ms=120,
                created_at_ms=120,
                updated_at_ms=120,
            )
        )
        await store.upsert_span(
            TraceSpanRecord(
                span_id="span-1",
                trace_id="trace-turn-3",
                turn_id="turn-3",
                parent_span_id=None,
                node_type="llm_call",
                name="LLM call",
                status="ok",
                run_revision=0,
                started_at_ms=120,
                ended_at_ms=180,
                duration_ms=60,
                created_at_ms=120,
                updated_at_ms=180,
            )
        )

        turn = await store.get_turn("turn-3")
        span = await store.get_span("span-1")

        assert turn is not None
        assert turn.run_id == "run-1"
        assert turn.run_revision == 3
        assert turn.status == "completed"
        assert span is not None
        assert span.run_id == "run-1"
        assert span.run_revision == 3
        assert span.status == "ok"
        assert span.input_preview == "User asks for a recommendation"
        assert span.output_preview == "Draft recommendation"
    finally:
        await store.shutdown()


@pytest.mark.asyncio
async def test_runtime_trace_store_does_not_create_runtime_heartbeats_table(tmp_path: Path) -> None:
    from magi.runtime_trace import RuntimeTraceStore

    db_path = tmp_path / "runtime_trace.db"
    store = RuntimeTraceStore(db_path=str(db_path))
    await store.initialize()

    try:
        assert "runtime_heartbeats" not in _list_tables(db_path)
    finally:
        await store.shutdown()


@pytest.mark.asyncio
async def test_runtime_trace_store_retries_transient_locked_tool_write(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from magi.runtime_trace import RuntimeTraceStore, TraceToolRecord
    from magi.runtime_trace import store as store_module

    db_path = tmp_path / "runtime_trace.db"
    store = RuntimeTraceStore(db_path=str(db_path))
    await store.initialize()
    retry_state = _patch_one_locked_hot_write(
        monkeypatch,
        target_sql="INSERT INTO trace_tools",
    )

    try:
        await store.upsert_tool_call(
            TraceToolRecord(
                span_id="span-tool-1",
                trace_id="trace-1",
                turn_id="turn-1",
                tool_name="glob",
                tool_call_id="call-1",
                arguments_json='{"path":"."}',
                success=True,
                execution_time_ms=12,
                error_code=None,
                error_message=None,
                result_preview="ok",
                result_json='{"success":true}',
            )
        )

        record = await store.get_tool_call("span-tool-1")
        assert record is not None
        assert record.tool_name == "glob"
        assert retry_state["failures"] == 1
        assert retry_state["sleep_delays"] == [store_module._SQLITE_LOCK_RETRY_DELAYS_SECONDS[0]]
    finally:
        await store.shutdown()


@pytest.mark.asyncio
async def test_runtime_trace_store_creates_plugin_ingress_events_table(tmp_path: Path) -> None:
    from magi.runtime_trace.store import RuntimeTraceStore

    db_path = tmp_path / "runtime_trace.db"
    store = RuntimeTraceStore(db_path=str(db_path))

    await store.initialize()

    try:
        tables = _list_tables(db_path)
        assert "plugin_ingress_events" in tables
    finally:
        await store.shutdown()


@pytest.mark.asyncio
async def test_runtime_trace_store_claims_and_updates_plugin_ingress_events(tmp_path: Path) -> None:
    from magi.runtime_trace import RuntimeTraceStore, StoredPluginIngressEventRecord

    db_path = tmp_path / "runtime_trace.db"
    store = RuntimeTraceStore(db_path=str(db_path))
    await store.initialize()

    try:
        event_id = await store.append_plugin_ingress_event(
            StoredPluginIngressEventRecord(
                event_id=0,
                source_kind="desktop",
                producer="example_producer",
                plugin_target="example_target",
                event_type="example_event",
                occurred_at_ms=1_711_523_200_000,
                payload_json='{"foo":"bar"}',
                created_at_ms=1_711_523_200_050,
            )
        )

        claimed = await store.claim_next_plugin_ingress_event(consumer_name="runtime_worker")
        assert claimed is not None
        assert claimed.event_id == event_id
        assert claimed.status == "claimed"
        assert claimed.claimed_by == "runtime_worker"

        await store.complete_plugin_ingress_event(event_id)
        completed = await store.get_plugin_ingress_event(event_id)
        assert completed is not None
        assert completed.status == "completed"
        assert completed.processed_at_ms is not None

        failed_event_id = await store.append_plugin_ingress_event(
            StoredPluginIngressEventRecord(
                event_id=0,
                source_kind="desktop",
                producer="example_producer",
                plugin_target="example_target",
                event_type="example_event",
                occurred_at_ms=1_711_523_500_000,
                payload_json='{"foo":"baz"}',
                created_at_ms=1_711_523_500_010,
            )
        )
        failed_claim = await store.claim_next_plugin_ingress_event(consumer_name="runtime_worker")
        assert failed_claim is not None
        assert failed_claim.event_id == failed_event_id

        await store.fail_plugin_ingress_event(failed_event_id, error_text="HANDLER_FAILED")
        failed = await store.get_plugin_ingress_event(failed_event_id)
        assert failed is not None
        assert failed.status == "failed"
        assert failed.last_error == "HANDLER_FAILED"
        assert failed.processed_at_ms is not None
    finally:
        await store.shutdown()


@pytest.mark.asyncio
async def test_plugin_ingress_drops_events_at_or_before_memory_clear_cutoff(
    tmp_path: Path,
) -> None:
    from magi.memory.clear_generation import (
        advance_memory_clear_generation,
        current_memory_clear_state,
        ensure_memory_clear_state,
    )
    from magi.runtime_trace import RuntimeTraceStore, StoredPluginIngressEventRecord
    from magi.core.sqlite import sqlite_connection_async

    memory_db_path = tmp_path / "memory.db"
    async with sqlite_connection_async(str(memory_db_path)) as db:
        await ensure_memory_clear_state(db)
        await advance_memory_clear_generation(db, updated_at=2_000.0)
        await db.commit()

    async def read_memory_clear_state() -> tuple[int, float]:
        return await current_memory_clear_state(str(memory_db_path))

    store = RuntimeTraceStore(
        db_path=str(tmp_path / "runtime_trace.db"),
        plugin_ingress_clear_state_reader=read_memory_clear_state,
    )
    await store.initialize()
    try:
        stale_id = await store.append_plugin_ingress_event(
            StoredPluginIngressEventRecord(
                event_id=0,
                source_kind="desktop",
                producer="old_producer",
                plugin_target="example_target",
                event_type="example_event",
                occurred_at_ms=2_000_000,
                payload_json='{"private":"old"}',
            )
        )
        fresh_id = await store.append_plugin_ingress_event(
            StoredPluginIngressEventRecord(
                event_id=0,
                source_kind="desktop",
                producer="new_producer",
                plugin_target="example_target",
                event_type="example_event",
                occurred_at_ms=2_000_001,
                payload_json='{"private":"new"}',
            )
        )
        async with sqlite_connection_async(str(tmp_path / "runtime_trace.db")) as db:
            cursor = await db.execute(
                """
                INSERT INTO plugin_ingress_events (
                    source_kind, producer, plugin_target, event_type,
                    occurred_at_ms, payload_json, status, created_at_ms
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    "desktop",
                    "direct_old_producer",
                    "example_target",
                    "example_event",
                    1_999_999,
                    '{"private":"direct-old"}',
                    "pending",
                    1,
                ),
            )
            direct_stale_id = int(cursor.lastrowid)
            await db.commit()

        assert stale_id == 0
        assert fresh_id > 0
        claimed = await store.claim_next_plugin_ingress_event(
            consumer_name="runtime_worker"
        )
        assert claimed is not None
        assert claimed.event_id == fresh_id
        assert await store.get_plugin_ingress_event(direct_stale_id) is None
    finally:
        await store.shutdown()
