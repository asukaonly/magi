"""Source-reference cleanup for L0 prompt-time projections."""

from __future__ import annotations

import asyncio
import time
from collections.abc import Iterable
from typing import Any, Protocol, cast

import aiosqlite

from ....core.sqlite import sqlite_connection_async
from ...source_event_governance import source_event_time_range_block_predicate
from .serialization import decode_source_event_ids, row_to_tactic

_GOVERNANCE_TABLES = frozenset(
    {
        "memory_projection_blocks",
        "memory_source_event_tombstones",
    }
)
_SOURCE_REFERENCE_BATCH_SIZE = 500


def normalize_tactic_source_references(source_references: Iterable[str]) -> tuple[str, ...]:
    """Return stable, non-empty references used by temporary tactics."""
    return tuple(
        dict.fromkeys(
            str(reference).strip() for reference in source_references if str(reference).strip()
        )
    )


def tactic_source_references(tactic: dict[str, Any]) -> set[str]:
    """Return only the explicit provenance fields owned by the tactic contract."""
    raw_source_ids = tactic.get("source_event_ids")
    references = (
        set(normalize_tactic_source_references(raw_source_ids))
        if isinstance(raw_source_ids, (list, tuple, set))
        else set()
    )
    payload = tactic.get("tactic_payload")
    if not isinstance(payload, dict):
        return references

    turn_id = str(payload.get("turn_id") or "").strip()
    if turn_id:
        references.add(turn_id)

    payload_source_ids = payload.get("source_event_ids")
    if isinstance(payload_source_ids, list):
        references.update(normalize_tactic_source_references(payload_source_ids))
    return references


def active_entity_source_references(entity: dict[str, Any]) -> tuple[str, ...] | None:
    """Return validated active-entity provenance, or None when it is unsafe."""
    return decode_source_event_ids(entity.get("source_event_ids"))


async def filter_active_entities_by_governance(
    db: aiosqlite.Connection,
    entities: Iterable[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Exclude active entities governed by source or time/entity projection barriers."""
    source_free: list[dict[str, Any]] = []
    sourced: list[tuple[dict[str, Any], tuple[str, ...]]] = []
    for entity in entities:
        references = active_entity_source_references(entity)
        if references is None:
            continue
        if not references:
            source_free.append(entity)
            continue
        sourced.append((entity, references))
    if not sourced:
        return source_free

    async with db.execute("SELECT name FROM sqlite_master WHERE type = 'table'") as cursor:
        available_tables = {str(row[0]) for row in await cursor.fetchall()}
    if not _GOVERNANCE_TABLES.issubset(available_tables):
        return source_free

    all_references = tuple(
        dict.fromkeys(reference for _, references in sourced for reference in references)
    )
    tombstoned: set[str] = set()
    entity_projection_blocks: set[tuple[str, str]] = set()
    time_range_projection_blocks: set[str] = set()
    for offset in range(0, len(all_references), _SOURCE_REFERENCE_BATCH_SIZE):
        chunk = all_references[offset : offset + _SOURCE_REFERENCE_BATCH_SIZE]
        placeholders = ", ".join("?" for _ in chunk)
        async with db.execute(
            f"""
            SELECT event_id
            FROM memory_source_event_tombstones
            WHERE event_id IN ({placeholders})
            """,
            tuple(chunk),
        ) as cursor:
            tombstoned.update(str(row[0]) for row in await cursor.fetchall())
        async with db.execute(
            f"""
            SELECT block_kind, target_id, event_id
            FROM memory_projection_blocks
            WHERE event_id IN ({placeholders})
              AND (
                  block_kind IN (
                      'entity_projection', 'entity_projection_candidate'
                  )
                  OR (
                      block_kind = 'episode_formation'
                      AND target_id LIKE 'time:%'
                  )
              )
            """,
            tuple(chunk),
        ) as cursor:
            for block_kind, target_id, event_id in await cursor.fetchall():
                if str(block_kind) in {
                    "entity_projection",
                    "entity_projection_candidate",
                }:
                    entity_projection_blocks.add((str(target_id), str(event_id)))
                else:
                    time_range_projection_blocks.add(str(event_id))

    retained = list(source_free)
    for entity, references in sourced:
        if any(
            reference in tombstoned or reference in time_range_projection_blocks
            for reference in references
        ):
            continue
        entity_id = str(entity.get("entity_id") or "").strip()
        if not entity_id or any(
            (entity_id, reference) in entity_projection_blocks for reference in references
        ):
            continue
        retained.append(entity)
    return retained


async def forgotten_tactic_source_references(
    db: aiosqlite.Connection,
    source_references: Iterable[str],
) -> set[str]:
    """Return source references protected by either local or global barriers."""
    normalized = normalize_tactic_source_references(source_references)
    if not normalized:
        return set()
    async with db.execute("""
        SELECT name
        FROM sqlite_master
        WHERE type = 'table'
          AND name IN (
              'l0_forgotten_tactic_source_refs',
              'memory_source_event_tombstones',
              'memory_projection_blocks'
          )
        """) as cursor:
        available_tables = {str(row[0]) for row in await cursor.fetchall()}

    found: set[str] = set()
    barrier_columns = {
        "l0_forgotten_tactic_source_refs": "source_ref",
        "memory_source_event_tombstones": "event_id",
    }
    for table_name, column_name in barrier_columns.items():
        if table_name not in available_tables:
            continue
        for offset in range(0, len(normalized), 500):
            chunk = normalized[offset : offset + 500]
            placeholders = ", ".join("?" for _ in chunk)
            async with db.execute(
                f"""
                SELECT {column_name}
                FROM {table_name}
                WHERE {column_name} IN ({placeholders})
                """,
                tuple(chunk),
            ) as cursor:
                found.update(str(row[0]) for row in await cursor.fetchall())
    if "memory_projection_blocks" in available_tables:
        for offset in range(0, len(normalized), 500):
            chunk = normalized[offset : offset + 500]
            placeholders = ", ".join("?" for _ in chunk)
            async with db.execute(
                f"""
                SELECT DISTINCT event_id
                FROM memory_projection_blocks AS projection_blocks
                WHERE {source_event_time_range_block_predicate("projection_blocks")}
                  AND event_id IN ({placeholders})
                """,
                tuple(chunk),
            ) as cursor:
                found.update(str(row[0]) for row in await cursor.fetchall())
    return found


class _L0SourceForgettingHostProtocol(Protocol):
    checkpoint_db_path: str
    _checkpoint_lock: asyncio.Lock
    _active_entities: dict[str, dict[tuple[str, str], dict[str, Any]]]
    _temporary_tactics: dict[str, dict[str, dict[str, Any]]]

    async def initialize(self) -> None: ...


class L0SourceForgettingMixin:
    """Remove short-lived prompt state derived from forgotten sources."""

    async def forget_active_entities(self, source_references: Iterable[str]) -> int:
        """Remove source-derived entity cards from live state and checkpoints."""
        references = set(normalize_tactic_source_references(source_references))
        if not references:
            return 0

        host = cast(_L0SourceForgettingHostProtocol, self)
        await host.initialize()
        async with host._checkpoint_lock:
            live_matches = {
                (session_id, entity_id, entity_type)
                for session_id, entities in host._active_entities.items()
                for (entity_id, entity_type), entity in entities.items()
                if (
                    (sources := active_entity_source_references(entity)) is None
                    or bool(set(sources) & references)
                )
            }
            async with sqlite_connection_async(host.checkpoint_db_path) as db:
                db.row_factory = aiosqlite.Row
                await db.execute("BEGIN IMMEDIATE")
                try:
                    checkpoint_matches = await self._checkpoint_active_entity_keys_for_references(
                        db,
                        references,
                    )
                    matching_keys = checkpoint_matches | live_matches
                    if matching_keys:
                        await db.executemany(
                            """
                            DELETE FROM l0_active_entities
                            WHERE session_id = ? AND entity_id = ? AND entity_type = ?
                            """,
                            sorted(matching_keys),
                        )
                    await db.commit()
                except BaseException:
                    await db.rollback()
                    raise

            for session_id, entity_id, entity_type in matching_keys:
                host._active_entities.get(session_id, {}).pop((entity_id, entity_type), None)
            return len(matching_keys)

    async def forget_temporary_tactics(self, source_references: Iterable[str]) -> int:
        """Delete matching tactics from both live state and the durable checkpoint."""
        references = set(normalize_tactic_source_references(source_references))
        if not references:
            return 0

        host = cast(_L0SourceForgettingHostProtocol, self)
        await host.initialize()
        async with host._checkpoint_lock:
            live_matches = {
                str(tactic_id)
                for tactics in host._temporary_tactics.values()
                for tactic_id, tactic in tactics.items()
                if tactic_source_references(tactic) & references
            }
            async with sqlite_connection_async(host.checkpoint_db_path) as db:
                db.row_factory = aiosqlite.Row
                await db.execute("BEGIN IMMEDIATE")
                try:
                    await db.executemany(
                        """
                        INSERT OR IGNORE INTO l0_forgotten_tactic_source_refs(
                            source_ref, created_at
                        ) VALUES (?, ?)
                        """,
                        [(reference, time.time()) for reference in sorted(references)],
                    )
                    checkpoint_matches = await self._checkpoint_tactic_ids_for_references(
                        db,
                        references,
                    )
                    matching_ids = checkpoint_matches | live_matches
                    if matching_ids:
                        await db.executemany(
                            "DELETE FROM l0_temporary_tactics WHERE tactic_id = ?",
                            [(tactic_id,) for tactic_id in sorted(matching_ids)],
                        )
                    await db.commit()
                except BaseException:
                    await db.rollback()
                    raise

            for tactics in host._temporary_tactics.values():
                for tactic_id in matching_ids:
                    tactics.pop(tactic_id, None)
            return len(matching_ids)

    async def _checkpoint_tactic_ids_for_references(
        self,
        db: aiosqlite.Connection,
        references: set[str],
    ) -> set[str]:
        matches: set[str] = set()
        async with db.execute("SELECT * FROM l0_temporary_tactics") as cursor:
            async for row in cursor:
                tactic = row_to_tactic(row)
                if tactic_source_references(tactic) & references:
                    matches.add(str(tactic["tactic_id"]))
        return matches

    async def _checkpoint_active_entity_keys_for_references(
        self,
        db: aiosqlite.Connection,
        references: set[str],
    ) -> set[tuple[str, str, str]]:
        matches: set[tuple[str, str, str]] = set()
        async with db.execute("""
            SELECT session_id, entity_id, entity_type, source_event_ids
            FROM l0_active_entities
            """) as cursor:
            async for row in cursor:
                sources = decode_source_event_ids(row["source_event_ids"])
                if sources is not None and not set(sources).intersection(references):
                    continue
                matches.add((str(row[0]), str(row[1]), str(row[2])))
        return matches


__all__ = [
    "L0SourceForgettingMixin",
    "active_entity_source_references",
    "filter_active_entities_by_governance",
    "forgotten_tactic_source_references",
    "normalize_tactic_source_references",
    "tactic_source_references",
]
