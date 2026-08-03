"""Durable outbox for cross-database L1 entity-link projections."""

from __future__ import annotations

import hashlib
import json
import time
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from typing import Any, Protocol, cast

import aiosqlite

from ....core.sqlite import sqlite_connection_async
from ...clear_generation import (
    advance_memory_clear_generation,
    memory_clear_generation_on_connection,
)
from ...entity_link_projection import (
    DesiredEntityLink,
    desired_entity_links_from_json,
    desired_entity_links_json,
    normalize_desired_entity_links,
)
from ..batch_models import L2ProjectionLease
from .fencing import assert_current_projection_attempt, normalize_projection_leases


@dataclass(frozen=True, slots=True)
class L2EventEntityLinkOutboxItem:
    """One revision-fenced desired entity-link set for an L1 event."""

    event_id: str
    revision: int
    batch_key: str
    lease_token: str
    attempt_count: int
    clear_generation: int
    desired_links: tuple[DesiredEntityLink, ...]


@dataclass(frozen=True, slots=True)
class L2EventEntityLinkOutboxBatch:
    """One atomically published multi-event desired-set batch."""

    batch_key: str
    items: tuple[L2EventEntityLinkOutboxItem, ...]


@dataclass(frozen=True, slots=True)
class _AuthoritativeEntityLinkRevision:
    """Latest consumable or applied desired set for one event."""

    event_id: str
    revision: int
    batch_key: str
    state: str
    desired_links: tuple[DesiredEntityLink, ...]


class _L2EventEntityLinkOutboxHostProtocol(Protocol):
    db_path: str

    async def initialize(self) -> None: ...


class L2EventEntityLinkOutboxMixin:
    """Stage and reconcile L1 entity links without cross-database TOCTOU."""

    async def stage_event_entity_link_projections(
        self,
        *,
        desired_links_by_event: Mapping[str, Sequence[DesiredEntityLink]],
        projection_leases: Iterable[L2ProjectionLease],
    ) -> L2EventEntityLinkOutboxBatch:
        """Stage a complete desired-set batch inside its exact L2 attempt."""

        leases = normalize_projection_leases(projection_leases, required=True)
        desired_event_ids = {str(event_id or "").strip() for event_id in desired_links_by_event}
        lease_event_ids = {lease.event_id for lease in leases}
        if not all(desired_event_ids) or desired_event_ids != lease_event_ids:
            raise ValueError("desired entity links must cover the complete projection lease set")

        normalized_by_event = {
            lease.event_id: normalize_desired_entity_links(desired_links_by_event[lease.event_id])
            for lease in leases
        }
        batch_key = projection_entity_link_batch_key(leases)
        host = cast(_L2EventEntityLinkOutboxHostProtocol, self)
        await host.initialize()
        now = time.time()
        staged: list[L2EventEntityLinkOutboxItem] = []
        async with sqlite_connection_async(host.db_path, profile="hot_write") as db:
            db.row_factory = aiosqlite.Row
            await db.execute("BEGIN IMMEDIATE")
            try:
                await assert_current_projection_attempt(db, leases)
                clear_generation = await memory_clear_generation_on_connection(db)
                for lease in leases:
                    desired_links = normalized_by_event[lease.event_id]
                    payload_json = desired_entity_links_json(desired_links)
                    async with db.execute(
                        """
                        SELECT revision, state, desired_links_json
                        FROM l2_event_entity_link_outbox
                        WHERE event_id = ? AND batch_key = ?
                        """,
                        (lease.event_id, batch_key),
                    ) as cursor:
                        attempt_row = await cursor.fetchone()
                    if attempt_row is not None:
                        if str(attempt_row["state"]) != "pending":
                            raise RuntimeError(
                                "L2 entity-link projection attempt is no longer pending"
                            )
                        if str(attempt_row["desired_links_json"]) != payload_json:
                            raise RuntimeError(
                                "L2 entity-link projection attempt maps to conflicting payloads"
                            )
                        revision = int(attempt_row["revision"])
                    else:
                        revision = await _next_event_revision(db, lease.event_id)
                        await db.execute(
                            """
                            INSERT INTO l2_event_entity_link_outbox(
                                event_id, revision, batch_key, lease_token, attempt_count,
                                clear_generation, desired_links_json, state,
                                created_at, updated_at, applied_at
                            ) VALUES (?, ?, ?, ?, ?, ?, ?, 'pending', ?, ?, NULL)
                            """,
                            (
                                lease.event_id,
                                revision,
                                batch_key,
                                lease.lease_token,
                                lease.attempt_count,
                                clear_generation,
                                payload_json,
                                now,
                                now,
                            ),
                        )
                    staged.append(
                        L2EventEntityLinkOutboxItem(
                            event_id=lease.event_id,
                            revision=revision,
                            batch_key=batch_key,
                            lease_token=lease.lease_token,
                            attempt_count=lease.attempt_count,
                            clear_generation=clear_generation,
                            desired_links=desired_links,
                        )
                    )
                await db.commit()
            except BaseException:
                await db.rollback()
                raise
        return L2EventEntityLinkOutboxBatch(
            batch_key=batch_key,
            items=tuple(sorted(staged, key=lambda item: item.event_id)),
        )

    async def prepare_event_entity_link_outbox(
        self,
    ) -> list[L2EventEntityLinkOutboxBatch]:
        """Discard stale pending batches and return completion-published batches."""

        host = cast(_L2EventEntityLinkOutboxHostProtocol, self)
        await host.initialize()
        now = time.time()
        async with sqlite_connection_async(host.db_path, profile="hot_write") as db:
            db.row_factory = aiosqlite.Row
            await db.execute("BEGIN IMMEDIATE")
            try:
                clear_generation = await memory_clear_generation_on_connection(db)
                await db.execute(
                    """
                    UPDATE l2_event_entity_link_outbox
                    SET state = 'discarded', updated_at = ?
                    WHERE state IN ('pending', 'ready') AND clear_generation != ?
                    """,
                    (now, clear_generation),
                )
                async with db.execute(
                    """
                    SELECT outbox.batch_key, outbox.event_id,
                           outbox.lease_token, outbox.attempt_count,
                           jobs.status AS job_status,
                           jobs.lease_token AS job_lease_token,
                           jobs.attempt_count AS job_attempt_count
                    FROM l2_event_entity_link_outbox AS outbox
                    LEFT JOIN l2_projection_jobs AS jobs
                      ON jobs.event_id = outbox.event_id
                    WHERE outbox.state = 'pending'
                      AND outbox.clear_generation = ?
                    ORDER BY outbox.batch_key, outbox.event_id
                    """,
                    (clear_generation,),
                ) as cursor:
                    pending_rows = await cursor.fetchall()
                pending_by_batch: dict[str, list[aiosqlite.Row]] = {}
                for row in pending_rows:
                    pending_by_batch.setdefault(str(row["batch_key"]), []).append(row)
                for batch_key, rows in pending_by_batch.items():
                    if all(_pending_row_still_current(row) for row in rows):
                        continue
                    await db.execute(
                        """
                        UPDATE l2_event_entity_link_outbox
                        SET state = 'discarded', updated_at = ?
                        WHERE batch_key = ? AND state = 'pending'
                        """,
                        (now, batch_key),
                    )

                async with db.execute(
                    """
                    SELECT event_id, revision, batch_key, lease_token, attempt_count,
                           clear_generation, desired_links_json
                    FROM l2_event_entity_link_outbox
                    WHERE state = 'ready' AND clear_generation = ?
                    ORDER BY created_at, batch_key, event_id
                    """,
                    (clear_generation,),
                ) as cursor:
                    ready_rows = await cursor.fetchall()
                await db.commit()
            except BaseException:
                await db.rollback()
                raise
        return _outbox_batches_from_rows(ready_rows)

    async def acknowledge_event_entity_link_projection_batch(
        self,
        batch: L2EventEntityLinkOutboxBatch,
    ) -> bool:
        """CAS-acknowledge a complete ready batch in one transaction."""

        if not batch.items or any(item.batch_key != batch.batch_key for item in batch.items):
            raise ValueError("entity-link outbox batch must be complete and consistent")
        expected = {item.event_id: (item.revision, item.clear_generation) for item in batch.items}
        if len(expected) != len(batch.items):
            raise ValueError("entity-link outbox batch must contain unique event IDs")
        host = cast(_L2EventEntityLinkOutboxHostProtocol, self)
        await host.initialize()
        now = time.time()
        async with sqlite_connection_async(host.db_path, profile="hot_write") as db:
            db.row_factory = aiosqlite.Row
            await db.execute("BEGIN IMMEDIATE")
            try:
                async with db.execute(
                    """
                    SELECT event_id, revision, clear_generation, state
                    FROM l2_event_entity_link_outbox
                    WHERE batch_key = ?
                    ORDER BY event_id
                    """,
                    (batch.batch_key,),
                ) as cursor:
                    rows = await cursor.fetchall()
                actual = {
                    str(row["event_id"]): (
                        int(row["revision"]),
                        int(row["clear_generation"]),
                    )
                    for row in rows
                }
                clear_generation = await memory_clear_generation_on_connection(db)
                if (
                    actual != expected
                    or any(str(row["state"]) not in {"ready", "applied"} for row in rows)
                    or any(item.clear_generation != clear_generation for item in batch.items)
                ):
                    await db.rollback()
                    return False
                await db.execute(
                    """
                    UPDATE l2_event_entity_link_outbox
                    SET state = 'applied', applied_at = COALESCE(applied_at, ?), updated_at = ?
                    WHERE batch_key = ? AND state = 'ready'
                    """,
                    (now, now, batch.batch_key),
                )
                await db.commit()
                return True
            except BaseException:
                await db.rollback()
                raise

    async def _finalize_event_entity_link_outbox_on_connection(
        self,
        db: aiosqlite.Connection,
        *,
        leases: tuple[L2ProjectionLease, ...],
    ) -> int:
        """Publish a complete staged batch inside queue completion."""

        normalized = normalize_projection_leases(leases, required=True)
        batch_key = projection_entity_link_batch_key(normalized)
        event_ids = {lease.event_id for lease in normalized}
        clear_generation = await memory_clear_generation_on_connection(db)
        async with db.execute(
            """
            SELECT event_id, lease_token, attempt_count, clear_generation, state
            FROM l2_event_entity_link_outbox
            WHERE batch_key = ?
            """,
            (batch_key,),
        ) as cursor:
            rows = await cursor.fetchall()
        if len(rows) != len(normalized) or {str(row["event_id"]) for row in rows} != event_ids:
            raise RuntimeError("projection completion is missing staged entity-link outputs")
        lease_by_event = {lease.event_id: lease for lease in normalized}
        if any(
            str(row["state"]) != "pending"
            or int(row["clear_generation"]) != clear_generation
            or str(row["lease_token"]) != lease_by_event[str(row["event_id"])].lease_token
            or int(row["attempt_count"]) != lease_by_event[str(row["event_id"])].attempt_count
            for row in rows
        ):
            raise RuntimeError("projection completion entity-link batch is not pending")
        now = time.time()
        cursor = await db.execute(
            """
            UPDATE l2_event_entity_link_outbox
            SET state = 'ready', updated_at = ?
            WHERE batch_key = ? AND state = 'pending'
            """,
            (now, batch_key),
        )
        finalized = max(int(cursor.rowcount or 0), 0)
        if finalized != len(normalized):
            raise RuntimeError(
                "projection completion did not publish its complete entity-link batch"
            )
        return finalized

    async def _stage_source_event_link_forget_on_connection(
        self,
        db: aiosqlite.Connection,
        *,
        event_ids: Sequence[str],
        reason: str,
    ) -> int:
        """Append an empty revision and irreversibly redact forgotten event links."""

        normalized = tuple(sorted({str(event_id).strip() for event_id in event_ids if event_id}))
        if not normalized:
            return 0
        clear_generation = await memory_clear_generation_on_connection(db)
        event_set = set(normalized)
        latest = await _latest_authoritative_link_revisions(
            db,
            clear_generation=clear_generation,
        )
        ready_batch_keys = await _ready_batch_keys_touching_source_events(
            db,
            normalized,
            clear_generation=clear_generation,
        )
        desired: dict[str, tuple[DesiredEntityLink, ...]] = {
            event_id: ()
            for event_id in normalized
            if event_id in latest and latest[event_id].desired_links
        }
        _add_ready_batch_compensations(
            desired,
            latest=latest,
            discarded_batch_keys=ready_batch_keys,
        )
        appended = await _append_forget_governance_batch(
            db,
            prefix="forget:event",
            operation_key=reason,
            clear_generation=clear_generation,
            desired_links_by_event=desired,
            latest=latest,
        )
        await _discard_pending_batches_touching_events(
            db,
            event_set,
            clear_generation=clear_generation,
        )
        await _discard_ready_batches(
            db,
            ready_batch_keys,
            clear_generation=clear_generation,
        )
        await _redact_source_event_link_payloads(db, normalized)
        return appended

    async def _stage_entity_link_forget_on_connection(
        self,
        db: aiosqlite.Connection,
        *,
        entity_id: str,
        operation_key: str,
    ) -> int:
        """Append filtered revisions and irreversibly redact one entity ID."""

        normalized_entity_id = str(entity_id or "").strip()
        if not normalized_entity_id:
            return 0
        clear_generation = await memory_clear_generation_on_connection(db)
        latest = await _latest_authoritative_link_revisions(
            db,
            clear_generation=clear_generation,
        )
        desired: dict[str, tuple[DesiredEntityLink, ...]] = {}
        for event_id, authoritative in latest.items():
            filtered = tuple(
                link for link in authoritative.desired_links if link[0] != normalized_entity_id
            )
            if len(filtered) != len(authoritative.desired_links):
                desired[event_id] = filtered
        pending_batch_keys = await _batch_keys_containing_entity(
            db,
            normalized_entity_id,
            state="pending",
            clear_generation=clear_generation,
        )
        ready_batch_keys = await _batch_keys_containing_entity(
            db,
            normalized_entity_id,
            state="ready",
            clear_generation=clear_generation,
        )
        _add_ready_batch_compensations(
            desired,
            latest=latest,
            discarded_batch_keys=ready_batch_keys,
        )
        appended = await _append_forget_governance_batch(
            db,
            prefix="forget:entity",
            operation_key=operation_key,
            clear_generation=clear_generation,
            desired_links_by_event=desired,
            latest=latest,
        )
        await _discard_batches_by_state(
            db,
            pending_batch_keys,
            state="pending",
            clear_generation=clear_generation,
        )
        await _discard_ready_batches(
            db,
            ready_batch_keys,
            clear_generation=clear_generation,
        )
        await _redact_entity_link_payloads(db, normalized_entity_id)
        return appended


async def begin_event_entity_link_projection_clear(db_path: str) -> int:
    """Fence every pre-clear outbox row before the separate L1 wipe starts."""

    async with sqlite_connection_async(db_path, profile="hot_write") as db:
        await db.execute("BEGIN IMMEDIATE")
        try:
            generation = await advance_memory_clear_generation(db)
            await db.commit()
            return generation
        except BaseException:
            await db.rollback()
            raise


async def clear_event_entity_link_projection_recovery(
    db_path: str,
    *,
    expected_clear_generation: int,
) -> int:
    """Delete recovery lineage only after L1 projections were cleared."""

    async with sqlite_connection_async(db_path, profile="hot_write") as db:
        await db.execute("BEGIN IMMEDIATE")
        try:
            deleted = await _clear_projection_recovery_on_connection(
                db,
                expected_clear_generation=expected_clear_generation,
            )
            await db.commit()
            return deleted
        except BaseException:
            await db.rollback()
            raise


def projection_entity_link_batch_key(leases: Iterable[L2ProjectionLease]) -> str:
    """Return the stable identity of one complete projection lease set."""

    normalized = normalize_projection_leases(leases, required=True)
    material = "\n".join(
        f"{lease.event_id}:{lease.attempt_count}:{lease.lease_token}"
        for lease in sorted(normalized, key=lambda item: item.event_id)
    )
    return "l2elb_" + hashlib.sha256(material.encode("utf-8")).hexdigest()[:32]


async def _next_event_revision(db: aiosqlite.Connection, event_id: str) -> int:
    async with db.execute(
        """
        SELECT COALESCE(MAX(revision), 0) + 1
        FROM l2_event_entity_link_outbox
        WHERE event_id = ?
        """,
        (event_id,),
    ) as cursor:
        row = await cursor.fetchone()
    return int(row[0])


async def _count_projection_recovery_rows(db: aiosqlite.Connection) -> int:
    tables = await _projection_recovery_tables(db)
    if "l2_event_entity_link_outbox" not in tables:
        return 0
    async with db.execute("SELECT COUNT(*) FROM l2_event_entity_link_outbox") as cursor:
        outbox_row = await cursor.fetchone()
    return int(outbox_row[0]) if outbox_row else 0


async def _clear_projection_recovery_on_connection(
    db: aiosqlite.Connection,
    *,
    expected_clear_generation: int,
) -> int:
    current_generation = await memory_clear_generation_on_connection(db)
    if int(expected_clear_generation) != current_generation:
        raise RuntimeError("entity-link projection clear generation is stale")
    tables = await _projection_recovery_tables(db)
    outbox_row = None
    jobs_row = None
    if "l2_event_entity_link_outbox" in tables:
        async with db.execute("SELECT COUNT(*) FROM l2_event_entity_link_outbox") as cursor:
            outbox_row = await cursor.fetchone()
        await db.execute("DELETE FROM l2_event_entity_link_outbox")
    if "l2_projection_jobs" in tables:
        async with db.execute("SELECT COUNT(*) FROM l2_projection_jobs") as cursor:
            jobs_row = await cursor.fetchone()
        await db.execute("DELETE FROM l2_projection_jobs")
    return int(outbox_row[0] if outbox_row else 0) + int(jobs_row[0] if jobs_row else 0)


async def _projection_recovery_tables(db: aiosqlite.Connection) -> set[str]:
    async with db.execute("""
        SELECT name FROM sqlite_master
        WHERE type = 'table'
          AND name IN ('l2_event_entity_link_outbox', 'l2_projection_jobs')
        """) as cursor:
        return {str(row[0]) for row in await cursor.fetchall()}


def _pending_row_still_current(row: Mapping[str, Any]) -> bool:
    return (
        str(row["job_status"] or "") == "running"
        and str(row["job_lease_token"] or "") == str(row["lease_token"])
        and int(row["job_attempt_count"] or 0) == int(row["attempt_count"])
    )


async def _discard_pending_batches_touching_events(
    db: aiosqlite.Connection,
    event_ids: set[str],
    *,
    clear_generation: int,
) -> None:
    if not event_ids:
        return
    placeholders = ", ".join("?" for _ in event_ids)
    async with db.execute(
        f"""
        SELECT DISTINCT batch_key
        FROM l2_event_entity_link_outbox
        WHERE state = 'pending' AND clear_generation = ?
          AND event_id IN ({placeholders})
        """,
        (clear_generation, *sorted(event_ids)),
    ) as cursor:
        batch_keys = [str(row[0]) for row in await cursor.fetchall()]
    now = time.time()
    for batch_key in batch_keys:
        await db.execute(
            """
            UPDATE l2_event_entity_link_outbox
            SET state = 'discarded', updated_at = ?
            WHERE batch_key = ? AND state = 'pending'
            """,
            (now, batch_key),
        )


async def _ready_batch_keys_touching_source_events(
    db: aiosqlite.Connection,
    event_ids: Sequence[str],
    *,
    clear_generation: int,
) -> set[str]:
    if not event_ids:
        return set()
    placeholders = ", ".join("?" for _ in event_ids)
    async with db.execute(
        f"""
        SELECT DISTINCT batch_key
        FROM l2_event_entity_link_outbox
        WHERE event_id IN ({placeholders}) AND state = 'ready'
          AND clear_generation = ? AND json_array_length(desired_links_json) > 0
        """,
        (*event_ids, clear_generation),
    ) as cursor:
        return {str(row[0]) for row in await cursor.fetchall()}


async def _batch_keys_containing_entity(
    db: aiosqlite.Connection,
    entity_id: str,
    *,
    state: str,
    clear_generation: int,
) -> set[str]:
    if state not in {"pending", "ready"}:
        raise ValueError("entity-link outbox state must be pending or ready")
    async with db.execute(
        """
        SELECT DISTINCT outbox.batch_key
        FROM l2_event_entity_link_outbox AS outbox,
             json_each(outbox.desired_links_json) AS link
        WHERE outbox.state = ? AND outbox.clear_generation = ?
          AND json_extract(link.value, '$.entity_id') = ?
        """,
        (state, clear_generation, entity_id),
    ) as cursor:
        return {str(row[0]) for row in await cursor.fetchall()}


async def _latest_authoritative_link_revisions(
    db: aiosqlite.Connection,
    *,
    clear_generation: int,
) -> dict[str, _AuthoritativeEntityLinkRevision]:
    async with db.execute(
        """
        SELECT outbox.event_id, outbox.revision, outbox.batch_key,
               outbox.state, outbox.desired_links_json
        FROM l2_event_entity_link_outbox AS outbox
        JOIN (
            SELECT event_id, MAX(revision) AS revision
            FROM l2_event_entity_link_outbox
            WHERE state IN ('ready', 'applied')
              AND clear_generation = ?
            GROUP BY event_id
        ) AS latest
          ON latest.event_id = outbox.event_id AND latest.revision = outbox.revision
        ORDER BY outbox.event_id
        """,
        (clear_generation,),
    ) as cursor:
        rows = await cursor.fetchall()
    return {
        str(row["event_id"]): _AuthoritativeEntityLinkRevision(
            event_id=str(row["event_id"]),
            revision=int(row["revision"]),
            batch_key=str(row["batch_key"]),
            state=str(row["state"]),
            desired_links=desired_entity_links_from_json(str(row["desired_links_json"])),
        )
        for row in rows
    }


def _add_ready_batch_compensations(
    desired_links_by_event: dict[str, tuple[DesiredEntityLink, ...]],
    *,
    latest: Mapping[str, _AuthoritativeEntityLinkRevision],
    discarded_batch_keys: set[str],
) -> None:
    """Preserve unrelated latest desired sets from discarded atomic batches."""

    for event_id, authoritative in latest.items():
        if (
            authoritative.state == "ready"
            and authoritative.batch_key in discarded_batch_keys
            and event_id not in desired_links_by_event
        ):
            desired_links_by_event[event_id] = authoritative.desired_links


async def _append_forget_governance_batch(
    db: aiosqlite.Connection,
    *,
    prefix: str,
    operation_key: str,
    clear_generation: int,
    desired_links_by_event: Mapping[str, Sequence[DesiredEntityLink]],
    latest: Mapping[str, _AuthoritativeEntityLinkRevision],
) -> int:
    if not desired_links_by_event:
        return 0
    predecessor_material = tuple(
        (
            event_id,
            latest[event_id].revision if event_id in latest else 0,
            (
                desired_entity_links_json(latest[event_id].desired_links)
                if event_id in latest
                else "[]"
            ),
        )
        for event_id in sorted(desired_links_by_event)
    )
    desired_material = tuple(
        (
            event_id,
            desired_entity_links_json(desired_links_by_event[event_id]),
        )
        for event_id in sorted(desired_links_by_event)
    )
    batch_key = _governance_batch_key(
        prefix,
        operation_key,
        (clear_generation, predecessor_material, desired_material),
    )
    return await _append_ready_governance_batch(
        db,
        batch_key=batch_key,
        desired_links_by_event=desired_links_by_event,
    )


async def _discard_ready_batches(
    db: aiosqlite.Connection,
    batch_keys: set[str],
    *,
    clear_generation: int,
) -> None:
    await _discard_batches_by_state(
        db,
        batch_keys,
        state="ready",
        clear_generation=clear_generation,
    )


async def _discard_batches_by_state(
    db: aiosqlite.Connection,
    batch_keys: set[str],
    *,
    state: str,
    clear_generation: int,
) -> None:
    if state not in {"pending", "ready"}:
        raise ValueError("entity-link outbox state must be pending or ready")
    if not batch_keys:
        return
    now = time.time()
    placeholders = ", ".join("?" for _ in batch_keys)
    await db.execute(
        f"""
        UPDATE l2_event_entity_link_outbox
        SET state = 'discarded', updated_at = ?
        WHERE state = ? AND clear_generation = ?
          AND batch_key IN ({placeholders})
        """,
        (now, state, clear_generation, *sorted(batch_keys)),
    )


async def _redact_source_event_link_payloads(
    db: aiosqlite.Connection,
    event_ids: Sequence[str],
) -> None:
    if not event_ids:
        return
    placeholders = ", ".join("?" for _ in event_ids)
    await db.execute(
        f"""
        UPDATE l2_event_entity_link_outbox
        SET desired_links_json = '[]', updated_at = ?
        WHERE event_id IN ({placeholders}) AND desired_links_json != '[]'
        """,
        (time.time(), *event_ids),
    )


async def _redact_entity_link_payloads(
    db: aiosqlite.Connection,
    entity_id: str,
) -> None:
    async with db.execute(
        """
        SELECT DISTINCT outbox.event_id, outbox.revision, outbox.desired_links_json
        FROM l2_event_entity_link_outbox AS outbox,
             json_each(outbox.desired_links_json) AS link
        WHERE json_extract(link.value, '$.entity_id') = ?
        ORDER BY outbox.event_id, outbox.revision
        """,
        (entity_id,),
    ) as cursor:
        rows = await cursor.fetchall()
    now = time.time()
    for row in rows:
        links = desired_entity_links_from_json(str(row["desired_links_json"]))
        filtered = tuple(link for link in links if link[0] != entity_id)
        await db.execute(
            """
            UPDATE l2_event_entity_link_outbox
            SET desired_links_json = ?, updated_at = ?
            WHERE event_id = ? AND revision = ?
            """,
            (
                desired_entity_links_json(filtered),
                now,
                str(row["event_id"]),
                int(row["revision"]),
            ),
        )


async def _append_ready_governance_batch(
    db: aiosqlite.Connection,
    *,
    batch_key: str,
    desired_links_by_event: Mapping[str, Sequence[DesiredEntityLink]],
) -> int:
    now = time.time()
    clear_generation = await memory_clear_generation_on_connection(db)
    appended = 0
    for event_id, raw_links in sorted(desired_links_by_event.items()):
        links = normalize_desired_entity_links(raw_links)
        payload_json = desired_entity_links_json(links)
        async with db.execute(
            """
            SELECT revision, desired_links_json, state
            FROM l2_event_entity_link_outbox
            WHERE event_id = ? AND batch_key = ?
            """,
            (event_id, batch_key),
        ) as cursor:
            existing = await cursor.fetchone()
        if existing is not None:
            if str(existing["desired_links_json"]) != payload_json or str(
                existing["state"]
            ) not in {"ready", "applied"}:
                raise RuntimeError("entity-link governance batch maps to conflicting payloads")
            continue
        revision = await _next_event_revision(db, event_id)
        await db.execute(
            """
            INSERT INTO l2_event_entity_link_outbox(
                event_id, revision, batch_key, lease_token, attempt_count,
                clear_generation, desired_links_json, state,
                created_at, updated_at, applied_at
            ) VALUES (?, ?, ?, ?, 1, ?, ?, 'ready', ?, ?, NULL)
            """,
            (
                event_id,
                revision,
                batch_key,
                batch_key,
                clear_generation,
                payload_json,
                now,
                now,
            ),
        )
        appended += 1
    return appended


def _governance_batch_key(prefix: str, operation_key: str, payload: Any) -> str:
    material = json.dumps(
        [prefix, str(operation_key), payload],
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
        default=list,
    )
    return f"{prefix}:" + hashlib.sha256(material.encode("utf-8")).hexdigest()[:32]


def _outbox_batches_from_rows(
    rows: Sequence[Mapping[str, Any]],
) -> list[L2EventEntityLinkOutboxBatch]:
    items_by_batch: dict[str, list[L2EventEntityLinkOutboxItem]] = {}
    for row in rows:
        batch_key = str(row["batch_key"])
        items_by_batch.setdefault(batch_key, []).append(
            L2EventEntityLinkOutboxItem(
                event_id=str(row["event_id"]),
                revision=int(row["revision"]),
                batch_key=batch_key,
                lease_token=str(row["lease_token"]),
                attempt_count=int(row["attempt_count"]),
                clear_generation=int(row["clear_generation"]),
                desired_links=desired_entity_links_from_json(str(row["desired_links_json"])),
            )
        )
    return [
        L2EventEntityLinkOutboxBatch(
            batch_key=batch_key,
            items=tuple(sorted(items, key=lambda item: item.event_id)),
        )
        for batch_key, items in items_by_batch.items()
    ]


__all__ = [
    "DesiredEntityLink",
    "L2EventEntityLinkOutboxBatch",
    "L2EventEntityLinkOutboxItem",
    "L2EventEntityLinkOutboxMixin",
    "begin_event_entity_link_projection_clear",
    "clear_event_entity_link_projection_recovery",
    "projection_entity_link_batch_key",
]
