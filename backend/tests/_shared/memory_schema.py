"""Shared schema setup for memory tests.

Single source of truth for the memory_shared release baseline, used by
tests/memory/l2/conftest.py, tests/memory/l3/conftest.py, and
tests/api/conftest.py.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path
from types import ModuleType

import aiosqlite


_MIGRATIONS_DIR = (
    Path(__file__).resolve().parents[2]
    / "src" / "magi" / "db" / "migrations" / "memory_shared" / "versions"
)

MEMORY_SHARED_MIGRATIONS: tuple[str, ...] = (
    "v1_initial.py",
    "v2_experience_drafts.py",
    "v3_experience_draft_cover.py",
    "v4_memory_corrections.py",
    "v5_assertion_scope_uniqueness.py",
    "v6_relationship_governance_slots.py",
    "v7_l3_derivation_state.py",
)


def _load_migration(filename: str) -> ModuleType:
    migration_path = _MIGRATIONS_DIR / filename
    spec = importlib.util.spec_from_file_location(f"memory_shared_{filename}", migration_path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Could not load migration {migration_path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


async def apply_memory_shared_schema(db_path: str) -> None:
    """Apply the memory_shared release baseline to a fresh sqlite file."""
    for filename in MEMORY_SHARED_MIGRATIONS:
        sql = _load_migration(filename).SCHEMA_SQL
        async with aiosqlite.connect(db_path) as db:
            # executescript runs its own implicit COMMIT — no explicit commit needed.
            await db.executescript(sql)
