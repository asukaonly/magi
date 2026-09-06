"""Tests for SqliteSourceStateStore."""

from __future__ import annotations

import pytest

from magi.awareness.source_state import SqliteSourceStateStore


@pytest.fixture
def store(tmp_path):
    return SqliteSourceStateStore(tmp_path / "source_state.db")


class TestSqliteSourceStateStore:
    @pytest.mark.asyncio
    async def test_cursor_round_trip(self, store: SqliteSourceStateStore):
        assert await store.get_cursor("source-1") is None
        await store.set_cursor("source-1", "cursor-abc")
        assert await store.get_cursor("source-1") == "cursor-abc"

    @pytest.mark.asyncio
    async def test_cursor_overwrite(self, store: SqliteSourceStateStore):
        await store.set_cursor("source-1", "v1")
        await store.set_cursor("source-1", "v2")
        assert await store.get_cursor("source-1") == "v2"

    @pytest.mark.asyncio
    async def test_fingerprints_add_and_get(self, store: SqliteSourceStateStore):
        fps = await store.get_known_fingerprints("source-1")
        assert fps == set()

        await store.add_fingerprints("source-1", {"fp1", "fp2", "fp3"})
        fps = await store.get_known_fingerprints("source-1")
        assert fps == {"fp1", "fp2", "fp3"}

    @pytest.mark.asyncio
    async def test_fingerprints_idempotent(self, store: SqliteSourceStateStore):
        await store.add_fingerprints("source-1", {"fp1"})
        await store.add_fingerprints("source-1", {"fp1", "fp2"})
        fps = await store.get_known_fingerprints("source-1")
        assert fps == {"fp1", "fp2"}

    @pytest.mark.asyncio
    async def test_fingerprint_groups_add_and_get(self, store: SqliteSourceStateStore):
        await store.add_fingerprint_groups(
            {
                "source-1": {"fp1", "fp2"},
                "source-2": {"fp3"},
            }
        )

        assert await store.get_known_fingerprints("source-1") == {"fp1", "fp2"}
        assert await store.get_known_fingerprints("source-2") == {"fp3"}

    @pytest.mark.asyncio
    async def test_fingerprints_limit(self, store: SqliteSourceStateStore):
        await store.add_fingerprints("source-1", {f"fp{i}" for i in range(20)})
        fps = await store.get_known_fingerprints("source-1", limit=5)
        assert len(fps) == 5

    @pytest.mark.asyncio
    async def test_prune_fingerprints(self, store: SqliteSourceStateStore):
        await store.add_fingerprints("source-1", {f"fp{i}" for i in range(10)})
        pruned = await store.prune_fingerprints("source-1", keep_latest=3)
        assert pruned == 7
        fps = await store.get_known_fingerprints("source-1")
        assert len(fps) == 3

    @pytest.mark.asyncio
    async def test_prune_nothing_to_prune(self, store: SqliteSourceStateStore):
        await store.add_fingerprints("source-1", {"fp1", "fp2"})
        pruned = await store.prune_fingerprints("source-1", keep_latest=10)
        assert pruned == 0

    @pytest.mark.asyncio
    async def test_stats_round_trip(self, store: SqliteSourceStateStore):
        stats = await store.get_stats("source-1")
        assert stats == {}

        await store.update_stats("source-1", {"items_synced": 42})
        stats = await store.get_stats("source-1")
        assert stats == {"items_synced": 42}

    @pytest.mark.asyncio
    async def test_stats_merge(self, store: SqliteSourceStateStore):
        await store.update_stats("source-1", {"a": 1, "b": 2})
        await store.update_stats("source-1", {"b": 3, "c": 4})
        stats = await store.get_stats("source-1")
        assert stats == {"a": 1, "b": 3, "c": 4}

    @pytest.mark.asyncio
    async def test_isolation_between_sources(self, store: SqliteSourceStateStore):
        await store.set_cursor("source-1", "c1")
        await store.set_cursor("source-2", "c2")
        await store.add_fingerprints("source-1", {"fp-a"})
        await store.add_fingerprints("source-2", {"fp-b"})

        assert await store.get_cursor("source-1") == "c1"
        assert await store.get_cursor("source-2") == "c2"
        assert await store.get_known_fingerprints("source-1") == {"fp-a"}
        assert await store.get_known_fingerprints("source-2") == {"fp-b"}
