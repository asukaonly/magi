"""On-demand failure diagnostics for the memory overview."""

from fastapi import HTTPException
from pydantic import BaseModel, Field, field_validator

from magi.memory.l2.projection.diagnostics import ProjectionFailureReason
from magi.utils.log_redaction import redact_log_text

from .. import dependencies
from ..router import memory_router


class ProjectionFailureGroup(BaseModel):
    source: str
    reason: ProjectionFailureReason
    count: int = Field(gt=0)
    last_failed_at: float = Field(ge=0)
    error: str | None

    @field_validator("error")
    @classmethod
    def sanitize_error(cls, value: str | None) -> str | None:
        if not value:
            return None
        return redact_log_text(value)[:1200]


class ProjectionFailureSummary(BaseModel):
    total: int = Field(ge=0)
    groups: list[ProjectionFailureGroup] = Field(max_length=12)
    other_count: int = Field(ge=0)


@memory_router.get("/l2/failures", response_model=ProjectionFailureSummary)
async def get_projection_failures() -> ProjectionFailureSummary:
    """Read current failure causes separately from dashboard polling."""
    memory = dependencies._resolve_unified_memory()
    if memory is None or memory.l2 is None:
        raise HTTPException(status_code=503, detail="Memory diagnostics are unavailable")
    return ProjectionFailureSummary.model_validate(await memory.l2.get_projection_failure_summary())
