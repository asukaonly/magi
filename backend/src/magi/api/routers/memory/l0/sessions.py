"""L0 session list response helpers for the memory API."""
from __future__ import annotations

import time
from typing import Any, Mapping

from magi.identity import CANONICAL_LOCAL_USER as DEFAULT_USER_ID

from .display import derive_l0_session_display


def _current_attention(items: list[Any]) -> list[dict[str, Any]]:
    now = time.time()
    return [
        item
        for item in items
        if isinstance(item, dict)
        and str(item.get("status") or "") in {"active", "background"}
        and (
            item.get("expires_at") is None
            or float(item["expires_at"]) > now
        )
    ]


def empty_l0_sessions_response(*, limit: int, offset: int) -> dict[str, Any]:
    return {
        "items": [],
        "total": 0,
        "limit": limit,
        "offset": offset,
        "stats": {
            "active_sessions": 0,
            "total_attention_items": 0,
            "active_attention_items": 0,
            "background_attention_items": 0,
        },
    }


def sorted_l0_session_ids(
    sessions: Mapping[str, Mapping[str, Any]],
    *,
    status_filter: str | None,
) -> list[str]:
    session_ids = sorted(
        sessions.keys(),
        key=lambda session_id: sessions[session_id].get("last_active_at", 0),
        reverse=True,
    )
    if status_filter:
        session_ids = [
            session_id
            for session_id in session_ids
            if sessions[session_id].get("status") == status_filter
        ]
    return session_ids


def session_ids_by_user(
    sessions: Mapping[str, Mapping[str, Any]],
    session_ids: list[str],
) -> dict[str, list[str]]:
    grouped: dict[str, list[str]] = {}
    for session_id in session_ids:
        user_id = str(sessions[session_id].get("user_id") or DEFAULT_USER_ID)
        grouped.setdefault(user_id, []).append(session_id)
    return grouped


def filter_l0_session_ids_by_query(
    *,
    session_ids: list[str],
    query: str | None,
    sessions: Mapping[str, Mapping[str, Any]],
    attention_by_session: Mapping[str, list[Any]],
    summary_map: Mapping[str, Any],
) -> list[str]:
    if not query:
        return session_ids
    query_lower = query.lower()
    filtered_session_ids: list[str] = []
    for session_id in session_ids:
        session = sessions[session_id]
        attention = _current_attention(
            list(attention_by_session.get(session_id, []))
        )
        display = derive_l0_session_display(
            session_id=session_id,
            attention_items=attention,
            chat_summary=summary_map.get(session_id),
        )
        searchable = " ".join(
            filter(
                None,
                [
                    session_id,
                    display.get("display_title", ""),
                    display.get("display_subtitle", ""),
                    session.get("status", ""),
                    *[
                        str(item.get("summary") or "")
                        for item in attention
                    ],
                ],
            )
        ).lower()
        if query_lower in searchable:
            filtered_session_ids.append(session_id)
    return filtered_session_ids


def build_l0_session_list_items(
    *,
    session_ids: list[str],
    sessions: Mapping[str, Mapping[str, Any]],
    attention_by_session: Mapping[str, list[Any]],
    summary_map: Mapping[str, Any],
) -> tuple[list[dict[str, Any]], dict[str, int]]:
    items: list[dict[str, Any]] = []
    total_attention_items = 0
    active_attention_items = 0
    background_attention_items = 0

    for session_id in session_ids:
        session = sessions[session_id]
        attention = _current_attention(
            list(attention_by_session.get(session_id, []))
        )
        active_count = sum(
            str(item.get("status") or "") == "active"
            for item in attention
        )
        background_count = sum(
            str(item.get("status") or "") == "background"
            for item in attention
        )
        chat_summary = summary_map.get(session_id)
        display = derive_l0_session_display(
            session_id=session_id,
            attention_items=attention,
            chat_summary=chat_summary,
        )
        total_attention_items += len(attention)
        active_attention_items += active_count
        background_attention_items += background_count

        items.append(
            {
                "session_id": session_id,
                "user_id": session.get("user_id"),
                "status": session.get("status"),
                "started_at": session.get("started_at"),
                "last_active_at": session.get("last_active_at"),
                "attention_count": len(attention),
                "active_attention_count": active_count,
                "background_attention_count": background_count,
                "workspace_path": getattr(chat_summary, "workspace_path", None),
                "message_count": getattr(chat_summary, "message_count", None),
                "last_message_preview": getattr(chat_summary, "last_message_preview", None),
                "last_user_message_preview": getattr(chat_summary, "last_user_message_preview", None),
                "title_overridden": getattr(chat_summary, "title_overridden", None),
                "history_version": getattr(chat_summary, "history_version", None),
                **display,
            }
        )

    return items, {
        "active_sessions": len([item for item in items if item["status"] == "active"]),
        "total_attention_items": total_attention_items,
        "active_attention_items": active_attention_items,
        "background_attention_items": background_attention_items,
    }
