"""Snapshot persistence helpers for the L2 cognition store."""

from __future__ import annotations

import time
from typing import Any, Dict, List, cast

import aiosqlite

from ....core.sqlite import sqlite_connection_async
from .snapshot_assembly import L2SnapshotAssemblyMixin
from .snapshot_persistence import L2SnapshotPersistenceMixin
from .snapshot_protocols import _SnapshotHostProtocol


class L2StoreSnapshotMixin(
    L2SnapshotAssemblyMixin,
    L2SnapshotPersistenceMixin,
):
    """Persist ToM snapshots derived from assertions and graph relations."""

    async def _upsert_snapshot(
        self,
        *,
        entity_id: str,
        entity_type: str,
        assertions: List[Dict[str, Any]],
        expired_assertions: List[Dict[str, Any]],
        stable_assertions: List[Dict[str, Any]],
        tentative_assertions: List[Dict[str, Any]] | None = None,
        all_raw_assertions: List[Dict[str, Any]] | None = None,
        outgoing_relations: List[Dict[str, Any]],
        incoming_relations: List[Dict[str, Any]],
        superseded_outgoing_relations: List[Dict[str, Any]],
        superseded_incoming_relations: List[Dict[str, Any]],
    ) -> Dict[str, Any]:
        host = cast(_SnapshotHostProtocol, self)
        now = time.time()
        state = self._build_snapshot_state(
            assertions=assertions,
            expired_assertions=expired_assertions,
            stable_assertions=stable_assertions,
            tentative_assertions=tentative_assertions,
            outgoing_relations=outgoing_relations,
            incoming_relations=incoming_relations,
            now=now,
        )

        async with sqlite_connection_async(host.db_path) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute(
                "SELECT * FROM tom_snapshots WHERE entity_id = ? AND entity_type = ?",
                (entity_id, entity_type),
            ) as cursor:
                existing = await cursor.fetchone()
            existing_snapshot = host._snapshot_row_to_dict(existing) if existing else None

            mood_trajectory = self._build_mood_trajectory(
                existing_snapshot=existing_snapshot,
                assertions=assertions,
                all_raw_assertions=all_raw_assertions,
            )

            evolution_payload = host._build_snapshot_evolution_payload(
                existing_snapshot=existing_snapshot,
                core_traits=state["core_traits"],
                preferences=state["preferences"],
                relationship_topology=state["relationship_topology"],
                assertions=assertions,
                outgoing_relations=outgoing_relations,
                incoming_relations=incoming_relations,
                superseded_outgoing_relations=superseded_outgoing_relations,
                superseded_incoming_relations=superseded_incoming_relations,
                fallback_updated_at=now,
            )

            await self._persist_snapshot_payload(
                db=db,
                existing=existing,
                entity_id=entity_id,
                entity_type=entity_type,
                state=state,
                evolution_payload=evolution_payload,
                mood_trajectory=mood_trajectory,
                now=now,
            )
            await db.commit()

        snapshot = await host.get_tom_snapshot(entity_id=entity_id, entity_type=entity_type)
        assert snapshot is not None
        return snapshot


__all__ = [
    "L2StoreSnapshotMixin",
    "L2SnapshotAssemblyMixin",
    "L2SnapshotPersistenceMixin",
    "_SnapshotHostProtocol",
]
