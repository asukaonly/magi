"""Shared fixtures for L2 memory tests."""

from __future__ import annotations

import pytest_asyncio

from _shared.memory_schema import apply_memory_shared_schema


@pytest_asyncio.fixture
async def l2_store_with_schema(tmp_path):
    """An L2CognitionStore backed by a tmp_path DB with all memory_shared schema applied.

    Use this fixture for any test that needs L2CognitionStore.initialize() to succeed.
    """
    from magi.memory.l2.store import L2CognitionStore

    db_path = str(tmp_path / "l2.db")
    await apply_memory_shared_schema(db_path)
    store = L2CognitionStore(db_path=db_path)
    await store.initialize()
    return store
