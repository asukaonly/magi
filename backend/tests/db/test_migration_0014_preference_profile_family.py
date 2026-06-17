"""Test migration 0014: removed taste_profile family is normalized."""

from __future__ import annotations

import importlib.util
import sqlite3
from pathlib import Path
from types import ModuleType


_VERSIONS_DIR = (
    Path(__file__).resolve().parents[2]
    / "src"
    / "magi"
    / "db"
    / "migrations"
    / "memory_shared"
    / "versions"
)

_TABLE_SQL = """
CREATE TABLE tom_trait_assertions (
    assertion_id TEXT PRIMARY KEY,
    trait_family TEXT NOT NULL,
    trait_name TEXT NOT NULL
);
"""


def _load_migration() -> ModuleType:
    migration_path = _VERSIONS_DIR / "0014_preference_profile_family.py"
    spec = importlib.util.spec_from_file_location(
        "migration_0014_preference_profile_family",
        migration_path,
    )
    assert spec is not None, f"Could not create spec for {migration_path}"
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _build_pre_migration_db() -> sqlite3.Connection:
    conn = sqlite3.connect(":memory:")
    conn.executescript(_TABLE_SQL)
    conn.executemany(
        """
        INSERT INTO tom_trait_assertions (assertion_id, trait_family, trait_name)
        VALUES (?, ?, ?)
        """,
        [
            ("a1", "taste_profile", "taste.music"),
            ("a2", "taste_profile", "preference.music.genres"),
            ("a3", "routine_profile", "routine.work_hours"),
        ],
    )
    return conn


def test_migration_module_loads() -> None:
    mod = _load_migration()

    assert mod.revision == "0014_preference_profile_family"
    assert mod.down_revision == "0013_tom_assertions_shadow_status"


def test_taste_profile_rows_are_normalized() -> None:
    conn = _build_pre_migration_db()
    mod = _load_migration()

    mod.apply(conn)
    mod.apply(conn)

    rows = conn.execute(
        """
        SELECT assertion_id, trait_family
        FROM tom_trait_assertions
        ORDER BY assertion_id
        """
    ).fetchall()

    assert rows == [
        ("a1", "preference_profile"),
        ("a2", "preference_profile"),
        ("a3", "routine_profile"),
    ]
