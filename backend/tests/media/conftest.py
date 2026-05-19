"""Re-export the L2 schema fixture for media tests that need a real L2 store."""

from __future__ import annotations

import pytest_asyncio

from _shared.memory_schema import apply_memory_shared_schema


@pytest_asyncio.fixture
async def l2_store_with_schema(tmp_path):
    from magi.memory.l2.store import L2CognitionStore

    db_path = str(tmp_path / "memory.db")
    await apply_memory_shared_schema(db_path)
    store = L2CognitionStore(db_path=db_path)
    await store.initialize()
    return store
