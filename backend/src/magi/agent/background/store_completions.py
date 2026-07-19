"""Durable completion intents for background-task terminal transitions."""

from __future__ import annotations

import json
import time
from dataclasses import dataclass, replace

import aiosqlite

from ...core.sqlite import sqlite_connection_async
from .contracts import BackgroundTask, BackgroundTaskEvent, BackgroundTaskStatus


@dataclass(frozen=True, slots=True)
class PendingBackgroundTaskCompletion:
    """Immutable task attempt plus any prepared outreach content."""

    task: BackgroundTask
    intent_json: str | None
    composed_body: str | None


class BackgroundTaskCompletionStoreMixin:
    """Persist terminal state and its user-facing completion intent atomically."""

    db_path: str

    async def persist_cancellation_request(
        self,
        *,
        task_id: str,
        reason: str,
        updated_at: float,
    ) -> BackgroundTask | None:
        """Move an active attempt to cancelling before its token is signalled."""

        await self.initialize()
        async with sqlite_connection_async(self.db_path, profile="hot_write") as db:
            await db.execute("BEGIN IMMEDIATE")
            db.row_factory = aiosqlite.Row
            cursor = await db.execute(
                "SELECT * FROM background_tasks WHERE task_id = ?",
                (str(task_id),),
            )
            row = await cursor.fetchone()
            if row is None:
                await db.commit()
                return None
            task = self._row_to_task(row)
            if task.status is BackgroundTaskStatus.CANCELLING:
                await db.commit()
                return task
            if task.status is BackgroundTaskStatus.PENDING:
                previous = task.status
                task.status = BackgroundTaskStatus.CANCELLED
                task.cancel_reason = str(reason)
                task.finished_at = float(updated_at)
                task.updated_at = float(updated_at)
                await self._update_task_row(db, task)
                await self._insert_event_row(
                    db,
                    BackgroundTaskEvent.transition(
                        task_id=task.task_id,
                        attempt_index=task.attempt_index,
                        from_status=previous,
                        to_status=BackgroundTaskStatus.CANCELLED,
                        message=str(reason),
                    ),
                )
                await self._insert_completion_intent_row(db, task)
                await db.commit()
                return task
            if task.status not in {
                BackgroundTaskStatus.RUNNING,
                BackgroundTaskStatus.SUSPENDED_WAITING_USER,
            }:
                await db.commit()
                return None
            previous = task.status
            task.status = BackgroundTaskStatus.CANCELLING
            task.cancel_reason = str(reason)
            task.updated_at = float(updated_at)
            await self._update_task_row(db, task)
            await self._insert_event_row(
                db,
                BackgroundTaskEvent.transition(
                    task_id=task.task_id,
                    attempt_index=task.attempt_index,
                    from_status=previous,
                    to_status=BackgroundTaskStatus.CANCELLING,
                    message=str(reason),
                ),
            )
            await db.commit()
            return task

    async def persist_running_transition(
        self,
        task: BackgroundTask,
        event: BackgroundTaskEvent,
    ) -> bool:
        """Start an attempt only while its durable row is still pending."""

        if task.status is not BackgroundTaskStatus.RUNNING:
            raise ValueError("Running transition requires a running task")
        if event.to_status is not BackgroundTaskStatus.RUNNING:
            raise ValueError("Running event must target the running state")
        if event.task_id != task.task_id or event.attempt_index != task.attempt_index:
            raise ValueError("Running event identity does not match the task attempt")

        await self.initialize()
        async with sqlite_connection_async(self.db_path, profile="hot_write") as db:
            await db.execute("BEGIN IMMEDIATE")
            cursor = await db.execute(
                """
                SELECT status, attempt_index
                FROM background_tasks
                WHERE task_id = ?
                """,
                (task.task_id,),
            )
            current = await cursor.fetchone()
            if current is None:
                await db.commit()
                return False
            if (
                int(current[1] or 0) != int(task.attempt_index)
                or BackgroundTaskStatus(str(current[0]))
                is not BackgroundTaskStatus.PENDING
            ):
                await db.commit()
                return False
            await self._update_task_row(db, task)
            await self._insert_event_row(db, event)
            await db.commit()
        return True

    async def persist_terminal_transition(
        self,
        task: BackgroundTask,
        event: BackgroundTaskEvent,
    ) -> BackgroundTask:
        """Commit a terminal task, event, and recoverable delivery snapshot."""

        if task.status not in BackgroundTaskStatus.terminal():
            raise ValueError("Completion intents require a terminal background task")
        if event.to_status is not task.status:
            raise ValueError("Terminal event status does not match the task status")
        if event.task_id != task.task_id or event.attempt_index != task.attempt_index:
            raise ValueError("Terminal event identity does not match the task attempt")

        await self.initialize()
        async with sqlite_connection_async(self.db_path, profile="hot_write") as db:
            await db.execute("BEGIN IMMEDIATE")
            db.row_factory = aiosqlite.Row
            cursor = await db.execute(
                """
                SELECT status, attempt_index
                FROM background_tasks
                WHERE task_id = ?
                """,
                (task.task_id,),
            )
            current = await cursor.fetchone()
            if current is None:
                raise RuntimeError(
                    "Background task disappeared before terminal transition"
                )
            current_attempt = int(current["attempt_index"] or 0)
            if current_attempt != int(task.attempt_index):
                raise RuntimeError(
                    "Stale background task attempt cannot overwrite a newer attempt"
                )
            current_status = BackgroundTaskStatus(str(current["status"]))
            if current_status in BackgroundTaskStatus.terminal():
                raise RuntimeError(
                    "Background task attempt is already terminal"
                )
            await self._update_task_row(db, task)
            await self._insert_event_row(
                db,
                replace(event, from_status=current_status),
            )
            await self._insert_completion_intent_row(db, task)
            await db.commit()
        return task

    async def claim_completion(
        self,
        *,
        task_id: str,
        attempt_index: int,
        claim_token: str,
    ) -> PendingBackgroundTaskCompletion | None:
        """Claim one pending completion before deriving or delivering content."""

        token = str(claim_token or "").strip()
        if not token:
            raise ValueError("Background completion claim token cannot be empty")
        await self.initialize()
        async with sqlite_connection_async(self.db_path, profile="hot_write") as db:
            await db.execute("BEGIN IMMEDIATE")
            db.row_factory = aiosqlite.Row
            claimed_at = time.time()
            claimed = await db.execute(
                """
                UPDATE background_task_completion_intents
                SET state = 'processing',
                    claim_token = ?,
                    claimed_at = ?
                WHERE task_id = ?
                  AND attempt_index = ?
                  AND state = 'pending'
                """,
                (
                    token,
                    claimed_at,
                    str(task_id),
                    int(attempt_index),
                ),
            )
            if int(claimed.rowcount or 0) != 1:
                await db.commit()
                return None
            cursor = await db.execute(
                """
                SELECT task_json, intent_json, composed_body
                FROM background_task_completion_intents
                WHERE task_id = ?
                  AND attempt_index = ?
                  AND state = 'processing'
                  AND claim_token = ?
                """,
                (str(task_id), int(attempt_index), token),
            )
            row = await cursor.fetchone()
            await db.commit()
        if row is None:
            raise RuntimeError("Claimed background completion disappeared")
        return self._row_to_pending_completion(row)

    async def list_pending_completions(
        self,
        *,
        limit: int = 500,
    ) -> list[PendingBackgroundTaskCompletion]:
        """Return immutable terminal snapshots awaiting outreach handling."""

        await self.initialize()
        async with sqlite_connection_async(self.db_path, profile="readonly") as db:
            db.row_factory = aiosqlite.Row
            cursor = await db.execute(
                """
                SELECT task_json, intent_json, composed_body
                FROM background_task_completion_intents
                WHERE state = 'pending'
                ORDER BY created_at ASC, task_id ASC, attempt_index ASC
                LIMIT ?
                """,
                (max(1, int(limit)),),
            )
            rows = await cursor.fetchall()

        return [self._row_to_pending_completion(row) for row in rows]

    async def save_completion_intent(
        self,
        *,
        task_id: str,
        attempt_index: int,
        claim_token: str,
        intent_json: str,
    ) -> str:
        """Freeze the first derived outreach intent for a task attempt."""

        normalized = str(intent_json or "").strip()
        if not normalized:
            raise ValueError("Background completion intent JSON cannot be empty")
        await self.initialize()
        async with sqlite_connection_async(self.db_path, profile="hot_write") as db:
            await db.execute("BEGIN IMMEDIATE")
            cursor = await db.execute(
                """
                SELECT intent_json
                FROM background_task_completion_intents
                WHERE task_id = ?
                  AND attempt_index = ?
                  AND state = 'processing'
                  AND claim_token = ?
                """,
                (str(task_id), int(attempt_index), str(claim_token)),
            )
            row = await cursor.fetchone()
            if row is None:
                raise RuntimeError(
                    "Background completion was handled before intent preparation"
                )
            existing = str(row[0]) if row[0] is not None else None
            if existing is not None and existing != normalized:
                raise RuntimeError(
                    "Background completion intent changed after it was prepared"
                )
            if existing is None:
                await db.execute(
                    """
                    UPDATE background_task_completion_intents
                    SET intent_json = ?
                    WHERE task_id = ?
                      AND attempt_index = ?
                      AND state = 'processing'
                      AND claim_token = ?
                      AND intent_json IS NULL
                    """,
                    (
                        normalized,
                        str(task_id),
                        int(attempt_index),
                        str(claim_token),
                    ),
                )
            await db.commit()
        return existing or normalized

    async def save_completion_body(
        self,
        *,
        task_id: str,
        attempt_index: int,
        claim_token: str,
        intent_json: str,
        composed_body: str,
    ) -> str:
        """Persist the first composed body before any delivery side effect."""

        normalized_intent = str(intent_json or "").strip()
        body = str(composed_body)
        if not normalized_intent:
            raise ValueError("Background completion intent JSON cannot be empty")
        await self.initialize()
        async with sqlite_connection_async(self.db_path, profile="hot_write") as db:
            await db.execute("BEGIN IMMEDIATE")
            cursor = await db.execute(
                """
                SELECT intent_json, composed_body
                FROM background_task_completion_intents
                WHERE task_id = ?
                  AND attempt_index = ?
                  AND state = 'processing'
                  AND claim_token = ?
                """,
                (str(task_id), int(attempt_index), str(claim_token)),
            )
            row = await cursor.fetchone()
            if row is None:
                raise RuntimeError(
                    "Background completion was handled before body preparation"
                )
            existing_intent = str(row[0]) if row[0] is not None else None
            if existing_intent != normalized_intent:
                raise RuntimeError(
                    "Background completion body does not match its prepared intent"
                )
            existing_body = str(row[1]) if row[1] is not None else None
            if existing_body is None:
                await db.execute(
                    """
                    UPDATE background_task_completion_intents
                    SET composed_body = ?
                    WHERE task_id = ?
                      AND attempt_index = ?
                      AND state = 'processing'
                      AND claim_token = ?
                      AND composed_body IS NULL
                    """,
                    (
                        body,
                        str(task_id),
                        int(attempt_index),
                        str(claim_token),
                    ),
                )
            elif existing_body != body:
                raise RuntimeError(
                    "Background completion body changed after it was prepared"
                )
            await db.commit()
        return existing_body if existing_body is not None else body

    async def mark_completion_handled(
        self,
        *,
        task_id: str,
        attempt_index: int,
        claim_token: str,
        handled_at: float | None = None,
    ) -> bool:
        """Acknowledge a delivered or intentionally ignored completion intent."""

        await self.initialize()
        async with sqlite_connection_async(self.db_path, profile="hot_write") as db:
            cursor = await db.execute(
                """
                UPDATE background_task_completion_intents
                SET state = 'handled',
                    task_json = '{}',
                    intent_json = NULL,
                    composed_body = NULL,
                    claim_token = NULL,
                    claimed_at = NULL,
                    handled_at = ?
                WHERE task_id = ?
                  AND attempt_index = ?
                  AND state = 'processing'
                  AND claim_token = ?
                """,
                (
                    float(handled_at if handled_at is not None else time.time()),
                    str(task_id),
                    int(attempt_index),
                    str(claim_token),
                ),
            )
            await db.execute(
                """
                DELETE FROM background_task_completion_intents
                WHERE task_id = ?
                  AND attempt_index = ?
                  AND state = 'handled'
                  AND NOT EXISTS (
                      SELECT 1
                      FROM background_tasks
                      WHERE background_tasks.task_id = ?
                  )
                """,
                (str(task_id), int(attempt_index), str(task_id)),
            )
            await db.commit()
        return int(cursor.rowcount or 0) == 1

    async def release_completion_claim(
        self,
        *,
        task_id: str,
        attempt_index: int,
        claim_token: str,
    ) -> bool:
        """Return a failed or cancelled delivery claim to the pending queue."""

        await self.initialize()
        async with sqlite_connection_async(self.db_path, profile="hot_write") as db:
            cursor = await db.execute(
                """
                UPDATE background_task_completion_intents
                SET state = 'pending',
                    claim_token = NULL,
                    claimed_at = NULL
                WHERE task_id = ?
                  AND attempt_index = ?
                  AND state = 'processing'
                  AND claim_token = ?
                """,
                (str(task_id), int(attempt_index), str(claim_token)),
            )
            await db.commit()
        return int(cursor.rowcount or 0) == 1

    async def recover_interrupted_completion_claims(self) -> int:
        """Make crash-interrupted delivery claims available on startup."""

        await self.initialize()
        async with sqlite_connection_async(self.db_path, profile="hot_write") as db:
            cursor = await db.execute(
                """
                UPDATE background_task_completion_intents
                SET state = 'pending',
                    claim_token = NULL,
                    claimed_at = NULL
                WHERE state = 'processing'
                """
            )
            await db.commit()
        return int(cursor.rowcount or 0)

    async def discard_pending_completions_in_scope(
        self,
        *,
        user_id: str | None,
        session_id: str | None,
        origin_turn_ids: set[str] | None,
        task_ids: set[str] | None = None,
        pending_message_ids: set[str] | None = None,
        discarded_at: float | None = None,
    ) -> tuple[int, int]:
        """Discard pending scope rows and count deliveries already in progress."""

        conditions: list[str] = []
        params: list[object] = []
        if user_id is not None:
            conditions.append("task.user_id = ?")
            params.append(str(user_id))
        if session_id is not None:
            conditions.append("task.session_id = ?")
            params.append(str(session_id))
        identity_conditions: list[str] = []
        identity_params: list[object] = []
        if origin_turn_ids is not None:
            normalized = sorted(
                {
                    turn_id
                    for raw_turn_id in origin_turn_ids
                    if (turn_id := str(raw_turn_id or "").strip())
                }
            )
            if normalized:
                placeholders = ",".join("?" * len(normalized))
                identity_conditions.append(
                    f"task.origin_turn_id IN ({placeholders})"
                )
                identity_params.extend(normalized)
        if task_ids is not None:
            normalized = sorted(
                {
                    task_id
                    for raw_task_id in task_ids
                    if (task_id := str(raw_task_id or "").strip())
                }
            )
            if normalized:
                placeholders = ",".join("?" * len(normalized))
                identity_conditions.append(
                    f"task.task_id IN ({placeholders})"
                )
                identity_params.extend(normalized)
        if pending_message_ids is not None:
            normalized = sorted(
                {
                    message_id
                    for raw_message_id in pending_message_ids
                    if (message_id := str(raw_message_id or "").strip())
                }
            )
            if normalized:
                placeholders = ",".join("?" * len(normalized))
                identity_conditions.append(
                    "json_extract(task.spec_json, '$.pending_message_id') "
                    f"IN ({placeholders})"
                )
                identity_params.extend(normalized)
        if identity_conditions:
            conditions.append(f"({' OR '.join(identity_conditions)})")
            params.extend(identity_params)
        elif any(
            values is not None
            for values in (
                origin_turn_ids,
                task_ids,
                pending_message_ids,
            )
        ):
            return 0, 0
        scope_where = " AND ".join(conditions) if conditions else "1 = 1"
        scope_query = (
            "SELECT task.task_id FROM background_tasks AS task "
            f"WHERE {scope_where}"
        )
        handled_at = float(
            discarded_at if discarded_at is not None else time.time()
        )

        await self.initialize()
        async with sqlite_connection_async(self.db_path, profile="hot_write") as db:
            await db.execute("BEGIN IMMEDIATE")
            discarded = await db.execute(
                f"""
                UPDATE background_task_completion_intents
                SET state = 'discarded',
                    task_json = '{{}}',
                    intent_json = NULL,
                    composed_body = NULL,
                    claim_token = NULL,
                    claimed_at = NULL,
                    handled_at = ?
                WHERE state = 'pending'
                  AND task_id IN ({scope_query})
                """,
                [handled_at, *params],
            )
            processing_cursor = await db.execute(
                f"""
                SELECT COUNT(*)
                FROM background_task_completion_intents
                WHERE state = 'processing'
                  AND task_id IN ({scope_query})
                """,
                params,
            )
            processing_row = await processing_cursor.fetchone()
            await db.commit()
        return (
            int(discarded.rowcount or 0),
            int(processing_row[0]) if processing_row is not None else 0,
        )

    async def count_pending_completion_intents(self) -> int:
        """Return the number of recoverable completion intents."""

        await self.initialize()
        async with sqlite_connection_async(self.db_path, profile="readonly") as db:
            cursor = await db.execute(
                """
                SELECT COUNT(*)
                FROM background_task_completion_intents
                WHERE state = 'pending'
                """
            )
            row = await cursor.fetchone()
        return int(row[0]) if row is not None else 0

    @classmethod
    def _row_to_pending_completion(
        cls,
        row: aiosqlite.Row,
    ) -> PendingBackgroundTaskCompletion:
        payload = json.loads(str(row["task_json"] or "{}"))
        if not isinstance(payload, dict):
            raise ValueError("Background completion snapshot must be an object")
        task = cls._dict_to_task(payload)
        if task.status not in BackgroundTaskStatus.terminal():
            raise ValueError("Background completion snapshot is not terminal")
        return PendingBackgroundTaskCompletion(
            task=task,
            intent_json=(
                str(row["intent_json"])
                if row["intent_json"] is not None
                else None
            ),
            composed_body=(
                str(row["composed_body"])
                if row["composed_body"] is not None
                else None
            ),
        )

    @staticmethod
    async def _update_task_row(
        db: aiosqlite.Connection,
        task: BackgroundTask,
    ) -> None:
        cursor = await db.execute(
            """
            UPDATE background_tasks SET
                status = ?,
                attempt_index = ?,
                orchestration_id = ?,
                user_task_id = ?,
                summary = ?,
                result_payload_json = ?,
                error = ?,
                cancel_reason = ?,
                started_at = ?,
                finished_at = ?,
                updated_at = ?
            WHERE task_id = ?
            """,
            (
                task.status.value,
                int(task.attempt_index),
                task.orchestration_id,
                task.user_task_id,
                task.summary,
                json.dumps(task.result_payload, ensure_ascii=False),
                task.error,
                task.cancel_reason,
                float(task.started_at) if task.started_at is not None else None,
                float(task.finished_at) if task.finished_at is not None else None,
                float(task.updated_at),
                task.task_id,
            ),
        )
        if int(cursor.rowcount or 0) != 1:
            raise RuntimeError(
                f"Background task disappeared before terminal transition: {task.task_id}"
            )

    @staticmethod
    async def _insert_event_row(
        db: aiosqlite.Connection,
        event: BackgroundTaskEvent,
    ) -> None:
        await db.execute(
            """
            INSERT INTO background_task_events (
                event_id, task_id, attempt_index, event_type,
                from_status, to_status, message, payload_json, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                event.event_id,
                event.task_id,
                int(event.attempt_index),
                event.event_type,
                event.from_status.value if event.from_status is not None else None,
                event.to_status.value if event.to_status is not None else None,
                event.message,
                json.dumps(event.payload, ensure_ascii=False),
                float(event.created_at),
            ),
        )

    @staticmethod
    async def _insert_completion_intent_row(
        db: aiosqlite.Connection,
        task: BackgroundTask,
    ) -> None:
        await db.execute(
            """
            INSERT OR IGNORE INTO background_task_completion_intents (
                task_id,
                attempt_index,
                task_json,
                intent_json,
                composed_body,
                claim_token,
                claimed_at,
                state,
                created_at,
                handled_at
            ) VALUES (?, ?, ?, NULL, NULL, NULL, NULL, 'pending', ?, NULL)
            """,
            (
                task.task_id,
                int(task.attempt_index),
                json.dumps(
                    task.to_dict(),
                    ensure_ascii=False,
                    sort_keys=True,
                    separators=(",", ":"),
                ),
                float(task.finished_at or task.updated_at),
            ),
        )


__all__ = [
    "BackgroundTaskCompletionStoreMixin",
    "PendingBackgroundTaskCompletion",
]
