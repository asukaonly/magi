"""Durable append log and current surface for chat model context."""

from __future__ import annotations

import hashlib
import json
from typing import Any, Iterable
from uuid import uuid4

import aiosqlite

from ...agent.trace import now_wall_ms
from ...core.sqlite import sqlite_connection_async
from ..model_context import (
    ModelContextBoundary,
    ModelContextEvent,
    ModelContextItem,
    ModelContextRevisionConflictError,
    ModelContextSnapshot,
)


class ChatModelContextPersistenceMixin:
    """Persist reconstructible model context independently of visible chat."""

    db_path: str

    async def initialize(self) -> None:
        raise NotImplementedError

    async def load_model_context(self, *, session_id: str) -> ModelContextSnapshot:
        """Load the current ordered surface for one session."""

        normalized_session_id = _require_session_id(session_id)
        await self.initialize()
        async with sqlite_connection_async(self.db_path, profile="mixed") as db:
            db.row_factory = aiosqlite.Row
            return await self._load_model_context_with_connection(
                db,
                session_id=normalized_session_id,
            )

    async def append_model_context(
        self,
        *,
        session_id: str,
        items: Iterable[ModelContextItem],
        expected_revision: int | None = None,
        turn_id: str | None = None,
        run_id: str | None = None,
        step_index: int | None = None,
    ) -> ModelContextSnapshot:
        """Append items and expose them on the current surface atomically."""

        normalized_session_id = _require_session_id(session_id)
        normalized_items = tuple(items)
        if not normalized_items:
            return await self.load_model_context(session_id=normalized_session_id)
        await self.initialize()
        async with sqlite_connection_async(self.db_path, profile="mixed") as db:
            db.row_factory = aiosqlite.Row
            await db.execute("BEGIN IMMEDIATE")
            try:
                generation, revision, last_sequence_no = await self._ensure_head(
                    db,
                    session_id=normalized_session_id,
                )
                _check_revision(expected_revision, revision)
                start_position = await self._next_surface_position(
                    db,
                    session_id=normalized_session_id,
                    generation=generation,
                )
                next_sequence_no = last_sequence_no
                created_at_ms = now_wall_ms()
                for offset, item in enumerate(normalized_items):
                    next_sequence_no += 1
                    event_id = uuid4().hex
                    await self._insert_event(
                        db,
                        event_id=event_id,
                        session_id=normalized_session_id,
                        generation=generation,
                        sequence_no=next_sequence_no,
                        operation="append",
                        item=item,
                        turn_id=turn_id,
                        run_id=run_id,
                        step_index=step_index,
                        created_at_ms=created_at_ms,
                    )
                    await db.execute(
                        """
                        INSERT INTO chat_model_context_surface_nodes(
                            session_id,
                            generation,
                            position,
                            event_sequence_no
                        )
                        VALUES (?, ?, ?, ?)
                        """,
                        (
                            normalized_session_id,
                            generation,
                            start_position + offset,
                            next_sequence_no,
                        ),
                    )
                await self._update_head(
                    db,
                    session_id=normalized_session_id,
                    generation=generation,
                    revision=revision + 1,
                    last_sequence_no=next_sequence_no,
                    updated_at_ms=created_at_ms,
                )
                await db.commit()
            except BaseException:
                await db.rollback()
                raise
            return await self._load_model_context_with_connection(
                db,
                session_id=normalized_session_id,
            )

    async def replace_model_context_surface(
        self,
        *,
        session_id: str,
        items: Iterable[ModelContextItem],
        expected_revision: int,
        turn_id: str | None = None,
        run_id: str | None = None,
        step_index: int | None = None,
    ) -> ModelContextSnapshot:
        """Replace the current surface while retaining prior log events."""

        normalized_session_id = _require_session_id(session_id)
        normalized_items = tuple(items)
        await self.initialize()
        async with sqlite_connection_async(self.db_path, profile="mixed") as db:
            db.row_factory = aiosqlite.Row
            await db.execute("BEGIN IMMEDIATE")
            try:
                generation, revision, last_sequence_no = await self._ensure_head(
                    db,
                    session_id=normalized_session_id,
                )
                _check_revision(expected_revision, revision)
                await db.execute(
                    """
                    DELETE FROM chat_model_context_surface_nodes
                    WHERE session_id = ? AND generation = ?
                    """,
                    (normalized_session_id, generation),
                )
                next_sequence_no = last_sequence_no
                created_at_ms = now_wall_ms()
                for position, item in enumerate(normalized_items):
                    next_sequence_no += 1
                    event_id = uuid4().hex
                    await self._insert_event(
                        db,
                        event_id=event_id,
                        session_id=normalized_session_id,
                        generation=generation,
                        sequence_no=next_sequence_no,
                        operation="surface_replace",
                        item=item,
                        turn_id=turn_id,
                        run_id=run_id,
                        step_index=step_index,
                        created_at_ms=created_at_ms,
                    )
                    await db.execute(
                        """
                        INSERT INTO chat_model_context_surface_nodes(
                            session_id,
                            generation,
                            position,
                            event_sequence_no
                        )
                        VALUES (?, ?, ?, ?)
                        """,
                        (
                            normalized_session_id,
                            generation,
                            position,
                            next_sequence_no,
                        ),
                    )
                await self._update_head(
                    db,
                    session_id=normalized_session_id,
                    generation=generation,
                    revision=revision + 1,
                    last_sequence_no=next_sequence_no,
                    updated_at_ms=created_at_ms,
                )
                await db.commit()
            except BaseException:
                await db.rollback()
                raise
            return await self._load_model_context_with_connection(
                db,
                session_id=normalized_session_id,
            )

    async def sync_model_context_surface(
        self,
        *,
        session_id: str,
        items: Iterable[ModelContextItem],
        expected_revision: int,
        turn_id: str | None = None,
        run_id: str | None = None,
        step_index: int | None = None,
    ) -> ModelContextSnapshot:
        """Append a suffix or atomically replace a changed surface."""

        desired = tuple(items)
        current = await self.load_model_context(session_id=session_id)
        _check_revision(expected_revision, current.revision)
        current_payloads = [item.to_payload() for item in current.items]
        desired_payloads = [item.to_payload() for item in desired]
        if current_payloads == desired_payloads:
            return current
        if desired_payloads[: len(current_payloads)] == current_payloads:
            return await self.append_model_context(
                session_id=session_id,
                items=desired[len(current_payloads) :],
                expected_revision=current.revision,
                turn_id=turn_id,
                run_id=run_id,
                step_index=step_index,
            )
        return await self.replace_model_context_surface(
            session_id=session_id,
            items=desired,
            expected_revision=current.revision,
            turn_id=turn_id,
            run_id=run_id,
            step_index=step_index,
        )

    async def reset_model_context(self, *, session_id: str) -> None:
        """Physically remove all context-log and surface rows for one session."""

        normalized_session_id = _require_session_id(session_id)
        await self.initialize()
        async with sqlite_connection_async(self.db_path, profile="mixed") as db:
            await db.execute("BEGIN IMMEDIATE")
            try:
                for table in (
                    "chat_model_context_boundaries",
                    "chat_model_context_epochs",
                    "chat_model_context_surface_nodes",
                    "chat_model_context_events",
                    "chat_model_context_heads",
                ):
                    await db.execute(
                        f"DELETE FROM {table} WHERE session_id = ?",
                        (normalized_session_id,),
                    )
                await db.commit()
            except BaseException:
                await db.rollback()
                raise

    async def record_model_context_boundary(
        self,
        *,
        session_id: str,
        surface_revision: int,
        system_prompt: str,
        tools: list[dict[str, Any]],
        boundary_kind: str,
        turn_id: str | None = None,
        run_id: str | None = None,
        step_index: int | None = None,
    ) -> ModelContextBoundary:
        """Record the exact stable prompt/tool epoch used by one model call."""

        normalized_session_id = _require_session_id(session_id)
        normalized_kind = str(boundary_kind or "").strip()
        if not normalized_kind:
            raise ValueError("Model-context boundary kind is required")
        normalized_system_prompt = str(system_prompt or "")
        normalized_tools = [dict(tool) for tool in tools]
        tools_json = _canonical_json(normalized_tools)
        system_hash = _content_hash(normalized_system_prompt)
        tools_hash = _content_hash(tools_json)
        await self.initialize()
        async with sqlite_connection_async(self.db_path, profile="mixed") as db:
            db.row_factory = aiosqlite.Row
            await db.execute("BEGIN IMMEDIATE")
            try:
                generation, revision, _ = await self._ensure_head(
                    db,
                    session_id=normalized_session_id,
                )
                _check_revision(surface_revision, revision)
                epoch_id = uuid4().hex
                created_at_ms = now_wall_ms()
                await db.execute(
                    """
                    INSERT OR IGNORE INTO chat_model_context_epochs(
                        epoch_id,
                        session_id,
                        generation,
                        system_hash,
                        system_prompt,
                        tools_hash,
                        tools_json,
                        created_at_ms
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        epoch_id,
                        normalized_session_id,
                        generation,
                        system_hash,
                        normalized_system_prompt,
                        tools_hash,
                        tools_json,
                        created_at_ms,
                    ),
                )
                cursor = await db.execute(
                    """
                    SELECT epoch_id
                    FROM chat_model_context_epochs
                    WHERE session_id = ? COLLATE NOCASE
                      AND generation = ?
                      AND system_hash = ?
                      AND tools_hash = ?
                    """,
                    (
                        normalized_session_id,
                        generation,
                        system_hash,
                        tools_hash,
                    ),
                )
                epoch_row = await cursor.fetchone()
                if epoch_row is None:  # pragma: no cover - transaction invariant
                    raise RuntimeError("Model-context epoch insert was not observable")
                epoch_id = str(epoch_row["epoch_id"])
                cursor = await db.execute(
                    """
                    SELECT COALESCE(MAX(boundary_no), 0) + 1
                    FROM chat_model_context_boundaries
                    WHERE session_id = ? COLLATE NOCASE AND generation = ?
                    """,
                    (normalized_session_id, generation),
                )
                boundary_no_row = await cursor.fetchone()
                boundary_no = int(boundary_no_row[0] if boundary_no_row is not None else 1)
                boundary_id = uuid4().hex
                await db.execute(
                    """
                    INSERT INTO chat_model_context_boundaries(
                        boundary_id,
                        session_id,
                        generation,
                        boundary_no,
                        surface_revision,
                        epoch_id,
                        boundary_kind,
                        turn_id,
                        run_id,
                        step_index,
                        created_at_ms
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        boundary_id,
                        normalized_session_id,
                        generation,
                        boundary_no,
                        revision,
                        epoch_id,
                        normalized_kind,
                        turn_id,
                        run_id,
                        step_index,
                        created_at_ms,
                    ),
                )
                await db.commit()
            except BaseException:
                await db.rollback()
                raise
        return ModelContextBoundary(
            boundary_id=boundary_id,
            session_id=normalized_session_id,
            generation=generation,
            boundary_no=boundary_no,
            surface_revision=revision,
            epoch_id=epoch_id,
            boundary_kind=normalized_kind,
            turn_id=turn_id,
            run_id=run_id,
            step_index=step_index,
            created_at_ms=created_at_ms,
        )

    async def _ensure_head(
        self,
        db: aiosqlite.Connection,
        *,
        session_id: str,
    ) -> tuple[int, int, int]:
        cursor = await db.execute(
            """
            SELECT generation, revision, last_sequence_no
            FROM chat_model_context_heads
            WHERE session_id = ? COLLATE NOCASE
            """,
            (session_id,),
        )
        row = await cursor.fetchone()
        if row is None:
            timestamp = now_wall_ms()
            await db.execute(
                """
                INSERT INTO chat_model_context_heads(
                    session_id,
                    generation,
                    revision,
                    last_sequence_no,
                    updated_at_ms
                )
                VALUES (?, 1, 0, 0, ?)
                """,
                (session_id, timestamp),
            )
            return 1, 0, 0
        return (
            int(row["generation"]),
            int(row["revision"]),
            int(row["last_sequence_no"]),
        )

    async def _next_surface_position(
        self,
        db: aiosqlite.Connection,
        *,
        session_id: str,
        generation: int,
    ) -> int:
        cursor = await db.execute(
            """
            SELECT COALESCE(MAX(position), -1) + 1
            FROM chat_model_context_surface_nodes
            WHERE session_id = ? AND generation = ?
            """,
            (session_id, generation),
        )
        row = await cursor.fetchone()
        return int(row[0] if row is not None else 0)

    async def _insert_event(
        self,
        db: aiosqlite.Connection,
        *,
        event_id: str,
        session_id: str,
        generation: int,
        sequence_no: int,
        operation: str,
        item: ModelContextItem,
        turn_id: str | None,
        run_id: str | None,
        step_index: int | None,
        created_at_ms: int,
    ) -> None:
        await db.execute(
            """
            INSERT INTO chat_model_context_events(
                event_id,
                session_id,
                generation,
                sequence_no,
                operation,
                item_kind,
                item_json,
                turn_id,
                run_id,
                step_index,
                created_at_ms
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                event_id,
                session_id,
                generation,
                sequence_no,
                operation,
                item.kind.value,
                json.dumps(item.to_payload(), ensure_ascii=False, separators=(",", ":")),
                turn_id,
                run_id,
                step_index,
                created_at_ms,
            ),
        )

    async def _update_head(
        self,
        db: aiosqlite.Connection,
        *,
        session_id: str,
        generation: int,
        revision: int,
        last_sequence_no: int,
        updated_at_ms: int,
    ) -> None:
        await db.execute(
            """
            UPDATE chat_model_context_heads
            SET revision = ?, last_sequence_no = ?, updated_at_ms = ?
            WHERE session_id = ? AND generation = ?
            """,
            (
                revision,
                last_sequence_no,
                updated_at_ms,
                session_id,
                generation,
            ),
        )

    async def _load_model_context_with_connection(
        self,
        db: aiosqlite.Connection,
        *,
        session_id: str,
    ) -> ModelContextSnapshot:
        cursor = await db.execute(
            """
            SELECT generation, revision
            FROM chat_model_context_heads
            WHERE session_id = ? COLLATE NOCASE
            """,
            (session_id,),
        )
        head = await cursor.fetchone()
        if head is None:
            return ModelContextSnapshot(session_id=session_id, generation=1, revision=0)
        generation = int(head["generation"])
        cursor = await db.execute(
            """
            SELECT
                events.event_id,
                events.sequence_no,
                events.operation,
                events.item_json,
                events.turn_id,
                events.run_id,
                events.step_index,
                events.created_at_ms
            FROM chat_model_context_surface_nodes AS nodes
            JOIN chat_model_context_events AS events
              ON events.session_id = nodes.session_id
             AND events.generation = nodes.generation
             AND events.sequence_no = nodes.event_sequence_no
            WHERE nodes.session_id = ? COLLATE NOCASE
              AND nodes.generation = ?
            ORDER BY nodes.position ASC
            """,
            (session_id, generation),
        )
        rows = await cursor.fetchall()
        events = tuple(
            ModelContextEvent(
                event_id=str(row["event_id"]),
                session_id=session_id,
                generation=generation,
                sequence_no=int(row["sequence_no"]),
                operation=str(row["operation"]),
                item=ModelContextItem.from_payload(json.loads(str(row["item_json"]))),
                turn_id=str(row["turn_id"]) if row["turn_id"] is not None else None,
                run_id=str(row["run_id"]) if row["run_id"] is not None else None,
                step_index=int(row["step_index"]) if row["step_index"] is not None else None,
                created_at_ms=int(row["created_at_ms"]),
            )
            for row in rows
        )
        return ModelContextSnapshot(
            session_id=session_id,
            generation=generation,
            revision=int(head["revision"]),
            events=events,
        )


def _require_session_id(session_id: str) -> str:
    normalized = str(session_id or "").strip()
    if not normalized:
        raise ValueError("Session ID is required")
    return normalized


def _check_revision(expected: int | None, actual: int) -> None:
    if expected is not None and expected != actual:
        raise ModelContextRevisionConflictError(
            f"Model-context revision conflict: expected {expected}, found {actual}"
        )


def _canonical_json(value: Any) -> str:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    )


def _content_hash(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


__all__ = ["ChatModelContextPersistenceMixin"]
