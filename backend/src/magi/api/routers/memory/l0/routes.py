"""L0 working-memory API routes."""

from __future__ import annotations

from typing import Any

from fastapi import HTTPException, Query, status

from magi.identity import CANONICAL_LOCAL_USER as DEFAULT_USER_ID

from ..dependencies import _resolve_unified_memory, get_chat_read_service
from ..helpers import memory_t
from ..router import memory_router
from .sessions import (
    build_l0_session_list_items,
    empty_l0_sessions_response,
    filter_l0_session_ids_by_query,
    session_ids_by_user,
    sorted_l0_session_ids,
)


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
    index = await unified_memory.l0.get_session_index_snapshot()
    l0_sessions = index["sessions"]
    sorted_ids = sorted_l0_session_ids(l0_sessions, status_filter=status)

    summary_map: dict[str, Any] = {}
    for user_id, session_ids in session_ids_by_user(l0_sessions, sorted_ids).items():
        batch = await chat_read_service.aget_session_summaries_batch(user_id, session_ids)
        summary_map.update(batch)

    indexed_attention = index.get("attention_by_session", {})
    attention_by_session: dict[str, list[dict[str, Any]]] = {
        session_id: [
            dict(item)
            for item in (
                indexed_attention.get(session_id, {}).values()
                if isinstance(indexed_attention.get(session_id), dict)
                else ()
            )
            if isinstance(item, dict)
        ]
        for session_id in sorted_ids
    }

    filtered_ids = filter_l0_session_ids_by_query(
        session_ids=sorted_ids,
        query=query,
        sessions=l0_sessions,
        attention_by_session=attention_by_session,
        summary_map=summary_map,
    )
    total = len(filtered_ids)

    all_items, stats = build_l0_session_list_items(
        session_ids=filtered_ids,
        sessions=l0_sessions,
        attention_by_session=attention_by_session,
        summary_map=summary_map,
    )
    items = all_items[offset : offset + limit]

    return {
        "items": items,
        "total": total,
        "limit": limit,
        "offset": offset,
        "stats": stats,
    }


@memory_router.get("/l0/workbench/{session_id}")
async def get_l0_workbench(session_id: str):
    """Get the short-term attention workbench for a session."""
    unified_memory = _resolve_unified_memory()
    if not unified_memory or not unified_memory.l0:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=memory_t("memory.errors.l0_uninitialized", "L0 working memory not initialized"),
        )

    workbench = await unified_memory.l0.get_workbench(session_id)
    if not workbench.get("session"):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=memory_t("memory.errors.session_not_found", "Session not found"),
        )
    session = workbench["session"]
    user_id = str(session.get("user_id") or DEFAULT_USER_ID)
    usage = await get_chat_read_service().aget_latest_context_usage(
        user_id,
        session_id,
    )
    workbench["context_usage"] = usage.to_dict() if usage is not None else None
    return workbench
