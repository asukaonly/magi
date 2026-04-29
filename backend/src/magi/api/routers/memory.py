"""Memory API for the rewritten L0-L4 memory system."""

from __future__ import annotations

import asyncio
from dataclasses import asdict
import time
from typing import Any, Dict, Optional

from fastapi import APIRouter, HTTPException, Query, status

from ...chat import get_chat_read_service
from ...core.logger import get_logger
from ...core.runtime_bindings import (
    require_hybrid_retrieval_service,
    require_memory_integration,
    require_scenario_llm_pool,
    require_unified_memory,
)
from ...memory.eval_support.contracts import EvalMemoryQuery, EvalMemoryWriteRecord
from ...memory.eval_support.reader import EvalMemoryReader
from ...memory.eval_support.writer import EvalMemoryWriter
from ...memory.hybrid_retrieval import build_query
from ...memory.l2.models import ManualL2EventRequest
from .memory_eval_answering import (
    EVAL_ANSWER_TIMEOUT as _EVAL_ANSWER_TIMEOUT,
    format_l2_context as _format_l2_context,
    is_counting_or_aggregation_question as _is_counting_or_aggregation_question,
    is_temporal_reasoning_question as _is_temporal_reasoning_question,
    synthesize_eval_answer,
)
from .memory_clear import build_clear_memory_response as _build_clear_memory_response
from .memory_l0_sessions import (
    build_l0_session_list_items,
    empty_l0_sessions_response,
    filter_l0_session_ids_by_query,
    session_ids_by_user,
    sorted_l0_session_ids,
)
from .memory_l1_events import (
    build_l1_event_query_args as _build_l1_event_query_args,
    build_l1_events_response as _build_l1_events_response,
)
from .memory_l2_status import (
    build_background_pending_response as _build_background_pending_response,
    build_embedding_pending_from_store as _build_embedding_pending_from_store,
    build_l2_pending_payload as _build_l2_pending_payload,
    build_l2_pending_response as _build_l2_pending_response,
    build_l2_statistics_response as _build_l2_statistics_response,
    default_projection_backlog as _default_projection_backlog,
    empty_background_pending_response as _empty_background_pending_response,
    empty_l2_pending_response as _empty_l2_pending_response,
    empty_l2_statistics_response as _empty_l2_statistics_response,
)
from .memory_procedures import build_procedure_list_response as _build_procedure_list_response
from .memory_route_helpers import (
    canonical_self_id as _canonical_self_id,
    serialize_memory_event as _serialize_memory_event,
)
from .memory_schemas import (
    AssertionCorrectionRequest,
    AssertionFeedbackRequest,
    EpisodeAnnotationRequest,
    EvalFinalizeReplayRequest,
    EvalQueryRequest,
    EvalReplayRecordBody,
    EvalReplayRequest,
    ForgetEntityRequest,
    ForgetEpisodeRequest,
    ForgetTimeRangeRequest,
    GraphConflictRuleBody,
    L2EntityActionBody,
    ManualL2EventBody,
    RetrievalRequest,
)
from .memory_statistics import build_layer_statistics as _build_layer_statistics

logger = get_logger(__name__)

memory_router = APIRouter()


def _resolve_unified_memory():
    try:
        return require_unified_memory()
    except RuntimeError:
        return None


def _resolve_memory_integration():
    try:
        return require_memory_integration()
    except RuntimeError:
        return None


def _resolve_hybrid_retrieval_service():
    try:
        return require_hybrid_retrieval_service()
    except RuntimeError:
        return None


def _resolve_scenario_llm_pool():
    try:
        return require_scenario_llm_pool()
    except RuntimeError:
        return None


async def _synthesize_eval_answer(**kwargs: Any) -> tuple[str, dict[str, Any]]:
    return await synthesize_eval_answer(
        **kwargs,
        llm_pool=_resolve_scenario_llm_pool(),
        log=logger,
    )


# =============================================================================
# L0 Working Memory Endpoints
# =============================================================================

@memory_router.get("/l0/sessions")
async def list_l0_sessions(
    limit: int = Query(50, ge=1, le=500),
    offset: int = Query(0, ge=0),
    status: str | None = Query(None),
    query: str | None = Query(None),
):
    """List L0 sessions with pagination, sorted by last_active_at descending."""
    unified_memory = _resolve_unified_memory()
    if not unified_memory or not unified_memory.l0:
        return empty_l0_sessions_response(limit=limit, offset=offset)

    chat_read_service = get_chat_read_service()
    l0_sessions = unified_memory.l0._sessions
    sorted_ids = sorted_l0_session_ids(l0_sessions, status_filter=status)

    total = len(sorted_ids)
    page_ids = sorted_ids[offset : offset + limit]

    summary_map: dict[str, Any] = {}
    for user_id, session_ids in session_ids_by_user(l0_sessions, page_ids).items():
        batch = await chat_read_service.aget_session_summaries_batch(user_id, session_ids)
        summary_map.update(batch)

    page_ids = filter_l0_session_ids_by_query(
        session_ids=page_ids,
        query=query,
        sessions=l0_sessions,
        goals_by_session=unified_memory.l0._goal_stack,
        summary_map=summary_map,
    )
    items, stats = build_l0_session_list_items(
        session_ids=page_ids,
        sessions=l0_sessions,
        goals_by_session=unified_memory.l0._goal_stack,
        entities_by_session=unified_memory.l0._active_entities,
        tactics_by_session=unified_memory.l0._temporary_tactics,
        summary_map=summary_map,
    )

    return {
        "items": items,
        "total": total,
        "limit": limit,
        "offset": offset,
        "stats": stats,
    }


@memory_router.get("/l0/workbench/{session_id}")
async def get_l0_workbench(session_id: str):
    """Get the workbench (goals, entities, tactics) for a session."""
    unified_memory = _resolve_unified_memory()
    if not unified_memory or not unified_memory.l0:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="L0 working memory not initialized",
        )

    workbench = await unified_memory.l0.get_workbench(session_id)
    if not workbench.get("session"):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Session not found",
        )
    return workbench


# =============================================================================
# L2 Cognition Endpoints
# =============================================================================

@memory_router.get("/l2/statistics")
async def get_l2_statistics():
    """Get L2 cognition statistics."""
    unified_memory = _resolve_unified_memory()
    if not unified_memory or not unified_memory.l2:
        return _empty_l2_statistics_response()

    rel_count, tom_count = await asyncio.gather(
        unified_memory.l2.count_relationships(),
        unified_memory.l2.count_tom_assertions(),
    )
    pipeline_stats = unified_memory.get_l2_pipeline_stats() if hasattr(unified_memory, "get_l2_pipeline_stats") else {}
    projection_backlog = (
        await unified_memory.get_l2_projection_backlog()
        if hasattr(unified_memory, "get_l2_projection_backlog")
        else _default_projection_backlog()
    )
    return _build_l2_statistics_response(
        relation_count=rel_count,
        assertion_count=tom_count,
        pipeline_stats=pipeline_stats,
        projection_backlog=projection_backlog,
        db_path=unified_memory.l2.db_path,
    )


@memory_router.get("/l2/pending")
async def get_l2_pending():
    """Get calculated L2 queue backlog for quick polling."""
    unified_memory = _resolve_unified_memory()
    if not unified_memory or not unified_memory.l2:
        return _empty_l2_pending_response()

    pipeline_stats = unified_memory.get_l2_pipeline_stats() if hasattr(unified_memory, "get_l2_pipeline_stats") else {}
    projection_backlog = (
        await unified_memory.get_l2_projection_backlog()
        if hasattr(unified_memory, "get_l2_projection_backlog")
        else _default_projection_backlog()
    )
    return _build_l2_pending_response(
        pipeline_stats=pipeline_stats,
        projection_backlog=projection_backlog,
    )


@memory_router.get("/background/pending")
async def get_background_pending():
    """Get lightweight backlog stats for background memory workers."""
    unified_memory = _resolve_unified_memory()
    if not unified_memory:
        return _empty_background_pending_response()

    pipeline_stats = unified_memory.get_l2_pipeline_stats() if hasattr(unified_memory, "get_l2_pipeline_stats") else {}
    projection_backlog = (
        await unified_memory.get_l2_projection_backlog()
        if hasattr(unified_memory, "get_l2_projection_backlog")
        else _default_projection_backlog()
    )
    return _build_background_pending_response(
        l2_pending=_build_l2_pending_payload(
            pipeline_stats=pipeline_stats,
            projection_backlog=projection_backlog,
        ),
        l1_pending=_build_embedding_pending_from_store(getattr(unified_memory, "l1", None)),
        l3_pending=_build_embedding_pending_from_store(getattr(unified_memory, "l3", None)),
        l4_pending=_build_embedding_pending_from_store(getattr(unified_memory, "l4", None)),
    )


@memory_router.get("/l2/relations")
async def list_l2_relations(
    limit: int = Query(default=50, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
):
    """List knowledge graph relations."""
    unified_memory = _resolve_unified_memory()
    if not unified_memory or not unified_memory.l2:
        return {"items": [], "total": 0, "limit": limit, "offset": offset}
    items, total = await asyncio.gather(
        unified_memory.l2.get_relationships(limit=limit, offset=offset),
        unified_memory.l2.count_relationships(),
    )
    return {"items": items, "total": total, "limit": limit, "offset": offset}


@memory_router.get("/l2/assertions")
async def list_l2_assertions(
    limit: int = Query(default=50, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
):
    """List ToM trait assertions."""
    unified_memory = _resolve_unified_memory()
    if not unified_memory or not unified_memory.l2:
        return {"items": [], "total": 0, "limit": limit, "offset": offset}
    items, total = await asyncio.gather(
        unified_memory.l2.list_tom_assertions(limit=limit, offset=offset),
        unified_memory.l2.count_tom_assertions(),
    )
    return {"items": items, "total": total, "limit": limit, "offset": offset}


@memory_router.patch("/l2/assertions/{assertion_id}/feedback")
async def submit_assertion_feedback(assertion_id: str, body: AssertionFeedbackRequest):
    """Apply user confirmation or rejection to an L2 assertion."""
    unified_memory = _resolve_unified_memory()
    if not unified_memory or not unified_memory.l2:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="L2 store not initialized")
    result = await unified_memory.l2.apply_user_feedback(assertion_id=assertion_id, feedback=body.feedback)
    if result is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Assertion not found")
    return result


@memory_router.post("/l2/assertions/{assertion_id}/correct")
async def correct_assertion(assertion_id: str, body: AssertionCorrectionRequest):
    """User-initiated value correction that supersedes an existing assertion."""
    unified_memory = _resolve_unified_memory()
    if not unified_memory or not unified_memory.l2:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="L2 store not initialized")
    result = await unified_memory.l2.correct_assertion(
        assertion_id=assertion_id,
        new_value=body.new_value,
        reason=body.reason,
    )
    if result is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Assertion not found")
    return result


@memory_router.get("/l2/entities")
async def list_l2_entities(
    limit: int = Query(default=50, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
):
    """List canonical L2 entities for the frontend lab picker."""
    unified_memory = _resolve_unified_memory()
    if not unified_memory or not unified_memory.l2_entity_catalog:
        return {"items": [], "total": 0, "limit": limit, "offset": offset}
    items, total = await asyncio.gather(
        unified_memory.l2_entity_catalog.list_entities(limit=limit, offset=offset),
        unified_memory.l2_entity_catalog.count_entities(),
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
):
    """List materialized L2 snapshots."""
    unified_memory = _resolve_unified_memory()
    if not unified_memory or not unified_memory.l2:
        return {"items": [], "total": 0, "limit": limit, "offset": offset}
    items, total = await asyncio.gather(
        unified_memory.l2.list_tom_snapshots(limit=limit, offset=offset),
        unified_memory.l2.count_tom_snapshots(),
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
            "canonical_self_id": "user:self",
            "links": [],
        }
    return {
        "canonical_self_id": _canonical_self_id(unified_memory),
        "links": await unified_memory.list_identity_links(),
    }


@memory_router.put("/l2/conflict-rules/{predicate}")
async def upsert_l2_conflict_rule(predicate: str, body: GraphConflictRuleBody):
    """Create or update a persisted graph conflict rule."""
    unified_memory = _resolve_unified_memory()
    if not unified_memory or not unified_memory.l2:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Memory system not initialized",
        )
    normalized_predicate = predicate.strip()
    if not normalized_predicate:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Predicate is required")
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


@memory_router.post("/l2/manual-event")
async def create_manual_l2_event(body: ManualL2EventBody):
    """Inject a manual event into the L1 -> L2 write path."""
    unified_memory = _resolve_unified_memory()
    if not unified_memory:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Memory system not initialized",
        )
    result = await unified_memory.ingest_manual_l2_event(
        ManualL2EventRequest(
            text=body.text,
            user_id=body.user_id,
            session_id=body.session_id,
            source=body.source,
            entity_focus_hint=body.entity_focus_hint,
        )
    )
    return {"queued": True, **result}


@memory_router.post("/eval/replay")
async def replay_eval_records(body: EvalReplayRequest):
    """Replay benchmark records through the standard memory ingest path."""
    unified_memory = _resolve_unified_memory()
    if not unified_memory:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Memory system not initialized",
        )

    writer = EvalMemoryWriter(unified_memory)
    results = await writer.write_records(
        [
            EvalMemoryWriteRecord(
                namespace=record.namespace,
                session_id=record.session_id,
                timestamp=record.timestamp,
                role=record.role,
                content=record.content,
                turn_id=record.turn_id,
                metadata=dict(record.metadata),
            )
            for record in body.records
        ]
    )
    return {
        "namespace": body.namespace,
        "written": len(results),
        "results": results,
    }


@memory_router.post("/eval/query")
async def query_eval_memory(body: EvalQueryRequest):
    """Query benchmark memory directly without chat rendering."""
    retrieval_service = _resolve_hybrid_retrieval_service()
    if retrieval_service is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Hybrid retrieval service not initialized",
        )

    unified_memory = _resolve_unified_memory()
    reader = EvalMemoryReader(
        retrieval_service,
        l1_store=getattr(unified_memory, "l1", None) if unified_memory is not None else None,
    )
    logger.info(
        "Eval memory query started",
        namespace=body.namespace,
        mode=body.mode,
        top_k=body.top_k,
        answer_with_llm=body.answer_with_llm,
        query=body.query,
    )
    started_at = time.perf_counter()
    result = await reader.query_memory(
        EvalMemoryQuery(
            namespace=body.namespace,
            query=body.query,
            query_timestamp=body.query_timestamp,
            top_k=body.top_k,
            mode=body.mode,
            answer_with_llm=body.answer_with_llm,
            show_prompt=body.show_prompt,
        )
    )
    logger.info(
        "Eval memory query completed",
        namespace=body.namespace,
        mode=body.mode,
        top_k=body.top_k,
        answer_with_llm=body.answer_with_llm,
        hit_count=len(result.hits),
        duration_ms=round((time.perf_counter() - started_at) * 1000, 2),
    )
    if body.answer_with_llm:
        answer, answer_trace = await _synthesize_eval_answer(
            question=body.query,
            hits=[asdict(hit) for hit in result.hits],
            evidence_bundles=list(result.evidence_bundles),
            timeline_summary=list(result.timeline_summary),
            l2_entity_cards=list(result.l2_entity_cards),
            l2_relationships=list(result.l2_relationships),
            l2_assertions=list(result.l2_assertions),
            l2_episodes=list(result.l2_episodes),
            query_timestamp=body.query_timestamp,
            show_prompt=body.show_prompt,
        )
        result.answer = answer
        result.answer_trace = answer_trace
    return asdict(result)


@memory_router.post("/eval/finalize-replay")
async def finalize_eval_replay(body: EvalFinalizeReplayRequest):
    """Run post-replay summary generation and expose L2 pipeline status."""
    unified_memory = _resolve_unified_memory()
    if not unified_memory:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Memory system not initialized",
        )

    summaries: Dict[str, Any] = {}
    for period_type in body.period_types:
        summaries[period_type] = await unified_memory.generate_summary(period_type=period_type)

    l2_pipeline_stats = (
        unified_memory.get_l2_pipeline_stats()
        if hasattr(unified_memory, "get_l2_pipeline_stats")
        else {}
    )
    return {
        "summaries": summaries,
        "l2_pipeline_stats": l2_pipeline_stats,
    }


@memory_router.post("/l2/extract/{event_id}")
async def replay_l2_extraction(event_id: str):
    """Replay event extraction for an existing L1 event."""
    unified_memory = _resolve_unified_memory()
    if not unified_memory:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Memory system not initialized",
        )
    queued = await unified_memory.replay_l2_extraction(event_id)
    if not queued:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Event not found or pipeline unavailable")
    return {"queued": True, "event_id": event_id}


@memory_router.post("/l2/reconcile")
async def trigger_l2_reconcile(body: L2EntityActionBody):
    """Manually enqueue entity reconcile work."""
    unified_memory = _resolve_unified_memory()
    if not unified_memory:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Memory system not initialized",
        )
    queued = await unified_memory.reconcile_entities(body.entity_ids)
    if not queued:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="No valid entities to reconcile")
    return {"queued": True, "entity_ids": body.entity_ids}


@memory_router.post("/l2/snapshot-refresh")
async def trigger_l2_snapshot_refresh(body: L2EntityActionBody):
    """Manually enqueue snapshot refresh work."""
    unified_memory = _resolve_unified_memory()
    if not unified_memory:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Memory system not initialized",
        )
    queued = await unified_memory.refresh_l2_snapshots(body.entity_ids)
    if not queued:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="No valid entities to materialize")
    return {"queued": True, "entity_ids": body.entity_ids}


@memory_router.post("/l2/microbatch-flush")
async def trigger_l2_microbatch_flush():
    """Immediately flush all currently staged L2 microbatches."""
    unified_memory = _resolve_unified_memory()
    if not unified_memory:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Memory system not initialized",
        )

    batch_count = await unified_memory.flush_l2_microbatches()
    return {"queued": batch_count > 0, "batch_count": batch_count}


# =============================================================================
# L3 Reflection Endpoints
# =============================================================================

@memory_router.get("/l3/summaries")
async def list_l3_summaries(
    limit: int = Query(default=50, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    summary_type: Optional[str] = Query(default=None, description="Filter by type: temporal, thematic, insight"),
    summary_category: Optional[str] = Query(default=None, description="Filter by category: topic, task_reflection, state_change, trend_shift, etc."),
):
    """List L3 reflection summaries."""
    unified_memory = _resolve_unified_memory()
    if not unified_memory or not unified_memory.l3:
        return {"items": [], "total": 0, "limit": limit, "offset": offset}

    items, total = await asyncio.gather(
        unified_memory.l3.list_summaries(limit=limit, offset=offset),
        unified_memory.l3.count_summaries(),
    )
    if summary_type:
        items = [s for s in items if s.get("summary_type") == summary_type]
    if summary_category:
        items = [s for s in items if s.get("summary_category") == summary_category]
    return {"items": items, "total": total, "limit": limit, "offset": offset}


# =============================================================================
# Unified Statistics Endpoint
# =============================================================================

@memory_router.get("/statistics")
async def get_memory_statistics():
    """Return per-layer memory statistics in L0-L4 format."""
    unified_memory = _resolve_unified_memory()
    memory_integration = _resolve_memory_integration()

    if not unified_memory:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Memory system not initialized",
        )

    async def _zero() -> int:
        return 0

    l1_coro = unified_memory.l1.count_events() if unified_memory.l1 else _zero()
    l2_rel_coro = unified_memory.l2.count_relationships() if unified_memory.l2 else _zero()
    l2_tom_coro = unified_memory.l2.count_tom_assertions() if unified_memory.l2 else _zero()
    l3_coro = unified_memory.l3.count_summaries() if unified_memory.l3 else _zero()
    l4_coro = unified_memory.l4.count_skills() if unified_memory.l4 else _zero()

    l1_count, l2_rel_count, l2_tom_count, l3_count, l4_count = await asyncio.gather(
        l1_coro, l2_rel_coro, l2_tom_coro, l3_coro, l4_coro,
    )
    return _build_layer_statistics(
        unified_memory=unified_memory,
        l1_count=l1_count,
        l2_relation_count=l2_rel_count,
        l2_assertion_count=l2_tom_count,
        l3_count=l3_count,
        l4_count=l4_count,
        integration_stats=memory_integration.get_statistics() if memory_integration else None,
    )


@memory_router.delete("/clear")
async def clear_memory_layers():
    """Clear all memory layers and chat session mappings."""
    logger.info("clear_memory: request received")
    unified_memory = _resolve_unified_memory()
    if not unified_memory:
        logger.warning("clear_memory: memory system not initialized")
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Memory system not initialized",
        )

    logger.info("clear_memory: clearing l0")
    l0_count = await unified_memory.l0.clear() if getattr(unified_memory, "l0", None) else 0
    logger.info("clear_memory: l0 done, removed=%d; clearing l1", l0_count)
    l1_count = await unified_memory.l1.clear() if getattr(unified_memory, "l1", None) else 0
    logger.info("clear_memory: l1 done, removed=%d; clearing l2", l1_count)
    l2_count = await unified_memory.l2.clear() if getattr(unified_memory, "l2", None) else 0
    if getattr(unified_memory, "l2_entity_catalog", None):
        l2_count += await unified_memory.l2_entity_catalog.clear()
    logger.info("clear_memory: l2 done, removed=%d; clearing l3", l2_count)
    l3_count = await unified_memory.l3.clear() if getattr(unified_memory, "l3", None) else 0
    logger.info("clear_memory: l3 done, removed=%d; clearing l4", l3_count)
    l4_count = await unified_memory.l4.clear() if getattr(unified_memory, "l4", None) else 0
    logger.info("clear_memory: l4 done, removed=%d; clearing chat context", l4_count)
    chat_context_count = get_chat_read_service().clear_all_sessions()
    logger.info(
        "clear_memory: complete. l0=%d l1=%d l2=%d l3=%d l4=%d chat=%d",
        l0_count, l1_count, l2_count, l3_count, l4_count, chat_context_count,
    )

    return _build_clear_memory_response(
        l0_count=l0_count,
        l1_count=l1_count,
        l2_count=l2_count,
        l3_count=l3_count,
        l4_count=l4_count,
        chat_context_count=chat_context_count,
    )


@memory_router.get("/l1/events")
async def get_l1_events(
    limit: int = Query(default=50, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    event_type: Optional[str] = Query(default=None),
    user_id: Optional[str] = Query(default=None),
    session_id: Optional[str] = Query(default=None),
    query: Optional[str] = Query(default=None),
    source: Optional[str] = Query(default=None),
    source_item_id: Optional[str] = Query(default=None),
    idempotency_key: Optional[str] = Query(default=None),
    start_date: Optional[str] = Query(default=None),
    end_date: Optional[str] = Query(default=None),
):
    unified_memory = _resolve_unified_memory()
    if not unified_memory or not unified_memory.l1:
        return {"items": [], "total": 0, "limit": limit, "offset": offset}

    query_args = _build_l1_event_query_args(
        session_id=session_id,
        user_id=user_id,
        event_type=event_type,
        query=query,
        source=source,
        source_item_id=source_item_id,
        idempotency_key=idempotency_key,
        start_date=start_date,
        end_date=end_date,
    )

    events, total = await asyncio.gather(
        unified_memory.l1.query_events(
            **query_args,
            limit=limit,
            offset=offset,
            include_metadata_json=False,
            include_embedding_fields=False,
        ),
        unified_memory.l1.count_events(
            **query_args,
        ),
    )
    return _build_l1_events_response(
        events=events,
        total=total,
        limit=limit,
        offset=offset,
    )


@memory_router.post("/search")
async def search_memory(request: RetrievalRequest):
    retrieval_service = _resolve_hybrid_retrieval_service()
    if retrieval_service is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Hybrid retrieval service not initialized",
        )

    payload = await retrieval_service.query(
        build_query(
            query=request.query,
            user_id=request.user_id,
            session_id=request.session_id,
            time_range=request.time_range,
            query_mode=request.query_mode,
            source_filters=request.source_filters,
            domain_filters=request.domain_filters,
            limit=request.limit,
        )
    )
    return asdict(payload)


@memory_router.get("/procedures")
async def list_procedures(
    limit: int = Query(default=50, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
):
    unified_memory = _resolve_unified_memory()
    if not unified_memory or not unified_memory.l4:
        return {"items": [], "total": 0, "limit": limit, "offset": offset}

    items, total = await asyncio.gather(
        unified_memory.l4.get_all_skills(limit=limit, offset=offset),
        unified_memory.l4.count_skills(),
    )
    return _build_procedure_list_response(
        items=items,
        total=total,
        limit=limit,
        offset=offset,
    )


@memory_router.get("/tom/{entity_id}")
async def get_tom_snapshot(entity_id: str, entity_type: str = Query(default="user")):
    unified_memory = _resolve_unified_memory()
    if not unified_memory or not unified_memory.l2:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Cognition store unavailable",
        )

    snapshot = await unified_memory.l2.get_tom_snapshot(entity_id=entity_id, entity_type=entity_type)
    if snapshot is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Snapshot not found")
    return snapshot


# ── Episode Endpoints ────────────────────────────────────────────


@memory_router.get("/l2/episodes")
async def list_l2_episodes(
    status_filter: Optional[str] = Query(default=None, alias="status"),
    episode_type: Optional[str] = Query(default=None),
    time_start: Optional[float] = Query(default=None),
    time_end: Optional[float] = Query(default=None),
    parent_episode_id: Optional[str] = Query(default=None),
    limit: int = Query(default=50, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
):
    """List episodes with optional filters."""
    unified_memory = _resolve_unified_memory()
    if not unified_memory or not unified_memory.l2:
        return {"items": [], "total": 0, "limit": limit, "offset": offset}
    items, total = await asyncio.gather(
        unified_memory.l2.list_episodes(
            status=status_filter,
            episode_type=episode_type,
            time_start=time_start,
            time_end=time_end,
            parent_episode_id=parent_episode_id,
            limit=limit,
            offset=offset,
        ),
        unified_memory.l2.count_episodes(status=status_filter),
    )
    return {"items": items, "total": total, "limit": limit, "offset": offset}


@memory_router.get("/l2/episodes/search")
async def search_l2_episodes(
    q: str = Query(..., min_length=1, max_length=500),
    limit: int = Query(default=20, ge=1, le=100),
):
    """Full-text search over episodes."""
    unified_memory = _resolve_unified_memory()
    if not unified_memory or not unified_memory.l2:
        return {"items": []}
    items = await unified_memory.l2.search_episodes_fts(query=q, limit=limit)
    return {"items": items}


@memory_router.get("/l2/episodes/{episode_id}")
async def get_l2_episode(episode_id: str):
    """Get a single episode with its event memberships."""
    unified_memory = _resolve_unified_memory()
    if not unified_memory or not unified_memory.l2:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="L2 store not initialized")
    episode = await unified_memory.l2.get_episode(episode_id=episode_id)
    if episode is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Episode not found")
    events = await unified_memory.l2.list_episode_events(episode_id=episode_id)
    return {**episode, "events": events}


@memory_router.patch("/l2/episodes/{episode_id}")
async def annotate_l2_episode(episode_id: str, body: EpisodeAnnotationRequest):
    """User annotation on an episode (label, note, pin)."""
    unified_memory = _resolve_unified_memory()
    if not unified_memory or not unified_memory.l2:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="L2 store not initialized")
    updates: Dict[str, Any] = {}
    if body.user_label is not None:
        updates["user_label"] = body.user_label
    if body.user_note is not None:
        updates["user_note"] = body.user_note
    if body.user_pinned is not None:
        updates["user_pinned"] = 1 if body.user_pinned else 0
        if body.user_pinned:
            updates["status"] = "user_pinned"
    if not updates:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="No fields to update")
    ok = await unified_memory.l2.update_episode(episode_id=episode_id, **updates)
    if not ok:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Episode not found")
    return await unified_memory.l2.get_episode(episode_id=episode_id)


# ── User agency: reject / forget ─────────────────────────────────


@memory_router.patch("/l2/edges/{triple_id}/reject")
async def reject_l2_edge(triple_id: str):
    """User-initiated rejection of a KG edge."""
    unified_memory = _resolve_unified_memory()
    if not unified_memory or not unified_memory.l2:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="L2 store not initialized")
    result = await unified_memory.l2.reject_edge(triple_id=triple_id)
    if result is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Edge not found")
    return result


@memory_router.post("/forget/entity")
async def forget_entity(body: ForgetEntityRequest):
    """Cascade forget: invalidate all L2 records derived from an entity."""
    unified_memory = _resolve_unified_memory()
    if not unified_memory or not unified_memory.l2:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="L2 store not initialized")

    l2_counts = await unified_memory.l2.forget_entity(entity_id=body.entity_id)

    l1_deleted = 0
    if body.delete_l1_events and unified_memory.l1 is not None:
        entity_events = await unified_memory.l1.get_entity_event_ids([body.entity_id])
        event_ids = entity_events.get(body.entity_id, [])
        for eid in event_ids:
            if await unified_memory.l1.mark_deleted(eid):
                l1_deleted += 1

    return {"l2_counts": l2_counts, "l1_events_deleted": l1_deleted}


@memory_router.post("/forget/time-range")
async def forget_time_range(body: ForgetTimeRangeRequest):
    """Cascade forget: invalidate L2 records inferred during a time range."""
    if body.end <= body.start:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="end must be greater than start")

    unified_memory = _resolve_unified_memory()
    if not unified_memory or not unified_memory.l2:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="L2 store not initialized")

    l2_counts = await unified_memory.l2.forget_time_range(start=body.start, end=body.end)

    l1_deleted = 0
    if body.delete_l1_events and unified_memory.l1 is not None:
        events = await unified_memory.l1.query_events(start_time=body.start, end_time=body.end, limit=10000)
        for ev in events:
            eid = ev.get("event_id") or ev.get("id")
            if eid and await unified_memory.l1.mark_deleted(str(eid)):
                l1_deleted += 1

    return {"l2_counts": l2_counts, "l1_events_deleted": l1_deleted}


@memory_router.post("/forget/episode")
async def forget_episode(body: ForgetEpisodeRequest):
    """Invalidate a specific episode and optionally its member events."""
    unified_memory = _resolve_unified_memory()
    if not unified_memory or not unified_memory.l2:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="L2 store not initialized")

    result = await unified_memory.l2.forget_episode(
        episode_id=body.episode_id,
        delete_events=body.delete_events,
    )
    if result is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Episode not found")

    l1_deleted = 0
    if body.delete_events and unified_memory.l1 is not None:
        for eid in result.get("event_ids", []):
            if await unified_memory.l1.mark_deleted(eid):
                l1_deleted += 1

    return {**result, "l1_events_deleted": l1_deleted}
