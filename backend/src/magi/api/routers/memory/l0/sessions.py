"""L0 session list response helpers for the memory API."""
from __future__ import annotations

import time
from typing import Any, Mapping

from magi.identity import CANONICAL_LOCAL_USER as DEFAULT_USER_ID

from .display import derive_l0_session_display


def _current_goals(goals: list[Any]) -> list[Any]:
    return [
        goal
        for goal in goals
        if str(goal.get("status") or "") in {"pending", "in_progress"}
    ]


def empty_l0_sessions_response(*, limit: int, offset: int) -> dict[str, Any]:
    return {
        "items": [],
        "total": 0,
        "limit": limit,
        "offset": offset,
        "stats": {
            "active_sessions": 0,
            "total_goals": 0,
            "total_entities": 0,
            "total_tactics": 0,
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
    goals_by_session: Mapping[str, list[Any]],
    summary_map: Mapping[str, Any],
) -> list[str]:
    if not query:
        return session_ids
    query_lower = query.lower()
    filtered_session_ids: list[str] = []
    for session_id in session_ids:
        session = sessions[session_id]
        display = derive_l0_session_display(
            session_id=session_id,
            goals=_current_goals(goals_by_session.get(session_id, [])),
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
    goals_by_session: Mapping[str, list[Any]],
    entities_by_session: Mapping[str, Mapping[str, Any]],
    tactics_by_session: Mapping[str, Mapping[str, Any]],
    summary_map: Mapping[str, Any],
) -> tuple[list[dict[str, Any]], dict[str, int]]:
    items: list[dict[str, Any]] = []
    total_goals = 0
    total_entities = 0
    total_tactics = 0
    now = time.time()

    for session_id in session_ids:
        session = sessions[session_id]
        goals = _current_goals(goals_by_session.get(session_id, []))
        entities = entities_by_session.get(session_id, {})
        tactics = {
            tactic_id: tactic
            for tactic_id, tactic in tactics_by_session.get(session_id, {}).items()
            if tactic.get("expires_at") is None
            or float(tactic["expires_at"]) > now
        }
        chat_summary = summary_map.get(session_id)
        display = derive_l0_session_display(
            session_id=session_id,
            goals=goals,
            chat_summary=chat_summary,
        )
        total_goals += len(goals)
        total_entities += len(entities)
        total_tactics += len(tactics)

        items.append(
            {
                "session_id": session_id,
                "user_id": session.get("user_id"),
                "status": session.get("status"),
                "started_at": session.get("started_at"),
                "last_active_at": session.get("last_active_at"),
                "goal_count": len(goals),
                "entity_count": len(entities),
                "tactic_count": len(tactics),
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
        "total_goals": total_goals,
        "total_entities": total_entities,
        "total_tactics": total_tactics,
    }
