"""SQLite repository for correction records, rules, revisions, and jobs."""

from __future__ import annotations

import json
import math
import time
import uuid
from collections.abc import Iterable, Mapping
from typing import Any

import aiosqlite

from ....core.sqlite import sqlite_connection_async
from .evidence_ledger import claim_evidence_event_ids
from .models import (
    CorrectionCreateResult,
    CorrectionRule,
    CorrectionTargetKind,
    MemoryCorrection,
    NewMemoryCorrection,
)
from .relationship_conflict_effects import (
    apply_relationship_conflict_effects,
    load_relationship_graph_conflict_rules,
    relationship_conflict_effects_on_connection,
)

DEFAULT_DERIVATION_MAX_ATTEMPTS = 5
DEFAULT_DERIVATION_STALE_RUNNING_SECONDS = 300.0


class MemoryCorrectionRepository:
    """Persist correction governance inside the shared memory transaction."""

    def __init__(self, db_path: str):
        self.db_path = db_path

    async def create(
        self,
        correction: NewMemoryCorrection,
        *,
        rules: Iterable[CorrectionRule] = (),
        subject_keys: Iterable[str] = (),
    ) -> CorrectionCreateResult:
        """Insert one correction idempotently and bump affected revisions."""
        async with sqlite_connection_async(self.db_path) as db:
            db.row_factory = aiosqlite.Row
            await db.execute("BEGIN IMMEDIATE")
            try:
                existing = await self.get_by_request_id_on_connection(
                    db,
                    correction.request_id,
                )
                if existing is not None:
                    await db.commit()
                    return CorrectionCreateResult(
                        correction=existing,
                        created=False,
                        subject_revisions={},
                    )
                await self.insert_correction(db, correction)
                for rule in rules:
                    await self.insert_rule(db, rule)
                revisions = {}
                if not _transition_is_pending(correction):
                    revisions = {
                        subject_key: await self.bump_subject_revision(
                            db,
                            subject_key=subject_key,
                            updated_at=correction.created_at,
                        )
                        for subject_key in dict.fromkeys(
                            str(item).strip() for item in subject_keys if str(item).strip()
                        )
                    }
                await db.commit()
            except Exception:
                await db.rollback()
                raise
        stored = await self.get(correction.correction_id)
        assert stored is not None
        return CorrectionCreateResult(
            correction=stored,
            created=True,
            subject_revisions=revisions,
        )

    async def insert_correction(
        self,
        db: aiosqlite.Connection,
        correction: NewMemoryCorrection,
    ) -> None:
        """Insert a correction using an existing transaction."""
        await db.execute(
            """
            INSERT INTO memory_corrections(
                correction_id, request_id, actor_id, target_kind, target_id,
                slot_key, claim_fingerprint, correction_kind, reason, before_json,
                replacement_json, effective_at, scope_json, source_event_id,
                audit_event_id, replacement_target_id, state, created_at,
                transition_applied_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'active', ?, ?)
            """,
            (
                correction.correction_id,
                correction.request_id,
                correction.actor_id,
                correction.target_kind.value,
                correction.target_id,
                correction.slot_key,
                correction.claim_fingerprint,
                correction.correction_kind.value,
                _optional_text(correction.reason),
                _json_mapping(correction.before),
                _json_mapping(correction.replacement),
                correction.effective_at,
                _json_mapping(correction.scope),
                _optional_text(correction.source_event_id),
                _optional_text(correction.audit_event_id),
                _optional_text(correction.replacement_target_id),
                correction.created_at,
                _initial_transition_applied_at(correction),
            ),
        )
        evidence_event_ids, evidence_fail_closed = _correction_evidence_governance(correction)
        ledger_event_ids = await claim_evidence_event_ids(
            db,
            target_kind=correction.target_kind,
            claim_fingerprint=correction.claim_fingerprint,
        )
        await self.append_evidence_event_ids(
            db,
            correction_id=correction.correction_id,
            target_kind=correction.target_kind,
            event_ids=(*evidence_event_ids, *ledger_event_ids),
            created_at=correction.created_at,
        )
        if evidence_fail_closed:
            await self.mark_evidence_fail_closed(
                db,
                correction_id=correction.correction_id,
                created_at=correction.created_at,
            )

    async def append_evidence_event_ids(
        self,
        db: aiosqlite.Connection,
        *,
        correction_id: str,
        target_kind: CorrectionTargetKind,
        event_ids: Iterable[str],
        created_at: float,
    ) -> None:
        """Attach newly governed evidence to an active correction transactionally."""
        normalized = list(
            dict.fromkeys(str(event_id).strip() for event_id in event_ids if str(event_id).strip())
        )
        if not normalized:
            return
        await db.executemany(
            """
            INSERT OR IGNORE INTO memory_correction_evidence_events(
                correction_id, event_id, target_kind, created_at
            ) VALUES (?, ?, ?, ?)
            """,
            [
                (
                    correction_id,
                    event_id,
                    target_kind.value,
                    created_at,
                )
                for event_id in normalized
            ],
        )

    async def mark_evidence_fail_closed(
        self,
        db: aiosqlite.Connection,
        *,
        correction_id: str,
        created_at: float,
    ) -> None:
        """Record that one correction must govern every candidate evidence event."""
        await db.execute(
            """
            INSERT OR IGNORE INTO memory_correction_evidence_fail_closed(
                correction_id, created_at
            ) VALUES (?, ?)
            """,
            (correction_id, created_at),
        )

    async def insert_rule(
        self,
        db: aiosqlite.Connection,
        rule: CorrectionRule,
    ) -> None:
        """Insert one materialized correction rule in the current transaction."""
        await db.execute(
            """
            INSERT INTO memory_correction_rules(
                rule_id, correction_id, target_kind, rule_kind, slot_key,
                claim_fingerprint, scope_key, effective_from, effective_to,
                active, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                rule.rule_id,
                rule.correction_id,
                rule.target_kind.value,
                rule.rule_kind.value,
                rule.slot_key,
                _optional_text(rule.claim_fingerprint),
                rule.scope_key,
                rule.effective_from,
                rule.effective_to,
                int(rule.active),
                rule.created_at,
            ),
        )

    async def get(self, correction_id: str) -> MemoryCorrection | None:
        async with sqlite_connection_async(self.db_path) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute(
                "SELECT * FROM memory_corrections WHERE correction_id = ?",
                (correction_id,),
            ) as cursor:
                row = await cursor.fetchone()
        return MemoryCorrection.from_row(dict(row)) if row is not None else None

    async def get_by_request_id(self, request_id: str) -> MemoryCorrection | None:
        async with sqlite_connection_async(self.db_path) as db:
            db.row_factory = aiosqlite.Row
            return await self.get_by_request_id_on_connection(db, request_id)

    async def get_by_request_id_on_connection(
        self,
        db: aiosqlite.Connection,
        request_id: str,
    ) -> MemoryCorrection | None:
        async with db.execute(
            "SELECT * FROM memory_corrections WHERE request_id = ?",
            (request_id,),
        ) as cursor:
            row = await cursor.fetchone()
        return MemoryCorrection.from_row(dict(row)) if row is not None else None

    async def list_for_target(
        self,
        *,
        target_kind: CorrectionTargetKind,
        target_id: str,
        limit: int = 100,
    ) -> list[MemoryCorrection]:
        async with sqlite_connection_async(self.db_path) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute(
                """
                SELECT * FROM memory_corrections
                WHERE target_kind = ? AND target_id = ?
                ORDER BY created_at DESC
                LIMIT ?
                """,
                (target_kind.value, target_id, int(limit)),
            ) as cursor:
                rows = await cursor.fetchall()
        return [MemoryCorrection.from_row(dict(row)) for row in rows]

    async def correction_ids_with_forget_barriers(
        self,
        correction_ids: Iterable[str],
    ) -> set[str]:
        """Return corrections that cannot be reverted across a forget boundary."""
        normalized = list(
            dict.fromkeys(
                str(correction_id).strip()
                for correction_id in correction_ids
                if str(correction_id).strip()
            )
        )
        if not normalized:
            return set()
        candidate_json = json.dumps(normalized, ensure_ascii=False, separators=(",", ":"))
        async with sqlite_connection_async(self.db_path) as db:
            async with db.execute(
                """
                SELECT DISTINCT correction_id
                FROM memory_correction_forget_barriers
                WHERE correction_id IN (
                    SELECT CAST(value AS TEXT) FROM json_each(?)
                )
                """,
                (candidate_json,),
            ) as cursor:
                return {str(row[0]) for row in await cursor.fetchall()}

    async def list_active_rules(
        self,
        *,
        target_kind: CorrectionTargetKind,
        slot_key: str,
    ) -> list[dict[str, Any]]:
        async with sqlite_connection_async(self.db_path) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute(
                """
                SELECT * FROM memory_correction_rules
                WHERE target_kind = ? AND slot_key = ? AND active = 1
                ORDER BY created_at ASC
                """,
                (target_kind.value, slot_key),
            ) as cursor:
                rows = await cursor.fetchall()
        return [dict(row) for row in rows]

    async def active_correction_evidence_event_ids(
        self,
        event_ids: Iterable[str],
    ) -> set[str]:
        """Return candidate L1 events governed by a correction or forget rule."""
        normalized = list(
            dict.fromkeys(str(event_id).strip() for event_id in event_ids if str(event_id).strip())
        )
        if not normalized:
            return set()
        candidate_json = json.dumps(
            normalized,
            ensure_ascii=False,
            separators=(",", ":"),
        )
        async with sqlite_connection_async(self.db_path) as db:
            async with db.execute(
                """
                SELECT DISTINCT evidence.event_id, 0 AS fail_closed
                FROM memory_correction_evidence_events AS evidence
                JOIN memory_corrections AS corrections
                  ON corrections.correction_id = evidence.correction_id
                WHERE evidence.event_id IN (
                    SELECT CAST(value AS TEXT) FROM json_each(?)
                )
                  AND corrections.state = 'active'
                  AND corrections.transition_cancelled_at IS NULL
                UNION ALL
                SELECT NULL AS event_id, 1 AS fail_closed
                WHERE EXISTS (
                    SELECT 1
                    FROM memory_correction_evidence_fail_closed AS fail_closed
                    JOIN memory_corrections AS corrections
                      ON corrections.correction_id = fail_closed.correction_id
                    WHERE corrections.state = 'active'
                      AND corrections.transition_cancelled_at IS NULL
                )
                UNION ALL
                SELECT DISTINCT evidence.event_id, 0 AS fail_closed
                FROM memory_forget_evidence_events AS evidence
                WHERE evidence.event_id IN (
                    SELECT CAST(value AS TEXT) FROM json_each(?)
                )
                UNION ALL
                SELECT DISTINCT tombstones.event_id, 0 AS fail_closed
                FROM memory_source_event_tombstones AS tombstones
                WHERE tombstones.event_id IN (
                    SELECT CAST(value AS TEXT) FROM json_each(?)
                )
                UNION ALL
                SELECT NULL AS event_id, 1 AS fail_closed
                WHERE EXISTS (
                    SELECT 1
                    FROM memory_forget_claim_rules AS rules
                    WHERE rules.evidence_fail_closed = 1
                )
                """,
                (candidate_json, candidate_json, candidate_json),
            ) as cursor:
                rows = await cursor.fetchall()
        if any(bool(row[1]) for row in rows):
            return set(normalized)
        return {str(row[0]) for row in rows if row[0] is not None}

    async def current_subject_revision(self, subject_key: str) -> int:
        async with sqlite_connection_async(self.db_path) as db:
            async with db.execute(
                "SELECT revision FROM memory_subject_revisions WHERE subject_key = ?",
                (subject_key,),
            ) as cursor:
                row = await cursor.fetchone()
        return int(row[0]) if row is not None else 0

    async def bump_subject_revision(
        self,
        db: aiosqlite.Connection,
        *,
        subject_key: str,
        updated_at: float | None = None,
    ) -> int:
        """Increment and return a subject revision inside the caller transaction."""
        now = float(updated_at if updated_at is not None else time.time())
        await db.execute(
            """
            INSERT INTO memory_subject_revisions(subject_key, revision, updated_at)
            VALUES (?, 1, ?)
            ON CONFLICT(subject_key) DO UPDATE SET
                revision = memory_subject_revisions.revision + 1,
                updated_at = excluded.updated_at
            """,
            (subject_key, now),
        )
        async with db.execute(
            "SELECT revision FROM memory_subject_revisions WHERE subject_key = ?",
            (subject_key,),
        ) as cursor:
            row = await cursor.fetchone()
        assert row is not None
        return int(row[0])

    async def activate_due_situation_changes(
        self,
        *,
        limit: int = 25,
        now: float | None = None,
    ) -> tuple[int, dict[str, int]]:
        """Advance revisions for due situation changes exactly once."""
        activated_at = float(now if now is not None else time.time())
        bounded_limit = max(1, int(limit))
        activated_count = 0
        subject_revisions: dict[str, int] = {}
        async with sqlite_connection_async(self.db_path) as db:
            db.row_factory = aiosqlite.Row
            await db.execute("BEGIN IMMEDIATE")
            try:
                async with db.execute(
                    """
                    SELECT *
                    FROM memory_corrections
                    WHERE correction_kind = 'situation_changed'
                      AND state = 'active'
                      AND transition_applied_at IS NULL
                      AND transition_cancelled_at IS NULL
                      AND effective_at IS NOT NULL
                      AND effective_at <= ?
                    ORDER BY effective_at, created_at, correction_id
                    LIMIT ?
                    """,
                    (activated_at, bounded_limit),
                ) as cursor:
                    due_rows = await cursor.fetchall()

                for row in due_rows:
                    correction = MemoryCorrection.from_row(dict(row))
                    subjects = _correction_subject_keys(correction)
                    source_kind = (
                        "assertion"
                        if correction.target_kind == CorrectionTargetKind.ASSERTION
                        else "edge"
                    )
                    source_ids = [
                        correction.target_id,
                        correction.replacement_target_id or "",
                    ]
                    if correction.target_kind == CorrectionTargetKind.EDGE:
                        replacement_is_effective = await _relationship_replacement_is_effective(
                            db,
                            correction=correction,
                            effective_at=activated_at,
                        )
                        if correction.replacement is not None and replacement_is_effective:
                            graph_conflict_rules = await load_relationship_graph_conflict_rules(db)
                            await apply_relationship_conflict_effects(
                                db,
                                replacement=correction.replacement,
                                correction_id=correction.correction_id,
                                graph_conflict_rules=graph_conflict_rules,
                                effective_at=float(correction.effective_at or activated_at),
                                now=activated_at,
                            )
                        conflict_effects = await relationship_conflict_effects_on_connection(
                            db,
                            correction_id=correction.correction_id,
                            replacement_id=correction.replacement_target_id,
                        )
                        source_ids.extend(conflict_effects.edge_ids)
                        subjects = list(dict.fromkeys([*subjects, *conflict_effects.subject_keys]))
                    l3_subjects = await self.invalidate_l3_insights_on_connection(
                        db,
                        source_kind=source_kind,
                        source_ids=source_ids,
                        subject_keys=subjects,
                        updated_at=activated_at,
                    )
                    affected_subjects = list(dict.fromkeys([*subjects, *sorted(l3_subjects)]))
                    for subject_key in affected_subjects:
                        revision = await self.bump_subject_revision(
                            db,
                            subject_key=subject_key,
                            updated_at=activated_at,
                        )
                        subject_revisions[subject_key] = revision
                        await self.enqueue_subject_derivations(
                            db,
                            correction_id=correction.correction_id,
                            subject_key=subject_key,
                            target_revision=revision,
                            include_l3=subject_key in l3_subjects,
                            now=activated_at,
                        )
                    cursor = await db.execute(
                        """
                        UPDATE memory_corrections
                        SET transition_applied_at = ?
                        WHERE correction_id = ?
                          AND state = 'active'
                          AND transition_applied_at IS NULL
                          AND transition_cancelled_at IS NULL
                        """,
                        (activated_at, correction.correction_id),
                    )
                    activated_count += int(cursor.rowcount or 0)
                await db.commit()
            except Exception:
                await db.rollback()
                raise
        return activated_count, subject_revisions

    async def enqueue_derivation_job(
        self,
        db: aiosqlite.Connection,
        *,
        correction_id: str,
        job_kind: str,
        target_key: str,
        target_revision: int,
        now: float | None = None,
    ) -> str:
        """Queue one durable correction follow-up using the current transaction."""
        job_id = f"correction_job_{uuid.uuid4().hex}"
        created_at = float(now if now is not None else time.time())
        await db.execute(
            """
            INSERT INTO memory_derivation_jobs(
                job_id, correction_id, job_kind, target_key, target_revision,
                status, attempt_count, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, 'pending', 0, ?, ?)
            ON CONFLICT(correction_id, job_kind, target_key, target_revision) DO NOTHING
            """,
            (
                job_id,
                correction_id,
                job_kind,
                target_key,
                int(target_revision),
                created_at,
                created_at,
            ),
        )
        return job_id

    async def enqueue_subject_derivations(
        self,
        db: aiosqlite.Connection,
        *,
        correction_id: str,
        subject_key: str,
        target_revision: int,
        include_l3: bool = False,
        now: float | None = None,
    ) -> list[str]:
        """Queue the latest derived views affected by one subject correction."""
        job_kinds = ["snapshot"]
        if subject_key.startswith("user:"):
            job_kinds.extend(("profile", "portrait"))
        if include_l3:
            job_kinds.append("l3_insight")

        created_at = float(now if now is not None else time.time())
        job_ids: list[str] = []
        for job_kind in job_kinds:
            await db.execute(
                """
                UPDATE memory_derivation_jobs
                SET status = 'completed', next_retry_at = NULL,
                    last_error = ?, updated_at = ?
                WHERE job_kind = ? AND target_key = ?
                  AND target_revision < ? AND status IN ('pending', 'failed')
                """,
                (
                    f"Superseded by revision {int(target_revision)}",
                    created_at,
                    job_kind,
                    subject_key,
                    int(target_revision),
                ),
            )
            job_ids.append(
                await self.enqueue_derivation_job(
                    db,
                    correction_id=correction_id,
                    job_kind=job_kind,
                    target_key=subject_key,
                    target_revision=target_revision,
                    now=created_at,
                )
            )
        return job_ids

    async def requeue_running_jobs(self) -> int:
        """Return all running jobs to pending for explicit startup recovery."""
        recovery = await self.recover_stale_running_jobs(stale_after_seconds=0.0)
        return recovery["requeued"]

    async def recover_stale_running_jobs(
        self,
        *,
        stale_after_seconds: float = DEFAULT_DERIVATION_STALE_RUNNING_SECONDS,
        max_attempts: int = DEFAULT_DERIVATION_MAX_ATTEMPTS,
        now: float | None = None,
    ) -> dict[str, int]:
        """Recover abandoned running jobs without disturbing live workers."""
        recovered_at = float(now if now is not None else time.time())
        stale_before = recovered_at - max(0.0, float(stale_after_seconds))
        bounded_attempts = max(1, int(max_attempts))
        async with sqlite_connection_async(self.db_path) as db:
            terminal_cursor = await db.execute(
                """
                UPDATE memory_derivation_jobs
                SET status = 'failed', next_retry_at = NULL,
                    last_error = 'Interrupted after maximum attempts', updated_at = ?
                WHERE status = 'running' AND updated_at <= ?
                  AND attempt_count >= ?
                """,
                (recovered_at, stale_before, bounded_attempts),
            )
            requeued_cursor = await db.execute(
                """
                UPDATE memory_derivation_jobs
                SET status = 'pending', next_retry_at = NULL,
                    last_error = 'Interrupted before completion', updated_at = ?
                WHERE status = 'running' AND updated_at <= ?
                  AND attempt_count < ?
                """,
                (recovered_at, stale_before, bounded_attempts),
            )
            await db.commit()
        return {
            "requeued": int(requeued_cursor.rowcount or 0),
            "terminal_failed": int(terminal_cursor.rowcount or 0),
        }

    async def next_derivation_wakeup_at(
        self,
        *,
        stale_after_seconds: float = DEFAULT_DERIVATION_STALE_RUNNING_SECONDS,
        max_attempts: int = DEFAULT_DERIVATION_MAX_ATTEMPTS,
        now: float | None = None,
    ) -> float | None:
        """Return when the next retryable or recoverable job needs attention."""
        checked_at = float(now if now is not None else time.time())
        bounded_attempts = max(1, int(max_attempts))
        async with sqlite_connection_async(self.db_path) as db:
            async with db.execute(
                """
                SELECT MIN(ready_at)
                FROM (
                    SELECT CASE
                        WHEN status = 'pending'
                            THEN COALESCE(next_retry_at, ?)
                        WHEN status = 'failed' AND next_retry_at IS NOT NULL
                            THEN next_retry_at
                        WHEN status = 'running'
                            THEN updated_at + ?
                        ELSE NULL
                    END AS ready_at
                    FROM memory_derivation_jobs
                    WHERE (
                        attempt_count < ?
                        AND (
                            status = 'pending'
                            OR (status = 'failed' AND next_retry_at IS NOT NULL)
                        )
                    )
                    OR status = 'running'
                    UNION ALL
                    SELECT effective_at AS ready_at
                    FROM memory_corrections
                    WHERE correction_kind = 'situation_changed'
                      AND state = 'active'
                      AND transition_applied_at IS NULL
                      AND transition_cancelled_at IS NULL
                      AND effective_at IS NOT NULL
                )
                WHERE ready_at IS NOT NULL
                """,
                (
                    checked_at,
                    max(0.0, float(stale_after_seconds)),
                    bounded_attempts,
                ),
            ) as cursor:
                row = await cursor.fetchone()
        if row is None or row[0] is None:
            return None
        return float(row[0])

    async def derivation_state_for_correction(self, correction_id: str) -> str:
        """Return the aggregate follow-up state for one correction."""
        async with sqlite_connection_async(self.db_path) as db:
            async with db.execute(
                """
                SELECT correction_kind, state, transition_applied_at,
                       transition_cancelled_at
                FROM memory_corrections
                WHERE correction_id = ?
                """,
                (correction_id,),
            ) as cursor:
                correction_row = await cursor.fetchone()
            async with db.execute(
                """
                SELECT status, next_retry_at
                FROM memory_derivation_jobs
                WHERE correction_id = ?
                """,
                (correction_id,),
            ) as cursor:
                rows = await cursor.fetchall()
        if any(str(status) == "failed" and next_retry_at is None for status, next_retry_at in rows):
            return "failed"
        if (
            correction_row is not None
            and str(correction_row[0]) == "situation_changed"
            and str(correction_row[1]) == "active"
            and correction_row[2] is None
            and correction_row[3] is None
        ):
            return "pending"
        if any(str(status) == "running" for status, _ in rows):
            return "running"
        if any(
            str(status) == "pending" or (str(status) == "failed" and next_retry_at is not None)
            for status, next_retry_at in rows
        ):
            return "pending"
        return "completed"

    async def claim_next_derivation_job(
        self,
        *,
        max_attempts: int = DEFAULT_DERIVATION_MAX_ATTEMPTS,
        now: float | None = None,
    ) -> dict[str, Any] | None:
        """Atomically claim the next ready derivation job."""
        claimed_at = float(now if now is not None else time.time())
        bounded_attempts = max(1, int(max_attempts))
        async with sqlite_connection_async(self.db_path) as db:
            db.row_factory = aiosqlite.Row
            await db.execute("BEGIN IMMEDIATE")
            try:
                await db.execute(
                    """
                    UPDATE memory_derivation_jobs
                    SET status = 'failed', next_retry_at = NULL,
                        last_error = COALESCE(last_error, 'Maximum attempts reached'),
                        updated_at = ?
                    WHERE status IN ('pending', 'failed')
                      AND attempt_count >= ?
                    """,
                    (claimed_at, bounded_attempts),
                )
                await db.execute(
                    """
                    UPDATE memory_derivation_jobs AS dependent
                    SET status = 'failed', next_retry_at = NULL,
                        last_error = 'Blocked by failed profile derivation',
                        updated_at = ?
                    WHERE dependent.job_kind = 'portrait'
                      AND dependent.status IN ('pending', 'failed')
                      AND EXISTS (
                          SELECT 1
                          FROM memory_derivation_jobs AS prerequisite
                          WHERE prerequisite.correction_id = dependent.correction_id
                            AND prerequisite.target_key = dependent.target_key
                            AND prerequisite.target_revision = dependent.target_revision
                            AND prerequisite.job_kind = 'profile'
                            AND prerequisite.status = 'failed'
                            AND prerequisite.next_retry_at IS NULL
                      )
                    """,
                    (claimed_at,),
                )
                async with db.execute(
                    """
                    SELECT candidate.* FROM memory_derivation_jobs AS candidate
                    WHERE candidate.attempt_count < ?
                      AND (
                          (
                              candidate.status = 'pending'
                              AND (
                                  candidate.next_retry_at IS NULL
                                  OR candidate.next_retry_at <= ?
                              )
                          )
                          OR (
                              candidate.status = 'failed'
                              AND candidate.next_retry_at IS NOT NULL
                              AND candidate.next_retry_at <= ?
                          )
                      )
                      AND (
                          candidate.job_kind != 'portrait'
                          OR NOT EXISTS (
                              SELECT 1
                              FROM memory_derivation_jobs AS prerequisite
                              WHERE prerequisite.correction_id = candidate.correction_id
                                AND prerequisite.target_key = candidate.target_key
                                AND prerequisite.target_revision = candidate.target_revision
                                AND prerequisite.job_kind = 'profile'
                                AND prerequisite.status != 'completed'
                          )
                      )
                    ORDER BY
                        CASE candidate.job_kind
                            WHEN 'l1_audit' THEN 0
                            WHEN 'snapshot' THEN 1
                            WHEN 'profile' THEN 2
                            WHEN 'portrait' THEN 3
                            WHEN 'l3_insight' THEN 4
                            ELSE 5
                        END,
                        candidate.target_revision DESC,
                        candidate.created_at ASC
                    LIMIT 1
                    """,
                    (bounded_attempts, claimed_at, claimed_at),
                ) as cursor:
                    row = await cursor.fetchone()
                if row is None:
                    await db.commit()
                    return None
                job = dict(row)
                cursor = await db.execute(
                    """
                    UPDATE memory_derivation_jobs
                    SET status = 'running', attempt_count = attempt_count + 1,
                        next_retry_at = NULL, updated_at = ?
                    WHERE job_id = ? AND status IN ('pending', 'failed')
                    """,
                    (claimed_at, job["job_id"]),
                )
                if int(cursor.rowcount or 0) != 1:
                    await db.rollback()
                    return None
                await db.commit()
            except Exception:
                await db.rollback()
                raise
        job["status"] = "running"
        job["attempt_count"] = int(job["attempt_count"]) + 1
        job["updated_at"] = claimed_at
        return job

    async def complete_derivation_job(
        self,
        job_id: str,
        *,
        attempt_count: int,
        message: str | None = None,
    ) -> bool:
        """Complete only the running attempt that still owns the job lease."""
        now = time.time()
        async with sqlite_connection_async(self.db_path) as db:
            cursor = await db.execute(
                """
                UPDATE memory_derivation_jobs
                SET status = 'completed', next_retry_at = NULL,
                    last_error = ?, updated_at = ?
                WHERE job_id = ? AND status = 'running' AND attempt_count = ?
                """,
                (_optional_text(message), now, job_id, int(attempt_count)),
            )
            await db.commit()
        return int(cursor.rowcount or 0) == 1

    async def fail_derivation_job(
        self,
        job_id: str,
        *,
        error: str,
        attempt_count: int,
        max_attempts: int = DEFAULT_DERIVATION_MAX_ATTEMPTS,
        now: float | None = None,
    ) -> bool:
        """Fail only the running attempt that still owns the job lease."""
        failed_at = float(now if now is not None else time.time())
        terminal = int(attempt_count) >= max(1, int(max_attempts))
        delay_seconds = min(300.0, 2.0 ** max(0, int(attempt_count) - 1))
        next_retry_at = None if terminal else failed_at + delay_seconds
        status = "failed" if terminal else "pending"
        async with sqlite_connection_async(self.db_path) as db:
            cursor = await db.execute(
                """
                UPDATE memory_derivation_jobs
                SET status = ?, next_retry_at = ?, last_error = ?, updated_at = ?
                WHERE job_id = ? AND status = 'running' AND attempt_count = ?
                """,
                (
                    status,
                    next_retry_at,
                    str(error)[:1000],
                    failed_at,
                    job_id,
                    int(attempt_count),
                ),
            )
            await db.commit()
        return int(cursor.rowcount or 0) == 1

    async def replace_dependencies(
        self,
        *,
        artifact_kind: str,
        artifact_id: str,
        subject_key: str,
        source_revision: int,
        sources: Iterable[tuple[str, str]],
    ) -> None:
        """Replace the source ledger for one rebuilt derived artifact."""
        await self.replace_artifact_dependencies(
            artifact_kind=artifact_kind,
            artifact_id=artifact_id,
            dependencies=[
                (
                    str(source_kind),
                    str(source_id),
                    subject_key,
                    int(source_revision),
                )
                for source_kind, source_id in sources
            ],
        )

    async def replace_artifact_dependencies(
        self,
        *,
        artifact_kind: str,
        artifact_id: str,
        dependencies: Iterable[tuple[str, str, str, int]],
    ) -> None:
        """Replace all possibly multi-subject dependencies for one artifact."""
        async with sqlite_connection_async(self.db_path) as db:
            await self.replace_artifact_dependencies_on_connection(
                db,
                artifact_kind=artifact_kind,
                artifact_id=artifact_id,
                dependencies=dependencies,
            )
            await db.commit()

    async def replace_artifact_dependencies_on_connection(
        self,
        db: aiosqlite.Connection,
        *,
        artifact_kind: str,
        artifact_id: str,
        dependencies: Iterable[tuple[str, str, str, int]],
        created_at: float | None = None,
    ) -> None:
        """Replace an artifact dependency ledger in the caller transaction."""
        now = float(created_at if created_at is not None else time.time())
        normalized = list(
            dict.fromkeys(
                (
                    str(source_kind),
                    str(source_id),
                    str(subject_key),
                    int(source_revision),
                )
                for source_kind, source_id, subject_key, source_revision in dependencies
                if str(source_id).strip() and str(subject_key).strip()
            )
        )
        await db.execute(
            """
            DELETE FROM memory_derivation_dependencies
            WHERE artifact_kind = ? AND artifact_id = ?
            """,
            (artifact_kind, artifact_id),
        )
        await db.executemany(
            """
            INSERT INTO memory_derivation_dependencies(
                artifact_kind, artifact_id, source_kind, source_id,
                subject_key, source_revision, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            [
                (
                    artifact_kind,
                    artifact_id,
                    source_kind,
                    source_id,
                    subject_key,
                    int(source_revision),
                    now,
                )
                for source_kind, source_id, subject_key, source_revision in normalized
            ],
        )

    async def invalidate_l3_insights_on_connection(
        self,
        db: aiosqlite.Connection,
        *,
        source_kind: str,
        source_ids: Iterable[str],
        subject_keys: Iterable[str] = (),
        include_current_subjects: bool = False,
        updated_at: float | None = None,
    ) -> set[str]:
        """Invalidate direct dependants and keep stale same-subject rebuilds queued."""
        normalized_ids = list(
            dict.fromkeys(
                str(source_id).strip() for source_id in source_ids if str(source_id).strip()
            )
        )
        normalized_subjects = list(
            dict.fromkeys(
                str(subject_key).strip() for subject_key in subject_keys if str(subject_key).strip()
            )
        )
        if not normalized_ids and not normalized_subjects:
            return set()
        clauses: list[str] = []
        args: list[Any] = []
        if normalized_ids:
            placeholders = ", ".join("?" for _ in normalized_ids)
            clauses.append(
                f"(dependencies.source_kind = ? AND dependencies.source_id IN ({placeholders}))"
            )
            args.extend((source_kind, *normalized_ids))
        if normalized_subjects:
            placeholders = ", ".join("?" for _ in normalized_subjects)
            subject_clause = f"dependencies.subject_key IN ({placeholders})"
            if not include_current_subjects:
                subject_clause += " AND summaries.derivation_state = 'stale'"
            clauses.append(f"({subject_clause})")
            args.extend(normalized_subjects)
        async with db.execute(
            f"""
            SELECT DISTINCT dependencies.artifact_id, dependencies.subject_key
            FROM memory_derivation_dependencies AS dependencies
            JOIN summaries ON summaries.summary_id = dependencies.artifact_id
            WHERE dependencies.artifact_kind = 'l3_insight'
              AND ({' OR '.join(clauses)})
            """,
            tuple(args),
        ) as cursor:
            rows = await cursor.fetchall()
        if not rows:
            return set()
        artifact_ids = [str(row[0]) for row in rows]
        artifact_placeholders = ", ".join("?" for _ in artifact_ids)
        now = float(updated_at if updated_at is not None else time.time())
        await db.execute(
            f"""
            UPDATE summaries
            SET derivation_state = 'stale', updated_at = ?
            WHERE summary_id IN ({artifact_placeholders})
              AND summary_type = 'insight'
            """,
            (now, *artifact_ids),
        )
        await db.execute(
            f"DELETE FROM l3_summaries_fts WHERE summary_id IN ({artifact_placeholders})",
            tuple(artifact_ids),
        )
        return {str(row[1]) for row in rows if str(row[1]).strip()}


async def _relationship_replacement_is_effective(
    db: aiosqlite.Connection,
    *,
    correction: MemoryCorrection,
    effective_at: float,
) -> bool:
    replacement_id = correction.replacement_target_id
    if not replacement_id:
        return False
    async with db.execute(
        """
        SELECT status, status_reason, valid_from, valid_to
        FROM knowledge_graph
        WHERE triple_id = ?
        """,
        (replacement_id,),
    ) as cursor:
        row = await cursor.fetchone()
    if row is None or str(row[0]) in {"archived", "conflicted", "expired", "user_rejected"}:
        return False
    if str(row[1] or "") == "user_forget":
        return False
    valid_from = float(row[2]) if row[2] is not None else -math.inf
    valid_to = float(row[3]) if row[3] is not None else math.inf
    return valid_from <= effective_at < valid_to


def _initial_transition_applied_at(correction: NewMemoryCorrection) -> float | None:
    if correction.correction_kind.value != "situation_changed":
        return None
    if _transition_is_pending(correction):
        return None
    return float(correction.created_at)


def _transition_is_pending(correction: NewMemoryCorrection) -> bool:
    return (
        correction.correction_kind.value == "situation_changed"
        and correction.effective_at is not None
        and float(correction.effective_at) > float(correction.created_at)
    )


def _correction_subject_keys(correction: MemoryCorrection) -> list[str]:
    if correction.target_kind == CorrectionTargetKind.ASSERTION:
        entity_id = str(correction.before.get("entity_id") or "").strip()
        return [entity_id] if entity_id else []

    keys: list[str] = []
    for payload in (correction.before, correction.replacement or {}):
        subject_id = str(payload.get("subject_id") or "").strip()
        object_id = str(payload.get("object_id") or "").strip()
        if subject_id:
            keys.append(subject_id)
        if ":" in object_id:
            keys.append(object_id)
    return list(dict.fromkeys(keys))


def _json_mapping(value: Mapping[str, Any] | None) -> str | None:
    if value is None:
        return None
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _correction_evidence_governance(
    correction: NewMemoryCorrection,
) -> tuple[list[str], bool]:
    key = (
        "evidence_events"
        if correction.target_kind == CorrectionTargetKind.ASSERTION
        else "evidence_event_ids"
    )
    parsed: Any = correction.before.get(key)
    if parsed is None:
        return [], False
    for _ in range(2):
        if not isinstance(parsed, str):
            break
        try:
            parsed = json.loads(parsed)
        except json.JSONDecodeError:
            return [], True
    if isinstance(parsed, (list, tuple, set)):
        parsed = list(parsed)
    else:
        return [], True
    if any(not isinstance(event_id, str) or not event_id.strip() for event_id in parsed):
        return [], True
    return list(dict.fromkeys(event_id.strip() for event_id in parsed)), False


def _optional_text(value: str | None) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


__all__ = [
    "DEFAULT_DERIVATION_MAX_ATTEMPTS",
    "DEFAULT_DERIVATION_STALE_RUNNING_SECONDS",
    "MemoryCorrectionRepository",
]
