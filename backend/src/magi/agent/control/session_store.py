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
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Iterable

__all__ = [
    "AskState",
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
    answered_at: float | None = None
    answer: str | None = None
    #: ``"user"`` | ``"cancelled"`` | ``"timeout"`` | ``None`` while pending.
    resolution: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "request_id": self.request_id,
            "question": self.question,
            "options": list(self.options),
            "allow_free_text": self.allow_free_text,
            "asked_at": self.asked_at,
            "answered_at": self.answered_at,
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
        self._default_plan_mode_allowed_tools: tuple[str, ...] = tuple(
            default_plan_mode_allowed_tools
        )

    # ------------------------------------------------------------------
    # Plan mode
    # ------------------------------------------------------------------

    async def enter_plan_mode(
        self,
        session_id: str,
        *,
        allowed_tools: Iterable[str] | None = None,
    ) -> PlanModeState:
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
        entry = self._entries.get(session_id)
        return entry.plan if entry else PlanModeState()

    def plan_allows(self, session_id: str, tool_name: str) -> bool:
        """Return True when ``tool_name`` is callable under the current plan state.

        If plan mode is off, every tool is allowed. If plan mode is on,
        only tools in the session allowlist (or the store default if
        no session allowlist was set) are allowed.
        """
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

        async with self._lock:
            entry = self._entries.setdefault(session_id, _SessionEntry())
            entry.todos = todos
            return list(entry.todos)

    def list_todos(self, session_id: str) -> list[TodoItem]:
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
        request_id: str | None = None,
    ) -> AskState:
        async with self._lock:
            entry = self._entries.setdefault(session_id, _SessionEntry())
            entry.ask = AskState(
                request_id=request_id or uuid.uuid4().hex,
                question=question,
                options=tuple(options),
                allow_free_text=bool(allow_free_text),
            )
            return entry.ask

    async def close_ask(
        self,
        session_id: str,
        *,
        answer: str | None,
        resolution: str,
    ) -> AskState | None:
        async with self._lock:
            entry = self._entries.get(session_id)
            if entry is None or entry.ask is None:
                return None
            entry.ask.answer = answer
            entry.ask.resolution = resolution
            entry.ask.answered_at = time.time()
            return entry.ask

    def ask_state(self, session_id: str) -> AskState | None:
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
