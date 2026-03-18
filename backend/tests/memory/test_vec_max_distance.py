"""Tests for SqliteVecIndex.search max_distance filtering."""

from __future__ import annotations

import aiosqlite
import pytest

from magi.memory.embedding_service import EmbeddingResult
from magi.memory.sqlite_vec_index import SqliteVecIndex


def _make_embedding(vector: list[float]) -> EmbeddingResult:
    return EmbeddingResult(model_name="test-model", dimension=len(vector), vector=vector)


@pytest.fixture
async def index(tmp_path):
    idx = SqliteVecIndex(
        db_path=str(tmp_path / "vec.db"),
        registry_table="test_registry",
        entity_column="entity_id",
        vec_table_prefix="test_vec",
    )
    await idx.initialize()
    # Insert three vectors: [1,0,0,0], [0,1,0,0], [0.9,0.1,0,0]
    await idx.upsert(entity_id="a", embedding=_make_embedding([1.0, 0.0, 0.0, 0.0]))
    await idx.upsert(entity_id="b", embedding=_make_embedding([0.0, 1.0, 0.0, 0.0]))
    await idx.upsert(entity_id="c", embedding=_make_embedding([0.9, 0.1, 0.0, 0.0]))
    yield idx
    await idx.close()


@pytest.mark.asyncio
async def test_search_without_max_distance_returns_all(index: SqliteVecIndex):
    query = _make_embedding([1.0, 0.0, 0.0, 0.0])
    hits = await index.search(embedding=query, limit=10)
    assert len(hits) == 3


@pytest.mark.asyncio
async def test_search_with_tight_max_distance_filters(index: SqliteVecIndex):
    query = _make_embedding([1.0, 0.0, 0.0, 0.0])
    # Only "a" (distance=0) and "c" (small distance) should survive a tight threshold
    hits = await index.search(embedding=query, limit=10, max_distance=0.5)
    entity_ids = {h.entity_id for h in hits}
    assert "a" in entity_ids
    assert "c" in entity_ids
    assert "b" not in entity_ids


@pytest.mark.asyncio
async def test_search_with_very_small_max_distance(index: SqliteVecIndex):
    query = _make_embedding([1.0, 0.0, 0.0, 0.0])
    # Only exact match should survive
    hits = await index.search(embedding=query, limit=10, max_distance=0.01)
    assert len(hits) == 1
    assert hits[0].entity_id == "a"


@pytest.mark.asyncio
async def test_search_max_distance_none_same_as_no_filter(index: SqliteVecIndex):
    query = _make_embedding([1.0, 0.0, 0.0, 0.0])
    hits_none = await index.search(embedding=query, limit=10, max_distance=None)
    hits_default = await index.search(embedding=query, limit=10)
    assert len(hits_none) == len(hits_default)


@pytest.mark.asyncio
async def test_clear_skips_missing_registry_table_when_index_state_is_stale(tmp_path):
    idx = SqliteVecIndex(
        db_path=str(tmp_path / "vec.db"),
        registry_table="test_registry",
        entity_column="entity_id",
        vec_table_prefix="test_vec",
    )
    idx._db = await aiosqlite.connect(str(tmp_path / "vec.db"))
    idx._db.row_factory = aiosqlite.Row
    idx._initialized = True

    try:
        await idx.clear()
    finally:
        await idx.close()
