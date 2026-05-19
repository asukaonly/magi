"""Shared fixtures for API tests.

Provides a fake `unified_memory` whose only exposed surface is the
attributes the TimelineService accesses. Real unified_memory is built by
the bootstrap composition root, which is too heavy to spin up for unit
tests. The fake is a thin object that hands TimelineService a real
L2CognitionStore bound to a tmp_path DB.
"""

from __future__ import annotations

import re
from pathlib import Path

import aiosqlite
import pytest_asyncio


_MIGRATIONS_DIR = Path(__file__).resolve().parents[2] / "src" / "magi" / "db" / "migrations" / "memory_shared" / "versions"


def _extract_schema_sql(filename: str) -> str:
    src = (_MIGRATIONS_DIR / filename).read_text()
    match = re.search(r'SCHEMA_SQL\s*=\s*"""(.*?)"""', src, re.S)
    if not match:
        raise RuntimeError(f"SCHEMA_SQL not found in {filename}")
    return match.group(1)


async def _apply_memory_shared_schema(db_path: str) -> None:
    """Apply all memory_shared migrations to a fresh sqlite file.

    MAINTENANCE: keep this tuple synchronized with the L2/L3 conftests and with
    backend/src/magi/db/migrations/memory_shared/versions/.
    """
    for filename in (
        "0001_initial.py",
        "0002_user_profile_projection.py",
        "0003_l2_episode_immersive_columns.py",
        "0004_l3_summary_essence_prose.py",
        "0005_daily_mood_aggregate.py",
    ):
        sql = _extract_schema_sql(filename)
        async with aiosqlite.connect(db_path) as db:
            await db.executescript(sql)


class _FakeL2Pipeline:
    """Stand-in for the runtime L2 pipeline; exposes only the surface
    TimelineService touches."""

    def __init__(self, cognition_store) -> None:
        self._cognition_store = cognition_store


class _FakeUnifiedMemory:
    """Stand-in for the runtime unified_memory facade.

    Only exposes attributes the TimelineService currently reads. Tests
    that need richer behavior should extend this class with additional
    properties as new code paths are added.
    """

    def __init__(self, *, cognition_store, memory_db_path: str) -> None:
        self.l2_pipeline = _FakeL2Pipeline(cognition_store)
        self.memory_db_path = memory_db_path


@pytest_asyncio.fixture
async def l2_store_for_tests(tmp_path):
    from magi.memory.l2.store import L2CognitionStore

    db_path = str(tmp_path / "memory.db")
    await _apply_memory_shared_schema(db_path)
    store = L2CognitionStore(db_path=db_path)
    await store.initialize()
    return store


@pytest_asyncio.fixture
async def unified_memory_for_tests(tmp_path, l2_store_for_tests):
    return _FakeUnifiedMemory(
        cognition_store=l2_store_for_tests,
        memory_db_path=str(tmp_path / "memory.db"),
    )
