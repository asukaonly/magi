"""Tests for SqliteVecIndex.search max_distance filtering."""

from __future__ import annotations

import aiosqlite
import pytest

from magi.memory.embedding.embedding_service import EmbeddingResult
from magi.memory.embedding import sqlite_vec_index as sqlite_vec_index_module
from magi.memory.embedding.sqlite_vec_index import SqliteVecIndex


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
@pytest.mark.parametrize(
    ("options", "ids", "distances"),
    [
        ({}, ["a", "c", "b"], [0.0, 0.14142136, 1.41421356]),
        ({"max_distance": None}, ["a", "c", "b"], [0.0, 0.14142136, 1.41421356]),
        ({"max_distance": 0.5}, ["a", "c"], [0.0, 0.14142136]),
        ({"max_distance": 0.01}, ["a"], [0.0]),
    ],
)
async def test_vector_distance_filter_returns_exact_ordered_hits(index, options, ids, distances):
    hits = await index.search(embedding=_make_embedding([1.0, 0.0, 0.0, 0.0]), limit=10, **options)
    assert [hit.entity_id for hit in hits] == ids
    assert [hit.distance for hit in hits] == pytest.approx(distances)


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


@pytest.mark.asyncio
async def test_clear_empties_vectors_but_preserves_overlapping_registry_name(tmp_path):
    import sqlite3

    path = tmp_path / "vec.db"
    index = SqliteVecIndex(
        db_path=str(path),
        registry_table="l1_event_vectors",
        entity_column="event_id",
        vec_table_prefix="l1_event_vec",
    )
    await index.initialize()
    try:
        await index.upsert(entity_id="event-1", embedding=_make_embedding([1.0, 0.0, 0.0, 0.0]))
        with sqlite3.connect(path) as db:
            tables_before = {
                row[0] for row in db.execute("SELECT name FROM sqlite_master WHERE type = 'table'")
            }
            vectors = {row[0] for row in db.execute("SELECT vec_table FROM l1_event_vectors")}
        assert len(vectors) == 1
        assert vectors <= tables_before
        assert "l1_event_vectors" in tables_before
        await index.clear()
        with sqlite3.connect(path) as db:
            tables_after = {
                row[0] for row in db.execute("SELECT name FROM sqlite_master WHERE type = 'table'")
            }
            assert db.execute("SELECT COUNT(*) FROM l1_event_vectors").fetchone()[0] == 0
        assert "l1_event_vectors" in tables_after
        assert vectors <= tables_after
        for table in vectors:
            async with index._db.execute(f'SELECT COUNT(*) FROM "{table}"') as cursor:
                assert (await cursor.fetchone())[0] == 0
        assert await index.search(embedding=_make_embedding([1.0, 0.0, 0.0, 0.0]), limit=10) == []
    finally:
        await index.close()


@pytest.mark.asyncio
async def test_upsert_recreates_missing_registry_table_when_index_state_is_stale(tmp_path):
    idx = SqliteVecIndex(
        db_path=str(tmp_path / "vec.db"),
        registry_table="test_registry",
        entity_column="entity_id",
        vec_table_prefix="test_vec",
    )
    idx._db = await aiosqlite.connect(str(tmp_path / "vec.db"))
    idx._db.row_factory = aiosqlite.Row
    await idx._load_extension(idx._db)
    idx._initialized = True

    try:
        await idx.upsert(entity_id="evt-1", embedding=_make_embedding([1.0, 0.0, 0.0, 0.0]))

        async with idx._db.execute("SELECT entity_id FROM test_registry") as cursor:
            rows = await cursor.fetchall()
        assert [row[0] for row in rows] == ["evt-1"]
    finally:
        await idx.close()


def test_deserialize_float32_blob_falls_back_when_package_helper_is_missing(monkeypatch: pytest.MonkeyPatch):
    raw = sqlite_vec_index_module.sqlite_vec.serialize_float32([1.0, 2.5, -3.0])
    monkeypatch.delattr(sqlite_vec_index_module.sqlite_vec, "deserialize_float32", raising=False)

    decoded = sqlite_vec_index_module._deserialize_float32_blob(raw)

    assert decoded == pytest.approx([1.0, 2.5, -3.0])


@pytest.mark.asyncio
async def test_upsert_many_persists_multiple_vectors_in_one_call(tmp_path):
    idx = SqliteVecIndex(
        db_path=str(tmp_path / "vec.db"),
        registry_table="test_registry",
        entity_column="entity_id",
        vec_table_prefix="test_vec",
    )
    await idx.initialize()

    try:
        await idx.upsert_many(
            [
                {"entity_id": "a", "embedding": _make_embedding([1.0, 0.0, 0.0, 0.0]), "metadata": {"kind": "a"}},
                {"entity_id": "b", "embedding": _make_embedding([0.0, 1.0, 0.0, 0.0]), "metadata": {"kind": "b"}},
                {"entity_id": "c", "embedding": _make_embedding([0.9, 0.1, 0.0, 0.0]), "metadata": {"kind": "c"}},
            ]
        )

        hits = await idx.search(embedding=_make_embedding([1.0, 0.0, 0.0, 0.0]), limit=10)
        assert {hit.entity_id for hit in hits} == {"a", "b", "c"}

        async with idx._db.execute("SELECT entity_id FROM test_registry ORDER BY entity_id") as cursor:
            rows = await cursor.fetchall()
        assert [row[0] for row in rows] == ["a", "b", "c"]
    finally:
        await idx.close()
