"""Durable intent/completion ledger for effectful tool invocations."""

from __future__ import annotations

import time
import uuid
from collections.abc import Iterable

import aiosqlite

from ...core.sqlite import sqlite_connection_async
from ..execution.tool_effects import (
    ToolEffectAdmission,
    ToolEffectIntent,
    ToolEffectState,
)

_UNRESOLVED_STATES = (
    ToolEffectState.ATTEMPTING.value,
    ToolEffectState.UNCERTAIN.value,
)
_TERMINAL_STATES = {
    ToolEffectState.SUCCEEDED,
    ToolEffectState.FAILED_NO_EFFECT,
    ToolEffectState.UNCERTAIN,
}


class BackgroundTaskEffectStoreMixin:
    """Store tool-effect intents in the runtime-owned background database."""

    db_path: str

    async def begin_tool_effect(
        self,
        intent: ToolEffectIntent,
        *,
        permit_ambiguous_retry: bool,
    ) -> ToolEffectAdmission:
        await self.initialize()
        now = time.time()
        async with sqlite_connection_async(self.db_path, profile="hot_write") as db:
            await db.execute("BEGIN IMMEDIATE")
            try:
                if not permit_ambiguous_retry:
                    blocked = await self._find_blocking_attempt(db, intent)
                    if blocked is not None:
                        await db.commit()
                        return ToolEffectAdmission(
                            attempt_id=None,
                            blocked_by_attempt_id=str(blocked[0]),
                            blocked_state=ToolEffectState(str(blocked[1])),
                        )

                attempt_id = f"effect_{uuid.uuid4().hex}"
                await db.execute(
                    """
                    INSERT INTO tool_effect_attempts (
                        attempt_id, semantic_key, scope_id,
                        user_id, session_id, turn_id, task_id, tool_call_id,
                        tool_name, replay_policy, arguments_digest,
                        idempotency_key_digest, state, error_code,
                        started_at, finished_at, updated_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, NULL, ?, NULL, ?)
                    """,
                    (
                        attempt_id,
                        intent.semantic_key,
                        intent.scope_id,
                        intent.user_id,
                        intent.session_id,
                        intent.turn_id,
                        intent.task_id,
                        intent.tool_call_id,
                        intent.tool_name,
                        intent.replay_policy.value,
                        intent.arguments_digest,
                        intent.idempotency_key_digest,
                        ToolEffectState.ATTEMPTING.value,
                        now,
                        now,
                    ),
                )
                await db.commit()
            except BaseException:
                await db.rollback()
                raise
        return ToolEffectAdmission(attempt_id=attempt_id)

    @staticmethod
    async def _find_blocking_attempt(
        db: aiosqlite.Connection,
        intent: ToolEffectIntent,
    ) -> tuple[object, object] | None:
        if intent.tool_call_id:
            cursor = await db.execute(
                """
                SELECT attempt_id, state
                FROM tool_effect_attempts
                WHERE scope_id = ? AND tool_name = ? AND tool_call_id = ?
                  AND state IN (?, ?, ?)
                ORDER BY started_at DESC
                LIMIT 1
                """,
                (
                    intent.scope_id,
                    intent.tool_name,
                    intent.tool_call_id,
                    ToolEffectState.ATTEMPTING.value,
                    ToolEffectState.SUCCEEDED.value,
                    ToolEffectState.UNCERTAIN.value,
                ),
            )
            exact = await cursor.fetchone()
            if exact is not None:
                return exact
        cursor = await db.execute(
            """
            SELECT attempt_id, state
            FROM tool_effect_attempts
            WHERE semantic_key = ? AND state IN (?, ?)
            ORDER BY started_at DESC
            LIMIT 1
            """,
            (intent.semantic_key, *_UNRESOLVED_STATES),
        )
        return await cursor.fetchone()

    async def finish_tool_effect(
        self,
        *,
        attempt_id: str,
        state: ToolEffectState,
        error_code: str | None = None,
    ) -> None:
        if state not in _TERMINAL_STATES:
            raise ValueError(f"Tool effect cannot finish in state: {state.value}")
        await self.initialize()
        now = time.time()
        async with sqlite_connection_async(self.db_path, profile="hot_write") as db:
            cursor = await db.execute(
                """
                UPDATE tool_effect_attempts
                SET state = ?, error_code = ?, finished_at = ?, updated_at = ?
                WHERE attempt_id = ? AND state = ?
                """,
                (
                    state.value,
                    error_code,
                    now,
                    now,
                    attempt_id,
                    ToolEffectState.ATTEMPTING.value,
                ),
            )
            if cursor.rowcount != 1:
                raise ValueError(f"Tool effect attempt is not active: {attempt_id}")
            await db.commit()

    async def recover_incomplete_tool_effects(self) -> int:
        """Convert attempts orphaned by process exit into explicit uncertainty."""
        await self.initialize()
        now = time.time()
        async with sqlite_connection_async(self.db_path, profile="hot_write") as db:
            cursor = await db.execute(
                """
                UPDATE tool_effect_attempts
                SET state = ?, error_code = ?, finished_at = ?, updated_at = ?
                WHERE state = ?
                """,
                (
                    ToolEffectState.UNCERTAIN.value,
                    "PROCESS_EXIT_DURING_EFFECT",
                    now,
                    now,
                    ToolEffectState.ATTEMPTING.value,
                ),
            )
            await db.commit()
            return max(0, int(cursor.rowcount))

    async def list_unresolved_tool_effects(self) -> list[dict[str, object]]:
        """Return privacy-minimized unresolved rows for recovery diagnostics."""
        await self.initialize()
        async with sqlite_connection_async(self.db_path, profile="readonly") as db:
            db.row_factory = aiosqlite.Row
            cursor = await db.execute(
                """
                SELECT attempt_id, semantic_key, scope_id, user_id, session_id,
                       turn_id, task_id, tool_call_id, tool_name, replay_policy,
                       arguments_digest, idempotency_key_digest, state,
                       error_code, started_at, finished_at, updated_at
                FROM tool_effect_attempts
                WHERE state IN (?, ?)
                ORDER BY started_at ASC
                """,
                _UNRESOLVED_STATES,
            )
            rows = await cursor.fetchall()
        return [dict(row) for row in rows]

    async def discard_tool_effects_for_scope(
        self,
        *,
        user_id: str | None = None,
        session_id: str | None = None,
        turn_ids: Iterable[str] | None = None,
        task_ids: Iterable[str] | None = None,
    ) -> int:
        scope_conditions: list[str] = []
        identity_conditions: list[str] = []
        parameters: list[object] = []
        for column, value in (("user_id", user_id), ("session_id", session_id)):
            normalized = str(value or "").strip()
            if normalized:
                scope_conditions.append(f"{column} = ?")
                parameters.append(normalized)
        for column, values in (("turn_id", turn_ids), ("task_id", task_ids)):
            normalized_values = sorted(
                {str(value).strip() for value in (values or ()) if str(value).strip()}
            )
            if normalized_values:
                placeholders = ",".join("?" for _ in normalized_values)
                identity_conditions.append(f"{column} IN ({placeholders})")
                parameters.extend(normalized_values)
        if not scope_conditions and not identity_conditions:
            return 0
        conditions = list(scope_conditions)
        if identity_conditions:
            conditions.append(f"({' OR '.join(identity_conditions)})")
        await self.initialize()
        async with sqlite_connection_async(self.db_path, profile="hot_write") as db:
            cursor = await db.execute(
                f"DELETE FROM tool_effect_attempts WHERE {' AND '.join(conditions)}",
                parameters,
            )
            await db.commit()
            return max(0, int(cursor.rowcount))


__all__ = ["BackgroundTaskEffectStoreMixin"]
