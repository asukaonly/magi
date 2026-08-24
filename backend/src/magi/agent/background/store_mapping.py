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
        task_data = {
            "task_id": str(row["task_id"]),
            "spec": spec_data,
            "status": str(row["status"]),
            "attempt_index": int(row["attempt_index"] or 0),
            "user_task_id": row["user_task_id"],
            "summary": row["summary"],
            "result_payload": json.loads(
                str(row["result_payload_json"] or "{}")
            ),
            "error": row["error"],
            "cancel_reason": row["cancel_reason"],
            "created_at": float(row["created_at"]),
            "started_at": row["started_at"],
            "finished_at": row["finished_at"],
            "updated_at": float(row["updated_at"]),
        }
        return BackgroundTaskRowMappingMixin._dict_to_task(task_data)

    @staticmethod
    def _dict_to_task(data: dict[str, Any]) -> BackgroundTask:
        """Rebuild a task from its durable completion snapshot."""

        spec_data = data.get("spec")
        if not isinstance(spec_data, dict):
            raise ValueError("Background task snapshot is missing its spec")
        spec = BackgroundTaskSpec.from_dict(spec_data)
        result_payload = data.get("result_payload")
        if not isinstance(result_payload, dict):
            raise ValueError("Background task snapshot has an invalid result payload")
        return BackgroundTask(
            task_id=str(data["task_id"]),
            spec=spec,
            status=BackgroundTaskStatus(str(data["status"])),
            attempt_index=int(data.get("attempt_index") or 0),
            user_task_id=(
                str(data["user_task_id"])
                if data.get("user_task_id") is not None
                else None
            ),
            summary=(
                str(data["summary"]) if data.get("summary") is not None else None
            ),
            result_payload=dict(result_payload),
            error=(str(data["error"]) if data.get("error") is not None else None),
            cancel_reason=(
                str(data["cancel_reason"])
                if data.get("cancel_reason") is not None
                else None
            ),
            created_at=float(data["created_at"]),
            started_at=(
                float(data["started_at"])
                if data.get("started_at") is not None
                else None
            ),
            finished_at=(
                float(data["finished_at"])
                if data.get("finished_at") is not None
                else None
            ),
            updated_at=float(data["updated_at"]),
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
