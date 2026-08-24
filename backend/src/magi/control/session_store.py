"""Per-session state for the agent control plane.

Holds the non-permission state shared across the control-plane tools:

* **Plan mode** — whether the session is currently in read-only
  planning, which tools are allowed while in that mode, and the
  authoring plan text.
* **Run plan** — the durable, versioned plan maintained by ``todo_write``.
* **Ask state** — the last outstanding ``ask_user_question`` request
  for the session, so the UI can render or replay it even if the IPC
  event was missed.

Plan mode and asks are process-local control state. Run plans are persisted in
the runtime database and rehydrated at startup.
"""

from __future__ import annotations

import asyncio
import json
import time
import uuid
import aiosqlite
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable

from magi.core.operation_barrier import AsyncOperationBarrier
from magi.core.sqlite import sqlite_connection_async

from .run_plan import (
    RunPlan,
    RunPlanError,
    RunPlanVersionConflict,
    TodoItem,
    TodoStatus,
    apply_plan_mutation,
)

__all__ = [
    "AskState",
    "ControlSessionClearedError",
    "ControlSessionStore",
    "PlanModeState",
    "RunPlan",
    "RunPlanError",
    "RunPlanVersionConflict",
    "TodoItem",
    "TodoStatus",
]


class ControlSessionClearedError(RuntimeError):
    """Raised when a control-state operation crosses a full data clear."""


@dataclass(slots=True)
class PlanModeState:
    active: bool = False
    #: Tools that are allowed while plan mode is active. Empty or
    #: ``None`` means: fall back to the store-level default allowlist.
    allowed_tools: tuple[str, ...] = ()
    plan_text: str | None = None
    entered_at: float | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "active": self.active,
            "allowed_tools": list(self.allowed_tools),
            "plan_text": self.plan_text,
            "entered_at": self.entered_at,
        }


@dataclass(slots=True)
class AskState:
    request_id: str
    question: str
    options: tuple[str, ...] = ()
    allow_free_text: bool = True
    asked_at: float = field(default_factory=time.time)
    timeout_seconds: float | None = None
    expires_at: float | None = None
    answered_at: float | None = None
    answer: str | None = None
    #: ``"user"`` | ``"cancelled"`` | ``"timeout"`` | ``None`` while pending.
    resolution: str | None = None
    clear_generation: int = field(default=0, repr=False)

    @property
    def status(self) -> str:
        if self.resolution == "user":
            return "answered"
        if self.resolution in {"timeout", "cancelled"}:
            return self.resolution
        return "pending"

    def to_dict(self) -> dict[str, Any]:
        created_at_ms = int(self.asked_at * 1000)
        answered_at_ms = int(self.answered_at * 1000) if self.answered_at else None
        expires_at_ms = int(self.expires_at * 1000) if self.expires_at else None
        return {
            "request_id": self.request_id,
            "question": self.question,
            "options": list(self.options),
            "allow_free_text": self.allow_free_text,
            "status": self.status,
            "asked_at": self.asked_at,
            "created_at_ms": created_at_ms,
            "timeout_seconds": self.timeout_seconds,
            "expires_at": self.expires_at,
            "expires_at_ms": expires_at_ms,
            "answered_at": self.answered_at,
            "answered_at_ms": answered_at_ms,
            "answer": self.answer,
            "resolution": self.resolution,
        }


@dataclass(slots=True)
class _SessionEntry:
    plan: PlanModeState = field(default_factory=PlanModeState)
    run_plans: dict[str, RunPlan] = field(default_factory=dict)
    ask: AskState | None = None


DEFAULT_PLAN_MODE_ALLOWED_TOOLS: tuple[str, ...] = (
    # Read-only / scan-only / think-only.
    "file_read",
    "read_file",
    "glob",
    "grep",
    "web_search",
    "web_fetch",
    "memory_query",
    "capabilities",
    # The plan-mode tools themselves must stay callable.
    "enter_plan_mode",
    "exit_plan_mode",
    "todo_write",
    "ask_user_question",
)


class ControlSessionStore:
    """Process-wide control state plus durable, versioned run plans."""

    def __init__(
        self,
        *,
        db_path: str | Path | None = None,
        default_plan_mode_allowed_tools: Iterable[str] = DEFAULT_PLAN_MODE_ALLOWED_TOOLS,
    ) -> None:
        self._db_path = str(Path(db_path).expanduser()) if db_path is not None else None
        self._entries: dict[str, _SessionEntry] = {}
        self._lock = asyncio.Lock()
        self._clear_barrier = AsyncOperationBarrier()
        self._clear_generation = 0
        self._clear_request_count = 0
        self._default_plan_mode_allowed_tools: tuple[str, ...] = tuple(
            default_plan_mode_allowed_tools
        )
        self._initialized = False

    async def initialize(self) -> None:
        """Load the latest durable plan for every session."""
        if self._initialized:
            return
        if self._db_path is not None:
            async with sqlite_connection_async(self._db_path, profile="hot_write") as db:
                db.row_factory = aiosqlite.Row
                cursor = await db.execute(
                    """
                    SELECT plan_json
                    FROM run_plans
                    ORDER BY session_id ASC, updated_at_ms DESC
                    """
                )
                for row in await cursor.fetchall():
                    plan = RunPlan.from_dict(json.loads(row["plan_json"]))
                    self._entries.setdefault(plan.session_id, _SessionEntry()).run_plans[
                        plan.run_id
                    ] = plan
        self._initialized = True

    async def shutdown(self) -> None:
        self._initialized = False

    @asynccontextmanager
    async def user_content_operation(
        self,
        *,
        expected_generation: int | None = None,
    ) -> AsyncIterator[int]:
        """Guard one logical control-state write against a full data clear.

        Callers that mutate state and then publish an event can wrap both steps
        in this boundary. This makes the mutation and its projection one clear
        operation instead of leaving a publish window after the store write.
        """
        generation = (
            self._clear_generation if expected_generation is None else int(expected_generation)
        )
        if self._clear_request_count > 0:
            raise ControlSessionClearedError("control session content is being cleared")
        async with self._clear_barrier.operation():
            if self._clear_request_count > 0 or generation != self._clear_generation:
                raise ControlSessionClearedError(
                    "control session operation crossed a full data clear"
                )
            yield generation

    @asynccontextmanager
    async def user_content_clear_boundary(self) -> AsyncIterator[None]:
        """Clear session content and reject writes until the global clear ends."""
        self._clear_request_count += 1
        self._clear_generation += 1
        try:
            async with self._clear_barrier.exclusive():
                async with self._lock:
                    await self._delete_all_run_plans()
                    self._entries.clear()
                yield
        finally:
            self._clear_request_count -= 1

    def user_content_generation(self) -> int:
        """Return the generation a new logical control operation must retain."""
        return self._clear_generation

    # ------------------------------------------------------------------
    # Plan mode
    # ------------------------------------------------------------------

    async def enter_plan_mode(
        self,
        session_id: str,
        *,
        allowed_tools: Iterable[str] | None = None,
    ) -> PlanModeState:
        async with self.user_content_operation():
            async with self._lock:
                entry = self._entries.setdefault(session_id, _SessionEntry())
                entry.plan = PlanModeState(
                    active=True,
                    allowed_tools=tuple(allowed_tools) if allowed_tools else (),
                    entered_at=time.time(),
                    plan_text=None,
                )
                return entry.plan

    async def exit_plan_mode(
        self,
        session_id: str,
        *,
        plan_text: str | None = None,
    ) -> PlanModeState:
        async with self.user_content_operation():
            async with self._lock:
                entry = self._entries.setdefault(session_id, _SessionEntry())
                entry.plan = PlanModeState(
                    active=False,
                    allowed_tools=(),
                    plan_text=plan_text,
                    entered_at=entry.plan.entered_at,
                )
                return entry.plan

    def plan_state(self, session_id: str) -> PlanModeState:
        if self._clear_request_count > 0:
            return PlanModeState()
        entry = self._entries.get(session_id)
        return entry.plan if entry else PlanModeState()

    def plan_allows(self, session_id: str, tool_name: str) -> bool:
        """Return True when ``tool_name`` is callable under the current plan state.

        If plan mode is off, every tool is allowed. If plan mode is on,
        only tools in the session allowlist (or the store default if
        no session allowlist was set) are allowed.
        """
        if self._clear_request_count > 0:
            return False
        state = self.plan_state(session_id)
        if not state.active:
            return True
        allowlist: tuple[str, ...] = state.allowed_tools or self._default_plan_mode_allowed_tools
        return tool_name in allowlist

    # ------------------------------------------------------------------
    # Run plan
    # ------------------------------------------------------------------

    async def mutate_run_plan(
        self,
        session_id: str,
        *,
        run_id: str,
        plan_id: str | None,
        expected_version: int,
        required: bool | None = None,
        status: str | None = None,
        item_mutations: Iterable[dict[str, Any]] = (),
    ) -> RunPlan:
        """Apply one optimistic, versioned plan mutation."""
        normalized_session_id = str(session_id or "").strip()
        normalized_run_id = str(run_id or "").strip()
        if not normalized_session_id or not normalized_run_id:
            raise RunPlanError("session_id and run_id are required")
        async with self.user_content_operation():
            async with self._lock:
                entry = self._entries.setdefault(normalized_session_id, _SessionEntry())
                current = entry.run_plans.get(normalized_run_id)
                plan = apply_plan_mutation(
                    current,
                    session_id=normalized_session_id,
                    run_id=normalized_run_id,
                    plan_id=plan_id,
                    expected_version=expected_version,
                    required=required,
                    status=status,
                    item_mutations=item_mutations,
                )
                await self._persist_run_plan(plan)
                entry.run_plans[normalized_run_id] = plan
                return plan

    def current_run_plan(
        self,
        session_id: str,
        *,
        run_id: str | None = None,
    ) -> RunPlan | None:
        if self._clear_request_count > 0:
            return None
        entry = self._entries.get(session_id)
        if entry is None:
            return None
        if run_id is not None:
            return entry.run_plans.get(run_id)
        return max(
            entry.run_plans.values(),
            key=lambda plan: plan.updated_at_ms,
            default=None,
        )

    async def _persist_run_plan(self, plan: RunPlan) -> None:
        if self._db_path is None:
            return
        payload = json.dumps(plan.to_dict(), ensure_ascii=False, separators=(",", ":"))
        async with sqlite_connection_async(self._db_path, profile="hot_write") as db:
            await db.execute(
                """
                INSERT INTO run_plans (
                    plan_id, run_id, session_id, version, required, status,
                    plan_json, created_at_ms, updated_at_ms
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(plan_id) DO UPDATE SET
                    version = excluded.version,
                    required = excluded.required,
                    status = excluded.status,
                    plan_json = excluded.plan_json,
                    updated_at_ms = excluded.updated_at_ms
                """,
                (
                    plan.plan_id,
                    plan.run_id,
                    plan.session_id,
                    plan.version,
                    1 if plan.required else 0,
                    plan.status.value,
                    payload,
                    plan.created_at_ms,
                    plan.updated_at_ms,
                ),
            )
            await db.commit()

    async def _delete_all_run_plans(self) -> None:
        if self._db_path is None:
            return
        async with sqlite_connection_async(self._db_path, profile="hot_write") as db:
            await db.execute("DELETE FROM run_plans")
            await db.commit()

    async def clear_session(self, session_id: str) -> None:
        """Remove all control state and durable plans for one session."""
        normalized_session_id = str(session_id or "").strip()
        if not normalized_session_id:
            return
        async with self.user_content_operation():
            async with self._lock:
                if self._db_path is not None:
                    async with sqlite_connection_async(
                        self._db_path,
                        profile="hot_write",
                    ) as db:
                        await db.execute(
                            "DELETE FROM run_plans WHERE session_id = ?",
                            (normalized_session_id,),
                        )
                        await db.commit()
                self._entries.pop(normalized_session_id, None)

    # ------------------------------------------------------------------
    # Ask state
    # ------------------------------------------------------------------

    async def open_ask(
        self,
        session_id: str,
        *,
        question: str,
        options: Iterable[str] = (),
        allow_free_text: bool = True,
        timeout_seconds: float | None = None,
        request_id: str | None = None,
    ) -> AskState:
        async with self.user_content_operation() as generation:
            now = time.time()
            timeout_value = float(timeout_seconds) if timeout_seconds is not None else None
            expires_at = now + timeout_value if timeout_value and timeout_value > 0 else None
            async with self._lock:
                entry = self._entries.setdefault(session_id, _SessionEntry())
                entry.ask = AskState(
                    request_id=request_id or uuid.uuid4().hex,
                    question=question,
                    options=tuple(options),
                    allow_free_text=bool(allow_free_text),
                    asked_at=now,
                    timeout_seconds=timeout_value,
                    expires_at=expires_at,
                    clear_generation=generation,
                )
                return entry.ask

    async def close_ask(
        self,
        session_id: str,
        *,
        request_id: str,
        expected_generation: int,
        answer: str | None,
        resolution: str,
    ) -> AskState | None:
        async with self.user_content_operation(expected_generation=expected_generation):
            async with self._lock:
                entry = self._entries.get(session_id)
                if (
                    entry is None
                    or entry.ask is None
                    or entry.ask.request_id != request_id
                    or entry.ask.clear_generation != expected_generation
                ):
                    return None
                entry.ask.answer = answer
                entry.ask.resolution = resolution
                entry.ask.answered_at = time.time()
                return entry.ask

    def ask_state(self, session_id: str) -> AskState | None:
        if self._clear_request_count > 0:
            return None
        entry = self._entries.get(session_id)
        return entry.ask if entry else None

    # ------------------------------------------------------------------
    # Test helpers
    # ------------------------------------------------------------------

    def reset(self, session_id: str | None = None) -> None:
        if session_id is None:
            self._entries.clear()
        else:
            self._entries.pop(session_id, None)
