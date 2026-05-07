"""SQLite schema helpers for L0 working-memory checkpoints.

Schema is owned by alembic (``magi.db.migrations.memory_shared``).
"""
from __future__ import annotations

import aiosqlite

L0_CLEAR_SQL = """
DELETE FROM l0_sessions;
DELETE FROM l0_goal_stack;
DELETE FROM l0_active_entities;
DELETE FROM l0_temporary_tactics;
DELETE FROM l0_execution_runs;
DELETE FROM l0_execution_pending_turns;
DELETE FROM l0_execution_results;
"""


async def ensure_l0_checkpoint_schema(db: aiosqlite.Connection) -> None:
    """No-op kept for compatibility — schema is alembic-managed."""
    return None


async def clear_l0_checkpoint_tables(db: aiosqlite.Connection) -> None:
    await db.executescript(L0_CLEAR_SQL)
