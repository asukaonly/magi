"""Shared fixtures for L3 memory tests.

Mirrors the opt-in pattern from tests/memory/l2/conftest.py: applies the
memory_shared Alembic migrations to a fresh tmp_path DB before constructing
an L3SummaryStore. Without this, _store_summary fails because the
`summaries` table does not exist in a bare sqlite file.
"""

from __future__ import annotations

import re
from pathlib import Path

import aiosqlite
import pytest_asyncio


_MIGRATIONS_DIR = (
    Path(__file__).resolve().parents[3]
    / "src"
    / "magi"
    / "db"
    / "migrations"
    / "memory_shared"
    / "versions"
)


def _extract_schema_sql(filename: str) -> str:
    src = (_MIGRATIONS_DIR / filename).read_text()
    match = re.search(r'SCHEMA_SQL\s*=\s*"""(.*?)"""', src, re.S)
    if not match:
        raise RuntimeError(f"SCHEMA_SQL not found in {filename}")
    return match.group(1)


async def _apply_memory_shared_schema(db_path: str) -> None:
    """Apply all memory_shared migrations to a fresh sqlite file."""
    # MAINTENANCE: keep this tuple synchronized with the L2 conftest and with
    # backend/src/magi/db/migrations/memory_shared/versions/.
    for filename in (
        "0001_initial.py",
        "0002_user_profile_projection.py",
        "0003_l2_episode_immersive_columns.py",
        "0004_l3_summary_essence_prose.py",
        "0005_daily_mood_aggregate.py",
    ):
        sql = _extract_schema_sql(filename)
        async with aiosqlite.connect(db_path) as db:
            # executescript runs its own implicit COMMIT — no explicit commit needed.
            await db.executescript(sql)


@pytest_asyncio.fixture
async def l3_store_with_schema(tmp_path):
    """An L3SummaryStore backed by a tmp_path DB with all memory_shared schema applied."""
    from magi.memory.l3.summary_store import L3SummaryStore

    db_path = str(tmp_path / "memory.db")
    await _apply_memory_shared_schema(db_path)
    store = L3SummaryStore(db_path=db_path)
    await store.initialize()
    return store
