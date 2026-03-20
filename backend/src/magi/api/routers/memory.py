"""Memory API for the rewritten L0-L4 memory system."""

from __future__ import annotations

from dataclasses import asdict
from typing import Any, Dict, List, Literal, Optional

from fastapi import APIRouter, HTTPException, Query, status
from pydantic import BaseModel, Field, field_validator

from ..services import get_chat_read_service
from ...config.models import LLMScenario
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
from ...memory.event_contracts import MemoryEvent
from ...memory.hybrid_retrieval import build_query
from ...memory.l2.models import ManualL2EventRequest

logger = get_logger(__name__)

memory_router = APIRouter()


class RetrievalRequest(BaseModel):
    query: str = Field(..., description="Search text")
    query_mode: str = Field(default="detail", description="detail|summary|experience|graph|strategy")
    time_range: Dict[str, Any] = Field(default_factory=dict)
    source_filters: List[str] = Field(default_factory=list)
    domain_filters: List[str] = Field(default_factory=list)
    user_id: Optional[str] = None
    session_id: Optional[str] = None
    limit: int = Field(default=10, ge=1, le=200)


class ProcedureResponse(BaseModel):
    skill_id: str
    skill_name: str
    skill_category: str
    success_rate: float
    total_attempts: int
    circuit_breaker_state: str


class ManualL2EventBody(BaseModel):
    text: str = Field(..., description="Manual event text")
    user_id: str = Field(..., description="User id for the synthetic event")
    session_id: Optional[str] = Field(default=None, description="Optional session id")
    source: str = Field(default="l2_lab", description="Synthetic event source label")
    entity_focus_hint: Optional[str] = Field(default=None, description="Optional focus entity id")


class EvalReplayRecordBody(BaseModel):
    namespace: str = Field(..., description="Benchmark namespace")
    session_id: str = Field(..., description="Replay session id")
    timestamp: float = Field(..., description="Replay timestamp")
    role: str = Field(..., description="Replay speaker role")
    content: str = Field(..., description="Replay text content")
    turn_id: Optional[str] = Field(default=None, description="Optional replay turn id")
    metadata: Dict[str, Any] = Field(default_factory=dict, description="Optional replay metadata")


class EvalReplayRequest(BaseModel):
    namespace: str = Field(..., description="Benchmark namespace")
    records: List[EvalReplayRecordBody] = Field(default_factory=list, description="Replay records")


class EvalQueryRequest(BaseModel):
    namespace: str = Field(..., description="Benchmark namespace")
    query: str = Field(..., description="Benchmark memory query")
    query_timestamp: Optional[float] = Field(default=None, description="Optional query timestamp")
    top_k: int = Field(default=10, ge=1, le=200, description="Top-k retrieval limit")
    mode: str = Field(default="auto", description="Retrieval mode hint")
    answer_with_llm: bool = Field(default=False, description="Whether to synthesize a final answer with the runtime LLM")


class EvalFinalizeReplayRequest(BaseModel):
    period_types: List[str] = Field(
        default_factory=lambda: ["hour", "day", "week", "month"],
        description="Temporal summary categories to generate after replay",
    )


class L2EntityActionBody(BaseModel):
    entity_ids: List[str] = Field(..., description="Canonical entity ids")


class GraphConflictRuleBody(BaseModel):
    opposite_predicates: List[str] = Field(default_factory=list, description="Predicates that conflict as logical opposites")
    opposite_resolution: Literal["mark_deprecated", "mark_conflicted"] = Field(default="mark_deprecated", description="mark_deprecated|mark_conflicted")
    exclusive_group: Optional[str] = Field(default=None, description="Optional mutual-exclusion group")
    exclusive_scope: Literal["same_subject"] = Field(default="same_subject", description="Conflict scope")
    exclusive_resolution: Literal["mark_deprecated", "mark_conflicted"] = Field(default="mark_deprecated", description="mark_deprecated|mark_conflicted")

    @field_validator("opposite_predicates", mode="before")
    @classmethod
    def _normalize_opposites(cls, value: Any) -> List[str]:
        if value is None:
            return []
        if not isinstance(value, list):
            raise ValueError("opposite_predicates must be a list of strings")
        return [str(item).strip() for item in value if str(item).strip()]

    @field_validator("exclusive_group", mode="before")
    @classmethod
    def _normalize_exclusive_group(cls, value: Any) -> Optional[str]:
        if value is None:
            return None
        text = str(value).strip()
        return text or None


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


def _build_clear_result(count: int) -> Dict[str, Any]:
    return {
        "cleared": True,
        "count": int(count),
    }


async def _synthesize_eval_answer(
    *,
    question: str,
    hits: list[dict[str, Any]],
) -> tuple[str, dict[str, Any]]:
    llm_pool = _resolve_scenario_llm_pool()
    if llm_pool is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Scenario LLM pool is not initialized",
        )

    adapter = llm_pool.get(LLMScenario.CORE)
    evidence_blocks: list[str] = []
    for index, hit in enumerate(hits, start=1):
        content = str(hit.get("content") or "").strip()
        if not content:
            continue
        session_id = str(hit.get("session_id") or "").strip() or "unknown-session"
        turn_id = str(hit.get("turn_id") or "").strip() or "unknown-turn"
        evidence_blocks.append(f"[{index}] session={session_id} turn={turn_id}\n{content}")

    evidence_text = "\n\n".join(evidence_blocks) if evidence_blocks else "(no evidence retrieved)"
    logger.info(
        "Eval query answer synthesis started",
        question=question,
        evidence_hit_count=len(hits),
        evidence_preview=evidence_text[:800],
    )
    prompt = (
        "You are answering a benchmark question using retrieved memory evidence only.\n"
        "Return a concise final answer to the question.\n"
        "If the evidence is insufficient, answer exactly: unknown\n\n"
        f"Question:\n{question}\n\n"
        f"Retrieved Evidence:\n{evidence_text}\n"
    )
    answer = await adapter.chat(
        [{"role": "user", "content": prompt}],
        max_tokens=128,
        temperature=0.0,
    )
    normalized_answer = str(answer or "").strip() or "unknown"
    logger.info(
        "Eval query answer synthesis completed",
        question=question,
        evidence_hit_count=len(hits),
        answer=normalized_answer,
    )
    return normalized_answer, {
        "answer_source": "llm",
        "llm_scenario": LLMScenario.CORE.value,
        "evidence_hit_count": len(hits),
    }


def _build_l2_pending_breakdown(pipeline_stats: Dict[str, Any]) -> Dict[str, int]:
    return {
        "extract_pending": max(
            int(pipeline_stats.get("extract_enqueued", 0))
            - int(pipeline_stats.get("extract_completed", 0))
            - int(pipeline_stats.get("extract_failed", 0))
            - int(pipeline_stats.get("extract_skipped", 0)),
            0,
        ),
        "reconcile_pending": max(
            int(pipeline_stats.get("reconcile_enqueued", 0))
            - int(pipeline_stats.get("reconcile_completed", 0))
            - int(pipeline_stats.get("reconcile_failed", 0)),
            0,
        ),
        "snapshot_pending": max(
            int(pipeline_stats.get("snapshot_enqueued", 0))
            - int(pipeline_stats.get("snapshot_completed", 0))
            - int(pipeline_stats.get("snapshot_failed", 0)),
            0,
        ),
    }


def _serialize_memory_event(event: MemoryEvent | Dict[str, Any]) -> Dict[str, Any]:
    if isinstance(event, MemoryEvent):
        return event.to_dict()
    return dict(event)


# =============================================================================
# L0 Working Memory Endpoints
# =============================================================================

@memory_router.get("/l0/sessions")
async def list_l0_sessions():
    """List all active L0 sessions with stats."""
    unified_memory = _resolve_unified_memory()
    if not unified_memory or not unified_memory.l0:
        return {"sessions": [], "stats": {"active_sessions": 0, "total_goals": 0, "total_entities": 0, "total_tactics": 0}}

    sessions = []
    total_goals = 0
    total_entities = 0
    total_tactics = 0

    for session_id, session in unified_memory.l0._sessions.items():
        goals = unified_memory.l0._goal_stack.get(session_id, [])
        entities = unified_memory.l0._active_entities.get(session_id, {})
        tactics = unified_memory.l0._temporary_tactics.get(session_id, {})
        total_goals += len(goals)
        total_entities += len(entities)
        total_tactics += len(tactics)

        sessions.append({
            "session_id": session_id,
            "user_id": session.get("user_id"),
            "status": session.get("status"),
            "started_at": session.get("started_at"),
            "last_active_at": session.get("last_active_at"),
            "goal_count": len(goals),
            "entity_count": len(entities),
            "tactic_count": len(tactics),
        })

    return {
        "sessions": sessions,
        "stats": {
            "active_sessions": len([s for s in sessions if s["status"] == "active"]),
            "total_goals": total_goals,
            "total_entities": total_entities,
            "total_tactics": total_tactics,
        },
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
        return {
            "is_running": False,
            "relation_count": 0,
            "assertion_count": 0,
            "extract_enqueued": 0,
            "extract_completed": 0,
            "extract_failed": 0,
            "extract_skipped": 0,
            "reconcile_enqueued": 0,
            "reconcile_completed": 0,
            "reconcile_failed": 0,
            "snapshot_enqueued": 0,
            "snapshot_completed": 0,
            "snapshot_failed": 0,
            "relations_written": 0,
            "assertions_written": 0,
            "extract_by_evidence_class": {},
            "skip_by_reason": {},
            "db_path": None,
        }

    relations = await unified_memory.l2.get_relationships(limit=10000)
    assertions = await unified_memory.l2.list_tom_assertions(limit=10000)
    pipeline_stats = unified_memory.get_l2_pipeline_stats() if hasattr(unified_memory, "get_l2_pipeline_stats") else {}
    return {
        "is_running": bool(pipeline_stats.get("is_running", False)),
        "relation_count": len(relations),
        "assertion_count": len(assertions),
        "extract_enqueued": int(pipeline_stats.get("extract_enqueued", 0)),
        "extract_completed": int(pipeline_stats.get("extract_completed", 0)),
        "extract_failed": int(pipeline_stats.get("extract_failed", 0)),
        "extract_skipped": int(pipeline_stats.get("extract_skipped", 0)),
        "reconcile_enqueued": int(pipeline_stats.get("reconcile_enqueued", 0)),
        "reconcile_completed": int(pipeline_stats.get("reconcile_completed", 0)),
        "reconcile_failed": int(pipeline_stats.get("reconcile_failed", 0)),
        "snapshot_enqueued": int(pipeline_stats.get("snapshot_enqueued", 0)),
        "snapshot_completed": int(pipeline_stats.get("snapshot_completed", 0)),
        "snapshot_failed": int(pipeline_stats.get("snapshot_failed", 0)),
        "relations_written": int(pipeline_stats.get("relations_written", 0)),
        "assertions_written": int(pipeline_stats.get("assertions_written", 0)),
        "extract_by_evidence_class": dict(pipeline_stats.get("extract_by_evidence_class", {})),
        "skip_by_reason": dict(pipeline_stats.get("skip_by_reason", {})),
        "db_path": unified_memory.l2.db_path,
    }


@memory_router.get("/l2/pending")
async def get_l2_pending():
    """Get calculated L2 queue backlog for quick polling."""
    unified_memory = _resolve_unified_memory()
    if not unified_memory or not unified_memory.l2:
        return {
            "is_running": False,
            "extract_pending": 0,
            "reconcile_pending": 0,
            "snapshot_pending": 0,
        }

    pipeline_stats = unified_memory.get_l2_pipeline_stats() if hasattr(unified_memory, "get_l2_pipeline_stats") else {}
    pending = _build_l2_pending_breakdown(pipeline_stats)
    return {
        "is_running": bool(pipeline_stats.get("is_running", False)),
        **pending,
    }
@memory_router.get("/l2/relations")
async def list_l2_relations(limit: int = Query(default=100, ge=1, le=500)):
    """List knowledge graph relations."""
    unified_memory = _resolve_unified_memory()
    if not unified_memory or not unified_memory.l2:
        return []
    return await unified_memory.l2.get_relationships(limit=limit)


@memory_router.get("/l2/assertions")
async def list_l2_assertions(limit: int = Query(default=100, ge=1, le=500)):
    """List ToM trait assertions."""
    unified_memory = _resolve_unified_memory()
    if not unified_memory or not unified_memory.l2:
        return []
    return await unified_memory.l2.list_tom_assertions(limit=limit)


@memory_router.get("/l2/entities")
async def list_l2_entities(limit: int = Query(default=100, ge=1, le=500)):
    """List canonical L2 entities for the frontend lab picker."""
    unified_memory = _resolve_unified_memory()
    if not unified_memory or not unified_memory.l2_entity_catalog:
        return []
    return await unified_memory.l2_entity_catalog.list_entities(limit=limit)


@memory_router.get("/l2/mentions")
async def list_l2_mentions(limit: int = Query(default=100, ge=1, le=500)):
    """List recent entity mentions and their resolution state."""
    unified_memory = _resolve_unified_memory()
    if not unified_memory or not unified_memory.l2_entity_catalog:
        return []
    return await unified_memory.l2_entity_catalog.list_mentions(limit=limit)


@memory_router.get("/l2/snapshots")
async def list_l2_snapshots(limit: int = Query(default=100, ge=1, le=500)):
    """List materialized L2 snapshots."""
    unified_memory = _resolve_unified_memory()
    if not unified_memory or not unified_memory.l2:
        return []
    return await unified_memory.l2.list_tom_snapshots(limit=limit)


@memory_router.get("/l2/conflict-rules")
async def list_l2_conflict_rules():
    """List persisted graph conflict rules."""
    unified_memory = _resolve_unified_memory()
    if not unified_memory or not unified_memory.l2:
        return []
    return await unified_memory.l2.list_graph_conflict_rules()


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

    reader = EvalMemoryReader(retrieval_service)
    result = await reader.query_memory(
        EvalMemoryQuery(
            namespace=body.namespace,
            query=body.query,
            query_timestamp=body.query_timestamp,
            top_k=body.top_k,
            mode=body.mode,
            answer_with_llm=body.answer_with_llm,
        )
    )
    if body.answer_with_llm:
        answer, answer_trace = await _synthesize_eval_answer(
            question=body.query,
            hits=[asdict(hit) for hit in result.hits],
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


# =============================================================================
# L3 Reflection Endpoints
# =============================================================================

@memory_router.get("/l3/summaries")
async def list_l3_summaries(
    limit: int = Query(default=100, ge=1, le=500),
    summary_type: Optional[str] = Query(default=None, description="Filter by type: temporal, thematic, insight"),
    summary_category: Optional[str] = Query(default=None, description="Filter by category: topic, task_reflection, state_change, trend_shift, etc."),
):
    """List L3 reflection summaries."""
    unified_memory = _resolve_unified_memory()
    if not unified_memory or not unified_memory.l3:
        return []

    summaries = await unified_memory.l3.list_summaries(limit=limit)
    if summary_type:
        summaries = [s for s in summaries if s.get("summary_type") == summary_type]
    if summary_category:
        summaries = [s for s in summaries if s.get("summary_category") == summary_category]
    return summaries


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

    stats: Dict[str, Any] = {}

    # L0 statistics
    if unified_memory.l0:
        sessions = unified_memory.l0._sessions
        total_goals = sum(len(unified_memory.l0._goal_stack.get(sid, [])) for sid in sessions)
        total_entities = sum(len(unified_memory.l0._active_entities.get(sid, {})) for sid in sessions)
        total_tactics = sum(len(unified_memory.l0._temporary_tactics.get(sid, {})) for sid in sessions)
        stats["l0"] = {
            "active_sessions": len([s for s in sessions.values() if s.get("status") == "active"]),
            "total_goals": total_goals,
            "total_entities": total_entities,
            "total_tactics": total_tactics,
            "db_path": unified_memory.l0.checkpoint_db_path,
        }
    else:
        stats["l0"] = {"active_sessions": 0, "total_goals": 0, "total_entities": 0, "total_tactics": 0}

    # L1 statistics
    if unified_memory.l1:
        stats["l1"] = {
            "event_count": await unified_memory.l1.count_events(),
            "db_path": unified_memory.l1.db_path,
        }
    else:
        stats["l1"] = {"event_count": 0}

    # L2 statistics
    if unified_memory.l2:
        relations = await unified_memory.l2.get_relationships(limit=10000)
        assertions = await unified_memory.l2.list_tom_assertions(limit=10000)
        stats["l2"] = {
            "relation_count": len(relations),
            "assertion_count": len(assertions),
            "db_path": unified_memory.l2.db_path,
        }
    else:
        stats["l2"] = {"relation_count": 0, "assertion_count": 0}

    # L3 statistics
    if unified_memory.l3:
        summaries = await unified_memory.l3.list_summaries(limit=10000)
        stats["l3"] = {
            "summary_count": len(summaries),
            "db_path": unified_memory.l3.db_path,
        }
    else:
        stats["l3"] = {"summary_count": 0}

    # L4 statistics
    if unified_memory.l4:
        skills = await unified_memory.l4.get_all_skills(limit=10000)
        open_breakers = sum(1 for s in skills if s.get("circuit_breaker_state") != "closed")
        stats["l4"] = {
            "skill_count": len(skills),
            "open_circuit_breakers": open_breakers,
            "db_path": unified_memory.l4.db_path,
        }
    else:
        stats["l4"] = {"skill_count": 0, "open_circuit_breakers": 0}

    if memory_integration:
        stats["integration"] = memory_integration.get_statistics()

    return stats


@memory_router.delete("/clear")
async def clear_memory_layers():
    """Clear all memory layers and chat session mappings."""
    unified_memory = _resolve_unified_memory()
    if not unified_memory:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Memory system not initialized",
        )

    l0_count = await unified_memory.l0.clear() if getattr(unified_memory, "l0", None) else 0
    l1_count = await unified_memory.l1.clear() if getattr(unified_memory, "l1", None) else 0
    l2_count = await unified_memory.l2.clear() if getattr(unified_memory, "l2", None) else 0
    if getattr(unified_memory, "l2_entity_catalog", None):
        l2_count += await unified_memory.l2_entity_catalog.clear()
    l3_count = await unified_memory.l3.clear() if getattr(unified_memory, "l3", None) else 0
    l4_count = await unified_memory.l4.clear() if getattr(unified_memory, "l4", None) else 0
    chat_context_count = get_chat_read_service().clear_all_sessions()

    return {
        "success": True,
        "results": {
            "l0": _build_clear_result(l0_count),
            "l1": _build_clear_result(l1_count),
            "l2": _build_clear_result(l2_count),
            "l3": _build_clear_result(l3_count),
            "l4": _build_clear_result(l4_count),
            "chat_context": _build_clear_result(chat_context_count),
        },
    }


@memory_router.get("/l1/events")
async def get_l1_events(
    limit: int = Query(default=50, ge=1, le=500),
    event_type: Optional[str] = Query(default=None),
    user_id: Optional[str] = Query(default=None),
    session_id: Optional[str] = Query(default=None),
):
    unified_memory = _resolve_unified_memory()
    if not unified_memory or not unified_memory.l1:
        return {"events": [], "stats": {"total": 0}}

    events = await unified_memory.l1.query_events(
        session_id=session_id,
        user_id=user_id,
        event_type=event_type,
        limit=limit,
    )
    total = await unified_memory.l1.count_events()
    return {"events": [_serialize_memory_event(event) for event in events], "stats": {"total": total}}


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


@memory_router.get("/procedures", response_model=List[ProcedureResponse])
async def list_procedures(limit: int = Query(default=100, ge=1, le=500)):
    unified_memory = _resolve_unified_memory()
    if not unified_memory or not unified_memory.l4:
        return []

    procedures = await unified_memory.l4.get_all_skills(limit=limit)
    return [
        ProcedureResponse(
            skill_id=str(item["skill_id"]),
            skill_name=str(item["skill_name"]),
            skill_category=str(item["skill_category"]),
            success_rate=float(item["success_rate"]),
            total_attempts=int(item["total_attempts"]),
            circuit_breaker_state=str(item["circuit_breaker_state"]),
        )
        for item in procedures
    ]


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
