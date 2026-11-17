"""Memory-owned evidence reads for quiet reflection and explicit watches."""

import hashlib
import json
from typing import Any

from ..core.sqlite import sqlite_connection_async
from .source_event_governance import source_event_derivation_block_ids
from .l2.corrections.repository import MemoryCorrectionRepository
from .l1.storage.connection import event_connection


def evidence_digest(event: dict[str, Any]) -> str:
    payload = {key: event.get(key) for key in (
        "event_id", "content", "user_id", "source", "timestamp", "author_type", "metadata_json",
    )}
    return hashlib.sha256(json.dumps(payload, sort_keys=True, ensure_ascii=False).encode()).hexdigest()


class ReflectionEvidenceReader:
    digest = staticmethod(evidence_digest)

    def __init__(self, memory: Any) -> None:
        self.memory = memory

    async def watch_sources(self, user_id: str) -> list[str]:
        async with event_connection(self.memory.l1_db_path) as db:
            cursor = await db.execute("SELECT DISTINCT source FROM fact_events WHERE user_id=? AND deleted_at IS NULL AND cognition_eligible=1 ORDER BY source", (user_id,))
            return [row[0] for row in await cursor.fetchall()]

    async def watch_changes(self, user_id: str, sources: list[str], after: float, after_id: str) -> tuple[list[dict], float, str]:
        # shortcut: capture-order cursors exclude older delayed deliveries; use an ingestion sequence before supporting out-of-order delivery.
        async with event_connection(self.memory.l1_db_path) as db:
            cursor = await db.execute("SELECT event_id,created_at FROM fact_events WHERE user_id=? AND source IN (SELECT value FROM json_each(?)) AND (created_at,event_id)>(?,?) ORDER BY created_at,event_id LIMIT 24",
                                      (user_id, json.dumps(sources), after, after_id))
            rows = await cursor.fetchall()
        if not rows:
            return [], after, after_id
        current = await self.current(user_id, [row[0] for row in rows])
        return [row for row in current if row.get("author_type") != "assistant"], rows[-1][1], rows[-1][0]

    async def governance_revision(self) -> str:
        # Any correction invalidates old interpretations before their next read.
        async with sqlite_connection_async(self.memory.memory_db_path) as db:
            cursor = await db.execute("SELECT subject_key, revision FROM memory_subject_revisions ORDER BY subject_key")
            return hashlib.sha256(json.dumps([tuple(row) for row in await cursor.fetchall()]).encode()).hexdigest()

    async def recent(self, user_id: str, *, limit: int = 60, query: str | None = None) -> list[dict]:
        if self.memory.l1 is None:
            return []
        rows = await self.memory.l1.query_events(
            user_id=user_id, cognition_eligible=True, query=query, limit=limit,
            order_by="created_at_desc", include_embedding_fields=False,
        )
        return await self._allowed(rows, user_id)

    async def last_chat_at(self, user_id: str) -> float:
        if self.memory.l1 is None:
            return 0
        rows = await self.memory.l1.query_events(user_id=user_id, source_filters=["chat"], limit=1,
                                                order_by="created_at_desc", include_embedding_fields=False)
        return float(rows[0].get("created_at") or rows[0]["timestamp"]) if rows else 0

    async def current(self, user_id: str, identities: list[str]) -> list[dict]:
        if self.memory.l1 is None:
            return []
        rows = []
        for identity in dict.fromkeys(identities):
            event = await self.memory.l1.get_user_visible_event(identity)
            if event:
                rows.append(event)
        return await self._allowed(rows, user_id)

    async def _allowed(self, rows: list[dict], user_id: str) -> list[dict]:
        async with sqlite_connection_async(self.memory.memory_db_path) as db:
            blocked = await source_event_derivation_block_ids(db, [row["event_id"] for row in rows])
        blocked.update(await MemoryCorrectionRepository(self.memory.memory_db_path).active_correction_evidence_event_ids(
            row["event_id"] for row in rows
        ))
        return [row for row in rows if row.get("user_id") == user_id
                and row.get("cognition_eligible") and row["event_id"] not in blocked
                and row.get("memory_domain") not in {"runtime_telemetry", "system_control"}
                and row.get("content") and not row.get("deleted_at")]
