"""Persistent generation barrier for destructive memory clears."""

from __future__ import annotations

import time

import aiosqlite

from ..core.sqlite import sqlite_connection_async

MEMORY_CLEAR_STATE_TABLE = "memory_clear_state"
MEMORY_CLEAR_STATE_ID = 1


async def ensure_memory_clear_state(db: aiosqlite.Connection) -> None:
    """Ensure the singleton generation row exists on a caller connection."""
    await db.execute(
        f"""
        CREATE TABLE IF NOT EXISTS {MEMORY_CLEAR_STATE_TABLE} (
            singleton_id INTEGER PRIMARY KEY CHECK(singleton_id = {MEMORY_CLEAR_STATE_ID}),
            generation INTEGER NOT NULL DEFAULT 0,
            updated_at REAL NOT NULL
        )
        """
    )
    await db.execute(
        f"""
        INSERT OR IGNORE INTO {MEMORY_CLEAR_STATE_TABLE}(singleton_id, generation, updated_at)
        VALUES (?, 0, ?)
        """,
        (MEMORY_CLEAR_STATE_ID, time.time()),
    )


async def memory_clear_generation_on_connection(db: aiosqlite.Connection) -> int:
    """Return the current clear generation in the caller transaction."""
    async with db.execute(
        f"SELECT generation FROM {MEMORY_CLEAR_STATE_TABLE} WHERE singleton_id = ?",
        (MEMORY_CLEAR_STATE_ID,),
    ) as cursor:
        row = await cursor.fetchone()
    if row is None:
        raise RuntimeError("Memory clear generation is not initialized")
    return int(row[0])


async def current_memory_clear_generation(db_path: str) -> int:
    """Return the persisted clear generation for one shared-memory database."""
    async with sqlite_connection_async(db_path) as db:
        return await memory_clear_generation_on_connection(db)


async def advance_memory_clear_generation(
    db: aiosqlite.Connection,
    *,
    updated_at: float | None = None,
) -> int:
    """Advance and return the generation inside the caller transaction."""
    await ensure_memory_clear_state(db)
    await db.execute(
        f"""
        UPDATE {MEMORY_CLEAR_STATE_TABLE}
        SET generation = generation + 1, updated_at = ?
        WHERE singleton_id = ?
        """,
        (float(updated_at if updated_at is not None else time.time()), MEMORY_CLEAR_STATE_ID),
    )
    return await memory_clear_generation_on_connection(db)


__all__ = [
    "MEMORY_CLEAR_STATE_ID",
    "MEMORY_CLEAR_STATE_TABLE",
    "advance_memory_clear_generation",
    "current_memory_clear_generation",
    "ensure_memory_clear_state",
    "memory_clear_generation_on_connection",
]
