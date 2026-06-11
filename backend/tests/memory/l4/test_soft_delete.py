"""Tests for L4 soft-delete via deleted_at column."""
from __future__ import annotations

import pytest

from magi.core.sqlite import sqlite_connection_async
from magi.memory.l4.procedural_memory import L4ProceduralMemoryStore
from magi.memory.l4.storage.records import soft_delete_skill
from magi.memory.l4.storage.schema import ensure_procedural_memory_schema


async def _seed_skill(db_path: str, *, skill_id: str, name: str) -> None:
    async with sqlite_connection_async(db_path) as db:
        await ensure_procedural_memory_schema(db)
        await db.execute(
            """
            INSERT INTO procedural_skills(
                skill_id, skill_name, skill_category, skill_type,
                source_event_ids, created_at, updated_at,
                total_attempts, success_count, failure_count
            ) VALUES (?, ?, 'tool', 'external_tool', '[]', 1.0, 1.0, 1, 1, 0)
            """,
            (skill_id, name),
        )
        await db.commit()


@pytest.mark.asyncio
async def test_migration_adds_deleted_at_idempotently(tmp_path, ensure_memory_schema):
    db_path = str(tmp_path / "l4.db")
    # Schema is alembic-owned (ensure_procedural_memory_schema is a no-op).
    ensure_memory_schema("memory_shared", db_path)
    async with sqlite_connection_async(db_path) as db:
        await ensure_procedural_memory_schema(db)
        await db.commit()
    # Run again — must not raise.
    async with sqlite_connection_async(db_path) as db:
        await ensure_procedural_memory_schema(db)
        await db.commit()
    async with sqlite_connection_async(db_path) as db:
        async with db.execute("SELECT deleted_at FROM procedural_skills LIMIT 1") as cur:
            await cur.fetchone()  # column must exist


@pytest.mark.asyncio
async def test_soft_delete_filters_from_reads(tmp_path, ensure_memory_schema):
    db_path = str(tmp_path / "l4.db")
    ensure_memory_schema("memory_shared", db_path)
    await _seed_skill(db_path, skill_id="sk-1", name="alive")
    await _seed_skill(db_path, skill_id="sk-2", name="zombie")

    store = L4ProceduralMemoryStore(db_path=db_path, vector_enabled=False)

    total_before = await store.count_skills()
    assert total_before == 2

    await soft_delete_skill(db_path=db_path, skill_id="sk-2", now=2.0)

    total_after = await store.count_skills()
    assert total_after == 1

    rows = await store.get_all_skills(limit=10, offset=0)
    skill_names = {r["skill_name"] for r in rows}
    assert "alive" in skill_names
    assert "zombie" not in skill_names

    # Direct fetch should also exclude soft-deleted rows.
    assert await store.get_skill(skill_name="zombie", skill_category="tool") is None
    assert await store.get_skill(skill_name="alive", skill_category="tool") is not None
