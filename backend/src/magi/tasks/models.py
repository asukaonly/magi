"""Task data models."""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Optional


class TaskStatus(str, Enum):
    OPEN = "open"
    IN_PROGRESS = "in_progress"
    DONE = "done"
    CANCELLED = "cancelled"


class TaskPriority(str, Enum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    URGENT = "urgent"


@dataclass(slots=True)
class UserTask:
    """A user-visible task that may originate from user input or agent work."""

    task_id: str
    title: str
    description: str = ""
    status: TaskStatus = TaskStatus.OPEN
    priority: TaskPriority = TaskPriority.MEDIUM
    tags: list[str] = field(default_factory=list)
    due_date: Optional[float] = None
    created_by: str = "user"
    user_id: str = ""
    session_id: Optional[str] = None
    linked_orchestration_id: Optional[str] = None
    linked_turn_id: Optional[str] = None
    created_at: float = 0.0
    updated_at: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        return {
            "task_id": self.task_id,
            "title": self.title,
            "description": self.description,
            "status": self.status.value,
            "priority": self.priority.value,
            "tags": list(self.tags),
            "due_date": self.due_date,
            "created_by": self.created_by,
            "user_id": self.user_id,
            "session_id": self.session_id,
            "linked_orchestration_id": self.linked_orchestration_id,
            "linked_turn_id": self.linked_turn_id,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }
