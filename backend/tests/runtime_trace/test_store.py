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
    finally:
        await store.shutdown()
