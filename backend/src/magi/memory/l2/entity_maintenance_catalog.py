"""Entity catalog cleanup helpers for L2 entity maintenance."""

from __future__ import annotations

import json
import re
import time
import uuid
from typing import Any, Protocol

import aiosqlite

from ...core.logger import get_logger
from ...core.sqlite import sqlite_connection_async
from .pipeline import L2Pipeline

logger = get_logger("magi.memory.l2.entity_maintenance")

# Maximum number of evidence event IDs retained per edge/facet merge.
# When exceeded, the oldest entries are dropped.
MAX_EVIDENCE_EVENT_IDS = 50


def _slugify_entity_id_suffix(value: str) -> str:
    """Match L2Pipeline._slugify for stable entity_id suffix comparison."""
    normalized = value.strip().casefold()
    slug = re.sub(r"[^a-z0-9]+", "-", normalized).strip("-")
    if slug:
        return slug
    return uuid.uuid5(uuid.NAMESPACE_URL, normalized).hex[:12]


def _canonical_entity_id(entity_type: str, canonical_name: str) -> str:
    return f"{entity_type}:{_slugify_entity_id_suffix(canonical_name)}"


def _merge_evidence_json(a: str, b: str, *, max_items: int = MAX_EVIDENCE_EVENT_IDS) -> str:
    try:
        la = json.loads(a or "[]")
        lb = json.loads(b or "[]")
    except json.JSONDecodeError:
        return a or b or "[]"
    if not isinstance(la, list):
        la = []
    if not isinstance(lb, list):
        lb = []
    seen: set[str] = set()
    out: list[Any] = []
    for item in la + lb:
        s = str(item)
        if s not in seen:
            seen.add(s)
            out.append(item)
    if len(out) > max_items:
        out = out[-max_items:]
    return json.dumps(out)


class _CatalogMaintenanceStatsProtocol(Protocol):
    ghost_edges_rewritten: int
    ghost_rows_merged: int
    ghost_skipped_no_target: int
    tom_entity_refs_rewritten: int
    fragment_entities_merged: int
    fragment_groups_processed: int
    orphans_pruned: int
    errors: list[str]


class _CatalogMaintenanceHostProtocol(Protocol):
    _db_path: str


class L2EntityCatalogMaintenanceMixin:
    """Maintain catalog references, fragmented entities, and low-mention orphans."""

    async def _resolve_ghost_graph_refs(
        self,
        stats: _CatalogMaintenanceStatsProtocol,
    ) -> None:
        """Remap knowledge_graph rows whose subject/object ids are not in entity_catalog."""
        host = self._catalog_maintenance_host()
        async with sqlite_connection_async(host._db_path) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute(
                """
                SELECT DISTINCT object_id FROM knowledge_graph
                WHERE object_id NOT IN (SELECT entity_id FROM entity_catalog)
                  AND object_id NOT LIKE 'other:%'
                """
            ) as cur:
                ghost_objects = [str(r[0]) for r in await cur.fetchall()]
            async with db.execute(
                """
                SELECT DISTINCT subject_id FROM knowledge_graph
                WHERE subject_id NOT IN (SELECT entity_id FROM entity_catalog)
                  AND subject_id NOT LIKE 'other:%'
                  AND subject_id NOT LIKE 'user:%'
                """
            ) as cur:
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

        await self._rewrite_tom_entity_refs(stats)

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
        if not matches:
            return None
        return await self._pick_entity_by_mention_count(matches)

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
                    rows = await cur.fetchall()
                for row in rows:
                    triple_id = str(row[0])
                    subject_id = str(row[1])
                    predicate = str(row[3])
                    object_id = str(row[4])
                    if column == "subject_id":
                        new_subject = to_id
                        new_object = object_id
                    else:
                        new_subject = subject_id
                        new_object = to_id
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
                        if column == "subject_id":
                            await db.execute(
                                "UPDATE knowledge_graph SET subject_id = ?, updated_at = ? WHERE triple_id = ?",
                                (to_id, now, triple_id),
                            )
                        else:
                            await db.execute(
                                "UPDATE knowledge_graph SET object_id = ?, updated_at = ? WHERE triple_id = ?",
                                (to_id, now, triple_id),
                            )
                        rewritten += 1
                    else:
                        dup_id = str(dup[0])
                        ev = _merge_evidence_json(str(row[7]), str(dup[1]))
                        obs = int(row[8]) + int(dup[2])
                        first_at = min(float(row[9]), float(dup[3]))
                        last_at = max(float(row[10]), float(dup[4]))
                        conf = max(float(row[6]), float(dup[5]))
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
                        await db.execute(
                            "DELETE FROM knowledge_graph WHERE triple_id = ?", (triple_id,)
                        )
                        merged += 1
                await db.commit()
            except Exception as exc:
                await db.rollback()
                logger.warning("L2 ghost graph rewrite failed", error=str(exc))
                raise
        return (rewritten, merged)

    async def _rewrite_tom_entity_refs(
        self,
        stats: _CatalogMaintenanceStatsProtocol,
    ) -> None:
        """Remap tom_* tables for ids not in catalog."""
        host = self._catalog_maintenance_host()
        async with sqlite_connection_async(host._db_path) as db:
            async with db.execute(
                """
                SELECT DISTINCT entity_id FROM tom_trait_assertions
                WHERE entity_id NOT IN (SELECT entity_id FROM entity_catalog)
                  AND entity_id NOT LIKE 'user:%'
                """
            ) as cur:
                ghosts = [str(r[0]) for r in await cur.fetchall()]
        for ghost_id in ghosts:
            target = await self._resolve_ghost_to_catalog_id(ghost_id)
            if not target:
                continue
            async with sqlite_connection_async(host._db_path) as db:
                await db.execute("BEGIN IMMEDIATE")
                try:
                    db.row_factory = aiosqlite.Row
                    async with db.execute(
                        """
                        SELECT a.assertion_id AS ghost_aid, a.confidence_score AS ghost_conf,
                               b.assertion_id AS target_aid, b.confidence_score AS target_conf
                        FROM tom_trait_assertions a
                        JOIN tom_trait_assertions b
                          ON b.entity_id = ? AND a.entity_type = b.entity_type
                             AND a.trait_name = b.trait_name AND a.target_entity_id = b.target_entity_id
                        WHERE a.entity_id = ?
                        """,
                        (target, ghost_id),
                    ) as cur:
                        conflicts = await cur.fetchall()
                    for conflict in conflicts:
                        if float(conflict["ghost_conf"]) > float(conflict["target_conf"]):
                            await db.execute(
                                "DELETE FROM tom_trait_assertions WHERE assertion_id = ?",
                                (conflict["target_aid"],),
                            )
                        else:
                            await db.execute(
                                "DELETE FROM tom_trait_assertions WHERE assertion_id = ?",
                                (conflict["ghost_aid"],),
                            )
                    await db.execute(
                        "UPDATE tom_trait_assertions SET entity_id = ? WHERE entity_id = ?",
                        (target, ghost_id),
                    )
                    await db.execute(
                        "UPDATE tom_trait_assertions SET target_entity_id = ? WHERE target_entity_id = ?",
                        (target, ghost_id),
                    )
                    async with db.execute(
                        "SELECT 1 FROM tom_snapshots WHERE entity_id = ? LIMIT 1",
                        (target,),
                    ) as cur:
                        target_has_snapshot = await cur.fetchone() is not None
                    if target_has_snapshot:
                        await db.execute(
                            "DELETE FROM tom_snapshots WHERE entity_id = ?",
                            (ghost_id,),
                        )
                    else:
                        await db.execute(
                            "UPDATE tom_snapshots SET entity_id = ? WHERE entity_id = ?",
                            (target, ghost_id),
                        )
                    await db.commit()
                except Exception:
                    await db.rollback()
                    raise
            stats.tom_entity_refs_rewritten += 1

    async def _merge_fragmented_entities(
        self,
        stats: _CatalogMaintenanceStatsProtocol,
    ) -> None:
        """Merge catalog rows that share the same canonical name with mergeable types."""
        host = self._catalog_maintenance_host()
        async with sqlite_connection_async(host._db_path) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute(
                """
                SELECT LOWER(TRIM(canonical_name)) AS ck, COUNT(*) AS n
                FROM entity_catalog
                GROUP BY ck
                HAVING n >= 2
                """
            ) as cur:
                keys = [str(r["ck"]) for r in await cur.fetchall()]

        for ck in keys:
            async with sqlite_connection_async(host._db_path) as db:
                db.row_factory = aiosqlite.Row
                async with db.execute(
                    """
                    SELECT entity_id, canonical_name, entity_type
                    FROM entity_catalog
                    WHERE LOWER(TRIM(canonical_name)) = ?
                    """,
                    (ck,),
                ) as cur:
                    group = await cur.fetchall()
            if len(group) < 2:
                continue
            types = [str(r["entity_type"]) for r in group]
            if not self._group_types_all_mergeable(types):
                continue
            entity_ids = [str(r["entity_id"]) for r in group]
            winner = await self._pick_entity_by_mention_count(entity_ids)
            losers = [eid for eid in entity_ids if eid != winner]
            for loser in losers:
                try:
                    await self._merge_entity_into(winner, loser)
                    stats.fragment_entities_merged += 1
                except Exception as exc:
                    stats.errors.append(f"merge {loser}->{winner}: {exc}")
                    logger.warning(
                        "L2 fragment merge failed", loser=loser, winner=winner, error=str(exc)
                    )
            stats.fragment_groups_processed += 1

    @staticmethod
    def _group_types_all_mergeable(types: list[str]) -> bool:
        for i, a in enumerate(types):
            for b in types[i + 1 :]:
                if not L2Pipeline._are_types_mergeable(a, b):
                    return False
        return True

    async def _merge_entity_into(self, winner_id: str, loser_id: str) -> None:
        host = self._catalog_maintenance_host()
        if winner_id == loser_id:
            return
        now = time.time()
        async with sqlite_connection_async(host._db_path) as db:
            await db.execute("BEGIN IMMEDIATE")
            try:
                await db.execute(
                    "UPDATE entity_mentions SET resolved_entity_id = ? WHERE resolved_entity_id = ?",
                    (winner_id, loser_id),
                )
                async with db.execute(
                    "SELECT alias_text, normalized_alias, confidence FROM entity_aliases WHERE entity_id = ?",
                    (loser_id,),
                ) as cur:
                    aliases = await cur.fetchall()
                for al in aliases:
                    alias_text, norm, conf = str(al[0]), str(al[1]), float(al[2])
                    await db.execute(
                        """
                        INSERT INTO entity_aliases(entity_id, alias_text, normalized_alias, confidence, created_at, updated_at)
                        VALUES (?, ?, ?, ?, ?, ?)
                        ON CONFLICT(entity_id, normalized_alias) DO UPDATE SET
                            confidence = MAX(entity_aliases.confidence, excluded.confidence),
                            updated_at = excluded.updated_at
                        """,
                        (winner_id, alias_text, norm, conf, now, now),
                    )
                await db.execute("DELETE FROM entity_aliases WHERE entity_id = ?", (loser_id,))

                await self._merge_kg_ids_locked(db, "subject_id", loser_id, winner_id, now)
                await self._merge_kg_ids_locked(db, "object_id", loser_id, winner_id, now)

                await db.execute(
                    "UPDATE tom_trait_assertions SET entity_id = ? WHERE entity_id = ?",
                    (winner_id, loser_id),
                )
                await db.execute(
                    "UPDATE tom_trait_assertions SET target_entity_id = ? WHERE target_entity_id = ?",
                    (winner_id, loser_id),
                )
                await db.execute(
                    "UPDATE tom_snapshots SET entity_id = ? WHERE entity_id = ?",
                    (winner_id, loser_id),
                )
                await db.execute(
                    "UPDATE OR IGNORE entity_facets SET entity_id = ? WHERE entity_id = ?",
                    (winner_id, loser_id),
                )
                await db.execute("DELETE FROM entity_facets WHERE entity_id = ?", (loser_id,))
                await db.execute("DELETE FROM entity_catalog WHERE entity_id = ?", (loser_id,))
                await db.commit()
            except Exception:
                await db.rollback()
                raise

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

    async def _prune_orphan_low_mention_entities(
        self,
        stats: _CatalogMaintenanceStatsProtocol,
        *,
        min_mentions: int,
    ) -> None:
        host = self._catalog_maintenance_host()
        async with sqlite_connection_async(host._db_path) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute(
                """
                SELECT c.entity_id,
                       COUNT(m.mention_id) AS mention_count
                FROM entity_catalog c
                LEFT JOIN entity_mentions m ON m.resolved_entity_id = c.entity_id
                GROUP BY c.entity_id
                HAVING mention_count < ?
                """,
                (min_mentions,),
            ) as cur:
                candidates = [
                    (str(r["entity_id"]), int(r["mention_count"])) for r in await cur.fetchall()
                ]

        for entity_id, _mc in candidates:
            try:
                pruned = await self._check_and_delete_orphan(entity_id)
                if pruned:
                    stats.orphans_pruned += 1
            except Exception as exc:
                stats.errors.append(f"prune {entity_id}: {exc}")
                logger.warning("L2 orphan prune failed", entity_id=entity_id, error=str(exc))

    async def _check_and_delete_orphan(self, entity_id: str) -> bool:
        """Atomically verify entity is unreferenced in KG/assertions and delete it."""
        host = self._catalog_maintenance_host()
        async with sqlite_connection_async(host._db_path) as db:
            await db.execute("BEGIN IMMEDIATE")
            try:
                async with db.execute(
                    "SELECT 1 FROM knowledge_graph WHERE subject_id = ? OR object_id = ? LIMIT 1",
                    (entity_id, entity_id),
                ) as cur:
                    if await cur.fetchone():
                        await db.rollback()
                        return False
                async with db.execute(
                    "SELECT 1 FROM tom_trait_assertions WHERE entity_id = ? OR target_entity_id = ? LIMIT 1",
                    (entity_id, entity_id),
                ) as cur:
                    if await cur.fetchone():
                        await db.rollback()
                        return False
                await db.execute("DELETE FROM tom_snapshots WHERE entity_id = ?", (entity_id,))
                await db.execute("DELETE FROM entity_facets WHERE entity_id = ?", (entity_id,))
                await db.execute("DELETE FROM entity_aliases WHERE entity_id = ?", (entity_id,))
                await db.execute(
                    "DELETE FROM entity_mentions WHERE resolved_entity_id = ?", (entity_id,)
                )
                await db.execute("DELETE FROM entity_catalog WHERE entity_id = ?", (entity_id,))
                await db.commit()
                return True
            except Exception:
                await db.rollback()
                raise

    def _catalog_maintenance_host(self) -> _CatalogMaintenanceHostProtocol:
        return self  # type: ignore[return-value]
