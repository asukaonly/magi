"""Claim selection helpers for the L2 projection queue."""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Any, Dict, Protocol, cast

import aiosqlite

from ....core.sqlite import sqlite_connection_async
from ..batching_policy import BatchingPolicy, BucketState, decide_flush


class _ProjectionQueueClaimingHostProtocol(Protocol):
    db_path: str

    async def _count_by_status(self, db: aiosqlite.Connection, status: str) -> int: ...

    def _row_to_dict(self, row: aiosqlite.Row) -> Dict[str, Any]: ...


def _projection_queue_module() -> Any:
    from . import queue as projection_queue_module

    return projection_queue_module


def _build_owner_policy(
    *,
    max_events: int,
    min_ready_events: int,
    max_wait_seconds: float | None,
    claim_mode: str,
    steady_state_max_wait_cap: float,
) -> tuple[BatchingPolicy, bool]:
    """Translate raw SQL aggregation values into a BatchingPolicy for one owner.

    Returns the policy plus a flag indicating whether the interval-elapsed
    branch is reachable. Catch-up mode with no explicit max_wait_seconds keeps
    the prior behavior of never triggering on age alone.
    """
    if claim_mode == "catch_up":
        effective_min_ready = max_events
        effective_wait = max_wait_seconds
        wait_reachable = max_wait_seconds is not None
    else:
        effective_min_ready = max(1, min(min_ready_events, max_events))
        effective_wait = (
            min(max_wait_seconds, steady_state_max_wait_cap)
            if max_wait_seconds is not None
            else steady_state_max_wait_cap
        )
        wait_reachable = True
    policy = BatchingPolicy(
        max_events=max_events,
        max_estimated_tokens=10**9,  # token cap is not tracked in the durable queue
        max_wait_seconds=float(effective_wait if effective_wait is not None else 0.0),
        min_ready_events=effective_min_ready,
    )
    return policy, wait_reachable


@dataclass(frozen=True, slots=True)
class _OwnerBucket:
    owner: str
    catch_up_owner: str
    pending_count: int
    max_events: int
    min_ready_events: int
    max_wait_seconds: float | None
    oldest_created_at: float

    def oldest_age_seconds(self, now: float) -> float:
        return max(0.0, now - self.oldest_created_at)


def _owner_bucket_from_row(row: aiosqlite.Row, *, now: float) -> _OwnerBucket | None:
    owner = str(row["batch_owner"] or "").strip()
    if not owner:
        return None
    pending_count = int(row["pending_count"] or 0)
    if pending_count <= 0:
        return None
    max_wait_value = row["bucket_max_wait_seconds"]
    return _OwnerBucket(
        owner=owner,
        catch_up_owner=str(row["bucket_catch_up_owner"] or "").strip(),
        pending_count=pending_count,
        max_events=int(row["bucket_max_events"] or 1),
        min_ready_events=int(row["bucket_min_ready_events"] or (row["bucket_max_events"] or 1)),
        max_wait_seconds=float(max_wait_value) if max_wait_value is not None else None,
        oldest_created_at=float(row["oldest_created_at"] or now),
    )


def _bucket_claim_count(
    *,
    pending_count: int,
    ready_events: int,
    remaining: int,
    flush_reason: str | None,
) -> int:
    if flush_reason is None:
        return 0
    if pending_count < ready_events:
        return min(pending_count, remaining)
    claim_count = min((pending_count // ready_events) * ready_events, remaining)
    return claim_count - (claim_count % ready_events)


def _tail_claim_count(
    *,
    pending_count: int,
    max_events: int,
    remaining: int,
    flush_reason: str | None,
) -> int:
    return _bucket_claim_count(
        pending_count=pending_count,
        ready_events=max_events,
        remaining=remaining,
        flush_reason=flush_reason,
    )


def _tail_groups_by_oldest(
    low_frequency_owners_by_tail: dict[str, list[_OwnerBucket]],
) -> list[tuple[str, list[_OwnerBucket]]]:
    return sorted(
        low_frequency_owners_by_tail.items(),
        key=lambda item: min(bucket.oldest_created_at for bucket in item[1]),
    )


class ProjectionQueueClaimingMixin:
    """Owner-aware ready-claim behavior for projection queues."""

    async def claim_ready(
        self,
        *,
        consumer_name: str,
        limit: int,
    ) -> list[Dict[str, Any]]:
        """Claim pending jobs whose owner bucket is ready for extraction."""
        host = self._claiming_host()
        projection_queue_module = _projection_queue_module()
        requested_limit = max(1, int(limit))
        now = time.time()

        async with sqlite_connection_async(host.db_path) as db:
            db.row_factory = aiosqlite.Row
            pending_total = await host._count_by_status(db, "pending")
            claim_mode = self._claim_mode(pending_total, projection_queue_module)
            selected_event_ids, effective_owner_by_event_id = await self._select_ready_event_ids(
                db,
                limit=requested_limit,
                now=now,
                claim_mode=claim_mode,
                projection_queue_module=projection_queue_module,
            )
            if not selected_event_ids:
                return []
            claimed_rows = await self._claim_selected_rows(
                db,
                consumer_name=consumer_name,
                now=now,
                selected_event_ids=selected_event_ids,
            )

        return self._serialize_claimed_rows(
            host=host,
            claimed_rows=claimed_rows,
            selected_event_ids=selected_event_ids,
            effective_owner_by_event_id=effective_owner_by_event_id,
            requested_limit=requested_limit,
        )

    @staticmethod
    def _claim_mode(pending_total: int, projection_queue_module: Any) -> str:
        if pending_total >= projection_queue_module.DEFAULT_L2_CATCH_UP_PENDING_THRESHOLD:
            return "catch_up"
        return "steady_state"

    async def _select_ready_event_ids(
        self,
        db: aiosqlite.Connection,
        *,
        limit: int,
        now: float,
        claim_mode: str,
        projection_queue_module: Any,
    ) -> tuple[list[str], dict[str, str]]:
        selected_event_ids: list[str] = []
        effective_owner_by_event_id: dict[str, str] = {}
        remaining = limit

        unowned_event_ids = await self._select_unowned_event_ids(db, limit=remaining)
        selected_event_ids.extend(unowned_event_ids)
        remaining -= len(unowned_event_ids)
        if remaining <= 0:
            return selected_event_ids, effective_owner_by_event_id

        buckets = await self._fetch_owner_buckets(db, now=now)
        low_frequency_owners_by_tail: dict[str, list[_OwnerBucket]] = {}
        steady_wait_cap = float(projection_queue_module.DEFAULT_L2_STEADY_STATE_MAX_WAIT_SECONDS)

        for bucket in buckets:
            if remaining <= 0:
                break
            claim_count = self._claim_count_for_owner_bucket(
                bucket,
                claim_mode=claim_mode,
                remaining=remaining,
                now=now,
                steady_wait_cap=steady_wait_cap,
            )
            if self._should_defer_to_tail_merge(bucket, claim_mode, claim_count):
                low_frequency_owners_by_tail.setdefault(bucket.catch_up_owner, []).append(bucket)
                continue
            if claim_count <= 0:
                continue

            owner_event_ids = await self._select_owner_event_ids(
                db,
                owner=bucket.owner,
                limit=claim_count,
            )
            selected_event_ids.extend(owner_event_ids)
            effective_owner_by_event_id.update(
                {event_id: bucket.owner for event_id in owner_event_ids}
            )
            remaining -= len(owner_event_ids)

        if claim_mode == "catch_up" and remaining > 0 and low_frequency_owners_by_tail:
            tail_event_ids, tail_owner_map = await self._select_tail_event_ids(
                db,
                low_frequency_owners_by_tail=low_frequency_owners_by_tail,
                remaining=remaining,
                now=now,
            )
            selected_event_ids.extend(tail_event_ids)
            effective_owner_by_event_id.update(tail_owner_map)

        return selected_event_ids, effective_owner_by_event_id

    @staticmethod
    def _claim_count_for_owner_bucket(
        bucket: _OwnerBucket,
        *,
        claim_mode: str,
        remaining: int,
        now: float,
        steady_wait_cap: float,
    ) -> int:
        policy, wait_reachable = _build_owner_policy(
            max_events=bucket.max_events,
            min_ready_events=bucket.min_ready_events,
            max_wait_seconds=bucket.max_wait_seconds,
            claim_mode=claim_mode,
            steady_state_max_wait_cap=steady_wait_cap,
        )
        state = BucketState(
            event_count=bucket.pending_count,
            estimated_tokens=0,
            oldest_age_seconds=bucket.oldest_age_seconds(now),
        )
        flush_reason = decide_flush(state, policy, batching_enabled=wait_reachable)
        return _bucket_claim_count(
            pending_count=bucket.pending_count,
            ready_events=policy.min_ready_events or policy.max_events,
            remaining=remaining,
            flush_reason=flush_reason,
        )

    @staticmethod
    def _should_defer_to_tail_merge(
        bucket: _OwnerBucket,
        claim_mode: str,
        claim_count: int,
    ) -> bool:
        return (
            claim_count <= 0
            and claim_mode == "catch_up"
            and bool(bucket.catch_up_owner)
            and bucket.pending_count < bucket.max_events
        )

    @staticmethod
    async def _select_unowned_event_ids(
        db: aiosqlite.Connection,
        *,
        limit: int,
    ) -> list[str]:
        async with db.execute(
            """
            SELECT event_id
            FROM l2_projection_jobs
            WHERE status = 'pending'
              AND (batch_owner IS NULL OR batch_owner = '')
            ORDER BY created_at ASC
            LIMIT ?
            """,
            (limit,),
        ) as cursor:
            rows = await cursor.fetchall()
        return [str(row["event_id"]) for row in rows]

    @staticmethod
    async def _fetch_owner_buckets(
        db: aiosqlite.Connection,
        *,
        now: float,
    ) -> list[_OwnerBucket]:
        async with db.execute(
            """
            SELECT
                batch_owner,
                MIN(NULLIF(catch_up_owner, '')) AS bucket_catch_up_owner,
                COUNT(*) AS pending_count,
                MIN(created_at) AS oldest_created_at,
                MIN(CASE WHEN max_events IS NOT NULL AND max_events > 0 THEN max_events END) AS bucket_max_events,
                MIN(CASE WHEN min_ready_events IS NOT NULL AND min_ready_events > 0 THEN min_ready_events END) AS bucket_min_ready_events,
                MIN(CASE WHEN max_wait_seconds IS NOT NULL AND max_wait_seconds > 0 THEN max_wait_seconds END) AS bucket_max_wait_seconds
            FROM l2_projection_jobs
            WHERE status = 'pending'
              AND batch_owner IS NOT NULL
              AND batch_owner != ''
            GROUP BY batch_owner
            ORDER BY oldest_created_at ASC
            """,
        ) as cursor:
            owner_rows = await cursor.fetchall()
        return [
            bucket
            for row in owner_rows
            if (bucket := _owner_bucket_from_row(row, now=now)) is not None
        ]

    @staticmethod
    async def _select_owner_event_ids(
        db: aiosqlite.Connection,
        *,
        owner: str,
        limit: int,
    ) -> list[str]:
        async with db.execute(
            """
            SELECT event_id
            FROM l2_projection_jobs
            WHERE status = 'pending'
              AND batch_owner = ?
            ORDER BY created_at ASC
            LIMIT ?
            """,
            (owner, limit),
        ) as cursor:
            event_rows = await cursor.fetchall()
        return [str(row["event_id"]) for row in event_rows]

    async def _select_tail_event_ids(
        self,
        db: aiosqlite.Connection,
        *,
        low_frequency_owners_by_tail: dict[str, list[_OwnerBucket]],
        remaining: int,
        now: float,
    ) -> tuple[list[str], dict[str, str]]:
        selected_event_ids: list[str] = []
        effective_owner_by_event_id: dict[str, str] = {}

        for catch_up_owner, grouped_buckets in _tail_groups_by_oldest(low_frequency_owners_by_tail):
            if remaining <= 0:
                break
            claim_count = self._claim_count_for_tail_group(
                grouped_buckets,
                remaining=remaining,
                now=now,
            )
            if claim_count <= 0:
                continue
            owner_names = [bucket.owner for bucket in grouped_buckets if bucket.owner]
            if not owner_names:
                continue

            tail_event_ids = await self._select_event_ids_for_owner_group(
                db,
                owner_names=owner_names,
                limit=claim_count,
            )
            if not tail_event_ids:
                continue
            selected_event_ids.extend(tail_event_ids)
            effective_owner_by_event_id.update(
                {event_id: catch_up_owner for event_id in tail_event_ids}
            )
            remaining -= len(tail_event_ids)

        return selected_event_ids, effective_owner_by_event_id

    @staticmethod
    def _claim_count_for_tail_group(
        grouped_buckets: list[_OwnerBucket],
        *,
        remaining: int,
        now: float,
    ) -> int:
        pending_count = sum(bucket.pending_count for bucket in grouped_buckets)
        max_events = min(max(1, bucket.max_events) for bucket in grouped_buckets)
        oldest_created_at = min(bucket.oldest_created_at for bucket in grouped_buckets)
        oldest_age_seconds = max(0.0, now - oldest_created_at)
        max_wait_candidates = [
            bucket.max_wait_seconds
            for bucket in grouped_buckets
            if bucket.max_wait_seconds is not None
        ]
        effective_wait_seconds = min(max_wait_candidates) if max_wait_candidates else None
        tail_policy = BatchingPolicy(
            max_events=max_events,
            max_estimated_tokens=10**9,
            max_wait_seconds=float(effective_wait_seconds or 0.0),
            min_ready_events=max_events,
        )
        tail_state = BucketState(
            event_count=pending_count,
            estimated_tokens=0,
            oldest_age_seconds=oldest_age_seconds,
        )
        tail_flush = decide_flush(
            tail_state,
            tail_policy,
            batching_enabled=effective_wait_seconds is not None,
        )
        return _tail_claim_count(
            pending_count=pending_count,
            max_events=max_events,
            remaining=remaining,
            flush_reason=tail_flush,
        )

    @staticmethod
    async def _select_event_ids_for_owner_group(
        db: aiosqlite.Connection,
        *,
        owner_names: list[str],
        limit: int,
    ) -> list[str]:
        placeholders = ", ".join("?" for _ in owner_names)
        async with db.execute(
            f"""
            SELECT event_id
            FROM l2_projection_jobs
            WHERE status = 'pending'
              AND batch_owner IN ({placeholders})
            ORDER BY created_at ASC
            LIMIT ?
            """,
            (*owner_names, limit),
        ) as cursor:
            event_rows = await cursor.fetchall()
        return [str(row["event_id"]) for row in event_rows]

    @staticmethod
    async def _claim_selected_rows(
        db: aiosqlite.Connection,
        *,
        consumer_name: str,
        now: float,
        selected_event_ids: list[str],
    ) -> list[aiosqlite.Row]:
        placeholders = ", ".join("?" for _ in selected_event_ids)
        await db.execute(
            f"""
            UPDATE l2_projection_jobs
            SET status = 'queued',
                claimed_by = ?,
                claimed_at = ?,
                started_at = NULL,
                updated_at = ?
            WHERE event_id IN ({placeholders})
            """,
            (consumer_name, now, now, *selected_event_ids),
        )
        async with db.execute(
            f"""
            SELECT *
            FROM l2_projection_jobs
            WHERE event_id IN ({placeholders})
            """,
            tuple(selected_event_ids),
        ) as cursor:
            claimed_rows = cast(list[aiosqlite.Row], await cursor.fetchall())
        await db.commit()
        return claimed_rows

    @staticmethod
    def _serialize_claimed_rows(
        *,
        host: _ProjectionQueueClaimingHostProtocol,
        claimed_rows: list[aiosqlite.Row],
        selected_event_ids: list[str],
        effective_owner_by_event_id: dict[str, str],
        requested_limit: int,
    ) -> list[Dict[str, Any]]:
        order = {event_id: index for index, event_id in enumerate(selected_event_ids)}
        claimed_dicts = [host._row_to_dict(row) for row in claimed_rows]
        for item in claimed_dicts:
            event_id = str(item.get("event_id") or "")
            effective_owner = effective_owner_by_event_id.get(event_id)
            if effective_owner:
                item["effective_batch_owner"] = effective_owner
        claimed_dicts.sort(
            key=lambda item: order.get(str(item.get("event_id") or ""), requested_limit)
        )
        return claimed_dicts

    def _claiming_host(self) -> _ProjectionQueueClaimingHostProtocol:
        return cast(_ProjectionQueueClaimingHostProtocol, self)


__all__ = ["ProjectionQueueClaimingMixin"]
