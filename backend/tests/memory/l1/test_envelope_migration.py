from __future__ import annotations
import pytest
import tempfile
from pathlib import Path
from magi.core.sqlite import sqlite_connection_async
from magi.memory.l1.storage.schema import L1EventSchemaMixin


class _Probe(L1EventSchemaMixin):
    pass


@pytest.mark.asyncio
async def test_envelope_columns_added_to_fact_events():
    with tempfile.TemporaryDirectory() as tmp:
        db_path = str(Path(tmp) / "l1.db")
        async with sqlite_connection_async(db_path) as db:
            await db.execute(
                """
                CREATE TABLE fact_events (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    event_id TEXT NOT NULL UNIQUE,
                    correlation_id TEXT NOT NULL,
                    timestamp REAL NOT NULL,
                    created_at REAL NOT NULL,
                    event_type TEXT NOT NULL,
                    source TEXT NOT NULL,
                    source_item_id TEXT,
                    idempotency_key TEXT,
                    memory_domain INTEGER NOT NULL,
                    ingest_target INTEGER NOT NULL,
                    cognition_eligible INTEGER NOT NULL DEFAULT 0,
                    tom_depth INTEGER NOT NULL DEFAULT 1,
                    retention_class INTEGER NOT NULL DEFAULT 2,
                    session_id TEXT,
                    turn_id TEXT,
                    user_id TEXT,
                    task_id TEXT,
                    content TEXT NOT NULL,
                    author_type TEXT NOT NULL,
                    content_type TEXT NOT NULL,
                    importance_score REAL NOT NULL DEFAULT 0.5,
                    level INTEGER NOT NULL DEFAULT 1,
                    media_path TEXT
                )
                """
            )
            await db.commit()

        probe = _Probe()
        async with sqlite_connection_async(db_path) as db:
            await probe._ensure_envelope_columns(db)
            await db.commit()

        async with sqlite_connection_async(db_path) as db:
            async with db.execute("PRAGMA table_info(fact_events)") as cur:
                cols = {row[1] for row in await cur.fetchall()}
        for name in ("causation_id", "trace_id", "span_id", "parent_span_id"):
            assert name in cols


@pytest.mark.asyncio
async def test_envelope_migration_idempotent():
    with tempfile.TemporaryDirectory() as tmp:
        db_path = str(Path(tmp) / "l1.db")
        async with sqlite_connection_async(db_path) as db:
            await db.execute(
                "CREATE TABLE fact_events ("
                " id INTEGER PRIMARY KEY, event_id TEXT NOT NULL UNIQUE,"
                " correlation_id TEXT NOT NULL, timestamp REAL NOT NULL,"
                " created_at REAL NOT NULL, event_type TEXT NOT NULL,"
                " source TEXT NOT NULL, memory_domain INTEGER NOT NULL,"
                " ingest_target INTEGER NOT NULL, content TEXT NOT NULL,"
                " author_type TEXT NOT NULL, content_type TEXT NOT NULL"
                ")"
            )
            await db.commit()

        probe = _Probe()
        for _ in range(2):
            async with sqlite_connection_async(db_path) as db:
                await probe._ensure_envelope_columns(db)
                await db.commit()


@pytest.mark.asyncio
async def test_envelope_indexes_created():
    with tempfile.TemporaryDirectory() as tmp:
        db_path = str(Path(tmp) / "l1.db")
        async with sqlite_connection_async(db_path) as db:
            await db.execute(
                "CREATE TABLE fact_events ("
                " id INTEGER PRIMARY KEY, event_id TEXT NOT NULL UNIQUE,"
                " correlation_id TEXT NOT NULL, timestamp REAL NOT NULL,"
                " created_at REAL NOT NULL, event_type TEXT NOT NULL,"
                " source TEXT NOT NULL, memory_domain INTEGER NOT NULL,"
                " ingest_target INTEGER NOT NULL, content TEXT NOT NULL,"
                " author_type TEXT NOT NULL, content_type TEXT NOT NULL"
                ")"
            )
            await db.commit()

        probe = _Probe()
        async with sqlite_connection_async(db_path) as db:
            await probe._ensure_envelope_columns(db)
            await db.commit()

        async with sqlite_connection_async(db_path) as db:
            async with db.execute(
                "SELECT name FROM sqlite_master WHERE type='index' AND tbl_name='fact_events'"
            ) as cur:
                idx = {row[0] for row in await cur.fetchall()}
        assert "idx_fact_events_trace" in idx
        assert "idx_fact_events_causation" in idx
