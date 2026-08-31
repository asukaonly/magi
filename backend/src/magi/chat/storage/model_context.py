"""Durable accepted and run-working model-context surfaces."""

from __future__ import annotations

from dataclasses import dataclass
from difflib import SequenceMatcher
import hashlib
import json
from typing import Any, Iterable, Mapping
from uuid import uuid4

import aiosqlite

from ...agent.trace import now_wall_ms
from ...core.sqlite import sqlite_connection_async
from ...utils.model_message_protocol import protocol_complete_message_indexes
from ..model_context import (
    ModelContextBoundary,
    ModelContextCallSnapshot,
    ModelContextEpoch,
    ModelContextEvent,
    ModelContextItem,
    ModelContextItemKind,
    ModelContextRevisionConflictError,
    ModelContextScope,
    ModelContextSnapshot,
)


@dataclass(frozen=True, slots=True)
class _HeadState:
    generation: int
    revision: int
    accepted_revision: int
    last_sequence_no: int


class ChatModelContextPersistenceMixin:
    """Persist immutable model-context revisions and isolated run branches."""

    db_path: str

    async def initialize(self) -> None:
        raise NotImplementedError

    async def load_model_context(
        self,
        *,
        session_id: str,
        run_id: str | None = None,
        revision: int | None = None,
    ) -> ModelContextSnapshot:
        """Load the accepted, active working, or named immutable revision."""

        normalized_session_id = _require_identifier(session_id, "Session ID")
        normalized_run_id = _normalize_optional_identifier(run_id)
        if revision is not None and revision < 0:
            raise ValueError("Model-context revision cannot be negative")
        if revision is not None and normalized_run_id is not None:
            raise ValueError("Run ID and explicit revision are mutually exclusive")
        await self.initialize()
        async with sqlite_connection_async(self.db_path, profile="mixed") as db:
            db.row_factory = aiosqlite.Row
            return await self._load_model_context_with_connection(
                db,
                session_id=normalized_session_id,
                run_id=normalized_run_id,
                revision=revision,
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
        """Append directly to the accepted surface.

        Runtime execution must use ``sync_model_context_surface`` instead. This
        method remains the explicit maintenance seam for accepted context.
        """

        normalized_session_id = _require_identifier(session_id, "Session ID")
        normalized_items = tuple(items)
        if not normalized_items:
            return await self.load_model_context(session_id=normalized_session_id)
        await self.initialize()
        async with sqlite_connection_async(self.db_path, profile="mixed") as db:
            db.row_factory = aiosqlite.Row
            await db.execute("BEGIN IMMEDIATE")
            try:
                head = await self._ensure_head(db, session_id=normalized_session_id)
                _check_revision(expected_revision, head.accepted_revision)
                current = await self._load_revision_with_connection(
                    db,
                    session_id=normalized_session_id,
                    head=head,
                    revision=head.accepted_revision,
                )
                snapshot = await self._write_revision(
                    db,
                    session_id=normalized_session_id,
                    head=head,
                    current=current,
                    items=(*current.items, *normalized_items),
                    operation="append",
                    turn_id=turn_id,
                    run_id=run_id,
                    step_index=step_index,
                    accept=True,
                )
                await db.commit()
                return snapshot
            except BaseException:
                await db.rollback()
                raise

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
        """Replace the accepted surface with a new immutable revision."""

        normalized_session_id = _require_identifier(session_id, "Session ID")
        await self.initialize()
        async with sqlite_connection_async(self.db_path, profile="mixed") as db:
            db.row_factory = aiosqlite.Row
            await db.execute("BEGIN IMMEDIATE")
            try:
                head = await self._ensure_head(db, session_id=normalized_session_id)
                _check_revision(expected_revision, head.accepted_revision)
                current = await self._load_revision_with_connection(
                    db,
                    session_id=normalized_session_id,
                    head=head,
                    revision=head.accepted_revision,
                )
                snapshot = await self._write_revision(
                    db,
                    session_id=normalized_session_id,
                    head=head,
                    current=current,
                    items=tuple(items),
                    operation="accepted_replace",
                    turn_id=turn_id,
                    run_id=run_id,
                    step_index=step_index,
                    accept=True,
                )
                await db.commit()
                return snapshot
            except BaseException:
                await db.rollback()
                raise

    async def sync_model_context_surface(
        self,
        *,
        session_id: str,
        items: Iterable[ModelContextItem],
        expected_revision: int,
        turn_id: str | None,
        run_id: str,
        step_index: int | None = None,
    ) -> ModelContextSnapshot:
        """Synchronize one run's isolated working surface."""

        normalized_session_id = _require_identifier(session_id, "Session ID")
        normalized_run_id = _require_identifier(run_id, "Run ID")
        await self.initialize()
        async with sqlite_connection_async(self.db_path, profile="mixed") as db:
            db.row_factory = aiosqlite.Row
            await db.execute("BEGIN IMMEDIATE")
            try:
                snapshot = await self._sync_working_surface_with_connection(
                    db,
                    session_id=normalized_session_id,
                    run_id=normalized_run_id,
                    turn_id=turn_id,
                    items=tuple(items),
                    expected_revision=expected_revision,
                    step_index=step_index,
                )
                await db.commit()
                return snapshot
            except BaseException:
                await db.rollback()
                raise

    async def prepare_model_context_call(
        self,
        *,
        session_id: str,
        items: Iterable[ModelContextItem],
        expected_revision: int,
        system_prompt: str,
        tools: list[dict[str, Any]],
        boundary_kind: str,
        turn_id: str | None,
        run_id: str,
        step_index: int | None = None,
        request_options: Mapping[str, Any] | None = None,
    ) -> tuple[ModelContextSnapshot, ModelContextBoundary]:
        """Atomically persist a working surface and its model-call boundary."""

        normalized_session_id = _require_identifier(session_id, "Session ID")
        normalized_run_id = _require_identifier(run_id, "Run ID")
        await self.initialize()
        async with sqlite_connection_async(self.db_path, profile="mixed") as db:
            db.row_factory = aiosqlite.Row
            await db.execute("BEGIN IMMEDIATE")
            try:
                snapshot = await self._sync_working_surface_with_connection(
                    db,
                    session_id=normalized_session_id,
                    run_id=normalized_run_id,
                    turn_id=turn_id,
                    items=tuple(items),
                    expected_revision=expected_revision,
                    step_index=step_index,
                )
                boundary = await self._record_boundary_with_connection(
                    db,
                    session_id=normalized_session_id,
                    surface_revision=snapshot.revision,
                    system_prompt=system_prompt,
                    tools=tools,
                    boundary_kind=boundary_kind,
                    turn_id=turn_id,
                    run_id=normalized_run_id,
                    step_index=step_index,
                    request_options=request_options,
                )
                await db.commit()
                return snapshot, boundary
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
        request_options: Mapping[str, Any] | None = None,
    ) -> ModelContextBoundary:
        """Record a boundary for an already durable immutable revision."""

        normalized_session_id = _require_identifier(session_id, "Session ID")
        await self.initialize()
        async with sqlite_connection_async(self.db_path, profile="mixed") as db:
            db.row_factory = aiosqlite.Row
            await db.execute("BEGIN IMMEDIATE")
            try:
                boundary = await self._record_boundary_with_connection(
                    db,
                    session_id=normalized_session_id,
                    surface_revision=surface_revision,
                    system_prompt=system_prompt,
                    tools=tools,
                    boundary_kind=boundary_kind,
                    turn_id=turn_id,
                    run_id=run_id,
                    step_index=step_index,
                    request_options=request_options,
                )
                await db.commit()
                return boundary
            except BaseException:
                await db.rollback()
                raise

    async def load_model_context_call(
        self,
        *,
        boundary_id: str,
    ) -> ModelContextCallSnapshot:
        """Reconstruct the exact provider-neutral input of one model call."""

        normalized_boundary_id = _require_identifier(boundary_id, "Boundary ID")
        await self.initialize()
        async with sqlite_connection_async(self.db_path, profile="mixed") as db:
            db.row_factory = aiosqlite.Row
            cursor = await db.execute(
                """
                SELECT boundaries.*, epochs.system_prompt, epochs.tools_json,
                       epochs.system_hash, epochs.tools_hash, epochs.created_at_ms AS epoch_created_at_ms
                FROM chat_model_context_boundaries AS boundaries
                JOIN chat_model_context_epochs AS epochs
                  ON epochs.epoch_id = boundaries.epoch_id
                WHERE boundaries.boundary_id = ?
                """,
                (normalized_boundary_id,),
            )
            row = await cursor.fetchone()
            if row is None:
                raise KeyError(f"Unknown model-context boundary: {normalized_boundary_id}")
            boundary = _boundary_from_row(row)
            epoch = ModelContextEpoch(
                epoch_id=boundary.epoch_id,
                session_id=boundary.session_id,
                generation=boundary.generation,
                system_prompt=str(row["system_prompt"]),
                tools=tuple(json.loads(str(row["tools_json"]))),
                system_hash=str(row["system_hash"]),
                tools_hash=str(row["tools_hash"]),
                created_at_ms=int(row["epoch_created_at_ms"]),
            )
            surface = await self._load_model_context_with_connection(
                db,
                session_id=boundary.session_id,
                revision=boundary.surface_revision,
            )
            return ModelContextCallSnapshot(boundary=boundary, epoch=epoch, surface=surface)

    async def reset_model_context(self, *, session_id: str) -> None:
        """Physically remove all model-context rows for one session."""

        normalized_session_id = _require_identifier(session_id, "Session ID")
        await self.initialize()
        async with sqlite_connection_async(self.db_path, profile="mixed") as db:
            await db.execute("BEGIN IMMEDIATE")
            try:
                for table in (
                    "chat_model_context_boundaries",
                    "chat_model_context_epochs",
                    "chat_model_context_run_heads",
                    "chat_model_context_surface_nodes",
                    "chat_model_context_revisions",
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

    async def _promote_model_context_run_with_connection(
        self,
        db: aiosqlite.Connection,
        *,
        session_id: str,
        run_id: str,
        turn_id: str,
        outcome_text: str,
        outcome_kind: str,
        persona_id: str | None,
        completed_at_ms: int,
    ) -> ModelContextSnapshot | None:
        """Promote a working branch inside the visible-outcome transaction."""

        normalized_session_id = _require_identifier(session_id, "Session ID")
        normalized_run_id = _require_identifier(run_id, "Run ID")
        head = await self._ensure_head(db, session_id=normalized_session_id)
        run_head = await self._load_run_head(
            db,
            session_id=normalized_session_id,
            run_id=normalized_run_id,
        )
        if run_head is None:
            accepted = await self._load_revision_with_connection(
                db,
                session_id=normalized_session_id,
                head=head,
                revision=head.accepted_revision,
            )
            source_items = list(accepted.items)
            if not accepted.contains_turn(turn_id):
                cursor = await db.execute(
                    """
                    SELECT content_text, persona_id
                    FROM chat_messages
                    WHERE session_id = ? COLLATE NOCASE AND turn_id = ?
                      AND role = 'user' AND is_visible = 1
                    ORDER BY sequence_no ASC
                    LIMIT 1
                    """,
                    (normalized_session_id, turn_id),
                )
                user_row = await cursor.fetchone()
                if user_row is not None:
                    user_metadata: dict[str, Any] = {"origin_turn_id": turn_id}
                    user_persona_id = str(user_row["persona_id"] or "").strip()
                    if user_persona_id:
                        user_metadata["persona_id"] = user_persona_id
                    source_items.append(
                        ModelContextItem.from_prompt_message(
                            {
                                "role": "user",
                                "content": str(user_row["content_text"] or ""),
                            },
                            source="user",
                            scope=ModelContextScope.SESSION,
                            metadata=user_metadata,
                        )
                    )
            accepted_items = _accepted_outcome_items(
                tuple(source_items),
                turn_id=turn_id,
                outcome_text=outcome_text,
                outcome_kind=outcome_kind,
                persona_id=persona_id,
            )
            if _item_payloads(accepted_items) == _item_payloads(accepted.items):
                return accepted
            return await self._write_revision(
                db,
                session_id=normalized_session_id,
                head=head,
                current=accepted,
                items=accepted_items,
                operation="run_accept",
                turn_id=turn_id,
                run_id=normalized_run_id,
                step_index=None,
                accept=True,
                created_at_ms=completed_at_ms,
            )
        if str(run_head["status"]) != "active":
            return await self._load_revision_with_connection(
                db,
                session_id=normalized_session_id,
                head=head,
                revision=head.accepted_revision,
            )
        base_revision = int(run_head["base_revision"])
        if base_revision != head.accepted_revision:
            raise ModelContextRevisionConflictError(
                "Cannot promote a model-context run based on a stale accepted revision"
            )
        working_revision = int(run_head["working_revision"])
        working = await self._load_revision_with_connection(
            db,
            session_id=normalized_session_id,
            head=head,
            revision=working_revision,
            run_id=normalized_run_id,
        )
        accepted_items = _accepted_outcome_items(
            working.items,
            turn_id=turn_id,
            outcome_text=outcome_text,
            outcome_kind=outcome_kind,
            persona_id=persona_id,
        )
        if _item_payloads(accepted_items) == _item_payloads(working.items):
            await db.execute(
                """
                UPDATE chat_model_context_heads
                SET accepted_revision = ?, updated_at_ms = ?
                WHERE session_id = ? COLLATE NOCASE AND generation = ?
                """,
                (working_revision, completed_at_ms, normalized_session_id, head.generation),
            )
            snapshot = ModelContextSnapshot(
                session_id=normalized_session_id,
                generation=head.generation,
                revision=working_revision,
                accepted_revision=working_revision,
                events=working.events,
            )
        else:
            snapshot = await self._write_revision(
                db,
                session_id=normalized_session_id,
                head=head,
                current=working,
                items=accepted_items,
                operation="run_accept",
                turn_id=turn_id,
                run_id=normalized_run_id,
                step_index=None,
                accept=True,
                created_at_ms=completed_at_ms,
            )
        await db.execute(
            """
            UPDATE chat_model_context_run_heads
            SET status = 'accepted', updated_at_ms = ?
            WHERE session_id = ? COLLATE NOCASE AND run_id = ?
            """,
            (completed_at_ms, normalized_session_id, normalized_run_id),
        )
        return snapshot

    async def _sync_working_surface_with_connection(
        self,
        db: aiosqlite.Connection,
        *,
        session_id: str,
        run_id: str,
        turn_id: str | None,
        items: tuple[ModelContextItem, ...],
        expected_revision: int,
        step_index: int | None,
    ) -> ModelContextSnapshot:
        head = await self._ensure_head(db, session_id=session_id)
        run_head = await self._load_run_head(db, session_id=session_id, run_id=run_id)
        if run_head is None:
            _check_revision(expected_revision, head.accepted_revision)
            timestamp = now_wall_ms()
            await db.execute(
                """
                UPDATE chat_model_context_run_heads
                SET status = 'abandoned', updated_at_ms = ?
                WHERE session_id = ? COLLATE NOCASE AND status = 'active'
                """,
                (timestamp, session_id),
            )
            await db.execute(
                """
                INSERT INTO chat_model_context_run_heads(
                    session_id, run_id, turn_id, generation, base_revision,
                    working_revision, status, updated_at_ms
                )
                VALUES (?, ?, ?, ?, ?, ?, 'active', ?)
                """,
                (
                    session_id,
                    run_id,
                    turn_id,
                    head.generation,
                    head.accepted_revision,
                    head.accepted_revision,
                    timestamp,
                ),
            )
            working_revision = head.accepted_revision
        else:
            if str(run_head["status"]) != "active":
                raise ModelContextRevisionConflictError(
                    f"Model-context run is no longer active: {run_id}"
                )
            working_revision = int(run_head["working_revision"])
            _check_revision(expected_revision, working_revision)
        current = await self._load_revision_with_connection(
            db,
            session_id=session_id,
            head=head,
            revision=working_revision,
            run_id=run_id,
        )
        if _item_payloads(current.items) == _item_payloads(items):
            return current
        operation = (
            "working_append"
            if _is_prefix(current.items, items)
            else "working_replace"
        )
        snapshot = await self._write_revision(
            db,
            session_id=session_id,
            head=head,
            current=current,
            items=items,
            operation=operation,
            turn_id=turn_id,
            run_id=run_id,
            step_index=step_index,
            accept=False,
        )
        await db.execute(
            """
            UPDATE chat_model_context_run_heads
            SET working_revision = ?, turn_id = COALESCE(?, turn_id), updated_at_ms = ?
            WHERE session_id = ? COLLATE NOCASE AND run_id = ? AND status = 'active'
            """,
            (snapshot.revision, turn_id, now_wall_ms(), session_id, run_id),
        )
        return snapshot

    async def _write_revision(
        self,
        db: aiosqlite.Connection,
        *,
        session_id: str,
        head: _HeadState,
        current: ModelContextSnapshot,
        items: tuple[ModelContextItem, ...],
        operation: str,
        turn_id: str | None,
        run_id: str | None,
        step_index: int | None,
        accept: bool,
        created_at_ms: int | None = None,
    ) -> ModelContextSnapshot:
        timestamp = created_at_ms if created_at_ms is not None else now_wall_ms()
        revision = head.revision + 1
        next_sequence_no = head.last_sequence_no
        reused = _matching_event_sequences(current, items)
        events: list[ModelContextEvent] = []
        for position, item in enumerate(items):
            existing = reused.get(position)
            if existing is None:
                next_sequence_no += 1
                existing = ModelContextEvent(
                    event_id=uuid4().hex,
                    session_id=session_id,
                    generation=head.generation,
                    sequence_no=next_sequence_no,
                    operation=operation,
                    item=item,
                    turn_id=turn_id,
                    run_id=run_id,
                    step_index=step_index,
                    created_at_ms=timestamp,
                )
                await self._insert_event(db, event=existing)
            events.append(existing)
            await db.execute(
                """
                INSERT INTO chat_model_context_surface_nodes(
                    session_id, generation, revision, position, event_sequence_no
                )
                VALUES (?, ?, ?, ?, ?)
                """,
                (
                    session_id,
                    head.generation,
                    revision,
                    position,
                    existing.sequence_no,
                ),
            )
        accepted_revision = revision if accept else head.accepted_revision
        await db.execute(
            """
            INSERT INTO chat_model_context_revisions(
                session_id, generation, revision, parent_revision,
                branch_kind, run_id, item_count, created_at_ms
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                session_id,
                head.generation,
                revision,
                current.revision,
                "accepted" if accept else "working",
                run_id,
                len(items),
                timestamp,
            ),
        )
        cursor = await db.execute(
            """
            UPDATE chat_model_context_heads
            SET revision = ?, accepted_revision = ?, last_sequence_no = ?, updated_at_ms = ?
            WHERE session_id = ? COLLATE NOCASE AND generation = ? AND revision = ?
            """,
            (
                revision,
                accepted_revision,
                next_sequence_no,
                timestamp,
                session_id,
                head.generation,
                head.revision,
            ),
        )
        if cursor.rowcount != 1:
            raise ModelContextRevisionConflictError(
                "Model-context head changed while writing a new revision"
            )
        return ModelContextSnapshot(
            session_id=session_id,
            generation=head.generation,
            revision=revision,
            accepted_revision=accepted_revision,
            run_id=None if accept else run_id,
            events=tuple(events),
        )

    async def _record_boundary_with_connection(
        self,
        db: aiosqlite.Connection,
        *,
        session_id: str,
        surface_revision: int,
        system_prompt: str,
        tools: list[dict[str, Any]],
        boundary_kind: str,
        turn_id: str | None,
        run_id: str | None,
        step_index: int | None,
        request_options: Mapping[str, Any] | None,
    ) -> ModelContextBoundary:
        normalized_kind = str(boundary_kind or "").strip()
        if not normalized_kind:
            raise ValueError("Model-context boundary kind is required")
        head = await self._ensure_head(db, session_id=session_id)
        if surface_revision < 0 or surface_revision > head.revision:
            raise ModelContextRevisionConflictError(
                f"Unknown model-context revision: {surface_revision}"
            )
        if surface_revision > 0:
            cursor = await db.execute(
                """
                SELECT 1 FROM chat_model_context_revisions
                WHERE session_id = ? COLLATE NOCASE AND generation = ? AND revision = ?
                """,
                (session_id, head.generation, surface_revision),
            )
            if await cursor.fetchone() is None:
                raise ModelContextRevisionConflictError(
                    f"Unknown model-context revision: {surface_revision}"
                )
        normalized_system_prompt = str(system_prompt or "")
        normalized_tools = [dict(tool) for tool in tools]
        tools_json = _canonical_json(normalized_tools)
        system_hash = _content_hash(normalized_system_prompt)
        tools_hash = _content_hash(tools_json)
        timestamp = now_wall_ms()
        epoch_id = uuid4().hex
        await db.execute(
            """
            INSERT OR IGNORE INTO chat_model_context_epochs(
                epoch_id, session_id, generation, system_hash, system_prompt,
                tools_hash, tools_json, created_at_ms
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                epoch_id,
                session_id,
                head.generation,
                system_hash,
                normalized_system_prompt,
                tools_hash,
                tools_json,
                timestamp,
            ),
        )
        cursor = await db.execute(
            """
            SELECT epoch_id FROM chat_model_context_epochs
            WHERE session_id = ? COLLATE NOCASE AND generation = ?
              AND system_hash = ? AND tools_hash = ?
            """,
            (session_id, head.generation, system_hash, tools_hash),
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
            (session_id, head.generation),
        )
        row = await cursor.fetchone()
        boundary_no = int(row[0] if row is not None else 1)
        boundary_id = uuid4().hex
        options = dict(request_options or {})
        await db.execute(
            """
            INSERT INTO chat_model_context_boundaries(
                boundary_id, session_id, generation, boundary_no,
                surface_revision, epoch_id, boundary_kind, turn_id, run_id,
                step_index, request_options_json, created_at_ms
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                boundary_id,
                session_id,
                head.generation,
                boundary_no,
                surface_revision,
                epoch_id,
                normalized_kind,
                turn_id,
                run_id,
                step_index,
                _canonical_json(options),
                timestamp,
            ),
        )
        return ModelContextBoundary(
            boundary_id=boundary_id,
            session_id=session_id,
            generation=head.generation,
            boundary_no=boundary_no,
            surface_revision=surface_revision,
            epoch_id=epoch_id,
            boundary_kind=normalized_kind,
            turn_id=turn_id,
            run_id=run_id,
            step_index=step_index,
            request_options=options,
            created_at_ms=timestamp,
        )

    async def _ensure_head(
        self,
        db: aiosqlite.Connection,
        *,
        session_id: str,
    ) -> _HeadState:
        existing = await self._load_head(db, session_id=session_id)
        if existing is not None:
            return existing
        timestamp = now_wall_ms()
        await db.execute(
            """
            INSERT INTO chat_model_context_heads(
                session_id, generation, revision, accepted_revision,
                last_sequence_no, updated_at_ms
            )
            VALUES (?, 1, 0, 0, 0, ?)
            """,
            (session_id, timestamp),
        )
        return _HeadState(1, 0, 0, 0)

    async def _load_head(
        self,
        db: aiosqlite.Connection,
        *,
        session_id: str,
    ) -> _HeadState | None:
        cursor = await db.execute(
            """
            SELECT generation, revision, accepted_revision, last_sequence_no
            FROM chat_model_context_heads
            WHERE session_id = ? COLLATE NOCASE
            """,
            (session_id,),
        )
        row = await cursor.fetchone()
        if row is None:
            return None
        return _HeadState(
            generation=int(row["generation"]),
            revision=int(row["revision"]),
            accepted_revision=int(row["accepted_revision"]),
            last_sequence_no=int(row["last_sequence_no"]),
        )

    async def _load_run_head(
        self,
        db: aiosqlite.Connection,
        *,
        session_id: str,
        run_id: str,
    ) -> aiosqlite.Row | None:
        cursor = await db.execute(
            """
            SELECT * FROM chat_model_context_run_heads
            WHERE session_id = ? COLLATE NOCASE AND run_id = ?
            """,
            (session_id, run_id),
        )
        return await cursor.fetchone()

    async def _insert_event(
        self,
        db: aiosqlite.Connection,
        *,
        event: ModelContextEvent,
    ) -> None:
        await db.execute(
            """
            INSERT INTO chat_model_context_events(
                event_id, session_id, generation, sequence_no, operation,
                item_kind, item_json, turn_id, run_id, step_index, created_at_ms
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                event.event_id,
                event.session_id,
                event.generation,
                event.sequence_no,
                event.operation,
                event.item.kind.value,
                json.dumps(
                    event.item.to_payload(),
                    ensure_ascii=False,
                    separators=(",", ":"),
                ),
                event.turn_id,
                event.run_id,
                event.step_index,
                event.created_at_ms,
            ),
        )

    async def _load_model_context_with_connection(
        self,
        db: aiosqlite.Connection,
        *,
        session_id: str,
        run_id: str | None = None,
        revision: int | None = None,
    ) -> ModelContextSnapshot:
        head = await self._load_head(db, session_id=session_id)
        if head is None:
            return ModelContextSnapshot(
                session_id=session_id,
                generation=1,
                revision=0,
                accepted_revision=0,
            )
        resolved_run_id: str | None = None
        if revision is None and run_id is not None:
            run_head = await self._load_run_head(
                db,
                session_id=session_id,
                run_id=run_id,
            )
            if run_head is not None and str(run_head["status"]) == "active":
                revision = int(run_head["working_revision"])
                resolved_run_id = run_id
        if revision is None:
            revision = head.accepted_revision
        if revision > head.revision:
            raise KeyError(f"Unknown model-context revision: {revision}")
        return await self._load_revision_with_connection(
            db,
            session_id=session_id,
            head=head,
            revision=revision,
            run_id=resolved_run_id,
        )

    async def _load_revision_with_connection(
        self,
        db: aiosqlite.Connection,
        *,
        session_id: str,
        head: _HeadState,
        revision: int,
        run_id: str | None = None,
    ) -> ModelContextSnapshot:
        if revision == 0:
            return ModelContextSnapshot(
                session_id=session_id,
                generation=head.generation,
                revision=0,
                accepted_revision=head.accepted_revision,
                run_id=run_id,
            )
        cursor = await db.execute(
            """
            SELECT item_count FROM chat_model_context_revisions
            WHERE session_id = ? COLLATE NOCASE AND generation = ? AND revision = ?
            """,
            (session_id, head.generation, revision),
        )
        revision_row = await cursor.fetchone()
        if revision_row is None:
            raise KeyError(f"Unknown model-context revision: {revision}")
        cursor = await db.execute(
            """
            SELECT events.event_id, events.sequence_no, events.operation,
                   events.item_json, events.turn_id, events.run_id,
                   events.step_index, events.created_at_ms
            FROM chat_model_context_surface_nodes AS nodes
            JOIN chat_model_context_events AS events
              ON events.session_id = nodes.session_id
             AND events.generation = nodes.generation
             AND events.sequence_no = nodes.event_sequence_no
            WHERE nodes.session_id = ? COLLATE NOCASE
              AND nodes.generation = ? AND nodes.revision = ?
            ORDER BY nodes.position ASC
            """,
            (session_id, head.generation, revision),
        )
        rows = await cursor.fetchall()
        if not rows and int(revision_row["item_count"]) != 0:
            raise RuntimeError(f"Incomplete model-context revision: {revision}")
        events = tuple(
            ModelContextEvent(
                event_id=str(row["event_id"]),
                session_id=session_id,
                generation=head.generation,
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
            generation=head.generation,
            revision=revision,
            accepted_revision=head.accepted_revision,
            run_id=run_id,
            events=events,
        )


def _accepted_outcome_items(
    items: tuple[ModelContextItem, ...],
    *,
    turn_id: str,
    outcome_text: str,
    outcome_kind: str,
    persona_id: str | None,
) -> tuple[ModelContextItem, ...]:
    latest_runtime_world_state = next(
        (
            item
            for item in reversed(items)
            if item.kind is ModelContextItemKind.RUNTIME_WORLD_STATE
        ),
        None,
    )
    filtered = tuple(
        item
        for item in items
        if item.kind
        not in {
            ModelContextItemKind.WORKING_CONTEXT,
            ModelContextItemKind.LAUNCH_CONTEXT,
            ModelContextItemKind.RUNTIME_CONTROL,
        }
        and (
            item.kind is not ModelContextItemKind.RUNTIME_WORLD_STATE
            or item is latest_runtime_world_state
        )
        and not (
            item.kind is ModelContextItemKind.ASSISTANT_MESSAGE
            and str(item.metadata.get("origin_turn_id") or "") == turn_id
        )
    )
    retained_indexes = protocol_complete_message_indexes(
        [item.message for item in filtered]
    )
    filtered = tuple(filtered[index] for index in retained_indexes)
    normalized_text = str(outcome_text or "").strip()
    if not normalized_text:
        return filtered
    is_assistant = outcome_kind == "assistant"
    metadata: dict[str, Any] = {
        "origin_turn_id": turn_id,
        "accepted_outcome": True,
    }
    if persona_id:
        metadata["persona_id"] = persona_id
    item = ModelContextItem.from_prompt_message(
        {"role": "assistant" if is_assistant else "user", "content": normalized_text},
        source="model" if is_assistant else "runtime_outcome",
        kind=(
            ModelContextItemKind.ASSISTANT_MESSAGE
            if is_assistant
            else ModelContextItemKind.RUNTIME_OBSERVATION
        ),
        scope=ModelContextScope.SESSION,
        metadata=metadata,
    )
    return (*filtered, item)


def _matching_event_sequences(
    current: ModelContextSnapshot,
    desired: tuple[ModelContextItem, ...],
) -> dict[int, ModelContextEvent]:
    current_keys = [_canonical_json(item.to_payload()) for item in current.items]
    desired_keys = [_canonical_json(item.to_payload()) for item in desired]
    matcher = SequenceMatcher(a=current_keys, b=desired_keys, autojunk=False)
    reused: dict[int, ModelContextEvent] = {}
    for block in matcher.get_matching_blocks():
        for offset in range(block.size):
            reused[block.b + offset] = current.events[block.a + offset]
    return reused


def _is_prefix(
    current: tuple[ModelContextItem, ...],
    desired: tuple[ModelContextItem, ...],
) -> bool:
    return _item_payloads(desired[: len(current)]) == _item_payloads(current)


def _item_payloads(items: Iterable[ModelContextItem]) -> list[dict[str, Any]]:
    return [item.to_payload() for item in items]


def _boundary_from_row(row: aiosqlite.Row) -> ModelContextBoundary:
    return ModelContextBoundary(
        boundary_id=str(row["boundary_id"]),
        session_id=str(row["session_id"]),
        generation=int(row["generation"]),
        boundary_no=int(row["boundary_no"]),
        surface_revision=int(row["surface_revision"]),
        epoch_id=str(row["epoch_id"]),
        boundary_kind=str(row["boundary_kind"]),
        turn_id=str(row["turn_id"]) if row["turn_id"] is not None else None,
        run_id=str(row["run_id"]) if row["run_id"] is not None else None,
        step_index=int(row["step_index"]) if row["step_index"] is not None else None,
        request_options=json.loads(str(row["request_options_json"])),
        created_at_ms=int(row["created_at_ms"]),
    )


def _require_identifier(value: str, label: str) -> str:
    normalized = str(value or "").strip()
    if not normalized:
        raise ValueError(f"{label} is required")
    return normalized


def _normalize_optional_identifier(value: str | None) -> str | None:
    normalized = str(value or "").strip()
    return normalized or None


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
