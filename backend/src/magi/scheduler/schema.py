"""SQLite schema management for scheduler persistence.

Schema is owned by alembic (``magi.db.migrations.scheduler``).
"""

from __future__ import annotations

import aiosqlite


async def ensure_scheduler_schema(db: aiosqlite.Connection) -> None:
    """No-op kept for compatibility — schema is alembic-managed."""
    return None


__all__ = ["ensure_scheduler_schema"]