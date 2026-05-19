"""Shared fixtures for API tests."""

from __future__ import annotations

import pytest_asyncio

from _shared.memory_schema import apply_memory_shared_schema


class _FakeL2Pipeline:
    """Stand-in for the runtime L2 pipeline; exposes only the surface
    TimelineService used to touch via the older private path. Kept for
    backward compatibility; current code reads unified_memory.l2 directly.
    """

    def __init__(self, cognition_store) -> None:
        self._cognition_store = cognition_store


class _FakeUnifiedMemory:
    """Stand-in for the runtime unified_memory facade.

    Exposes the attributes TimelineService reads:
      - `l2` — the L2CognitionStore (canonical accessor since T11)
      - `l2_pipeline._cognition_store` — legacy, kept for back-compat
      - `memory_db_path` — used by future endpoint (Task 12)

    Tests that need richer behavior should extend this class with
    additional properties as new code paths are added.
    """

    def __init__(self, *, cognition_store, memory_db_path: str) -> None:
        self.l2 = cognition_store
        self.l2_pipeline = _FakeL2Pipeline(cognition_store)
        self.memory_db_path = memory_db_path


@pytest_asyncio.fixture
async def l2_store_for_tests(tmp_path):
    from magi.memory.l2.store import L2CognitionStore

    db_path = str(tmp_path / "memory.db")
    await apply_memory_shared_schema(db_path)
    store = L2CognitionStore(db_path=db_path)
    await store.initialize()
    return store


@pytest_asyncio.fixture
async def unified_memory_for_tests(tmp_path, l2_store_for_tests):
    return _FakeUnifiedMemory(
        cognition_store=l2_store_for_tests,
        memory_db_path=str(tmp_path / "memory.db"),
    )
