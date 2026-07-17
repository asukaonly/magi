"""SQLite schema constants for L4 procedural memory.

Schema is owned by alembic (``magi.db.migrations.memory_shared``); this
module only re-exports table names and helper constants.
"""

from __future__ import annotations

import aiosqlite

from ..table_names import EXECUTION_TRACES_TABLE, SKILL_CHUNKS_TABLE  # noqa: F401

EMBEDDING_TEXT_BUILDER_VERSION = "l4_skill_v1"
EMBEDDING_STATUS_READY = "ready"
EMBEDDING_STATUS_DISABLED = "disabled"

MAX_TRACES_PER_SKILL = 50
DEFAULT_STRATEGY_EXTRACTION_THRESHOLD = 5
_ADAPTIVE_MAX_THRESHOLD = 100


async def ensure_procedural_memory_schema(db: aiosqlite.Connection) -> None:
    """No-op kept for compatibility — schema is alembic-managed."""
    return None
