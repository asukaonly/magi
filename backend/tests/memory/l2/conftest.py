"""Shared fixtures for L2 memory tests.

This conftest provides an opt-in fixture that applies the memory_shared
Alembic migrations to a fresh tmp_path DB before constructing an
L2CognitionStore. Without this, store.initialize() fails because the
graph_conflict_rules table (and others) only exist after migrations run.

Existing tests under tests/memory/l2/ that don't use this fixture have
pre-existing failures unrelated to any current work.
"""

from __future__ import annotations

import re
from pathlib import Path

import aiosqlite
import pytest_asyncio


_MIGRATIONS_DIR = Path(__file__).resolve().parents[3] / "src" / "magi" / "db" / "migrations" / "memory_shared" / "versions"


def _extract_schema_sql(filename: str) -> str:
    """Extract the SCHEMA_SQL constant from a migration file.

    We use string extraction rather than module import because Python
    cannot import modules whose names start with a digit (e.g. 0001_initial).
    """
    src = (_MIGRATIONS_DIR / filename).read_text()
    match = re.search(r'SCHEMA_SQL\s*=\s*"""(.*?)"""', src, re.S)
    if not match:
        raise RuntimeError(f"SCHEMA_SQL not found in {filename}")
    return match.group(1)


async def _apply_memory_shared_schema(db_path: str) -> None:
    """Apply all memory_shared migrations to a fresh sqlite file."""
    statements: list[str] = []
    # Apply migrations in order. As Plan 1 lands, 0004 and 0005 will be added.
    for filename in (
        "0001_initial.py",
        "0002_user_profile_projection.py",
        "0003_l2_episode_immersive_columns.py",
    ):
        statements.append(_extract_schema_sql(filename))

    async with aiosqlite.connect(db_path) as db:
        for sql in statements:
            await db.executescript(sql)
        await db.commit()


@pytest_asyncio.fixture
async def l2_store_with_schema(tmp_path):
    """An L2CognitionStore backed by a tmp_path DB with all memory_shared schema applied.

    Use this fixture for any test that needs L2CognitionStore.initialize() to succeed.
    """
    from magi.memory.l2.store import L2CognitionStore

    db_path = str(tmp_path / "l2.db")
    await _apply_memory_shared_schema(db_path)
    store = L2CognitionStore(db_path=db_path)
    await store.initialize()
    return store
