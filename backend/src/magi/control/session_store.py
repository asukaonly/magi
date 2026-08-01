"""Per-session state for the agent control plane.

Holds the non-permission state shared across the control-plane tools:

* **Plan mode** — whether the session is currently in read-only
  planning, which tools are allowed while in that mode, and the
  authoring plan text.
* **Todo list** — the working task list maintained by ``todo_write``.
  The in-progress cap (≤ 1) is enforced here so any caller (UI,
  tool, test) gets consistent validation.
* **Ask state** — the last outstanding ``ask_user_question`` request
  for the session, so the UI can render or replay it even if the IPC
  event was missed.

The store is purely in-memory. Durability is an orthogonal concern:
sessions that survive restarts will rehydrate through their own
persistence layer and replay ``set_plan``/``set_todos`` on load.
"""

from __future__ import annotations

import asyncio
import time
import uuid
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Iterable

from magi.core.operation_barrier import AsyncOperationBarrier

__all__ = [
    "AskState",
    "ControlSessionClearedError",
    "ControlSessionStore",
    "PlanModeState",
    "TodoItem",
    "TodoStatus",
    "TodoListError",
]


class TodoStatus(str, Enum):
    NOT_STARTED = "not_started"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"


@dataclass(slots=True)
class TodoItem:
    id: str
    content: str
    status: TodoStatus = TodoStatus.NOT_STARTED
    created_at_ms: int = field(default_factory=lambda: int(time.time() * 1000))
    updated_at_ms: int = field(default_factory=lambda: int(time.time() * 1000))

    @property
    def title(self) -> str:
        return self.content

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "content": self.content,
            "status": self.status.value,
            "created_at_ms": self.created_at_ms,
            "updated_at_ms": self.updated_at_ms,
        }

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "TodoItem":
        status_raw = payload.get("status") or TodoStatus.NOT_STARTED.value
        try:
            status = TodoStatus(status_raw)
        except ValueError:
            status = TodoStatus.NOT_STARTED
        item_id = payload.get("id") or uuid.uuid4().hex
        content = str(payload.get("content") or payload.get("title") or "").strip()
        if not content:
            raise TodoListError("each todo item requires non-empty content")
        created_at_ms = _coerce_timestamp_ms(payload.get("created_at_ms"))
        updated_at_ms = _coerce_timestamp_ms(payload.get("updated_at_ms"))
        if created_at_ms is None:
            created_at_ms = int(time.time() * 1000)
        if updated_at_ms is None:
            updated_at_ms = created_at_ms
        if updated_at_ms < created_at_ms:
            updated_at_ms = created_at_ms
        return cls(
            id=str(item_id),
            content=content,
            status=status,
            created_at_ms=created_at_ms,
            updated_at_ms=updated_at_ms,
        )


def _coerce_timestamp_ms(value: Any) -> int | None:
    try:
        if value is None or value == "":
            return None
        return int(value)
    except (TypeError, ValueError):
        return None


class TodoListError(ValueError):
    """Raised when a todo list violates the server-side invariants."""


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
    todos: list[TodoItem] = field(default_factory=list)
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
    """Thread-safe, async-locked, in-memory state keyed by ``session_id``.

    A single instance is process-global; concurrent workers coordinate
    on the internal ``asyncio.Lock``.
    """

    def __init__(
        self,
        *,
        default_plan_mode_allowed_tools: Iterable[str] = DEFAULT_PLAN_MODE_ALLOWED_TOOLS,
    ) -> None:
        self._entries: dict[str, _SessionEntry] = {}
        self._lock = asyncio.Lock()
        self._clear_barrier = AsyncOperationBarrier()
        self._clear_generation = 0
        self._clear_request_count = 0
        self._default_plan_mode_allowed_tools: tuple[str, ...] = tuple(
            default_plan_mode_allowed_tools
        )

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
            self._clear_generation
            if expected_generation is None
            else int(expected_generation)
        )
        if self._clear_request_count > 0:
            raise ControlSessionClearedError(
                "control session content is being cleared"
            )
        async with self._clear_barrier.operation():
            if (
                self._clear_request_count > 0
                or generation != self._clear_generation
            ):
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
        allowlist: tuple[str, ...] = (
            state.allowed_tools or self._default_plan_mode_allowed_tools
        )
        return tool_name in allowlist

    # ------------------------------------------------------------------
    # Todos
    # ------------------------------------------------------------------

    async def replace_todos(
        self, session_id: str, items: Iterable[dict[str, Any] | TodoItem]
    ) -> list[TodoItem]:
        """Replace the todo list wholesale; enforces ≤ 1 in-progress."""
        todos: list[TodoItem] = []
        seen_ids: set[str] = set()
        in_progress_count = 0
        for raw in items:
            item = raw if isinstance(raw, TodoItem) else TodoItem.from_dict(raw)
            if item.id in seen_ids:
                raise TodoListError(f"duplicate todo id: {item.id}")
            seen_ids.add(item.id)
            if item.status is TodoStatus.IN_PROGRESS:
                in_progress_count += 1
                if in_progress_count > 1:
                    raise TodoListError(
                        "only one todo may be in_progress at a time"
                    )
            todos.append(item)

        async with self.user_content_operation():
            async with self._lock:
                entry = self._entries.setdefault(session_id, _SessionEntry())
                entry.todos = todos
                return list(entry.todos)

    def list_todos(self, session_id: str) -> list[TodoItem]:
        if self._clear_request_count > 0:
            return []
        entry = self._entries.get(session_id)
        return list(entry.todos) if entry else []

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
            timeout_value = (
                float(timeout_seconds) if timeout_seconds is not None else None
            )
            expires_at = (
                now + timeout_value if timeout_value and timeout_value > 0 else None
            )
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
        async with self.user_content_operation(
            expected_generation=expected_generation
        ):
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
