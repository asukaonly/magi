"""BatchStore — aiosqlite manifest persistence for the batch orchestrator.

Mirrors identity/bindings_store.py: one connection per call, schema built
by alembic at startup, ``initialize()`` only ensures the parent dir.
The store is task-agnostic — JSON blobs (input/result/...) are opaque.
"""
from __future__ import annotations

import json
import time
import uuid
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any, Iterable

import aiosqlite

from .contracts import (
    BatchItem,
    BatchItemStatus,
    BatchJob,
    BatchJobStatus,
    ItemOutcome,
    ReconcileReport,
    TERMINAL_ITEM_STATUSES,
)


def _now_ms() -> int:
    return int(time.time() * 1000)


def _loads(blob: str | None) -> Any:
    return json.loads(blob) if blob else None


def _normalize_result(result: Any) -> "dict[str, Any] | None":
    """Persist ``result`` as a dict so downstream readers (dedup, reporting) can
    rely on ``.get()``. The agent fills this freeform via batch_item_update and
    isn't always consistent: usually a dict, but sometimes a JSON-encoded string
    or plain text. Parse a JSON object when we got one; otherwise wrap the scalar
    so a stray string never becomes a double-encoded blob that breaks readers."""
    if result is None or isinstance(result, dict):
        return result
    if isinstance(result, str):
        try:
            parsed = json.loads(result)
        except (ValueError, TypeError):
            parsed = None
        if isinstance(parsed, dict):
            return parsed
    return {"value": result}


def _row_to_job(row: aiosqlite.Row) -> BatchJob:
    return BatchJob(
        job_id=row["job_id"],
        title=row["title"],
        owner=row["owner"],
        origin_session_id=row["origin_session_id"],
        origin_turn_id=row["origin_turn_id"],
        handler_ref=row["handler_ref"],
        handler_config=json.loads(row["handler_config"]),
        seed_spec=json.loads(row["seed_spec"]),
        status=BatchJobStatus(row["status"]),
        batch_size=row["batch_size"],
        concurrency=row["concurrency"],
        max_attempts=row["max_attempts"],
        reconcile_rounds_max=row["reconcile_rounds_max"],
        created_at_ms=row["created_at_ms"],
        updated_at_ms=row["updated_at_ms"],
    )


def _row_to_item(row: aiosqlite.Row) -> BatchItem:
    return BatchItem(
        job_id=row["job_id"],
        item_id=row["item_id"],
        input=json.loads(row["input"]),
        status=BatchItemStatus(row["status"]),
        attempts=row["attempts"],
        result=_loads(row["result"]),
        error=row["error"],
        review_reason=row["review_reason"],
        review_decision=_loads(row["review_decision"]),
        lease_owner=row["lease_owner"],
        lease_expires_at_ms=row["lease_expires_at_ms"],
        updated_at_ms=row["updated_at_ms"],
    )


class BatchStore:
    def __init__(self, *, db_path: str) -> None:
        self._db_path = str(Path(db_path).expanduser())
        self._initialized = False

    async def initialize(self) -> None:
        Path(self._db_path).parent.mkdir(parents=True, exist_ok=True)
        self._initialized = True

    @asynccontextmanager
    async def _connect(self):
        """One connection per call, configured for concurrent access: WAL journal
        so readers never block the writer (persistent once set, idempotent to
        re-assert), plus a busy_timeout so a concurrent writer waits for the lock
        instead of immediately raising 'database is locked'."""
        db = await aiosqlite.connect(self._db_path)
        try:
            await db.execute("PRAGMA journal_mode=WAL")
            await db.execute("PRAGMA busy_timeout=5000")
            yield db
        finally:
            await db.close()

    # --- jobs -------------------------------------------------------------

    async def create_job(
        self,
        *,
        title: str,
        owner: str,
        origin_session_id: str,
        origin_turn_id: str,
        handler_ref: str,
        handler_config: dict[str, Any],
        seed_spec: dict[str, Any],
        batch_size: int = 15,
        concurrency: int = 1,
        max_attempts: int = 3,
        reconcile_rounds_max: int = 2,
    ) -> BatchJob:
        now = _now_ms()
        job = BatchJob(
            job_id=uuid.uuid4().hex,
            title=title,
            owner=owner,
            origin_session_id=origin_session_id,
            origin_turn_id=origin_turn_id,
            handler_ref=handler_ref,
            handler_config=handler_config,
            seed_spec=seed_spec,
            status=BatchJobStatus.PLANNING,
            batch_size=batch_size,
            concurrency=concurrency,
            max_attempts=max_attempts,
            reconcile_rounds_max=reconcile_rounds_max,
            created_at_ms=now,
            updated_at_ms=now,
        )
        async with self._connect() as db:
            await db.execute(
                """
                INSERT INTO batch_job (
                    job_id, title, owner, origin_session_id, origin_turn_id,
                    handler_ref, handler_config, seed_spec, status, batch_size,
                    concurrency, max_attempts, reconcile_rounds_max,
                    created_at_ms, updated_at_ms
                ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                """,
                (
                    job.job_id, job.title, job.owner, job.origin_session_id,
                    job.origin_turn_id, job.handler_ref,
                    json.dumps(job.handler_config), json.dumps(job.seed_spec),
                    job.status.value, job.batch_size, job.concurrency,
                    job.max_attempts, job.reconcile_rounds_max,
                    job.created_at_ms, job.updated_at_ms,
                ),
            )
            await db.commit()
        return job

    async def get_job(self, job_id: str) -> BatchJob | None:
        async with self._connect() as db:
            db.row_factory = aiosqlite.Row
            cur = await db.execute(
                "SELECT * FROM batch_job WHERE job_id = ?", (job_id,)
            )
            row = await cur.fetchone()
            return _row_to_job(row) if row else None

    async def list_jobs_by_status(self, status: BatchJobStatus) -> "list[BatchJob]":
        """All jobs in a given status, oldest first. Used by restart-resume."""
        async with self._connect() as db:
            db.row_factory = aiosqlite.Row
            cur = await db.execute(
                "SELECT * FROM batch_job WHERE status = ? ORDER BY created_at_ms",
                (status.value,),
            )
            return [_row_to_job(r) for r in await cur.fetchall()]

    async def set_job_status(self, job_id: str, status: BatchJobStatus) -> None:
        async with self._connect() as db:
            await db.execute(
                "UPDATE batch_job SET status = ?, updated_at_ms = ? WHERE job_id = ?",
                (status.value, _now_ms(), job_id),
            )
            await db.commit()

    # --- items ------------------------------------------------------------

    async def add_items(
        self, job_id: str, inputs: "Iterable[dict[str, Any]]", *, chunk_size: int = 1000
    ) -> int:
        """Seed pending items from a (possibly lazy) iterable, committing in
        chunks so a huge seed never builds one giant transaction. Returns total."""
        now = _now_ms()
        total = 0
        chunk: list[tuple] = []

        async def _flush(db) -> None:
            nonlocal total, chunk
            if not chunk:
                return
            await db.executemany(
                """
                INSERT INTO batch_item (
                    job_id, item_id, input, status, attempts, result, error,
                    review_reason, review_decision, lease_owner,
                    lease_expires_at_ms, updated_at_ms
                ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)
                """,
                chunk,
            )
            await db.commit()
            total += len(chunk)
            chunk = []

        async with self._connect() as db:
            for inp in inputs:
                chunk.append((
                    job_id, uuid.uuid4().hex, json.dumps(inp),
                    BatchItemStatus.PENDING.value, 0, None, None, None, None,
                    None, None, now,
                ))
                if len(chunk) >= chunk_size:
                    await _flush(db)
            await _flush(db)
        return total

    async def get_item(self, job_id: str, item_id: str) -> BatchItem | None:
        async with self._connect() as db:
            db.row_factory = aiosqlite.Row
            cur = await db.execute(
                "SELECT * FROM batch_item WHERE job_id = ? AND item_id = ?",
                (job_id, item_id),
            )
            row = await cur.fetchone()
            return _row_to_item(row) if row else None

    async def list_by_status(
        self, job_id: str, status: BatchItemStatus
    ) -> list[BatchItem]:
        async with self._connect() as db:
            db.row_factory = aiosqlite.Row
            cur = await db.execute(
                "SELECT * FROM batch_item WHERE job_id = ? AND status = ? ORDER BY item_id",
                (job_id, status.value),
            )
            return [_row_to_item(r) for r in await cur.fetchall()]

    # --- lease (CAS claim) ------------------------------------------------

    async def lease_next_batch(
        self,
        job_id: str,
        *,
        limit: int,
        lease_owner: str,
        lease_ttl_ms: int,
        now_ms: int | None = None,
    ) -> list[BatchItem]:
        """Atomically claim up to ``limit`` pending items for ``lease_owner``.

        CAS: pending -> running. A unique ``lease_owner`` per run lets us
        SELECT exactly what this call claimed. Idempotent across crashes.
        """
        now = now_ms if now_ms is not None else _now_ms()
        expires = now + lease_ttl_ms
        async with self._connect() as db:
            db.row_factory = aiosqlite.Row
            await db.execute("BEGIN IMMEDIATE")
            await db.execute(
                """
                UPDATE batch_item
                SET status = 'running', lease_owner = ?, lease_expires_at_ms = ?,
                    updated_at_ms = ?
                WHERE (job_id, item_id) IN (
                    SELECT job_id, item_id FROM batch_item
                    WHERE job_id = ? AND status = 'pending'
                    ORDER BY item_id LIMIT ?
                )
                """,
                (lease_owner, expires, now, job_id, limit),
            )
            cur = await db.execute(
                """
                SELECT * FROM batch_item
                WHERE job_id = ? AND status = 'running' AND lease_owner = ?
                ORDER BY item_id
                """,
                (job_id, lease_owner),
            )
            rows = await cur.fetchall()
            await db.commit()
            return [_row_to_item(r) for r in rows]

    # --- update (array idempotent write-back) -----------------------------

    async def update_items(
        self, job_id: str, outcomes: list[ItemOutcome], *, now_ms: int | None = None
    ) -> int:
        """Apply agent-reported outcomes. Idempotent: only rows currently
        ``running`` are updated; ``attempts`` += 1 per applied row. Returns
        the number of rows actually updated.
        """
        now = now_ms if now_ms is not None else _now_ms()
        applied = 0
        async with self._connect() as db:
            for oc in outcomes:
                cur = await db.execute(
                    """
                    UPDATE batch_item
                    SET status = ?, result = ?, review_reason = ?, error = ?,
                        attempts = attempts + 1, lease_owner = NULL,
                        lease_expires_at_ms = NULL, updated_at_ms = ?
                    WHERE job_id = ? AND item_id = ? AND status = 'running'
                    """,
                    (
                        oc.status.value,
                        json.dumps(_normalize_result(oc.result)) if oc.result is not None else None,
                        oc.review_reason,
                        oc.error,
                        now,
                        job_id,
                        oc.item_id,
                    ),
                )
                applied += cur.rowcount
            await db.commit()
        return applied

    # --- counts / reconcile ----------------------------------------------

    async def status_counts(self, job_id: str) -> dict[str, int]:
        async with self._connect() as db:
            cur = await db.execute(
                "SELECT status, COUNT(*) FROM batch_item WHERE job_id = ? GROUP BY status",
                (job_id,),
            )
            return {status: count for status, count in await cur.fetchall()}

    async def reclaim_expired_leases(self, job_id: str, *, now_ms: int) -> int:
        async with self._connect() as db:
            cur = await db.execute(
                """
                UPDATE batch_item
                SET status = 'pending', lease_owner = NULL,
                    lease_expires_at_ms = NULL, updated_at_ms = ?
                WHERE job_id = ? AND status = 'running'
                  AND lease_expires_at_ms IS NOT NULL AND lease_expires_at_ms < ?
                """,
                (now_ms, job_id, now_ms),
            )
            await db.commit()
            return cur.rowcount

    async def reconcile_scan(self, job_id: str, *, now_ms: int) -> ReconcileReport:
        """Reclaim expired leases, then report counts + dedup_key conflicts +
        completeness. ``complete`` == no pending/running/needs_review left AND
        counts sum to total. ``conflicts`` pairs done items whose
        ``result.dedup_key`` collide (the engine's task-agnostic conflict check;
        handlers opt in by writing a ``dedup_key`` into ``result``).
        """
        reclaimed = await self.reclaim_expired_leases(job_id, now_ms=now_ms)
        counts = await self.status_counts(job_id)
        total = sum(counts.values())

        non_terminal = (
            counts.get(BatchItemStatus.PENDING.value, 0)
            + counts.get(BatchItemStatus.RUNNING.value, 0)
            + counts.get(BatchItemStatus.NEEDS_REVIEW.value, 0)
        )
        terminal_sum = sum(counts.get(s.value, 0) for s in TERMINAL_ITEM_STATUSES)
        complete = non_terminal == 0 and (terminal_sum == total)

        conflicts = await self._dedup_conflicts(job_id)
        return ReconcileReport(
            job_id=job_id, counts=counts, total=total, conflicts=conflicts,
            reclaimed_leases=reclaimed, complete=complete,
        )

    async def _dedup_conflicts(self, job_id: str) -> list[tuple[str, str]]:
        async with self._connect() as db:
            db.row_factory = aiosqlite.Row
            cur = await db.execute(
                "SELECT item_id, result FROM batch_item WHERE job_id = ? AND status = 'done'",
                (job_id,),
            )
            by_key: dict[str, str] = {}
            conflicts: list[tuple[str, str]] = []
            for row in await cur.fetchall():
                result = _loads(row["result"])
                if not isinstance(result, dict):
                    continue  # tolerate legacy double-encoded / scalar results
                key = result.get("dedup_key")
                if not key:
                    continue
                if key in by_key:
                    conflicts.append((by_key[key], row["item_id"]))
                else:
                    by_key[key] = row["item_id"]
            return conflicts

    async def apply_review(
        self,
        job_id: str,
        item_id: str,
        decision: str,
        *,
        data: Any = None,
        now_ms: int | None = None,
    ) -> bool:
        """Resolve a needs_review item: approve/override -> pending (re-process
        with the decision recorded); skip -> skipped. Idempotent: only acts on
        rows still ``needs_review``. Returns True if a row was updated.
        """
        now = now_ms if now_ms is not None else _now_ms()
        new_status = (
            BatchItemStatus.SKIPPED.value
            if decision == "skip"
            else BatchItemStatus.PENDING.value
        )
        payload = json.dumps({"decision": decision, "data": data})
        async with self._connect() as db:
            cur = await db.execute(
                "UPDATE batch_item SET status = ?, review_decision = ?, updated_at_ms = ? "
                "WHERE job_id = ? AND item_id = ? AND status = 'needs_review'",
                (new_status, payload, now, job_id, item_id),
            )
            await db.commit()
            return cur.rowcount > 0

    async def requeue_running(self, job_id: str) -> int:
        """Force ALL 'running' items back to 'pending' (clearing the lease),
        regardless of lease expiry. Used by restart-resume: after a process
        restart no batch runs are in-flight, so every 'running' row is an orphan
        and must be re-driven without waiting for the lease TTL. Returns rows requeued."""
        async with self._connect() as db:
            cur = await db.execute(
                """
                UPDATE batch_item
                SET status = 'pending', lease_owner = NULL,
                    lease_expires_at_ms = NULL, updated_at_ms = ?
                WHERE job_id = ? AND status = 'running'
                """,
                (_now_ms(), job_id),
            )
            await db.commit()
            return cur.rowcount

    async def reclaim_owner_running(
        self,
        job_id: str,
        lease_owner: str,
        max_attempts: int,
        *,
        now_ms: int | None = None,
    ) -> "tuple[int, int]":
        """Reclaim items a FINISHED run leased but never reported.

        When a batch run ends (hit its step cap or died) it may leave items it
        leased stuck in ``running`` under its ``lease_owner`` with a still-valid
        lease — invisible to leasing (not pending), to requeue_retryable (not
        failed), and to reclaim_expired_leases (lease not yet expired). Without
        this they stall the job until the TTL elapses.

        Scoped to ``lease_owner`` so a finishing run only reclaims its OWN
        orphans, never items still in-flight under other concurrent runs. The
        dead run counts as a consumed attempt (``attempts += 1``, mirroring
        update_items) so a structurally unprocessable item that keeps capping
        the run eventually dead-letters to ``failed`` instead of looping
        pending -> running -> cap -> pending forever. Items that have not yet
        exhausted ``max_attempts`` go back to ``pending`` for re-dispatch.

        Returns ``(requeued, dead_lettered)``.
        """
        now = now_ms if now_ms is not None else _now_ms()
        async with self._connect() as db:
            dead = await db.execute(
                """
                UPDATE batch_item
                SET status = 'failed', attempts = attempts + 1, lease_owner = NULL,
                    lease_expires_at_ms = NULL, updated_at_ms = ?,
                    error = 'orphaned: run ended without reporting an outcome'
                WHERE job_id = ? AND status = 'running' AND lease_owner = ?
                  AND attempts + 1 >= ?
                """,
                (now, job_id, lease_owner, max_attempts),
            )
            dead_lettered = dead.rowcount
            requeue = await db.execute(
                """
                UPDATE batch_item
                SET status = 'pending', attempts = attempts + 1, lease_owner = NULL,
                    lease_expires_at_ms = NULL, updated_at_ms = ?
                WHERE job_id = ? AND status = 'running' AND lease_owner = ?
                """,
                (now, job_id, lease_owner),
            )
            requeued = requeue.rowcount
            await db.commit()
            return requeued, dead_lettered

    async def requeue_retryable(
        self, job_id: str, max_attempts: int, *, now_ms: int | None = None
    ) -> int:
        """Failed items still under the attempt limit go back to pending."""
        now = now_ms if now_ms is not None else _now_ms()
        async with self._connect() as db:
            cur = await db.execute(
                "UPDATE batch_item SET status = 'pending', lease_owner = NULL, "
                "lease_expires_at_ms = NULL, updated_at_ms = ? "
                "WHERE job_id = ? AND status = 'failed' AND attempts < ?",
                (now, job_id, max_attempts),
            )
            await db.commit()
            return cur.rowcount

    async def clear_all(self) -> dict[str, int]:
        """Delete every persisted batch manifest and its content payloads."""
        async with self._connect() as db:
            await db.execute("BEGIN IMMEDIATE")
            try:
                item_row = await (
                    await db.execute("SELECT COUNT(*) FROM batch_item")
                ).fetchone()
                job_row = await (
                    await db.execute("SELECT COUNT(*) FROM batch_job")
                ).fetchone()
                await db.execute("DELETE FROM batch_item")
                await db.execute("DELETE FROM batch_job")
                await db.commit()
            except BaseException:
                await db.rollback()
                raise
        return {
            "batch_items": int(item_row[0] if item_row else 0),
            "batch_jobs": int(job_row[0] if job_row else 0),
        }


def default_batch_store() -> BatchStore:
    """Construct a BatchStore against the runtime batch DB (schema built by
    alembic at startup). The store is stateless — one connection per call — so
    a fresh instance per tool invocation is fine."""
    from ...utils.runtime import get_runtime_paths

    return BatchStore(db_path=str(get_runtime_paths().batch_db_path))
