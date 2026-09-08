"""Entity identity governance exposed through the authenticated memory API."""

from __future__ import annotations

from collections.abc import Awaitable
from typing import TypeVar

from fastapi import HTTPException, Query

from magi.memory.l2.entities.governance import EntityIdentityService
from magi.memory.l2.entities.governance_models import (
    EntityChangeApplyRequest,
    EntityChangeCommand,
    EntityChangePreview,
    EntityChangeResult,
    EntityIdentityAudit,
    EntityReviewRejectRequest,
    EntityReviewRejectResult,
    EntityTypeReviewList,
)
from magi.memory.l2.entities.governance_read import (
    EntityIdentityConflictError,
    EntityIdentityNotFoundError,
)

from ..dependencies import _resolve_unified_memory
from ..helpers import canonical_self_id
from ..router import memory_router

T = TypeVar("T")


def _service() -> EntityIdentityService:
    memory = _resolve_unified_memory()
    if memory is None or memory.l2_entity_catalog is None:
        raise HTTPException(status_code=503, detail="Entity catalog is unavailable")
    return EntityIdentityService(memory.l2_entity_catalog)


async def _respond(operation: Awaitable[T]) -> T:
    try:
        return await operation
    except EntityIdentityNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except EntityIdentityConflictError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@memory_router.post("/l2/entities/changes/preview", response_model=EntityChangePreview)
async def preview_entity_change(body: EntityChangeCommand) -> EntityChangePreview:
    return await _respond(_service().preview(body))


@memory_router.post("/l2/entities/changes/apply", response_model=EntityChangeResult)
async def apply_entity_change(body: EntityChangeApplyRequest) -> EntityChangeResult:
    service = _service()
    memory = _resolve_unified_memory()
    async with memory.memory_operation_guard():
        return await _respond(service.apply(body, actor_id=canonical_self_id(memory)))


@memory_router.get("/l2/entities/reviews", response_model=EntityTypeReviewList)
async def list_entity_type_reviews(
    limit: int = Query(default=100, ge=1, le=500), offset: int = Query(default=0, ge=0)
) -> EntityTypeReviewList:
    return await _respond(_service().list_reviews(limit=limit, offset=offset))


@memory_router.post(
    "/l2/entities/reviews/{review_id}/reject", response_model=EntityReviewRejectResult
)
async def reject_entity_type_review(
    review_id: str, body: EntityReviewRejectRequest
) -> EntityReviewRejectResult:
    return await _respond(
        _service().reject_review(review_id, expected_version=body.expected_version)
    )


@memory_router.get("/l2/entities/identity-audit", response_model=EntityIdentityAudit)
async def audit_entity_identities(
    limit: int = Query(default=50, ge=1, le=100), offset: int = Query(default=0, ge=0)
) -> EntityIdentityAudit:
    return await _respond(_service().audit(limit=limit, offset=offset))
