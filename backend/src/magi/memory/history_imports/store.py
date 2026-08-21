"""SQLite persistence for history import previews and resumable jobs."""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any

from ...core.sqlite import sqlite_connection_async
from .models import (
    HistoryImportAppendResult,
    HistoryImportJob,
    HistoryImportParticipant,
    HistoryImportRecord,
    HistoryImportSourceSummary,
    ParsedHistorySource,
)

_SOURCE_IDENTITY_READ_BATCH_SIZE = 400
_SESSION_PREFIX_READ_BATCH_SIZE = 300

_RECORD_SELECT = """
    SELECT membership.job_record_id,
           membership.job_id,
           source.source_record_key,
           source.file_fingerprint,
           source.source_name,
           source.source_id,
           source.source_kind,
           source.parsed_session_key,
           source.session_id,
           membership.source_order AS session_seq,
           source.speaker_id,
           source.speaker_name,
           source.message_key,
           source.parent_message_key,
           source.speaker_role,
           source.content,
           source.event_at,
           source.timestamp_confidence,
           source.timestamp_anchor_source,
           source.calendar_timezone_id,
           source.meaningful,
           source.event_id,
           membership.raw_state,
           membership.projection_state,
           membership.created_at,
           membership.updated_at
    FROM history_import_job_records AS membership
    JOIN history_import_source_records AS source
      ON source.source_record_key = membership.source_record_key
"""

_CHAT_SESSION_ANCHOR_CTE = """
    WITH session_anchors AS (
        SELECT anchor_membership.job_id,
               anchor_source.session_id,
               MAX(anchor_source.event_at) AS latest_event_at
        FROM history_import_job_records AS anchor_membership
        JOIN history_import_source_records AS anchor_source
          ON anchor_source.source_record_key = anchor_membership.source_record_key
        WHERE anchor_membership.job_id = ?
        GROUP BY anchor_membership.job_id, anchor_source.session_id
    )
"""

_CHAT_SESSION_ANCHOR_JOIN = """
    JOIN session_anchors AS session_anchor
      ON session_anchor.job_id = membership.job_id
     AND session_anchor.session_id = source.session_id
"""


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
                async with db.execute(
                    """
                    SELECT job_id
                    FROM history_import_jobs
                    WHERE source_fingerprint = ? AND deleted_at IS NULL
                    ORDER BY created_at DESC
                    LIMIT 1
                    """,
                    (job.source_fingerprint,),
                ) as cursor:
                    existing_row = await cursor.fetchone()
                if existing_row is not None:
                    await db.rollback()
                    existing = await self.get_job(str(existing_row["job_id"]))
                    if existing is None:
                        raise RuntimeError("Existing history import preview is missing")
                    return existing
                await db.execute(
                    """
                    INSERT INTO history_import_jobs(
                        job_id, source_type, source_fingerprint,
                        source_ids_json, included_source_ids_json,
                        importer_plugin_id, importer_id, importer_format_version,
                        detected_kind, status,
                        total_records, meaningful_records,
                        quick_target_records, quick_max_records,
                        quick_imported_count, imported_count, projected_count,
                        self_participant_ids_json, warnings_json, quick_ready,
                        error_text, created_at, updated_at, deleted_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        job.job_id,
                        job.source_type,
                        job.source_fingerprint,
                        json.dumps(job.source_ids, ensure_ascii=False),
                        json.dumps(job.included_source_ids, ensure_ascii=False),
                        job.importer_plugin_id,
                        job.importer_id,
                        job.importer_format_version,
                        job.detected_kind,
                        job.status,
                        job.total_records,
                        job.meaningful_records,
                        job.quick_target_records,
                        job.quick_max_records,
                        job.quick_imported_count,
                        job.imported_count,
                        job.projected_count,
                        json.dumps(job.self_participant_ids, ensure_ascii=False),
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
                    INSERT INTO history_import_source_records(
                        source_record_key, file_fingerprint, source_id, source_name, source_kind,
                        parsed_session_key, session_id, session_seq,
                        speaker_id, speaker_name, message_key, parent_message_key,
                        speaker_role, content, event_at,
                        timestamp_confidence, timestamp_anchor_source,
                        calendar_timezone_id, meaningful, event_id, created_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(source_record_key) DO NOTHING
                    """,
                    [
                        (
                            record.source_record_key,
                            record.file_fingerprint,
                            record.source_id,
                            record.source_name,
                            record.source_kind,
                            record.parsed_session_key,
                            record.session_id,
                            record.session_seq,
                            record.speaker_id,
                            record.speaker_name,
                            record.message_key,
                            record.parent_message_key,
                            record.speaker_role,
                            record.content,
                            record.event_at,
                            record.timestamp_confidence,
                            record.timestamp_anchor_source,
                            record.calendar_timezone_id,
                            1 if record.meaningful else 0,
                            record.event_id,
                            record.created_at,
                        )
                        for record in records
                    ],
                )
                stored_identities = await _load_source_identity_rows(
                    db,
                    [record.source_record_key for record in records],
                )
                for record in records:
                    stored = stored_identities.get(record.source_record_key)
                    if stored is None or not _same_source_identity(record, stored):
                        raise ValueError("history_import_source_identity_conflict")
                await db.executemany(
                    """
                    INSERT INTO history_import_job_records(
                        job_record_id, job_id, source_record_key,
                        source_order, raw_state, projection_state, created_at, updated_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    [
                        (
                            record.job_record_id,
                            record.job_id,
                            record.source_record_key,
                            record.session_seq,
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

    async def append_preview(
        self,
        *,
        job_id: str,
        records: list[HistoryImportRecord],
        warnings: list[str],
        allow_existing_source_updates: bool,
    ) -> HistoryImportAppendResult:
        """Append unseen records to an unconfirmed preview in one transaction."""

        now = time.time()
        incoming_source_ids = list(dict.fromkeys(record.source_id for record in records))
        async with sqlite_connection_async(self.db_path) as db:
            await db.execute("BEGIN IMMEDIATE")
            try:
                async with db.execute(
                    "SELECT * FROM history_import_jobs WHERE job_id = ?",
                    (job_id,),
                ) as cursor:
                    row = await cursor.fetchone()
                if row is None or row["deleted_at"] is not None:
                    raise KeyError(job_id)
                if (
                    str(row["status"]) != "preview_ready"
                    or bool(row["quick_ready"])
                    or int(row["imported_count"]) > 0
                    or json.loads(row["self_participant_ids_json"] or "[]")
                ):
                    raise ValueError("history_import_selection_locked")

                existing_source_ids = list(json.loads(row["source_ids_json"] or "[]"))
                existing_source_set = set(existing_source_ids)
                existing_record_keys = await _load_job_record_keys(
                    db,
                    job_id=job_id,
                    source_record_keys=[record.source_record_key for record in records],
                )
                records_by_source: dict[str, list[HistoryImportRecord]] = {}
                for record in records:
                    records_by_source.setdefault(record.source_id, []).append(record)
                duplicate_source_count = sum(
                    1
                    for source_records in records_by_source.values()
                    if source_records
                    and all(
                        record.source_record_key in existing_record_keys
                        for record in source_records
                    )
                )
                new_records = [
                    record
                    for record in records
                    if record.source_record_key not in existing_record_keys
                ]
                if not allow_existing_source_updates and any(
                    source_id in existing_source_set
                    and any(
                        record.source_record_key not in existing_record_keys
                        for record in source_records
                    )
                    for source_id, source_records in records_by_source.items()
                ):
                    raise ValueError("history_import_source_name_conflict")

                added_source_ids = [
                    source_id
                    for source_id in incoming_source_ids
                    if source_id not in existing_source_set
                    and any(
                        record.source_record_key not in existing_record_keys
                        for record in records_by_source[source_id]
                    )
                ]
                merged_source_ids = [*existing_source_ids, *added_source_ids]
                included_source_ids = list(json.loads(row["included_source_ids_json"] or "[]"))
                merged_included_source_ids = [*included_source_ids, *added_source_ids]

                if records:
                    await db.executemany(
                        """
                        INSERT INTO history_import_source_records(
                            source_record_key, file_fingerprint, source_id, source_name,
                            source_kind, parsed_session_key, session_id, session_seq,
                            speaker_id, speaker_name, message_key, parent_message_key,
                            speaker_role, content, event_at,
                            timestamp_confidence, timestamp_anchor_source,
                            calendar_timezone_id, meaningful, event_id, created_at
                        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                        ON CONFLICT(source_record_key) DO NOTHING
                        """,
                        [
                            (
                                record.source_record_key,
                                record.file_fingerprint,
                                record.source_id,
                                record.source_name,
                                record.source_kind,
                                record.parsed_session_key,
                                record.session_id,
                                record.session_seq,
                                record.speaker_id,
                                record.speaker_name,
                                record.message_key,
                                record.parent_message_key,
                                record.speaker_role,
                                record.content,
                                record.event_at,
                                record.timestamp_confidence,
                                record.timestamp_anchor_source,
                                record.calendar_timezone_id,
                                1 if record.meaningful else 0,
                                record.event_id,
                                record.created_at,
                            )
                            for record in records
                        ],
                    )
                    stored_identities = await _load_source_identity_rows(
                        db,
                        [record.source_record_key for record in records],
                    )
                    for record in records:
                        stored = stored_identities.get(record.source_record_key)
                        if stored is None or not _same_source_identity(record, stored):
                            raise ValueError("history_import_source_identity_conflict")

                if new_records:
                    await db.executemany(
                        """
                        INSERT INTO history_import_job_records(
                            job_record_id, job_id, source_record_key,
                            source_order, raw_state, projection_state, created_at, updated_at
                        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                        """,
                        [
                            (
                                record.job_record_id,
                                record.job_id,
                                record.source_record_key,
                                record.session_seq,
                                record.raw_state,
                                record.projection_state,
                                record.created_at,
                                record.updated_at,
                            )
                            for record in new_records
                        ],
                    )

                await db.execute(
                    """
                    UPDATE history_import_jobs
                    SET source_ids_json = ?,
                        included_source_ids_json = ?,
                        total_records = total_records + ?,
                        meaningful_records = meaningful_records + ?,
                        warnings_json = ?,
                        updated_at = ?
                    WHERE job_id = ?
                    """,
                    (
                        json.dumps(merged_source_ids, ensure_ascii=False),
                        json.dumps(merged_included_source_ids, ensure_ascii=False),
                        len(new_records),
                        sum(1 for record in new_records if record.meaningful),
                        json.dumps(warnings, ensure_ascii=False),
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
        return HistoryImportAppendResult(
            job=job,
            added_source_count=len(added_source_ids),
            duplicate_source_count=duplicate_source_count,
        )

    async def validate_platform_session_prefixes(
        self,
        *,
        importer_plugin_id: str,
        importer_id: str,
        importer_format_version: str,
        sources: list[ParsedHistorySource],
    ) -> None:
        """Require incremental exports to preserve existing message order prefixes."""

        incoming_prefixes = {
            (source.source_id, source.session_key): [
                str(record["message_key"])
                for record in sorted(
                    source.records,
                    key=lambda record: int(record.get("source_order", 0)),
                )
            ]
            for source in sources
        }
        async with sqlite_connection_async(self.db_path) as db:
            reserved_prefixes = await _load_reserved_session_prefixes(
                db,
                importer_plugin_id=importer_plugin_id,
                importer_id=importer_id,
                importer_format_version=importer_format_version,
                session_identities=list(incoming_prefixes),
            )
        _require_append_only_session_prefixes(
            incoming_prefixes=incoming_prefixes,
            reserved_prefixes=reserved_prefixes,
        )

    async def get_job(self, job_id: str) -> HistoryImportJob | None:
        """Load one job together with preview-only participant and source details."""

        async with sqlite_connection_async(self.db_path) as db:
            async with db.execute(
                "SELECT * FROM history_import_jobs WHERE job_id = ?",
                (job_id,),
            ) as cursor:
                row = await cursor.fetchone()
            if row is None:
                return None
            included_source_ids = list(json.loads(row["included_source_ids_json"] or "[]"))
            participants = await self._participants(
                db,
                job_id,
                included_source_ids=included_source_ids,
            )
            sources = await self._source_summaries(
                db,
                job_id,
                included_source_ids=included_source_ids,
            )
            previews = await self._preview_records(
                db,
                job_id,
                included_source_ids=included_source_ids,
            )
        return _job_from_row(
            row,
            participants=participants,
            sources=sources,
            preview_records=previews,
        )

    async def get_job_progress(self, job_id: str) -> HistoryImportJob | None:
        """Load lifecycle counters without scanning imported record content."""

        async with sqlite_connection_async(self.db_path) as db:
            async with db.execute(
                "SELECT * FROM history_import_jobs WHERE job_id = ?",
                (job_id,),
            ) as cursor:
                row = await cursor.fetchone()
        if row is None:
            return None
        return _job_from_row(
            row,
            participants=[],
            sources=[],
            preview_records=[],
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
            job = await self.get_job_progress(str(row["job_id"]))
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

    async def list_quick_resumable_job_ids(self) -> list[str]:
        """List confirmed imports interrupted before the quick-ready boundary."""

        async with sqlite_connection_async(self.db_path) as db:
            async with db.execute(
                """
                SELECT job_id
                FROM history_import_jobs
                WHERE deleted_at IS NULL
                  AND quick_ready = 0
                  AND status = 'running'
                  AND json_array_length(included_source_ids_json) > 0
                  AND json_array_length(self_participant_ids_json) > 0
                ORDER BY updated_at ASC
                """
            ) as cursor:
                rows = await cursor.fetchall()
        return [str(row[0]) for row in rows]

    async def update_selection(
        self,
        *,
        job_id: str,
        included_source_ids: list[str],
    ) -> HistoryImportJob:
        now = time.time()
        normalized = list(
            dict.fromkeys(item.strip() for item in included_source_ids if item.strip())
        )
        async with sqlite_connection_async(self.db_path) as db:
            cursor = await db.execute(
                """
                UPDATE history_import_jobs
                SET included_source_ids_json = ?, updated_at = ?
                WHERE job_id = ?
                  AND deleted_at IS NULL
                  AND status = 'preview_ready'
                  AND quick_ready = 0
                  AND imported_count = 0
                  AND json_array_length(self_participant_ids_json) = 0
                """,
                (json.dumps(normalized, ensure_ascii=False), now, job_id),
            )
            await db.commit()
            if not cursor.rowcount:
                async with db.execute(
                    "SELECT deleted_at FROM history_import_jobs WHERE job_id = ?",
                    (job_id,),
                ) as existing_cursor:
                    existing = await existing_cursor.fetchone()
                if existing is None or existing["deleted_at"] is not None:
                    raise KeyError(job_id)
                raise ValueError("history_import_selection_locked")
        job = await self.get_job(job_id)
        if job is None:
            raise KeyError(job_id)
        return job

    async def set_scope(
        self,
        *,
        job_id: str,
        self_participant_ids: list[str],
        included_source_ids: list[str],
    ) -> HistoryImportJob:
        now = time.time()
        normalized = list(
            dict.fromkeys(item.strip() for item in self_participant_ids if item.strip())
        )
        normalized_files = list(
            dict.fromkeys(item.strip() for item in included_source_ids if item.strip())
        )
        async with sqlite_connection_async(self.db_path) as db:
            await db.execute("BEGIN IMMEDIATE")
            try:
                async with db.execute(
                    """
                    SELECT importer_plugin_id, importer_id, importer_format_version,
                           included_source_ids_json, self_participant_ids_json,
                           status, quick_ready, imported_count
                    FROM history_import_jobs
                    WHERE job_id = ? AND deleted_at IS NULL
                    """,
                    (job_id,),
                ) as cursor:
                    importer_row = await cursor.fetchone()
                if importer_row is None:
                    raise KeyError(job_id)
                committed_participants = list(
                    json.loads(importer_row["self_participant_ids_json"] or "[]")
                )
                committed_sources = list(
                    json.loads(importer_row["included_source_ids_json"] or "[]")
                )
                if committed_participants:
                    if set(committed_participants) == set(normalized) and set(
                        committed_sources
                    ) == set(normalized_files):
                        await db.commit()
                        job = await self.get_job_progress(job_id)
                        if job is None:
                            raise KeyError(job_id)
                        return job
                    raise ValueError("history_import_scope_conflict")
                if (
                    str(importer_row["status"]) != "preview_ready"
                    or bool(importer_row["quick_ready"])
                    or int(importer_row["imported_count"] or 0) > 0
                ):
                    raise ValueError("history_import_scope_conflict")
                importer_identity = tuple(
                    str(importer_row[column] or "").strip()
                    for column in (
                        "importer_plugin_id",
                        "importer_id",
                        "importer_format_version",
                    )
                )
                if all(importer_identity):
                    incoming_prefixes = await _load_job_session_prefixes(
                        db,
                        job_id=job_id,
                        included_source_ids=normalized_files,
                    )
                    reserved_prefixes = await _load_reserved_session_prefixes(
                        db,
                        importer_plugin_id=importer_identity[0],
                        importer_id=importer_identity[1],
                        importer_format_version=importer_identity[2],
                        session_identities=list(incoming_prefixes),
                    )
                    _require_append_only_session_prefixes(
                        incoming_prefixes=incoming_prefixes,
                        reserved_prefixes=reserved_prefixes,
                    )
                participant_placeholders = ",".join("?" for _ in normalized)
                file_placeholders = ",".join("?" for _ in normalized_files)
                async with db.execute(
                    f"""
                    SELECT source.source_record_key
                    FROM history_import_source_records AS source
                    JOIN history_import_job_records AS membership
                      ON membership.source_record_key = source.source_record_key
                    WHERE membership.job_id = ?
                      AND source.source_id IN ({file_placeholders})
                      AND source.speaker_role != 'unknown'
                      AND source.speaker_role != CASE
                          WHEN source.speaker_id IN ({participant_placeholders})
                          THEN 'user'
                          ELSE 'other'
                      END
                    LIMIT 1
                    """,
                    (job_id, *normalized_files, *normalized),
                ) as cursor:
                    role_conflict = await cursor.fetchone()
                if role_conflict is not None:
                    raise ValueError("history_import_speaker_role_conflict")
                await db.execute(
                    f"""
                    UPDATE history_import_source_records
                    SET speaker_role = CASE
                            WHEN speaker_id IN ({participant_placeholders})
                            THEN 'user'
                            ELSE 'other'
                        END
                    WHERE speaker_role = 'unknown'
                      AND source_id IN ({file_placeholders})
                      AND source_record_key IN (
                          SELECT source_record_key
                          FROM history_import_job_records
                          WHERE job_id = ?
                      )
                    """,
                    (*normalized, *normalized_files, job_id),
                )
                await db.execute(
                    f"""
                    UPDATE history_import_job_records
                    SET raw_state = CASE
                            WHEN source_record_key IN (
                                SELECT source_record_key
                                FROM history_import_source_records
                                WHERE source_id IN ({file_placeholders})
                            )
                            THEN raw_state
                            ELSE 'skipped'
                        END,
                        projection_state = CASE
                            WHEN source_record_key IN (
                                SELECT source_record_key
                                FROM history_import_source_records
                                WHERE source_id IN ({file_placeholders})
                            )
                                 AND source_record_key IN (
                                     SELECT source_record_key
                                     FROM history_import_source_records
                                     WHERE speaker_role = 'user'
                                 )
                            THEN projection_state
                            ELSE 'skipped'
                        END,
                        updated_at = ?
                    WHERE job_id = ?
                    """,
                    (*normalized_files, *normalized_files, now, job_id),
                )
                job_cursor = await db.execute(
                    f"""
                    UPDATE history_import_jobs
                    SET included_source_ids_json = ?,
                        self_participant_ids_json = ?,
                        status = 'running',
                        total_records = (
                            SELECT COUNT(*)
                            FROM history_import_job_records AS membership
                            JOIN history_import_source_records AS source
                              ON source.source_record_key = membership.source_record_key
                            WHERE membership.job_id = ?
                              AND source.source_id IN ({file_placeholders})
                        ),
                        meaningful_records = (
                            SELECT COUNT(*)
                            FROM history_import_job_records AS membership
                            JOIN history_import_source_records AS source
                              ON source.source_record_key = membership.source_record_key
                            WHERE membership.job_id = ?
                              AND source.source_id IN ({file_placeholders})
                              AND source.meaningful = 1
                        ),
                        error_text = NULL,
                        updated_at = ?
                    WHERE job_id = ?
                      AND deleted_at IS NULL
                      AND status = 'preview_ready'
                      AND quick_ready = 0
                      AND imported_count = 0
                      AND json_array_length(self_participant_ids_json) = 0
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
                if job_cursor.rowcount != 1:
                    raise ValueError("history_import_scope_conflict")
                await db.commit()
            except BaseException:
                await db.rollback()
                raise
        job = await self.get_job_progress(job_id)
        if job is None:
            raise KeyError(job_id)
        return job

    async def list_participants_for_sources(
        self,
        *,
        job_id: str,
        included_source_ids: list[str],
    ) -> list[HistoryImportParticipant]:
        """Return participant choices for one proposed source selection."""

        if not included_source_ids:
            return []
        async with sqlite_connection_async(self.db_path) as db:
            return await self._participants(
                db,
                job_id,
                included_source_ids=included_source_ids,
            )

    async def select_quick_records(
        self,
        *,
        job_id: str,
        meaningful_user_target: int = 30,
    ) -> list[HistoryImportRecord]:
        job = await self.get_job_progress(job_id)
        if job is None:
            raise KeyError(job_id)
        if job.source_type == "platform_chat":
            query = f"""
                {_CHAT_SESSION_ANCHOR_CTE}
                {_RECORD_SELECT}
                {_CHAT_SESSION_ANCHOR_JOIN}
                WHERE membership.job_id = ? AND membership.raw_state = 'pending'
                ORDER BY session_anchor.latest_event_at DESC,
                         source.session_id ASC, membership.source_order ASC
                LIMIT ?
                """
            params = (job_id, job_id, job.quick_max_records)
        else:
            query = f"""
                {_RECORD_SELECT}
                WHERE membership.job_id = ? AND membership.raw_state = 'pending'
                ORDER BY source.event_at DESC, source.session_id DESC,
                         membership.source_order DESC
                LIMIT ?
                """
            params = (job_id, job.quick_max_records)
        async with sqlite_connection_async(self.db_path) as db:
            async with db.execute(query, params) as cursor:
                rows = list(await cursor.fetchall())
        selected = rows[: job.quick_target_records]
        while (
            len(selected) < len(rows) and _meaningful_user_count(selected) < meaningful_user_target
        ):
            next_size = min(len(rows), len(selected) + 100)
            selected = rows[:next_size]
        records = [_record_from_row(row) for row in selected]
        if job.source_type == "platform_chat":
            return records
        return sorted(records, key=lambda item: (item.event_at, item.session_id, item.session_seq))

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

    async def list_source_records(
        self,
        *,
        job_id: str,
        source_id: str,
        limit: int,
    ) -> list[HistoryImportRecord]:
        """Return one source in its original order for reader-facing preview."""

        async with sqlite_connection_async(self.db_path) as db:
            async with db.execute(
                f"""
                {_RECORD_SELECT}
                WHERE membership.job_id = ? AND source.source_id = ?
                ORDER BY source.session_id ASC, membership.source_order ASC
                LIMIT ?
                """,
                (job_id, source_id, max(1, min(int(limit), 501))),
            ) as cursor:
                rows = await cursor.fetchall()
        return [_record_from_row(row) for row in rows]

    async def list_imported_event_ids(self, *, job_id: str) -> list[str]:
        async with sqlite_connection_async(self.db_path) as db:
            async with db.execute(
                """
                SELECT source.event_id
                FROM history_import_job_records AS membership
                JOIN history_import_source_records AS source
                  ON source.source_record_key = membership.source_record_key
                WHERE membership.job_id = ? AND membership.raw_state = 'stored'
                ORDER BY source.event_at ASC, source.session_id ASC,
                         membership.source_order ASC
                """,
                (job_id,),
            ) as cursor:
                rows = await cursor.fetchall()
        return [str(row[0]) for row in rows]

    async def list_unreferenced_event_ids_for_delete(self, *, job_id: str) -> list[str]:
        """Return stored events whose final active job membership is being deleted."""

        async with sqlite_connection_async(self.db_path) as db:
            async with db.execute(
                """
                SELECT source.event_id
                FROM history_import_job_records AS target
                JOIN history_import_source_records AS source
                  ON source.source_record_key = target.source_record_key
                WHERE target.job_id = ?
                  AND target.raw_state != 'skipped'
                  AND NOT EXISTS (
                      SELECT 1
                      FROM history_import_job_records AS other
                      JOIN history_import_jobs AS other_job
                        ON other_job.job_id = other.job_id
                      WHERE other.source_record_key = target.source_record_key
                        AND other.job_id != target.job_id
                        AND other_job.deleted_at IS NULL
                        AND other_job.status != 'preview_ready'
                        AND json_array_length(other_job.self_participant_ids_json) > 0
                        AND other.raw_state != 'skipped'
                        AND EXISTS (
                            SELECT 1
                            FROM json_each(other_job.included_source_ids_json)
                            WHERE CAST(value AS TEXT) = source.source_id
                        )
                  )
                ORDER BY source.event_at, source.session_id, target.source_order
                """,
                (job_id,),
            ) as cursor:
                rows = await cursor.fetchall()
        return [str(row[0]) for row in rows]

    async def count_active_imported_events(self) -> int:
        """Count distinct L1 events retained by active import memberships."""

        async with sqlite_connection_async(self.db_path) as db:
            async with db.execute(
                """
                SELECT COUNT(DISTINCT source.event_id)
                FROM history_import_job_records AS active
                JOIN history_import_jobs AS active_job
                  ON active_job.job_id = active.job_id
                JOIN history_import_source_records AS source
                  ON source.source_record_key = active.source_record_key
                WHERE active_job.deleted_at IS NULL
                  AND active.raw_state != 'skipped'
                  AND EXISTS (
                      SELECT 1
                      FROM json_each(active_job.included_source_ids_json)
                      WHERE CAST(value AS TEXT) = source.source_id
                  )
                  AND EXISTS (
                      SELECT 1
                      FROM history_import_job_records AS stored
                      WHERE stored.source_record_key = active.source_record_key
                        AND stored.raw_state = 'stored'
                  )
                """
            ) as cursor:
                row = await cursor.fetchone()
        return int(row[0] or 0) if row is not None else 0

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
                f"""
                {_RECORD_SELECT}
                WHERE membership.job_id = ?
                  AND source.speaker_role = 'user'
                  AND source.meaningful = 1
                  AND membership.raw_state = 'stored'
                ORDER BY source.event_at DESC, source.session_id DESC,
                         membership.source_order DESC
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
        job_record_id: str,
        quick: bool,
    ) -> None:
        now = time.time()
        async with sqlite_connection_async(self.db_path) as db:
            await db.execute("BEGIN IMMEDIATE")
            try:
                cursor = await db.execute(
                    """
                    UPDATE history_import_job_records
                    SET raw_state = 'stored', updated_at = ?
                    WHERE job_record_id = ? AND job_id = ? AND raw_state = 'pending'
                    """,
                    (now, job_record_id, job_id),
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

    async def mark_projected(self, *, job_id: str, job_record_id: str) -> None:
        now = time.time()
        async with sqlite_connection_async(self.db_path) as db:
            await db.execute("BEGIN IMMEDIATE")
            try:
                cursor = await db.execute(
                    """
                    UPDATE history_import_job_records
                    SET projection_state = 'projected', updated_at = ?
                    WHERE job_record_id = ? AND job_id = ?
                      AND projection_state = 'pending'
                    """,
                    (now, job_record_id, job_id),
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

    async def mark_raw_skipped(self, *, job_id: str, job_record_id: str) -> None:
        now = time.time()
        async with sqlite_connection_async(self.db_path) as db:
            await db.execute(
                """
                UPDATE history_import_job_records
                SET raw_state = 'skipped',
                    projection_state = 'skipped',
                    updated_at = ?
                WHERE job_record_id = ? AND job_id = ? AND raw_state = 'pending'
                """,
                (now, job_record_id, job_id),
            )
            await db.commit()

    async def mark_projection_skipped(
        self,
        *,
        job_id: str,
        job_record_id: str,
    ) -> None:
        now = time.time()
        async with sqlite_connection_async(self.db_path) as db:
            await db.execute(
                """
                UPDATE history_import_job_records
                SET projection_state = 'skipped', updated_at = ?
                WHERE job_record_id = ? AND job_id = ?
                  AND projection_state = 'pending'
                """,
                (now, job_record_id, job_id),
            )
            await db.commit()

    async def reset_skipped_projections(self, *, job_id: str) -> int:
        """Make failed user-memory handoffs eligible for an explicit retry."""

        now = time.time()
        async with sqlite_connection_async(self.db_path) as db:
            cursor = await db.execute(
                """
                UPDATE history_import_job_records
                SET projection_state = 'pending', updated_at = ?
                WHERE job_id = ?
                  AND raw_state = 'stored'
                  AND projection_state = 'skipped'
                  AND source_record_key IN (
                      SELECT source_record_key
                      FROM history_import_source_records
                      WHERE speaker_role = 'user'
                  )
                """,
                (now, job_id),
            )
            await db.commit()
        return max(0, int(cursor.rowcount or 0))

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
        async with sqlite_connection_async(self.db_path) as db:
            await db.execute("BEGIN IMMEDIATE")
            try:
                await db.execute(
                    """
                    UPDATE history_import_jobs
                    SET source_type = 'deleted',
                        source_fingerprint = 'deleted:' || job_id,
                        source_ids_json = '[]',
                        included_source_ids_json = '[]',
                        importer_plugin_id = NULL,
                        importer_id = NULL,
                        importer_format_version = NULL,
                        detected_kind = 'deleted',
                        status = 'deleted',
                        total_records = 0,
                        meaningful_records = 0,
                        quick_target_records = 0,
                        quick_max_records = 0,
                        quick_imported_count = 0,
                        imported_count = 0,
                        projected_count = 0,
                        self_participant_ids_json = '[]',
                        warnings_json = '[]',
                        quick_ready = 0,
                        deleted_at = ?,
                        error_text = NULL,
                        updated_at = ?
                    WHERE job_id = ? AND deleted_at IS NULL
                    """,
                    (now, now, job_id),
                )
                await db.execute(
                    "DELETE FROM history_import_job_records WHERE job_id = ?",
                    (job_id,),
                )
                await db.execute(
                    """
                    DELETE FROM history_import_source_records AS source
                    WHERE NOT EXISTS (
                        SELECT 1
                        FROM history_import_job_records AS membership
                        WHERE membership.source_record_key = source.source_record_key
                    )
                    """
                )
                await db.execute(
                    """
                    UPDATE history_import_source_records AS source
                    SET speaker_role = 'unknown'
                    WHERE NOT EXISTS (
                        SELECT 1
                        FROM history_import_job_records AS membership
                        JOIN history_import_jobs AS job
                          ON job.job_id = membership.job_id
                        WHERE membership.source_record_key = source.source_record_key
                          AND job.deleted_at IS NULL
                          AND job.status != 'preview_ready'
                          AND json_array_length(job.self_participant_ids_json) > 0
                          AND membership.raw_state != 'skipped'
                          AND EXISTS (
                              SELECT 1
                              FROM json_each(job.included_source_ids_json)
                              WHERE CAST(value AS TEXT) = source.source_id
                          )
                    )
                    """
                )
                await db.commit()
            except BaseException:
                await db.rollback()
                raise

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
        job = await self.get_job_progress(job_id)
        if job is None:
            raise KeyError(job_id)
        if job.source_type == "platform_chat":
            query = f"""
                {_CHAT_SESSION_ANCHOR_CTE}
                {_RECORD_SELECT}
                {_CHAT_SESSION_ANCHOR_JOIN}
                WHERE membership.job_id = ? AND {where}
                ORDER BY session_anchor.latest_event_at ASC,
                         source.session_id ASC, membership.source_order ASC
                LIMIT ?
                """
            params = (job_id, job_id, max(1, int(limit)))
        else:
            query = f"""
                {_RECORD_SELECT}
                WHERE membership.job_id = ? AND {where}
                ORDER BY source.event_at ASC, source.session_id ASC,
                         membership.source_order ASC
                LIMIT ?
                """
            params = (job_id, max(1, int(limit)))
        async with sqlite_connection_async(self.db_path) as db:
            async with db.execute(query, params) as cursor:
                rows = await cursor.fetchall()
        return [_record_from_row(row) for row in rows]

    @staticmethod
    async def _participants(
        db: Any,
        job_id: str,
        *,
        included_source_ids: list[str],
    ) -> list[HistoryImportParticipant]:
        if not included_source_ids:
            return []
        placeholders = ",".join("?" for _ in included_source_ids)
        async with db.execute(
            f"""
            WITH ranked AS (
                SELECT source.speaker_id,
                       source.speaker_name,
                       source.content,
                       source.meaningful,
                       ROW_NUMBER() OVER (
                           PARTITION BY source.speaker_id
                           ORDER BY source.meaningful DESC,
                                    LENGTH(source.content) DESC,
                                    membership.source_order ASC
                       ) AS sample_rank
                FROM history_import_job_records AS membership
                JOIN history_import_source_records AS source
                  ON source.source_record_key = membership.source_record_key
                WHERE membership.job_id = ?
                  AND source.source_id IN ({placeholders})
            )
            SELECT speaker_id,
                   MIN(speaker_name) AS display_name,
                   COUNT(*) AS message_count,
                   SUM(meaningful) AS meaningful_count,
                   MAX(CASE WHEN sample_rank = 1 THEN content END) AS sample
            FROM ranked
            GROUP BY speaker_id
            ORDER BY message_count DESC, speaker_id ASC
            """,
            (job_id, *included_source_ids),
        ) as cursor:
            rows = await cursor.fetchall()
        return [
            HistoryImportParticipant(
                participant_id=str(row["speaker_id"]),
                display_name=str(row["display_name"]),
                message_count=int(row["message_count"]),
                meaningful_count=int(row["meaningful_count"] or 0),
                sample=str(row["sample"] or "")[:160],
            )
            for row in rows
        ]

    @staticmethod
    async def _source_summaries(
        db: Any,
        job_id: str,
        *,
        included_source_ids: list[str],
    ) -> list[HistoryImportSourceSummary]:
        async with db.execute(
            """
            WITH ranked AS (
                SELECT source.source_id,
                       source.source_name,
                       source.source_kind,
                       source.content,
                       source.meaningful,
                       source.event_at,
                       source.timestamp_confidence,
                       source.speaker_id,
                       ROW_NUMBER() OVER (
                           PARTITION BY source.source_id
                           ORDER BY source.meaningful DESC,
                                    LENGTH(source.content) DESC,
                                    membership.source_order ASC
                       ) AS sample_rank
                FROM history_import_job_records AS membership
                JOIN history_import_source_records AS source
                  ON source.source_record_key = membership.source_record_key
                WHERE membership.job_id = ?
            )
            SELECT source_id,
                   MIN(source_name) AS source_name,
                   COUNT(*) AS record_count,
                   SUM(meaningful) AS meaningful_count,
                   MIN(event_at) AS first_event_at,
                   MAX(event_at) AS last_event_at,
                   GROUP_CONCAT(DISTINCT timestamp_confidence) AS timestamp_confidences,
                   GROUP_CONCAT(DISTINCT source_kind) AS source_kinds,
                   MAX(CASE WHEN sample_rank = 1 THEN content END) AS sample
            FROM ranked
            GROUP BY source_id
            ORDER BY source_name COLLATE NOCASE ASC
            """,
            (job_id,),
        ) as cursor:
            rows = await cursor.fetchall()
        included = set(included_source_ids)
        summaries: list[HistoryImportSourceSummary] = []
        for row in rows:
            source_id = str(row["source_id"])
            record_count = int(row["record_count"])
            source_kinds = {
                item.strip() for item in str(row["source_kinds"] or "").split(",") if item.strip()
            }
            detected_kind = next(iter(source_kinds)) if len(source_kinds) == 1 else "mixed"
            confidence_values = {
                item.strip()
                for item in str(row["timestamp_confidences"] or "").split(",")
                if item.strip()
            }
            summaries.append(
                HistoryImportSourceSummary(
                    source_id=source_id,
                    source_name=str(row["source_name"]),
                    detected_kind=detected_kind,
                    record_count=record_count,
                    meaningful_count=int(row["meaningful_count"] or 0),
                    first_event_at=float(row["first_event_at"]),
                    last_event_at=float(row["last_event_at"]),
                    timestamp_confidence=(
                        next(iter(confidence_values)) if len(confidence_values) == 1 else "mixed"
                    ),
                    sample=str(row["sample"] or "")[:240],
                    included=source_id in included,
                )
            )
        return summaries

    @staticmethod
    async def _preview_records(
        db: Any,
        job_id: str,
        *,
        included_source_ids: list[str],
    ) -> list[HistoryImportRecord]:
        if not included_source_ids:
            return []
        placeholders = ",".join("?" for _ in included_source_ids)
        async with db.execute(
            f"""
            {_RECORD_SELECT}
            WHERE membership.job_id = ?
              AND source.source_id IN ({placeholders})
            ORDER BY source.event_at DESC, source.session_id DESC,
                     membership.source_order DESC
            LIMIT 6
            """,
            (job_id, *included_source_ids),
        ) as cursor:
            rows = await cursor.fetchall()
        return sorted(
            (_record_from_row(row) for row in rows),
            key=lambda item: (item.event_at, item.session_id, item.session_seq),
        )


async def _load_source_identity_rows(
    db: Any,
    source_record_keys: list[str],
) -> dict[str, Any]:
    """Load persisted source identities using bounded SQLite parameter batches."""

    unique_keys = list(dict.fromkeys(source_record_keys))
    rows_by_key: dict[str, Any] = {}
    for offset in range(0, len(unique_keys), _SOURCE_IDENTITY_READ_BATCH_SIZE):
        batch = unique_keys[offset : offset + _SOURCE_IDENTITY_READ_BATCH_SIZE]
        placeholders = ",".join("?" for _ in batch)
        async with db.execute(
            f"""
            SELECT source_record_key, source_id, source_name, source_kind, parsed_session_key,
                   session_id, session_seq, speaker_id, speaker_name,
                   message_key, parent_message_key, content, event_at,
                   timestamp_confidence, timestamp_anchor_source,
                   calendar_timezone_id, meaningful, event_id
            FROM history_import_source_records
            WHERE source_record_key IN ({placeholders})
            """,
            tuple(batch),
        ) as cursor:
            rows = await cursor.fetchall()
        rows_by_key.update({str(row["source_record_key"]): row for row in rows})
    return rows_by_key


async def _load_job_record_keys(
    db: Any,
    *,
    job_id: str,
    source_record_keys: list[str],
) -> set[str]:
    """Load candidate record keys already attached to one preview job."""

    unique_keys = list(dict.fromkeys(source_record_keys))
    loaded: set[str] = set()
    for offset in range(0, len(unique_keys), _SOURCE_IDENTITY_READ_BATCH_SIZE):
        batch = unique_keys[offset : offset + _SOURCE_IDENTITY_READ_BATCH_SIZE]
        if not batch:
            continue
        placeholders = ",".join("?" for _ in batch)
        async with db.execute(
            f"""
            SELECT source_record_key
            FROM history_import_job_records
            WHERE job_id = ?
              AND source_record_key IN ({placeholders})
            """,
            (job_id, *batch),
        ) as cursor:
            rows = await cursor.fetchall()
        loaded.update(str(row["source_record_key"]) for row in rows)
    return loaded


async def _load_reserved_session_prefixes(
    db: Any,
    *,
    importer_plugin_id: str,
    importer_id: str,
    importer_format_version: str,
    session_identities: list[tuple[str, str]],
) -> dict[tuple[str, str], list[str]]:
    """Load confirmed session prefixes in bounded batches, never per source."""

    unique_identities = list(dict.fromkeys(session_identities))
    prefixes: dict[tuple[str, str], list[str]] = {}
    for offset in range(0, len(unique_identities), _SESSION_PREFIX_READ_BATCH_SIZE):
        batch = unique_identities[offset : offset + _SESSION_PREFIX_READ_BATCH_SIZE]
        requested_values = ", ".join("(?, ?)" for _ in batch)
        parameters = tuple(
            value for source_id, session_key in batch for value in (source_id, session_key)
        )
        async with db.execute(
            f"""
            WITH requested(source_id, parsed_session_key) AS (
                VALUES {requested_values}
            )
            SELECT source.source_id,
                   source.parsed_session_key,
                   source.message_key,
                   MIN(membership.source_order) AS reserved_order
            FROM requested
            JOIN history_import_source_records AS source
              ON source.source_id = requested.source_id
             AND source.parsed_session_key = requested.parsed_session_key
            JOIN history_import_job_records AS membership
              ON membership.source_record_key = source.source_record_key
            JOIN history_import_jobs AS job
              ON job.job_id = membership.job_id
            WHERE job.deleted_at IS NULL
              AND job.status != 'preview_ready'
              AND job.importer_plugin_id = ?
              AND job.importer_id = ?
              AND job.importer_format_version = ?
              AND membership.raw_state != 'skipped'
            GROUP BY source.source_id,
                     source.parsed_session_key,
                     source.message_key
            ORDER BY source.source_id,
                     source.parsed_session_key,
                     reserved_order
            """,
            (
                *parameters,
                importer_plugin_id,
                importer_id,
                importer_format_version,
            ),
        ) as cursor:
            rows = await cursor.fetchall()
        for row in rows:
            identity = (str(row["source_id"]), str(row["parsed_session_key"]))
            prefixes.setdefault(identity, []).append(str(row["message_key"]))
    return prefixes


async def _load_job_session_prefixes(
    db: Any,
    *,
    job_id: str,
    included_source_ids: list[str],
) -> dict[tuple[str, str], list[str]]:
    """Load selected source sequences for one preview in a single query."""

    if not included_source_ids:
        return {}
    placeholders = ",".join("?" for _ in included_source_ids)
    async with db.execute(
        f"""
        SELECT source.source_id,
               source.parsed_session_key,
               source.message_key,
               membership.source_order
        FROM history_import_job_records AS membership
        JOIN history_import_source_records AS source
          ON source.source_record_key = membership.source_record_key
        WHERE membership.job_id = ?
          AND source.source_id IN ({placeholders})
        ORDER BY source.source_id,
                 source.parsed_session_key,
                 membership.source_order
        """,
        (job_id, *included_source_ids),
    ) as cursor:
        rows = await cursor.fetchall()
    prefixes: dict[tuple[str, str], list[str]] = {}
    for row in rows:
        identity = (str(row["source_id"]), str(row["parsed_session_key"]))
        prefixes.setdefault(identity, []).append(str(row["message_key"]))
    return prefixes


def _require_append_only_session_prefixes(
    *,
    incoming_prefixes: dict[tuple[str, str], list[str]],
    reserved_prefixes: dict[tuple[str, str], list[str]],
) -> None:
    """Reject truncation, reordering, or divergent branches of a session."""

    for identity, incoming_keys in incoming_prefixes.items():
        reserved_keys = reserved_prefixes.get(identity, [])
        if reserved_keys and incoming_keys[: len(reserved_keys)] != reserved_keys:
            raise ValueError("history_import_non_append_update")


def _meaningful_user_count(rows: list[Any]) -> int:
    return sum(
        1 for row in rows if str(row["speaker_role"] or "") == "user" and bool(row["meaningful"])
    )


def _same_source_identity(record: HistoryImportRecord, row: Any) -> bool:
    """Reject stable identity reuse when source-declared message data changed.

    Display labels and host-derived projection metadata are intentionally not
    part of this comparison. A later export may rename a conversation or
    participant, and the host timezone or meaningfulness heuristic may change,
    without changing the platform message itself.
    """

    stored_confidence = str(row["timestamp_confidence"])
    confidence_matches = stored_confidence == record.timestamp_confidence
    declared_time_matches = record.timestamp_confidence not in {
        "exact",
        "inferred",
    } or (
        float(row["event_at"]) == record.event_at
        and str(row["timestamp_anchor_source"])
        == record.timestamp_anchor_source
        == "source_timestamp"
    )
    return (
        str(row["source_id"]) == record.source_id
        and str(row["source_kind"]) == record.source_kind
        and str(row["parsed_session_key"]) == record.parsed_session_key
        and str(row["session_id"]) == record.session_id
        and str(row["speaker_id"]) == record.speaker_id
        and str(row["message_key"]) == record.message_key
        and (str(row["parent_message_key"]) if row["parent_message_key"] is not None else None)
        == record.parent_message_key
        and str(row["content"]) == record.content
        and confidence_matches
        and declared_time_matches
        and str(row["event_id"]) == record.event_id
    )


def _record_from_row(row: Any) -> HistoryImportRecord:
    return HistoryImportRecord(
        job_record_id=str(row["job_record_id"]),
        job_id=str(row["job_id"]),
        source_record_key=str(row["source_record_key"]),
        file_fingerprint=str(row["file_fingerprint"]),
        source_id=str(row["source_id"]),
        source_name=str(row["source_name"]),
        source_kind=str(row["source_kind"]),
        parsed_session_key=str(row["parsed_session_key"]),
        session_id=str(row["session_id"]),
        session_seq=int(row["session_seq"]),
        speaker_id=str(row["speaker_id"]),
        speaker_name=str(row["speaker_name"]),
        message_key=str(row["message_key"]),
        parent_message_key=(
            str(row["parent_message_key"]) if row["parent_message_key"] is not None else None
        ),
        speaker_role=str(row["speaker_role"]),
        content=str(row["content"]),
        event_at=float(row["event_at"]),
        timestamp_confidence=str(row["timestamp_confidence"]),
        timestamp_anchor_source=str(row["timestamp_anchor_source"]),
        calendar_timezone_id=str(row["calendar_timezone_id"]),
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
        source_ids=list(json.loads(row["source_ids_json"] or "[]")),
        included_source_ids=list(json.loads(row["included_source_ids_json"] or "[]")),
        detected_kind=str(row["detected_kind"]),
        status=str(row["status"]),
        total_records=int(row["total_records"]),
        meaningful_records=int(row["meaningful_records"]),
        quick_target_records=int(row["quick_target_records"]),
        quick_max_records=int(row["quick_max_records"]),
        quick_imported_count=int(row["quick_imported_count"]),
        imported_count=int(row["imported_count"]),
        projected_count=int(row["projected_count"]),
        self_participant_ids=list(json.loads(row["self_participant_ids_json"] or "[]")),
        warnings=list(json.loads(row["warnings_json"] or "[]")),
        quick_ready=bool(row["quick_ready"]),
        error_text=str(row["error_text"]) if row["error_text"] is not None else None,
        created_at=float(row["created_at"]),
        updated_at=float(row["updated_at"]),
        deleted_at=float(row["deleted_at"]) if row["deleted_at"] is not None else None,
        importer_plugin_id=(
            str(row["importer_plugin_id"]) if row["importer_plugin_id"] is not None else None
        ),
        importer_id=str(row["importer_id"]) if row["importer_id"] is not None else None,
        importer_format_version=(
            str(row["importer_format_version"])
            if row["importer_format_version"] is not None
            else None
        ),
        participants=participants,
        sources=sources,
        preview_records=preview_records,
    )


__all__ = ["HistoryImportStore"]
