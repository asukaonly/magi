"""SQLite persistence for history import previews and resumable jobs."""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any

from ...core.sqlite import sqlite_connection_async
from .models import (
    HistoryImportJob,
    HistoryImportParticipant,
    HistoryImportRecord,
    HistoryImportSourceSummary,
)


class HistoryImportStore:
    """Persist normalized records before they enter memory."""

    def __init__(self, *, db_path: str) -> None:
        self.db_path = str(Path(db_path).expanduser())

    async def find_active_by_fingerprint(
        self,
        fingerprint: str,
    ) -> HistoryImportJob | None:
        async with sqlite_connection_async(self.db_path) as db:
            async with db.execute(
                """
                SELECT *
                FROM history_import_jobs
                WHERE source_fingerprint = ? AND deleted_at IS NULL
                ORDER BY created_at DESC
                LIMIT 1
                """,
                (fingerprint,),
            ) as cursor:
                row = await cursor.fetchone()
        return await self.get_job(str(row["job_id"])) if row is not None else None

    async def create_preview(
        self,
        *,
        job: HistoryImportJob,
        records: list[HistoryImportRecord],
    ) -> HistoryImportJob:
        async with sqlite_connection_async(self.db_path) as db:
            await db.execute("BEGIN IMMEDIATE")
            try:
                await db.execute(
                    """
                    INSERT INTO history_import_jobs(
                        job_id, source_type, source_fingerprint,
                        source_files_json, included_files_json,
                        detected_kind, status,
                        total_records, meaningful_records,
                        quick_target_records, quick_max_records,
                        quick_imported_count, imported_count, projected_count,
                        self_participants_json, warnings_json, quick_ready,
                        error_text, created_at, updated_at, deleted_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        job.job_id,
                        job.source_type,
                        job.source_fingerprint,
                        json.dumps(job.source_files, ensure_ascii=False),
                        json.dumps(job.included_files, ensure_ascii=False),
                        job.detected_kind,
                        job.status,
                        job.total_records,
                        job.meaningful_records,
                        job.quick_target_records,
                        job.quick_max_records,
                        job.quick_imported_count,
                        job.imported_count,
                        job.projected_count,
                        json.dumps(job.self_participants, ensure_ascii=False),
                        json.dumps(job.warnings, ensure_ascii=False),
                        1 if job.quick_ready else 0,
                        job.error_text,
                        job.created_at,
                        job.updated_at,
                        job.deleted_at,
                    ),
                )
                await db.executemany(
                    """
                    INSERT INTO history_import_records(
                        record_id, job_id, source_name, session_id, session_seq,
                        speaker_name, speaker_role, content, event_at,
                        timestamp_confidence, meaningful, event_id,
                        raw_state, projection_state, created_at, updated_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    [
                        (
                            record.record_id,
                            record.job_id,
                            record.source_name,
                            record.session_id,
                            record.session_seq,
                            record.speaker_name,
                            record.speaker_role,
                            record.content,
                            record.event_at,
                            record.timestamp_confidence,
                            1 if record.meaningful else 0,
                            record.event_id,
                            record.raw_state,
                            record.projection_state,
                            record.created_at,
                            record.updated_at,
                        )
                        for record in records
                    ],
                )
                await db.commit()
            except BaseException:
                await db.rollback()
                raise
        result = await self.get_job(job.job_id)
        if result is None:
            raise RuntimeError("Created history import preview is missing")
        return result

    async def get_job(self, job_id: str) -> HistoryImportJob | None:
        async with sqlite_connection_async(self.db_path) as db:
            async with db.execute(
                "SELECT * FROM history_import_jobs WHERE job_id = ?",
                (job_id,),
            ) as cursor:
                row = await cursor.fetchone()
            if row is None:
                return None
            included_files = list(json.loads(row["included_files_json"] or "[]"))
            participants = await self._participants(
                db,
                job_id,
                included_files=included_files,
            )
            sources = await self._source_summaries(
                db,
                job_id,
                included_files=included_files,
            )
            previews = await self._preview_records(
                db,
                job_id,
                included_files=included_files,
            )
        return _job_from_row(
            row,
            participants=participants,
            sources=sources,
            preview_records=previews,
        )

    async def list_active_jobs(self, *, limit: int = 20) -> list[HistoryImportJob]:
        async with sqlite_connection_async(self.db_path) as db:
            async with db.execute(
                """
                SELECT job_id
                FROM history_import_jobs
                WHERE deleted_at IS NULL
                ORDER BY created_at DESC
                LIMIT ?
                """,
                (max(1, min(int(limit), 100)),),
            ) as cursor:
                rows = await cursor.fetchall()
        jobs: list[HistoryImportJob] = []
        for row in rows:
            job = await self.get_job(str(row["job_id"]))
            if job is not None:
                jobs.append(job)
        return jobs

    async def list_resumable_job_ids(self) -> list[str]:
        async with sqlite_connection_async(self.db_path) as db:
            async with db.execute(
                """
                SELECT job_id
                FROM history_import_jobs
                WHERE deleted_at IS NULL
                  AND quick_ready = 1
                  AND status IN ('running', 'ready')
                ORDER BY updated_at ASC
                """
            ) as cursor:
                rows = await cursor.fetchall()
        return [str(row[0]) for row in rows]

    async def update_selection(
        self,
        *,
        job_id: str,
        included_files: list[str],
    ) -> HistoryImportJob:
        now = time.time()
        normalized = list(dict.fromkeys(item.strip() for item in included_files if item.strip()))
        async with sqlite_connection_async(self.db_path) as db:
            await db.execute(
                """
                UPDATE history_import_jobs
                SET included_files_json = ?, updated_at = ?
                WHERE job_id = ?
                  AND deleted_at IS NULL
                  AND quick_ready = 0
                  AND imported_count = 0
                """,
                (json.dumps(normalized, ensure_ascii=False), now, job_id),
            )
            await db.commit()
        job = await self.get_job(job_id)
        if job is None:
            raise KeyError(job_id)
        return job

    async def set_scope(
        self,
        *,
        job_id: str,
        self_participants: list[str],
        included_files: list[str],
    ) -> HistoryImportJob:
        now = time.time()
        normalized = list(dict.fromkeys(item.strip() for item in self_participants if item.strip()))
        normalized_files = list(
            dict.fromkeys(item.strip() for item in included_files if item.strip())
        )
        async with sqlite_connection_async(self.db_path) as db:
            await db.execute("BEGIN IMMEDIATE")
            try:
                participant_placeholders = ",".join("?" for _ in normalized)
                file_placeholders = ",".join("?" for _ in normalized_files)
                await db.execute(
                    """
                    UPDATE history_import_records
                    SET speaker_role = 'other', updated_at = ?
                    WHERE job_id = ?
                    """,
                    (now, job_id),
                )
                if normalized:
                    await db.execute(
                        f"""
                        UPDATE history_import_records
                        SET speaker_role = 'user', updated_at = ?
                        WHERE job_id = ?
                          AND source_name IN ({file_placeholders})
                          AND speaker_name IN ({participant_placeholders})
                        """,
                        (
                            now,
                            job_id,
                            *normalized_files,
                            *normalized,
                        ),
                    )
                await db.execute(
                    f"""
                    UPDATE history_import_records
                    SET raw_state = CASE
                            WHEN source_name IN ({file_placeholders})
                            THEN raw_state
                            ELSE 'skipped'
                        END,
                        projection_state = CASE
                            WHEN source_name IN ({file_placeholders})
                                 AND speaker_role = 'user'
                            THEN projection_state
                            ELSE 'skipped'
                        END,
                        updated_at = ?
                    WHERE job_id = ?
                    """,
                    (*normalized_files, *normalized_files, now, job_id),
                )
                await db.execute(
                    f"""
                    UPDATE history_import_jobs
                    SET included_files_json = ?,
                        self_participants_json = ?,
                        status = 'running',
                        total_records = (
                            SELECT COUNT(*)
                            FROM history_import_records
                            WHERE job_id = ?
                              AND source_name IN ({file_placeholders})
                        ),
                        meaningful_records = (
                            SELECT COUNT(*)
                            FROM history_import_records
                            WHERE job_id = ?
                              AND source_name IN ({file_placeholders})
                              AND meaningful = 1
                        ),
                        error_text = NULL,
                        updated_at = ?
                    WHERE job_id = ? AND deleted_at IS NULL
                    """,
                    (
                        json.dumps(normalized_files, ensure_ascii=False),
                        json.dumps(normalized, ensure_ascii=False),
                        job_id,
                        *normalized_files,
                        job_id,
                        *normalized_files,
                        now,
                        job_id,
                    ),
                )
                await db.commit()
            except BaseException:
                await db.rollback()
                raise
        job = await self.get_job(job_id)
        if job is None:
            raise KeyError(job_id)
        return job

    async def select_quick_records(
        self,
        *,
        job_id: str,
        meaningful_user_target: int = 30,
    ) -> list[HistoryImportRecord]:
        job = await self.get_job(job_id)
        if job is None:
            raise KeyError(job_id)
        async with sqlite_connection_async(self.db_path) as db:
            async with db.execute(
                """
                SELECT *
                FROM history_import_records
                WHERE job_id = ? AND raw_state = 'pending'
                ORDER BY event_at DESC, session_id DESC, session_seq DESC
                LIMIT ?
                """,
                (job_id, job.quick_max_records),
            ) as cursor:
                rows = list(await cursor.fetchall())
        selected = rows[: job.quick_target_records]
        while (
            len(selected) < len(rows) and _meaningful_user_count(selected) < meaningful_user_target
        ):
            next_size = min(len(rows), len(selected) + 100)
            selected = rows[:next_size]
        return sorted(
            (_record_from_row(row) for row in selected),
            key=lambda item: (item.event_at, item.session_id, item.session_seq),
        )

    async def list_pending_raw_records(
        self,
        *,
        job_id: str,
        limit: int = 100,
    ) -> list[HistoryImportRecord]:
        return await self._list_records(
            job_id=job_id,
            where="raw_state = 'pending'",
            limit=limit,
        )

    async def list_pending_projection_records(
        self,
        *,
        job_id: str,
        limit: int = 50,
    ) -> list[HistoryImportRecord]:
        return await self._list_records(
            job_id=job_id,
            where="raw_state = 'stored' AND speaker_role = 'user' AND projection_state = 'pending'",
            limit=limit,
        )

    async def list_imported_event_ids(self, *, job_id: str) -> list[str]:
        async with sqlite_connection_async(self.db_path) as db:
            async with db.execute(
                """
                SELECT event_id
                FROM history_import_records
                WHERE job_id = ? AND raw_state = 'stored'
                ORDER BY event_at ASC, session_id ASC, session_seq ASC
                """,
                (job_id,),
            ) as cursor:
                rows = await cursor.fetchall()
        return [str(row[0]) for row in rows]

    async def list_first_contact_records(
        self,
        *,
        limit: int = 12,
    ) -> list[HistoryImportRecord]:
        async with sqlite_connection_async(self.db_path) as db:
            async with db.execute(
                """
                SELECT job_id
                FROM history_import_jobs
                WHERE deleted_at IS NULL
                  AND quick_ready = 1
                ORDER BY updated_at DESC
                LIMIT 1
                """
            ) as cursor:
                job_row = await cursor.fetchone()
            if job_row is None:
                return []
            async with db.execute(
                """
                SELECT *
                FROM history_import_records
                WHERE job_id = ?
                  AND speaker_role = 'user'
                  AND meaningful = 1
                  AND raw_state = 'stored'
                ORDER BY event_at DESC, session_id DESC, session_seq DESC
                LIMIT ?
                """,
                (str(job_row["job_id"]), max(1, min(int(limit), 50))),
            ) as cursor:
                rows = await cursor.fetchall()
        return [_record_from_row(row) for row in rows]

    async def mark_raw_stored(
        self,
        *,
        job_id: str,
        record_id: str,
        quick: bool,
    ) -> None:
        now = time.time()
        async with sqlite_connection_async(self.db_path) as db:
            await db.execute("BEGIN IMMEDIATE")
            try:
                cursor = await db.execute(
                    """
                    UPDATE history_import_records
                    SET raw_state = 'stored', updated_at = ?
                    WHERE record_id = ? AND job_id = ? AND raw_state = 'pending'
                    """,
                    (now, record_id, job_id),
                )
                if cursor.rowcount:
                    await db.execute(
                        """
                        UPDATE history_import_jobs
                        SET imported_count = imported_count + 1,
                            quick_imported_count = quick_imported_count + ?,
                            updated_at = ?
                        WHERE job_id = ?
                        """,
                        (1 if quick else 0, now, job_id),
                    )
                await db.commit()
            except BaseException:
                await db.rollback()
                raise

    async def mark_projected(self, *, job_id: str, record_id: str) -> None:
        now = time.time()
        async with sqlite_connection_async(self.db_path) as db:
            await db.execute("BEGIN IMMEDIATE")
            try:
                cursor = await db.execute(
                    """
                    UPDATE history_import_records
                    SET projection_state = 'projected', updated_at = ?
                    WHERE record_id = ? AND job_id = ?
                      AND projection_state = 'pending'
                    """,
                    (now, record_id, job_id),
                )
                if cursor.rowcount:
                    await db.execute(
                        """
                        UPDATE history_import_jobs
                        SET projected_count = projected_count + 1, updated_at = ?
                        WHERE job_id = ?
                        """,
                        (now, job_id),
                    )
                await db.commit()
            except BaseException:
                await db.rollback()
                raise

    async def mark_raw_skipped(self, *, job_id: str, record_id: str) -> None:
        now = time.time()
        async with sqlite_connection_async(self.db_path) as db:
            await db.execute(
                """
                UPDATE history_import_records
                SET raw_state = 'skipped',
                    projection_state = 'skipped',
                    updated_at = ?
                WHERE record_id = ? AND job_id = ? AND raw_state = 'pending'
                """,
                (now, record_id, job_id),
            )
            await db.commit()

    async def mark_projection_skipped(
        self,
        *,
        job_id: str,
        record_id: str,
    ) -> None:
        now = time.time()
        async with sqlite_connection_async(self.db_path) as db:
            await db.execute(
                """
                UPDATE history_import_records
                SET projection_state = 'skipped', updated_at = ?
                WHERE record_id = ? AND job_id = ?
                  AND projection_state = 'pending'
                """,
                (now, record_id, job_id),
            )
            await db.commit()

    async def mark_quick_ready(self, *, job_id: str) -> None:
        await self._update_job(
            job_id,
            "quick_ready = 1, status = 'ready', error_text = NULL",
        )

    async def mark_running(self, *, job_id: str) -> None:
        await self._update_job(job_id, "status = 'running', error_text = NULL")

    async def mark_completed(self, *, job_id: str) -> None:
        await self._update_job(job_id, "status = 'completed', error_text = NULL")

    async def mark_failed(self, *, job_id: str, error_text: str) -> None:
        await self._update_job(
            job_id,
            "status = 'failed', error_text = ?",
            (str(error_text)[:500],),
        )

    async def mark_deleted(self, *, job_id: str) -> None:
        now = time.time()
        await self._update_job(
            job_id,
            "status = 'deleted', deleted_at = ?, error_text = NULL",
            (now,),
        )

    async def _update_job(
        self,
        job_id: str,
        assignments: str,
        values: tuple[Any, ...] = (),
    ) -> None:
        now = time.time()
        async with sqlite_connection_async(self.db_path) as db:
            await db.execute(
                f"""
                UPDATE history_import_jobs
                SET {assignments}, updated_at = ?
                WHERE job_id = ? AND deleted_at IS NULL
                """,
                (*values, now, job_id),
            )
            await db.commit()

    async def _list_records(
        self,
        *,
        job_id: str,
        where: str,
        limit: int,
    ) -> list[HistoryImportRecord]:
        async with sqlite_connection_async(self.db_path) as db:
            async with db.execute(
                f"""
                SELECT *
                FROM history_import_records
                WHERE job_id = ? AND {where}
                ORDER BY event_at ASC, session_id ASC, session_seq ASC
                LIMIT ?
                """,
                (job_id, max(1, int(limit))),
            ) as cursor:
                rows = await cursor.fetchall()
        return [_record_from_row(row) for row in rows]

    @staticmethod
    async def _participants(
        db: Any,
        job_id: str,
        *,
        included_files: list[str],
    ) -> list[HistoryImportParticipant]:
        if not included_files:
            return []
        placeholders = ",".join("?" for _ in included_files)
        async with db.execute(
            f"""
            SELECT speaker_name,
                   COUNT(*) AS message_count,
                   SUM(meaningful) AS meaningful_count
            FROM history_import_records
            WHERE job_id = ? AND source_name IN ({placeholders})
            GROUP BY speaker_name
            ORDER BY message_count DESC, speaker_name ASC
            """,
            (job_id, *included_files),
        ) as cursor:
            rows = await cursor.fetchall()
        participants: list[HistoryImportParticipant] = []
        for row in rows:
            async with db.execute(
                """
                SELECT content
                FROM history_import_records
                WHERE job_id = ?
                  AND speaker_name = ?
                  AND source_name IN ({placeholders})
                ORDER BY meaningful DESC, LENGTH(content) DESC
                LIMIT 1
                """.format(placeholders=placeholders),
                (job_id, row["speaker_name"], *included_files),
            ) as cursor:
                sample_row = await cursor.fetchone()
            participants.append(
                HistoryImportParticipant(
                    name=str(row["speaker_name"]),
                    message_count=int(row["message_count"]),
                    meaningful_count=int(row["meaningful_count"] or 0),
                    sample=str(sample_row["content"] if sample_row else "")[:160],
                )
            )
        return participants

    @staticmethod
    async def _source_summaries(
        db: Any,
        job_id: str,
        *,
        included_files: list[str],
    ) -> list[HistoryImportSourceSummary]:
        async with db.execute(
            """
            SELECT source_name,
                   COUNT(*) AS record_count,
                   SUM(meaningful) AS meaningful_count,
                   MIN(event_at) AS first_event_at,
                   MAX(event_at) AS last_event_at,
                   GROUP_CONCAT(DISTINCT timestamp_confidence) AS timestamp_confidences,
                   SUM(CASE WHEN speaker_name = ? THEN 1 ELSE 0 END) AS document_records
            FROM history_import_records
            WHERE job_id = ?
            GROUP BY source_name
            ORDER BY source_name COLLATE NOCASE ASC
            """,
            ("__document_author__", job_id),
        ) as cursor:
            rows = await cursor.fetchall()
        included = set(included_files)
        summaries: list[HistoryImportSourceSummary] = []
        for row in rows:
            source_name = str(row["source_name"])
            record_count = int(row["record_count"])
            document_records = int(row["document_records"] or 0)
            if document_records == record_count:
                detected_kind = "document"
            elif document_records == 0:
                detected_kind = "chat"
            else:
                detected_kind = "mixed"
            async with db.execute(
                """
                SELECT content
                FROM history_import_records
                WHERE job_id = ? AND source_name = ?
                ORDER BY meaningful DESC, LENGTH(content) DESC
                LIMIT 1
                """,
                (job_id, source_name),
            ) as cursor:
                sample_row = await cursor.fetchone()
            confidence_values = {
                item.strip()
                for item in str(row["timestamp_confidences"] or "").split(",")
                if item.strip()
            }
            summaries.append(
                HistoryImportSourceSummary(
                    source_name=source_name,
                    detected_kind=detected_kind,
                    record_count=record_count,
                    meaningful_count=int(row["meaningful_count"] or 0),
                    first_event_at=float(row["first_event_at"]),
                    last_event_at=float(row["last_event_at"]),
                    timestamp_confidence=(
                        next(iter(confidence_values)) if len(confidence_values) == 1 else "mixed"
                    ),
                    sample=str(sample_row["content"] if sample_row else "")[:240],
                    included=source_name in included,
                )
            )
        return summaries

    @staticmethod
    async def _preview_records(
        db: Any,
        job_id: str,
        *,
        included_files: list[str],
    ) -> list[HistoryImportRecord]:
        if not included_files:
            return []
        placeholders = ",".join("?" for _ in included_files)
        async with db.execute(
            f"""
            SELECT *
            FROM history_import_records
            WHERE job_id = ? AND source_name IN ({placeholders})
            ORDER BY event_at DESC, session_id DESC, session_seq DESC
            LIMIT 6
            """,
            (job_id, *included_files),
        ) as cursor:
            rows = await cursor.fetchall()
        return sorted(
            (_record_from_row(row) for row in rows),
            key=lambda item: (item.event_at, item.session_id, item.session_seq),
        )


def _meaningful_user_count(rows: list[Any]) -> int:
    return sum(
        1 for row in rows if str(row["speaker_role"] or "") == "user" and bool(row["meaningful"])
    )


def _record_from_row(row: Any) -> HistoryImportRecord:
    return HistoryImportRecord(
        record_id=str(row["record_id"]),
        job_id=str(row["job_id"]),
        source_name=str(row["source_name"]),
        session_id=str(row["session_id"]),
        session_seq=int(row["session_seq"]),
        speaker_name=str(row["speaker_name"]),
        speaker_role=str(row["speaker_role"]),
        content=str(row["content"]),
        event_at=float(row["event_at"]),
        timestamp_confidence=str(row["timestamp_confidence"]),
        meaningful=bool(row["meaningful"]),
        event_id=str(row["event_id"]),
        raw_state=str(row["raw_state"]),
        projection_state=str(row["projection_state"]),
        created_at=float(row["created_at"]),
        updated_at=float(row["updated_at"]),
    )


def _job_from_row(
    row: Any,
    *,
    participants: list[HistoryImportParticipant],
    sources: list[HistoryImportSourceSummary],
    preview_records: list[HistoryImportRecord],
) -> HistoryImportJob:
    return HistoryImportJob(
        job_id=str(row["job_id"]),
        source_type=str(row["source_type"]),
        source_fingerprint=str(row["source_fingerprint"]),
        source_files=list(json.loads(row["source_files_json"] or "[]")),
        included_files=list(json.loads(row["included_files_json"] or "[]")),
        detected_kind=str(row["detected_kind"]),
        status=str(row["status"]),
        total_records=int(row["total_records"]),
        meaningful_records=int(row["meaningful_records"]),
        quick_target_records=int(row["quick_target_records"]),
        quick_max_records=int(row["quick_max_records"]),
        quick_imported_count=int(row["quick_imported_count"]),
        imported_count=int(row["imported_count"]),
        projected_count=int(row["projected_count"]),
        self_participants=list(json.loads(row["self_participants_json"] or "[]")),
        warnings=list(json.loads(row["warnings_json"] or "[]")),
        quick_ready=bool(row["quick_ready"]),
        error_text=str(row["error_text"]) if row["error_text"] is not None else None,
        created_at=float(row["created_at"]),
        updated_at=float(row["updated_at"]),
        deleted_at=float(row["deleted_at"]) if row["deleted_at"] is not None else None,
        participants=participants,
        sources=sources,
        preview_records=preview_records,
    )


__all__ = ["HistoryImportStore"]
