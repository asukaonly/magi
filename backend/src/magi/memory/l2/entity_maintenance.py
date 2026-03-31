"""Offline-style L2 entity catalog and knowledge-graph maintenance."""

from __future__ import annotations

import json
import re
import time
import uuid
from dataclasses import dataclass, field
from typing import Any

import aiosqlite

from ...core.logger import get_logger
from ...core.sqlite import sqlite_connection_async
from ..embedding.chunking import ChunkedText
from ..embedding.embedding_pipeline import (
    EmbeddingPipelineItem,
    MemoryEmbeddingPipeline,
)
from ..embedding.embedding_text_builders import build_l2_edge_embedding_text
from ..embedding.sqlite_vec_index import SqliteVecIndex
from .ontology import PREDICATE_REGISTRY, get_predicate_synonym_group
from .pipeline import L2Pipeline

logger = get_logger(__name__)

SCHEDULE_ID_L2_MAINTENANCE = "memory-l2-maintenance:global"
TARGET_KEY_L2_MAINTENANCE = "memory_l2_maintenance"


def _slugify_entity_id_suffix(value: str) -> str:
    """Match L2Pipeline._slugify for stable entity_id suffix comparison."""
    normalized = value.strip().casefold()
    slug = re.sub(r"[^a-z0-9]+", "-", normalized).strip("-")
    if slug:
        return slug
    return uuid.uuid5(uuid.NAMESPACE_URL, normalized).hex[:12]


def _canonical_entity_id(entity_type: str, canonical_name: str) -> str:
    return f"{entity_type}:{_slugify_entity_id_suffix(canonical_name)}"


def _merge_evidence_json(a: str, b: str) -> str:
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
    return json.dumps(out)


@dataclass
class L2EntityMaintenanceStats:
    """Counters from one maintenance run."""

    ghost_edges_rewritten: int = 0
    ghost_rows_merged: int = 0
    ghost_skipped_no_target: int = 0
    tom_entity_refs_rewritten: int = 0
    fragment_entities_merged: int = 0
    fragment_groups_processed: int = 0
    orphans_pruned: int = 0
    expired_future_intents: int = 0
    expired_assertions: int = 0
    open_predicates_consolidated: int = 0
    edges_embedded: int = 0
    errors: list[str] = field(default_factory=list)


class L2EntityMaintenance:
    """Best-effort cleanup: ghost graph refs, same-name type merges, low-mention orphans."""

    def __init__(
        self,
        *,
        db_path: str,
        embedding_service: Any | None = None,
        edge_vector_index: SqliteVecIndex | None = None,
    ) -> None:
        self._db_path = db_path
        self._embedding_service = embedding_service
        self._edge_vector_index = edge_vector_index

    # Default TTLs (seconds) for decay policies that lack an explicit expires_at.
    FAST_DECAY_TTL: float = 4 * 3600       # 4 hours
    SESSION_DECAY_TTL: float = 24 * 3600   # 24 hours

    async def run(
        self,
        *,
        min_mentions_to_keep: int = 2,
        resolve_ghosts: bool = True,
        merge_fragments: bool = True,
        prune_orphans: bool = True,
        expire_future_intents: bool = True,
        expire_decayed_assertions: bool = True,
        consolidate_open_predicates: bool = True,
        embed_edges: bool = True,
    ) -> L2EntityMaintenanceStats:
        stats = L2EntityMaintenanceStats()
        if resolve_ghosts:
            await self._resolve_ghost_graph_refs(stats)
        if merge_fragments:
            await self._merge_fragmented_entities(stats)
        if prune_orphans:
            await self._prune_orphan_low_mention_entities(stats, min_mentions=min_mentions_to_keep)
        if expire_future_intents:
            await self._expire_stale_future_intents(stats)
        if expire_decayed_assertions:
            await self._expire_decayed_assertions(stats)
        if consolidate_open_predicates:
            await self._consolidate_open_predicates(stats)
        if embed_edges:
            await self._embed_pending_edges(stats)
        if any(
            (
                stats.ghost_edges_rewritten,
                stats.ghost_rows_merged,
                stats.tom_entity_refs_rewritten,
                stats.fragment_entities_merged,
                stats.orphans_pruned,
                stats.expired_future_intents,
                stats.expired_assertions,
                stats.open_predicates_consolidated,
                stats.edges_embedded,
            )
        ):
            logger.info(
                "L2 entity maintenance completed",
                ghost_edges_rewritten=stats.ghost_edges_rewritten,
                ghost_rows_merged=stats.ghost_rows_merged,
                ghost_skipped=stats.ghost_skipped_no_target,
                tom_entity_refs_rewritten=stats.tom_entity_refs_rewritten,
                fragment_entities_merged=stats.fragment_entities_merged,
                fragment_groups=stats.fragment_groups_processed,
                orphans_pruned=stats.orphans_pruned,
                expired_future_intents=stats.expired_future_intents,
                expired_assertions=stats.expired_assertions,
                open_predicates_consolidated=stats.open_predicates_consolidated,
                edges_embedded=stats.edges_embedded,
            )
        return stats

    async def _resolve_ghost_graph_refs(self, stats: L2EntityMaintenanceStats) -> None:
        """Remap knowledge_graph rows whose subject/object ids are not in entity_catalog."""
        async with sqlite_connection_async(self._db_path) as db:
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
        if ":" not in ghost_id:
            return None
        prefix, suffix = ghost_id.split(":", 1)
        entity_type = prefix.strip().lower()
        if not entity_type or not suffix:
            return None
        async with sqlite_connection_async(self._db_path) as db:
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
        if len(entity_ids) == 1:
            return entity_ids[0]
        counts: dict[str, int] = {eid: 0 for eid in entity_ids}
        placeholders = ", ".join("?" for _ in entity_ids)
        async with sqlite_connection_async(self._db_path) as db:
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
        if from_id == to_id:
            return (0, 0)
        if column not in {"subject_id", "object_id"}:
            return (0, 0)
        rewritten = 0
        merged = 0
        now = time.time()
        async with sqlite_connection_async(self._db_path) as db:
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
                    subject_type = str(row[2])
                    predicate = str(row[3])
                    object_id = str(row[4])
                    object_type = str(row[5])
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
                        await db.execute("DELETE FROM knowledge_graph WHERE triple_id = ?", (triple_id,))
                        merged += 1
                await db.commit()
            except Exception as exc:
                await db.rollback()
                logger.warning("L2 ghost graph rewrite failed", error=str(exc))
                raise
        return (rewritten, merged)

    async def _rewrite_tom_entity_refs(self, stats: L2EntityMaintenanceStats) -> None:
        """Remap tom_* tables for ids not in catalog (same slug rule as knowledge_graph)."""
        async with sqlite_connection_async(self._db_path) as db:
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
            async with sqlite_connection_async(self._db_path) as db:
                await db.execute(
                    "UPDATE tom_trait_assertions SET entity_id = ? WHERE entity_id = ?",
                    (target, ghost_id),
                )
                await db.execute(
                    "UPDATE tom_trait_assertions SET target_entity_id = ? WHERE target_entity_id = ?",
                    (target, ghost_id),
                )
                await db.execute(
                    "UPDATE tom_snapshots SET entity_id = ? WHERE entity_id = ?",
                    (target, ghost_id),
                )
                await db.commit()
            stats.tom_entity_refs_rewritten += 1

    async def _merge_fragmented_entities(self, stats: L2EntityMaintenanceStats) -> None:
        """Merge catalog rows that share the same canonical name (case-insensitive) with mergeable types."""
        async with sqlite_connection_async(self._db_path) as db:
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
            async with sqlite_connection_async(self._db_path) as db:
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
                    logger.warning("L2 fragment merge failed", loser=loser, winner=winner, error=str(exc))
            stats.fragment_groups_processed += 1

    @staticmethod
    def _group_types_all_mergeable(types: list[str]) -> bool:
        for i, a in enumerate(types):
            for b in types[i + 1 :]:
                if not L2Pipeline._are_types_mergeable(a, b):
                    return False
        return True

    async def _merge_entity_into(self, winner_id: str, loser_id: str) -> None:
        if winner_id == loser_id:
            return
        now = time.time()
        async with sqlite_connection_async(self._db_path) as db:
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
        stats: L2EntityMaintenanceStats,
        *,
        min_mentions: int,
    ) -> None:
        async with sqlite_connection_async(self._db_path) as db:
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
                candidates = [(str(r["entity_id"]), int(r["mention_count"])) for r in await cur.fetchall()]

        for entity_id, _mc in candidates:
            if await self._entity_referenced_in_graph(entity_id):
                continue
            if await self._entity_referenced_in_tom(entity_id):
                continue
            try:
                await self._delete_entity_cascade(entity_id)
                stats.orphans_pruned += 1
            except Exception as exc:
                stats.errors.append(f"prune {entity_id}: {exc}")
                logger.warning("L2 orphan prune failed", entity_id=entity_id, error=str(exc))

    async def _entity_referenced_in_graph(self, entity_id: str) -> bool:
        async with sqlite_connection_async(self._db_path) as db:
            async with db.execute(
                """
                SELECT 1 FROM knowledge_graph
                WHERE subject_id = ? OR object_id = ?
                LIMIT 1
                """,
                (entity_id, entity_id),
            ) as cur:
                row = await cur.fetchone()
        return row is not None

    async def _entity_referenced_in_tom(self, entity_id: str) -> bool:
        async with sqlite_connection_async(self._db_path) as db:
            async with db.execute(
                """
                SELECT 1 FROM tom_trait_assertions
                WHERE entity_id = ? OR target_entity_id = ?
                LIMIT 1
                """,
                (entity_id, entity_id),
            ) as cur:
                if await cur.fetchone():
                    return True
            async with db.execute(
                "SELECT 1 FROM tom_snapshots WHERE entity_id = ? LIMIT 1",
                (entity_id,),
            ) as cur:
                if await cur.fetchone():
                    return True
        return False

    async def _delete_entity_cascade(self, entity_id: str) -> None:
        async with sqlite_connection_async(self._db_path) as db:
            await db.execute("DELETE FROM entity_aliases WHERE entity_id = ?", (entity_id,))
            await db.execute("DELETE FROM entity_mentions WHERE resolved_entity_id = ?", (entity_id,))
            await db.execute("DELETE FROM entity_catalog WHERE entity_id = ?", (entity_id,))
            await db.commit()

    async def _expire_stale_future_intents(self, stats: L2EntityMaintenanceStats) -> None:
        """Mark expired future_intent edges as 'expired'."""
        now = time.time()
        async with sqlite_connection_async(self._db_path) as db:
            cursor = await db.execute(
                """
                UPDATE knowledge_graph
                SET status = 'expired', updated_at = ?
                WHERE fact_kind = 'future_intent'
                  AND expires_at IS NOT NULL AND expires_at < ?
                  AND status = 'active'
                """,
                (now, now),
            )
            stats.expired_future_intents = cursor.rowcount
            await db.commit()

    async def _expire_decayed_assertions(self, stats: L2EntityMaintenanceStats) -> None:
        """Expire assertions whose decay policy indicates they have outlived their TTL.

        - ``fast_decay`` (annoyance, irritation, frustration): expire after
          ``FAST_DECAY_TTL`` seconds since last update.
        - ``session_decay`` (mood, engagement): expire after
          ``SESSION_DECAY_TTL`` seconds since last update.
        - Assertions that already have an explicit ``expires_at`` in the past
          are also marked expired.
        """
        now = time.time()
        fast_cutoff = now - self.FAST_DECAY_TTL
        session_cutoff = now - self.SESSION_DECAY_TTL
        async with sqlite_connection_async(self._db_path) as db:
            cursor = await db.execute(
                """
                UPDATE tom_trait_assertions
                SET validation_state = 'expired', updated_at = ?
                WHERE validation_state NOT IN ('expired', 'user_rejected', 'contradicted')
                  AND (
                    (expires_at IS NOT NULL AND expires_at < ?)
                    OR (decay_policy = 'fast_decay' AND updated_at < ?)
                    OR (decay_policy = 'session_decay' AND updated_at < ?)
                  )
                """,
                (now, now, fast_cutoff, session_cutoff),
            )
            stats.expired_assertions = cursor.rowcount
            await db.commit()

    async def _consolidate_open_predicates(self, stats: L2EntityMaintenanceStats) -> None:
        """Rewrite non-core predicates to their core synonym when a mapping exists.

        For each active edge whose predicate is not in ``PREDICATE_REGISTRY``,
        check ``_PREDICATE_SYNONYM_GROUPS``. If the open predicate's synonym
        group contains a core predicate, rewrite the edge's predicate and
        recalculate its ``triple_id``.
        """
        core_by_group: dict[str, str] = {}
        for pred in PREDICATE_REGISTRY:
            group = get_predicate_synonym_group(pred)
            if group and group not in core_by_group:
                core_by_group[group] = pred

        async with sqlite_connection_async(self._db_path) as db:
            db.row_factory = aiosqlite.Row
            rows = await db.execute_fetchall(
                """
                SELECT triple_id, subject_id, predicate, object_id
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
                if group is None or group not in core_by_group:
                    continue
                core_predicate = core_by_group[group]
                new_triple_id = str(
                    uuid.uuid5(
                        uuid.NAMESPACE_URL,
                        f"{row['subject_id']}:{core_predicate}:{row['object_id']}",
                    )
                )
                existing = await db.execute_fetchall(
                    "SELECT triple_id FROM knowledge_graph WHERE triple_id = ?",
                    (new_triple_id,),
                )
                if existing:
                    await db.execute(
                        """
                        UPDATE knowledge_graph
                        SET status = 'superseded', updated_at = ?
                        WHERE triple_id = ?
                        """,
                        (now, row["triple_id"]),
                    )
                else:
                    await db.execute(
                        """
                        UPDATE knowledge_graph
                        SET predicate = ?, triple_id = ?, updated_at = ?
                        WHERE triple_id = ?
                        """,
                        (core_predicate, new_triple_id, now, row["triple_id"]),
                    )
                consolidated += 1
            if consolidated:
                await db.commit()
            stats.open_predicates_consolidated = consolidated

    async def _embed_pending_edges(
        self,
        stats: L2EntityMaintenanceStats,
        *,
        batch_limit: int = 200,
    ) -> None:
        """Embed knowledge_graph edges that have embedding_status='pending'."""
        if self._embedding_service is None or self._edge_vector_index is None:
            return

        pipeline = MemoryEmbeddingPipeline(
            embedding_service=self._embedding_service,
            vector_index=self._edge_vector_index,
        )

        async with sqlite_connection_async(self._db_path) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute(
                "SELECT kg.triple_id, kg.subject_id, kg.predicate, kg.object_id, "
                "kg.evidence_text, kg.natural_summary, "
                "sc.canonical_name AS subject_name, oc.canonical_name AS object_name "
                "FROM knowledge_graph kg "
                "LEFT JOIN entity_catalog sc ON sc.entity_id = kg.subject_id "
                "LEFT JOIN entity_catalog oc ON oc.entity_id = kg.object_id "
                "WHERE kg.embedding_status = 'pending' AND kg.status = 'active' "
                "ORDER BY kg.updated_at DESC LIMIT ?",
                (batch_limit,),
            ) as cur:
                rows = await cur.fetchall()

        if not rows:
            return

        items: list[EmbeddingPipelineItem] = []
        for row in rows:
            text = build_l2_edge_embedding_text(
                subject_id=str(row["subject_id"]),
                predicate=str(row["predicate"]),
                object_id=str(row["object_id"]),
                evidence_text=row["evidence_text"],
                natural_summary=row["natural_summary"],
                subject_name=row["subject_name"],
                object_name=row["object_name"],
            )
            if not text.strip():
                continue
            triple_id = str(row["triple_id"])
            items.append(
                EmbeddingPipelineItem(
                    parent_id=triple_id,
                    chunks=[
                        ChunkedText(
                            chunk_id=triple_id,
                            text=text,
                            chunk_index=0,
                            char_start=0,
                            char_end=len(text),
                            token_estimate=max(1, len(text) // 4),
                        )
                    ],
                    metadata={"kind": "edge"},
                )
            )

        if not items:
            return

        try:
            results = await pipeline.upsert_items(items)
            embedded_ids = [r.parent_id for r in results]
            if embedded_ids:
                placeholders = ", ".join("?" for _ in embedded_ids)
                async with sqlite_connection_async(self._db_path) as db:
                    await db.execute(
                        f"UPDATE knowledge_graph SET embedding_status = 'ready' "
                        f"WHERE triple_id IN ({placeholders})",
                        tuple(embedded_ids),
                    )
                    await db.commit()
                stats.edges_embedded = len(embedded_ids)
        except Exception as exc:
            logger.warning("Failed to embed pending edges: %s", exc)
            stats.errors.append(f"edge_embedding: {exc}")
