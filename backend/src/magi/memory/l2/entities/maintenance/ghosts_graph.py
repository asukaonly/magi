"""Knowledge-graph ghost entity rewrite helpers for L2 maintenance."""

from __future__ import annotations

import time
from typing import Any, cast

import aiosqlite

from .....core.logger import get_logger
from .....core.sqlite import sqlite_connection_async
from ...graph.relationship_rekey_coordinator import RelationshipIdentityRekeyCoordinator
from ...graph.relationship_rekey_references import (
    rewrite_materialized_relationship_references,
)
from .ghosts_common import (
    L2EntityGhostHostMixin,
    _CatalogMaintenanceStatsProtocol,
    _canonical_entity_id,
)

logger = get_logger("magi.memory.l2.entities.maintenance")


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
        """Rewrite one graph endpoint and merge only same-scope duplicates."""
        host = self._catalog_maintenance_host()
        if from_id == to_id:
            return (0, 0)
        if column not in {"subject_id", "object_id"}:
            return (0, 0)
        rewritten = 0
        merged = 0
        invalidated_vector_ids: set[str] = set()
        rewritten_references = {from_id: to_id}
        now = time.time()
        async with sqlite_connection_async(host._db_path) as db:
            db.row_factory = aiosqlite.Row
            await db.execute("BEGIN IMMEDIATE")
            try:
                rows = await self._fetch_graph_rewrite_rows(db, column, from_id)
                for row in rows:
                    current = await db.execute_fetchall(
                        "SELECT * FROM knowledge_graph WHERE triple_id = ?",
                        (row["triple_id"],),
                    )
                    if not current:
                        continue
                    current_row = current[0]
                    result = await RelationshipIdentityRekeyCoordinator(db).rekey(
                        source_triple_id=str(current_row["triple_id"]),
                        subject_id=(
                            to_id if column == "subject_id" else str(current_row["subject_id"])
                        ),
                        predicate=str(current_row["predicate"]),
                        object_id=(
                            to_id if column == "object_id" else str(current_row["object_id"])
                        ),
                        now=now,
                        reference_replacements={from_id: to_id},
                        rewrite_materialized_references=False,
                    )
                    rewritten += int(result.rewritten)
                    merged += int(result.merged)
                    invalidated_vector_ids.update(result.invalidated_vector_ids)
                    rewritten_references.update(result.rewritten_reference_ids)
                await rewrite_materialized_relationship_references(
                    db,
                    rewritten_references,
                )
                await db.commit()
            except Exception as exc:
                await db.rollback()
                logger.warning("L2 ghost graph rewrite failed", error=str(exc))
                raise
        await self._delete_invalidated_edge_vectors(invalidated_vector_ids)
        return (rewritten, merged)

    async def _fetch_graph_rewrite_rows(
        self,
        db: aiosqlite.Connection,
        column: str,
        from_id: str,
    ) -> list[Any]:
        async with db.execute(
            f"""
            SELECT triple_id
            FROM knowledge_graph
            WHERE {column} = ?
            ORDER BY triple_id
            """,
            (from_id,),
        ) as cur:
            return cast(list[Any], await cur.fetchall())

    async def _merge_kg_ids_locked(
        self,
        db: aiosqlite.Connection,
        column: str,
        loser_id: str,
        winner_id: str,
        now: float,
    ) -> set[str]:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            f"SELECT triple_id FROM knowledge_graph WHERE {column} = ? ORDER BY triple_id",
            (loser_id,),
        ) as cur:
            rows = await cur.fetchall()
        invalidated_vector_ids: set[str] = set()
        rewritten_references = {loser_id: winner_id}
        for row in rows:
            current = await db.execute_fetchall(
                "SELECT * FROM knowledge_graph WHERE triple_id = ?",
                (row["triple_id"],),
            )
            if not current:
                continue
            current_row = current[0]
            result = await RelationshipIdentityRekeyCoordinator(db).rekey(
                source_triple_id=str(current_row["triple_id"]),
                subject_id=(
                    winner_id if column == "subject_id" else str(current_row["subject_id"])
                ),
                predicate=str(current_row["predicate"]),
                object_id=(winner_id if column == "object_id" else str(current_row["object_id"])),
                now=now,
                reference_replacements={loser_id: winner_id},
                rewrite_materialized_references=False,
            )
            invalidated_vector_ids.update(result.invalidated_vector_ids)
            rewritten_references.update(result.rewritten_reference_ids)
        await rewrite_materialized_relationship_references(
            db,
            rewritten_references,
        )
        return invalidated_vector_ids

    async def _delete_invalidated_edge_vectors(self, triple_ids: set[str]) -> None:
        host = self._catalog_maintenance_host()
        vector_index = getattr(host, "_edge_vector_index", None)
        if vector_index is None:
            return
        for triple_id in sorted(triple_ids):
            try:
                await vector_index.delete_entity(entity_id=triple_id)
            except Exception as exc:
                logger.warning(
                    "L2 relationship vector cleanup failed",
                    triple_id=triple_id,
                    error=str(exc),
                )


__all__ = ["L2EntityGhostGraphMaintenanceMixin"]
