"""Snapshot persistence helpers for the L2 cognition store."""

from __future__ import annotations

from dataclasses import dataclass
import time
from typing import Any, Callable, Dict, List, Protocol, cast

import aiosqlite

from ....core.logger import get_logger
from ....core.sqlite import sqlite_connection_async
from ...derivation_revision import DerivationRevision
from .snapshot_assembly import L2SnapshotAssemblyMixin
from .snapshot_persistence import L2SnapshotPersistenceMixin
from .snapshot_protocols import _SnapshotHostProtocol

logger = get_logger(__name__)


@dataclass(slots=True)
class _SnapshotRefreshRelations:
    outgoing: List[Dict[str, Any]]
    incoming: List[Dict[str, Any]]
    superseded_outgoing: List[Dict[str, Any]]
    superseded_incoming: List[Dict[str, Any]]


@dataclass(slots=True)
class _SnapshotRefreshAssertions:
    expired: List[Dict[str, Any]]
    active: List[Dict[str, Any]]
    tentative: List[Dict[str, Any]]
    stable: List[Dict[str, Any]]


class _SnapshotRefreshHostProtocol(_SnapshotHostProtocol, Protocol):
    async def list_current_assertions(
        self,
        *,
        entity_id: str | None = None,
        entity_type: str | None = None,
        context_scope: dict[str, Any] | None = None,
        effective_at: float | None = None,
        include_expired: bool = False,
        limit: int = 100,
    ) -> List[Dict[str, Any]]: ...

    async def list_current_relationships(
        self,
        *,
        subject_id: str | None = None,
        object_id: str | None = None,
        context_scope: dict[str, Any] | None = None,
        effective_at: float | None = None,
        limit: int = 100,
    ) -> List[Dict[str, Any]]: ...

    async def batch_get_relationships(
        self,
        *,
        entity_ids: List[str],
        direction: str = "outgoing",
        status_filters: List[str] | None = None,
        limit_per_entity: int = 100,
    ) -> Dict[str, List[Dict[str, Any]]]: ...


class L2StoreSnapshotMixin(
    L2SnapshotAssemblyMixin,
    L2SnapshotPersistenceMixin,
):
    """Persist ToM snapshots derived from assertions and graph relations."""

    async def refresh_entity_snapshot(
        self,
        *,
        entity_id: str,
        entity_type: str | None = None,
    ) -> Dict[str, Any] | None:
        """Rebuild one snapshot from reconciled assertions and graph edges."""
        host = cast(_SnapshotRefreshHostProtocol, self)
        derivation_revision = await DerivationRevision.capture(host, entity_id)
        assertions = await host.list_current_assertions(
            entity_id=entity_id,
            entity_type=entity_type,
            context_scope=None,
            include_expired=True,
            limit=500,
        )
        relations = await self._snapshot_refresh_relations(
            host=host,
            entity_id=entity_id,
        )
        if _snapshot_refresh_is_empty(assertions=assertions, relations=relations):
            await self._delete_empty_snapshot(
                host=host,
                entity_id=entity_id,
                entity_type=entity_type,
                derivation_revision=derivation_revision,
            )
            return None

        assertion_groups = _group_snapshot_refresh_assertions(
            assertions=assertions,
            is_expired=host._is_assertion_expired,
        )
        normalized_entity_type = _snapshot_refresh_entity_type(
            entity_id=entity_id,
            entity_type=entity_type,
            assertions=assertions,
        )
        snapshot = await self._upsert_snapshot(
            entity_id=entity_id,
            entity_type=normalized_entity_type,
            assertions=assertion_groups.active,
            expired_assertions=assertion_groups.expired,
            stable_assertions=assertion_groups.stable,
            tentative_assertions=assertion_groups.tentative,
            all_raw_assertions=assertions,
            outgoing_relations=relations.outgoing,
            incoming_relations=relations.incoming,
            superseded_outgoing_relations=relations.superseded_outgoing,
            superseded_incoming_relations=relations.superseded_incoming,
            derivation_revision=derivation_revision,
        )
        _log_snapshot_refreshed(
            entity_id=entity_id,
            entity_type=normalized_entity_type,
            assertion_groups=assertion_groups,
            relations=relations,
            snapshot=snapshot,
        )
        return snapshot

    async def _delete_empty_snapshot(
        self,
        *,
        host: _SnapshotRefreshHostProtocol,
        entity_id: str,
        entity_type: str | None,
        derivation_revision: DerivationRevision,
    ) -> None:
        """Remove a materialized snapshot after its final source disappears."""
        async with sqlite_connection_async(host.db_path) as db:
            await db.execute("BEGIN IMMEDIATE")
            try:
                await derivation_revision.ensure_current_on_connection(db)
                if entity_type is None:
                    await db.execute(
                        "DELETE FROM tom_snapshots WHERE entity_id = ?",
                        (entity_id,),
                    )
                else:
                    await db.execute(
                        "DELETE FROM tom_snapshots WHERE entity_id = ? AND entity_type = ?",
                        (entity_id, entity_type),
                    )
                await db.commit()
            except Exception:
                await db.rollback()
                raise

    async def _snapshot_refresh_relations(
        self,
        *,
        host: _SnapshotRefreshHostProtocol,
        entity_id: str,
    ) -> _SnapshotRefreshRelations:
        outgoing = await host.list_current_relationships(
            subject_id=entity_id,
            context_scope=None,
            limit=400,
        )
        incoming = await host.list_current_relationships(
            object_id=entity_id,
            context_scope=None,
            limit=400,
        )
        batch_result = await host.batch_get_relationships(
            entity_ids=[entity_id],
            direction="both",
            status_filters=["deprecated", "conflicted"],
            limit_per_entity=400,
        )
        return _group_snapshot_refresh_relations(
            entity_id=entity_id,
            all_edges=[
                *outgoing,
                *incoming,
                *(
                    item
                    for item in batch_result.get(entity_id, [])
                    if item.get("status_reason") != "user_correction"
                ),
            ],
        )

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
        derivation_revision: DerivationRevision,
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
            await db.execute("BEGIN IMMEDIATE")
            try:
                await derivation_revision.ensure_current_on_connection(db)
                async with db.execute(
                    "SELECT * FROM tom_snapshots WHERE entity_id = ? AND entity_type = ?",
                    (entity_id, entity_type),
                ) as cursor:
                    existing = await cursor.fetchone()
                existing_snapshot = host._snapshot_row_to_dict(existing) if existing else None
                if existing_snapshot is not None and (
                    int(existing_snapshot.get("source_generation") or 0)
                    != int(derivation_revision.clear_generation or 0)
                    or int(existing_snapshot.get("source_revision") or 0)
                    > derivation_revision.source_revision
                ):
                    existing_snapshot = None

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
                    source_revision=derivation_revision.source_revision,
                    source_generation=int(derivation_revision.clear_generation or 0),
                    now=now,
                )
                async with db.execute(
                    "SELECT * FROM tom_snapshots WHERE entity_id = ? AND entity_type = ?",
                    (entity_id, entity_type),
                ) as cursor:
                    stored = await cursor.fetchone()
                assert stored is not None
                snapshot = host._snapshot_row_to_dict(stored)
                await db.commit()
            except Exception:
                await db.rollback()
                raise
        return snapshot


def _group_snapshot_refresh_relations(
    *,
    entity_id: str,
    all_edges: List[Dict[str, Any]],
) -> _SnapshotRefreshRelations:
    superseded_statuses = {"deprecated", "conflicted"}
    return _SnapshotRefreshRelations(
        outgoing=[
            item
            for item in all_edges
            if item["subject_id"] == entity_id and item["status"] == "active"
        ],
        incoming=[
            item
            for item in all_edges
            if item["object_id"] == entity_id and item["status"] == "active"
        ],
        superseded_outgoing=[
            item
            for item in all_edges
            if item["subject_id"] == entity_id and item["status"] in superseded_statuses
        ],
        superseded_incoming=[
            item
            for item in all_edges
            if item["object_id"] == entity_id and item["status"] in superseded_statuses
        ],
    )


def _group_snapshot_refresh_assertions(
    *,
    assertions: List[Dict[str, Any]],
    is_expired: Callable[[Dict[str, Any]], bool],
) -> _SnapshotRefreshAssertions:
    return _SnapshotRefreshAssertions(
        expired=[item for item in assertions if is_expired(item)],
        active=[
            item
            for item in assertions
            if item.get("status", item["validation_state"]) in {"stable", "corroborated"}
            and not is_expired(item)
            and item.get("user_feedback") != "rejected"
        ],
        tentative=[
            item
            for item in assertions
            if item.get("status", item["validation_state"]) == "tentative"
            and not is_expired(item)
            and item.get("user_feedback") != "rejected"
        ],
        stable=[item for item in assertions if item["validation_state"] == "stable"],
    )


def _snapshot_refresh_is_empty(
    *,
    assertions: List[Dict[str, Any]],
    relations: _SnapshotRefreshRelations,
) -> bool:
    return (
        not assertions
        and not relations.outgoing
        and not relations.incoming
        and not relations.superseded_outgoing
        and not relations.superseded_incoming
    )


def _snapshot_refresh_entity_type(
    *,
    entity_id: str,
    entity_type: str | None,
    assertions: List[Dict[str, Any]],
) -> str:
    if entity_type:
        return entity_type
    if assertions:
        return str(assertions[0]["entity_type"])
    return entity_id.split(":", 1)[0]


def _log_snapshot_refreshed(
    *,
    entity_id: str,
    entity_type: str,
    assertion_groups: _SnapshotRefreshAssertions,
    relations: _SnapshotRefreshRelations,
    snapshot: Dict[str, Any],
) -> None:
    logger.info(
        "L2 snapshot refreshed",
        entity_id=entity_id,
        entity_type=entity_type,
        active_assertion_count=len(assertion_groups.active),
        stable_assertion_count=len(assertion_groups.stable),
        outgoing_relation_count=len(relations.outgoing),
        incoming_relation_count=len(relations.incoming),
        snapshot_version=snapshot.get("snapshot_version"),
    )


__all__ = [
    "L2StoreSnapshotMixin",
    "L2SnapshotAssemblyMixin",
    "L2SnapshotPersistenceMixin",
    "_SnapshotHostProtocol",
]
