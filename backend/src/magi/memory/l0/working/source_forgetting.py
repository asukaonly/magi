"""Source-governed deletion for L0 attention projections."""

from __future__ import annotations

import asyncio
import math
import time
from typing import Any, Iterable, Protocol, cast

import aiosqlite

from ....core.sqlite import sqlite_connection_async
from ...source_event_governance import (
    normalize_source_event_ids,
    source_event_derivation_block_predicate,
    source_turn_cutoffs,
    upsert_source_turn_cutoffs,
)
from .serialization import row_to_attention_item


def normalize_attention_source_references(
    source_references: Iterable[str],
) -> tuple[str, ...]:
    """Normalize event and turn references used by L0 provenance."""

    return normalize_source_event_ids(source_references)


def attention_source_references(item: Any) -> set[str]:
    """Return all durable provenance references carried by one item or action."""

    if isinstance(item, dict):
        values = [
            *item.get("source_turn_ids", []),
            *item.get("source_event_ids", []),
        ]
    else:
        values = [
            *getattr(item, "source_turn_ids", ()),
            *getattr(item, "source_event_ids", ()),
        ]
    return set(normalize_attention_source_references(values))


async def forgotten_attention_source_references(
    db: aiosqlite.Connection,
    source_references: Iterable[str],
) -> set[str]:
    """Return source references blocked permanently by global forgetting."""

    normalized = normalize_attention_source_references(source_references)
    if not normalized:
        return set()
    async with db.execute(
        """
        SELECT name
        FROM sqlite_master
        WHERE type = 'table'
          AND name IN (
              'l0_forgotten_attention_source_refs',
              'memory_source_event_tombstones',
              'memory_projection_blocks'
          )
        """
    ) as cursor:
        available_tables = {str(row[0]) for row in await cursor.fetchall()}

    found: set[str] = set()
    barrier_columns = {
        "l0_forgotten_attention_source_refs": "source_ref",
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
                WHERE {source_event_derivation_block_predicate("projection_blocks")}
                  AND event_id IN ({placeholders})
                """,
                tuple(chunk),
            ) as cursor:
                found.update(str(row[0]) for row in await cursor.fetchall())
    return found


async def forgotten_attention_turn_cutoffs(
    db: aiosqlite.Connection,
    turn_ids: Iterable[str],
) -> dict[str, float]:
    """Return the latest local or shared deletion cutoff for runtime turns."""

    normalized = normalize_attention_source_references(turn_ids)
    if not normalized:
        return {}
    return await source_turn_cutoffs(db, normalized)


async def forgotten_attention_entity_cutoffs(
    db: aiosqlite.Connection,
    entity_ids: Iterable[str],
) -> dict[str, float]:
    """Return the latest forget cutoff for each linked canonical entity."""

    normalized = normalize_source_event_ids(entity_ids)
    if not normalized:
        return {}
    async with db.execute(
        """
        SELECT 1
        FROM sqlite_master
        WHERE type = 'table'
          AND name = 'l0_forgotten_attention_entities'
        LIMIT 1
        """
    ) as cursor:
        if await cursor.fetchone() is None:
            return {}

    found: dict[str, float] = {}
    for offset in range(0, len(normalized), 500):
        chunk = normalized[offset : offset + 500]
        placeholders = ", ".join("?" for _ in chunk)
        async with db.execute(
            f"""
            SELECT entity_id, cutoff_at
            FROM l0_forgotten_attention_entities
            WHERE entity_id IN ({placeholders})
            """,
            tuple(chunk),
        ) as cursor:
            found.update(
                (str(entity_id), float(cutoff_at))
                for entity_id, cutoff_at in await cursor.fetchall()
            )
    return found


async def latest_attention_entity_forget_cutoff(
    db: aiosqlite.Connection,
) -> float:
    """Return the newest cutoff that can invalidate an already accepted turn."""

    async with db.execute(
        """
        SELECT 1
        FROM sqlite_master
        WHERE type = 'table'
          AND name = 'l0_forgotten_attention_entities'
        LIMIT 1
        """
    ) as cursor:
        if await cursor.fetchone() is None:
            return 0.0
    async with db.execute(
        "SELECT MAX(cutoff_at) FROM l0_forgotten_attention_entities"
    ) as cursor:
        row = await cursor.fetchone()
    return float(row[0] or 0.0) if row is not None else 0.0


async def filter_attention_items_by_governance(
    db: aiosqlite.Connection,
    items: Iterable[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Fail closed for source-derived attention whose provenance is forgotten."""

    candidates = list(items)
    event_references = {
        reference
        for item in candidates
        for reference in normalize_attention_source_references(
            item.get("source_event_ids", ())
        )
    }
    turn_ids = {
        reference
        for item in candidates
        for reference in normalize_attention_source_references(
            item.get("source_turn_ids", ())
        )
    }
    forgotten = await forgotten_attention_source_references(
        db,
        event_references,
    )
    turn_cutoffs = await forgotten_attention_turn_cutoffs(db, turn_ids)
    entity_cutoffs = await forgotten_attention_entity_cutoffs(
        db,
        (
            str(item.get("entity_id") or "")
            for item in candidates
            if str(item.get("entity_id") or "")
        ),
    )
    return [
        item
        for item in candidates
        if not (
            set(
                normalize_attention_source_references(
                    item.get("source_event_ids", ())
                )
            )
            & forgotten
        )
        and not attention_item_predates_turn_forget(
            item,
            turn_cutoffs=turn_cutoffs,
        )
        and not _attention_item_predates_entity_forget(
            item,
            entity_cutoffs=entity_cutoffs,
        )
    ]


def attention_item_predates_turn_forget(
    item: dict[str, Any],
    *,
    turn_cutoffs: dict[str, float],
) -> bool:
    """Return whether an item's original turn evidence predates deletion."""

    source_turn_ids = normalize_attention_source_references(
        item.get("source_turn_ids", ())
    )
    relevant_cutoffs = {
        turn_id: turn_cutoffs[turn_id]
        for turn_id in source_turn_ids
        if turn_id in turn_cutoffs
    }
    if not relevant_cutoffs:
        return False
    metadata = item.get("metadata")
    raw_timestamps = (
        metadata.get("source_turn_accepted_at")
        if isinstance(metadata, dict)
        else None
    )
    if not isinstance(raw_timestamps, dict):
        return True
    for turn_id, cutoff in relevant_cutoffs.items():
        try:
            accepted_at = float(raw_timestamps.get(turn_id))
        except (TypeError, ValueError):
            return True
        if not math.isfinite(accepted_at) or accepted_at <= cutoff:
            return True
    return False


def _attention_item_predates_entity_forget(
    item: dict[str, Any],
    *,
    entity_cutoffs: dict[str, float],
) -> bool:
    entity_id = str(item.get("entity_id") or "").strip()
    cutoff = entity_cutoffs.get(entity_id)
    if cutoff is None:
        return False
    return attention_item_predates_entity_forget(item, cutoff_at=cutoff)


def attention_item_predates_entity_forget(
    item: dict[str, Any],
    *,
    cutoff_at: float,
) -> bool:
    """Return whether an item has no source turn accepted after a cutoff."""

    metadata = item.get("metadata")
    raw_timestamps = (
        metadata.get("source_turn_accepted_at")
        if isinstance(metadata, dict)
        else None
    )
    if not isinstance(raw_timestamps, dict):
        return True

    source_turn_ids = normalize_attention_source_references(
        item.get("source_turn_ids", ())
    )
    if not source_turn_ids:
        return True
    for turn_id in source_turn_ids:
        try:
            accepted_at = float(raw_timestamps.get(turn_id))
        except (TypeError, ValueError):
            return True
        if not math.isfinite(accepted_at) or accepted_at <= cutoff_at:
            return True
    return False


class _L0SourceForgettingHostProtocol(Protocol):
    checkpoint_db_path: str
    _checkpoint_lock: asyncio.Lock
    _attention_items: dict[str, dict[str, dict[str, Any]]]

    async def initialize(self) -> None: ...


class L0SourceForgettingMixin:
    """Remove short-lived attention derived from forgotten sources."""

    async def forget_attention_items(
        self,
        source_references: Iterable[str],
    ) -> int:
        """Delete matching attention from live state and durable checkpoints."""

        references = set(
            normalize_attention_source_references(source_references)
        )
        if not references:
            return 0
        host = cast(_L0SourceForgettingHostProtocol, self)
        await host.initialize()
        async with host._checkpoint_lock:
            live_matches = {
                item_id
                for items in host._attention_items.values()
                for item_id, item in items.items()
                if attention_source_references(item) & references
            }
            async with sqlite_connection_async(host.checkpoint_db_path) as db:
                db.row_factory = aiosqlite.Row
                await db.execute("BEGIN IMMEDIATE")
                try:
                    forgotten_at = time.time()
                    await db.executemany(
                        """
                        INSERT OR IGNORE INTO l0_forgotten_attention_source_refs(
                            source_ref, created_at
                        ) VALUES (?, ?)
                        """,
                        [
                            (reference, forgotten_at)
                            for reference in sorted(references)
                        ],
                    )
                    checkpoint_matches = (
                        await self._checkpoint_attention_ids_for_references(
                            db,
                            references,
                        )
                    )
                    matching_ids = checkpoint_matches | live_matches
                    if matching_ids:
                        await db.executemany(
                            "DELETE FROM l0_attention_items WHERE item_id = ?",
                            [(item_id,) for item_id in sorted(matching_ids)],
                        )
                    await db.commit()
                except BaseException:
                    await db.rollback()
                    raise
            for items in host._attention_items.values():
                for item_id in matching_ids:
                    items.pop(item_id, None)
            return len(matching_ids)

    async def forget_chat_turn(
        self,
        *,
        session_id: str,
        turn_id: str,
    ) -> int:
        """Forget attention sourced from one deleted or superseded chat turn."""

        del session_id
        normalized_turn_ids = set(
            normalize_attention_source_references((turn_id,))
        )
        if not normalized_turn_ids:
            return 0
        host = cast(_L0SourceForgettingHostProtocol, self)
        await host.initialize()
        forgotten_at = time.time()
        async with host._checkpoint_lock:
            live_matches = {
                item_id
                for items in host._attention_items.values()
                for item_id, item in items.items()
                if set(item.get("source_turn_ids", ())) & normalized_turn_ids
            }
            async with sqlite_connection_async(host.checkpoint_db_path) as db:
                db.row_factory = aiosqlite.Row
                await db.execute("BEGIN IMMEDIATE")
                try:
                    await upsert_source_turn_cutoffs(
                        db,
                        turn_ids=normalized_turn_ids,
                        cutoff_at=forgotten_at,
                        reason="runtime_chat_turn_deleted",
                    )
                    checkpoint_matches = (
                        await self._checkpoint_attention_ids_for_references(
                            db,
                            normalized_turn_ids,
                        )
                    )
                    matching_ids = checkpoint_matches | live_matches
                    if matching_ids:
                        await db.executemany(
                            "DELETE FROM l0_attention_items WHERE item_id = ?",
                            [(item_id,) for item_id in sorted(matching_ids)],
                        )
                    await db.commit()
                except BaseException:
                    await db.rollback()
                    raise
            for items in host._attention_items.values():
                for item_id in matching_ids:
                    items.pop(item_id, None)
            return len(matching_ids)

    async def remove_attention_for_turn_cutoffs(
        self,
        turn_ids: Iterable[str],
    ) -> int:
        """Physically remove attention covered by already-durable turn cutoffs."""

        normalized_turn_ids = set(
            normalize_attention_source_references(turn_ids)
        )
        if not normalized_turn_ids:
            return 0
        host = cast(_L0SourceForgettingHostProtocol, self)
        await host.initialize()
        async with host._checkpoint_lock:
            live_matches = {
                item_id
                for items in host._attention_items.values()
                for item_id, item in items.items()
                if set(item.get("source_turn_ids", ())) & normalized_turn_ids
            }
            async with sqlite_connection_async(host.checkpoint_db_path) as db:
                db.row_factory = aiosqlite.Row
                await db.execute("BEGIN IMMEDIATE")
                try:
                    checkpoint_matches = (
                        await self._checkpoint_attention_ids_for_references(
                            db,
                            normalized_turn_ids,
                        )
                    )
                    matching_ids = checkpoint_matches | live_matches
                    if matching_ids:
                        await db.executemany(
                            "DELETE FROM l0_attention_items WHERE item_id = ?",
                            [(item_id,) for item_id in sorted(matching_ids)],
                        )
                    await db.commit()
                except BaseException:
                    await db.rollback()
                    raise
            for items in host._attention_items.values():
                for item_id in matching_ids:
                    items.pop(item_id, None)
            return len(matching_ids)

    async def _checkpoint_attention_ids_for_references(
        self,
        db: aiosqlite.Connection,
        references: set[str],
    ) -> set[str]:
        matches: set[str] = set()
        malformed_ids: list[str] = []
        async with db.execute("SELECT * FROM l0_attention_items") as cursor:
            async for row in cursor:
                try:
                    item = row_to_attention_item(row)
                except (TypeError, ValueError, KeyError):
                    malformed_ids.append(str(row["item_id"]))
                    continue
                if attention_source_references(item) & references:
                    matches.add(str(item["item_id"]))
        if malformed_ids:
            await db.executemany(
                "DELETE FROM l0_attention_items WHERE item_id = ?",
                [(item_id,) for item_id in malformed_ids],
            )
        return matches

__all__ = [
    "L0SourceForgettingMixin",
    "attention_item_predates_entity_forget",
    "attention_item_predates_turn_forget",
    "attention_source_references",
    "filter_attention_items_by_governance",
    "forgotten_attention_entity_cutoffs",
    "forgotten_attention_source_references",
    "forgotten_attention_turn_cutoffs",
    "latest_attention_entity_forget_cutoff",
    "normalize_attention_source_references",
]
