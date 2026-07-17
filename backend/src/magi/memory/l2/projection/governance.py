"""Durable source governance shared by L2 projection queue operations."""

from __future__ import annotations

from ...source_event_governance import source_event_time_range_block_predicate


def active_projection_event_predicate(event_id_sql: str) -> str:
    """Return SQL for an event that may still produce L2 derivatives."""
    return f"""
        NOT EXISTS (
            SELECT 1
            FROM memory_source_event_tombstones AS projection_tombstones
            WHERE projection_tombstones.event_id = {event_id_sql}
        )
        AND NOT EXISTS (
            SELECT 1
            FROM memory_projection_blocks AS projection_time_blocks
            WHERE projection_time_blocks.event_id = {event_id_sql}
              AND {source_event_time_range_block_predicate("projection_time_blocks")}
        )
    """


__all__ = ["active_projection_event_predicate"]
