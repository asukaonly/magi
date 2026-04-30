"""Contradiction hint persistence helpers for the L2 cognition store."""

from __future__ import annotations

import time
from typing import Any, Dict, Protocol, cast

import aiosqlite

from ....core.logger import get_logger
from ....core.sqlite import sqlite_connection_async
from ..models import ContradictionHint

logger = get_logger(__name__)


class _ContradictionHostProtocol(Protocol):
    db_path: str

    async def initialize(self) -> None:
        ...

    def _contradicted_confidence(self, *, current_confidence: float, hint_confidence: float, action: str) -> float:
        ...


class L2StoreContradictionMixin:
    """Apply contradiction hints to persisted graph and assertion records."""

    async def apply_contradiction_hint(self, hint: Dict[str, Any] | ContradictionHint) -> bool:
        """Apply a contradiction hint to an existing graph edge or ToM assertion."""
        host = cast(_ContradictionHostProtocol, self)
        payload = hint.to_dict() if isinstance(hint, ContradictionHint) else dict(hint)
        target_record_type = str(payload.get("target_record_type", ""))
        target_record_id = str(payload.get("target_record_id", ""))
        action = str(payload.get("recommended_action", ""))
        confidence = float(payload.get("confidence", 0.0) or 0.0)
        if not target_record_id or not target_record_type:
            return False

        now = time.time()
        await host.initialize()
        async with sqlite_connection_async(host.db_path) as db:
            db.row_factory = aiosqlite.Row
            if target_record_type == "tom_trait_assertion":
                async with db.execute(
                    "SELECT assertion_id, confidence_score, validation_state FROM tom_trait_assertions WHERE assertion_id = ?",
                    (target_record_id,),
                ) as cursor:
                    row = await cursor.fetchone()
                if row is None:
                    return False

                if action == "revalidate_only":
                    await db.execute(
                        """
                        UPDATE tom_trait_assertions
                        SET last_validated_at = ?, updated_at = ?
                        WHERE assertion_id = ?
                        """,
                        (now, now, target_record_id),
                    )
                    await db.commit()
                    logger.info(
                        "L2 contradiction revalidated existing assertion",
                        target_record_type=target_record_type,
                        target_record_id=target_record_id,
                    )
                    return True

                existing_confidence = float(row["confidence_score"])
                next_confidence = host._contradicted_confidence(
                    current_confidence=existing_confidence,
                    hint_confidence=confidence,
                    action=action,
                )
                next_state = "contradicted" if action in {"downgrade_confidence", "mark_conflicted"} else "corroborated"
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
                        target_record_id,
                    ),
                )
                await db.commit()
                logger.info(
                    "L2 contradiction applied",
                    target_record_type=target_record_type,
                    target_record_id=target_record_id,
                    action=action,
                    next_state=next_state,
                    next_confidence=next_confidence,
                )
                return True

            if target_record_type == "knowledge_graph":
                if action == "revalidate_only":
                    await db.execute(
                        """
                        UPDATE knowledge_graph
                        SET last_confirmed_at = ?, updated_at = ?
                        WHERE triple_id = ?
                        """,
                        (now, now, target_record_id),
                    )
                    await db.commit()
                    logger.info(
                        "L2 contradiction revalidated existing relation",
                        target_record_type=target_record_type,
                        target_record_id=target_record_id,
                    )
                    return True

                next_status = "deprecated" if action == "mark_deprecated" else "conflicted"
                await db.execute(
                    """
                    UPDATE knowledge_graph
                    SET status = ?, deprecated_by = ?, deprecated_at = ?, updated_at = ?
                    WHERE triple_id = ?
                    """,
                    (
                        next_status,
                        f"hint:{target_record_id}",
                        now,
                        now,
                        target_record_id,
                    ),
                )
                await db.commit()
                logger.info(
                    "L2 contradiction applied",
                    target_record_type=target_record_type,
                    target_record_id=target_record_id,
                    action=action,
                    next_status=next_status,
                )
                return True

        return False
