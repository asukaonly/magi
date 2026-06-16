"""Test migration 0013: 'shadow' status added to active-unique index exclusion.

Loads the migration module via importlib (its name starts with a digit, so
normal import is not possible — mirrors the pattern in
tests/api/test_gateway_api_contract.py::_load_contract_checker).
"""
from __future__ import annotations

import importlib.util
import sqlite3
import tempfile
from pathlib import Path
from types import ModuleType

import pytest


_VERSIONS_DIR = (
    Path(__file__).resolve().parents[2]
    / "src"
    / "magi"
    / "db"
    / "migrations"
    / "memory_shared"
    / "versions"
)

_OLD_INDEX_SQL = (
    "CREATE UNIQUE INDEX IF NOT EXISTS idx_tom_assertions_active_unique "
    "ON tom_trait_assertions(entity_id, entity_type, trait_name, target_entity_id) "
    "WHERE status NOT IN ('superseded', 'archived', 'expired', 'user_rejected');"
)

_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS tom_trait_assertions (
    assertion_id    TEXT PRIMARY KEY,
    entity_id       TEXT NOT NULL,
    entity_type     TEXT NOT NULL DEFAULT 'user',
    trait_name      TEXT NOT NULL,
    target_entity_id TEXT,
    status          TEXT NOT NULL DEFAULT 'active'
);
"""


def _load_migration(filename: str) -> ModuleType:
    migration_path = _VERSIONS_DIR / filename
    spec = importlib.util.spec_from_file_location("migration_0013_shadow_status", migration_path)
    assert spec is not None, f"Could not create spec for {migration_path}"
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _build_pre_migration_db() -> sqlite3.Connection:
    """Return an in-memory sqlite3 connection with the OLD schema (pre-0012)."""
    conn = sqlite3.connect(":memory:")
    conn.executescript(_TABLE_SQL + _OLD_INDEX_SQL)
    return conn


def test_migration_module_loads() -> None:
    """The migration file must exist and be importable."""
    mod = _load_migration("0013_tom_assertions_shadow_status.py")
    assert mod.revision == "0013_tom_assertions_shadow_status"
    assert mod.down_revision == "0012_drop_privacy_scope"


def test_shadow_appears_in_index_where_clause_after_migration() -> None:
    """After apply(), the index WHERE clause must include 'shadow'."""
    conn = _build_pre_migration_db()
    mod = _load_migration("0013_tom_assertions_shadow_status.py")

    # Pre-condition: 'shadow' is NOT in the index before migration.
    rows = conn.execute(
        "SELECT sql FROM sqlite_master WHERE type='index' AND name='idx_tom_assertions_active_unique'"
    ).fetchall()
    assert rows, "Index must exist before migration"
    pre_sql = rows[0][0]
    assert "shadow" not in pre_sql, f"Expected 'shadow' absent before migration, got: {pre_sql}"

    # Apply the migration.
    mod.apply(conn)

    # Post-condition: 'shadow' IS in the index WHERE clause.
    rows = conn.execute(
        "SELECT sql FROM sqlite_master WHERE type='index' AND name='idx_tom_assertions_active_unique'"
    ).fetchall()
    assert rows, "Index must still exist after migration"
    post_sql = rows[0][0]
    assert "shadow" in post_sql, f"Expected 'shadow' in index WHERE after migration, got: {post_sql}"


def test_shadow_and_active_rows_can_coexist_after_migration() -> None:
    """After apply(), inserting both an 'active' and a 'shadow' row on the same
    (entity_id, entity_type, trait_name, target_entity_id) key must not raise
    a UNIQUE constraint violation.

    Note: target_entity_id must be non-NULL so the partial unique index applies
    (SQLite treats NULL != NULL in unique indexes, making NULLs invisible to the
    constraint).
    """
    conn = _build_pre_migration_db()
    mod = _load_migration("0013_tom_assertions_shadow_status.py")
    mod.apply(conn)

    # Insert the authoritative 'active' row.
    conn.execute(
        "INSERT INTO tom_trait_assertions "
        "(assertion_id, entity_id, entity_type, trait_name, target_entity_id, status) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        ("a1", "user_1", "user", "likes_music", "entity_rock", "active"),
    )

    # Insert the 'shadow' row on the same key — must NOT raise.
    conn.execute(
        "INSERT INTO tom_trait_assertions "
        "(assertion_id, entity_id, entity_type, trait_name, target_entity_id, status) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        ("a2", "user_1", "user", "likes_music", "entity_rock", "shadow"),
    )

    count = conn.execute(
        "SELECT COUNT(*) FROM tom_trait_assertions WHERE entity_id='user_1'"
    ).fetchone()[0]
    assert count == 2, f"Expected 2 rows (active + shadow), got {count}"


def test_two_active_rows_still_violate_after_migration() -> None:
    """The unique constraint must still prevent two 'active' rows on the same key.

    Note: target_entity_id must be non-NULL so the unique constraint fires
    (SQLite treats NULL != NULL in unique indexes).
    """
    conn = _build_pre_migration_db()
    mod = _load_migration("0013_tom_assertions_shadow_status.py")
    mod.apply(conn)

    conn.execute(
        "INSERT INTO tom_trait_assertions "
        "(assertion_id, entity_id, entity_type, trait_name, target_entity_id, status) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        ("b1", "user_2", "user", "likes_jazz", "entity_jazz", "active"),
    )

    with pytest.raises(sqlite3.IntegrityError):
        conn.execute(
            "INSERT INTO tom_trait_assertions "
            "(assertion_id, entity_id, entity_type, trait_name, target_entity_id, status) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            ("b2", "user_2", "user", "likes_jazz", "entity_jazz", "active"),
        )
