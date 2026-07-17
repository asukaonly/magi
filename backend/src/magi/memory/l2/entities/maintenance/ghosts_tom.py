"""ToM ghost entity reference rewrite helpers for L2 maintenance."""

from __future__ import annotations

import time
from typing import Any, cast

import aiosqlite

from .....core.logger import get_logger
from .....core.sqlite import sqlite_connection_async
from ...assertions.identity_rekey import rekey_assertion_entity_identity
from .ghosts_common import L2EntityGhostHostMixin, _CatalogMaintenanceStatsProtocol

logger = get_logger("magi.memory.l2.entities.maintenance")


async def _read_tom_ghost_entity_ids(db_path: str) -> list[str]:
    async with sqlite_connection_async(db_path) as db:
        async with db.execute("""
            SELECT entity_id
            FROM (
                SELECT entity_id FROM tom_trait_assertions
                UNION
                SELECT target_entity_id AS entity_id FROM tom_trait_assertions
            )
            WHERE TRIM(entity_id) != ''
              AND entity_id NOT IN (SELECT entity_id FROM entity_catalog)
              AND entity_id NOT LIKE 'user:%'
            ORDER BY entity_id
            """) as cur:
            return [str(r[0]) for r in await cur.fetchall()]


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
            await rekey_assertion_entity_identity(
                db,
                source_entity_id=ghost_id,
                target_entity_id=target,
                now=time.time(),
            )
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
        refresh_targets: set[str] = set()
        for ghost_id in ghosts:
            target = await cast(Any, self)._resolve_ghost_to_catalog_id(ghost_id)
            if not target:
                continue
            await _rewrite_one_tom_ghost_entity_ref(
                host._db_path,
                ghost_id=ghost_id,
                target=target,
            )
            refresh_targets.add(target)
            stats.tom_entity_refs_rewritten += 1
        for target in sorted(refresh_targets):
            try:
                snapshot = await _refresh_tom_snapshot_after_rekey(host, target)
                stats.snapshots_refreshed += int(snapshot is not None)
            except Exception as exc:
                stats.errors.append(f"refresh snapshot {target}: {exc}")
                logger.warning(
                    "L2 snapshot refresh after ghost rekey failed",
                    entity_id=target,
                    error=str(exc),
                )


async def _refresh_tom_snapshot_after_rekey(host: Any, entity_id: str) -> Any:
    store = getattr(host, "_cognition_store", None)
    if store is None:
        from ...store import L2CognitionStore

        store = L2CognitionStore(db_path=host._db_path)
        await store.initialize()
        host._cognition_store = store
    return await store.refresh_entity_snapshot(entity_id=entity_id)


__all__ = [
    "L2EntityTomGhostMaintenanceMixin",
    "_refresh_tom_snapshot_after_rekey",
]
