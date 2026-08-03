"""Contradiction hint persistence helpers for the L2 cognition store."""

from __future__ import annotations

import time
from collections.abc import Iterable
from dataclasses import dataclass
from typing import Any, Dict, Protocol, cast

import aiosqlite

from ....core.logger import get_logger
from ....core.sqlite import sqlite_connection_async
from ..batch_models import L2ProjectionLease
from ..models import ContradictionHint
from ..projection.fencing import (
    assert_current_projection_attempt,
    normalize_projection_leases,
)

logger = get_logger(__name__)


class _ContradictionHostProtocol(Protocol):
    db_path: str

    async def initialize(self) -> None: ...

    def _contradicted_confidence(
        self, *, current_confidence: float, hint_confidence: float, action: str
    ) -> float: ...


@dataclass(frozen=True)
class _ContradictionPayload:
    target_record_type: str
    target_record_id: str
    action: str
    confidence: float


class L2StoreContradictionMixin:
    """Apply contradiction hints to persisted graph and assertion records."""

    async def apply_contradiction_hint(
        self,
        hint: Dict[str, Any] | ContradictionHint,
        *,
        projection_leases: Iterable[L2ProjectionLease] = (),
    ) -> bool:
        """Apply a contradiction hint to an existing graph edge or ToM assertion."""
        host = cast(_ContradictionHostProtocol, self)
        payload = self._contradiction_payload(hint)
        if not payload.target_record_id or not payload.target_record_type:
            return False

        now = time.time()
        await host.initialize()
        lease_items = normalize_projection_leases(projection_leases, required=False)
        async with sqlite_connection_async(host.db_path) as db:
            db.row_factory = aiosqlite.Row
            await db.execute("BEGIN IMMEDIATE")
            try:
                if lease_items:
                    await assert_current_projection_attempt(db, lease_items)
                if payload.target_record_type == "tom_trait_assertion":
                    applied = await self._apply_assertion_contradiction(
                        db,
                        host=host,
                        payload=payload,
                        now=now,
                    )
                elif payload.target_record_type == "knowledge_graph":
                    applied = await self._apply_relation_contradiction(
                        db,
                        payload=payload,
                        now=now,
                    )
                else:
                    applied = False
                await db.commit()
                return applied
            except Exception:
                await db.rollback()
                raise

        return False

    @staticmethod
    def _contradiction_payload(
        hint: Dict[str, Any] | ContradictionHint,
    ) -> _ContradictionPayload:
        raw = hint.to_dict() if isinstance(hint, ContradictionHint) else dict(hint)
        return _ContradictionPayload(
            target_record_type=str(raw.get("target_record_type", "")),
            target_record_id=str(raw.get("target_record_id", "")),
            action=str(raw.get("recommended_action", "")),
            confidence=float(raw.get("confidence", 0.0) or 0.0),
        )

    async def _apply_assertion_contradiction(
        self,
        db: aiosqlite.Connection,
        *,
        host: _ContradictionHostProtocol,
        payload: _ContradictionPayload,
        now: float,
    ) -> bool:
        row = await self._fetch_contradicted_assertion(db, payload.target_record_id)
        if row is None:
            return False
        if payload.action == "revalidate_only":
            return await self._revalidate_contradicted_assertion(
                db,
                payload=payload,
                now=now,
            )
        return await self._update_contradicted_assertion(
            db,
            host=host,
            payload=payload,
            row=row,
            now=now,
        )

    @staticmethod
    async def _fetch_contradicted_assertion(
        db: aiosqlite.Connection,
        target_record_id: str,
    ) -> aiosqlite.Row | None:
        async with db.execute(
            "SELECT assertion_id, confidence_score, validation_state FROM tom_trait_assertions WHERE assertion_id = ?",
            (target_record_id,),
        ) as cursor:
            return await cursor.fetchone()

    @staticmethod
    async def _revalidate_contradicted_assertion(
        db: aiosqlite.Connection,
        *,
        payload: _ContradictionPayload,
        now: float,
    ) -> bool:
        await db.execute(
            """
            UPDATE tom_trait_assertions
            SET last_validated_at = ?, updated_at = ?
            WHERE assertion_id = ?
            """,
            (now, now, payload.target_record_id),
        )
        logger.info(
            "L2 contradiction revalidated existing assertion",
            target_record_type=payload.target_record_type,
            target_record_id=payload.target_record_id,
        )
        return True

    @staticmethod
    async def _update_contradicted_assertion(
        db: aiosqlite.Connection,
        *,
        host: _ContradictionHostProtocol,
        payload: _ContradictionPayload,
        row: aiosqlite.Row,
        now: float,
    ) -> bool:
        next_confidence = host._contradicted_confidence(
            current_confidence=float(row["confidence_score"]),
            hint_confidence=payload.confidence,
            action=payload.action,
        )
        next_state = (
            "contradicted"
            if payload.action in {"downgrade_confidence", "mark_conflicted"}
            else "corroborated"
        )
        await db.execute(
            """
            UPDATE tom_trait_assertions
            SET confidence_score = ?, validation_state = ?, last_validated_at = ?, updated_at = ?
            WHERE assertion_id = ?
            """,
            (
                next_confidence,
                next_state,
                now,
                now,
                payload.target_record_id,
            ),
        )
        logger.info(
            "L2 contradiction applied",
            target_record_type=payload.target_record_type,
            target_record_id=payload.target_record_id,
            action=payload.action,
            next_state=next_state,
            next_confidence=next_confidence,
        )
        return True

    async def _apply_relation_contradiction(
        self,
        db: aiosqlite.Connection,
        *,
        payload: _ContradictionPayload,
        now: float,
    ) -> bool:
        if payload.action == "revalidate_only":
            return await self._revalidate_contradicted_relation(
                db,
                payload=payload,
                now=now,
            )
        return await self._update_contradicted_relation(db, payload=payload, now=now)

    @staticmethod
    async def _revalidate_contradicted_relation(
        db: aiosqlite.Connection,
        *,
        payload: _ContradictionPayload,
        now: float,
    ) -> bool:
        await db.execute(
            """
            UPDATE knowledge_graph
            SET last_confirmed_at = ?, updated_at = ?
            WHERE triple_id = ?
            """,
            (now, now, payload.target_record_id),
        )
        logger.info(
            "L2 contradiction revalidated existing relation",
            target_record_type=payload.target_record_type,
            target_record_id=payload.target_record_id,
        )
        return True

    @staticmethod
    async def _update_contradicted_relation(
        db: aiosqlite.Connection,
        *,
        payload: _ContradictionPayload,
        now: float,
    ) -> bool:
        next_status = "deprecated" if payload.action == "mark_deprecated" else "conflicted"
        await db.execute(
            """
            UPDATE knowledge_graph
            SET status = ?, deprecated_by = ?, deprecated_at = ?, updated_at = ?
            WHERE triple_id = ?
            """,
            (
                next_status,
                f"hint:{payload.target_record_id}",
                now,
                now,
                payload.target_record_id,
            ),
        )
        logger.info(
            "L2 contradiction applied",
            target_record_type=payload.target_record_type,
            target_record_id=payload.target_record_id,
            action=payload.action,
            next_status=next_status,
        )
        return True
