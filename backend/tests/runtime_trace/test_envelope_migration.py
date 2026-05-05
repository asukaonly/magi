from __future__ import annotations
import pytest
import tempfile
from pathlib import Path
from magi.core.sqlite import sqlite_connection_async
from magi.runtime_trace.schema import ensure_runtime_trace_schema, _ensure_trace_spans_turn_id_nullable


@pytest.mark.asyncio
async def test_old_schema_with_notnull_turn_id_migrated_to_nullable():
    with tempfile.TemporaryDirectory() as tmp:
        db_path = str(Path(tmp) / "trace.db")
        # Bootstrap with the OLD schema where turn_id is NOT NULL
        async with sqlite_connection_async(db_path) as db:
            await db.execute(
                """
                CREATE TABLE trace_spans (
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
                )
                """
            )
            # Insert one row with turn_id present so we can verify data preservation
            await db.execute(
                "INSERT INTO trace_spans VALUES (?, ?, ?, NULL, ?, ?, ?, 1, 0, NULL, NULL, NULL, NULL, ?, ?, ?, ?, ?)",
                ("s1", "t1", "turn1", "span", "x", "ok", 100, 200, 100, 100, 200),
            )
            await db.commit()

        async with sqlite_connection_async(db_path) as db:
            await _ensure_trace_spans_turn_id_nullable(db)
            await db.commit()

        # turn_id is now nullable
        async with sqlite_connection_async(db_path) as db:
            cursor = await db.execute("PRAGMA table_info(trace_spans)")
            rows = await cursor.fetchall()
            turn_id_row = next(r for r in rows if r[1] == "turn_id")
            assert turn_id_row[3] == 0, "turn_id should be NULLABLE (notnull == 0)"

        # Original data preserved
        async with sqlite_connection_async(db_path) as db:
            cursor = await db.execute(
                "SELECT span_id, trace_id, turn_id FROM trace_spans WHERE span_id = ?", ("s1",)
            )
            row = await cursor.fetchone()
            assert tuple(row) == ("s1", "t1", "turn1")

        # Now we can insert a row with NULL turn_id
        async with sqlite_connection_async(db_path) as db:
            await db.execute(
                "INSERT INTO trace_spans VALUES (?, ?, NULL, NULL, ?, ?, ?, 1, 0, NULL, NULL, NULL, NULL, ?, ?, ?, ?, ?)",
                ("s2", "t2", "span", "y", "ok", 100, 200, 100, 100, 200),
            )
            await db.commit()


@pytest.mark.asyncio
async def test_migration_idempotent():
    """Second run is a no-op."""
    with tempfile.TemporaryDirectory() as tmp:
        db_path = str(Path(tmp) / "trace.db")
        async with sqlite_connection_async(db_path) as db:
            await ensure_runtime_trace_schema(db)
            await db.commit()
        # Run twice more — must not raise
        for _ in range(2):
            async with sqlite_connection_async(db_path) as db:
                await ensure_runtime_trace_schema(db)
                await db.commit()


@pytest.mark.asyncio
async def test_fresh_schema_already_nullable():
    """ensure_runtime_trace_schema on a brand new DB should produce a nullable turn_id."""
    with tempfile.TemporaryDirectory() as tmp:
        db_path = str(Path(tmp) / "trace.db")
        async with sqlite_connection_async(db_path) as db:
            await ensure_runtime_trace_schema(db)
            await db.commit()
        async with sqlite_connection_async(db_path) as db:
            cursor = await db.execute("PRAGMA table_info(trace_spans)")
            rows = await cursor.fetchall()
            turn_id_row = next(r for r in rows if r[1] == "turn_id")
            assert turn_id_row[3] == 0
