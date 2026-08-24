"""Canonical, runtime-owned plan state for one agent run."""

from __future__ import annotations

import time
import uuid
from dataclasses import dataclass, field, replace
from enum import Enum
from typing import Any, Iterable


class PlanStatus(str, Enum):
    ACTIVE = "active"
    COMPLETED = "completed"
    BLOCKED = "blocked"
    CANCELLED = "cancelled"

    @property
    def terminal(self) -> bool:
        return self is not PlanStatus.ACTIVE


class TodoStatus(str, Enum):
    PENDING = "pending"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    BLOCKED = "blocked"
    SKIPPED = "skipped"
    CANCELLED = "cancelled"

    @property
    def terminal(self) -> bool:
        return self in {
            TodoStatus.COMPLETED,
            TodoStatus.BLOCKED,
            TodoStatus.SKIPPED,
            TodoStatus.CANCELLED,
        }


class RunPlanError(ValueError):
    """Base error for invalid plan mutations."""


class RunPlanVersionConflict(RunPlanError):
    """Raised when a mutation targets a stale plan version."""


@dataclass(frozen=True, slots=True)
class TodoItem:
    id: str
    content: str
    status: TodoStatus = TodoStatus.PENDING
    required: bool = True
    evidence_refs: tuple[str, ...] = ()
    blocked_reason: str | None = None
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
            "required": self.required,
            "evidence_refs": list(self.evidence_refs),
            "blocked_reason": self.blocked_reason,
            "created_at_ms": self.created_at_ms,
            "updated_at_ms": self.updated_at_ms,
        }

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "TodoItem":
        content = str(payload.get("content") or payload.get("title") or "").strip()
        if not content:
            raise RunPlanError("each todo item requires non-empty content")
        status = _enum_value(
            TodoStatus,
            payload.get("status"),
            default=TodoStatus.PENDING,
        )
        now_ms = int(time.time() * 1000)
        created_at_ms = _timestamp_ms(payload.get("created_at_ms"), default=now_ms)
        updated_at_ms = max(
            created_at_ms,
            _timestamp_ms(payload.get("updated_at_ms"), default=created_at_ms),
        )
        evidence_refs = _normalize_refs(payload.get("evidence_refs"))
        blocked_reason = str(payload.get("blocked_reason") or "").strip() or None
        _validate_todo_terminal_fields(status, evidence_refs, blocked_reason)
        return cls(
            id=str(payload.get("id") or uuid.uuid4().hex),
            content=content,
            status=status,
            required=bool(payload.get("required", True)),
            evidence_refs=evidence_refs,
            blocked_reason=blocked_reason,
            created_at_ms=created_at_ms,
            updated_at_ms=updated_at_ms,
        )

    def apply(self, mutation: dict[str, Any], *, now_ms: int) -> "TodoItem":
        content = (
            str(mutation["content"]).strip()
            if "content" in mutation
            else self.content
        )
        if not content:
            raise RunPlanError("todo content must not be empty")
        status = (
            _enum_value(TodoStatus, mutation.get("status"), default=self.status)
            if "status" in mutation
            else self.status
        )
        _validate_todo_transition(self.status, status)
        evidence_refs = (
            _normalize_refs(mutation.get("evidence_refs"))
            if "evidence_refs" in mutation
            else self.evidence_refs
        )
        blocked_reason = (
            str(mutation.get("blocked_reason") or "").strip() or None
            if "blocked_reason" in mutation
            else self.blocked_reason
        )
        _validate_todo_terminal_fields(status, evidence_refs, blocked_reason)
        return replace(
            self,
            content=content,
            status=status,
            required=(
                bool(mutation["required"])
                if "required" in mutation
                else self.required
            ),
            evidence_refs=evidence_refs,
            blocked_reason=blocked_reason,
            updated_at_ms=now_ms,
        )


@dataclass(frozen=True, slots=True)
class RunPlan:
    plan_id: str
    run_id: str
    session_id: str
    version: int
    required: bool
    status: PlanStatus
    items: tuple[TodoItem, ...]
    created_at_ms: int
    updated_at_ms: int

    def to_dict(self) -> dict[str, Any]:
        return {
            "plan_id": self.plan_id,
            "run_id": self.run_id,
            "session_id": self.session_id,
            "version": self.version,
            "required": self.required,
            "status": self.status.value,
            "items": [item.to_dict() for item in self.items],
            "created_at_ms": self.created_at_ms,
            "updated_at_ms": self.updated_at_ms,
        }

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "RunPlan":
        return cls(
            plan_id=str(payload["plan_id"]),
            run_id=str(payload["run_id"]),
            session_id=str(payload["session_id"]),
            version=int(payload["version"]),
            required=bool(payload.get("required", False)),
            status=_enum_value(
                PlanStatus,
                payload.get("status"),
                default=PlanStatus.ACTIVE,
            ),
            items=tuple(
                TodoItem.from_dict(item)
                for item in payload.get("items", [])
                if isinstance(item, dict)
            ),
            created_at_ms=int(payload["created_at_ms"]),
            updated_at_ms=int(payload["updated_at_ms"]),
        )


def apply_plan_mutation(
    current: RunPlan | None,
    *,
    session_id: str,
    run_id: str,
    plan_id: str | None,
    expected_version: int,
    required: bool | None,
    status: str | None,
    item_mutations: Iterable[dict[str, Any]],
) -> RunPlan:
    """Apply a version-checked patch and derive terminal plan state."""
    if expected_version < 0:
        raise RunPlanError("expected_version must not be negative")
    now_ms = int(time.time() * 1000)
    if current is None:
        if expected_version != 0:
            raise RunPlanVersionConflict(
                f"cannot create plan at version {expected_version}; expected 0"
            )
        if str(plan_id or "").strip():
            raise RunPlanError("plan_id must be omitted when creating a run plan")
        resolved_plan_id = uuid.uuid4().hex
        items: dict[str, TodoItem] = {}
        created_at_ms = now_ms
        current_status = PlanStatus.ACTIVE
    else:
        if plan_id != current.plan_id:
            raise RunPlanVersionConflict("plan_id does not identify the current run plan")
        if expected_version != current.version:
            raise RunPlanVersionConflict(
                f"stale plan version {expected_version}; current version is {current.version}"
            )
        if current.status in {PlanStatus.COMPLETED, PlanStatus.CANCELLED}:
            raise RunPlanError(f"cannot mutate terminal plan in state {current.status.value}")
        resolved_plan_id = current.plan_id
        items = {item.id: item for item in current.items}
        created_at_ms = current.created_at_ms
        current_status = current.status

    for mutation in item_mutations:
        if not isinstance(mutation, dict):
            raise RunPlanError("each todo mutation must be an object")
        item_id = str(mutation.get("id") or "").strip()
        if item_id:
            item = items.get(item_id)
            if item is None:
                if not str(mutation.get("content") or mutation.get("title") or "").strip():
                    raise RunPlanError(f"unknown todo id: {item_id}")
                payload = {**mutation, "id": item_id, "updated_at_ms": now_ms}
                items[item_id] = TodoItem.from_dict(payload)
            else:
                items[item_id] = item.apply(mutation, now_ms=now_ms)
            continue
        payload = {**mutation, "id": uuid.uuid4().hex, "updated_at_ms": now_ms}
        new_item = TodoItem.from_dict(payload)
        items[new_item.id] = new_item

    resolved_items = tuple(items.values())
    if sum(item.status is TodoStatus.IN_PROGRESS for item in resolved_items) > 1:
        raise RunPlanError("only one todo may be in_progress at a time")

    requested_status = (
        _enum_value(PlanStatus, status, default=current_status)
        if status is not None
        else current_status
    )
    _validate_plan_transition(current_status, requested_status)
    if requested_status is PlanStatus.CANCELLED:
        resolved_items = tuple(
            replace(
                item,
                status=TodoStatus.CANCELLED,
                updated_at_ms=now_ms,
            )
            if not item.status.terminal
            else item
            for item in resolved_items
        )
    resolved_status = _derive_plan_status(requested_status, resolved_items)
    resolved_required = required if required is not None else bool(current.required if current else False)
    if resolved_status is PlanStatus.COMPLETED:
        incomplete = [
            item.id
            for item in resolved_items
            if item.required and item.status is not TodoStatus.COMPLETED
        ]
        if incomplete:
            raise RunPlanError("completed plan contains incomplete required todos")

    return RunPlan(
        plan_id=resolved_plan_id,
        run_id=run_id,
        session_id=session_id,
        version=(current.version + 1 if current else 1),
        required=resolved_required,
        status=resolved_status,
        items=resolved_items,
        created_at_ms=created_at_ms,
        updated_at_ms=now_ms,
    )


def _derive_plan_status(
    requested: PlanStatus,
    items: tuple[TodoItem, ...],
) -> PlanStatus:
    if requested is not PlanStatus.ACTIVE:
        return requested
    required_items = [item for item in items if item.required]
    if any(item.status is TodoStatus.BLOCKED for item in required_items):
        return PlanStatus.BLOCKED
    if required_items and all(
        item.status is TodoStatus.COMPLETED for item in required_items
    ):
        return PlanStatus.COMPLETED
    return PlanStatus.ACTIVE


def _validate_plan_transition(previous: PlanStatus, target: PlanStatus) -> None:
    allowed = {
        PlanStatus.ACTIVE: {
            PlanStatus.ACTIVE,
            PlanStatus.COMPLETED,
            PlanStatus.BLOCKED,
            PlanStatus.CANCELLED,
        },
        PlanStatus.BLOCKED: {
            PlanStatus.ACTIVE,
            PlanStatus.BLOCKED,
            PlanStatus.CANCELLED,
        },
    }
    if target not in allowed.get(previous, {previous}):
        raise RunPlanError(
            f"invalid plan transition: {previous.value} -> {target.value}"
        )


def _validate_todo_transition(previous: TodoStatus, target: TodoStatus) -> None:
    allowed = {
        TodoStatus.PENDING: {
            TodoStatus.PENDING,
            TodoStatus.IN_PROGRESS,
            TodoStatus.BLOCKED,
            TodoStatus.SKIPPED,
            TodoStatus.CANCELLED,
        },
        TodoStatus.IN_PROGRESS: {
            TodoStatus.IN_PROGRESS,
            TodoStatus.PENDING,
            TodoStatus.COMPLETED,
            TodoStatus.BLOCKED,
            TodoStatus.CANCELLED,
        },
        TodoStatus.BLOCKED: {
            TodoStatus.BLOCKED,
            TodoStatus.IN_PROGRESS,
            TodoStatus.SKIPPED,
            TodoStatus.CANCELLED,
        },
    }
    if target not in allowed.get(previous, {previous}):
        raise RunPlanError(
            f"invalid todo transition: {previous.value} -> {target.value}"
        )


def _validate_todo_terminal_fields(
    status: TodoStatus,
    evidence_refs: tuple[str, ...],
    blocked_reason: str | None,
) -> None:
    if status is TodoStatus.COMPLETED and not evidence_refs:
        raise RunPlanError("completed todo requires at least one evidence_ref")
    if status is TodoStatus.BLOCKED and blocked_reason is None:
        raise RunPlanError("blocked todo requires blocked_reason")


def _normalize_refs(value: Any) -> tuple[str, ...]:
    if value is None:
        return ()
    if not isinstance(value, (list, tuple)):
        raise RunPlanError("evidence_refs must be a list")
    return tuple(
        dict.fromkeys(
            str(item).strip()
            for item in value
            if str(item).strip()
        )
    )


def _timestamp_ms(value: Any, *, default: int) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _enum_value(enum_type, value: Any, *, default):
    if value is None or value == "":
        return default
    try:
        return enum_type(str(value))
    except ValueError as exc:
        choices = ", ".join(item.value for item in enum_type)
        raise RunPlanError(f"invalid status {value!r}; expected one of: {choices}") from exc


__all__ = [
    "PlanStatus",
    "RunPlan",
    "RunPlanError",
    "RunPlanVersionConflict",
    "TodoItem",
    "TodoStatus",
    "apply_plan_mutation",
]
