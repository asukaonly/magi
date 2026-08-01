from __future__ import annotations

import sqlite3
from pathlib import Path

from alembic import command
import pytest

from magi.db.runner import MIGRATION_TARGETS, _build_config
from magi.plugins.user_content_clear_checkpoint import (
    PluginUserContentClearCheckpointStore,
)


def _config(db_path: Path):  # type: ignore[no-untyped-def]
    target = next(item for item in MIGRATION_TARGETS if item.name == "message_queue")
    return _build_config(target, db_path)


@pytest.mark.asyncio
async def test_checkpoint_persists_applied_shared_generation(tmp_path: Path) -> None:
    db_path = tmp_path / "message-queue.db"
    command.upgrade(_config(db_path), "head")
    store = PluginUserContentClearCheckpointStore(db_path)

    assert await store.read_applied_generation() == 0
    await store.mark_applied(4)

    reopened = PluginUserContentClearCheckpointStore(db_path)
    assert await reopened.read_applied_generation() == 4
    with sqlite3.connect(db_path) as connection:
        generation = connection.execute(
            """
            SELECT generation
            FROM runtime_user_message_clear_state
            WHERE singleton_id = 1
            """
        ).fetchone()
    assert generation == (0,)


@pytest.mark.asyncio
async def test_checkpoint_rejects_generation_regression(tmp_path: Path) -> None:
    db_path = tmp_path / "message-queue.db"
    command.upgrade(_config(db_path), "head")
    store = PluginUserContentClearCheckpointStore(db_path)
    await store.mark_applied(4)

    with pytest.raises(RuntimeError, match="cannot move backward"):
        await store.mark_applied(3)

    assert await store.read_applied_generation() == 4


@pytest.mark.asyncio
async def test_checkpoint_can_restore_only_its_just_written_generation(
    tmp_path: Path,
) -> None:
    db_path = tmp_path / "message-queue.db"
    command.upgrade(_config(db_path), "head")
    store = PluginUserContentClearCheckpointStore(db_path)
    await store.mark_applied(4)

    await store.restore_pending(
        clear_generation=4,
        previous_applied_generation=0,
    )

    assert await store.read_applied_generation() == 0
    with pytest.raises(RuntimeError, match="changed before rollback"):
        await store.restore_pending(
            clear_generation=4,
            previous_applied_generation=0,
        )


def test_checkpoint_downgrade_fails_closed_after_a_clear(tmp_path: Path) -> None:
    db_path = tmp_path / "message-queue.db"
    config = _config(db_path)
    command.upgrade(config, "head")
    with sqlite3.connect(db_path) as connection:
        connection.execute(
            """
            UPDATE runtime_plugin_user_content_clear_state
            SET applied_generation = 2
            WHERE singleton_id = 1
            """
        )
        connection.commit()

    with pytest.raises(RuntimeError, match="checkpoint exists"):
        command.downgrade(config, "v5")

    with sqlite3.connect(db_path) as connection:
        assert connection.execute(
            "SELECT applied_generation FROM runtime_plugin_user_content_clear_state"
        ).fetchone() == (2,)


def test_checkpoint_migration_seeds_completed_existing_generation(
    tmp_path: Path,
) -> None:
    db_path = tmp_path / "message-queue.db"
    config = _config(db_path)
    command.upgrade(config, "v5")
    with sqlite3.connect(db_path) as connection:
        connection.execute(
            """
            UPDATE runtime_user_message_clear_state
            SET generation = 7
            WHERE singleton_id = 1
            """
        )
        connection.commit()

    command.upgrade(config, "head")

    with sqlite3.connect(db_path) as connection:
        assert connection.execute(
            "SELECT applied_generation FROM runtime_plugin_user_content_clear_state"
        ).fetchone() == (7,)
