"""Round 5 I4: backfill script for entity_catalog.canonical_name.

Verifies plan_backfill / apply_backfill against a synthetic SQLite DB
covering each branch of the priority chain (alias > mention > skip) and
the safety invariants (no overwriting good names; hash-like candidates
rejected; missing tables tolerated).
"""

from __future__ import annotations

import importlib.util
import sqlite3
import sys
import time
from pathlib import Path

import pytest


SCRIPT_PATH = (
    Path(__file__).resolve().parents[2]
    / "scripts"
    / "backfill_entity_canonical_names.py"
)


def _load_script_module():
    spec = importlib.util.spec_from_file_location(
        "backfill_entity_canonical_names", SCRIPT_PATH
    )
    mod = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(mod)  # type: ignore[attr-defined]
    return mod


def _seed_db(path: Path) -> None:
    with sqlite3.connect(path) as conn:
        conn.executescript(
            """
            CREATE TABLE entity_catalog (
                entity_id TEXT PRIMARY KEY,
                canonical_name TEXT NOT NULL,
                entity_type TEXT NOT NULL,
                created_at REAL NOT NULL,
                updated_at REAL NOT NULL
            );
            CREATE TABLE entity_aliases (
                alias_id INTEGER PRIMARY KEY AUTOINCREMENT,
                entity_id TEXT NOT NULL,
                alias_text TEXT NOT NULL,
                normalized_alias TEXT NOT NULL,
                confidence REAL NOT NULL DEFAULT 1.0,
                created_at REAL NOT NULL,
                updated_at REAL NOT NULL
            );
            CREATE TABLE entity_mentions (
                mention_id INTEGER PRIMARY KEY AUTOINCREMENT,
                mention_text TEXT NOT NULL,
                normalized_surface TEXT NOT NULL,
                resolved_entity_id TEXT,
                created_at REAL NOT NULL
            );
            """
        )
        now = time.time()
        # Row 1: hash-like canonical_name matching slug. Has a high-confidence
        # alias → should backfill from alias.
        conn.execute(
            "INSERT INTO entity_catalog VALUES (?, ?, ?, ?, ?)",
            ("organization:74f953b57f75", "74f953b57f75", "organization", now, now),
        )
        conn.execute(
            "INSERT INTO entity_aliases (entity_id, alias_text, normalized_alias, "
            "confidence, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?)",
            ("organization:74f953b57f75", "字节跳动", "bytedance", 0.95, now, now),
        )
        conn.execute(
            "INSERT INTO entity_aliases (entity_id, alias_text, normalized_alias, "
            "confidence, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?)",
            ("organization:74f953b57f75", "Bytedance", "bytedance", 0.50, now, now),
        )
        # Row 2: hash-like, NO alias, has mentions → backfill from mention.
        conn.execute(
            "INSERT INTO entity_catalog VALUES (?, ?, ?, ?, ?)",
            ("person:abc123def456", "abc123def456", "person", now, now),
        )
        for txt in ["子涵", "子涵", "Mary"]:
            conn.execute(
                "INSERT INTO entity_mentions (mention_text, normalized_surface, "
                "resolved_entity_id, created_at) VALUES (?, ?, ?, ?)",
                (txt, txt.lower(), "person:abc123def456", now),
            )
        # Row 3: hash-like, no data → no candidate, skipped.
        conn.execute(
            "INSERT INTO entity_catalog VALUES (?, ?, ?, ?, ?)",
            ("organization:deadbeef1234", "deadbeef1234", "organization", now, now),
        )
        # Row 4: ALREADY GOOD name → skipped, never overwritten.
        conn.execute(
            "INSERT INTO entity_catalog VALUES (?, ?, ?, ?, ?)",
            ("user:local_user", "Asuka", "user", now, now),
        )
        # Even if an alias exists, don't overwrite a good canonical_name.
        conn.execute(
            "INSERT INTO entity_aliases (entity_id, alias_text, normalized_alias, "
            "confidence, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?)",
            ("user:local_user", "Master", "master", 1.0, now, now),
        )
        # Row 5: hash-like alias should be rejected as candidate; no real
        # candidate → skipped.
        conn.execute(
            "INSERT INTO entity_catalog VALUES (?, ?, ?, ?, ?)",
            ("topic:cafebabe1234", "cafebabe1234", "topic", now, now),
        )
        conn.execute(
            "INSERT INTO entity_aliases (entity_id, alias_text, normalized_alias, "
            "confidence, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?)",
            ("topic:cafebabe1234", "feeddead0000", "feeddead0000", 0.99, now, now),
        )
        conn.commit()


def test_plan_lists_expected_updates(tmp_path) -> None:
    mod = _load_script_module()
    db = tmp_path / "memory.db"
    _seed_db(db)

    updates, stats = mod.plan_backfill(db)

    by_id = {u[0]: u for u in updates}
    # Hash-like w/ alias → backfilled from alias.
    assert "organization:74f953b57f75" in by_id
    _, old, new, source = by_id["organization:74f953b57f75"]
    assert old == "74f953b57f75"
    assert new == "字节跳动"
    assert source == "alias"
    # Hash-like w/ only mentions → backfilled from most-frequent mention.
    assert "person:abc123def456" in by_id
    _, _, new2, src2 = by_id["person:abc123def456"]
    assert new2 == "子涵"
    assert src2 == "mention"
    # Already-good row never planned for update.
    assert "user:local_user" not in by_id
    # Hash-like w/ no data → skipped.
    assert "organization:deadbeef1234" not in by_id
    # Hash-like alias rejected, no other source → skipped.
    assert "topic:cafebabe1234" not in by_id

    assert stats["total"] == 5
    assert stats["plan_update"] == 2
    assert stats["needs_backfill"] == 4  # all hash-like rows
    # Both `deadbeef` (no data) and `cafebabe` (only hash-like alias, which
    # is filtered out at the alias_map step) end up in no_candidate.
    assert stats["no_candidate"] == 2


def test_apply_writes_only_planned_rows(tmp_path) -> None:
    mod = _load_script_module()
    db = tmp_path / "memory.db"
    _seed_db(db)

    updates, _ = mod.plan_backfill(db)
    written = mod.apply_backfill(db, updates)
    assert written == len(updates)

    with sqlite3.connect(db) as conn:
        rows = dict(
            conn.execute("SELECT entity_id, canonical_name FROM entity_catalog").fetchall()
        )
    assert rows["organization:74f953b57f75"] == "字节跳动"
    assert rows["person:abc123def456"] == "子涵"
    # Good name preserved.
    assert rows["user:local_user"] == "Asuka"
    # No-candidate rows unchanged.
    assert rows["organization:deadbeef1234"] == "deadbeef1234"
    assert rows["topic:cafebabe1234"] == "cafebabe1234"


def test_idempotent(tmp_path) -> None:
    mod = _load_script_module()
    db = tmp_path / "memory.db"
    _seed_db(db)

    updates, _ = mod.plan_backfill(db)
    mod.apply_backfill(db, updates)

    # Second run: nothing to do.
    updates2, stats2 = mod.plan_backfill(db)
    assert updates2 == []
    assert stats2.get("plan_update", 0) == 0


def test_tolerates_missing_table(tmp_path) -> None:
    mod = _load_script_module()
    db = tmp_path / "empty.db"
    sqlite3.connect(db).close()  # no tables
    updates, stats = mod.plan_backfill(db)
    assert updates == []
    assert stats == {}


def test_is_hash_like_threshold() -> None:
    mod = _load_script_module()
    assert mod._is_hash_like("74f953b57f75")
    assert mod._is_hash_like("deadbeef1234")
    assert not mod._is_hash_like("local_user")
    assert not mod._is_hash_like("字节跳动")
    assert not mod._is_hash_like("abc")  # too short
    assert not mod._is_hash_like("")
