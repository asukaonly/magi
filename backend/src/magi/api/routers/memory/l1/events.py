"""L1 event list helpers for the memory API."""
from __future__ import annotations

from typing import Any

from ..helpers import parse_day_boundary, serialize_l1_event_list_item


def build_l1_event_query_args(
    *,
    session_id: str | None,
    user_id: str | None,
    event_type: str | None,
    query: str | None,
    source: str | None,
    source_item_id: str | None,
    idempotency_key: str | None,
    start_date: str | None,
    end_date: str | None,
) -> dict[str, Any]:
    return {
        "session_id": session_id,
        "user_id": user_id,
        "event_type": event_type,
        "query": _clean_optional(query),
        "source_filters": [str(source).strip()] if str(source or "").strip() else None,
        "source_item_id": _clean_optional(source_item_id),
        "idempotency_key": _clean_optional(idempotency_key),
        "start_time": parse_day_boundary(start_date, end_of_day=False),
        "end_time": parse_day_boundary(end_date, end_of_day=True),
    }


def build_l1_events_response(
    *,
    events: list[Any],
    total: int,
    limit: int,
    offset: int,
) -> dict[str, Any]:
    return {
        "items": [serialize_l1_event_list_item(event) for event in events],
        "total": total,
        "limit": limit,
        "offset": offset,
    }


def _clean_optional(value: str | None) -> str | None:
    cleaned = str(value or "").strip()
    return cleaned or None
