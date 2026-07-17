"""Search, archival, and retention maintenance for the unified memory store."""

from __future__ import annotations

import json
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict

from ..core.sqlite import sqlite_connection_async, sqlite_transaction_async
from .source_event_governance import (
    business_source_references,
    chat_session_source_reference,
    normalize_source_event_ids,
    source_event_tombstone_ids,
)

_L2_EPISODE_TERMINAL_STATUSES = ("merged", "invalidated", "archived")
_L2_EXPERIENCE_TERMINAL_STATUSES = ("merged", "invalidated")
_L2_SEED_ACTIVE_STATUSES = ("candidate", "accepted")
_L2_GRAPH_ACTIVE_STATUSES = ("active",)
_L2_ASSERTION_TERMINAL_STATUSES = (
    "superseded",
    "archived",
    "expired",
    "user_rejected",
    "shadow",
)
_L2_FACET_ACTIVE_STATUSES = ("active",)
_L3_REVIEW_PROTECTED_STATES = ("pending_confirmation", "confirmed")
_L3_EPISODIC_REFERENCE_KEYS = (
    "source_experience_id",
    "source_episode_id",
    "experience_id",
    "episode_id",
)


def _empty_maintenance_counts() -> Dict[str, int]:
    return {
        "expired_sessions": 0,
        "deleted_events": 0,
        "archived_events": 0,
        "archived_summaries": 0,
        "deleted_summaries": 0,
        "pruned_pinned_payloads": 0,
    }


def _merge_counts(base: Dict[str, int], delta: Dict[str, int]) -> None:
    for key, value in delta.items():
        base[key] = int(base.get(key, 0)) + int(value)


def _normalize_event_ids(event_ids: list[str]) -> list[str]:
    seen: set[str] = set()
    normalized: list[str] = []
    for raw_event_id in event_ids:
        event_id = str(raw_event_id or "").strip()
        if not event_id or event_id in seen:
            continue
        seen.add(event_id)
        normalized.append(event_id)
    return normalized


def _chunked(values: list[str], *, size: int = 500) -> list[list[str]]:
    return [values[index : index + size] for index in range(0, len(values), size)]


def _placeholders(count: int) -> str:
    return ", ".join("?" for _ in range(count))


def _json_array_expr(column_name: str) -> str:
    return f"CASE WHEN json_valid({column_name}) THEN {column_name} ELSE '[]' END"


def _summary_metadata(summary: Dict[str, Any]) -> dict[str, Any]:
    raw_metadata = summary.get("insight_metadata") or {}
    if isinstance(raw_metadata, dict):
        return raw_metadata
    if isinstance(raw_metadata, str):
        try:
            decoded = json.loads(raw_metadata)
        except json.JSONDecodeError:
            return {}
        return decoded if isinstance(decoded, dict) else {}
    return {}


def _l1_archive_source_references(event: Dict[str, Any]) -> tuple[str, ...]:
    references = [
        str(value).strip()
        for value in (event.get("event_id"), event.get("turn_id"))
        if str(value or "").strip()
    ]
    user_id = str(event.get("user_id") or "").strip()
    session_id = str(event.get("session_id") or "").strip()
    if user_id and session_id:
        references.append(
            chat_session_source_reference(user_id=user_id, session_id=session_id)
        )
    references.extend(
        business_source_references(
            source=str(event.get("source") or ""),
            event_type=str(event.get("event_type") or ""),
            source_item_id=event.get("source_item_id"),
            idempotency_key=event.get("idempotency_key"),
        )
    )
    return normalize_source_event_ids(references)


def _l3_archive_source_references(
    summary: Dict[str, Any],
    event_links: list[Dict[str, Any]],
) -> tuple[str, ...]:
    source_event_ids = summary.get("source_event_ids")
    references = list(source_event_ids) if isinstance(source_event_ids, list) else []
    references.extend(
        str(link.get("event_id") or "").strip()
        for link in event_links
        if str(link.get("event_id") or "").strip()
    )
    return normalize_source_event_ids(references)


async def _sqlite_table_names(db: Any) -> set[str]:
    async with db.execute("SELECT name FROM sqlite_master WHERE type = 'table'") as cursor:
        table_rows = await cursor.fetchall()
    return {str(row[0]) for row in table_rows}


async def _collect_l2_referenced_event_ids(
    db: Any,
    tables: set[str],
    event_ids: list[str],
    protected: set[str],
) -> None:
    await _collect_l2_episode_event_refs(db, tables, event_ids, protected)
    await _collect_l2_experience_event_refs(db, tables, event_ids, protected)
    await _collect_l2_experience_episode_refs(db, tables, event_ids, protected)
    await _collect_l2_experience_key_event_refs(db, tables, event_ids, protected)
    await _collect_l2_seed_event_refs(db, tables, event_ids, protected)
    await _collect_l2_seed_episode_refs(db, tables, event_ids, protected)
    await _collect_l2_json_event_refs(
        db,
        tables,
        event_ids,
        protected,
        table_name="knowledge_graph",
        table_alias="kg",
        json_column="evidence_event_ids",
        status_column="status",
        statuses=_L2_GRAPH_ACTIVE_STATUSES,
        status_operator="IN",
    )
    await _collect_l2_json_event_refs(
        db,
        tables,
        event_ids,
        protected,
        table_name="tom_trait_assertions",
        table_alias="a",
        json_column="evidence_events",
        status_column="status",
        statuses=_L2_ASSERTION_TERMINAL_STATUSES,
        status_operator="NOT IN",
    )
    await _collect_l2_json_event_refs(
        db,
        tables,
        event_ids,
        protected,
        table_name="entity_facets",
        table_alias="f",
        json_column="evidence_event_ids",
        status_column="status",
        statuses=_L2_FACET_ACTIVE_STATUSES,
        status_operator="IN",
    )


async def _collect_first_column(
    db: Any,
    protected: set[str],
    sql: str,
    args: tuple[Any, ...],
) -> None:
    async with db.execute(sql, args) as cursor:
        rows = await cursor.fetchall()
    protected.update(str(row[0]) for row in rows if row[0])


async def _collect_l2_episode_event_refs(
    db: Any,
    tables: set[str],
    event_ids: list[str],
    protected: set[str],
) -> None:
    if not {"episode_events", "episodes"}.issubset(tables):
        return
    event_placeholders = _placeholders(len(event_ids))
    status_placeholders = _placeholders(len(_L2_EPISODE_TERMINAL_STATUSES))
    await _collect_first_column(
        db,
        protected,
        f"""
        SELECT DISTINCT ee.event_id
        FROM episode_events AS ee
        JOIN episodes AS e ON e.episode_id = ee.episode_id
        WHERE ee.event_id IN ({event_placeholders})
          AND ee.membership_role != 'excluded'
          AND e.status NOT IN ({status_placeholders})
        """,
        (*event_ids, *_L2_EPISODE_TERMINAL_STATUSES),
    )


async def _collect_l2_experience_event_refs(
    db: Any,
    tables: set[str],
    event_ids: list[str],
    protected: set[str],
) -> None:
    if not {"experience_members", "experiences"}.issubset(tables):
        return
    event_placeholders = _placeholders(len(event_ids))
    status_placeholders = _placeholders(len(_L2_EXPERIENCE_TERMINAL_STATUSES))
    await _collect_first_column(
        db,
        protected,
        f"""
        SELECT DISTINCT em.member_id
        FROM experience_members AS em
        JOIN experiences AS x ON x.experience_id = em.experience_id
        WHERE em.member_type = 'event'
          AND em.member_id IN ({event_placeholders})
          AND em.role != 'excluded'
          AND x.status NOT IN ({status_placeholders})
        """,
        (*event_ids, *_L2_EXPERIENCE_TERMINAL_STATUSES),
    )


async def _collect_l2_experience_episode_refs(
    db: Any,
    tables: set[str],
    event_ids: list[str],
    protected: set[str],
) -> None:
    if not {"experience_members", "experiences", "episode_events"}.issubset(tables):
        return
    event_placeholders = _placeholders(len(event_ids))
    status_placeholders = _placeholders(len(_L2_EXPERIENCE_TERMINAL_STATUSES))
    await _collect_first_column(
        db,
        protected,
        f"""
        SELECT DISTINCT ee.event_id
        FROM experience_members AS em
        JOIN experiences AS x ON x.experience_id = em.experience_id
        JOIN episode_events AS ee ON ee.episode_id = em.member_id
        WHERE em.member_type = 'episode'
          AND ee.event_id IN ({event_placeholders})
          AND em.role != 'excluded'
          AND ee.membership_role != 'excluded'
          AND x.status NOT IN ({status_placeholders})
        """,
        (*event_ids, *_L2_EXPERIENCE_TERMINAL_STATUSES),
    )


async def _collect_l2_experience_key_event_refs(
    db: Any,
    tables: set[str],
    event_ids: list[str],
    protected: set[str],
) -> None:
    if not {"experience_key_events", "experiences"}.issubset(tables):
        return
    event_placeholders = _placeholders(len(event_ids))
    status_placeholders = _placeholders(len(_L2_EXPERIENCE_TERMINAL_STATUSES))
    await _collect_first_column(
        db,
        protected,
        f"""
        SELECT DISTINCT eke.event_id
        FROM experience_key_events AS eke
        JOIN experiences AS x ON x.experience_id = eke.experience_id
        WHERE eke.event_id IN ({event_placeholders})
          AND x.status NOT IN ({status_placeholders})
        """,
        (*event_ids, *_L2_EXPERIENCE_TERMINAL_STATUSES),
    )


async def _collect_l2_seed_event_refs(
    db: Any,
    tables: set[str],
    event_ids: list[str],
    protected: set[str],
) -> None:
    if not {"experience_seed_evidence", "experience_seeds"}.issubset(tables):
        return
    event_placeholders = _placeholders(len(event_ids))
    status_placeholders = _placeholders(len(_L2_SEED_ACTIVE_STATUSES))
    await _collect_first_column(
        db,
        protected,
        f"""
        SELECT DISTINCT ese.ref_id
        FROM experience_seed_evidence AS ese
        JOIN experience_seeds AS s ON s.seed_id = ese.seed_id
        WHERE ese.ref_type = 'event'
          AND ese.ref_id IN ({event_placeholders})
          AND s.status IN ({status_placeholders})
        """,
        (*event_ids, *_L2_SEED_ACTIVE_STATUSES),
    )


async def _collect_l2_seed_episode_refs(
    db: Any,
    tables: set[str],
    event_ids: list[str],
    protected: set[str],
) -> None:
    if not {"experience_seed_evidence", "experience_seeds", "episode_events"}.issubset(tables):
        return
    event_placeholders = _placeholders(len(event_ids))
    status_placeholders = _placeholders(len(_L2_SEED_ACTIVE_STATUSES))
    await _collect_first_column(
        db,
        protected,
        f"""
        SELECT DISTINCT ee.event_id
        FROM experience_seed_evidence AS ese
        JOIN experience_seeds AS s ON s.seed_id = ese.seed_id
        JOIN episode_events AS ee ON ee.episode_id = ese.ref_id
        WHERE ese.ref_type = 'episode'
          AND ee.event_id IN ({event_placeholders})
          AND ee.membership_role != 'excluded'
          AND s.status IN ({status_placeholders})
        """,
        (*event_ids, *_L2_SEED_ACTIVE_STATUSES),
    )


async def _collect_l2_json_event_refs(
    db: Any,
    tables: set[str],
    event_ids: list[str],
    protected: set[str],
    *,
    table_name: str,
    table_alias: str,
    json_column: str,
    status_column: str,
    statuses: tuple[str, ...],
    status_operator: str,
) -> None:
    if table_name not in tables:
        return
    event_placeholders = _placeholders(len(event_ids))
    status_placeholders = _placeholders(len(statuses))
    qualified_json_column = f"{table_alias}.{json_column}"
    await _collect_first_column(
        db,
        protected,
        f"""
        SELECT DISTINCT evidence.value
        FROM {table_name} AS {table_alias},
             json_each({_json_array_expr(qualified_json_column)}) AS evidence
        WHERE evidence.value IN ({event_placeholders})
          AND {table_alias}.{status_column} {status_operator} ({status_placeholders})
        """,
        (*event_ids, *statuses),
    )


class UnifiedMemoryMaintenanceMixin:
    """Expose lightweight search and retention maintenance operations."""

    l0: Any
    l1: Any
    l2: Any
    l3: Any
    l4: Any
    memory_db_path: str
    _archive_dir: Path
    _write_lock: Any

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
            await db.execute("""
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
                """)
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

    async def _archive_l3_summary(
        self,
        summary_payload: Dict[str, Any],
        *,
        archived_at: float,
    ) -> None:
        summary = summary_payload.get("summary") or {}
        summary_id = str(summary.get("summary_id") or "")
        if not summary_id:
            return

        archive_date = datetime.fromtimestamp(archived_at, tz=timezone.utc).strftime("%Y-%m-%d")
        archive_db_path = self._archive_db_path_for_date(archive_date)
        payload_json = json.dumps(summary_payload, ensure_ascii=False, separators=(",", ":"))
        async with sqlite_transaction_async(archive_db_path, profile="mixed") as db:
            await db.execute("""
                CREATE TABLE IF NOT EXISTS archived_l3_summaries (
                    summary_id TEXT PRIMARY KEY,
                    archived_date TEXT NOT NULL,
                    archived_at REAL NOT NULL,
                    period_start REAL NOT NULL,
                    period_end REAL NOT NULL,
                    summary_type TEXT NOT NULL,
                    summary_category TEXT NOT NULL,
                    payload_json TEXT NOT NULL
                )
                """)
            await db.execute(
                "CREATE INDEX IF NOT EXISTS idx_archived_l3_summaries_date ON archived_l3_summaries(archived_date, period_end)"
            )
            await db.execute(
                """
                INSERT OR REPLACE INTO archived_l3_summaries (
                    summary_id, archived_date, archived_at, period_start,
                    period_end, summary_type, summary_category, payload_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    summary_id,
                    archive_date,
                    float(archived_at),
                    float(summary.get("period_start") or archived_at),
                    float(summary.get("period_end") or archived_at),
                    str(summary.get("summary_type") or "unknown"),
                    str(summary.get("summary_category") or "unknown"),
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
        removed = _empty_maintenance_counts()
        _merge_counts(removed, await self.cleanup_runtime_data())
        _merge_counts(
            removed,
            await self.cleanup_l1_data(
                older_than_days=older_than_days,
                history_behavior=history_behavior,
            ),
        )
        _merge_counts(
            removed,
            await self.cleanup_l3_data(
                older_than_days=older_than_days,
                history_behavior=history_behavior,
            ),
        )
        return removed

    async def cleanup_runtime_data(self) -> Dict[str, int]:
        """Run global runtime maintenance that is not owned by a memory layer."""
        removed = _empty_maintenance_counts()
        if self.l0 is not None:
            removed["expired_sessions"] = len(await self.l0.expire_idle_sessions())
            await self.l0.checkpoint_all()
        return removed

    async def _l2_referenced_l1_event_ids(self, event_ids: list[str]) -> set[str]:
        """Return event ids that remain live evidence for L2 user-facing records."""
        normalized_event_ids = _normalize_event_ids(event_ids)
        if not normalized_event_ids or self.l2 is None:
            return set()

        db_path = str(getattr(self.l2, "db_path", "") or "")
        if not db_path:
            return set()

        initialize = getattr(self.l2, "initialize", None)
        if callable(initialize):
            await initialize()

        protected: set[str] = set()
        async with sqlite_connection_async(db_path) as db:
            tables = await _sqlite_table_names(db)
            for chunk in _chunked(normalized_event_ids):
                await _collect_l2_referenced_event_ids(db, tables, chunk, protected)

        return protected

    async def _filter_l1_retention_candidates(self, event_ids: list[str]) -> list[str]:
        normalized_event_ids = _normalize_event_ids(event_ids)
        if not normalized_event_ids:
            return []
        protected_event_ids = await self._l2_referenced_l1_event_ids(normalized_event_ids)
        if not protected_event_ids:
            return normalized_event_ids
        return [
            event_id for event_id in normalized_event_ids if event_id not in protected_event_ids
        ]

    async def _archive_sources_are_governed(self, references: tuple[str, ...]) -> bool:
        """Return whether forgetting already governs any source reference."""
        normalized = normalize_source_event_ids(references)
        if not normalized:
            return False
        async with sqlite_connection_async(self.memory_db_path) as db:
            if await source_event_tombstone_ids(db, normalized):
                return True
            for chunk in _chunked(list(normalized)):
                placeholders = _placeholders(len(chunk))
                async with db.execute(
                    f"""
                    SELECT 1
                    FROM memory_projection_blocks
                    WHERE event_id IN ({placeholders})
                    LIMIT 1
                    """,
                    tuple(chunk),
                ) as cursor:
                    if await cursor.fetchone() is not None:
                        return True
        return False

    def _is_l3_summary_retention_protected(self, summary: Dict[str, Any]) -> bool:
        review_state = str(summary.get("review_state") or "").strip()
        if review_state in _L3_REVIEW_PROTECTED_STATES:
            return True

        metadata = _summary_metadata(summary)
        if any(metadata.get(key) for key in _L3_EPISODIC_REFERENCE_KEYS):
            return True

        return bool(metadata.get("user_pinned") or metadata.get("pinned"))

    async def cleanup_l1_data(
        self,
        older_than_days: int = 30,
        *,
        history_behavior: str = "delete",
    ) -> Dict[str, int]:
        """Run L1 retention maintenance."""
        removed: Dict[str, int] = {
            "deleted_events": 0,
            "archived_events": 0,
            "pruned_pinned_payloads": 0,
        }
        cutoff = time.time() - (max(int(older_than_days), 0) * 86400)
        should_archive = str(history_behavior).lower() == "archive"
        archived_at = time.time()
        if self.l1 is not None and self.l3 is not None:
            candidate_event_ids = await self.l1.list_compressible_event_ids(
                older_than=cutoff,
                limit=10_000,
            )
            linked_event_ids = await self.l3.filter_linked_event_ids(candidate_event_ids)
            deletable_event_ids = await self._filter_l1_retention_candidates(linked_event_ids)
            for event_id in deletable_event_ids:
                async with self._write_lock:
                    event = await self.l1.get_active_event(event_id)
                    if event is None:
                        continue
                    archive_is_governed = should_archive and (
                        await self._archive_sources_are_governed(
                            _l1_archive_source_references(event)
                        )
                    )
                    if should_archive and not archive_is_governed:
                        await self._archive_l1_event(event, archived_at=archived_at)
                        removed["archived_events"] += 1
                    if await self.l1.mark_deleted(event_id):
                        removed["deleted_events"] += 1
        if self.l1 is not None:
            # P3: drop pinned capture-time full-text payloads past the retention
            # window. They are a transient L2-extraction aid (consumed shortly
            # after ingest), so they need not outlive the same cutoff.
            removed["pruned_pinned_payloads"] = await self.l1.prune_pinned_payloads(
                retention_seconds=max(int(older_than_days), 0) * 86400,
            )
        return removed

    async def cleanup_l3_data(
        self,
        older_than_days: int = 30,
        *,
        history_behavior: str = "delete",
    ) -> Dict[str, int]:
        """Run L3 summary-retention maintenance."""
        removed: Dict[str, int] = {
            "archived_summaries": 0,
            "deleted_summaries": 0,
        }
        cutoff = time.time() - (max(int(older_than_days), 0) * 86400)
        should_archive = str(history_behavior).lower() == "archive"
        archived_at = time.time()
        if self.l3 is not None:
            expired_summaries = await self.l3.list_summaries_older_than(
                older_than=cutoff,
                limit=10_000,
            )
            for summary in expired_summaries:
                summary_id = str(summary.get("summary_id") or "")
                if not summary_id:
                    continue
                async with self._write_lock:
                    current_summary = await self.l3.get_summary_by_id(summary_id)
                    if (
                        current_summary is None
                        or float(current_summary.get("period_end") or 0.0) >= cutoff
                        or self._is_l3_summary_retention_protected(current_summary)
                    ):
                        continue
                    event_links = await self.l3.list_summary_event_links(summary_id)
                    archive_is_governed = should_archive and (
                        await self._archive_sources_are_governed(
                            _l3_archive_source_references(current_summary, event_links)
                        )
                    )
                    if should_archive and not archive_is_governed:
                        await self._archive_l3_summary(
                            {
                                "summary": current_summary,
                                "event_links": event_links,
                                "task_links": await self.l3.list_summary_task_links(summary_id),
                            },
                            archived_at=archived_at,
                        )
                        removed["archived_summaries"] += 1
                    if await self.l3.delete_summary(summary_id):
                        removed["deleted_summaries"] += 1
        return removed

    async def run_maintenance(
        self,
        retention_days: int = 30,
        *,
        history_behavior: str = "delete",
    ) -> Dict[str, int]:
        """Run non-layer periodic maintenance."""
        _ = retention_days, history_behavior
        return await self.cleanup_runtime_data()


__all__ = ["UnifiedMemoryMaintenanceMixin"]
