"""SQLite schema constants for L3 summary storage.

Schema is owned by alembic (``magi.db.migrations.memory_shared``); this
module only re-exports table names and helper constants.
"""
from __future__ import annotations

import aiosqlite

SUMMARY_CHUNKS_TABLE = "l3_summary_chunks"
EMBEDDING_STATUS_READY = "ready"
EMBEDDING_STATUS_DISABLED = "disabled"


async def ensure_summary_store_schema(db: aiosqlite.Connection) -> None:
    """No-op kept for compatibility — schema is alembic-managed."""
    return None
