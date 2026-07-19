from __future__ import annotations

import sqlite3
from pathlib import Path

from alembic import command
import pytest

from magi.db.runner import MIGRATION_TARGETS, _build_config
from magi.db.migrations.memory_shared.versions import (
    v33_chat_forget_activation as activation_migration,
)

V32_REVISION = "v32_forget_source_owner_refs"
V33_REVISION = "v33_chat_forget_activation"


def _memory_config(db_path: Path):
    target = next(
        item for item in MIGRATION_TARGETS if item.name == "memory_shared"
    )
    return _build_config(target, db_path)


def _prepare_v32_operation(db_path: Path) -> None:
    config = _memory_config(db_path)
    command.upgrade(config, V32_REVISION)
    with sqlite3.connect(db_path) as connection:
        connection.execute(
            """
            INSERT INTO memory_forget_operations (
                operation_id, selector_kind, selector_hash, selector_json,
                reason, created_at, updated_at
            ) VALUES (
                'forget-resume', 'chat_message', 'selector-resume', '{}',
                'test interrupted migration', 1, 1
            )
            """
        )
        connection.commit()


def test_v33_fresh_database_has_activation_schema(tmp_path: Path) -> None:
    db_path = tmp_path / "memory-fresh.db"
    config = _memory_config(db_path)

    command.upgrade(config, "head")

    with sqlite3.connect(db_path) as connection:
        columns = {
            str(row[1])
            for row in connection.execute(
                "PRAGMA table_info(memory_forget_operations)"
            )
        }
        assert "execution_ready" in columns
        assert connection.execute(
            """
            SELECT version_num
            FROM alembic_version
            """
        ).fetchone() == (V33_REVISION,)


@pytest.mark.parametrize("interruption", ["column_only", "index_only"])
def test_v33_upgrade_resumes_each_additive_ddl_boundary(
    tmp_path: Path,
    interruption: str,
) -> None:
    db_path = tmp_path / f"memory-{interruption}.db"
    config = _memory_config(db_path)
    _prepare_v32_operation(db_path)

    with sqlite3.connect(db_path) as connection:
        connection.execute(activation_migration._ADD_COLUMN_SQL)
        if interruption == "index_only":
            connection.execute(activation_migration._CREATE_INDEX_SQL)
        connection.commit()

    command.upgrade(config, "head")
    command.upgrade(config, "head")

    with sqlite3.connect(db_path) as connection:
        assert connection.execute(
            """
            SELECT execution_ready
            FROM memory_forget_operations
            WHERE operation_id = 'forget-resume'
            """
        ).fetchone() == (1,)
        index_columns = tuple(
            str(row[2])
            for row in connection.execute(
                "PRAGMA index_info(idx_memory_forget_operations_activation)"
            )
        )
        assert index_columns == (
            "execution_ready",
            "status",
            "lease_expires_at",
            "updated_at",
            "operation_id",
        )
        assert connection.execute(
            "SELECT version_num FROM alembic_version"
        ).fetchone() == (V33_REVISION,)


def test_v33_upgrade_rejects_activation_column_without_constraint(
    tmp_path: Path,
) -> None:
    db_path = tmp_path / "memory-invalid-column.db"
    config = _memory_config(db_path)
    _prepare_v32_operation(db_path)

    with sqlite3.connect(db_path) as connection:
        connection.execute(
            """
            ALTER TABLE memory_forget_operations
            ADD COLUMN execution_ready INTEGER NOT NULL DEFAULT 1
            """
        )
        connection.commit()

    with pytest.raises(RuntimeError, match="unsupported schema"):
        command.upgrade(config, "head")

    with sqlite3.connect(db_path) as connection:
        assert connection.execute(
            """
            SELECT execution_ready
            FROM memory_forget_operations
            WHERE operation_id = 'forget-resume'
            """
        ).fetchone() == (1,)
        assert connection.execute(
            "SELECT version_num FROM alembic_version"
        ).fetchone() == (V32_REVISION,)


def test_v33_upgrade_rejects_wrong_activation_index(
    tmp_path: Path,
) -> None:
    db_path = tmp_path / "memory-invalid-index.db"
    config = _memory_config(db_path)
    _prepare_v32_operation(db_path)

    with sqlite3.connect(db_path) as connection:
        connection.execute(activation_migration._ADD_COLUMN_SQL)
        connection.execute(
            """
            CREATE INDEX idx_memory_forget_operations_activation
            ON memory_forget_operations(status, operation_id)
            """
        )
        connection.commit()

    with pytest.raises(RuntimeError, match="index has an unsupported schema"):
        command.upgrade(config, "head")

    with sqlite3.connect(db_path) as connection:
        assert connection.execute(
            """
            SELECT reason
            FROM memory_forget_operations
            WHERE operation_id = 'forget-resume'
            """
        ).fetchone() == ("test interrupted migration",)
        assert connection.execute(
            "SELECT version_num FROM alembic_version"
        ).fetchone() == (V32_REVISION,)


def test_v33_downgrade_remains_fail_closed(tmp_path: Path) -> None:
    db_path = tmp_path / "memory-downgrade.db"
    config = _memory_config(db_path)
    command.upgrade(config, "head")

    with pytest.raises(
        RuntimeError,
        match="Memory schema downgrades are not supported",
    ):
        command.downgrade(config, V32_REVISION)

    with sqlite3.connect(db_path) as connection:
        assert connection.execute(
            "SELECT version_num FROM alembic_version"
        ).fetchone() == (V33_REVISION,)
        assert "execution_ready" in {
            str(row[1])
            for row in connection.execute(
                "PRAGMA table_info(memory_forget_operations)"
            )
        }
