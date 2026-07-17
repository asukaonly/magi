"""Clear user-owned data in the shared database that sits outside L0-L4 stores."""

from __future__ import annotations

from ..core.sqlite import sqlite_connection_async
from .context_scope.cache_epoch import invalidate_context_caches
from .context_scope.catalog import clear_user_contexts

_SHARED_AUXILIARY_USER_TABLES = (
    "memory_time_range_forget_barriers",
    "memory_forget_operation_refs",
    "memory_forget_operation_events",
    "memory_forget_operations",
    "embedding_rebuild_job_layers",
    "embedding_rebuild_jobs",
    "manual_entries",
    "timeline_cover_preferences",
    "place_labels",
    "place_geocode_cache",
    "location_samples",
)


async def clear_shared_auxiliary_memory(db_path: str) -> None:
    """Delete source-facing and administrative memory rows from the shared DB."""
    async with sqlite_connection_async(db_path) as db:
        await db.execute("BEGIN IMMEDIATE")
        try:
            async with db.execute("SELECT name FROM sqlite_master WHERE type = 'table'") as cursor:
                existing_tables = {str(row[0]) for row in await cursor.fetchall()}
            if {
                "memory_context_catalog",
                "memory_context_aliases",
                "memory_context_bindings",
            }.issubset(existing_tables):
                await clear_user_contexts(db)
            for table in _SHARED_AUXILIARY_USER_TABLES:
                if table in existing_tables:
                    await db.execute(f"DELETE FROM {table}")
            await db.commit()
            invalidate_context_caches(db_path)
        except Exception:
            await db.rollback()
            raise


__all__ = ["clear_shared_auxiliary_memory"]
