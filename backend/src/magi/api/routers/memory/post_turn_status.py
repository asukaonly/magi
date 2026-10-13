"""Content-free status and recovery for durable conversation understanding."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field

from magi.core.logger import get_logger
from magi.core.runtime_bindings import get_optional_agent_runtime

logger = get_logger(__name__)


class PostTurnProcessingStatus(BaseModel):
    pending: int = Field(ge=0)
    claimed: int = Field(ge=0)
    failed: int = Field(ge=0)
    error_kinds: list[str]


def resolve_post_turn_service() -> Any | None:
    runtime = get_optional_agent_runtime()
    return runtime.get_post_turn_understanding_service() if runtime is not None else None


async def with_post_turn_processing(backlog: dict[str, Any]) -> dict[str, Any]:
    """Keep unavailable processing distinct from a verified idle queue."""
    service = resolve_post_turn_service()
    result: dict[str, Any] = {**backlog, "post_turn": None}
    if service is None:
        result["all_idle"] = False
        return result
    try:
        processing = PostTurnProcessingStatus.model_validate(await service.get_status())
    except Exception as exc:
        logger.warning("Post-turn processing status unavailable", error_type=type(exc).__name__)
        result["all_idle"] = False
        return result
    result["post_turn"] = processing.model_dump()
    busy = processing.pending + processing.claimed
    if "total_pending" in result:
        result["total_pending"] += busy
    result["all_idle"] = bool(result["all_idle"]) and busy == 0 and processing.failed == 0
    return result
