"""Entity catalog fragment and orphan cleanup helpers for L2 maintenance."""

from __future__ import annotations

import time

import aiosqlite

from .....core.logger import get_logger
from .....core.sqlite import sqlite_connection_async
from ...assertions.assertion_rekey_coordinator import AssertionEntityRekeyCoordinator
from ...pipeline import L2Pipeline
from ..identity import CONCEPT_ENTITY_TYPES
from .ghosts import (
    MAX_EVIDENCE_EVENT_IDS,
    L2EntityGhostMaintenanceMixin,
    _CatalogMaintenanceHostProtocol,
    _CatalogMaintenanceStatsProtocol,
    _canonical_entity_id,
    _merge_evidence_json,
)
from .ghosts_tom import _refresh_tom_snapshot_after_rekey

logger = get_logger("magi.memory.l2.entities.maintenance")


class L2EntityCatalogMaintenanceMixin(L2EntityGhostMaintenanceMixin):
    """Maintain fragmented entities and low-mention orphans."""

    async def _merge_fragmented_entities(
        self,
        stats: _CatalogMaintenanceStatsProtocol,
    ) -> None:
        """Merge catalog rows that share the same canonical name with mergeable types."""
        host = self._catalog_maintenance_host()
        async with sqlite_connection_async(host._db_path) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute("""
                SELECT LOWER(TRIM(canonical_name)) AS ck, COUNT(*) AS n
                FROM entity_catalog
                GROUP BY ck
                HAVING n >= 2
                """) as cur:
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
            if any(kind not in CONCEPT_ENTITY_TYPES for kind in types) or any(":source:" in str(row["entity_id"]) for row in group):
                continue
            if not self._group_types_all_mergeable(types):
                continue
            entity_ids = [str(r["entity_id"]) for r in group]
            winner = await self._pick_entity_by_mention_count(entity_ids)
            losers = [eid for eid in entity_ids if eid != winner]
            merged_any = False
            for loser in losers:
                try:
                    await self._merge_entity_into(winner, loser)
                    stats.fragment_entities_merged += 1
                    merged_any = True
                except Exception as exc:
                    stats.errors.append(f"merge {loser}->{winner}: {exc}")
                    logger.warning(
                        "L2 fragment merge failed", loser=loser, winner=winner, error=str(exc)
                    )
            if merged_any:
                try:
                    snapshot = await _refresh_tom_snapshot_after_rekey(host, winner)
                    stats.snapshots_refreshed += int(snapshot is not None)
                except Exception as exc:
                    stats.errors.append(f"refresh snapshot {winner}: {exc}")
                    logger.warning(
                        "L2 snapshot refresh after entity merge failed",
                        entity_id=winner,
                        error=str(exc),
                    )
            stats.fragment_groups_processed += 1

    @staticmethod
    def _group_types_all_mergeable(types: list[str]) -> bool:
        for i, a in enumerate(types):
            for b in types[i + 1 :]:
                if not L2Pipeline._are_types_mergeable(a, b):
                    return False
        return True

    async def _merge_entity_into(
        self,
        winner_id: str,
        loser_id: str,
    ) -> None:
        host = self._catalog_maintenance_host()
        if winner_id == loser_id:
            return
        now = time.time()
        invalidated_vector_ids: set[str] = set()
        async with sqlite_connection_async(host._db_path) as db:
            await db.execute("BEGIN IMMEDIATE")
            try:
                await db.execute(
                    "UPDATE entity_mentions SET resolved_entity_id = ? WHERE resolved_entity_id = ?",
                    (winner_id, loser_id),
                )
                async with db.execute(
                    """
                    SELECT canonical_name, canonical_name_is_independent
                    FROM entity_catalog WHERE entity_id = ?
                    """,
                    (loser_id,),
                ) as cur:
                    loser_catalog = await cur.fetchone()
                async with db.execute(
                    """
                    SELECT alias_text, normalized_alias, confidence, is_independent
                    FROM entity_aliases WHERE entity_id = ?
                    """,
                    (loser_id,),
                ) as cur:
                    aliases = await cur.fetchall()
                for al in aliases:
                    alias_text, norm, conf, independent = (
                        str(al[0]),
                        str(al[1]),
                        float(al[2]),
                        int(al[3]),
                    )
                    await db.execute(
                        """
                        INSERT INTO entity_aliases(
                            entity_id, alias_text, normalized_alias, confidence,
                            is_independent, created_at, updated_at
                        ) VALUES (?, ?, ?, ?, ?, ?, ?)
                        ON CONFLICT(entity_id, normalized_alias) DO UPDATE SET
                            confidence = MAX(entity_aliases.confidence, excluded.confidence),
                            is_independent = MAX(
                                entity_aliases.is_independent,
                                excluded.is_independent
                            ),
                            updated_at = excluded.updated_at
                        """,
                        (winner_id, alias_text, norm, conf, independent, now, now),
                    )
                if loser_catalog is not None and bool(loser_catalog[1]):
                    loser_name = str(loser_catalog[0]).strip()
                    if loser_name:
                        await db.execute(
                            """
                            INSERT INTO entity_aliases(
                                entity_id, alias_text, normalized_alias, confidence,
                                is_independent, created_at, updated_at
                            ) VALUES (?, ?, ?, 1.0, 1, ?, ?)
                            ON CONFLICT(entity_id, normalized_alias) DO UPDATE SET
                                is_independent = 1,
                                confidence = MAX(entity_aliases.confidence, 1.0),
                                updated_at = excluded.updated_at
                            """,
                            (winner_id, loser_name, loser_name.casefold(), now, now),
                        )
                async with db.execute(
                    """
                    SELECT name_kind, normalized_name, display_name, event_id,
                           confidence, created_at, updated_at
                    FROM entity_name_evidence
                    WHERE entity_id = ?
                    """,
                    (loser_id,),
                ) as cur:
                    name_evidence = await cur.fetchall()
                for evidence in name_evidence:
                    await db.execute(
                        """
                        INSERT INTO entity_name_evidence(
                            entity_id, name_kind, normalized_name, display_name,
                            event_id, confidence, created_at, updated_at
                        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                        ON CONFLICT(
                            entity_id, name_kind, normalized_name, event_id
                        ) DO UPDATE SET
                            confidence = MAX(
                                entity_name_evidence.confidence,
                                excluded.confidence
                            ),
                            updated_at = MAX(
                                entity_name_evidence.updated_at,
                                excluded.updated_at
                            )
                        """,
                        (winner_id, *tuple(evidence)),
                    )
                await db.execute(
                    "DELETE FROM entity_name_evidence WHERE entity_id = ?",
                    (loser_id,),
                )
                await db.execute("DELETE FROM entity_aliases WHERE entity_id = ?", (loser_id,))

                invalidated_vector_ids.update(
                    await self._merge_kg_ids_locked(db, "subject_id", loser_id, winner_id, now)
                )
                invalidated_vector_ids.update(
                    await self._merge_kg_ids_locked(db, "object_id", loser_id, winner_id, now)
                )

                await AssertionEntityRekeyCoordinator(db).rekey(
                    source_entity_id=loser_id,
                    target_entity_id=winner_id,
                    now=now,
                )
                affected_claim_ids = await self._rekey_claim_entity_refs_locked(
                    db,
                    source_entity_id=loser_id,
                    target_entity_id=winner_id,
                    now=now,
                )
                if affected_claim_ids:
                    placeholders = ", ".join("?" for _ in affected_claim_ids)
                    await db.execute(
                        f"""
                        UPDATE l2_claim_projection_outcomes
                        SET invalidated_at = ?, invalidated_reason = 'entity_merged'
                        WHERE claim_id IN ({placeholders})
                          AND target_kind = 'route'
                          AND invalidated_at IS NULL
                        """,
                        (now, *sorted(affected_claim_ids)),
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
        await self._delete_invalidated_edge_vectors(invalidated_vector_ids)

    async def _rekey_claim_entity_refs_locked(
        self,
        db: aiosqlite.Connection,
        *,
        source_entity_id: str,
        target_entity_id: str,
        now: float,
    ) -> set[str]:
        """Append canonical ref versions for Claims whose latest ref was merged."""

        db.row_factory = aiosqlite.Row
        async with db.execute(
            """
            WITH ranked_refs AS (
                SELECT refs.claim_id, refs.ref_role, refs.entity_id,
                       ROW_NUMBER() OVER (
                           PARTITION BY refs.claim_id, refs.ref_role
                           ORDER BY refs.resolution_version DESC,
                                    refs.created_at DESC,
                                    refs.entity_id
                       ) AS row_number
                FROM l2_claim_entity_refs AS refs
                JOIN l2_grounded_claims AS claims
                  ON claims.claim_id = refs.claim_id
                 AND claims.availability = 'active'
                WHERE refs.invalidated_at IS NULL
            ),
            direct_subjects AS (
                SELECT claims.claim_id, 'subject' AS ref_role
                FROM l2_grounded_claims AS claims
                WHERE claims.availability = 'active'
                  AND claims.subject_ref = ?
                  AND NOT EXISTS (
                      SELECT 1 FROM ranked_refs AS ranked
                      WHERE ranked.claim_id = claims.claim_id
                        AND ranked.ref_role = 'subject'
                        AND ranked.row_number = 1
                  )
            )
            SELECT claim_id, ref_role
            FROM ranked_refs
            WHERE row_number = 1 AND entity_id = ?
            UNION
            SELECT claim_id, ref_role FROM direct_subjects
            ORDER BY claim_id, ref_role
            """,
            (source_entity_id, source_entity_id),
        ) as cursor:
            affected_refs = [
                (str(row["claim_id"]), str(row["ref_role"])) for row in await cursor.fetchall()
            ]

        for claim_id, ref_role in affected_refs:
            async with db.execute(
                """
                SELECT COALESCE(MAX(resolution_version), 0)
                FROM l2_claim_entity_refs
                WHERE claim_id = ? AND ref_role = ?
                """,
                (claim_id, ref_role),
            ) as cursor:
                row = await cursor.fetchone()
            next_version = int(row[0] or 0) + 1 if row is not None else 1
            await db.execute(
                """
                UPDATE l2_claim_entity_refs
                SET invalidated_at = ?, invalidated_reason = 'entity_merged'
                WHERE claim_id = ? AND ref_role = ? AND invalidated_at IS NULL
                """,
                (now, claim_id, ref_role),
            )
            await db.execute(
                """
                INSERT INTO l2_claim_entity_refs(
                    claim_id, ref_role, entity_id, resolution_version, created_at
                ) VALUES (?, ?, ?, ?, ?)
                """,
                (claim_id, ref_role, target_entity_id, next_version, now),
            )
        return {claim_id for claim_id, _ref_role in affected_refs}

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
                WHERE c.canonical_name_is_independent = 0
                  AND NOT EXISTS (
                      SELECT 1 FROM entity_aliases AS alias
                      WHERE alias.entity_id = c.entity_id
                        AND alias.is_independent = 1
                  )
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
                    """
                    SELECT 1 FROM entity_catalog AS catalog
                    WHERE catalog.entity_id = ?
                      AND (
                          catalog.canonical_name_is_independent = 1
                          OR EXISTS (
                              SELECT 1 FROM entity_aliases AS alias
                              WHERE alias.entity_id = catalog.entity_id
                                AND alias.is_independent = 1
                          )
                      )
                    """,
                    (entity_id,),
                ) as cur:
                    if await cur.fetchone():
                        await db.rollback()
                        return False
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
                async with db.execute(
                    """
                    SELECT 1
                    FROM l2_grounded_claims AS claims
                    LEFT JOIN l2_claim_entity_refs AS refs
                      ON refs.claim_id = claims.claim_id
                     AND refs.invalidated_at IS NULL
                    WHERE claims.availability = 'active'
                      AND (claims.subject_ref = ? OR refs.entity_id = ?)
                    LIMIT 1
                    """,
                    (entity_id, entity_id),
                ) as cur:
                    if await cur.fetchone():
                        await db.rollback()
                        return False
                await db.execute("DELETE FROM tom_snapshots WHERE entity_id = ?", (entity_id,))
                await db.execute("DELETE FROM entity_facets WHERE entity_id = ?", (entity_id,))
                await db.execute(
                    "DELETE FROM entity_name_evidence WHERE entity_id = ?", (entity_id,)
                )
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


__all__ = [
    "MAX_EVIDENCE_EVENT_IDS",
    "L2EntityCatalogMaintenanceMixin",
    "_CatalogMaintenanceHostProtocol",
    "_CatalogMaintenanceStatsProtocol",
    "_canonical_entity_id",
    "_merge_evidence_json",
]
