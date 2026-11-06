"""On-demand failure diagnostics for the memory overview."""

import asyncio
from typing import Any, Literal

from fastapi import HTTPException, Query
from pydantic import BaseModel, ConfigDict, Field, field_validator

from magi.memory.l2.projection.diagnostics import ProjectionFailureReason
from magi.utils.log_redaction import redact_log_text

from .. import dependencies
from ..router import memory_router


class ProjectionFailureDiagnostic(BaseModel):
    source: str
    reason: ProjectionFailureReason
    retry_allowed: bool
    last_failed_at: float = Field(ge=0)
    error: str | None

    @field_validator("error")
    @classmethod
    def sanitize_error(cls, value: str | None) -> str | None:
        if not value:
            return None
        return redact_log_text(value)[:1200]


class ProjectionFailureGroup(ProjectionFailureDiagnostic):
    count: int = Field(gt=0)


class ProjectionFailureSummary(BaseModel):
    total: int = Field(ge=0)
    groups: list[ProjectionFailureGroup] = Field(max_length=12)
    other_count: int = Field(ge=0)
    retryable_count: int = Field(ge=0)


class ProjectionFailureRecord(ProjectionFailureDiagnostic):
    event_id: str
    status: Literal["failed", "ignored"]
    attempt_count: int = Field(ge=0)
    updated_at: float = Field(ge=0)
    content: str | None
    content_truncated: bool
    recorded_at: float | None


class ProjectionFailureRecords(BaseModel):
    items: list[ProjectionFailureRecord]
    total: int = Field(ge=0)
    limit: int = Field(ge=1, le=100)
    offset: int = Field(ge=0)


class FailureSelection(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    event_id: str = Field(min_length=1, max_length=512)
    expected_updated_at: float = Field(ge=0, allow_inf_nan=False)

    @field_validator("event_id")
    @classmethod
    def validate_event_id(cls, value: str) -> str:
        if value != value.strip():
            raise ValueError("Event IDs must not contain surrounding whitespace")
        return value


class FailureDispositionBody(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    action: Literal["ignore", "restore"]
    selections: list[FailureSelection] = Field(min_length=1, max_length=100)

    @field_validator("selections")
    @classmethod
    def validate_selections(cls, value: list[FailureSelection]) -> list[FailureSelection]:
        if len({item.event_id for item in value}) != len(value):
            raise ValueError("Failure selections must contain unique event IDs")
        return value


class FailureDispositionResponse(BaseModel):
    changed_count: int = Field(ge=0)
    unchanged_count: int = Field(ge=0)


@memory_router.get("/l2/failures", response_model=ProjectionFailureSummary)
async def get_projection_failures() -> ProjectionFailureSummary:
    """Read current failure causes separately from dashboard polling."""
    memory = dependencies._resolve_unified_memory()
    if memory is None or memory.l2 is None:
        raise HTTPException(status_code=503, detail="Memory diagnostics are unavailable")
    return ProjectionFailureSummary.model_validate(await memory.l2.get_projection_failure_summary())


@memory_router.get("/l2/failures/records", response_model=ProjectionFailureRecords)
async def get_projection_failure_records(
    status: Literal["failed", "ignored"] = Query(default="failed"),
    source: str | None = Query(default=None, min_length=1, max_length=512),
    reason: ProjectionFailureReason | None = Query(default=None),
    event_id: str | None = Query(default=None, min_length=1, max_length=512),
    include_content: bool = Query(default=False),
    limit: int = Query(default=20, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
) -> ProjectionFailureRecords:
    """Read source previews; full content requires an explicit single-record query."""
    if include_content and event_id is None:
        raise HTTPException(status_code=422, detail="Full content requires an event ID")
    memory = dependencies._resolve_unified_memory()
    if memory is None or memory.l2 is None:
        raise HTTPException(status_code=503, detail="Memory diagnostics are unavailable")
    page = await memory.l2.list_projection_failure_records(
        status=status, source=source, reason=reason, event_id=event_id, limit=limit, offset=offset,
    )

    async def hydrate(row: dict[str, Any]) -> ProjectionFailureRecord:
        event = await memory.l1.get_user_visible_event(row["event_id"]) if memory.l1 is not None else None
        content = event["content"] if event is not None else None
        truncated = content is not None and not include_content and len(content) > 400
        return ProjectionFailureRecord.model_validate({
            **row, "content": content[:400] if truncated else content,
            "content_truncated": truncated,
            "recorded_at": float(event["timestamp"]) if event is not None else None,
        })

    items = await asyncio.gather(*(hydrate(row) for row in page["items"]))
    return ProjectionFailureRecords.model_validate({**page, "items": items})


@memory_router.post("/l2/failures/disposition", response_model=FailureDispositionResponse)
async def set_projection_failure_disposition(body: FailureDispositionBody) -> FailureDispositionResponse:
    """Ignore or restore selected failures; neither operation deletes or queues content."""
    memory = dependencies._resolve_unified_memory()
    if memory is None or memory.l2 is None:
        raise HTTPException(status_code=503, detail="Memory diagnostics are unavailable")
    result = await memory.set_l2_failure_disposition(
        action=body.action, selections=[item.model_dump() for item in body.selections],
    )
    return FailureDispositionResponse.model_validate(result)
