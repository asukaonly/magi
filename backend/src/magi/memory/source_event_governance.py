"""Durable global barriers for user-forgotten source events."""

from __future__ import annotations

import hashlib
import json
import math
import sqlite3
import time
from collections.abc import Iterable
from dataclasses import dataclass

import aiosqlite

from .event_contracts import MemoryEvent

_CHAT_SESSION_SOURCE_PREFIX = "chat-session:v1:"
_IDEMPOTENCY_SOURCE_PREFIX = "source-idempotency:v1:"
_SOURCE_ITEM_SOURCE_PREFIX = "source-item:v1:"


@dataclass(frozen=True, slots=True)
class TimeRangeForgetBarrier:
    """One durable occurrence-time rule owned by a forget operation."""

    operation_id: str
    target_id: str
    range_start: float
    range_end: float
    delete_l1_events: bool


@dataclass(frozen=True, slots=True)
class TimeRangeGovernanceDecision:
    """Outcome of matching one source occurrence against durable ranges."""

    barriers: tuple[TimeRangeForgetBarrier, ...] = ()

    @property
    def blocks_derivations(self) -> bool:
        return bool(self.barriers)

    @property
    def delete_l1_event(self) -> bool:
        return any(barrier.delete_l1_events for barrier in self.barriers)


def source_event_derivation_block_predicate(alias: str = "projection_blocks") -> str:
    """Return the SQL policy that blocks source-derived memory projections."""
    return f"""
        (
            {alias}.block_kind = 'entity_projection'
            OR (
                {alias}.block_kind = 'episode_formation'
                AND {alias}.target_id LIKE 'time:%'
            )
        )
    """


def source_event_time_range_block_predicate(alias: str = "projection_blocks") -> str:
    """Return the SQL policy for one governed time-range source occurrence."""
    return f"""
        {alias}.block_kind = 'episode_formation'
        AND {alias}.target_id LIKE 'time:%'
    """


def source_occurrence_visible_predicate(
    timestamp_expression: str,
    *,
    barrier_alias: str = "forget_range",
) -> str:
    """Return SQL that hides source rows covered by an L1-delete range."""
    return f"""
        NOT EXISTS (
            SELECT 1
            FROM memory_time_range_forget_barriers AS {barrier_alias}
            WHERE {barrier_alias}.delete_l1_events = 1
              AND {barrier_alias}.range_start <= {timestamp_expression}
              AND {barrier_alias}.range_end >= {timestamp_expression}
        )
    """


def normalize_source_event_ids(event_ids: Iterable[str]) -> tuple[str, ...]:
    """Return stable, non-empty source event identities."""
    return tuple(
        dict.fromkeys(str(event_id).strip() for event_id in event_ids if str(event_id).strip())
    )


def business_source_references(
    *,
    source: str,
    event_type: str,
    source_item_id: str | None = None,
    idempotency_key: str | None = None,
    include_source_item: bool = True,
) -> tuple[str, ...]:
    """Return typed replay barriers for one source-owned business identity."""
    normalized_source = str(source or "").strip()
    normalized_event_type = str(event_type or "").strip()
    if not normalized_source:
        return ()
    references: list[str] = []
    if include_source_item:
        normalized_source_item_id = str(source_item_id or "").strip()
        if normalized_source_item_id:
            payload = json.dumps(
                [normalized_source, normalized_source_item_id],
                ensure_ascii=False,
                separators=(",", ":"),
            )
            digest = hashlib.sha256(payload.encode("utf-8")).hexdigest()
            references.append(f"{_SOURCE_ITEM_SOURCE_PREFIX}{digest}")
    normalized_idempotency_key = str(idempotency_key or "").strip()
    if normalized_idempotency_key and normalized_event_type:
        payload = json.dumps(
            [normalized_source, normalized_event_type, normalized_idempotency_key],
            ensure_ascii=False,
            separators=(",", ":"),
        )
        digest = hashlib.sha256(payload.encode("utf-8")).hexdigest()
        references.append(f"{_IDEMPOTENCY_SOURCE_PREFIX}{digest}")
    return normalize_source_event_ids(references)


def chat_session_source_reference(*, user_id: str, session_id: str) -> str:
    """Return the owner-scoped replay barrier for one chat session identity."""
    normalized_user_id = str(user_id or "").strip()
    normalized_session_id = str(session_id or "").strip()
    if not normalized_user_id or not normalized_session_id:
        raise ValueError("Chat user and session IDs must not be empty")
    payload = json.dumps(
        [normalized_user_id, normalized_session_id],
        ensure_ascii=False,
        separators=(",", ":"),
    )
    digest = hashlib.sha256(payload.encode("utf-8")).hexdigest()
    return f"{_CHAT_SESSION_SOURCE_PREFIX}{digest}"


def memory_event_source_references(event: MemoryEvent) -> tuple[str, ...]:
    """Return every durable identity that can govern one memory event replay."""
    references = [event.event_id, event.turn_id]
    if str(event.session_id or "").strip():
        references.append(
            chat_session_source_reference(
                user_id=str(event.user_id or ""),
                session_id=str(event.session_id),
            )
        )
    references.extend(
        business_source_references(
            source=event.source,
            event_type=event.event_type,
            source_item_id=event.source_item_id,
            idempotency_key=event.idempotency_key,
        )
    )
    return normalize_source_event_ids(references)


async def tombstone_source_event_ids(
    db: aiosqlite.Connection,
    *,
    event_ids: Iterable[str],
    reason: str,
    created_at: float,
) -> int:
    """Persist global source-event barriers and return newly inserted rows."""
    normalized = normalize_source_event_ids(event_ids)
    normalized_reason = str(reason).strip()
    if not normalized_reason:
        raise ValueError("Source-event tombstone reason must not be empty")
    if not normalized:
        return 0
    before = db.total_changes
    await db.executemany(
        """
        INSERT OR IGNORE INTO memory_source_event_tombstones(event_id, reason, created_at)
        VALUES (?, ?, ?)
        """,
        [(event_id, normalized_reason, created_at) for event_id in normalized],
    )
    return max(db.total_changes - before, 0)


async def source_event_tombstone_ids(
    db: aiosqlite.Connection,
    event_ids: Iterable[str],
) -> set[str]:
    """Return candidate source events already governed by a global barrier."""
    normalized = normalize_source_event_ids(event_ids)
    if not normalized:
        return set()
    found: set[str] = set()
    for offset in range(0, len(normalized), 500):
        chunk = normalized[offset : offset + 500]
        placeholders = ", ".join("?" for _ in chunk)
        async with db.execute(
            f"""
            SELECT event_id
            FROM memory_source_event_tombstones
            WHERE event_id IN ({placeholders})
            """,
            tuple(chunk),
        ) as cursor:
            found.update(str(row[0]) for row in await cursor.fetchall())
    return found


async def source_event_projection_block_ids(
    db: aiosqlite.Connection,
    event_ids: Iterable[str],
    *,
    block_kind: str = "entity_projection",
) -> set[str]:
    """Return old evidence blocked from one class of derived projection."""
    normalized = normalize_source_event_ids(event_ids)
    normalized_kind = str(block_kind or "").strip()
    if not normalized or not normalized_kind:
        return set()
    found: set[str] = set()
    for offset in range(0, len(normalized), 500):
        chunk = normalized[offset : offset + 500]
        placeholders = ", ".join("?" for _ in chunk)
        async with db.execute(
            f"""
            SELECT DISTINCT event_id
            FROM memory_projection_blocks
            WHERE block_kind = ? AND event_id IN ({placeholders})
            """,
            (normalized_kind, *chunk),
        ) as cursor:
            found.update(str(row[0]) for row in await cursor.fetchall())
    return found


async def source_event_derivation_block_ids(
    db: aiosqlite.Connection,
    event_ids: Iterable[str],
) -> set[str]:
    """Return source events blocked from general L3/L4 derivation."""
    normalized = normalize_source_event_ids(event_ids)
    if not normalized:
        return set()
    found: set[str] = set()
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


async def source_event_time_range_block_ids(
    db: aiosqlite.Connection,
    event_ids: Iterable[str],
) -> set[str]:
    """Return source events governed by any durable time-range barrier."""
    normalized = normalize_source_event_ids(event_ids)
    if not normalized:
        return set()
    found: set[str] = set()
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


async def matching_time_range_forget_barriers(
    db: aiosqlite.Connection,
    *,
    observed_from: float,
    observed_to: float | None = None,
) -> tuple[TimeRangeForgetBarrier, ...]:
    """Return durable ranges overlapping one canonical occurrence interval."""
    interval_start = float(observed_from)
    interval_end = interval_start if observed_to is None else float(observed_to)
    if not math.isfinite(interval_start) or not math.isfinite(interval_end):
        raise ValueError("Source occurrence time must be finite")
    if interval_end < interval_start:
        interval_start, interval_end = interval_end, interval_start
    try:
        async with db.execute(
            """
            SELECT operation_id, target_id, range_start, range_end, delete_l1_events
            FROM memory_time_range_forget_barriers
            WHERE range_start <= ? AND range_end >= ?
            ORDER BY range_start, range_end, operation_id
            """,
            (interval_end, interval_start),
        ) as cursor:
            rows = await cursor.fetchall()
    except sqlite3.OperationalError as exc:
        if "no such table: memory_time_range_forget_barriers" not in str(exc):
            raise
        if await _durable_forget_schema_exists(db):
            raise RuntimeError("Durable time-range forget barrier schema is missing") from exc
        return ()
    return tuple(
        TimeRangeForgetBarrier(
            operation_id=str(row[0]),
            target_id=str(row[1]),
            range_start=float(row[2]),
            range_end=float(row[3]),
            delete_l1_events=bool(row[4]),
        )
        for row in rows
    )


async def govern_source_events_by_time_range(
    db: aiosqlite.Connection,
    *,
    event_ids: Iterable[str],
    observed_from: float,
    observed_to: float | None = None,
) -> TimeRangeGovernanceDecision:
    """Atomically attach event-specific derivation blocks for matching ranges."""
    normalized = normalize_source_event_ids(event_ids)
    barriers = await matching_time_range_forget_barriers(
        db,
        observed_from=observed_from,
        observed_to=observed_to,
    )
    if not normalized or not barriers:
        return TimeRangeGovernanceDecision(barriers=barriers)
    created_at = time.time()
    await db.executemany(
        """
        INSERT OR IGNORE INTO memory_projection_blocks(
            block_kind, target_id, event_id, operation_id, created_at
        ) VALUES ('episode_formation', ?, ?, ?, ?)
        """,
        [
            (
                barrier.target_id,
                event_id,
                barrier.operation_id,
                created_at,
            )
            for barrier in barriers
            for event_id in normalized
        ],
    )
    return TimeRangeGovernanceDecision(barriers=barriers)


async def _durable_forget_schema_exists(db: aiosqlite.Connection) -> bool:
    async with db.execute("""
        SELECT 1
        FROM sqlite_master
        WHERE type = 'table' AND name = 'memory_forget_operations'
        """) as cursor:
        return await cursor.fetchone() is not None


async def source_event_entity_projection_block_ids(
    db: aiosqlite.Connection,
    event_ids: Iterable[str],
    *,
    entity_ids: Iterable[str],
) -> set[str]:
    """Return evidence blocked only when it projects one forgotten entity."""
    normalized_events = normalize_source_event_ids(event_ids)
    normalized_entities = normalize_source_event_ids(entity_ids)
    if not normalized_events or not normalized_entities:
        return set()
    entity_json = json.dumps(
        normalized_entities,
        ensure_ascii=False,
        separators=(",", ":"),
    )
    found: set[str] = set()
    for offset in range(0, len(normalized_events), 500):
        chunk = normalized_events[offset : offset + 500]
        placeholders = ", ".join("?" for _ in chunk)
        async with db.execute(
            f"""
            SELECT DISTINCT event_id
            FROM memory_projection_blocks
            WHERE block_kind IN (
                    'entity_projection', 'entity_projection_candidate'
                  )
              AND target_id IN (
                  SELECT CAST(value AS TEXT) FROM json_each(?)
              )
              AND event_id IN ({placeholders})
            """,
            (entity_json, *chunk),
        ) as cursor:
            found.update(str(row[0]) for row in await cursor.fetchall())
    return found


async def promote_source_event_entity_projection_candidates(
    db: aiosqlite.Connection,
    event_ids: Iterable[str],
    *,
    entity_ids: Iterable[str],
) -> int:
    """Promote narrow backlog barriers after a write proves entity lineage."""
    normalized_events = normalize_source_event_ids(event_ids)
    normalized_entities = normalize_source_event_ids(entity_ids)
    if not normalized_events or not normalized_entities:
        return 0
    event_json = json.dumps(
        normalized_events,
        ensure_ascii=False,
        separators=(",", ":"),
    )
    entity_json = json.dumps(
        normalized_entities,
        ensure_ascii=False,
        separators=(",", ":"),
    )
    before = db.total_changes
    await db.execute(
        """
        INSERT OR IGNORE INTO memory_projection_blocks(
            block_kind, target_id, event_id, operation_id, created_at
        )
        SELECT 'entity_projection',
               candidate.target_id,
               candidate.event_id,
               candidate.operation_id,
               candidate.created_at
        FROM memory_projection_blocks AS candidate
        WHERE candidate.block_kind = 'entity_projection_candidate'
          AND candidate.target_id IN (
              SELECT CAST(value AS TEXT) FROM json_each(?)
          )
          AND candidate.event_id IN (
              SELECT CAST(value AS TEXT) FROM json_each(?)
          )
        """,
        (entity_json, event_json),
    )
    return max(db.total_changes - before, 0)


__all__ = [
    "TimeRangeForgetBarrier",
    "TimeRangeGovernanceDecision",
    "business_source_references",
    "chat_session_source_reference",
    "govern_source_events_by_time_range",
    "matching_time_range_forget_barriers",
    "memory_event_source_references",
    "normalize_source_event_ids",
    "promote_source_event_entity_projection_candidates",
    "source_event_derivation_block_ids",
    "source_event_derivation_block_predicate",
    "source_event_entity_projection_block_ids",
    "source_event_projection_block_ids",
    "source_event_time_range_block_ids",
    "source_event_time_range_block_predicate",
    "source_event_tombstone_ids",
    "source_occurrence_visible_predicate",
    "tombstone_source_event_ids",
]
