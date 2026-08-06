"""Benchmark/evaluation memory API routes."""

from __future__ import annotations

from dataclasses import asdict
import time
from typing import Any, Dict

from fastapi import HTTPException, status

from magi.config.models import LLMScenario, ThinkingDepth
from magi.llm import LLMProviderBridge
from magi.memory.eval_support.contracts import EvalMemoryQuery, EvalMemoryWriteRecord
from magi.memory.eval_support.reader import EvalMemoryReader
from magi.memory.eval_support.writer import EvalMemoryWriter
from magi.utils.diagnostic_logging import full_content_logging_enabled

from ..dependencies import (
    _resolve_hybrid_retrieval_service,
    _resolve_scenario_llm_pool,
    _resolve_unified_memory,
    _synthesize_eval_answer,
    logger,
)
from ..helpers import memory_t
from ..router import memory_router
from ..schemas import (
    EvalFinalizeReplayRequest,
    EvalJudgeAnswerRequest,
    EvalQueryRequest,
    EvalReplayRequest,
)


@memory_router.post("/eval/replay")
async def replay_eval_records(body: EvalReplayRequest):
    """Replay benchmark records through the standard memory ingest path."""
    unified_memory = _resolve_unified_memory()
    if not unified_memory:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=memory_t("memory.errors.system_uninitialized", "Memory system not initialized"),
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
            detail=memory_t(
                "memory.errors.hybrid_retrieval_uninitialized",
                "Hybrid retrieval service not initialized",
            ),
        )

    unified_memory = _resolve_unified_memory()
    reader = EvalMemoryReader(
        retrieval_service,
        l1_store=getattr(unified_memory, "l1", None) if unified_memory is not None else None,
    )
    query_fields = (
        {"query": body.query}
        if full_content_logging_enabled()
        else {"query_chars": len(body.query)}
    )
    logger.info(
        "Eval memory query started",
        namespace=body.namespace,
        mode=body.mode,
        top_k=body.top_k,
        answer_with_llm=body.answer_with_llm,
        **query_fields,
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
            l2_experiences=list(result.l2_experiences),
            query_timestamp=body.query_timestamp,
            show_prompt=body.show_prompt,
        )
        result.answer = answer
        result.answer_trace = answer_trace
    return asdict(result)


@memory_router.post("/eval/judge-answer")
async def judge_eval_answer(body: EvalJudgeAnswerRequest):
    """Run a benchmark judge prompt through the runtime core LLM."""
    resolved_llm_pool = _resolve_scenario_llm_pool()
    if resolved_llm_pool is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=memory_t(
                "memory.errors.scenario_llm_pool_uninitialized",
                "Scenario LLM pool is not initialized",
            ),
        )

    adapter = resolved_llm_pool.get(LLMScenario.CORE)
    bridge = LLMProviderBridge(adapter)
    content = await bridge.chat(
        system_prompt=body.system_prompt,
        messages=[{"role": "user", "content": body.prompt}],
        max_tokens=body.max_tokens,
        temperature=body.temperature,
        json_mode=True,
        thinking_depth=ThinkingDepth.NONE,
        timeout_seconds=body.timeout_seconds,
        event_context={
            "request_kind": "eval:llm_judge",
            "agent_id": "memory_eval",
        },
    )
    return {
        "content": str(content or ""),
        "llm_scenario": LLMScenario.CORE.value,
        "model": str(
            getattr(adapter, "model_name", None) or getattr(adapter, "model", None) or "magi-core"
        ),
    }


@memory_router.post("/eval/finalize-replay")
async def finalize_eval_replay(body: EvalFinalizeReplayRequest):
    """Run post-replay summary generation and expose L2 pipeline status."""
    unified_memory = _resolve_unified_memory()
    if not unified_memory:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=memory_t("memory.errors.system_uninitialized", "Memory system not initialized"),
        )

    l2_projection_batch_count = 0
    if body.flush_l2_projection_jobs and hasattr(
        unified_memory, "flush_l2_projection_jobs"
    ):
        l2_projection_batch_count = await unified_memory.flush_l2_projection_jobs()

    l2_edge_embedding_count = 0
    if body.drain_l2_edge_embeddings and hasattr(unified_memory, "drain_l2_edge_embeddings"):
        l2_edge_embedding_count = await unified_memory.drain_l2_edge_embeddings()

    summaries: Dict[str, Any] = {}
    if body.generate_summaries:
        for period_type in body.period_types:
            summaries[period_type] = await unified_memory.generate_summary(period_type=period_type)

    l2_pipeline_stats = (
        dict(unified_memory.get_l2_pipeline_stats())
        if hasattr(unified_memory, "get_l2_pipeline_stats")
        else {}
    )
    if hasattr(unified_memory, "get_l2_projection_backlog"):
        l2_pipeline_stats["projection_backlog"] = await unified_memory.get_l2_projection_backlog()
    return {
        "summaries": summaries,
        "l2_projection_batch_count": int(l2_projection_batch_count or 0),
        "l2_edge_embedding_count": int(l2_edge_embedding_count or 0),
        "l2_pipeline_stats": l2_pipeline_stats,
    }
