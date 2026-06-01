"""Unit tests for the batch canonical-name lookup helper used by the
recall projection layer (Phase 5)."""

from __future__ import annotations

import aiosqlite
import pytest

from magi.memory.l2.entities.catalog.lookup import get_canonical_names


@pytest.mark.asyncio
async def test_returns_only_entries_with_non_empty_canonical_name(tmp_path):
    db_path = tmp_path / "catalog.sqlite"
    async with aiosqlite.connect(db_path) as db:
        await db.execute(
            "CREATE TABLE entity_catalog ("
            " entity_id TEXT PRIMARY KEY, canonical_name TEXT)"
        )
        await db.executemany(
            "INSERT INTO entity_catalog (entity_id, canonical_name) VALUES (?, ?)",
            [
                ("entity_a", "Alice"),
                ("entity_b", ""),           # empty canonical_name → dropped
                ("entity_c", None),          # NULL canonical_name → dropped
                ("entity_d", "Dave"),
            ],
        )
        await db.commit()

    result = await get_canonical_names(
        str(db_path),
        ["entity_a", "entity_b", "entity_c", "entity_d", "missing"],
    )
    assert result == {"entity_a": "Alice", "entity_d": "Dave"}


@pytest.mark.asyncio
async def test_empty_input_returns_empty_dict(tmp_path):
    db_path = tmp_path / "catalog.sqlite"
    async with aiosqlite.connect(db_path) as db:
        await db.execute(
            "CREATE TABLE entity_catalog ("
            " entity_id TEXT PRIMARY KEY, canonical_name TEXT)"
        )
        await db.commit()

    result = await get_canonical_names(str(db_path), [])
    assert result == {}


@pytest.mark.asyncio
async def test_handles_missing_table_gracefully(tmp_path):
    """If the catalog table doesn't exist (fresh deploy / corrupted state),
    return an empty dict rather than crashing the recall pipeline."""
    db_path = tmp_path / "empty.sqlite"
    async with aiosqlite.connect(db_path) as db:
        await db.commit()  # creates empty DB, no tables

    result = await get_canonical_names(str(db_path), ["x"])
    assert result == {}
