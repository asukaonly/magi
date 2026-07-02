"""Knowledge-graph ghost entity rewrite helpers for L2 maintenance."""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Any, cast

import aiosqlite

from .....core.logger import get_logger
from .....core.sqlite import sqlite_connection_async
from .ghosts_common import (
    L2EntityGhostHostMixin,
    _CatalogMaintenanceStatsProtocol,
    _canonical_entity_id,
    _merge_evidence_json,
)

logger = get_logger("magi.memory.l2.entities.maintenance")


@dataclass(slots=True, frozen=True)
class _GraphRewriteTarget:
    triple_id: str
    predicate: str
    new_subject: str
    new_object: str


class L2EntityGhostGraphMaintenanceMixin(L2EntityGhostHostMixin):
    """Resolve ghost catalog IDs and rewrite affected knowledge_graph rows."""

    async def _resolve_ghost_graph_refs(
        self,
        stats: _CatalogMaintenanceStatsProtocol,
    ) -> None:
        """Remap knowledge_graph rows whose subject/object ids are not in entity_catalog."""
        host = self._catalog_maintenance_host()
        async with sqlite_connection_async(host._db_path) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute("""
                SELECT DISTINCT object_id FROM knowledge_graph
                WHERE object_id NOT IN (SELECT entity_id FROM entity_catalog)
                  AND object_id NOT LIKE 'other:%'
                """) as cur:
                ghost_objects = [str(r[0]) for r in await cur.fetchall()]
            async with db.execute("""
                SELECT DISTINCT subject_id FROM knowledge_graph
                WHERE subject_id NOT IN (SELECT entity_id FROM entity_catalog)
                  AND subject_id NOT LIKE 'other:%'
                  AND subject_id NOT LIKE 'user:%'
                """) as cur:
                ghost_subjects = [str(r[0]) for r in await cur.fetchall()]

        for ghost_id in ghost_objects:
            target = await self._resolve_ghost_to_catalog_id(ghost_id)
            if not target:
                stats.ghost_skipped_no_target += 1
                continue
            rew, merged = await self._rewrite_graph_column("object_id", ghost_id, target)
            stats.ghost_edges_rewritten += rew
            stats.ghost_rows_merged += merged

        for ghost_id in ghost_subjects:
            target = await self._resolve_ghost_to_catalog_id(ghost_id)
            if not target:
                stats.ghost_skipped_no_target += 1
                continue
            rew, merged = await self._rewrite_graph_column("subject_id", ghost_id, target)
            stats.ghost_edges_rewritten += rew
            stats.ghost_rows_merged += merged

        await cast(Any, self)._rewrite_tom_entity_refs(stats)

    async def _resolve_ghost_to_catalog_id(self, ghost_id: str) -> str | None:
        host = self._catalog_maintenance_host()
        if ":" not in ghost_id:
            return None
        prefix, suffix = ghost_id.split(":", 1)
        entity_type = prefix.strip().lower()
        if not entity_type or not suffix:
            return None
        async with sqlite_connection_async(host._db_path) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute(
                "SELECT entity_id, canonical_name FROM entity_catalog WHERE entity_type = ?",
                (entity_type,),
            ) as cur:
                rows = await cur.fetchall()
        matches: list[str] = []
        for row in rows:
            cid = str(row["entity_id"])
            cname = str(row["canonical_name"])
            if _canonical_entity_id(entity_type, cname) == ghost_id:
                matches.append(cid)
        if len(matches) == 1:
            return matches[0]
        evidence_match = await self._resolve_ghost_by_evidence_text(
            ghost_id=ghost_id,
            entity_type=entity_type,
        )
        if evidence_match:
            return evidence_match
        if not matches:
            return None
        return await self._pick_entity_by_mention_count(matches)

    async def _resolve_ghost_by_evidence_text(
        self,
        *,
        ghost_id: str,
        entity_type: str,
    ) -> str | None:
        host = self._catalog_maintenance_host()
        async with sqlite_connection_async(host._db_path) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute(
                """
                SELECT evidence_text, natural_summary
                FROM knowledge_graph
                WHERE object_id = ? OR subject_id = ?
                """,
                (ghost_id, ghost_id),
            ) as cur:
                evidence_rows = await cur.fetchall()
            async with db.execute(
                """
                SELECT c.entity_id, c.canonical_name, a.alias_text
                FROM entity_catalog c
                LEFT JOIN entity_aliases a ON a.entity_id = c.entity_id
                WHERE c.entity_type = ?
                """,
                (entity_type,),
            ) as cur:
                catalog_rows = await cur.fetchall()

        evidence_blob = "\n".join(
            f"{row['evidence_text'] or ''}\n{row['natural_summary'] or ''}" for row in evidence_rows
        ).casefold()
        if not evidence_blob.strip():
            return None

        scored_matches: dict[str, int] = {}
        for row in catalog_rows:
            entity_id = str(row["entity_id"])
            for raw_name in (row["canonical_name"], row["alias_text"]):
                name = str(raw_name or "").strip()
                if len(name) < 2:
                    continue
                if name.casefold() in evidence_blob:
                    scored_matches[entity_id] = max(scored_matches.get(entity_id, 0), len(name))

        if not scored_matches:
            return None
        best_score = max(scored_matches.values())
        best_matches = [
            entity_id for entity_id, score in scored_matches.items() if score == best_score
        ]
        if len(best_matches) == 1:
            return best_matches[0]
        return await self._pick_entity_by_mention_count(best_matches)

    async def _pick_entity_by_mention_count(self, entity_ids: list[str]) -> str:
        host = self._catalog_maintenance_host()
        if len(entity_ids) == 1:
            return entity_ids[0]
        counts: dict[str, int] = {eid: 0 for eid in entity_ids}
        placeholders = ", ".join("?" for _ in entity_ids)
        async with sqlite_connection_async(host._db_path) as db:
            async with db.execute(
                f"""
                SELECT resolved_entity_id, COUNT(*) AS c
                FROM entity_mentions
                WHERE resolved_entity_id IN ({placeholders})
                GROUP BY resolved_entity_id
                """,
                tuple(entity_ids),
            ) as cur:
                for row in await cur.fetchall():
                    counts[str(row[0])] = int(row[1])
        return max(entity_ids, key=lambda eid: counts.get(eid, 0))

    async def _rewrite_graph_column(
        self,
        column: str,
        from_id: str,
        to_id: str,
    ) -> tuple[int, int]:
        """Rewrite column from_id -> to_id; merge rows that violate UNIQUE(subject_id, predicate, object_id)."""
        host = self._catalog_maintenance_host()
        if from_id == to_id:
            return (0, 0)
        if column not in {"subject_id", "object_id"}:
            return (0, 0)
        rewritten = 0
        merged = 0
        now = time.time()
        async with sqlite_connection_async(host._db_path) as db:
            await db.execute("BEGIN IMMEDIATE")
            try:
                rows = await self._fetch_graph_rewrite_rows(db, column, from_id)
                for row in rows:
                    row_rewritten, row_merged = await self._rewrite_graph_row_locked(
                        db=db,
                        column=column,
                        row=row,
                        to_id=to_id,
                        now=now,
                    )
                    rewritten += row_rewritten
                    merged += row_merged
                await db.commit()
            except Exception as exc:
                await db.rollback()
                logger.warning("L2 ghost graph rewrite failed", error=str(exc))
                raise
        return (rewritten, merged)

    async def _fetch_graph_rewrite_rows(
        self,
        db: aiosqlite.Connection,
        column: str,
        from_id: str,
    ) -> list[Any]:
        async with db.execute(
            f"""
            SELECT triple_id, subject_id, subject_type, predicate, object_id, object_type,
                   confidence, evidence_event_ids, observation_count,
                   first_observed_at, last_observed_at, last_confirmed_at,
                   source_type, extraction_method, status, created_at, updated_at
            FROM knowledge_graph
            WHERE {column} = ?
            """,
            (from_id,),
        ) as cur:
            return cast(list[Any], await cur.fetchall())

    async def _rewrite_graph_row_locked(
        self,
        *,
        db: aiosqlite.Connection,
        column: str,
        row: Any,
        to_id: str,
        now: float,
    ) -> tuple[int, int]:
        target = _graph_rewrite_target(row=row, column=column, to_id=to_id)
        duplicate = await self._find_graph_duplicate_locked(db, target)
        if duplicate is None:
            await self._update_graph_reference_locked(
                db=db,
                column=column,
                target=target,
                to_id=to_id,
                now=now,
            )
            return (1, 0)
        await self._merge_graph_duplicate_locked(
            db=db,
            row=row,
            duplicate=duplicate,
            target=target,
            now=now,
        )
        return (0, 1)

    async def _find_graph_duplicate_locked(
        self,
        db: aiosqlite.Connection,
        target: _GraphRewriteTarget,
    ) -> Any | None:
        async with db.execute(
            """
            SELECT triple_id, evidence_event_ids, observation_count,
                   first_observed_at, last_observed_at, confidence
            FROM knowledge_graph
            WHERE subject_id = ? AND predicate = ? AND object_id = ?
            """,
            (target.new_subject, target.predicate, target.new_object),
        ) as dup_cur:
            return await dup_cur.fetchone()

    async def _update_graph_reference_locked(
        self,
        *,
        db: aiosqlite.Connection,
        column: str,
        target: _GraphRewriteTarget,
        to_id: str,
        now: float,
    ) -> None:
        await db.execute(
            f"UPDATE knowledge_graph SET {column} = ?, updated_at = ? WHERE triple_id = ?",
            (to_id, now, target.triple_id),
        )

    async def _merge_graph_duplicate_locked(
        self,
        *,
        db: aiosqlite.Connection,
        row: Any,
        duplicate: Any,
        target: _GraphRewriteTarget,
        now: float,
    ) -> None:
        dup_id = str(duplicate[0])
        await db.execute(
            """
            UPDATE knowledge_graph
            SET evidence_event_ids = ?, observation_count = ?,
                first_observed_at = ?, last_observed_at = ?,
                confidence = ?, updated_at = ?
            WHERE triple_id = ?
            """,
            (
                _merge_evidence_json(str(row[7]), str(duplicate[1])),
                int(row[8]) + int(duplicate[2]),
                min(float(row[9]), float(duplicate[3])),
                max(float(row[10]), float(duplicate[4])),
                max(float(row[6]), float(duplicate[5])),
                now,
                dup_id,
            ),
        )
        await db.execute("DELETE FROM knowledge_graph WHERE triple_id = ?", (target.triple_id,))

    async def _merge_kg_ids_locked(
        self,
        db: aiosqlite.Connection,
        column: str,
        loser_id: str,
        winner_id: str,
        now: float,
    ) -> None:
        async with db.execute(
            f"SELECT * FROM knowledge_graph WHERE {column} = ?",
            (loser_id,),
        ) as cur:
            col_names = [d[0] for d in (cur.description or [])]
            rows = await cur.fetchall()
        for row in rows:
            rd = dict(zip(col_names, row))
            triple_id = str(rd["triple_id"])
            subject_id = str(rd["subject_id"])
            predicate = str(rd["predicate"])
            object_id = str(rd["object_id"])
            if column == "subject_id":
                new_subject = winner_id
                new_object = object_id
            else:
                new_subject = subject_id
                new_object = winner_id
            async with db.execute(
                """
                SELECT triple_id, evidence_event_ids, observation_count,
                       first_observed_at, last_observed_at, confidence
                FROM knowledge_graph
                WHERE subject_id = ? AND predicate = ? AND object_id = ?
                """,
                (new_subject, predicate, new_object),
            ) as dup_cur:
                dup = await dup_cur.fetchone()
            if dup is None:
                await db.execute(
                    f"UPDATE knowledge_graph SET {column} = ?, updated_at = ? WHERE triple_id = ?",
                    (winner_id, now, triple_id),
                )
            else:
                dup_id = str(dup[0])
                ev = _merge_evidence_json(str(rd["evidence_event_ids"]), str(dup[1]))
                obs = int(rd["observation_count"]) + int(dup[2])
                first_at = min(float(rd["first_observed_at"]), float(dup[3]))
                last_at = max(float(rd["last_observed_at"]), float(dup[4]))
                conf = max(float(rd["confidence"]), float(dup[5]))
                await db.execute(
                    """
                    UPDATE knowledge_graph
                    SET evidence_event_ids = ?, observation_count = ?,
                        first_observed_at = ?, last_observed_at = ?,
                        confidence = ?, updated_at = ?
                    WHERE triple_id = ?
                    """,
                    (ev, obs, first_at, last_at, conf, now, dup_id),
                )
                await db.execute("DELETE FROM knowledge_graph WHERE triple_id = ?", (triple_id,))


def _graph_rewrite_target(
    *,
    row: Any,
    column: str,
    to_id: str,
) -> _GraphRewriteTarget:
    subject_id = str(row[1])
    object_id = str(row[4])
    return _GraphRewriteTarget(
        triple_id=str(row[0]),
        predicate=str(row[3]),
        new_subject=to_id if column == "subject_id" else subject_id,
        new_object=to_id if column == "object_id" else object_id,
    )


__all__ = ["L2EntityGhostGraphMaintenanceMixin"]
