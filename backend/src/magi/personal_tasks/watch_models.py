"""Explicit, bounded attention requests over authorized memory sources."""

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class WatchCitation(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True, allow_inf_nan=False)
    event_id: str = Field(min_length=1, max_length=200)
    quote: str = Field(min_length=1, max_length=500)


class WatchFields(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True, allow_inf_nan=False)
    title: str = Field(min_length=1, max_length=200)
    condition: str = Field(min_length=1, max_length=1500)
    sources: list[str] = Field(min_length=1, max_length=20)
    expires_at: float | None = Field(default=None, gt=0)
    item_id: str | None = Field(default=None, min_length=1, max_length=128)

    @field_validator("sources")
    @classmethod
    def source_ids(cls, values: list[str]) -> list[str]:
        if any(not value.strip() or len(value) > 200 for value in values):
            raise ValueError("Source IDs must be nonempty and at most 200 characters")
        return sorted(set(value.strip() for value in values))


class WatchDecision(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    matched: bool
    summary: str = Field(default="", max_length=1200)
    next_step: str = Field(default="", max_length=500)
    citations: list[WatchCitation] = Field(default_factory=list, max_length=5)

    @model_validator(mode="after")
    def supported_result(self) -> "WatchDecision":
        if self.matched and (not self.summary or not self.citations):
            raise ValueError("A matched condition requires a summary and evidence")
        if not self.matched and (self.summary or self.next_step or self.citations):
            raise ValueError("Unmatched conditions must not retain generated content")
        return self


class AttentionWatch(WatchFields):
    id: str
    version: int
    status: Literal["active", "paused", "stopped", "matched", "expired"]
    created_at: float
    updated_at: float
    last_checked_at: float | None
    check_status: Literal["waiting", "checking", "no_match", "matched", "failed", "invalidated"]
    result: WatchDecision | None


class WatchMutation(BaseModel):
    model_config = ConfigDict(extra="forbid")
    request_id: str = Field(min_length=1, max_length=200)
    action: Literal["create", "update", "pause", "resume", "stop", "delete"]
    watch_id: str | None = Field(default=None, min_length=1, max_length=128)
    expected_version: int = Field(default=0, ge=0)
    fields: WatchFields | None = None

    @model_validator(mode="after")
    def command_shape(self) -> "WatchMutation":
        if self.action == "create":
            if self.watch_id or self.expected_version or not self.fields:
                raise ValueError("Create requires fields, no ID and version zero")
        elif not self.watch_id or not self.expected_version:
            raise ValueError("An existing watch ID and version are required")
        if self.action == "update" and not self.fields:
            raise ValueError("Update requires complete fields")
        if self.action not in {"create", "update"} and self.fields:
            raise ValueError("This action does not accept fields")
        return self


class WatchMutationResult(BaseModel):
    watch: AttentionWatch | None
    replayed: bool = False


class WatchPage(BaseModel):
    items: list[AttentionWatch]
    sources: list[str]
    next_offset: int | None = None
