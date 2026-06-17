"""Shared schema setup for memory tests.

Single source of truth for the memory_shared migration list, used by
tests/memory/l2/conftest.py, tests/memory/l3/conftest.py, and
tests/api/conftest.py. Add each new migration filename to MEMORY_SHARED_MIGRATIONS
in order.
"""

from __future__ import annotations

import re
from pathlib import Path

import aiosqlite


_MIGRATIONS_DIR = (
    Path(__file__).resolve().parents[2]
    / "src" / "magi" / "db" / "migrations" / "memory_shared" / "versions"
)

# MAINTENANCE: add each new memory_shared migration filename here in order,
# synchronized with backend/src/magi/db/migrations/memory_shared/versions/.
MEMORY_SHARED_MIGRATIONS: tuple[str, ...] = (
    "0001_initial.py",
    "0002_user_profile_projection.py",
    "0003_l2_episode_immersive_columns.py",
    "0004_l3_summary_essence_prose.py",
    "0005_daily_mood_aggregate.py",
    "0006_location_samples.py",
    "0007_manual_entries.py",
    "0008_manual_entries_weather.py",
    "0009_manual_entries_body_doc.py",
    "0010_kg_evidence_class.py",
    "0012_drop_privacy_scope.py",
    "0013_tom_assertions_shadow_status.py",
    "0014_preference_profile_family.py",
)


def _extract_schema_sql(filename: str) -> str:
    """Extract the SCHEMA_SQL constant from a migration file via regex.

    We use string extraction rather than module import because Python
    cannot import modules whose names start with a digit (e.g. 0001_initial).
    """
    src = (_MIGRATIONS_DIR / filename).read_text()
    match = re.search(r'SCHEMA_SQL\s*=\s*"""(.*?)"""', src, re.S)
    if not match:
        raise RuntimeError(f"SCHEMA_SQL not found in {filename}")
    return match.group(1)


async def apply_memory_shared_schema(db_path: str) -> None:
    """Apply all memory_shared migrations to a fresh sqlite file."""
    for filename in MEMORY_SHARED_MIGRATIONS:
        sql = _extract_schema_sql(filename)
        async with aiosqlite.connect(db_path) as db:
            # executescript runs its own implicit COMMIT — no explicit commit needed.
            await db.executescript(sql)
