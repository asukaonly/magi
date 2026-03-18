"""Helpers for migrating legacy memory identity rows to canonical self ids."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import aiosqlite

from ..core.logger import get_logger

logger = get_logger(__name__)

LEGACY_SELF_ENTITY_ID = "user:web_user"
CANONICAL_SELF_ENTITY_ID = "user:self"
LEGACY_RUNTIME_USER_ID = "web_user"


async def migrate_legacy_self_identity(*, l1_db_path: str | None, memory_db_path: str | None) -> dict[str, int]:
    """Rewrite legacy self ids in L1 and shared memory storage."""

    results = {
        "l1_fact_events_updated": 0,
        "l1_runtime_observations_updated": 0,
        "knowledge_graph_updated": 0,
        "assertions_updated": 0,
        "snapshots_updated": 0,
        "entity_catalog_updated": 0,
        "entity_aliases_updated": 0,
        "entity_mentions_updated": 0,
    }

    if l1_db_path:
        await _migrate_l1_db(str(Path(l1_db_path).expanduser()), results)
    if memory_db_path:
        await _migrate_memory_db(str(Path(memory_db_path).expanduser()), results)

    logger.info("Legacy self identity migration completed", **results)
    return results


async def _migrate_l1_db(db_path: str, results: dict[str, int]) -> None:
    async with aiosqlite.connect(db_path) as db:
        fact_cursor = await db.execute(
            """
            UPDATE fact_events
            SET memory_owner_id = ?
            WHERE runtime_user_id = ? AND (memory_owner_id IS NULL OR memory_owner_id = ?)
            """,
            (CANONICAL_SELF_ENTITY_ID, LEGACY_RUNTIME_USER_ID, LEGACY_SELF_ENTITY_ID),
        )
        runtime_cursor = await db.execute(
            """
            UPDATE runtime_observations
            SET memory_owner_id = ?
            WHERE runtime_user_id = ? AND (memory_owner_id IS NULL OR memory_owner_id = ?)
            """,
            (CANONICAL_SELF_ENTITY_ID, LEGACY_RUNTIME_USER_ID, LEGACY_SELF_ENTITY_ID),
        )
        await db.commit()

    results["l1_fact_events_updated"] += max(int(fact_cursor.rowcount), 0)
    results["l1_runtime_observations_updated"] += max(int(runtime_cursor.rowcount), 0)


async def _migrate_memory_db(db_path: str, results: dict[str, int]) -> None:
    async with aiosqlite.connect(db_path) as db:
        graph_cursor = await _execute_if_table_exists(
            db,
            "knowledge_graph",
            """
            UPDATE knowledge_graph
            SET
                subject_id = CASE WHEN subject_id = ? THEN ? ELSE subject_id END,
                object_id = CASE WHEN object_id = ? THEN ? ELSE object_id END
            WHERE subject_id = ? OR object_id = ?
            """,
            (
                LEGACY_SELF_ENTITY_ID,
                CANONICAL_SELF_ENTITY_ID,
                LEGACY_SELF_ENTITY_ID,
                CANONICAL_SELF_ENTITY_ID,
                LEGACY_SELF_ENTITY_ID,
                LEGACY_SELF_ENTITY_ID,
            ),
        )
        assertion_cursor = await _execute_if_table_exists(
            db,
            "tom_trait_assertions",
            """
            UPDATE tom_trait_assertions
            SET entity_id = ?
            WHERE entity_id = ?
            """,
            (CANONICAL_SELF_ENTITY_ID, LEGACY_SELF_ENTITY_ID),
        )
        snapshot_cursor = await _execute_if_table_exists(
            db,
            "tom_snapshots",
            """
            UPDATE tom_snapshots
            SET entity_id = ?
            WHERE entity_id = ?
            """,
            (CANONICAL_SELF_ENTITY_ID, LEGACY_SELF_ENTITY_ID),
        )
        entity_catalog_cursor = await _execute_if_table_exists(
            db,
            "entity_catalog",
            """
            UPDATE entity_catalog
            SET entity_id = ?
            WHERE entity_id = ?
            """,
            (CANONICAL_SELF_ENTITY_ID, LEGACY_SELF_ENTITY_ID),
        )
        entity_aliases_cursor = await _execute_if_table_exists(
            db,
            "entity_aliases",
            """
            UPDATE entity_aliases
            SET entity_id = ?
            WHERE entity_id = ?
            """,
            (CANONICAL_SELF_ENTITY_ID, LEGACY_SELF_ENTITY_ID),
        )
        entity_mentions_cursor = await _execute_if_table_exists(
            db,
            "entity_mentions",
            """
            UPDATE entity_mentions
            SET resolved_entity_id = ?
            WHERE resolved_entity_id = ?
            """,
            (CANONICAL_SELF_ENTITY_ID, LEGACY_SELF_ENTITY_ID),
        )
        await db.commit()

    results["knowledge_graph_updated"] += max(int(graph_cursor.rowcount), 0)
    results["assertions_updated"] += max(int(assertion_cursor.rowcount), 0)
    results["snapshots_updated"] += max(int(snapshot_cursor.rowcount), 0)
    results["entity_catalog_updated"] += max(int(entity_catalog_cursor.rowcount), 0)
    results["entity_aliases_updated"] += max(int(entity_aliases_cursor.rowcount), 0)
    results["entity_mentions_updated"] += max(int(entity_mentions_cursor.rowcount), 0)


async def _table_exists(db: aiosqlite.Connection, table_name: str) -> bool:
    async with db.execute(
        "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = ? LIMIT 1",
        (table_name,),
    ) as cursor:
        row = await cursor.fetchone()
    return row is not None


async def _execute_if_table_exists(
    db: aiosqlite.Connection,
    table_name: str,
    sql: str,
    parameters: tuple[Any, ...],
) -> Any:
    if not await _table_exists(db, table_name):
        return _NullCursor()
    return await db.execute(sql, parameters)


class _NullCursor:
    rowcount = 0


__all__ = [
    "CANONICAL_SELF_ENTITY_ID",
    "LEGACY_RUNTIME_USER_ID",
    "LEGACY_SELF_ENTITY_ID",
    "migrate_legacy_self_identity",
]
