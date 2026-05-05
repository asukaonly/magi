"""Schema migration helpers for the canonical L1 event store."""

from __future__ import annotations

import aiosqlite

from ....runtime_defaults import DEFAULT_USER_ID

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

    async def _backfill_external_owner_user_ids(self, db: aiosqlite.Connection) -> None:
        await db.execute(
            f"""
            UPDATE {FACT_EVENTS_TABLE}
            SET user_id = ?
            WHERE user_id IS NULL
              AND deleted_at IS NULL
              AND session_id IS NULL
              AND author_type = 'external'
            """,
            (DEFAULT_USER_ID,),
        )

    async def _ensure_event_identity_schema(self, db: aiosqlite.Connection) -> None:
        async with db.execute(f"PRAGMA table_info({FACT_EVENTS_TABLE})") as cursor:
            rows = await cursor.fetchall()
        columns = {str(row[1]) for row in rows}
        if not rows:
            return
        if "id" in columns and "idempotency_key" in columns:
            await db.execute(
                f"CREATE UNIQUE INDEX IF NOT EXISTS idx_fact_events_business_idempotency "
                f"ON {FACT_EVENTS_TABLE}(source, event_type, idempotency_key)"
            )
            await db.execute(
                f"CREATE INDEX IF NOT EXISTS idx_fact_events_idempotency_key ON {FACT_EVENTS_TABLE}(idempotency_key)"
            )
            return

        has_metadata_json = "metadata_json" in columns
        has_embedding_status = "embedding_status" in columns
        has_embedding_profile_id = "embedding_profile_id" in columns

        await db.executescript(
            f"""
            DROP TABLE IF EXISTS {FACT_EVENTS_TABLE}_migrated;
            CREATE TABLE {FACT_EVENTS_TABLE}_migrated (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                event_id TEXT NOT NULL UNIQUE,
                correlation_id TEXT NOT NULL,
                timestamp REAL NOT NULL,
                created_at REAL NOT NULL,
                event_type TEXT NOT NULL,
                source TEXT NOT NULL,
                source_item_id TEXT,
                idempotency_key TEXT,
                memory_domain INTEGER NOT NULL,
                ingest_target INTEGER NOT NULL,
                cognition_eligible INTEGER NOT NULL DEFAULT 0,
                tom_depth INTEGER NOT NULL DEFAULT 1,
                retention_class INTEGER NOT NULL DEFAULT 2,
                session_id TEXT,
                turn_id TEXT,
                user_id TEXT,
                task_id TEXT,
                content TEXT NOT NULL,
                author_type TEXT NOT NULL,
                content_type TEXT NOT NULL,
                importance_score REAL NOT NULL DEFAULT 0.5,
                level INTEGER NOT NULL DEFAULT 1,
                media_path TEXT,
                metadata_json TEXT,
                embedding_status TEXT NOT NULL DEFAULT '{EMBEDDING_STATUS_DISABLED}',
                embedding_profile_id TEXT,
                deleted_at REAL
            );
            """
        )
        metadata_json_expr = "metadata_json" if has_metadata_json else "NULL"
        embedding_status_expr = (
            "embedding_status" if has_embedding_status else f"'{EMBEDDING_STATUS_DISABLED}'"
        )
        embedding_profile_expr = "embedding_profile_id" if has_embedding_profile_id else "NULL"
        await db.execute(
            f"""
            INSERT INTO {FACT_EVENTS_TABLE}_migrated(
                event_id, correlation_id, timestamp, created_at,
                event_type, source, source_item_id, idempotency_key, memory_domain, ingest_target,
                cognition_eligible, tom_depth, retention_class, session_id, turn_id, user_id,
                task_id, content, author_type, content_type, importance_score,
                level, media_path, metadata_json, embedding_status, embedding_profile_id, deleted_at
            )
            SELECT
                event_id, correlation_id, timestamp, created_at,
                event_type, source, source_item_id, NULL, memory_domain, ingest_target,
                cognition_eligible, tom_depth, retention_class, session_id, turn_id, user_id,
                task_id, content, author_type, content_type, importance_score,
                level, media_path, {metadata_json_expr}, {embedding_status_expr}, {embedding_profile_expr}, deleted_at
            FROM {FACT_EVENTS_TABLE}
            """
        )
        await db.execute(f"DROP TABLE {FACT_EVENTS_TABLE}")
        await db.execute(f"ALTER TABLE {FACT_EVENTS_TABLE}_migrated RENAME TO {FACT_EVENTS_TABLE}")
        await db.execute(
            f"CREATE INDEX IF NOT EXISTS idx_fact_events_timestamp ON {FACT_EVENTS_TABLE}(timestamp)"
        )
        await db.execute(
            f"CREATE INDEX IF NOT EXISTS idx_fact_events_type ON {FACT_EVENTS_TABLE}(event_type)"
        )
        await db.execute(
            f"CREATE INDEX IF NOT EXISTS idx_fact_events_source ON {FACT_EVENTS_TABLE}(source)"
        )
        await db.execute(
            f"CREATE INDEX IF NOT EXISTS idx_fact_events_idempotency_key ON {FACT_EVENTS_TABLE}(idempotency_key)"
        )
        await db.execute(
            f"CREATE INDEX IF NOT EXISTS idx_fact_events_domain ON {FACT_EVENTS_TABLE}(memory_domain)"
        )
        await db.execute(
            f"CREATE INDEX IF NOT EXISTS idx_fact_events_session ON {FACT_EVENTS_TABLE}(session_id)"
        )
        await db.execute(
            f"CREATE INDEX IF NOT EXISTS idx_fact_events_turn ON {FACT_EVENTS_TABLE}(turn_id)"
        )
        await db.execute(
            f"CREATE INDEX IF NOT EXISTS idx_fact_events_user ON {FACT_EVENTS_TABLE}(user_id)"
        )
        await db.execute(
            f"CREATE INDEX IF NOT EXISTS idx_fact_events_importance ON {FACT_EVENTS_TABLE}(importance_score DESC)"
        )
        await db.execute(
            f"CREATE INDEX IF NOT EXISTS idx_fact_events_retention ON {FACT_EVENTS_TABLE}(retention_class)"
        )
        await db.execute(
            f"CREATE UNIQUE INDEX IF NOT EXISTS idx_fact_events_business_idempotency "
            f"ON {FACT_EVENTS_TABLE}(source, event_type, idempotency_key)"
        )

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
