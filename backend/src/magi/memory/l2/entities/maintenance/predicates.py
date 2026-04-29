"""Open predicate consolidation helpers for L2 entity maintenance."""

from __future__ import annotations

import time
import uuid
from typing import Protocol

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
        from . import get_predicate_synonym_group

        core_preds_by_group: dict[str, list[str]] = {}
        for pred in sorted(PREDICATE_REGISTRY):
            group = get_predicate_synonym_group(pred)
            if group:
                core_preds_by_group.setdefault(group, []).append(pred)

        async with sqlite_connection_async(host._db_path) as db:
            db.row_factory = aiosqlite.Row
            rows = await db.execute_fetchall(
                """
                SELECT triple_id, subject_id, predicate, object_id,
                       evidence_event_ids, observation_count, confidence,
                       first_observed_at, last_observed_at
                FROM knowledge_graph
                WHERE status = 'active'
                """
            )
            consolidated = 0
            now = time.time()
            for row in rows:
                predicate = str(row["predicate"]).strip().upper()
                if predicate in PREDICATE_REGISTRY:
                    continue
                group = get_predicate_synonym_group(predicate)
                if group is None or group not in core_preds_by_group:
                    continue
                core_predicates = core_preds_by_group[group]

                placeholders = ",".join("?" * len(core_predicates))
                existing = await db.execute_fetchall(
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
                )
                if existing:
                    dup = existing[0]
                    dup_triple_id = str(dup["triple_id"])
                    ev = _merge_evidence_json(
                        str(row["evidence_event_ids"]), str(dup["evidence_event_ids"])
                    )
                    obs = int(row["observation_count"]) + int(dup["observation_count"])
                    first_at = min(float(row["first_observed_at"]), float(dup["first_observed_at"]))
                    last_at = max(float(row["last_observed_at"]), float(dup["last_observed_at"]))
                    conf = max(float(row["confidence"]), float(dup["confidence"]))
                    await db.execute(
                        """
                        UPDATE knowledge_graph
                        SET evidence_event_ids = ?, observation_count = ?,
                            first_observed_at = ?, last_observed_at = ?,
                            confidence = ?, updated_at = ?
                        WHERE triple_id = ?
                        """,
                        (ev, obs, first_at, last_at, conf, now, dup_triple_id),
                    )
                    await db.execute(
                        "DELETE FROM knowledge_graph WHERE triple_id = ?",
                        (row["triple_id"],),
                    )
                else:
                    target_predicate = core_predicates[0]
                    triple_key = f"{row['subject_id']}:{target_predicate}:{row['object_id']}"
                    new_triple_id = f"triple_{uuid.uuid5(uuid.NAMESPACE_DNS, triple_key)}"
                    await db.execute(
                        """
                        UPDATE knowledge_graph
                        SET predicate = ?, triple_id = ?, updated_at = ?
                        WHERE triple_id = ?
                        """,
                        (target_predicate, new_triple_id, now, row["triple_id"]),
                    )
                consolidated += 1
            if consolidated:
                await db.commit()
            stats.open_predicates_consolidated = consolidated

    def _predicate_maintenance_host(self) -> _PredicateMaintenanceHostProtocol:
        return self  # type: ignore[return-value]
