"""L4 summary storage for multi-time-granularity memory digests."""

from __future__ import annotations

import json
import logging
import time
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, DefaultDict, Dict, List, Optional

import aiosqlite

logger = logging.getLogger(__name__)


@dataclass
class EventSummary:
    period_type: str
    period_key: str
    start_time: float
    end_time: float
    event_count: int
    summary: str
    event_types: Dict[str, int]
    metrics: Dict[str, Any]
    key_events: List[Dict[str, Any]]
    created_at: float = field(default_factory=time.time)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "period_type": self.period_type,
            "period_key": self.period_key,
            "start_time": self.start_time,
            "end_time": self.end_time,
            "event_count": self.event_count,
            "summary": self.summary,
            "event_types": self.event_types,
            "metrics": self.metrics,
            "key_events": self.key_events,
            "created_at": self.created_at,
        }

    @classmethod
    def from_dict(cls, payload: Dict[str, Any]) -> "EventSummary":
        return cls(
            period_type=str(payload["period_type"]),
            period_key=str(payload["period_key"]),
            start_time=float(payload["start_time"]),
            end_time=float(payload["end_time"]),
            event_count=int(payload["event_count"]),
            summary=str(payload["summary"]),
            event_types=dict(payload.get("event_types", {})),
            metrics=dict(payload.get("metrics", {})),
            key_events=list(payload.get("key_events", [])),
            created_at=float(payload.get("created_at", time.time())),
        )


class SummaryStore:
    """Aggregates events into hour/day/week/month summaries."""

    def __init__(self, persist_path: Optional[str] = None):
        self.persist_path = str(Path(persist_path or "~/.magi/data/memories/summaries.db").expanduser())
        self._summaries: DefaultDict[str, Dict[str, EventSummary]] = defaultdict(dict)
        self._event_cache: DefaultDict[str, DefaultDict[str, List[Dict[str, Any]]]] = defaultdict(
            lambda: defaultdict(list)
        )
        # compatibility alias used by old API code
        self._event_buffers = self._event_cache
        self._initialized = False

    async def initialize(self) -> None:
        if self._initialized:
            return

        Path(self.persist_path).parent.mkdir(parents=True, exist_ok=True)
        async with aiosqlite.connect(self.persist_path) as db:
            await db.execute(
                """
                CREATE TABLE IF NOT EXISTS summaries (
                    period_type TEXT NOT NULL,
                    period_key TEXT NOT NULL,
                    payload TEXT NOT NULL,
                    created_at REAL NOT NULL,
                    PRIMARY KEY(period_type, period_key)
                )
                """
            )
            await db.execute(
                "CREATE INDEX IF NOT EXISTS idx_summaries_created_at ON summaries(created_at)"
            )
            await db.commit()

            cursor = await db.execute("SELECT payload FROM summaries")
            rows = await cursor.fetchall()

        for (payload_text,) in rows:
            summary = EventSummary.from_dict(json.loads(payload_text))
            self._summaries[summary.period_type][summary.period_key] = summary

        self._initialized = True

    def add_event(self, event: Dict[str, Any]) -> None:
        """Adds an event to in-memory aggregation buffers."""
        ts = float(event.get("timestamp", time.time()))
        for period_type in ("hour", "day", "week", "month"):
            key = self._get_period_key(ts, period_type)
            self._event_cache[period_type][key].append(dict(event))
            if len(self._event_cache[period_type][key]) > 5000:
                self._event_cache[period_type][key] = self._event_cache[period_type][key][-5000:]

    def generate_summary(
        self,
        period_type: str,
        period_key: Optional[str] = None,
        force: bool = False,
    ) -> Optional[EventSummary]:
        """Generates or returns cached summary for a period."""
        if period_type not in {"hour", "day", "week", "month"}:
            return None

        key = period_key or self._get_period_key(time.time(), period_type)
        if not force and key in self._summaries[period_type]:
            return self._summaries[period_type][key]

        events = self._event_cache[period_type].get(key, [])
        if not events:
            return None

        summary = self._build_summary(period_type, key, events)
        self._summaries[period_type][key] = summary
        self._persist_summary(summary)
        return summary

    def get_summary(self, period_type: str, period_key: Optional[str] = None) -> Optional[EventSummary]:
        key = period_key or self._get_period_key(time.time(), period_type)
        return self._summaries.get(period_type, {}).get(key)

    def get_summaries(self, period_type: str, limit: int = 10) -> List[EventSummary]:
        items = list(self._summaries.get(period_type, {}).values())
        items.sort(key=lambda item: item.end_time, reverse=True)
        return items[:limit]

    def clear_old_summaries(self, older_than_months: int = 12) -> int:
        cutoff = time.time() - (older_than_months * 30 * 86400)
        removed = 0

        for period_type in list(self._summaries.keys()):
            old_keys = [
                key
                for key, summary in self._summaries[period_type].items()
                if summary.end_time < cutoff
            ]
            for key in old_keys:
                del self._summaries[period_type][key]
                removed += 1

        _sync_delete_old(self.persist_path, cutoff)
        return removed

    def clear(self) -> int:
        total = sum(len(items) for items in self._summaries.values())
        self._summaries.clear()
        self._event_cache.clear()
        _sync_clear_all(self.persist_path)
        return total

    def get_statistics(self) -> Dict[str, Any]:
        counts = {period_type: len(period_map) for period_type, period_map in self._summaries.items()}
        return {
            "summary_counts": counts,
            "total_summaries": sum(counts.values()),
            "buffered_periods": {
                period_type: len(period_map)
                for period_type, period_map in self._event_cache.items()
            },
            "db_path": self.persist_path,
        }

    def _build_summary(self, period_type: str, period_key: str, events: List[Dict[str, Any]]) -> EventSummary:
        event_types: Dict[str, int] = defaultdict(int)
        key_events: List[Dict[str, Any]] = []
        error_count = 0
        timestamps: List[float] = []

        for event in events:
            event_type = str(event.get("type", "unknown"))
            event_types[event_type] += 1
            ts = float(event.get("timestamp", 0.0))
            timestamps.append(ts)

            level = event.get("level", 1)
            if isinstance(level, str):
                level_text = level.upper()
                level_value = 3 if level_text in {"ERROR", "CRITICAL", "EMERGENCY"} else 1
            else:
                level_value = int(level)

            if level_value >= 3 or event_type.lower() in {"erroroccurred", "system_error"}:
                key_events.append(
                    {
                        "timestamp": ts,
                        "type": event_type,
                        "data": event.get("data", {}),
                    }
                )
                error_count += 1

        start_time = min(timestamps) if timestamps else time.time()
        end_time = max(timestamps) if timestamps else time.time()

        summary_text = self._render_summary_text(period_type, period_key, events, event_types, key_events)
        metrics = {
            "duration_hours": max(0.0, (end_time - start_time) / 3600),
            "error_rate": (error_count / len(events)) if events else 0.0,
            "most_common_type": max(event_types.items(), key=lambda item: item[1])[0] if event_types else "unknown",
        }

        return EventSummary(
            period_type=period_type,
            period_key=period_key,
            start_time=start_time,
            end_time=end_time,
            event_count=len(events),
            summary=summary_text,
            event_types=dict(event_types),
            metrics=metrics,
            key_events=key_events[:10],
        )

    def _render_summary_text(
        self,
        period_type: str,
        period_key: str,
        events: List[Dict[str, Any]],
        event_types: Dict[str, int],
        key_events: List[Dict[str, Any]],
    ) -> str:
        lines = [f"# {period_type} summary ({period_key})", f"- total events: {len(events)}"]
        if events:
            lines.append(
                "- time range: "
                f"{datetime.fromtimestamp(float(events[0].get('timestamp', 0.0))).isoformat()}"
                " -> "
                f"{datetime.fromtimestamp(float(events[-1].get('timestamp', 0.0))).isoformat()}"
            )

        lines.append("- event distribution:")
        for event_type, count in sorted(event_types.items(), key=lambda item: item[1], reverse=True):
            lines.append(f"  - {event_type}: {count}")

        if key_events:
            lines.append("- key events:")
            for event in key_events[:5]:
                ts = datetime.fromtimestamp(float(event.get("timestamp", 0.0))).strftime("%Y-%m-%d %H:%M:%S")
                lines.append(f"  - [{ts}] {event.get('type', 'unknown')}")

        return "\n".join(lines)

    def _persist_summary(self, summary: EventSummary) -> None:
        import sqlite3

        conn = sqlite3.connect(self.persist_path)
        cur = conn.cursor()
        payload = json.dumps(summary.to_dict(), ensure_ascii=False)
        cur.execute(
            """
            INSERT INTO summaries(period_type, period_key, payload, created_at)
            VALUES(?, ?, ?, ?)
            ON CONFLICT(period_type, period_key) DO UPDATE SET
                payload = excluded.payload,
                created_at = excluded.created_at
            """,
            (summary.period_type, summary.period_key, payload, summary.created_at),
        )
        conn.commit()
        conn.close()

    def _get_period_key(self, timestamp: float, period_type: str) -> str:
        dt = datetime.fromtimestamp(timestamp)
        if period_type == "hour":
            return dt.strftime("%Y-%m-%d-%H")
        if period_type == "day":
            return dt.strftime("%Y-%m-%d")
        if period_type == "week":
            year, week, _ = dt.isocalendar()
            return f"{year}-W{week:02d}"
        if period_type == "month":
            return dt.strftime("%Y-%m")
        raise ValueError(f"Unsupported period type: {period_type}")

    # compatibility helpers expected by previous callers
    def _save_to_disk(self) -> None:
        return None

    _save = _save_to_disk


class AutoSummarizer:
    """Background summary helper."""

    def __init__(self, summary_store: SummaryStore):
        self.summary_store = summary_store
        self._running = False

    async def start(self) -> None:
        if not self._running:
            await self.summary_store.initialize()
        self._running = True

    def stop(self) -> None:
        self._running = False

    async def generate_all_pending(self) -> None:
        now = time.time()
        for period_type in ("hour", "day", "week", "month"):
            key = self.summary_store._get_period_key(now, period_type)
            if key not in self.summary_store._summaries.get(period_type, {}):
                self.summary_store.generate_summary(period_type=period_type, period_key=key)


def _sync_delete_old(db_path: str, cutoff: float) -> None:
    import sqlite3

    conn = sqlite3.connect(db_path)
    cur = conn.cursor()
    cur.execute("DELETE FROM summaries WHERE created_at < ?", (cutoff,))
    conn.commit()
    conn.close()


def _sync_clear_all(db_path: str) -> None:
    import sqlite3

    conn = sqlite3.connect(db_path)
    cur = conn.cursor()
    cur.execute("DELETE FROM summaries")
    conn.commit()
    conn.close()
