"""UnifiedMemoryStore-backed L1 event query handler."""
from __future__ import annotations

import time
from typing import Any, Dict, List


PROGRAMMING_SOURCES = {"git", "terminal", "chrome_history", "chat"}


class L1EventQueryHandler:
    """Queries L1 events and returns normalized snippets for the LLM."""

    def __init__(self, unified_memory) -> None:
        self._unified_memory = unified_memory

    async def query(self, request, plan) -> List[Dict[str, Any]]:
        limit = int(getattr(request, "limit", 0) or 200)
        start_time, end_time = self._time_range_bounds(plan.time_range)
        events = await self._unified_memory.l1_raw.query_events(
            sources=plan.source_filters or None,
            start_time=start_time,
            end_time=end_time,
            limit=limit,
        )
        filtered: List[Dict[str, Any]] = []
        for event in events:
            if not self._matches_time_range(event, plan.time_range):
                continue
            if not self._matches_topic(event, plan.topic_query):
                continue
            filtered.append(self._normalize_event(event))
        filtered.sort(key=lambda item: float(item.get("timestamp", 0.0)), reverse=True)
        return filtered[:limit]

    def _time_range_bounds(self, time_range: Dict[str, Any]) -> tuple[float | None, float | None]:
        start = time_range.get("start")
        end = time_range.get("end")
        relative = str(time_range.get("relative") or "").strip().lower()
        if start is None and relative:
            start = self._relative_cutoff(relative)
        return (
            float(start) if start is not None else None,
            float(end) if end is not None else None,
        )

    def _matches_time_range(self, event: Dict[str, Any], time_range: Dict[str, Any]) -> bool:
        if not time_range:
            return True
        timestamp = float(event.get("timestamp") or 0.0)
        start = time_range.get("start")
        end = time_range.get("end")
        if start is not None and timestamp < float(start):
            return False
        if end is not None and timestamp > float(end):
            return False
        relative = str(time_range.get("relative") or "").strip().lower()
        if not relative:
            return True
        cutoff = self._relative_cutoff(relative)
        if cutoff is None:
            return True
        return timestamp >= cutoff

    def _relative_cutoff(self, relative: str) -> float | None:
        now = time.time()
        if relative.endswith("h"):
            return now - (int(relative[:-1]) * 3600)
        if relative.endswith("d"):
            return now - (int(relative[:-1]) * 86400)
        if relative.endswith("w"):
            return now - (int(relative[:-1]) * 7 * 86400)
        return None

    def _matches_topic(self, event: Dict[str, Any], topic_query: str) -> bool:
        if not topic_query:
            return True
        normalized_topic = topic_query.lower().strip()
        event_text = self._build_search_text(event)
        if normalized_topic in {"programming", "coding", "development"}:
            return str(event.get("source") or "") in PROGRAMMING_SOURCES or any(
                token in event_text for token in ["code", "bug", "repo", "test", "program", "开发", "代码"]
            )
        return normalized_topic in event_text

    def _build_search_text(self, event: Dict[str, Any]) -> str:
        parts: List[str] = [
            str(event.get("type") or ""),
            str(event.get("source") or ""),
        ]
        for container in (event.get("data"), event.get("metadata")):
            if not isinstance(container, dict):
                continue
            for value in container.values():
                if isinstance(value, str):
                    parts.append(value)
                elif isinstance(value, list):
                    parts.extend(str(item) for item in value if isinstance(item, (str, int, float)))
        return " ".join(parts).lower().strip()

    def _normalize_event(self, event: Dict[str, Any]) -> Dict[str, Any]:
        data = event.get("data") if isinstance(event.get("data"), dict) else {}
        metadata = event.get("metadata") if isinstance(event.get("metadata"), dict) else {}
        summary = (
            data.get("message")
            or data.get("command")
            or data.get("title")
            or metadata.get("summary")
            or f"{event.get('source', 'unknown')} {event.get('type', 'event')}".strip()
        )
        details = {
            key: value
            for key, value in {**data, **metadata}.items()
            if isinstance(value, (str, int, float, bool, list, dict))
        }
        return {
            "event_id": event.get("id"),
            "timestamp": event.get("timestamp"),
            "source": event.get("source"),
            "event_type": event.get("type"),
            "summary": str(summary),
            "details": details,
            "raw_ref": {"event_id": event.get("id")},
        }
