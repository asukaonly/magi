"""SQLite schema helpers for personality growth memory.

Schema is owned by alembic (``magi.db.migrations.growth_memory``).
"""

from __future__ import annotations

import aiosqlite


async def ensure_growth_memory_schema(db: aiosqlite.Connection) -> None:
    """No-op kept for compatibility — schema is alembic-managed."""
    return None


__all__ = ["ensure_growth_memory_schema"]