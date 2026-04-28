"""User feedback and correction helpers for the L2 cognition store."""

from __future__ import annotations

import json
import time
import uuid
from typing import Any, Dict, Optional, Protocol, cast

import aiosqlite

from ...core.logger import get_logger
from ...core.sqlite import sqlite_connection_async

logger = get_logger(__name__)


class _FeedbackHostProtocol(Protocol):
    db_path: str

    async def initialize(self) -> None:
        ...

    async def get_tom_assertion(self, *, assertion_id: str) -> Optional[Dict[str, Any]]:
        ...


class L2StoreFeedbackMixin:
    """Apply user feedback and user-initiated assertion corrections."""

    async def apply_user_feedback(
        self,
        *,
        assertion_id: str,
        feedback: str,
    ) -> Optional[Dict[str, Any]]:
        """Apply user confirmation or rejection to an assertion."""
        if feedback not in {"confirmed", "rejected"}:
            raise ValueError(f"Invalid feedback value: {feedback!r}")

        host = cast(_FeedbackHostProtocol, self)
        await host.initialize()
        now = time.time()

        async with sqlite_connection_async(host.db_path) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute(
                "SELECT * FROM tom_trait_assertions WHERE assertion_id = ?",
                (assertion_id,),
            ) as cursor:
                existing = await cursor.fetchone()

            if existing is None:
                return None

            current_confidence = float(existing["confidence_score"])
            current_state = str(existing["validation_state"])

            if feedback == "confirmed":
                new_confidence = min(0.95, current_confidence + 0.20)
                new_state = "stable" if current_state != "contradicted" else current_state
            else:
                new_confidence = 0.10
                new_state = "user_rejected"

            await db.execute(
                """
                UPDATE tom_trait_assertions
                SET user_feedback = ?, user_feedback_at = ?,
                    confidence_score = ?, validation_state = ?, status = ?, updated_at = ?
                WHERE assertion_id = ?
                """,
                (feedback, now, new_confidence, new_state, new_state, now, assertion_id),
            )
            await db.commit()

        logger.info(
            "L2 user feedback applied",
            assertion_id=assertion_id,
            feedback=feedback,
            old_confidence=current_confidence,
            new_confidence=new_confidence,
            old_state=current_state,
            new_state=new_state,
        )
        return await host.get_tom_assertion(assertion_id=assertion_id)

    async def correct_assertion(
        self,
        *,
        assertion_id: str,
        new_value: str,
        reason: Optional[str] = None,
    ) -> Optional[Dict[str, Any]]:
        """Supersede an assertion with a user-provided corrected value."""
        host = cast(_FeedbackHostProtocol, self)
        await host.initialize()
        now = time.time()

        async with sqlite_connection_async(host.db_path) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute(
                "SELECT * FROM tom_trait_assertions WHERE assertion_id = ?",
                (assertion_id,),
            ) as cursor:
                existing = await cursor.fetchone()

            if existing is None:
                return None

            new_assertion_id = f"assert_{uuid.uuid4().hex}"

            await db.execute(
                """
                UPDATE tom_trait_assertions
                SET status = 'superseded', superseded_by = ?, superseded_at = ?, updated_at = ?
                WHERE assertion_id = ?
                """,
                (new_assertion_id, now, now, assertion_id),
            )

            evidence = json.loads(existing["evidence_events"] or "[]")
            await db.execute(
                """
                INSERT INTO tom_trait_assertions(
                    assertion_id, entity_id, entity_type, trait_family, trait_name, trait_value,
                    confidence_score, evidence_events, volatility_index, source_domain,
                    inference_depth, validation_state, first_inferred_at, last_validated_at,
                    target_entity_id, target_entity_type, target_scope, temporal_scope,
                    decay_policy, decay_anchor_at, context_ref_id, expires_at,
                    status, privacy_scope, user_feedback, user_feedback_at,
                    created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    new_assertion_id,
                    str(existing["entity_id"]),
                    str(existing["entity_type"]),
                    str(existing["trait_family"]),
                    str(existing["trait_name"]),
                    new_value,
                    0.95,
                    json.dumps(evidence, ensure_ascii=False),
                    float(existing["volatility_index"]),
                    "user_correction",
                    "explicit",
                    "stable",
                    float(existing["first_inferred_at"]),
                    now,
                    str(existing["target_entity_id"] or ""),
                    str(existing["target_entity_type"] or ""),
                    str(existing["target_scope"] or "global"),
                    str(existing["temporal_scope"] or "session"),
                    existing["decay_policy"],
                    existing["decay_anchor_at"],
                    str(existing["context_ref_id"] or ""),
                    existing["expires_at"],
                    "stable",
                    str(existing["privacy_scope"] if "privacy_scope" in existing.keys() else "private"),
                    "confirmed",
                    now,
                    now,
                    now,
                ),
            )
            await db.commit()

        logger.info(
            "L2 user correction applied",
            old_assertion_id=assertion_id,
            new_assertion_id=new_assertion_id,
            entity_id=str(existing["entity_id"]),
            trait_name=str(existing["trait_name"]),
            old_value=str(existing["trait_value"]),
            new_value=new_value,
            reason=reason,
        )
        return await host.get_tom_assertion(assertion_id=new_assertion_id)
