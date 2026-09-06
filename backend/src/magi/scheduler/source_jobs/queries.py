"""Source sync job queries for the scheduler repository."""

from __future__ import annotations

import json
from typing import Optional, cast

import aiosqlite

from ..contracts import ScheduledTargetType
from .contracts import _SourceJobRepositoryHost


class _SourceSyncJobQueriesMixin:
    async def get_source_sync_job(self, job_id: str) -> Optional[dict[str, object]]:
        host = cast(_SourceJobRepositoryHost, self)
        async with host._connect() as db:
            cursor = await db.execute(
                """
                SELECT *
                FROM source_sync_jobs
                WHERE job_id = ?
                """,
                (job_id,),
            )
            row = await cursor.fetchone()
        if row is None:
            return None
        return self._row_to_source_sync_job(row)

    async def get_outstanding_source_sync_job(
        self,
        target_type: ScheduledTargetType,
        target_key: str,
    ) -> Optional[dict[str, object]]:
        host = cast(_SourceJobRepositoryHost, self)
        async with host._connect() as db:
            cursor = await db.execute(
                """
                SELECT *
                FROM source_sync_jobs
                WHERE target_type = ?
                  AND target_key = ?
                  AND status IN ('queued', 'running')
                ORDER BY created_at ASC
                LIMIT 1
                """,
                (target_type.value, target_key),
            )
            row = await cursor.fetchone()
        if row is None:
            return None
        return self._row_to_source_sync_job(row)

    async def get_latest_source_sync_job(
        self,
        target_type: ScheduledTargetType,
        target_key: str,
    ) -> Optional[dict[str, object]]:
        """Return the most recently created sync job for one source target."""

        host = cast(_SourceJobRepositoryHost, self)
        async with host._connect() as db:
            cursor = await db.execute(
                """
                SELECT *
                FROM source_sync_jobs
                WHERE target_type = ?
                  AND target_key = ?
                ORDER BY created_at DESC, rowid DESC
                LIMIT 1
                """,
                (target_type.value, target_key),
            )
            row = await cursor.fetchone()
        if row is None:
            return None
        return self._row_to_source_sync_job(row)

    def _row_to_source_sync_job(self, row: aiosqlite.Row) -> dict[str, object]:
        return {
            "job_id": str(row["job_id"]),
            "schedule_id": str(row["schedule_id"]),
            "execution_id": str(row["execution_id"]),
            "target_type": str(row["target_type"]),
            "target_key": str(row["target_key"]),
            "plugin_id": str(row["plugin_id"]),
            "source_type": str(row["source_type"]),
            "manual": bool(row["manual"]),
            "status": str(row["status"]),
            "payload": json.loads(str(row["payload_json"]) or "{}"),
            "created_at": float(row["created_at"]),
            "next_attempt_at": float(row["next_attempt_at"]),
            "claimed_at": float(row["claimed_at"]) if row["claimed_at"] is not None else None,
            "started_at": float(row["started_at"]) if row["started_at"] is not None else None,
            "finished_at": float(row["finished_at"]) if row["finished_at"] is not None else None,
            "claimed_by": str(row["claimed_by"]) if row["claimed_by"] is not None else None,
            "attempt_count": int(row["attempt_count"] or 0),
            "error": str(row["error"]) if row["error"] is not None else None,
            "result_message": (
                str(row["result_message"]) if row["result_message"] is not None else None
            ),
            "stats": json.loads(str(row["stats_json"]) or "{}"),
            "next_cursor": str(row["next_cursor"]) if row["next_cursor"] is not None else None,
            "watermark_ts": float(row["watermark_ts"]) if row["watermark_ts"] is not None else None,
        }
