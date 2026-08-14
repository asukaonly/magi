from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest
from alembic import command

from magi.db.runner import MIGRATION_TARGETS, _build_config

V31_REVISION = "v31_correction_replacement_slot_index"
V32_REVISION = "v32_forget_source_owner_refs"
MEMORY_HEAD_REVISION = "v47_history_import_deletion_privacy"


def _memory_config(db_path: Path):
    target = next(item for item in MIGRATION_TARGETS if item.name == "memory_shared")
    return _build_config(target, db_path)


def _seed_operation(connection: sqlite3.Connection) -> None:
    connection.execute(
        """
        INSERT INTO memory_forget_operations(
            operation_id, selector_kind, selector_hash, selector_json,
            reason, created_at, updated_at
        ) VALUES (
            'forget:source-owner-test', 'known_events', 'selector-hash',
            '{"event_ids":["event-1"],"block_source_item":true}',
            'test', 1.0, 1.0
        )
        """
    )
    connection.execute(
        """
        INSERT INTO memory_forget_operation_refs(
            operation_id, item_event_id, ref_role, ref_type,
            source_ref, created_at
        ) VALUES (
            'forget:source-owner-test', 'event-1', 'barrier',
            'exact_event', 'event-1', 1.0
        )
        """
    )
    connection.commit()


def test_source_owner_ref_migration_preserves_and_downgrades_data(
    tmp_path: Path,
) -> None:
    db_path = tmp_path / "memory.db"
    config = _memory_config(db_path)
    command.upgrade(config, V31_REVISION)
    with sqlite3.connect(db_path) as connection:
        _seed_operation(connection)

    command.upgrade(config, V32_REVISION)
    with sqlite3.connect(db_path) as connection:
        assert connection.execute("SELECT version_num FROM alembic_version").fetchone() == (
            V32_REVISION,
        )
        assert connection.execute(
            """
            SELECT source_ref
            FROM memory_forget_operation_refs
            WHERE ref_type = 'exact_event'
            """
        ).fetchall() == [("event-1",)]
        connection.execute(
            """
            INSERT INTO memory_forget_operation_refs(
                operation_id, item_event_id, ref_role, ref_type,
                source_ref, created_at
            ) VALUES (
                'forget:source-owner-test', '', 'target', 'source_owner',
                '{"source":"manual_entry"}', 2.0
            )
            """
        )
        connection.commit()
        assert connection.execute("PRAGMA foreign_key_check").fetchall() == []

    command.downgrade(config, V31_REVISION)
    with sqlite3.connect(db_path) as connection:
        assert connection.execute("SELECT version_num FROM alembic_version").fetchone() == (
            V31_REVISION,
        )
        assert connection.execute(
            """
            SELECT ref_type, source_ref
            FROM memory_forget_operation_refs
            ORDER BY ref_type, source_ref
            """
        ).fetchall() == [("exact_event", "event-1")]
        with pytest.raises(sqlite3.IntegrityError):
            connection.execute(
                """
                INSERT INTO memory_forget_operation_refs(
                    operation_id, item_event_id, ref_role, ref_type,
                    source_ref, created_at
                ) VALUES (
                    'forget:source-owner-test', '', 'target', 'source_owner',
                    'claim', 3.0
                )
                """
            )
        assert connection.execute("PRAGMA foreign_key_check").fetchall() == []


def test_memory_head_includes_source_owner_ref_revision(tmp_path: Path) -> None:
    db_path = tmp_path / "memory.db"
    command.upgrade(_memory_config(db_path), "head")
    with sqlite3.connect(db_path) as connection:
        assert connection.execute("SELECT version_num FROM alembic_version").fetchone() == (
            MEMORY_HEAD_REVISION,
        )
