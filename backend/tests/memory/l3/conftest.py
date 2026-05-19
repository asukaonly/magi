"""Shared fixtures for L3 memory tests."""

from __future__ import annotations

import pytest_asyncio

from _shared.memory_schema import apply_memory_shared_schema


@pytest_asyncio.fixture
async def l3_store_with_schema(tmp_path):
    """An L3SummaryStore backed by a tmp_path DB with all memory_shared schema applied."""
    from magi.memory.l3.summary_store import L3SummaryStore

    db_path = str(tmp_path / "memory.db")
    await apply_memory_shared_schema(db_path)
    store = L3SummaryStore(db_path=db_path)
    await store.initialize()
    return store
