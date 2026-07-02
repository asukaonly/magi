"""Open predicate consolidation helpers for L2 entity maintenance."""

from __future__ import annotations

import time
import uuid
from typing import Protocol, cast

import aiosqlite

from .....core.sqlite import sqlite_connection_async
from .catalog import _merge_evidence_json
from ...ontology import PREDICATE_REGISTRY


class _PredicateMaintenanceStatsProtocol(Protocol):
    open_predicates_consolidated: int


class _PredicateMaintenanceHostProtocol(Protocol):
    _db_path: str


class L2EntityPredicateMaintenanceMixin:
    """Consolidate open predicates into core ontology predicates where possible."""

    async def _consolidate_open_predicates(
        self,
        stats: _PredicateMaintenanceStatsProtocol,
    ) -> None:
        """Rewrite non-core predicates to their core synonym when a mapping exists."""
        host = self._predicate_maintenance_host()
        core_preds_by_group = _core_predicates_by_synonym_group()

        async with sqlite_connection_async(host._db_path) as db:
            db.row_factory = aiosqlite.Row
            rows = await _fetch_active_knowledge_graph_rows(db)
            consolidated = 0
            now = time.time()
            for row in rows:
                core_predicates = _matching_core_predicates(row, core_preds_by_group)
                if not core_predicates:
                    continue
                await _consolidate_open_predicate_row(db, row, core_predicates, now)
                consolidated += 1
            if consolidated:
                await db.commit()
            stats.open_predicates_consolidated = consolidated

    def _predicate_maintenance_host(self) -> _PredicateMaintenanceHostProtocol:
        return self  # type: ignore[return-value]


async def _fetch_active_knowledge_graph_rows(db: aiosqlite.Connection) -> list[aiosqlite.Row]:
    return cast(
        list[aiosqlite.Row],
        await db.execute_fetchall("""
            SELECT triple_id, subject_id, predicate, object_id,
                   evidence_event_ids, observation_count, confidence,
                   first_observed_at, last_observed_at
            FROM knowledge_graph
            WHERE status = 'active'
            """),
    )


def _core_predicates_by_synonym_group() -> dict[str, list[str]]:
    core_preds_by_group: dict[str, list[str]] = {}
    for predicate in sorted(PREDICATE_REGISTRY):
        group = _predicate_synonym_group(predicate)
        if group:
            core_preds_by_group.setdefault(group, []).append(predicate)
    return core_preds_by_group


def _matching_core_predicates(
    row: aiosqlite.Row,
    core_preds_by_group: dict[str, list[str]],
) -> list[str] | None:
    predicate = str(row["predicate"]).strip().upper()
    if predicate in PREDICATE_REGISTRY:
        return None
    group = _predicate_synonym_group(predicate)
    if group is None:
        return None
    return core_preds_by_group.get(group)


async def _consolidate_open_predicate_row(
    db: aiosqlite.Connection,
    row: aiosqlite.Row,
    core_predicates: list[str],
    now: float,
) -> None:
    existing = await _fetch_existing_core_predicates(db, row, core_predicates)
    if existing:
        await _merge_open_predicate_into_existing(db, row, existing[0], now)
        return
    await _rewrite_open_predicate(db, row, core_predicates[0], now)


async def _fetch_existing_core_predicates(
    db: aiosqlite.Connection,
    row: aiosqlite.Row,
    core_predicates: list[str],
) -> list[aiosqlite.Row]:
    placeholders = ",".join("?" * len(core_predicates))
    return cast(
        list[aiosqlite.Row],
        await db.execute_fetchall(
            f"""
            SELECT triple_id, predicate, evidence_event_ids,
                   observation_count, confidence,
                   first_observed_at, last_observed_at
            FROM knowledge_graph
            WHERE subject_id = ? AND object_id = ?
              AND predicate IN ({placeholders})
              AND triple_id != ? AND status = 'active'
            """,
            (row["subject_id"], row["object_id"], *core_predicates, row["triple_id"]),
        ),
    )


async def _merge_open_predicate_into_existing(
    db: aiosqlite.Connection,
    row: aiosqlite.Row,
    duplicate: aiosqlite.Row,
    now: float,
) -> None:
    await db.execute(
        """
        UPDATE knowledge_graph
        SET evidence_event_ids = ?, observation_count = ?,
            first_observed_at = ?, last_observed_at = ?,
            confidence = ?, updated_at = ?
        WHERE triple_id = ?
        """,
        (*_merged_predicate_values(row, duplicate), now, str(duplicate["triple_id"])),
    )
    await db.execute(
        "DELETE FROM knowledge_graph WHERE triple_id = ?",
        (row["triple_id"],),
    )


def _merged_predicate_values(
    row: aiosqlite.Row, duplicate: aiosqlite.Row
) -> tuple[str, int, float, float, float]:
    evidence = _merge_evidence_json(
        str(row["evidence_event_ids"]),
        str(duplicate["evidence_event_ids"]),
    )
    observation_count = int(row["observation_count"]) + int(duplicate["observation_count"])
    first_observed_at = min(float(row["first_observed_at"]), float(duplicate["first_observed_at"]))
    last_observed_at = max(float(row["last_observed_at"]), float(duplicate["last_observed_at"]))
    confidence = max(float(row["confidence"]), float(duplicate["confidence"]))
    return evidence, observation_count, first_observed_at, last_observed_at, confidence


async def _rewrite_open_predicate(
    db: aiosqlite.Connection,
    row: aiosqlite.Row,
    target_predicate: str,
    now: float,
) -> None:
    await db.execute(
        """
        UPDATE knowledge_graph
        SET predicate = ?, triple_id = ?, updated_at = ?
        WHERE triple_id = ?
        """,
        (target_predicate, _canonical_triple_id(row, target_predicate), now, row["triple_id"]),
    )


def _canonical_triple_id(row: aiosqlite.Row, target_predicate: str) -> str:
    triple_key = f"{row['subject_id']}:{target_predicate}:{row['object_id']}"
    return f"triple_{uuid.uuid5(uuid.NAMESPACE_DNS, triple_key)}"


def _predicate_synonym_group(predicate: str) -> str | None:
    from . import get_predicate_synonym_group

    return cast(str | None, get_predicate_synonym_group(predicate))
