"""Persistence for resumable forget operations."""

from __future__ import annotations

import json
import time
import uuid
from collections.abc import Iterable

from ...core.sqlite import sqlite_connection_async
from ..source_event_governance import normalize_source_event_ids, tombstone_source_event_ids
from .models import ForgetOperation, ForgetReference, ForgetSelector, SelectedEvent

# The desktop runtime admits one backend process.  This process-local registry
# closes the smaller in-process race created by tests, re-initialization, or an
# accidentally duplicated store: startup recovery may reclaim a lease left by
# a dead process, but must not steal one whose runner is still executing here.
_LIVE_LEASE_OWNERS: set[str] = set()


class ForgetOperationRepository:
    """Store operation checkpoints independently from layer cleanup code."""

    def __init__(self, db_path: str) -> None:
        self._db_path = db_path
        self._claims: dict[str, tuple[str, int]] = {}
        self._locally_completed: set[str] = set()

    @staticmethod
    def register_live_owner(owner: str) -> None:
        """Mark one process-local runner as actively executing claimed work."""
        normalized = str(owner or "").strip()
        if not normalized:
            raise ValueError("Forget operation lease owner must not be empty")
        _LIVE_LEASE_OWNERS.add(normalized)

    @staticmethod
    def unregister_live_owner(owner: str) -> None:
        """Release one process-local runner execution marker."""
        _LIVE_LEASE_OWNERS.discard(str(owner or "").strip())

    async def create_or_reuse(
        self,
        *,
        selector: ForgetSelector,
        reason: str,
        reuse_completed: bool,
    ) -> ForgetOperation:
        normalized_reason = str(reason or "").strip()
        if not normalized_reason:
            raise ValueError("Forget reason must not be empty")
        now = time.time()
        async with sqlite_connection_async(self._db_path) as db:
            await db.execute("BEGIN IMMEDIATE")
            try:
                row = await self._find_selector_row(
                    db,
                    selector=selector,
                    completed=False,
                )
                if row is None and reuse_completed:
                    row = await self._find_selector_row(
                        db,
                        selector=selector,
                        completed=True,
                    )
                if row is None:
                    operation_id = f"forget:{uuid.uuid4().hex}"
                    await db.execute(
                        """
                        INSERT INTO memory_forget_operations(
                            operation_id, selector_kind, selector_hash,
                            selector_json, reason, created_at, updated_at
                        ) VALUES (?, ?, ?, ?, ?, ?, ?)
                        """,
                        (
                            operation_id,
                            selector.kind,
                            selector.selector_hash,
                            selector.canonical_json,
                            normalized_reason,
                            now,
                            now,
                        ),
                    )
                    row = await self._get_row(db, operation_id)
                await db.commit()
            except BaseException:
                await db.rollback()
                raise
        if row is None:
            raise RuntimeError("Forget operation could not be created")
        return self._decode_operation(row)

    async def get(self, operation_id: str) -> ForgetOperation | None:
        async with sqlite_connection_async(self._db_path) as db:
            row = await self._get_row(db, operation_id)
        return self._decode_operation(row) if row is not None else None

    async def has_completed_selector(self, selector: ForgetSelector) -> bool:
        async with sqlite_connection_async(self._db_path) as db:
            row = await self._find_selector_row(db, selector=selector, completed=True)
        return row is not None

    async def claim(
        self,
        operation_id: str,
        *,
        owner: str,
        lease_seconds: float,
        force: bool,
    ) -> ForgetOperation | None:
        now = time.time()
        expires_at = now + max(float(lease_seconds), 1.0)
        async with sqlite_connection_async(self._db_path) as db:
            await db.execute("BEGIN IMMEDIATE")
            try:
                row = await self._get_row(db, operation_id)
                if row is None or str(row["status"]) == "completed":
                    await db.commit()
                    return self._decode_operation(row) if row is not None else None
                lease_owner = str(row["lease_owner"] or "")
                lease_expires_at = float(row["lease_expires_at"] or 0.0)
                force_reclaimable = bool(force and lease_owner not in _LIVE_LEASE_OWNERS)
                claimable = (
                    str(row["status"]) in {"pending", "failed"}
                    or lease_owner == owner
                    or lease_expires_at <= now
                    or force_reclaimable
                )
                if not claimable:
                    await db.commit()
                    return None
                await db.execute(
                    """
                    UPDATE memory_forget_operations
                    SET status = 'running', lease_owner = ?, lease_expires_at = ?,
                        attempt_count = attempt_count + 1,
                        lease_token = lease_token + 1, last_error = NULL,
                        updated_at = ?
                    WHERE operation_id = ?
                    """,
                    (owner, expires_at, now, operation_id),
                )
                row = await self._get_row(db, operation_id)
                await db.commit()
            except BaseException:
                await db.rollback()
                raise
        operation = self._decode_operation(row) if row is not None else None
        if operation is not None and not operation.completed:
            self._claims[operation_id] = (owner, operation.lease_token)
        return operation

    async def list_recoverable(
        self,
        *,
        force: bool,
        limit: int = 100,
        after_created_at: float | None = None,
        after_operation_id: str | None = None,
    ) -> list[ForgetOperation]:
        now = time.time()
        page_size = max(1, min(int(limit), 1000))
        condition = "status != 'completed'"
        args: list[object] = []
        if not force:
            condition = """
                status IN ('pending', 'failed')
                OR (status = 'running' AND COALESCE(lease_expires_at, 0) <= ?)
            """
            args.append(now)
        if after_created_at is not None and after_operation_id is not None:
            condition = f"""({condition}) AND (
                created_at > ? OR (created_at = ? AND operation_id > ?)
            )"""
            args.extend(
                (
                    float(after_created_at),
                    float(after_created_at),
                    str(after_operation_id),
                )
            )
        args.append(page_size)
        async with sqlite_connection_async(self._db_path) as db:
            async with db.execute(
                f"""
                SELECT *
                FROM memory_forget_operations
                WHERE {condition}
                ORDER BY created_at, operation_id
                LIMIT ?
                """,
                tuple(args),
            ) as cursor:
                rows = await cursor.fetchall()
        return [self._decode_operation(row) for row in rows]

    async def list_pending_surface_finalizations(
        self,
        *,
        limit: int = 1000,
    ) -> list[ForgetOperation]:
        """List completed chat operations whose user-facing surface is unfinished."""
        page_size = max(1, min(int(limit), 1000))
        async with sqlite_connection_async(self._db_path) as db:
            async with db.execute(
                """
                SELECT *
                FROM memory_forget_operations
                WHERE status = 'completed'
                  AND surface_finalized_at IS NULL
                  AND selector_kind IN (
                      'chat_session', 'chat_history', 'chat_message'
                  )
                ORDER BY completed_at, operation_id
                LIMIT ?
                """,
                (page_size,),
            ) as cursor:
                rows = await cursor.fetchall()
        return [self._decode_operation(row) for row in rows]

    async def mark_surface_finalized(self, operation_id: str) -> ForgetOperation:
        """Persist successful chat-surface cleanup after memory forgetting."""
        now = time.time()
        async with sqlite_connection_async(self._db_path) as db:
            await db.execute("BEGIN IMMEDIATE")
            try:
                row = await self._get_row(db, operation_id)
                if row is None:
                    raise RuntimeError("Forget operation does not exist")
                if str(row["status"]) != "completed":
                    raise RuntimeError(
                        "Chat surface cannot be finalized before memory forgetting completes"
                    )
                if str(row["selector_kind"]) not in {
                    "chat_session",
                    "chat_history",
                    "chat_message",
                }:
                    raise RuntimeError("Only chat forget operations have a user-facing surface")
                await db.execute(
                    """
                    UPDATE memory_forget_operations
                    SET surface_finalized_at = COALESCE(surface_finalized_at, ?),
                        updated_at = ?
                    WHERE operation_id = ?
                    """,
                    (now, now, operation_id),
                )
                row = await self._get_row(db, operation_id)
                await db.commit()
            except BaseException:
                await db.rollback()
                raise
        if row is None:
            raise RuntimeError("Forget operation disappeared while finalizing chat surface")
        return self._decode_operation(row)

    async def persist_selector_references(
        self,
        operation_id: str,
        *,
        references: Iterable[ForgetReference],
        reason: str,
    ) -> None:
        await self._persist_references(
            operation_id,
            references=tuple(references),
            reason=reason,
            events=(),
            cursor=None,
        )

    async def persist_time_range_barrier(self, operation: ForgetOperation) -> str | None:
        """Publish one durable range rule before enumerating existing sources."""
        if operation.selector.kind != "time_range":
            return None
        payload = operation.selector.payload
        target_id = f"time:{operation.selector.selector_hash}:{operation.operation_id}"
        now = time.time()
        async with sqlite_connection_async(self._db_path) as db:
            await db.execute("BEGIN IMMEDIATE")
            try:
                await self._assert_claim(db, operation.operation_id)
                await db.execute(
                    """
                    INSERT OR IGNORE INTO memory_time_range_forget_barriers(
                        operation_id, target_id, selector_hash, range_start, range_end,
                        delete_l1_events, reason, created_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        operation.operation_id,
                        target_id,
                        operation.selector.selector_hash,
                        float(payload["start"]),
                        float(payload["end"]),
                        int(bool(payload.get("delete_l1_events"))),
                        operation.reason,
                        now,
                    ),
                )
                async with db.execute(
                    """
                    SELECT target_id, selector_hash, range_start, range_end,
                           delete_l1_events, reason
                    FROM memory_time_range_forget_barriers
                    WHERE operation_id = ?
                    """,
                    (operation.operation_id,),
                ) as cursor:
                    row = await cursor.fetchone()
                expected = (
                    target_id,
                    operation.selector.selector_hash,
                    float(payload["start"]),
                    float(payload["end"]),
                    int(bool(payload.get("delete_l1_events"))),
                    operation.reason,
                )
                if row is None or tuple(row) != expected:
                    raise RuntimeError("Time-range forget barrier does not match its operation")
                await db.commit()
            except BaseException:
                await db.rollback()
                raise
        return target_id

    async def persist_event_page(
        self,
        operation_id: str,
        *,
        events: Iterable[SelectedEvent],
        references: Iterable[ForgetReference],
        reason: str,
        cursor: str,
    ) -> int:
        selected = tuple(events)
        if not selected:
            return 0
        return await self._persist_references(
            operation_id,
            references=tuple(references),
            reason=reason,
            events=selected,
            cursor=str(cursor),
        )

    async def _persist_references(
        self,
        operation_id: str,
        *,
        references: tuple[ForgetReference, ...],
        reason: str,
        events: tuple[SelectedEvent, ...],
        cursor: str | None,
    ) -> int:
        now = time.time()
        barrier_values = normalize_source_event_ids(
            reference.value for reference in references if reference.role == "barrier"
        )
        async with sqlite_connection_async(self._db_path) as db:
            await db.execute("BEGIN IMMEDIATE")
            try:
                await self._assert_claim(db, operation_id)
                existing_event_ids: set[str] = set()
                if events:
                    candidate_ids = tuple(event.event_id for event in events)
                    placeholders = ", ".join("?" for _ in candidate_ids)
                    async with db.execute(
                        f"""
                        SELECT event_id
                        FROM memory_forget_operation_events
                        WHERE operation_id = ? AND event_id IN ({placeholders})
                        """,
                        (operation_id, *candidate_ids),
                    ) as existing_cursor:
                        existing_event_ids = {
                            str(row[0]) for row in await existing_cursor.fetchall()
                        }
                before_events = db.total_changes
                if events:
                    await db.executemany(
                        """
                        INSERT OR IGNORE INTO memory_forget_operation_events(
                            operation_id, event_id, was_active, created_at, updated_at
                        ) VALUES (?, ?, ?, ?, ?)
                        """,
                        [
                            (
                                operation_id,
                                event.event_id,
                                int(event.was_active),
                                now,
                                now,
                            )
                            for event in events
                        ],
                    )
                inserted_events = max(db.total_changes - before_events, 0)
                inserted_active_events = sum(
                    1
                    for event in events
                    if event.was_active and event.event_id not in existing_event_ids
                )
                if references:
                    await db.executemany(
                        """
                        INSERT OR IGNORE INTO memory_forget_operation_refs(
                            operation_id, item_event_id, ref_role, ref_type,
                            source_ref, created_at
                        ) VALUES (?, ?, ?, ?, ?, ?)
                        """,
                        [
                            (
                                operation_id,
                                reference.item_event_id,
                                reference.role,
                                reference.ref_type,
                                reference.value,
                                now,
                            )
                            for reference in references
                        ],
                    )
                await tombstone_source_event_ids(
                    db,
                    event_ids=barrier_values,
                    reason=reason,
                    created_at=now,
                )
                if cursor is not None:
                    await db.execute(
                        """
                        UPDATE memory_forget_operations
                        SET cursor = ?, total_event_count = total_event_count + ?,
                            active_event_count = active_event_count + ?,
                            updated_at = ?
                        WHERE operation_id = ?
                        """,
                        (
                            cursor,
                            inserted_events,
                            inserted_active_events,
                            now,
                            operation_id,
                        ),
                    )
                else:
                    await db.execute(
                        """
                        UPDATE memory_forget_operations
                        SET updated_at = ?
                        WHERE operation_id = ?
                        """,
                        (now, operation_id),
                    )
                await db.commit()
            except BaseException:
                await db.rollback()
                raise
        return inserted_events

    async def persist_projection_block_page(
        self,
        operation_id: str,
        *,
        block_kind: str,
        target_id: str,
        event_ids: Iterable[str],
        cursor: str,
    ) -> None:
        normalized = normalize_source_event_ids(event_ids)
        if not normalized:
            return
        now = time.time()
        async with sqlite_connection_async(self._db_path) as db:
            await db.execute("BEGIN IMMEDIATE")
            try:
                await self._assert_claim(db, operation_id)
                await db.executemany(
                    """
                    INSERT OR IGNORE INTO memory_projection_blocks(
                        block_kind, target_id, event_id, operation_id, created_at
                    ) VALUES (?, ?, ?, ?, ?)
                    """,
                    [
                        (block_kind, target_id, event_id, operation_id, now)
                        for event_id in normalized
                    ],
                )
                if block_kind in {
                    "entity_projection",
                    "entity_projection_candidate",
                }:
                    await self._persist_entity_projection_identities(
                        db,
                        operation_id=operation_id,
                        target_id=target_id,
                        event_ids=normalized,
                        created_at=now,
                    )
                await db.execute(
                    """
                    UPDATE memory_forget_operations
                    SET projection_cursor = ?, updated_at = ?
                    WHERE operation_id = ?
                    """,
                    (str(cursor), now, operation_id),
                )
                await db.commit()
            except BaseException:
                await db.rollback()
                raise

    @staticmethod
    async def _persist_entity_projection_identities(
        db: object,
        *,
        operation_id: str,
        target_id: str,
        event_ids: tuple[str, ...],
        created_at: float,
    ) -> None:
        event_json = json.dumps(event_ids, ensure_ascii=False, separators=(",", ":"))
        async with db.execute(  # type: ignore[attr-defined]
            """
            SELECT surface, entity_type FROM (
                SELECT catalog.canonical_name AS surface,
                       catalog.entity_type AS entity_type
                FROM entity_catalog AS catalog
                WHERE catalog.entity_id = ?
                UNION
                SELECT alias.normalized_alias, catalog.entity_type
                FROM entity_aliases AS alias
                JOIN entity_catalog AS catalog ON catalog.entity_id = alias.entity_id
                WHERE alias.entity_id = ?
                UNION
                SELECT name.normalized_name, catalog.entity_type
                FROM entity_name_evidence AS name
                LEFT JOIN entity_catalog AS catalog ON catalog.entity_id = name.entity_id
                WHERE name.entity_id = ?
                  AND name.event_id IN (
                      SELECT CAST(value AS TEXT) FROM json_each(?)
                  )
                UNION
                SELECT mention.normalized_surface, mention.entity_type
                FROM entity_mentions AS mention
                WHERE mention.resolved_entity_id = ?
                  AND EXISTS (
                      SELECT 1
                      FROM json_each(CASE
                          WHEN json_valid(mention.evidence_event_ids)
                              THEN mention.evidence_event_ids ELSE '[]'
                      END) AS evidence
                      WHERE CAST(evidence.value AS TEXT) IN (
                          SELECT CAST(value AS TEXT) FROM json_each(?)
                      )
                  )
            )
            """,
            (target_id, target_id, target_id, event_json, target_id, event_json),
        ) as cursor:
            rows = await cursor.fetchall()
        identities = {
            (str(row[0] or "").strip().casefold(), str(row[1] or "").strip())
            for row in rows
            if str(row[0] or "").strip()
        }
        if not identities:
            return
        await db.executemany(  # type: ignore[attr-defined]
            """
            INSERT OR IGNORE INTO memory_entity_projection_identity_blocks(
                target_id, event_id, normalized_surface, entity_type,
                operation_id, created_at
            ) VALUES (?, ?, ?, ?, ?, ?)
            """,
            [
                (
                    target_id,
                    event_id,
                    normalized_surface,
                    entity_type,
                    operation_id,
                    created_at,
                )
                for event_id in event_ids
                for normalized_surface, entity_type in identities
            ],
        )

    async def finish_projection_selection(self, operation_id: str) -> None:
        await self._update_operation(
            operation_id,
            "projection_selection_complete = 1, updated_at = ?",
        )

    async def promote_entity_projection_candidates(
        self,
        operation_id: str,
        *,
        target_id: str,
        event_ids: Iterable[str],
    ) -> int:
        """Upgrade old job events only after they prove target-entity lineage."""
        normalized = normalize_source_event_ids(event_ids)
        normalized_target = str(target_id or "").strip()
        if not normalized or not normalized_target:
            return 0
        event_json = json.dumps(normalized, ensure_ascii=False, separators=(",", ":"))
        now = time.time()
        async with sqlite_connection_async(self._db_path) as db:
            await db.execute("BEGIN IMMEDIATE")
            try:
                await self._assert_claim(db, operation_id)
                async with db.execute(
                    """
                    SELECT event_id
                    FROM (
                        SELECT candidate.event_id
                        FROM memory_projection_blocks AS candidate
                        WHERE candidate.block_kind = 'entity_projection_candidate'
                          AND candidate.target_id = ?
                          AND candidate.event_id IN (
                              SELECT CAST(value AS TEXT) FROM json_each(?)
                          )
                        UNION
                        SELECT jobs.event_id
                        FROM l2_projection_jobs AS jobs
                        JOIN memory_forget_operations AS operation
                          ON operation.operation_id = ?
                        WHERE jobs.created_at <= operation.created_at
                          AND jobs.event_id IN (
                              SELECT CAST(value AS TEXT) FROM json_each(?)
                          )
                    )
                    ORDER BY event_id
                    """,
                    (
                        normalized_target,
                        event_json,
                        operation_id,
                        event_json,
                    ),
                ) as cursor:
                    promoted_event_ids = normalize_source_event_ids(
                        str(row[0]) for row in await cursor.fetchall()
                    )
                if not promoted_event_ids:
                    await db.commit()
                    return 0
                before = db.total_changes
                await db.executemany(
                    """
                    INSERT OR IGNORE INTO memory_projection_blocks(
                        block_kind, target_id, event_id, operation_id, created_at
                    ) VALUES ('entity_projection', ?, ?, ?, ?)
                    """,
                    [
                        (
                            normalized_target,
                            event_id,
                            operation_id,
                            now,
                        )
                        for event_id in promoted_event_ids
                    ],
                )
                inserted = max(db.total_changes - before, 0)
                await self._persist_entity_projection_identities(
                    db,
                    operation_id=operation_id,
                    target_id=normalized_target,
                    event_ids=promoted_event_ids,
                    created_at=now,
                )
                await db.commit()
                return inserted
            except BaseException:
                await db.rollback()
                raise

    async def finish_selection(self, operation_id: str) -> None:
        await self._update_operation(
            operation_id,
            """
            selection_complete = 1, phase = 'target_cleanup', updated_at = ?
            """,
        )

    async def list_event_ids(
        self,
        operation_id: str,
        *,
        after_event_id: str = "",
        limit: int = 500,
    ) -> list[str]:
        page_size = max(1, min(int(limit), 1000))
        async with sqlite_connection_async(self._db_path) as db:
            async with db.execute(
                """
                SELECT event_id
                FROM memory_forget_operation_events
                WHERE operation_id = ? AND event_id > ?
                ORDER BY event_id
                LIMIT ?
                """,
                (operation_id, str(after_event_id), page_size),
            ) as cursor:
                return [str(row[0]) for row in await cursor.fetchall()]

    async def list_time_range_projection_event_ids(
        self,
        operation_id: str,
        *,
        after_event_id: str = "",
        limit: int = 100,
    ) -> tuple[str, ...]:
        """Return one stable page of source events governed by a time range."""
        page_size = max(1, min(int(limit), 500))
        async with sqlite_connection_async(self._db_path) as db:
            async with db.execute(
                """
                SELECT DISTINCT event_id
                FROM memory_projection_blocks
                WHERE operation_id = ?
                  AND block_kind = 'episode_formation'
                  AND target_id LIKE 'time:%'
                  AND event_id > ?
                ORDER BY event_id
                LIMIT ?
                """,
                (operation_id, str(after_event_id), page_size),
            ) as cursor:
                return normalize_source_event_ids(str(row[0]) for row in await cursor.fetchall())

    async def list_audit_event_ids(
        self,
        operation_id: str,
        *,
        after_event_id: str = "",
        limit: int = 500,
    ) -> list[str]:
        page_size = max(1, min(int(limit), 1000))
        async with sqlite_connection_async(self._db_path) as db:
            async with db.execute(
                """
                SELECT DISTINCT source_ref
                FROM memory_forget_operation_refs
                WHERE operation_id = ? AND ref_type = 'audit_event'
                  AND source_ref > ?
                ORDER BY source_ref
                LIMIT ?
                """,
                (operation_id, str(after_event_id), page_size),
            ) as cursor:
                return [str(row[0]) for row in await cursor.fetchall()]

    async def list_pending_event_ids(
        self,
        operation_id: str,
        *,
        limit: int = 100,
    ) -> list[str]:
        page_size = max(1, min(int(limit), 500))
        async with sqlite_connection_async(self._db_path) as db:
            async with db.execute(
                """
                SELECT event_id
                FROM memory_forget_operation_events
                WHERE operation_id = ? AND cleanup_status = 'pending'
                ORDER BY event_id
                LIMIT ?
                """,
                (operation_id, page_size),
            ) as cursor:
                return [str(row[0]) for row in await cursor.fetchall()]

    async def cleanup_references_for_events(
        self,
        operation_id: str,
        event_ids: Iterable[str],
    ) -> tuple[str, ...]:
        normalized = normalize_source_event_ids(event_ids)
        if not normalized:
            return ()
        placeholders = ", ".join("?" for _ in normalized)
        async with sqlite_connection_async(self._db_path) as db:
            async with db.execute(
                f"""
                SELECT DISTINCT source_ref
                FROM memory_forget_operation_refs
                WHERE operation_id = ? AND ref_role = 'cleanup'
                  AND item_event_id IN ({placeholders})
                ORDER BY source_ref
                """,
                (operation_id, *normalized),
            ) as cursor:
                rows = await cursor.fetchall()
        return normalize_source_event_ids(str(row[0]) for row in rows)

    async def selector_cleanup_references(self, operation_id: str) -> tuple[str, ...]:
        async with sqlite_connection_async(self._db_path) as db:
            async with db.execute(
                """
                SELECT DISTINCT source_ref
                FROM memory_forget_operation_refs
                WHERE operation_id = ? AND item_event_id = ''
                  AND ref_role = 'cleanup'
                ORDER BY source_ref
                """,
                (operation_id,),
            ) as cursor:
                rows = await cursor.fetchall()
        return normalize_source_event_ids(str(row[0]) for row in rows)

    async def target_references(
        self,
        operation_id: str,
        *,
        ref_type: str,
        item_event_id: str | None = None,
    ) -> tuple[str, ...]:
        item_clause = ""
        args: tuple[object, ...] = (operation_id, ref_type)
        if item_event_id is not None:
            item_clause = " AND item_event_id = ?"
            args = (*args, str(item_event_id))
        async with sqlite_connection_async(self._db_path) as db:
            async with db.execute(
                f"""
                SELECT DISTINCT source_ref
                FROM memory_forget_operation_refs
                WHERE operation_id = ? AND ref_role = 'target'
                  AND ref_type = ?
                  {item_clause}
                ORDER BY source_ref
                """,
                args,
            ) as cursor:
                rows = await cursor.fetchall()
        return normalize_source_event_ids(str(row[0]) for row in rows)

    async def mark_events_cleaned(
        self,
        operation_id: str,
        event_ids: Iterable[str],
    ) -> int:
        normalized = normalize_source_event_ids(event_ids)
        if not normalized:
            return 0
        placeholders = ", ".join("?" for _ in normalized)
        now = time.time()
        async with sqlite_connection_async(self._db_path) as db:
            await db.execute("BEGIN IMMEDIATE")
            try:
                await self._assert_claim(db, operation_id)
                cursor = await db.execute(
                    f"""
                    UPDATE memory_forget_operation_events
                    SET cleanup_status = 'completed', updated_at = ?
                    WHERE operation_id = ? AND cleanup_status = 'pending'
                      AND event_id IN ({placeholders})
                    """,
                    (now, operation_id, *normalized),
                )
                changed = max(int(cursor.rowcount), 0)
                await db.execute(
                    """
                    UPDATE memory_forget_operations
                    SET cleaned_event_count = cleaned_event_count + ?, updated_at = ?
                    WHERE operation_id = ?
                    """,
                    (changed, now, operation_id),
                )
                await db.commit()
            except BaseException:
                await db.rollback()
                raise
        return changed

    async def finish_target_cleanup(
        self,
        operation_id: str,
        *,
        result: dict[str, object],
    ) -> None:
        now = time.time()
        encoded = json.dumps(result, ensure_ascii=False, separators=(",", ":"), sort_keys=True)
        async with sqlite_connection_async(self._db_path) as db:
            await db.execute("BEGIN IMMEDIATE")
            try:
                await self._assert_claim(db, operation_id)
                await db.execute(
                    """
                    UPDATE memory_forget_operations
                    SET result_json = ?, phase = 'source_cleanup', updated_at = ?
                    WHERE operation_id = ?
                    """,
                    (encoded, now, operation_id),
                )
                await db.commit()
            except BaseException:
                await db.rollback()
                raise

    async def mark_selector_cleanup_complete(self, operation_id: str) -> None:
        await self._update_operation(
            operation_id,
            "selector_cleanup_complete = 1, updated_at = ?",
        )

    async def mark_failed(self, operation_id: str, *, error: BaseException) -> None:
        message = f"{type(error).__name__}: {error}"[:4000]
        now = time.time()
        async with sqlite_connection_async(self._db_path) as db:
            await db.execute("BEGIN IMMEDIATE")
            try:
                await self._assert_claim(db, operation_id)
                await db.execute(
                    """
                    UPDATE memory_forget_operations
                    SET status = 'failed', lease_owner = NULL, lease_expires_at = NULL,
                        last_error = ?, updated_at = ?
                    WHERE operation_id = ? AND status != 'completed'
                    """,
                    (message, now, operation_id),
                )
                await db.commit()
            except BaseException:
                await db.rollback()
                raise
        self._claims.pop(operation_id, None)

    async def mark_completed(self, operation_id: str) -> ForgetOperation:
        now = time.time()
        row = None
        async with sqlite_connection_async(self._db_path) as db:
            await db.execute("BEGIN IMMEDIATE")
            try:
                await self._assert_claim(db, operation_id)
                async with db.execute(
                    """
                    SELECT selector_kind,
                           EXISTS (
                               SELECT 1
                               FROM memory_time_range_forget_barriers AS barrier
                               WHERE barrier.operation_id =
                                     memory_forget_operations.operation_id
                           )
                    FROM memory_forget_operations
                    WHERE operation_id = ?
                    """,
                    (operation_id,),
                ) as cursor:
                    completion_row = await cursor.fetchone()
                if completion_row is None:
                    raise RuntimeError("Forget operation disappeared while completing")
                if str(completion_row[0]) == "time_range" and not bool(completion_row[1]):
                    raise RuntimeError(
                        "Time-range forget operation cannot complete without a durable barrier"
                    )
                await db.execute(
                    """
                    UPDATE memory_forget_operations
                    SET status = 'completed', phase = 'completed',
                        projection_selection_complete = 1,
                        selection_complete = 1, selector_cleanup_complete = 1,
                        lease_owner = NULL, lease_expires_at = NULL,
                        last_error = NULL, updated_at = ?, completed_at = ?
                    WHERE operation_id = ?
                    """,
                    (now, now, operation_id),
                )
                row = await self._get_row(db, operation_id)
                await db.commit()
                self._locally_completed.add(operation_id)
            except BaseException:
                await db.rollback()
                raise
        if row is None:
            raise RuntimeError("Forget operation disappeared while completing")
        return self._decode_operation(row)

    async def _update_operation(
        self,
        operation_id: str,
        assignments: str,
    ) -> None:
        now = time.time()
        async with sqlite_connection_async(self._db_path) as db:
            await db.execute("BEGIN IMMEDIATE")
            try:
                await self._assert_claim(db, operation_id)
                await db.execute(
                    f"""
                    UPDATE memory_forget_operations
                    SET {assignments}
                    WHERE operation_id = ?
                    """,
                    (now, operation_id),
                )
                await db.commit()
            except BaseException:
                await db.rollback()
                raise

    async def renew_claim(self, operation_id: str, *, lease_seconds: float) -> bool:
        if operation_id in self._locally_completed:
            return False
        owner, token = self._required_claim(operation_id)
        expires_at = time.time() + max(float(lease_seconds), 1.0)
        async with sqlite_connection_async(self._db_path) as db:
            cursor = await db.execute(
                """
                UPDATE memory_forget_operations
                SET lease_expires_at = ?, updated_at = ?
                WHERE operation_id = ? AND status = 'running'
                  AND lease_owner = ? AND lease_token = ?
                """,
                (expires_at, time.time(), operation_id, owner, token),
            )
            await db.commit()
        if int(cursor.rowcount or 0) != 1:
            if operation_id in self._locally_completed:
                return False
            raise RuntimeError("Forget operation lease was lost")
        return True

    def release_local_claim(self, operation_id: str) -> None:
        """Drop process-local lease state after the runner has fully stopped."""
        self._claims.pop(operation_id, None)
        self._locally_completed.discard(operation_id)

    def _required_claim(self, operation_id: str) -> tuple[str, int]:
        claim = self._claims.get(operation_id)
        if claim is None:
            raise RuntimeError("Forget operation is not claimed by this runner")
        return claim

    async def _assert_claim(self, db: object, operation_id: str) -> None:
        owner, token = self._required_claim(operation_id)
        async with db.execute(  # type: ignore[attr-defined]
            """
            SELECT 1
            FROM memory_forget_operations
            WHERE operation_id = ? AND status = 'running'
              AND lease_owner = ? AND lease_token = ?
            """,
            (operation_id, owner, token),
        ) as cursor:
            if await cursor.fetchone() is None:
                raise RuntimeError("Forget operation lease was lost")

    @staticmethod
    async def _get_row(db: object, operation_id: str):
        async with db.execute(  # type: ignore[attr-defined]
            "SELECT * FROM memory_forget_operations WHERE operation_id = ?",
            (operation_id,),
        ) as cursor:
            return await cursor.fetchone()

    @staticmethod
    async def _find_selector_row(
        db: object,
        *,
        selector: ForgetSelector,
        completed: bool,
    ):
        status_condition = "status = 'completed'" if completed else "status != 'completed'"
        order = "ORDER BY completed_at DESC, created_at DESC" if completed else ""
        async with db.execute(  # type: ignore[attr-defined]
            f"""
            SELECT *
            FROM memory_forget_operations
            WHERE selector_kind = ? AND selector_hash = ? AND {status_condition}
            {order}
            LIMIT 1
            """,
            (selector.kind, selector.selector_hash),
        ) as cursor:
            return await cursor.fetchone()

    @staticmethod
    def _decode_operation(row: object) -> ForgetOperation:
        selector = ForgetSelector.from_json(
            kind=str(row["selector_kind"]),  # type: ignore[index]
            selector_json=str(row["selector_json"]),  # type: ignore[index]
        )
        raw_result = json.loads(str(row["result_json"]))  # type: ignore[index]
        result = raw_result if isinstance(raw_result, dict) else {}
        return ForgetOperation(
            operation_id=str(row["operation_id"]),  # type: ignore[index]
            selector=selector,
            reason=str(row["reason"]),  # type: ignore[index]
            status=str(row["status"]),  # type: ignore[index]
            phase=str(row["phase"]),  # type: ignore[index]
            projection_cursor=str(row["projection_cursor"] or ""),  # type: ignore[index]
            projection_selection_complete=bool(  # type: ignore[index]
                row["projection_selection_complete"]
            ),
            cursor=str(row["cursor"] or ""),  # type: ignore[index]
            selection_complete=bool(row["selection_complete"]),  # type: ignore[index]
            selector_cleanup_complete=bool(row["selector_cleanup_complete"]),  # type: ignore[index]
            total_event_count=int(row["total_event_count"]),  # type: ignore[index]
            active_event_count=int(row["active_event_count"]),  # type: ignore[index]
            cleaned_event_count=int(row["cleaned_event_count"]),  # type: ignore[index]
            attempt_count=int(row["attempt_count"]),  # type: ignore[index]
            lease_token=int(row["lease_token"]),  # type: ignore[index]
            created_at=float(row["created_at"]),  # type: ignore[index]
            surface_finalized_at=(
                float(row["surface_finalized_at"])  # type: ignore[index]
                if row["surface_finalized_at"] is not None  # type: ignore[index]
                else None
            ),
            result=result,
            last_error=(
                str(row["last_error"]) if row["last_error"] is not None else None  # type: ignore[index]
            ),
        )


__all__ = ["ForgetOperationRepository"]
