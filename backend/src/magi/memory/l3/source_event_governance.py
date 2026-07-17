"""Fail-closed source governance shared by L3 read paths."""

from __future__ import annotations

from ..source_event_governance import source_event_derivation_block_predicate


def active_summary_predicate(alias: str = "summaries") -> str:
    """Return the complete SQL predicate for one prompt-visible L3 summary."""
    return f"""
        {alias}.derivation_state = 'current'
        AND json_valid({alias}.source_event_ids)
        AND json_type({alias}.source_event_ids) = 'array'
        AND NOT EXISTS (
            SELECT 1
            FROM json_each({alias}.source_event_ids) AS invalid_source
            WHERE invalid_source.type != 'text'
               OR TRIM(CAST(invalid_source.value AS TEXT)) = ''
        )
        AND NOT EXISTS (
            SELECT 1
            FROM json_each({alias}.source_event_ids) AS source
            JOIN memory_source_event_tombstones AS tombstones
              ON tombstones.event_id = CAST(source.value AS TEXT)
        )
        AND NOT EXISTS (
            SELECT 1
            FROM json_each({alias}.source_event_ids) AS source
            JOIN memory_projection_blocks AS projection_blocks
              ON projection_blocks.event_id = CAST(source.value AS TEXT)
             AND {source_event_derivation_block_predicate("projection_blocks")}
        )
    """


__all__ = ["active_summary_predicate"]
