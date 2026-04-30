"""Search, archival, and retention maintenance for the unified memory store."""

from __future__ import annotations

import json
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict

from ..core.sqlite import sqlite_transaction_async


class UnifiedMemoryMaintenanceMixin:
    """Expose lightweight search and retention maintenance operations."""

    l0: Any
    l1: Any
    l2: Any
    l3: Any
    l4: Any
    _archive_dir: Path

    async def search(
        self,
        query: str,
        *,
        search_type: str = "detail",
        limit: int = 10,
    ) -> list[dict[str, Any]]:
        """Perform a simple layer-aware search without the retrieval router."""
        if search_type in {"detail", "hybrid", "keyword"} and self.l1 is not None:
            return await self.l1.search_events(query=query, limit=limit)
        if search_type == "summary" and self.l3 is not None:
            return await self.l3.search_summaries(query=query, limit=limit)
        if search_type in {"experience", "strategy"} and self.l4 is not None:
            return await self.l4.query_strategies(query=query, limit=limit)
        if search_type == "graph" and self.l2 is not None:
            return await self.l2.get_relationships(limit=limit)
        return []

    def _archive_db_path_for_date(self, archive_date: str) -> Path:
        return self._archive_dir / f"{archive_date}.db"

    async def _archive_l1_event(self, event: Dict[str, Any], *, archived_at: float) -> None:
        archive_date = datetime.fromtimestamp(archived_at, tz=timezone.utc).strftime("%Y-%m-%d")
        archive_db_path = self._archive_db_path_for_date(archive_date)
        payload_json = json.dumps(event, ensure_ascii=False, separators=(",", ":"))
        async with sqlite_transaction_async(archive_db_path, profile="mixed") as db:
            await db.execute(
                """
                CREATE TABLE IF NOT EXISTS archived_l1_events (
                    event_id TEXT PRIMARY KEY,
                    archived_date TEXT NOT NULL,
                    archived_at REAL NOT NULL,
                    event_timestamp REAL NOT NULL,
                    event_type TEXT NOT NULL,
                    source TEXT NOT NULL,
                    session_id TEXT,
                    user_id TEXT,
                    payload_json TEXT NOT NULL
                )
                """
            )
            await db.execute(
                "CREATE INDEX IF NOT EXISTS idx_archived_l1_events_date ON archived_l1_events(archived_date, event_timestamp)"
            )
            await db.execute(
                """
                INSERT OR REPLACE INTO archived_l1_events (
                    event_id, archived_date, archived_at, event_timestamp,
                    event_type, source, session_id, user_id, payload_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    event["event_id"],
                    archive_date,
                    float(archived_at),
                    float(event.get("timestamp") or archived_at),
                    str(event.get("event_type") or "unknown"),
                    str(event.get("source") or "unknown"),
                    event.get("session_id"),
                    event.get("user_id"),
                    payload_json,
                ),
            )

    async def cleanup_old_data(
        self,
        older_than_days: int = 30,
        *,
        history_behavior: str = "delete",
    ) -> Dict[str, int]:
        """Run lightweight cleanup jobs."""
        removed: Dict[str, int] = {
            "expired_sessions": 0,
            "deleted_events": 0,
            "archived_events": 0,
            "deleted_summaries": 0,
        }
        if self.l0 is not None:
            removed["expired_sessions"] = len(await self.l0.expire_idle_sessions())
            await self.l0.checkpoint_all()
        if self.l1 is not None and self.l3 is not None:
            cutoff = time.time() - (max(int(older_than_days), 0) * 86400)
            candidate_event_ids = await self.l1.list_compressible_event_ids(
                older_than=cutoff,
                limit=10_000,
            )
            linked_event_ids = await self.l3.filter_linked_event_ids(candidate_event_ids)
            should_archive = str(history_behavior).lower() == "archive"
            archived_at = time.time()
            for event_id in linked_event_ids:
                if should_archive:
                    event = await self.l1.get_event(event_id)
                    if event is None:
                        continue
                    await self._archive_l1_event(event, archived_at=archived_at)
                    removed["archived_events"] += 1
                if await self.l1.mark_deleted(event_id):
                    removed["deleted_events"] += 1
        return removed

    async def run_maintenance(
        self,
        retention_days: int = 30,
        *,
        history_behavior: str = "delete",
    ) -> Dict[str, int]:
        """Run periodic maintenance."""
        return await self.cleanup_old_data(
            older_than_days=retention_days,
            history_behavior=history_behavior,
        )


__all__ = ["UnifiedMemoryMaintenanceMixin"]
