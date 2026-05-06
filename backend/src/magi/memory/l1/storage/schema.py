"""Schema migration helpers for the canonical L1 event store."""

from __future__ import annotations

import aiosqlite

FACT_EVENTS_TABLE = "fact_events"
EMBEDDING_STATUS_DISABLED = "disabled"


class L1EventSchemaMixin:
    """Keep the L1 event store schema current across older local databases."""

    async def _ensure_embedding_status_columns(self, db: aiosqlite.Connection) -> None:
        async with db.execute(f"PRAGMA table_info({FACT_EVENTS_TABLE})") as cursor:
            columns = {str(row[1]) for row in await cursor.fetchall()}
        if "embedding_status" not in columns:
            await db.execute(
                f"ALTER TABLE {FACT_EVENTS_TABLE} ADD COLUMN embedding_status TEXT NOT NULL DEFAULT '{EMBEDDING_STATUS_DISABLED}'"
            )
        if "embedding_profile_id" not in columns:
            await db.execute(
                f"ALTER TABLE {FACT_EVENTS_TABLE} ADD COLUMN embedding_profile_id TEXT"
            )
        if "embedding_chunk_count" not in columns:
            await db.execute(
                f"ALTER TABLE {FACT_EVENTS_TABLE} ADD COLUMN embedding_chunk_count INTEGER NOT NULL DEFAULT 0"
            )
        if "last_embedded_at" not in columns:
            await db.execute(f"ALTER TABLE {FACT_EVENTS_TABLE} ADD COLUMN last_embedded_at REAL")

    async def _ensure_metadata_json_column(self, db: aiosqlite.Connection) -> None:
        async with db.execute(f"PRAGMA table_info({FACT_EVENTS_TABLE})") as cursor:
            columns = {str(row[1]) for row in await cursor.fetchall()}
        if "metadata_json" not in columns:
            await db.execute(f"ALTER TABLE {FACT_EVENTS_TABLE} ADD COLUMN metadata_json TEXT")

    async def _ensure_envelope_columns(self, db: aiosqlite.Connection) -> None:
        async with db.execute(f"PRAGMA table_info({FACT_EVENTS_TABLE})") as cursor:
            columns = {str(row[1]) for row in await cursor.fetchall()}
        for column_name in ("causation_id", "trace_id", "span_id", "parent_span_id"):
            if column_name not in columns:
                await db.execute(
                    f"ALTER TABLE {FACT_EVENTS_TABLE} ADD COLUMN {column_name} TEXT"
                )
        await db.execute(
            f"CREATE INDEX IF NOT EXISTS idx_fact_events_trace ON {FACT_EVENTS_TABLE}(trace_id)"
        )
        await db.execute(
            f"CREATE INDEX IF NOT EXISTS idx_fact_events_causation ON {FACT_EVENTS_TABLE}(causation_id)"
        )
