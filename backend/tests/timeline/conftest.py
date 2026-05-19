"""Re-export shared fixtures into the timeline test tree.

pytest's conftest discovery is directory-scoped — fixtures defined under
tests/memory/l2/conftest.py are not visible to tests under tests/timeline/.
This conftest re-defines the L2 schema fixture so the timeline tests can
use it without cross-importing.
"""

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
