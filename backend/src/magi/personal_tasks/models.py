"""Typed personal-task commands and product responses."""

from __future__ import annotations

from datetime import date, datetime
from typing import Literal
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import BaseModel, ConfigDict, Field, ValidationInfo, field_validator, model_validator

ItemStatus = Literal["inbox", "active", "waiting", "someday", "completed", "cancelled"]
ItemKind = Literal["action", "project"]


class TaskReference(BaseModel):
    model_config = ConfigDict(extra="forbid")
    kind: Literal["chat", "memory", "resource", "run", "source"]
    id: str = Field(min_length=1, max_length=512)
    label: str = Field(default="", max_length=300)
    session_id: str | None = Field(default=None, max_length=128)


class ItemFields(BaseModel):
    model_config = ConfigDict(extra="forbid")
    title: str = Field(min_length=1, max_length=300)
    body_md: str = Field(default="", max_length=100_000)
    kind: ItemKind = "action"
    parent_id: str | None = Field(default=None, max_length=128)
    status: ItemStatus = "active"
    defer_until: str | None = None
    due: str | None = None
    remind_at: str | None = None
    timezone: str = "UTC"
    references: list[TaskReference] = Field(default_factory=list, max_length=50)

    @field_validator("title")
    @classmethod
    def validate_title(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("Title must not be blank")
        return value.strip()

    @field_validator("defer_until", "due", "remind_at")
    @classmethod
    def validate_time(cls, value: str | None, info: ValidationInfo) -> str | None:
        if value is None:
            return None
        if len(value) == 10 and info.field_name != "remind_at":
            date.fromisoformat(value)
            return value
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        if parsed.tzinfo is None:
            raise ValueError("Timestamps must include a timezone offset")
        return parsed.isoformat()

    @field_validator("timezone")
    @classmethod
    def validate_timezone(cls, value: str) -> str:
        try:
            ZoneInfo(value)
        except (ZoneInfoNotFoundError, ValueError) as exc:
            raise ValueError("Unknown IANA timezone") from exc
        return value


class PersonalItem(ItemFields):
    id: str
    user_id: str
    origin: Literal["user", "source"]
    version: int
    created_at: float
    updated_at: float
    closed_at: float | None = None
    reminder_revision: int = 0
    reminder_synced_revision: int = 0
    reminder_delivered_revision: int = 0


class ItemPatch(BaseModel):
    model_config = ConfigDict(extra="forbid")
    title: str | None = Field(default=None, min_length=1, max_length=300)
    body_md: str | None = Field(default=None, max_length=100_000)
    kind: ItemKind | None = None
    parent_id: str | None = Field(default=None, max_length=128)
    status: ItemStatus | None = None
    defer_until: str | None = None
    due: str | None = None
    remind_at: str | None = None
    timezone: str | None = None
    references: list[TaskReference] | None = Field(default=None, max_length=50)


class TaskMutation(BaseModel):
    model_config = ConfigDict(extra="forbid")
    request_id: str = Field(min_length=1, max_length=200)
    action: Literal["create", "update", "progress", "delete"]
    item_id: str | None = Field(default=None, max_length=128)
    expected_version: int = Field(default=0, ge=0)
    fields: ItemPatch = Field(default_factory=ItemPatch)
    note: str = Field(default="", max_length=10_000)
    cascade: bool = False

    @model_validator(mode="after")
    def validate_command(self) -> TaskMutation:
        if self.action == "create":
            if self.item_id is not None or self.expected_version != 0:
                raise ValueError("Create requires no item ID and version zero")
            if not self.fields.title:
                raise ValueError("Create requires a title")
        elif not self.item_id or self.expected_version < 1:
            raise ValueError("An existing item ID and positive version are required")
        if self.action == "progress" and not self.note.strip():
            raise ValueError("Progress requires a note")
        if self.action == "progress" and self.fields.status is None:
            raise ValueError(
                "Progress requires fields.status: choose the current resulting state, including waiting or completed when applicable"
            )
        if self.action == "delete" and self.fields.model_fields_set:
            raise ValueError("Delete does not accept content changes")
        return self


class TaskChange(BaseModel):
    id: int
    item_id: str
    action: str
    actor: str
    version: int
    note: str
    changes: dict[str, object]
    references: list[TaskReference]
    created_at: float


class ItemPage(BaseModel):
    items: list[PersonalItem]
    total: int
    next_offset: int | None
    counts: dict[str, int]


class ItemDetail(BaseModel):
    item: PersonalItem
    children: list[PersonalItem]
    changes: list[TaskChange]
    next_history_offset: int | None = None


class MutationResult(BaseModel):
    item: PersonalItem | None = None
    deleted_ids: list[str] = Field(default_factory=list)
    replayed: bool = False
    reminders_pending: bool = False


class TaskConflictError(ValueError):
    """A write was based on an obsolete record or reused request identity."""


class TaskNotFoundError(LookupError):
    """A requested record is absent from the caller's ownership scope."""
