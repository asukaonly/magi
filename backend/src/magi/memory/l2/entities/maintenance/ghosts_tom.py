"""ToM ghost entity reference rewrite helpers for L2 maintenance."""

from __future__ import annotations

from typing import Any, cast

import aiosqlite

from .....core.sqlite import sqlite_connection_async
from .ghosts_common import L2EntityGhostHostMixin, _CatalogMaintenanceStatsProtocol


async def _read_tom_ghost_entity_ids(db_path: str) -> list[str]:
    async with sqlite_connection_async(db_path) as db:
        async with db.execute("""
            SELECT DISTINCT entity_id FROM tom_trait_assertions
            WHERE entity_id NOT IN (SELECT entity_id FROM entity_catalog)
              AND entity_id NOT LIKE 'user:%'
            """) as cur:
            return [str(r[0]) for r in await cur.fetchall()]


async def _fetch_tom_trait_conflicts(
    db: aiosqlite.Connection,
    *,
    ghost_id: str,
    target: str,
) -> list[aiosqlite.Row]:
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
        return cast(list[aiosqlite.Row], await cur.fetchall())


async def _delete_lower_confidence_tom_conflicts(
    db: aiosqlite.Connection,
    conflicts: list[aiosqlite.Row],
) -> None:
    for conflict in conflicts:
        if float(conflict["ghost_conf"]) > float(conflict["target_conf"]):
            assertion_id = conflict["target_aid"]
        else:
            assertion_id = conflict["ghost_aid"]
        await db.execute(
            "DELETE FROM tom_trait_assertions WHERE assertion_id = ?",
            (assertion_id,),
        )


async def _rewrite_tom_trait_refs(
    db: aiosqlite.Connection,
    *,
    ghost_id: str,
    target: str,
) -> None:
    await db.execute(
        "UPDATE tom_trait_assertions SET entity_id = ? WHERE entity_id = ?",
        (target, ghost_id),
    )
    await db.execute(
        "UPDATE tom_trait_assertions SET target_entity_id = ? WHERE target_entity_id = ?",
        (target, ghost_id),
    )


async def _rewrite_tom_snapshot_ref(
    db: aiosqlite.Connection,
    *,
    ghost_id: str,
    target: str,
) -> None:
    async with db.execute(
        "SELECT 1 FROM tom_snapshots WHERE entity_id = ? LIMIT 1",
        (target,),
    ) as cur:
        target_has_snapshot = await cur.fetchone() is not None
    if target_has_snapshot:
        await db.execute("DELETE FROM tom_snapshots WHERE entity_id = ?", (ghost_id,))
        return
    await db.execute(
        "UPDATE tom_snapshots SET entity_id = ? WHERE entity_id = ?",
        (target, ghost_id),
    )


async def _rewrite_one_tom_ghost_entity_ref(
    db_path: str,
    *,
    ghost_id: str,
    target: str,
) -> None:
    async with sqlite_connection_async(db_path) as db:
        await db.execute("BEGIN IMMEDIATE")
        try:
            db.row_factory = aiosqlite.Row
            conflicts = await _fetch_tom_trait_conflicts(
                db,
                ghost_id=ghost_id,
                target=target,
            )
            await _delete_lower_confidence_tom_conflicts(db, conflicts)
            await _rewrite_tom_trait_refs(db, ghost_id=ghost_id, target=target)
            await _rewrite_tom_snapshot_ref(db, ghost_id=ghost_id, target=target)
            await db.commit()
        except Exception:
            await db.rollback()
            raise


class L2EntityTomGhostMaintenanceMixin(L2EntityGhostHostMixin):
    """Rewrite ghost entity references in tom_* tables."""

    async def _rewrite_tom_entity_refs(
        self,
        stats: _CatalogMaintenanceStatsProtocol,
    ) -> None:
        """Remap tom_* tables for ids not in catalog."""
        host = self._catalog_maintenance_host()
        ghosts = await _read_tom_ghost_entity_ids(host._db_path)
        for ghost_id in ghosts:
            target = await cast(Any, self)._resolve_ghost_to_catalog_id(ghost_id)
            if not target:
                continue
            await _rewrite_one_tom_ghost_entity_ref(
                host._db_path,
                ghost_id=ghost_id,
                target=target,
            )
            stats.tom_entity_refs_rewritten += 1


__all__ = ["L2EntityTomGhostMaintenanceMixin"]
