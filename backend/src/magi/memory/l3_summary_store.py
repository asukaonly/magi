"""L3 reflection memory store."""

from __future__ import annotations

import json
import time
import uuid
from pathlib import Path
from typing import Any, Dict, List, Optional

import aiosqlite

from .l1_event_store import L1EventStore


class L3SummaryStore:
    """Stores reflection-oriented summaries that remain traceable to L1 evidence."""

    def __init__(self, *, db_path: str = "~/.magi/data/memories/memory.db") -> None:
        self.db_path = str(Path(db_path).expanduser())
        self._initialized = False

    async def initialize(self) -> None:
        """Create the summaries schema."""
        if self._initialized:
            return

        Path(self.db_path).parent.mkdir(parents=True, exist_ok=True)
        async with aiosqlite.connect(self.db_path) as db:
            await db.executescript(
                """
                CREATE TABLE IF NOT EXISTS summaries (
                    summary_id TEXT PRIMARY KEY,
                    summary_type TEXT NOT NULL,
                    summary_category TEXT NOT NULL,
                    period_start REAL NOT NULL,
                    period_end REAL NOT NULL,
                    content TEXT NOT NULL,
                    key_topics TEXT,
                    key_entities TEXT,
                    sentiment_summary TEXT,
                    source_event_ids TEXT NOT NULL,
                    source_event_count INTEGER NOT NULL,
                    importance_aggregate REAL,
                    event_type_distribution TEXT,
                    generated_by_model TEXT,
                    generation_prompt TEXT,
                    generation_reason TEXT,
                    created_at REAL NOT NULL,
                    updated_at REAL NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_summaries_period ON summaries(summary_type, summary_category, period_start, period_end);

                CREATE TABLE IF NOT EXISTS l3_summary_vectors (
                    vector_id TEXT PRIMARY KEY,
                    summary_id TEXT NOT NULL,
                    embedding_model TEXT NOT NULL,
                    embedding_dim INTEGER NOT NULL,
                    embedding_payload BLOB NOT NULL,
                    metadata TEXT,
                    created_at REAL NOT NULL,
                    updated_at REAL NOT NULL,
                    UNIQUE(summary_id, embedding_model)
                );
                CREATE INDEX IF NOT EXISTS idx_l3_summary_vectors_summary ON l3_summary_vectors(summary_id);
                CREATE INDEX IF NOT EXISTS idx_l3_summary_vectors_model ON l3_summary_vectors(embedding_model);
                """
            )
            await db.commit()
        self._initialized = True

    async def generate_temporal_summary(
        self,
        *,
        l1_store: L1EventStore,
        summary_category: str,
        period_start: float,
        period_end: float,
    ) -> Optional[Dict[str, Any]]:
        """Build a temporal summary from eligible L1 events."""
        await self.initialize()
        candidates = await l1_store.query_events(
            start_time=period_start,
            end_time=period_end,
            cognition_eligible=True,
            limit=500,
        )
        events = [
            event
            for event in candidates
            if event["memory_domain"] != "runtime_telemetry" and event["retention_class"] != "disposable"
        ]
        if not events:
            return None

        source_event_ids = [event["event_id"] for event in events]
        content = " ".join(event["raw_content"] for event in events[:6]).strip()
        summary = {
            "summary_id": f"summary_{uuid.uuid4().hex}",
            "summary_type": "temporal",
            "summary_category": summary_category,
            "period_start": float(period_start),
            "period_end": float(period_end),
            "content": content,
            "key_topics": [],
            "key_entities": [],
            "sentiment_summary": None,
            "source_event_ids": source_event_ids,
            "source_event_count": len(source_event_ids),
            "importance_aggregate": sum(float(event["importance_score"]) for event in events) / len(events),
            "event_type_distribution": {
                event["event_type"]: sum(1 for item in events if item["event_type"] == event["event_type"])
                for event in events
            },
            "generated_by_model": "rule-summary",
            "generation_prompt": None,
            "generation_reason": f"temporal:{summary_category}",
            "created_at": time.time(),
            "updated_at": time.time(),
        }
        await self._store_summary(summary)
        return summary

    async def search_summaries(
        self,
        *,
        query: str,
        summary_type: Optional[str] = None,
        limit: int = 10,
    ) -> List[Dict[str, Any]]:
        """Perform simple keyword retrieval over summary content."""
        await self.initialize()
        sql = "SELECT * FROM summaries WHERE content LIKE ?"
        args: List[Any] = [f"%{query}%"]
        if summary_type:
            sql += " AND summary_type = ?"
            args.append(summary_type)
        sql += " ORDER BY updated_at DESC LIMIT ?"
        args.append(int(limit))
        async with aiosqlite.connect(self.db_path) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute(sql, tuple(args)) as cursor:
                rows = await cursor.fetchall()
        return [self._row_to_dict(row) for row in rows]

    async def list_summaries(self, *, limit: int = 100) -> List[Dict[str, Any]]:
        """List most recent summaries."""
        await self.initialize()
        async with aiosqlite.connect(self.db_path) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute("SELECT * FROM summaries ORDER BY updated_at DESC LIMIT ?", (int(limit),)) as cursor:
                rows = await cursor.fetchall()
        return [self._row_to_dict(row) for row in rows]

    async def clear(self) -> int:
        """Delete all summaries."""
        await self.initialize()
        async with aiosqlite.connect(self.db_path) as db:
            async with db.execute("SELECT COUNT(*) FROM summaries") as cursor:
                row = await cursor.fetchone()
                count = int(row[0]) if row else 0
            await db.execute("DELETE FROM summaries")
            await db.commit()
        return count

    def get_statistics(self) -> Dict[str, Any]:
        """Return lightweight metadata for reporting."""
        return {"db_path": self.db_path}

    async def _store_summary(self, summary: Dict[str, Any]) -> None:
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute(
                """
                INSERT OR REPLACE INTO summaries(
                    summary_id, summary_type, summary_category, period_start, period_end,
                    content, key_topics, key_entities, sentiment_summary, source_event_ids,
                    source_event_count, importance_aggregate, event_type_distribution,
                    generated_by_model, generation_prompt, generation_reason, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    summary["summary_id"],
                    summary["summary_type"],
                    summary["summary_category"],
                    float(summary["period_start"]),
                    float(summary["period_end"]),
                    summary["content"],
                    json.dumps(summary["key_topics"], ensure_ascii=False),
                    json.dumps(summary["key_entities"], ensure_ascii=False),
                    summary["sentiment_summary"],
                    json.dumps(summary["source_event_ids"], ensure_ascii=False),
                    int(summary["source_event_count"]),
                    float(summary["importance_aggregate"]),
                    json.dumps(summary["event_type_distribution"], ensure_ascii=False),
                    summary["generated_by_model"],
                    summary["generation_prompt"],
                    summary["generation_reason"],
                    float(summary["created_at"]),
                    float(summary["updated_at"]),
                ),
            )
            await db.commit()

    def _row_to_dict(self, row: aiosqlite.Row) -> Dict[str, Any]:
        return {
            "summary_id": str(row["summary_id"]),
            "summary_type": str(row["summary_type"]),
            "summary_category": str(row["summary_category"]),
            "period_start": float(row["period_start"]),
            "period_end": float(row["period_end"]),
            "content": str(row["content"]),
            "key_topics": json.loads(row["key_topics"] or "[]"),
            "key_entities": json.loads(row["key_entities"] or "[]"),
            "sentiment_summary": row["sentiment_summary"],
            "source_event_ids": json.loads(row["source_event_ids"] or "[]"),
            "source_event_count": int(row["source_event_count"]),
            "importance_aggregate": float(row["importance_aggregate"] or 0.0),
            "event_type_distribution": json.loads(row["event_type_distribution"] or "{}"),
            "generated_by_model": row["generated_by_model"],
            "generation_prompt": row["generation_prompt"],
            "generation_reason": row["generation_reason"],
            "created_at": float(row["created_at"]),
            "updated_at": float(row["updated_at"]),
        }


__all__ = ["L3SummaryStore"]
