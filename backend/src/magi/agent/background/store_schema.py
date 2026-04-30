"""SQLite schema initialization for background task storage."""

from __future__ import annotations

from pathlib import Path

from ...core.sqlite import sqlite_connection_async


class BackgroundTaskSchemaMixin:
    """Initialize background task persistence tables."""

    db_path: str
    _initialized: bool

    async def initialize(self) -> None:
        if self._initialized:
            return
        Path(self.db_path).parent.mkdir(parents=True, exist_ok=True)
        async with sqlite_connection_async(self.db_path, profile="hot_write") as db:
            await db.executescript(
                """
                CREATE TABLE IF NOT EXISTS background_tasks (
                    task_id TEXT PRIMARY KEY,
                    user_id TEXT NOT NULL,
                    session_id TEXT NOT NULL,
                    origin_turn_id TEXT NOT NULL,
                    title TEXT NOT NULL,
                    goal TEXT NOT NULL,
                    status TEXT NOT NULL,
                    attempt_index INTEGER NOT NULL DEFAULT 0,
                    spec_json TEXT NOT NULL,
                    orchestration_id TEXT,
                    user_task_id TEXT,
                    summary TEXT,
                    result_payload_json TEXT NOT NULL DEFAULT '{}',
                    error TEXT,
                    cancel_reason TEXT,
                    created_at REAL NOT NULL,
                    started_at REAL,
                    finished_at REAL,
                    updated_at REAL NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_bg_tasks_user_status
                    ON background_tasks(user_id, status);
                CREATE INDEX IF NOT EXISTS idx_bg_tasks_session
                    ON background_tasks(session_id, created_at DESC);
                CREATE INDEX IF NOT EXISTS idx_bg_tasks_status_created
                    ON background_tasks(status, created_at);

                CREATE TABLE IF NOT EXISTS background_task_events (
                    event_id TEXT PRIMARY KEY,
                    task_id TEXT NOT NULL,
                    attempt_index INTEGER NOT NULL,
                    event_type TEXT NOT NULL,
                    from_status TEXT,
                    to_status TEXT,
                    message TEXT NOT NULL DEFAULT '',
                    payload_json TEXT NOT NULL DEFAULT '{}',
                    created_at REAL NOT NULL,
                    FOREIGN KEY (task_id) REFERENCES background_tasks(task_id)
                );
                CREATE INDEX IF NOT EXISTS idx_bg_events_task_created
                    ON background_task_events(task_id, created_at);
                """
            )
            await db.commit()
        self._initialized = True


__all__ = ["BackgroundTaskSchemaMixin"]
