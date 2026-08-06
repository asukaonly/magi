"""Governed pending-memory review API routes."""

from __future__ import annotations

import uuid
from typing import Literal

from fastapi import HTTPException, Query, status
from pydantic import BaseModel, Field

from magi.memory.l2.pipeline.claim_persistence import EVIDENCE_RULE_VERSION
from magi.memory.l2.reviews.repository import (
    PendingReviewConflictError,
    PendingReviewNotFoundError,
)
from magi.memory.l2.semantic_routing import ROUTE_CONTRACT_VERSION

from ..dependencies import _resolve_unified_memory
from ..helpers import canonical_self_id, memory_t
from ..router import memory_router


class PendingReviewEditRequest(BaseModel):
    """User-editable review fields; semantic routing fields remain host-owned."""

    trait_value: str | None = Field(default=None, min_length=1, max_length=1000)
    natural_summary: str | None = Field(default=None, min_length=1, max_length=500)


class PendingReviewResolveRequest(BaseModel):
    """Optimistically versioned pending-review resolution command."""

    action: Literal["confirm", "reject", "confirm_with_edit"]
    expected_version: int = Field(ge=1)
    edit: PendingReviewEditRequest | None = None


@memory_router.get("/l2/reviews")
async def list_l2_pending_reviews(
    review_status: Literal["pending", "confirmed", "rejected", "closed"] = Query(
        default="pending",
        alias="status",
    ),
    limit: int = Query(default=100, ge=1, le=500),
):
    """List governed pre-materialization memory reviews."""

    unified_memory = _resolve_unified_memory()
    if not unified_memory or not unified_memory.l2:
        return {"items": [], "total": 0}
    items = await unified_memory.l2.list_pending_reviews(
        subject_id=canonical_self_id(unified_memory),
        status=review_status,
        limit=limit,
    )
    return {"items": items, "total": len(items)}


@memory_router.post("/l2/reviews/{review_id}/resolve")
async def resolve_l2_pending_review(
    review_id: str,
    body: PendingReviewResolveRequest,
):
    """Confirm, reject, or edit a pending review atomically."""

    unified_memory = _resolve_unified_memory()
    if not unified_memory or not unified_memory.l2:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=memory_t("memory.errors.l2_store_uninitialized", "L2 store not initialized"),
        )
    if body.action == "confirm_with_edit" and body.edit is None:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="confirm_with_edit requires an edit payload",
        )
    if body.action != "confirm_with_edit" and body.edit is not None:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="edit payload is only valid for confirm_with_edit",
        )
    try:
        result = await unified_memory.l2.resolve_pending_review(
            review_id=review_id,
            action=body.action,
            expected_version=body.expected_version,
            resolved_by=canonical_self_id(unified_memory),
            resolution_event_id=f"review_event_{uuid.uuid4().hex}",
            edit=(body.edit.model_dump(exclude_none=True) if body.edit is not None else None),
            route_contract_version=ROUTE_CONTRACT_VERSION,
            evidence_rule_version=EVIDENCE_RULE_VERSION,
        )
    except PendingReviewNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Pending review not found",
        ) from exc
    except PendingReviewConflictError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=str(exc),
        ) from exc
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=str(exc),
        ) from exc
    return {
        "review_id": result.review_id,
        "status": result.status,
        "version": result.version,
        "assertion_id": result.assertion_id,
    }


__all__ = [
    "PendingReviewEditRequest",
    "PendingReviewResolveRequest",
    "list_l2_pending_reviews",
    "resolve_l2_pending_review",
]
