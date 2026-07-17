from __future__ import annotations

import asyncio
import sqlite3
from pathlib import Path
from types import SimpleNamespace

import pytest
from alembic import command

from _shared.memory_schema import apply_memory_shared_schema
from magi.db.migrations.memory_shared.versions import v20_identity_rekey_indexes as migration
from magi.db.runner import MIGRATION_TARGETS, _build_config

V19_REVISION = "v19_claim_evidence_ledger"
V20_REVISION = "v20_identity_rekey_indexes"


def _memory_config(db_path: Path):
    target = next(item for item in MIGRATION_TARGETS if item.name == "memory_shared")
    return _build_config(target, db_path)


def _index_names(connection: sqlite3.Connection) -> set[str]:
    return {
        str(row[0])
        for row in connection.execute(
            "SELECT name FROM sqlite_master WHERE type = 'index'"
        ).fetchall()
    }


def test_identity_rekey_lookups_use_bounded_indexes(tmp_path) -> None:
    db_path = tmp_path / "memory.db"
    asyncio.run(apply_memory_shared_schema(str(db_path)))

    with sqlite3.connect(db_path) as connection:
        assertion_plan = connection.execute(
            """
            EXPLAIN QUERY PLAN
            SELECT assertion_id FROM tom_trait_assertions
            WHERE target_entity_id = ?
            """,
            ("person:ghost",),
        ).fetchall()
        correction_plan = connection.execute(
            """
            EXPLAIN QUERY PLAN
            SELECT correction_id FROM memory_corrections
            WHERE target_kind = 'edge'
              AND target_id IN (SELECT CAST(value AS TEXT) FROM json_each(?))
            UNION
            SELECT correction_id FROM memory_corrections
            WHERE target_kind = 'edge'
              AND replacement_target_id IN (
                  SELECT CAST(value AS TEXT) FROM json_each(?)
              )
            """,
            ('["triple:ghost"]', '["triple:ghost"]'),
        ).fetchall()

    assert "idx_tom_assertions_target_entity_updated" in " ".join(
        str(item) for row in assertion_plan for item in row
    )
    assert "idx_memory_corrections_replacement_created" in " ".join(
        str(item) for row in correction_plan for item in row
    )
    assert "idx_memory_corrections_target_created" in " ".join(
        str(item) for row in correction_plan for item in row
    )


def test_identity_rekey_index_migration_round_trips(tmp_path: Path) -> None:
    db_path = tmp_path / "memory.db"
    config = _memory_config(db_path)
    expected = {
        "idx_tom_assertions_target_entity_updated",
        "idx_memory_corrections_replacement_created",
    }

    command.upgrade(config, V19_REVISION)
    command.upgrade(config, V20_REVISION)
    with sqlite3.connect(db_path) as connection:
        assert expected <= _index_names(connection)

    command.downgrade(config, V19_REVISION)
    with sqlite3.connect(db_path) as connection:
        assert not (expected & _index_names(connection))

    command.upgrade(config, V20_REVISION)
    with sqlite3.connect(db_path) as connection:
        assert expected <= _index_names(connection)


def test_identity_rekey_index_upgrade_rolls_back_partial_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    connection = sqlite3.connect(":memory:")
    try:
        connection.execute("""
            CREATE TABLE tom_trait_assertions(
                target_entity_id TEXT NOT NULL,
                updated_at REAL NOT NULL
            )
            """)
        monkeypatch.setattr(
            migration.op,
            "get_bind",
            lambda: SimpleNamespace(connection=connection),
        )

        with pytest.raises(sqlite3.OperationalError, match="memory_corrections"):
            migration.upgrade()

        assert "idx_tom_assertions_target_entity_updated" not in _index_names(connection)
        assert not connection.in_transaction
    finally:
        connection.close()
