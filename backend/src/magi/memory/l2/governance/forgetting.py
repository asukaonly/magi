"""User-driven rejection and forgetting helpers for the L2 cognition store."""

from __future__ import annotations

import time
import uuid
from dataclasses import asdict
from typing import Any, Dict, Mapping, Optional, Protocol, cast

import aiosqlite

from ....core.logger import get_logger
from ....core.sqlite import sqlite_connection_async
from ..corrections.models import (
    ApplyRelationshipCorrectionCommand,
    CorrectionKind,
    CorrectionTargetKind,
)
from ..corrections.repository import MemoryCorrectionRepository
from ..corrections.service import MemoryCorrectionService
from ..graph_conflicts import GraphConflictRule

logger = get_logger(__name__)


class _ForgettingHostProtocol(Protocol):
    db_path: str
    _graph_conflict_rules: Mapping[str, GraphConflictRule]

    async def initialize(self) -> None: ...

    async def get_relationship(self, *, triple_id: str) -> Optional[Dict[str, Any]]: ...

    async def wake_memory_correction_jobs(self) -> bool: ...


class L2StoreForgettingMixin:
    """Apply user rejection and forgetting actions to L2 records."""

    async def reject_edge(
        self,
        *,
        triple_id: str,
        audit_event_id: str | None = None,
    ) -> Optional[Dict[str, Any]]:
        """Reject a KG edge through durable correction governance."""
        host = cast(_ForgettingHostProtocol, self)
        await host.initialize()
        existing = await host.get_relationship(triple_id=triple_id)
        if existing is None:
            return None
        if existing["status"] == "user_rejected":
            return existing
        await self.apply_relationship_correction(
            triple_id=triple_id,
            request_id=f"edge_rejection_{uuid.uuid4().hex}",
            actor_id="local_user",
            correction_kind=CorrectionKind.RECORD_ERROR,
            audit_event_id=audit_event_id,
        )
        return await host.get_relationship(triple_id=triple_id)

    async def apply_relationship_correction(
        self,
        *,
        triple_id: str,
        request_id: str,
        actor_id: str,
        correction_kind: CorrectionKind | str,
        replacement: Dict[str, Any] | None = None,
        reason: str | None = None,
        effective_at: float | None = None,
        scope: Dict[str, Any] | None = None,
        source_event_id: str | None = None,
        audit_event_id: str | None = None,
        expected_updated_at: float | None = None,
    ) -> Optional[Dict[str, Any]]:
        """Apply a governed correction to one relationship."""
        host = cast(_ForgettingHostProtocol, self)
        await host.initialize()
        existing_request = await MemoryCorrectionRepository(host.db_path).get_by_request_id(
            request_id
        )
        current = (
            existing_request.before
            if existing_request is not None
            and existing_request.target_kind == CorrectionTargetKind.EDGE
            else await host.get_relationship(triple_id=triple_id)
        )
        if current is None and existing_request is None:
            return None
        normalized_replacement = dict(replacement) if replacement is not None else None
        result = await MemoryCorrectionService(
            host.db_path,
            graph_conflict_rules=host._graph_conflict_rules,
        ).apply_relationship_correction(
            ApplyRelationshipCorrectionCommand(
                triple_id=triple_id,
                request_id=request_id,
                actor_id=actor_id,
                correction_kind=CorrectionKind(correction_kind),
                replacement=normalized_replacement,
                reason=reason,
                effective_at=effective_at,
                scope=scope,
                source_event_id=source_event_id,
                audit_event_id=audit_event_id,
                expected_updated_at=expected_updated_at,
            )
        )
        if result is None:
            return None
        await host.wake_memory_correction_jobs()
        current_relationship = (
            await host.get_relationship(triple_id=result.current_triple_id)
            if result.current_triple_id
            else None
        )
        logger.info(
            "L2 relationship correction applied",
            correction_id=result.correction.correction_id,
            triple_id=triple_id,
            replacement_triple_id=result.correction.replacement_target_id,
            correction_kind=result.correction.correction_kind.value,
            created=result.created,
        )
        return {
            "correction": asdict(result.correction),
            "current_relationship": current_relationship,
            "subject_revision": result.subject_revision,
            "created": result.created,
        }

    async def revert_relationship_correction(
        self,
        *,
        correction_id: str,
        request_id: str,
        actor_id: str = "local_user",
    ) -> Optional[Dict[str, Any]]:
        """Revert one relationship correction."""
        host = cast(_ForgettingHostProtocol, self)
        await host.initialize()
        result = await MemoryCorrectionService(host.db_path).revert_relationship_correction(
            correction_id=correction_id,
            request_id=request_id,
            actor_id=actor_id,
        )
        if result is None:
            return None
        await host.wake_memory_correction_jobs()
        current_relationship = await host.get_relationship(
            triple_id=result.current_triple_id or result.correction.target_id
        )
        return {
            "correction": asdict(result.correction),
            "current_relationship": current_relationship,
            "subject_revision": result.subject_revision,
            "created": result.created,
        }

    async def get_relationship_correction_history(
        self,
        *,
        triple_id: str,
    ) -> Dict[str, Any]:
        """Return immutable versions and corrections for a relationship."""
        host = cast(_ForgettingHostProtocol, self)
        await host.initialize()
        history = await MemoryCorrectionService(host.db_path).get_relationship_correction_history(
            triple_id=triple_id
        )
        return {
            "versions": history["versions"],
            "corrections": [asdict(item) for item in history["corrections"]],
        }

    async def list_relationship_corrections(
        self,
        *,
        triple_id: str,
        limit: int = 100,
    ) -> list[Dict[str, Any]]:
        """List corrections originally applied to one relationship."""
        host = cast(_ForgettingHostProtocol, self)
        await host.initialize()
        corrections = await MemoryCorrectionRepository(host.db_path).list_for_target(
            target_kind=CorrectionTargetKind.EDGE,
            target_id=triple_id,
            limit=limit,
        )
        return [asdict(item) for item in corrections]

    async def forget_entity(
        self,
        *,
        entity_id: str,
    ) -> Dict[str, int]:
        """Cascade soft-delete everything derived from an entity."""
        host = cast(_ForgettingHostProtocol, self)
        await host.initialize()
        now = time.time()
        counts: Dict[str, int] = {}

        async with sqlite_connection_async(host.db_path) as db:
            cursor = await db.execute(
                """
                UPDATE knowledge_graph
                SET status = 'archived', status_reason = 'user_forget', updated_at = ?
                WHERE (subject_id = ? OR object_id = ?) AND status NOT IN ('archived', 'user_rejected')
                """,
                (now, entity_id, entity_id),
            )
            counts["knowledge_graph"] = cursor.rowcount

            cursor = await db.execute(
                """
                UPDATE tom_trait_assertions SET status = 'archived', updated_at = ?
                WHERE (entity_id = ? OR target_entity_id = ?) AND status NOT IN ('archived', 'user_rejected')
                """,
                (now, entity_id, entity_id),
            )
            counts["tom_trait_assertions"] = cursor.rowcount

            cursor = await db.execute(
                """
                UPDATE entity_facets SET status = 'archived', updated_at = ?
                WHERE entity_id = ? AND status != 'archived'
                """,
                (now, entity_id),
            )
            counts["entity_facets"] = cursor.rowcount

            escaped = entity_id.replace('"', '""')
            pattern = f'%"{escaped}"%'
            cursor = await db.execute(
                """
                UPDATE episodes SET status = 'invalidated', updated_at = ?
                WHERE primary_entity_ids LIKE ? AND status NOT IN ('invalidated', 'archived')
                """,
                (now, pattern),
            )
            counts["episodes"] = cursor.rowcount

            await db.commit()

        logger.info("L2 entity forgotten", entity_id=entity_id, counts=counts)
        return counts

    async def forget_time_range(
        self,
        *,
        start: float,
        end: float,
    ) -> Dict[str, int]:
        """Cascade invalidation for a time range."""
        if end <= start:
            raise ValueError("end must be greater than start")

        host = cast(_ForgettingHostProtocol, self)
        await host.initialize()
        now = time.time()
        counts: Dict[str, int] = {}

        async with sqlite_connection_async(host.db_path) as db:
            cursor = await db.execute(
                """
                UPDATE episodes SET status = 'invalidated', updated_at = ?
                WHERE time_start < ? AND time_end > ? AND status NOT IN ('invalidated', 'archived')
                """,
                (now, end, start),
            )
            counts["episodes"] = cursor.rowcount

            cursor = await db.execute(
                """
                UPDATE tom_trait_assertions SET status = 'archived', updated_at = ?
                WHERE first_inferred_at >= ? AND first_inferred_at <= ?
                  AND status NOT IN ('archived', 'user_rejected')
                """,
                (now, start, end),
            )
            counts["tom_trait_assertions"] = cursor.rowcount

            cursor = await db.execute(
                """
                UPDATE knowledge_graph
                SET status = 'archived', status_reason = 'user_forget', updated_at = ?
                WHERE first_observed_at >= ? AND first_observed_at <= ?
                  AND status NOT IN ('archived', 'user_rejected')
                """,
                (now, start, end),
            )
            counts["knowledge_graph"] = cursor.rowcount

            await db.commit()

        logger.info("L2 time range forgotten", start=start, end=end, counts=counts)
        return counts

    async def forget_episode(
        self,
        *,
        episode_id: str,
        delete_events: bool = False,
    ) -> Optional[Dict[str, Any]]:
        """Mark an episode as invalidated and optionally return member event IDs."""
        host = cast(_ForgettingHostProtocol, self)
        await host.initialize()
        now = time.time()

        async with sqlite_connection_async(host.db_path) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute(
                "SELECT episode_id FROM episodes WHERE episode_id = ?",
                (episode_id,),
            ) as cursor:
                existing = await cursor.fetchone()
            if existing is None:
                return None

            await db.execute(
                "UPDATE episodes SET status = 'invalidated', updated_at = ? WHERE episode_id = ?",
                (now, episode_id),
            )

            event_ids: list[str] = []
            if delete_events:
                async with db.execute(
                    "SELECT event_id FROM episode_events WHERE episode_id = ?",
                    (episode_id,),
                ) as cursor:
                    rows = await cursor.fetchall()
                event_ids = [str(row["event_id"]) for row in rows]

            await db.commit()

        logger.info(
            "L2 episode forgotten",
            episode_id=episode_id,
            delete_events=delete_events,
            event_count=len(event_ids),
        )
        return {"episode_id": episode_id, "event_ids": event_ids}
