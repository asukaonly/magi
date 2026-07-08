"""L2 graph, entity, assertion, and snapshot API routes."""

from __future__ import annotations

import asyncio

from fastapi import HTTPException, Query, status

from ..dependencies import _resolve_unified_memory
from ..helpers import canonical_self_id, memory_t
from ..router import memory_router
from ..schemas import AssertionCorrectionRequest, AssertionFeedbackRequest, GraphConflictRuleBody
from .....user_profile.portrait_projection_scheduler import (
    schedule_portrait_projection_refresh_after_assertion_change,
)


@memory_router.get("/l2/relations")
async def list_l2_relations(
    limit: int = Query(default=50, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    query: str | None = Query(default=None),
):
    """List knowledge graph relations."""
    unified_memory = _resolve_unified_memory()
    if not unified_memory or not unified_memory.l2:
        return {"items": [], "total": 0, "limit": limit, "offset": offset}
    items, total = await asyncio.gather(
        unified_memory.l2.get_relationships(limit=limit, offset=offset, query=query),
        unified_memory.l2.count_relationships(query=query),
    )
    return {"items": items, "total": total, "limit": limit, "offset": offset}


@memory_router.get("/l2/assertions")
async def list_l2_assertions(
    limit: int = Query(default=50, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    query: str | None = Query(default=None),
):
    """List ToM trait assertions."""
    unified_memory = _resolve_unified_memory()
    if not unified_memory or not unified_memory.l2:
        return {"items": [], "total": 0, "limit": limit, "offset": offset}
    items, total = await asyncio.gather(
        unified_memory.l2.list_tom_assertions(limit=limit, offset=offset, query=query),
        unified_memory.l2.count_tom_assertions(query=query),
    )
    return {"items": items, "total": total, "limit": limit, "offset": offset}


@memory_router.patch("/l2/assertions/{assertion_id}/feedback")
async def submit_assertion_feedback(assertion_id: str, body: AssertionFeedbackRequest):
    """Apply user confirmation or rejection to an L2 assertion."""
    unified_memory = _resolve_unified_memory()
    if not unified_memory or not unified_memory.l2:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=memory_t("memory.errors.l2_store_uninitialized", "L2 store not initialized"),
        )
    result = await unified_memory.l2.apply_user_feedback(assertion_id=assertion_id, feedback=body.feedback)
    if result is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=memory_t("memory.errors.assertion_not_found", "Assertion not found"))
    await schedule_portrait_projection_refresh_after_assertion_change(unified_memory, result)
    return result


@memory_router.post("/l2/assertions/{assertion_id}/correct")
async def correct_assertion(assertion_id: str, body: AssertionCorrectionRequest):
    """User-initiated value correction that supersedes an existing assertion."""
    unified_memory = _resolve_unified_memory()
    if not unified_memory or not unified_memory.l2:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=memory_t("memory.errors.l2_store_uninitialized", "L2 store not initialized"),
        )
    result = await unified_memory.l2.correct_assertion(
        assertion_id=assertion_id,
        new_value=body.new_value,
        reason=body.reason,
    )
    if result is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=memory_t("memory.errors.assertion_not_found", "Assertion not found"))
    await schedule_portrait_projection_refresh_after_assertion_change(unified_memory, result)
    return result


@memory_router.get("/l2/entities")
async def list_l2_entities(
    limit: int = Query(default=50, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    query: str | None = Query(default=None),
):
    """List canonical L2 entities for the frontend lab picker."""
    unified_memory = _resolve_unified_memory()
    if not unified_memory or not unified_memory.l2_entity_catalog:
        return {"items": [], "total": 0, "limit": limit, "offset": offset}
    items, total = await asyncio.gather(
        unified_memory.l2_entity_catalog.list_entities(limit=limit, offset=offset, query=query),
        unified_memory.l2_entity_catalog.count_entities(query=query),
    )
    return {"items": items, "total": total, "limit": limit, "offset": offset}


@memory_router.get("/l2/mentions")
async def list_l2_mentions(
    limit: int = Query(default=50, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
):
    """List recent entity mentions and their resolution state."""
    unified_memory = _resolve_unified_memory()
    if not unified_memory or not unified_memory.l2_entity_catalog:
        return {"items": [], "total": 0, "limit": limit, "offset": offset}
    items, total = await asyncio.gather(
        unified_memory.l2_entity_catalog.list_mentions(limit=limit, offset=offset),
        unified_memory.l2_entity_catalog.count_mentions(),
    )
    return {"items": items, "total": total, "limit": limit, "offset": offset}


@memory_router.get("/l2/snapshots")
async def list_l2_snapshots(
    limit: int = Query(default=50, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    query: str | None = Query(default=None),
):
    """List materialized L2 snapshots."""
    unified_memory = _resolve_unified_memory()
    if not unified_memory or not unified_memory.l2:
        return {"items": [], "total": 0, "limit": limit, "offset": offset}
    items, total = await asyncio.gather(
        unified_memory.l2.list_tom_snapshots(limit=limit, offset=offset, query=query),
        unified_memory.l2.count_tom_snapshots(query=query),
    )
    return {"items": items, "total": total, "limit": limit, "offset": offset}


@memory_router.get("/l2/conflict-rules")
async def list_l2_conflict_rules():
    """List persisted graph conflict rules."""
    unified_memory = _resolve_unified_memory()
    if not unified_memory or not unified_memory.l2:
        return []
    return await unified_memory.l2.list_graph_conflict_rules()


@memory_router.get("/identity/links")
async def list_memory_identity_links():
    """List runtime-to-memory identity mappings for frontend debugging views."""
    unified_memory = _resolve_unified_memory()
    if not unified_memory or not hasattr(unified_memory, "list_identity_links"):
        return {
            "canonical_self_id": canonical_self_id(unified_memory),
            "links": [],
        }
    return {
        "canonical_self_id": canonical_self_id(unified_memory),
        "links": await unified_memory.list_identity_links(),
    }


@memory_router.put("/l2/conflict-rules/{predicate}")
async def upsert_l2_conflict_rule(predicate: str, body: GraphConflictRuleBody):
    """Create or update a persisted graph conflict rule."""
    unified_memory = _resolve_unified_memory()
    if not unified_memory or not unified_memory.l2:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=memory_t("memory.errors.system_uninitialized", "Memory system not initialized"),
        )
    normalized_predicate = predicate.strip()
    if not normalized_predicate:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=memory_t("memory.errors.predicate_required", "Predicate is required"))
    try:
        return await unified_memory.l2.upsert_graph_conflict_rule(
            {
                "predicate": normalized_predicate,
                "opposite_predicates": body.opposite_predicates,
                "opposite_resolution": body.opposite_resolution,
                "exclusive_group": body.exclusive_group,
                "exclusive_scope": body.exclusive_scope,
                "exclusive_resolution": body.exclusive_resolution,
            }
        )
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)) from exc


@memory_router.get("/tom/{entity_id}")
async def get_tom_snapshot(entity_id: str, entity_type: str = Query(default="user")):
    unified_memory = _resolve_unified_memory()
    if not unified_memory or not unified_memory.l2:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=memory_t("memory.errors.cognition_store_unavailable", "Cognition store unavailable"),
        )

    snapshot = await unified_memory.l2.get_tom_snapshot(entity_id=entity_id, entity_type=entity_type)
    if snapshot is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=memory_t("memory.errors.snapshot_not_found", "Snapshot not found"))
    return snapshot
