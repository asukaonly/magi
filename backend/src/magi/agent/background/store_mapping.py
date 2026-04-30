"""Row mapping helpers for background task storage."""

from __future__ import annotations

import json
from typing import Any

import aiosqlite

from .contracts import (
    BackgroundTask,
    BackgroundTaskEvent,
    BackgroundTaskSpec,
    BackgroundTaskStatus,
)


class BackgroundTaskRowMappingMixin:
    """Convert SQLite rows to background task contracts."""

    @staticmethod
    def _row_to_task(row: aiosqlite.Row) -> BackgroundTask:
        spec_data: dict[str, Any] = json.loads(str(row["spec_json"] or "{}"))
        spec_data.setdefault("user_id", str(row["user_id"]))
        spec_data.setdefault("session_id", str(row["session_id"]))
        spec_data.setdefault("origin_turn_id", str(row["origin_turn_id"]))
        spec_data.setdefault("title", str(row["title"]))
        spec_data.setdefault("goal", str(row["goal"]))
        spec = BackgroundTaskSpec.from_dict(spec_data)
        return BackgroundTask(
            task_id=str(row["task_id"]),
            spec=spec,
            status=BackgroundTaskStatus(str(row["status"])),
            attempt_index=int(row["attempt_index"] or 0),
            orchestration_id=(
                str(row["orchestration_id"])
                if row["orchestration_id"] is not None
                else None
            ),
            user_task_id=(
                str(row["user_task_id"])
                if row["user_task_id"] is not None
                else None
            ),
            summary=(
                str(row["summary"]) if row["summary"] is not None else None
            ),
            result_payload=json.loads(str(row["result_payload_json"] or "{}")),
            error=(str(row["error"]) if row["error"] is not None else None),
            cancel_reason=(
                str(row["cancel_reason"])
                if row["cancel_reason"] is not None
                else None
            ),
            created_at=float(row["created_at"]),
            started_at=(
                float(row["started_at"]) if row["started_at"] is not None else None
            ),
            finished_at=(
                float(row["finished_at"]) if row["finished_at"] is not None else None
            ),
            updated_at=float(row["updated_at"]),
        )

    @staticmethod
    def _row_to_event(row: aiosqlite.Row) -> BackgroundTaskEvent:
        from_raw = row["from_status"]
        to_raw = row["to_status"]
        return BackgroundTaskEvent(
            event_id=str(row["event_id"]),
            task_id=str(row["task_id"]),
            attempt_index=int(row["attempt_index"] or 0),
            event_type=str(row["event_type"]),
            from_status=(
                BackgroundTaskStatus(str(from_raw)) if from_raw is not None else None
            ),
            to_status=(
                BackgroundTaskStatus(str(to_raw)) if to_raw is not None else None
            ),
            message=str(row["message"] or ""),
            payload=json.loads(str(row["payload_json"] or "{}")),
            created_at=float(row["created_at"]),
        )


__all__ = ["BackgroundTaskRowMappingMixin"]
