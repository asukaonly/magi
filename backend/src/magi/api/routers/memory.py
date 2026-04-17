"""Memory API for the rewritten L0-L4 memory system."""

from __future__ import annotations

import asyncio
from dataclasses import asdict
from datetime import date, datetime, time as datetime_time, timezone
import re
import time
from typing import Any, Dict, List, Literal, Optional

from fastapi import APIRouter, HTTPException, Query, status
from pydantic import BaseModel, Field, field_validator

from ...chat import get_chat_read_service
from ...config.models import LLMScenario, ThinkingDepth
from ...core.logger import get_logger
from ...llm import LLMProviderBridge
from ...core.runtime_bindings import (
    require_hybrid_retrieval_service,
    require_memory_integration,
    require_scenario_llm_pool,
    require_unified_memory,
)
from ...memory.eval_support.answer_normalization import (
    normalize_eval_answer,
)
from ...memory.eval_support.contracts import EvalMemoryQuery, EvalMemoryWriteRecord
from ...memory.eval_support.reader import EvalMemoryReader
from ...memory.eval_support.writer import EvalMemoryWriter
from ...memory.event_contracts import MemoryEvent
from ...memory.hybrid_retrieval import build_query
from ...memory.answering import (
    build_answer_prompt_payload,
)
from ...memory.l2.models import ManualL2EventRequest
from ...runtime_defaults import DEFAULT_USER_ID

logger = get_logger(__name__)

memory_router = APIRouter()


def _short_session_id(session_id: str) -> str:
    normalized = str(session_id or "").strip()
    if not normalized:
        return ""
    if "-" in normalized:
        return normalized.split("-", 1)[0]
    return normalized[:8]


def _truncate_session_preview(value: str, *, limit: int = 72) -> str:
    text = re.sub(r"\s+", " ", str(value or "").strip())
    if len(text) <= limit:
        return text
    return f"{text[: limit - 1].rstrip()}..."


def _is_generic_chat_title(value: str) -> bool:
    normalized = str(value or "").strip().lower()
    return normalized in {"", "new chat", "新对话"}


def _derive_l0_session_display(
    *,
    session_id: str,
    goals: list[dict[str, Any]],
    chat_summary: Any = None,
) -> dict[str, str | None]:
    short_session_id = _short_session_id(session_id)
    goal_title = ""
    if goals:
        first_goal = goals[0]
        goal_title = _truncate_session_preview(str(first_goal.get("description") or first_goal.get("goal_id") or ""))

    chat_title = _truncate_session_preview(str(getattr(chat_summary, "title", "") or ""))
    user_preview = _truncate_session_preview(str(getattr(chat_summary, "last_user_message_preview", "") or ""))
    last_preview = _truncate_session_preview(str(getattr(chat_summary, "last_message_preview", "") or ""))
    workspace_path = str(getattr(chat_summary, "workspace_path", "") or "").strip()
    workspace_name = workspace_path.rstrip("/").split("/")[-1] if workspace_path else ""

    display_title = (
        (chat_title if not _is_generic_chat_title(chat_title) else "")
        or goal_title
        or user_preview
        or last_preview
        or short_session_id
        or session_id
    )

    display_subtitle = None
    for candidate in (user_preview, last_preview, workspace_name):
        if candidate and candidate != display_title:
            display_subtitle = candidate
            break

    return {
        "short_session_id": short_session_id or session_id,
        "display_title": display_title,
        "display_subtitle": display_subtitle,
    }


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
    mode: str = Field(default="auto", description="Retrieval mode hint, including l1_only for debug-only L1 reads")
    answer_with_llm: bool = Field(default=False, description="Whether to synthesize a final answer with the runtime LLM")
    show_prompt: bool = Field(default=False, description="Whether to include the synthesized LLM prompt in debug output")


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


def _canonical_self_id(unified_memory: Any) -> str:
    resolver = getattr(unified_memory, "identity_resolver", None)
    if resolver is None:
        return "user:self"
    return str(getattr(resolver, "default_memory_owner_id", "user:self"))


def _build_clear_result(count: int) -> Dict[str, Any]:
    return {
        "cleared": True,
        "count": int(count),
    }


def _format_l2_context(
    *,
    entity_cards: list[dict[str, Any]] | None = None,
    relationships: list[dict[str, Any]] | None = None,
    assertions: list[dict[str, Any]] | None = None,
) -> str:
    """Format L2 knowledge graph data as LLM-readable context."""
    blocks: list[str] = []
    for rel in (relationships or []):
        summary = str(rel.get("natural_summary") or rel.get("evidence_text") or "").strip()
        if not summary:
            subj = str(rel.get("subject_id") or "")
            pred = str(rel.get("predicate") or "")
            obj = str(rel.get("object_id") or "")
            summary = f"{subj} {pred} {obj}"
        blocks.append(f"- [relationship] {summary}")
    for card in (entity_cards or []):
        entity_id = str(card.get("entity_id") or "")
        summary = str(card.get("summary") or card.get("snapshot") or "").strip()
        if summary:
            blocks.append(f"- [entity] {entity_id}: {summary}")
    for a in (assertions or []):
        text = str(a.get("assertion_text") or a.get("value") or "").strip()
        if text:
            blocks.append(f"- [assertion] {text}")
    return "\n".join(blocks) if blocks else "(no knowledge graph context)"


def _is_counting_or_aggregation_question(question: str) -> bool:
    """Detect questions that require multi-step counting, aggregation, or temporal math."""
    lowered = str(question or "").lower()
    return bool(re.search(
        r"\bhow many\b|\btotal\b|\bcombined\b|\ball together\b|\bsum\b|\baverage\b|\bhow old\b|\bhow long\b|\bhow much faster\b|\bhow much older\b",
        lowered,
    ))


def _is_temporal_reasoning_question(question: str) -> bool:
    """Detect questions that benefit from step-by-step temporal reasoning."""
    lowered = str(question or "").lower()
    return bool(re.search(
        r"\bhow many days\b|\bhow many weeks\b|\bhow many months\b|\bhow long ago\b|"
        r"\bdays? ago\b|\bweeks? ago\b|\bmonths? ago\b|\byears? ago\b|"
        r"\bmost recent\b|\bhappened first\b|\bwhich came first\b|"
        r"\bwhat day\b|\bwhat date\b|\bbefore or after\b|"
        r"\bfirst\b.{1,30}\bor\b.{1,30}\b(?:last|later|second)\b|"
        r"\blast\b.{1,30}\btime\b.{1,30}\b(?:did|was|were)\b",
        lowered,
    ))


_EVAL_ANSWER_TIMEOUT = 300  # 5 minutes — generous for thinking-enabled models


async def _synthesize_eval_answer(
    *,
    question: str,
    hits: list[dict[str, Any]],
    evidence_bundles: list[dict[str, Any]] | None = None,
    timeline_summary: list[dict[str, Any]] | None = None,
    l2_entity_cards: list[dict[str, Any]] | None = None,
    l2_relationships: list[dict[str, Any]] | None = None,
    l2_assertions: list[dict[str, Any]] | None = None,
    query_timestamp: float | None = None,
    show_prompt: bool = False,
) -> tuple[str, dict[str, Any]]:
    llm_pool = _resolve_scenario_llm_pool()
    if llm_pool is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Scenario LLM pool is not initialized",
        )

    adapter = llm_pool.get(LLMScenario.CORE)
    bridge = LLMProviderBridge(adapter)
    prompt_payload = build_answer_prompt_payload(
        question=question,
        hits=hits,
        evidence_bundles=evidence_bundles,
        timeline_summary=timeline_summary,
    )
    system_prompt = (
        "You are answering a question using retrieved memory evidence only.\n"
        "Return a concise final answer to the question.\n"
        "Return only the final answer span with no explanation.\n"
        "Prefer a short phrase copied or closely paraphrased from the evidence.\n"
        "When asked about order, count, duration, or time difference, reason over timestamps and content to derive the answer.\n"
        "For recency or ordering questions, rely on the Timeline Summary chronological order — "
        "do NOT judge recency by how much a topic is discussed in the evidence bundles.\n"
        "When asked 'how many' or 'total', enumerate EVERY relevant item from ALL bundles, timeline entries, and evidence, then sum to get the final count. "
        "Only count items that EXACTLY match the question criteria; do NOT count similar but different items. "
        "Ignore items mentioned in unrelated topics or different contexts. If an item is mentioned multiple times across bundles, count it only ONCE.\n"
        "When asked about 'X ago' or relative dates ('last Tuesday'), compute the delta between the event timestamp and the question date.\n"
        "IMPORTANT: If the question specifies a different reference point (e.g. 'when I did Y', 'at the time of Y', 'since I started X'), "
        "compute the delta relative to THAT event's date, NOT the question date. "
        "Example: 'How many days ago did I launch my website when I signed a contract?' — find the website-launch date and "
        "the contract-signing date, then compute (contract date minus launch date).\n"
        "When evidence spans multiple bundles, cross-reference and aggregate information across all of them.\n"
        "Look for answers in BOTH user messages AND assistant responses within the evidence.\n"
        "If the question asks about a specific detail (name, place, date, amount), check assistant replies — they often restate or confirm the user's information.\n"
        "\n"
        "ENTITY VERIFICATION:\n"
        "If the question asks about a SPECIFIC named entity and NO evidence mentions that entity "
        "or a clearly equivalent variant, answer 'unknown'. "
        "Do NOT substitute a genuinely DIFFERENT entity (e.g. do not answer about 'Dr. Smith' when asked about 'Dr. Johnson'). "
        "However, treat minor wording differences as matches (e.g. 'University of Melbourne' matches 'University of Melbourne in Australia'; "
        "'Spotify' matches 'a Spotify subscription'). When in doubt, prefer giving an answer over returning 'unknown'.\n"
        "\n"
        "CURRENT STATE (knowledge-update) questions:\n"
        "When the question asks about a current/present state ('where do I currently keep', 'how long have I been', "
        "'how many do I have now', 'what is my current'), use the value from the MOST RECENT evidence only. "
        "Do NOT sum or accumulate values across multiple time periods. "
        "If something was updated or changed over time, report only the latest value.\n"
        "\n"
        "Attempt an answer whenever the evidence provides any relevant clues, even if incomplete or indirect.\n"
        "Scan ALL evidence sections thoroughly — answers may appear in any bundle, timeline entry, or assistant reply.\n"
        "For recommendation or suggestion questions, ANY evidence about the user's interests, tools, past choices, "
        "or stated preferences is sufficient to generate a personalized answer. "
        "Do NOT answer 'unknown' for recommendation questions when you have any user context.\n"
        "BEFORE answering 'unknown', re-read EVERY bundle and timeline entry once more. "
        "Check if any user message or assistant reply contains words related to the question topic. "
        "If you find ANY mention — even indirect — attempt an answer based on that evidence.\n"
        "Answer exactly 'unknown' only as a last resort when no piece of evidence mentions anything related to the question topic."
    )
    l2_context_text = _format_l2_context(
        entity_cards=l2_entity_cards,
        relationships=l2_relationships,
        assertions=l2_assertions,
    )
    question_date_line = ""
    if query_timestamp is not None:
        qdt = datetime.fromtimestamp(query_timestamp, tz=timezone.utc)
        question_date_line = f"Question date: {qdt.strftime('%Y-%m-%d (%a) %H:%M')} UTC (timestamp={query_timestamp})\n"

    # For temporal questions, place Timeline Summary AFTER bundles so the LLM
    # reads it last (mitigates lost-in-the-middle attention decay).
    if prompt_payload.prioritize_timeline:
        user_prompt = (
            "Use relative time expressions in the evidence when comparing event order.\n"
            "Do not rely only on replay timestamps if the content itself gives a clearer time relation.\n\n"
            f"{prompt_payload.timeline_instruction}"
            f"{prompt_payload.preference_instruction}"
            f"{question_date_line}"
            f"Question:\n{question}\n\n"
            f"Session Evidence Bundles:\n{prompt_payload.bundle_text}\n\n"
            f"Retrieved Evidence:\n{prompt_payload.evidence_text}\n\n"
            f"Knowledge Graph Context:\n{l2_context_text}\n\n"
            f"Timeline Summary (use this for temporal/ordering questions):\n{prompt_payload.timeline_text}\n"
        )
    else:
        user_prompt = (
            "Use relative time expressions in the evidence when comparing event order.\n"
            "Do not rely only on replay timestamps if the content itself gives a clearer time relation.\n\n"
            f"{prompt_payload.timeline_instruction}"
            f"{prompt_payload.preference_instruction}"
            f"{question_date_line}"
            f"Question:\n{question}\n\n"
            f"Timeline Summary:\n{prompt_payload.timeline_text}\n\n"
            f"Session Evidence Bundles:\n{prompt_payload.bundle_text}\n\n"
            f"Retrieved Evidence:\n{prompt_payload.evidence_text}\n\n"
            f"Knowledge Graph Context:\n{l2_context_text}\n"
        )
    llm_messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_prompt},
    ]
    logger.info(
        "Eval query answer synthesis started",
        question=question,
        evidence_hit_count=len(hits),
        evidence_bundle_count=len(evidence_bundles or []),
        evidence_preview=prompt_payload.evidence_text[:800],
        llm_messages=(
            "==== SYSTEM MESSAGE ====\n"
            f"{system_prompt}\n"
            "==== USER MESSAGE ====\n"
            f"{user_prompt}\n"
            "==== END ANSWER LLM INPUT ===="
        ),
    )
    raw_answer = await bridge.chat(
        system_prompt=system_prompt,
        messages=[{"role": "user", "content": user_prompt}],
        max_tokens=4096,
        temperature=0.0,
        thinking_depth=ThinkingDepth.MEDIUM,
        timeout_seconds=_EVAL_ANSWER_TIMEOUT,
    )
    raw_answer = str(raw_answer or "")
    normalized_answer = normalize_eval_answer(raw_answer)
    logger.info(
        "Eval query answer synthesis completed",
        question=question,
        evidence_hit_count=len(hits),
        raw_answer=raw_answer,
        answer=normalized_answer,
    )
    l2_count = len(l2_entity_cards or []) + len(l2_relationships or []) + len(l2_assertions or [])
    answer_trace = {
        "answer_source": "llm",
        "llm_scenario": LLMScenario.CORE.value,
        "evidence_hit_count": len(hits) + l2_count,
        "evidence_bundle_count": len(evidence_bundles or []),
        "evidence_timeline_count": len(timeline_summary or []),
    }
    if show_prompt:
        answer_trace["prompt"] = user_prompt
    return normalized_answer, answer_trace


def _build_l2_pending_breakdown(
    pipeline_stats: Dict[str, Any],
    projection_backlog: Dict[str, Any] | None = None,
) -> Dict[str, int]:
    durable_projection = dict(projection_backlog or {})
    return {
        "extract_pending": max(int(durable_projection.get("pending", 0)) + int(durable_projection.get("claimed", 0)), 0),
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
        "projection_pending": max(int(durable_projection.get("pending", 0)), 0),
        "projection_claimed": max(int(durable_projection.get("claimed", 0)), 0),
        "projection_failed": max(int(durable_projection.get("failed", 0)), 0),
    }


def _build_embedding_pending(stats: Dict[str, Any] | None) -> Dict[str, Any]:
    payload = dict(stats or {})
    pending = int(payload.get("embedding_queue_size", 0) or 0)
    return {
        "pending": max(pending, 0),
        "worker_running": bool(payload.get("embedding_worker_running", False)),
        "vector_enabled": bool(payload.get("vector_enabled", False)),
        "async_embeddings": bool(payload.get("async_embeddings", False)),
    }


def _serialize_memory_event(event: MemoryEvent | Dict[str, Any]) -> Dict[str, Any]:
    if isinstance(event, MemoryEvent):
        return event.to_dict()
    return dict(event)


def _serialize_l1_event_list_item(event: MemoryEvent | Dict[str, Any]) -> Dict[str, Any]:
    payload = _serialize_memory_event(event)
    payload.pop("metadata_json", None)
    payload.pop("embedding_status", None)
    payload.pop("embedding_profile_id", None)
    return payload


def _parse_day_boundary(value: str | None, *, end_of_day: bool) -> float | None:
    normalized = str(value or "").strip()
    if not normalized:
        return None
    try:
        parsed = date.fromisoformat(normalized)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"Invalid date value: {normalized}",
        ) from exc
    boundary = datetime_time.max if end_of_day else datetime_time.min
    return datetime.combine(parsed, boundary).timestamp()


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
        return {"items": [], "total": 0, "limit": limit, "offset": offset, "stats": {"active_sessions": 0, "total_goals": 0, "total_entities": 0, "total_tactics": 0}}

    chat_read_service = get_chat_read_service()
    l0_sessions = unified_memory.l0._sessions

    # Sort all sessions by last_active_at descending (most recent first).
    sorted_ids = sorted(
        l0_sessions.keys(),
        key=lambda sid: l0_sessions[sid].get("last_active_at", 0),
        reverse=True,
    )

    # Apply status filter before pagination.
    if status:
        sorted_ids = [sid for sid in sorted_ids if l0_sessions[sid].get("status") == status]

    total = len(sorted_ids)

    # Slice for the requested page.
    page_ids = sorted_ids[offset : offset + limit]

    # Only batch-fetch chat summaries for the page slice (not all sessions).
    user_ids_by_session = {
        sid: str(l0_sessions[sid].get("user_id") or DEFAULT_USER_ID)
        for sid in page_ids
    }
    sessions_by_user: dict[str, list[str]] = {}
    for sid, uid in user_ids_by_session.items():
        sessions_by_user.setdefault(uid, []).append(sid)

    summary_map: dict[str, Any] = {}
    for uid, sids in sessions_by_user.items():
        batch = await chat_read_service.aget_session_summaries_batch(uid, sids)
        summary_map.update(batch)

    # Apply text query filter if provided (needs summaries for display text matching).
    if query:
        q_lower = query.lower()
        filtered_page_ids = []
        for sid in page_ids:
            session = l0_sessions[sid]
            goals = unified_memory.l0._goal_stack.get(sid, [])
            chat_summary = summary_map.get(sid)
            display = _derive_l0_session_display(session_id=sid, goals=goals, chat_summary=chat_summary)
            searchable = " ".join(filter(None, [
                sid,
                display.get("display_title", ""),
                display.get("display_subtitle", ""),
                session.get("status", ""),
            ])).lower()
            if q_lower in searchable:
                filtered_page_ids.append(sid)
        page_ids = filtered_page_ids

    items = []
    total_goals = 0
    total_entities = 0
    total_tactics = 0

    for session_id in page_ids:
        session = l0_sessions[session_id]
        goals = unified_memory.l0._goal_stack.get(session_id, [])
        entities = unified_memory.l0._active_entities.get(session_id, {})
        tactics = unified_memory.l0._temporary_tactics.get(session_id, {})
        chat_summary = summary_map.get(session_id)
        display = _derive_l0_session_display(
            session_id=session_id,
            goals=goals,
            chat_summary=chat_summary,
        )
        total_goals += len(goals)
        total_entities += len(entities)
        total_tactics += len(tactics)

        items.append({
            "session_id": session_id,
            "user_id": session.get("user_id"),
            "status": session.get("status"),
            "started_at": session.get("started_at"),
            "last_active_at": session.get("last_active_at"),
            "goal_count": len(goals),
            "entity_count": len(entities),
            "tactic_count": len(tactics),
            **display,
        })

    return {
        "items": items,
        "total": total,
        "limit": limit,
        "offset": offset,
        "stats": {
            "active_sessions": len([s for s in items if s["status"] == "active"]),
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
            "projection_backlog": {"pending": 0, "claimed": 0, "completed": 0, "failed": 0},
            "db_path": None,
        }

    rel_count, tom_count = await asyncio.gather(
        unified_memory.l2.count_relationships(),
        unified_memory.l2.count_tom_assertions(),
    )
    pipeline_stats = unified_memory.get_l2_pipeline_stats() if hasattr(unified_memory, "get_l2_pipeline_stats") else {}
    projection_backlog = (
        await unified_memory.get_l2_projection_backlog()
        if hasattr(unified_memory, "get_l2_projection_backlog")
        else {"pending": 0, "claimed": 0, "completed": 0, "failed": 0}
    )
    return {
        "is_running": bool(pipeline_stats.get("is_running", False)),
        "relation_count": rel_count,
        "assertion_count": tom_count,
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
        "projection_backlog": projection_backlog,
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
            "projection_pending": 0,
            "projection_claimed": 0,
            "projection_failed": 0,
        }

    pipeline_stats = unified_memory.get_l2_pipeline_stats() if hasattr(unified_memory, "get_l2_pipeline_stats") else {}
    projection_backlog = (
        await unified_memory.get_l2_projection_backlog()
        if hasattr(unified_memory, "get_l2_projection_backlog")
        else {"pending": 0, "claimed": 0, "completed": 0, "failed": 0}
    )
    pending = _build_l2_pending_breakdown(pipeline_stats, projection_backlog)
    return {
        "is_running": bool(pipeline_stats.get("is_running", False)),
        **pending,
    }


@memory_router.get("/background/pending")
async def get_background_pending():
    """Get lightweight backlog stats for background memory workers."""
    unified_memory = _resolve_unified_memory()
    if not unified_memory:
        return {
            "l2": {
                "extract_pending": 0,
                "reconcile_pending": 0,
                "snapshot_pending": 0,
                "projection_pending": 0,
                "projection_claimed": 0,
                "projection_failed": 0,
            },
            "l1_embeddings": {"pending": 0, "worker_running": False, "vector_enabled": False, "async_embeddings": False},
            "l3_embeddings": {"pending": 0, "worker_running": False, "vector_enabled": False, "async_embeddings": False},
            "l4_embeddings": {"pending": 0, "worker_running": False, "vector_enabled": False, "async_embeddings": False},
            "all_idle": True,
        }

    pipeline_stats = unified_memory.get_l2_pipeline_stats() if hasattr(unified_memory, "get_l2_pipeline_stats") else {}
    projection_backlog = (
        await unified_memory.get_l2_projection_backlog()
        if hasattr(unified_memory, "get_l2_projection_backlog")
        else {"pending": 0, "claimed": 0, "completed": 0, "failed": 0}
    )
    l2_pending = _build_l2_pending_breakdown(pipeline_stats, projection_backlog)
    l1_pending = _build_embedding_pending(
        unified_memory.l1.get_statistics() if getattr(unified_memory, "l1", None) and hasattr(unified_memory.l1, "get_statistics") else None
    )
    l3_pending = _build_embedding_pending(
        unified_memory.l3.get_statistics() if getattr(unified_memory, "l3", None) and hasattr(unified_memory.l3, "get_statistics") else None
    )
    l4_pending = _build_embedding_pending(
        unified_memory.l4.get_statistics() if getattr(unified_memory, "l4", None) and hasattr(unified_memory.l4, "get_statistics") else None
    )
    all_idle = (
        l2_pending["extract_pending"] == 0
        and l2_pending["reconcile_pending"] == 0
        and l2_pending["snapshot_pending"] == 0
        and l1_pending["pending"] == 0
        and l3_pending["pending"] == 0
        and l4_pending["pending"] == 0
    )
    return {
        "l2": l2_pending,
        "l1_embeddings": l1_pending,
        "l3_embeddings": l3_pending,
        "l4_embeddings": l4_pending,
        "all_idle": all_idle,
    }
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


class AssertionFeedbackRequest(BaseModel):
    feedback: Literal["confirmed", "rejected"]


class AssertionCorrectionRequest(BaseModel):
    new_value: str = Field(..., min_length=1, max_length=2000)
    reason: Optional[str] = Field(default=None, max_length=500)


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

    stats: Dict[str, Any] = {}

    # L0 statistics (in-memory, fast)
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

    # L1-L4 statistics: run count queries concurrently
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

    stats["l1"] = {"event_count": l1_count}
    if unified_memory.l1:
        stats["l1"]["db_path"] = unified_memory.l1.db_path

    stats["l2"] = {"relation_count": l2_rel_count, "assertion_count": l2_tom_count}
    if unified_memory.l2:
        stats["l2"]["db_path"] = unified_memory.l2.db_path

    stats["l3"] = {"summary_count": l3_count}
    if unified_memory.l3:
        stats["l3"]["db_path"] = unified_memory.l3.db_path

    stats["l4"] = {"skill_count": l4_count}
    if unified_memory.l4:
        stats["l4"]["db_path"] = unified_memory.l4.db_path

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

    start_time = _parse_day_boundary(start_date, end_of_day=False)
    end_time = _parse_day_boundary(end_date, end_of_day=True)

    source_filters = [str(source).strip()] if str(source or "").strip() else None
    cleaned_query = str(query or "").strip() or None
    cleaned_source_item_id = str(source_item_id or "").strip() or None
    cleaned_idempotency_key = str(idempotency_key or "").strip() or None

    events, total = await asyncio.gather(
        unified_memory.l1.query_events(
            session_id=session_id,
            user_id=user_id,
            event_type=event_type,
            query=cleaned_query,
            source_filters=source_filters,
            source_item_id=cleaned_source_item_id,
            idempotency_key=cleaned_idempotency_key,
            start_time=start_time,
            end_time=end_time,
            limit=limit,
            offset=offset,
            include_metadata_json=False,
            include_embedding_fields=False,
        ),
        unified_memory.l1.count_events(
            session_id=session_id,
            user_id=user_id,
            event_type=event_type,
            query=cleaned_query,
            source_filters=source_filters,
            source_item_id=cleaned_source_item_id,
            idempotency_key=cleaned_idempotency_key,
            start_time=start_time,
            end_time=end_time,
        ),
    )
    return {"items": [_serialize_l1_event_list_item(event) for event in events], "total": total, "limit": limit, "offset": offset}


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
    return {
        "items": [
            ProcedureResponse(
                skill_id=str(item["skill_id"]),
                skill_name=str(item["skill_name"]),
                skill_category=str(item["skill_category"]),
                success_rate=float(item["success_rate"]),
                total_attempts=int(item["total_attempts"]),
                circuit_breaker_state=str(item["circuit_breaker_state"]),
            )
            for item in items
        ],
        "total": total,
        "limit": limit,
        "offset": offset,
    }


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


class EpisodeAnnotationRequest(BaseModel):
    user_label: Optional[str] = Field(default=None, max_length=500)
    user_note: Optional[str] = Field(default=None, max_length=2000)
    user_pinned: Optional[bool] = None


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


class ForgetEntityRequest(BaseModel):
    entity_id: str = Field(..., min_length=1, max_length=500)
    delete_l1_events: bool = Field(default=False, description="Also soft-delete L1 events mentioning this entity")


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


class ForgetTimeRangeRequest(BaseModel):
    start: float = Field(..., description="Range start (epoch seconds)")
    end: float = Field(..., description="Range end (epoch seconds)")
    delete_l1_events: bool = Field(default=False, description="Also soft-delete L1 events in this range")


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


class ForgetEpisodeRequest(BaseModel):
    episode_id: str = Field(..., min_length=1, max_length=500)
    delete_events: bool = Field(default=False, description="Also soft-delete member L1 events")


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
