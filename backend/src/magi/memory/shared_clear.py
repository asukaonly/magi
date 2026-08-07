"""Clear user-owned data in the shared memory database."""

from __future__ import annotations

from dataclasses import dataclass

import aiosqlite

from ..core.sqlite import sqlite_connection_async
from .clear_generation import advance_memory_clear_generation
from .context_scope.cache_epoch import invalidate_context_caches
from .context_scope.catalog import clear_user_contexts
from .embedding.sqlite_vec_index import SqliteVecIndex
from .l2.store import L2_USER_CONTENT_TABLES


_L2_ENTITY_USER_TABLES = (
    "entity_name_evidence",
    "entity_mentions",
    "entity_aliases",
    "entity_catalog",
)

_L3_USER_TABLES = (
    "summary_event_links",
    "summary_task_links",
    "l3_summary_chunks",
    "l3_summaries_fts",
    "daily_mood_aggregate",
    "summaries",
)

_L4_USER_TABLES = (
    "l4_skill_event_links",
    "l4_skill_chunks",
    "l4_execution_traces",
    "l4_skills_fts",
    "procedural_skills",
)

_SHARED_AUXILIARY_USER_TABLES = (
    # Full-memory clear owns dormant L0 rows as well. The optional L0 store
    # cannot be relied on to exist when a user clears memory.
    "l0_attention_items",
    "l0_sessions",
    # Retired L0 tables are included for upgraded or interrupted installations.
    "l0_goal_stack",
    "l0_active_entities",
    "l0_temporary_tactics",
    "l0_forgotten_tactic_source_refs",
    "l0_forgotten_attention_source_refs",
    "l0_forgotten_attention_entities",
    "memory_source_turn_cutoffs",
    "memory_time_range_forget_barriers",
    "memory_forget_operation_refs",
    "memory_forget_operation_events",
    "memory_forget_operations",
    "embedding_rebuild_job_layers",
    "embedding_rebuild_jobs",
    "history_import_job_records",
    "history_import_source_records",
    "history_import_jobs",
    "manual_entries",
    "timeline_cover_preferences",
    "place_labels",
    "place_geocode_cache",
    "location_samples",
)


@dataclass(frozen=True, slots=True)
class SharedMemoryClearCounts:
    """Counts removed from layers that may not be active in this runtime."""

    l0: int = 0
    l2: int = 0
    l3: int = 0
    l4: int = 0


@dataclass(frozen=True, slots=True)
class _VectorIndexSpec:
    registry_table: str
    entity_column: str
    vec_table_prefix: str


_VECTOR_INDEX_SPECS = (
    _VectorIndexSpec("l2_entity_vectors", "entity_id", "l2_entity_vec"),
    _VectorIndexSpec("l2_edge_vectors", "entity_id", "l2_edge_vec"),
    _VectorIndexSpec("l3_summary_chunk_vectors", "chunk_id", "l3_summary_chunk_vec"),
    _VectorIndexSpec("l4_skill_chunk_vectors", "chunk_id", "l4_skill_chunk_vec"),
)


async def _count_existing_rows(
    db: aiosqlite.Connection,
    existing_tables: set[str],
    tables: tuple[str, ...],
) -> int:
    total = 0
    for table in tables:
        if table not in existing_tables:
            continue
        async with db.execute(f"SELECT COUNT(*) FROM {table}") as cursor:
            row = await cursor.fetchone()
        total += int(row[0]) if row else 0
    return total


def _vector_indexes_to_clear(
    *,
    existing_tables: set[str],
) -> tuple[_VectorIndexSpec, ...]:
    return tuple(
        spec
        for spec in _VECTOR_INDEX_SPECS
        if (
            spec.registry_table in existing_tables
            or any(name.startswith(spec.vec_table_prefix) for name in existing_tables)
        )
    )


async def _clear_vector_indexes(db_path: str, specs: tuple[_VectorIndexSpec, ...]) -> None:
    for spec in specs:
        index = SqliteVecIndex(
            db_path=db_path,
            registry_table=spec.registry_table,
            entity_column=spec.entity_column,
            vec_table_prefix=spec.vec_table_prefix,
        )
        try:
            await index.clear()
        finally:
            await index.close()


async def clear_shared_auxiliary_memory(
    db_path: str,
    *,
    advance_clear_generation: bool = False,
) -> SharedMemoryClearCounts:
    """Delete all user content, including stale shared vector indexes."""

    vector_specs: tuple[_VectorIndexSpec, ...] = ()
    counts = SharedMemoryClearCounts()
    async with sqlite_connection_async(db_path) as db:
        await db.execute("BEGIN IMMEDIATE")
        try:
            if advance_clear_generation:
                await advance_memory_clear_generation(db)
            async with db.execute("SELECT name FROM sqlite_master WHERE type = 'table'") as cursor:
                existing_tables = {str(row[0]) for row in await cursor.fetchall()}
            counts = SharedMemoryClearCounts(
                l0=await _count_existing_rows(
                    db,
                    existing_tables,
                    ("l0_attention_items", "l0_sessions"),
                ),
                l2=await _count_existing_rows(
                    db,
                    existing_tables,
                    ("tom_trait_assertions", "entity_catalog", "entity_mentions"),
                ),
                l3=await _count_existing_rows(db, existing_tables, ("summaries",)),
                l4=await _count_existing_rows(db, existing_tables, ("procedural_skills",)),
            )
            if {
                "memory_context_catalog",
                "memory_context_aliases",
                "memory_context_bindings",
            }.issubset(existing_tables):
                await clear_user_contexts(db)
            for table in (
                *L2_USER_CONTENT_TABLES,
                *_L2_ENTITY_USER_TABLES,
                *_L3_USER_TABLES,
                *_L4_USER_TABLES,
                *_SHARED_AUXILIARY_USER_TABLES,
            ):
                if table in existing_tables:
                    await db.execute(f"DELETE FROM {table}")
            vector_specs = _vector_indexes_to_clear(
                existing_tables=existing_tables,
            )
            await db.commit()
            invalidate_context_caches(db_path)
        except Exception:
            await db.rollback()
            raise
    await _clear_vector_indexes(db_path, vector_specs)
    return counts


__all__ = ["SharedMemoryClearCounts", "clear_shared_auxiliary_memory"]
