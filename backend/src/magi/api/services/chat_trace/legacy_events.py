"""Legacy L1 event loading for chat trace snapshots."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Protocol, cast

from ....core.logger import get_logger
from ....core.sqlite import connect_sqlite
from .constants import (
    FACT_DISPLAY_EVENT_TYPES,
    FACT_EVENTS_TABLE,
    RUNTIME_OBSERVATIONS_TABLE,
    TRACE_EVENT_TYPES,
)

logger = get_logger(__name__)


class _LegacyTraceEventsHost(Protocol):
    _l1_db_path: Path


class LegacyTraceEventsMixin:
    """Load and normalize legacy trace events from L1 fact tables."""

    def _load_turn_events(
        self,
        *,
        user_id: str,
        session_id: str,
        turn_id: str,
    ) -> list[dict[str, Any]]:
        host = cast(_LegacyTraceEventsHost, self)
        if not host._l1_db_path.exists():
            return []
        fact_items = self._query_table_events(
            table=FACT_EVENTS_TABLE,
            event_types=FACT_DISPLAY_EVENT_TYPES,
            user_id=user_id,
            session_id=session_id,
            turn_id=turn_id,
        )
        trace_items = self._query_table_events(
            table=RUNTIME_OBSERVATIONS_TABLE,
            event_types=TRACE_EVENT_TYPES,
            user_id=user_id,
            session_id=session_id,
            turn_id=turn_id,
        )
        return sorted(fact_items + trace_items, key=lambda item: float(item.get("timestamp", 0.0)))

    def _load_session_events(self, *, user_id: str, session_id: str) -> list[dict[str, Any]]:
        host = cast(_LegacyTraceEventsHost, self)
        if not host._l1_db_path.exists():
            return []
        fact_items = self._query_table_events(
            table=FACT_EVENTS_TABLE,
            event_types=FACT_DISPLAY_EVENT_TYPES,
            user_id=user_id,
            session_id=session_id,
            turn_id=None,
        )
        trace_items = self._query_table_events(
            table=RUNTIME_OBSERVATIONS_TABLE,
            event_types=TRACE_EVENT_TYPES,
            user_id=user_id,
            session_id=session_id,
            turn_id=None,
        )
        return sorted(fact_items + trace_items, key=lambda item: float(item.get("timestamp", 0.0)))

    def _query_table_events(
        self,
        *,
        table: str,
        event_types: tuple[str, ...],
        user_id: str,
        session_id: str,
        turn_id: str | None,
    ) -> list[dict[str, Any]]:
        if not event_types:
            return []
        host = cast(_LegacyTraceEventsHost, self)
        type_placeholders = ", ".join("?" for _ in event_types)
        query = f"""
            SELECT event_type, content, timestamp, turn_id
            FROM {table}
            WHERE deleted_at IS NULL
              AND event_type IN ({type_placeholders})
              AND user_id = ?
              AND session_id = ?
        """
        params: list[Any] = [*event_types, user_id, session_id]
        if turn_id is not None:
            query += " AND turn_id = ?"
            params.append(turn_id)
        query += " ORDER BY timestamp ASC"
        try:
            conn = connect_sqlite(host._l1_db_path, profile="hot_write", use_row_factory=False)
            cur = conn.cursor()
            cur.execute(query, params)
            rows = cur.fetchall()
            conn.close()
        except Exception as exc:
            logger.warning("Failed to query trace events table=%s: %s", table, exc)
            return []

        items: list[dict[str, Any]] = []
        for event_type, raw_content, timestamp, raw_turn_id in rows:
            payload = self._build_event_payload(
                event_type=str(event_type),
                raw_content=raw_content,
                turn_id=raw_turn_id,
            )
            items.append(
                {
                    "type": str(event_type),
                    "payload": payload if isinstance(payload, dict) else {},
                    "timestamp": float(timestamp or 0.0),
                }
            )
        return items

    def _build_event_payload(
        self,
        *,
        event_type: str,
        raw_content: object,
        turn_id: object,
    ) -> dict[str, Any]:
        text = str(raw_content or "").strip()
        normalized_turn_id = str(turn_id or "").strip() or None
        if event_type in FACT_DISPLAY_EVENT_TYPES:
            payload: dict[str, Any] = {"content": text}
            if normalized_turn_id:
                payload["turn_id"] = normalized_turn_id
            return payload
        if not text:
            return {"turn_id": normalized_turn_id} if normalized_turn_id else {}
        try:
            payload = json.loads(text)
        except Exception:
            payload = {"content": text}
        if not isinstance(payload, dict):
            payload = {"content": text}
        if normalized_turn_id and not payload.get("turn_id"):
            payload["turn_id"] = normalized_turn_id
        return payload


__all__ = ["LegacyTraceEventsMixin"]