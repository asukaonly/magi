from __future__ import annotations

import sqlite3

import pytest


def _has_table(db_path: str, table_name: str) -> bool:
    conn = sqlite3.connect(db_path)
    cur = conn.cursor()
    cur.execute(
        "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = ?",
        (table_name,),
    )
    row = cur.fetchone()
    conn.close()
    return row is not None


@pytest.mark.asyncio
async def test_memory_layers_create_dedicated_vector_tables(tmp_path):
    from magi.memory.l1_event_store import L1EventStore
    from magi.memory.l3_summary_store import L3SummaryStore
    from magi.memory.l4_procedural_memory import L4ProceduralMemoryStore
    from magi.memory.l5_capabilities import CapabilityMemory

    l1_db = tmp_path / "l1_events.db"
    l3_db = tmp_path / "l3_reflections.db"
    l4_db = tmp_path / "l4_procedural.db"
    l5_db = tmp_path / "capabilities.db"

    l1_store = L1EventStore(db_path=str(l1_db))
    l3_store = L3SummaryStore(db_path=str(l3_db))
    l4_store = L4ProceduralMemoryStore(db_path=str(l4_db))
    l5_store = CapabilityMemory(persist_path=str(l5_db))

    await l1_store.initialize()
    await l3_store.initialize()
    await l4_store.initialize()
    l5_store._ensure_db()

    assert _has_table(str(l1_db), "l1_event_vectors")
    assert _has_table(str(l3_db), "l3_summary_vectors")
    assert _has_table(str(l4_db), "l4_skill_vectors")
    assert _has_table(str(l5_db), "l5_capability_vectors")
