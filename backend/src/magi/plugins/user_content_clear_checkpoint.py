"""Durable plugin clear checkpoint backed by the runtime command database."""

from __future__ import annotations

import time
from pathlib import Path

from ..core.sqlite import sqlite_connection_async

_CHECKPOINT_ID = 1


class PluginUserContentClearCheckpointStore:
    """Record which shared full-clear generation all plugin hooks applied."""

    def __init__(self, db_path: str | Path) -> None:
        self._db_path = str(Path(db_path).expanduser())

    async def read_applied_generation(self) -> int:
        """Return the latest generation completed by every plugin hook."""

        async with sqlite_connection_async(self._db_path) as db:
            cursor = await db.execute(
                """
                SELECT applied_generation
                FROM runtime_plugin_user_content_clear_state
                WHERE singleton_id = ?
                """,
                (_CHECKPOINT_ID,),
            )
            row = await cursor.fetchone()
        if row is None:
            raise RuntimeError("Plugin user-content clear checkpoint is missing")
        return int(row[0])

    async def mark_applied(self, clear_generation: int) -> None:
        """Advance the checkpoint after every hook succeeds."""

        if isinstance(clear_generation, bool) or clear_generation < 1:
            raise ValueError("clear_generation must be a positive integer")
        async with sqlite_connection_async(self._db_path) as db:
            await db.execute("BEGIN IMMEDIATE")
            try:
                cursor = await db.execute(
                    """
                    SELECT applied_generation
                    FROM runtime_plugin_user_content_clear_state
                    WHERE singleton_id = ?
                    """,
                    (_CHECKPOINT_ID,),
                )
                row = await cursor.fetchone()
                if row is None:
                    raise RuntimeError(
                        "Plugin user-content clear checkpoint is missing"
                    )
                applied_generation = int(row[0])
                if clear_generation < applied_generation:
                    raise RuntimeError(
                        "Plugin user-content clear checkpoint cannot move backward"
                    )
                await db.execute(
                    """
                    UPDATE runtime_plugin_user_content_clear_state
                    SET applied_generation = ?, updated_at = ?
                    WHERE singleton_id = ?
                    """,
                    (clear_generation, time.time(), _CHECKPOINT_ID),
                )
                await db.commit()
            except BaseException:
                await db.rollback()
                raise

    async def restore_pending(
        self,
        *,
        clear_generation: int,
        previous_applied_generation: int,
    ) -> None:
        """Undo only this process's just-written checkpoint after resume fails."""

        if previous_applied_generation < 0:
            raise ValueError("previous_applied_generation must not be negative")
        if clear_generation <= previous_applied_generation:
            raise ValueError("clear_generation must exceed the previous checkpoint")
        async with sqlite_connection_async(self._db_path) as db:
            await db.execute("BEGIN IMMEDIATE")
            try:
                cursor = await db.execute(
                    """
                    UPDATE runtime_plugin_user_content_clear_state
                    SET applied_generation = ?, updated_at = ?
                    WHERE singleton_id = ? AND applied_generation = ?
                    """,
                    (
                        previous_applied_generation,
                        time.time(),
                        _CHECKPOINT_ID,
                        clear_generation,
                    ),
                )
                if cursor.rowcount != 1:
                    raise RuntimeError(
                        "Plugin user-content clear checkpoint changed before rollback"
                    )
                await db.commit()
            except BaseException:
                await db.rollback()
                raise


__all__ = ["PluginUserContentClearCheckpointStore"]
