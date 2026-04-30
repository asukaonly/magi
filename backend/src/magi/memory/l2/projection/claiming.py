"""Claim selection helpers for the L2 projection queue."""

from __future__ import annotations

import time
from typing import Any, Dict, Protocol, cast

import aiosqlite

from ....core.sqlite import sqlite_connection_async


class _ProjectionQueueClaimingHostProtocol(Protocol):
    db_path: str

    async def _count_by_status(self, db: aiosqlite.Connection, status: str) -> int: ...

    def _row_to_dict(self, row: aiosqlite.Row) -> Dict[str, Any]: ...


def _projection_queue_module() -> Any:
    from . import queue as projection_queue_module

    return projection_queue_module


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
        selected_event_ids: list[str] = []
        effective_owner_by_event_id: dict[str, str] = {}
        claimed_rows: list[aiosqlite.Row] = []

        async with sqlite_connection_async(host.db_path) as db:
            db.row_factory = aiosqlite.Row
            remaining = requested_limit
            pending_total = await host._count_by_status(db, "pending")
            claim_mode = (
                "catch_up"
                if pending_total >= projection_queue_module.DEFAULT_L2_CATCH_UP_PENDING_THRESHOLD
                else "steady_state"
            )

            async with db.execute(
                """
                SELECT event_id
                FROM l2_projection_jobs
                WHERE status = 'pending'
                  AND (batch_owner IS NULL OR batch_owner = '')
                ORDER BY created_at ASC
                LIMIT ?
                """,
                (remaining,),
            ) as cursor:
                rows = await cursor.fetchall()
            selected_event_ids.extend(str(row["event_id"]) for row in rows)
            remaining -= len(rows)

            if remaining > 0:
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

                low_frequency_owners_by_tail: dict[str, list[aiosqlite.Row]] = {}
                for owner_row in owner_rows:
                    if remaining <= 0:
                        break
                    owner = str(owner_row["batch_owner"] or "").strip()
                    if not owner:
                        continue
                    pending_count = int(owner_row["pending_count"] or 0)
                    if pending_count <= 0:
                        continue
                    max_events_value = owner_row["bucket_max_events"]
                    max_events = int(max_events_value or 1)
                    min_ready_value = owner_row["bucket_min_ready_events"]
                    min_ready_events = int(min_ready_value or max_events)
                    max_wait_value = owner_row["bucket_max_wait_seconds"]
                    catch_up_owner = str(owner_row["bucket_catch_up_owner"] or "").strip()
                    oldest_created_at = float(owner_row["oldest_created_at"] or now)
                    oldest_age_seconds = max(0.0, now - oldest_created_at)

                    effective_ready_events = max_events
                    effective_wait_seconds = (
                        float(max_wait_value) if max_wait_value is not None else None
                    )
                    if claim_mode != "catch_up":
                        effective_ready_events = max(1, min(min_ready_events, max_events))
                        if effective_wait_seconds is not None:
                            effective_wait_seconds = min(
                                effective_wait_seconds,
                                projection_queue_module.DEFAULT_L2_STEADY_STATE_MAX_WAIT_SECONDS,
                            )

                    claim_count = 0
                    if pending_count >= effective_ready_events:
                        claim_count = min(
                            (pending_count // effective_ready_events) * effective_ready_events,
                            remaining,
                        )
                        claim_count -= claim_count % effective_ready_events
                    elif (
                        effective_wait_seconds is not None
                        and oldest_age_seconds >= effective_wait_seconds
                    ):
                        claim_count = min(pending_count, remaining)

                    if (
                        claim_count <= 0
                        and claim_mode == "catch_up"
                        and catch_up_owner
                        and pending_count < max_events
                    ):
                        low_frequency_owners_by_tail.setdefault(catch_up_owner, []).append(
                            owner_row
                        )
                        continue

                    if claim_count <= 0:
                        continue

                    async with db.execute(
                        """
                        SELECT event_id
                        FROM l2_projection_jobs
                        WHERE status = 'pending'
                          AND batch_owner = ?
                        ORDER BY created_at ASC
                        LIMIT ?
                        """,
                        (owner, claim_count),
                    ) as cursor:
                        event_rows = await cursor.fetchall()
                    owner_event_ids = [str(row["event_id"]) for row in event_rows]
                    selected_event_ids.extend(owner_event_ids)
                    effective_owner_by_event_id.update(
                        {event_id: owner for event_id in owner_event_ids}
                    )
                    remaining -= len(owner_event_ids)

                if claim_mode == "catch_up" and remaining > 0 and low_frequency_owners_by_tail:
                    tail_rows = sorted(
                        low_frequency_owners_by_tail.items(),
                        key=lambda item: min(
                            float(row["oldest_created_at"] or now) for row in item[1]
                        ),
                    )
                    for catch_up_owner, grouped_rows in tail_rows:
                        if remaining <= 0:
                            break
                        owner_names = [
                            str(row["batch_owner"] or "").strip() for row in grouped_rows
                        ]
                        owner_names = [owner for owner in owner_names if owner]
                        if not owner_names:
                            continue

                        pending_count = sum(int(row["pending_count"] or 0) for row in grouped_rows)
                        max_events = min(
                            max(1, int(row["bucket_max_events"] or 1)) for row in grouped_rows
                        )
                        oldest_created_at = min(
                            float(row["oldest_created_at"] or now) for row in grouped_rows
                        )
                        oldest_age_seconds = max(0.0, now - oldest_created_at)
                        max_wait_candidates = [
                            float(row["bucket_max_wait_seconds"])
                            for row in grouped_rows
                            if row["bucket_max_wait_seconds"] is not None
                        ]
                        effective_wait_seconds = (
                            min(max_wait_candidates) if max_wait_candidates else None
                        )

                        claim_count = 0
                        if pending_count >= max_events:
                            claim_count = min((pending_count // max_events) * max_events, remaining)
                            claim_count -= claim_count % max_events
                        elif (
                            effective_wait_seconds is not None
                            and oldest_age_seconds >= effective_wait_seconds
                        ):
                            claim_count = min(pending_count, remaining)

                        if claim_count <= 0:
                            continue

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
                            (*owner_names, claim_count),
                        ) as cursor:
                            event_rows = await cursor.fetchall()
                        tail_event_ids = [str(row["event_id"]) for row in event_rows]
                        if not tail_event_ids:
                            continue
                        selected_event_ids.extend(tail_event_ids)
                        effective_owner_by_event_id.update(
                            {event_id: catch_up_owner for event_id in tail_event_ids}
                        )
                        remaining -= len(tail_event_ids)

            if not selected_event_ids:
                return []

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
                claimed_rows = await cursor.fetchall()
            await db.commit()

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
