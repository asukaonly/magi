"""SQLite repository for correction records, rules, revisions, and jobs."""

from __future__ import annotations

import json
import time
import uuid
from collections.abc import Iterable, Mapping
from typing import Any

import aiosqlite

from ....core.sqlite import sqlite_connection_async
from .models import (
    CorrectionCreateResult,
    CorrectionRule,
    CorrectionTargetKind,
    MemoryCorrection,
    NewMemoryCorrection,
)


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
                audit_event_id, replacement_target_id, state, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'active', ?)
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
            ),
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


def _json_mapping(value: Mapping[str, Any] | None) -> str | None:
    if value is None:
        return None
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _optional_text(value: str | None) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


__all__ = ["MemoryCorrectionRepository"]
