"""User feedback and correction helpers for the L2 cognition store."""

from __future__ import annotations

import json
import time
import uuid
from dataclasses import dataclass
from typing import Any, Dict, Optional, Protocol, cast

import aiosqlite

from ....core.logger import get_logger
from ....core.sqlite import sqlite_connection_async
from .settings import (
    CONFIDENCE_CEILING,
    USER_CONFIRMED_CONFIDENCE_FLOOR,
    USER_REJECTED_CONFIDENCE,
    assertion_float_setting,
)

logger = get_logger(__name__)


@dataclass(frozen=True)
class _ShadowConflictContext:
    shadow_id: str
    entity_id: str
    entity_type: str
    trait_name: str
    trait_value: str
    target_entity_id: str
    current_confidence: float
    now: float


@dataclass(frozen=True)
class _ShadowPromotionResult:
    old_authoritative_id: str | None
    new_confidence: float


class _FeedbackHostProtocol(Protocol):
    db_path: str

    async def initialize(self) -> None: ...

    async def get_tom_assertion(self, *, assertion_id: str) -> Optional[Dict[str, Any]]: ...

    async def refresh_entity_snapshot(
        self,
        *,
        entity_id: str,
        entity_type: Optional[str] = None,
    ) -> Optional[Dict[str, Any]]: ...

    async def _notify_assertion_changed(self, assertion: Dict[str, Any]) -> None: ...


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
                confidence_ceiling = assertion_float_setting(
                    "confidence_ceiling",
                    CONFIDENCE_CEILING,
                )
                new_confidence = max(
                    min(confidence_ceiling, current_confidence + 0.20),
                    assertion_float_setting(
                        "user_confirmed_confidence_floor",
                        USER_CONFIRMED_CONFIDENCE_FLOOR,
                    ),
                )
                new_state = "stable" if current_state != "contradicted" else current_state
            else:
                new_confidence = assertion_float_setting(
                    "user_rejected_confidence",
                    USER_REJECTED_CONFIDENCE,
                )
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
        result = await host.get_tom_assertion(assertion_id=assertion_id)
        await _notify_feedback_assertion_changed(host, result)
        return result

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

        existing = await _load_assertion_row(host.db_path, assertion_id)
        if existing is None:
            return None

        new_assertion_id = f"assert_{uuid.uuid4().hex}"
        await _write_corrected_assertion(
            host.db_path,
            existing=existing,
            old_assertion_id=assertion_id,
            new_assertion_id=new_assertion_id,
            new_value=new_value,
            now=now,
        )

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
        result = await host.get_tom_assertion(assertion_id=new_assertion_id)
        await _notify_feedback_assertion_changed(host, result)
        return result

    async def resolve_shadow_conflict(
        self,
        *,
        shadow_id: str,
        action: str,
    ) -> Optional[Dict[str, Any]]:
        """Resolve a profile conflict represented by a shadow assertion.

        action == "reject": discard the shadow (status -> user_rejected); the
            authoritative row is untouched.
        action == "confirm": promote the shadow to the active, user-confirmed value
            and supersede the prior authoritative row on the same key.

        Returns the resulting assertion dict (the kept/promoted row), or None if the
        shadow_id doesn't exist or isn't a shadow.
        """
        if action not in {"confirm", "reject"}:
            raise ValueError(f"Invalid action value: {action!r}")

        host = cast(_FeedbackHostProtocol, self)
        await host.initialize()

        shadow_row = await _load_assertion_row(host.db_path, shadow_id)
        if shadow_row is None or str(shadow_row["status"]) != "shadow":
            # Missing or already resolved — idempotent return.
            return None

        if action == "reject":
            # Delegate to the existing feedback path: user_rejected status + low confidence.
            return await self.apply_user_feedback(assertion_id=shadow_id, feedback="rejected")

        context = _build_shadow_conflict_context(shadow_id, shadow_row)
        promotion = await _confirm_shadow_conflict(host.db_path, context)

        logger.info(
            "L2 shadow conflict confirmed: shadow promoted to authoritative",
            shadow_id=shadow_id,
            old_authoritative_id=promotion.old_authoritative_id,
            entity_id=context.entity_id,
            entity_type=context.entity_type,
            trait_name=context.trait_name,
            promoted_value=context.trait_value,
            new_confidence=promotion.new_confidence,
        )

        await _refresh_snapshot_after_shadow_confirmation(host, context)

        result = await host.get_tom_assertion(assertion_id=shadow_id)
        await _notify_feedback_assertion_changed(host, result)
        return result


async def _notify_feedback_assertion_changed(
    host: _FeedbackHostProtocol,
    assertion: Dict[str, Any] | None,
) -> None:
    if assertion is None:
        return
    try:
        await host._notify_assertion_changed(assertion)
    except Exception as exc:  # pragma: no cover - defensive
        logger.warning(
            "L2 feedback assertion change notification failed",
            assertion_id=str(assertion.get("assertion_id", "")),
            entity_id=str(assertion.get("entity_id", "")),
            trait_name=str(assertion.get("trait_name", "")),
            error=str(exc),
        )


async def _load_assertion_row(
    db_path: str,
    assertion_id: str,
) -> aiosqlite.Row | None:
    async with sqlite_connection_async(db_path) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            "SELECT * FROM tom_trait_assertions WHERE assertion_id = ?",
            (assertion_id,),
        ) as cursor:
            return await cursor.fetchone()


async def _write_corrected_assertion(
    db_path: str,
    *,
    existing: aiosqlite.Row,
    old_assertion_id: str,
    new_assertion_id: str,
    new_value: str,
    now: float,
) -> None:
    async with sqlite_connection_async(db_path) as db:
        await _supersede_assertion_for_correction(
            db,
            old_assertion_id=old_assertion_id,
            new_assertion_id=new_assertion_id,
            now=now,
        )
        await _insert_corrected_assertion(
            db,
            existing=existing,
            new_assertion_id=new_assertion_id,
            new_value=new_value,
            now=now,
        )
        await db.commit()


async def _supersede_assertion_for_correction(
    db: aiosqlite.Connection,
    *,
    old_assertion_id: str,
    new_assertion_id: str,
    now: float,
) -> None:
    await db.execute(
        """
        UPDATE tom_trait_assertions
        SET status = 'superseded', superseded_by = ?, superseded_at = ?, updated_at = ?
        WHERE assertion_id = ?
        """,
        (new_assertion_id, now, now, old_assertion_id),
    )


async def _insert_corrected_assertion(
    db: aiosqlite.Connection,
    *,
    existing: aiosqlite.Row,
    new_assertion_id: str,
    new_value: str,
    now: float,
) -> None:
    await db.execute(
        """
        INSERT INTO tom_trait_assertions(
            assertion_id, entity_id, entity_type, trait_family, trait_name, trait_value,
            confidence_score, evidence_events, volatility_index, source_domain,
            inference_depth, validation_state, first_inferred_at, last_validated_at,
            target_entity_id, target_entity_type, target_scope, temporal_scope,
            decay_policy, decay_anchor_at, context_ref_id, expires_at,
            status, user_feedback, user_feedback_at,
            created_at, updated_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        _corrected_assertion_values(
            existing,
            new_assertion_id=new_assertion_id,
            new_value=new_value,
            now=now,
        ),
    )


def _corrected_assertion_values(
    existing: aiosqlite.Row,
    *,
    new_assertion_id: str,
    new_value: str,
    now: float,
) -> tuple[Any, ...]:
    evidence = json.loads(existing["evidence_events"] or "[]")
    return (
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
        "confirmed",
        now,
        now,
        now,
    )


def _build_shadow_conflict_context(
    shadow_id: str,
    shadow_row: aiosqlite.Row,
) -> _ShadowConflictContext:
    return _ShadowConflictContext(
        shadow_id=shadow_id,
        entity_id=str(shadow_row["entity_id"]),
        entity_type=str(shadow_row["entity_type"]),
        trait_name=str(shadow_row["trait_name"]),
        trait_value=str(shadow_row["trait_value"]),
        target_entity_id=str(shadow_row["target_entity_id"] or ""),
        current_confidence=float(shadow_row["confidence_score"]),
        now=time.time(),
    )


async def _confirm_shadow_conflict(
    db_path: str,
    context: _ShadowConflictContext,
) -> _ShadowPromotionResult:
    async with sqlite_connection_async(db_path) as db:
        db.row_factory = aiosqlite.Row
        await db.execute("BEGIN IMMEDIATE")
        try:
            old_authoritative_id = await _supersede_current_authoritative(db, context)
            new_confidence = await _promote_shadow_assertion(db, context)
            await db.commit()
        except Exception:
            await db.rollback()
            raise
    return _ShadowPromotionResult(
        old_authoritative_id=old_authoritative_id,
        new_confidence=new_confidence,
    )


async def _supersede_current_authoritative(
    db: aiosqlite.Connection,
    context: _ShadowConflictContext,
) -> str | None:
    old_authoritative_id = await _find_current_authoritative_id(db, context)
    if old_authoritative_id is None:
        return None

    await db.execute(
        """
        UPDATE tom_trait_assertions
        SET status = 'superseded', superseded_by = ?, superseded_at = ?, updated_at = ?
        WHERE assertion_id = ?
        """,
        (
            context.shadow_id,
            context.now,
            context.now,
            old_authoritative_id,
        ),
    )
    return old_authoritative_id


async def _find_current_authoritative_id(
    db: aiosqlite.Connection,
    context: _ShadowConflictContext,
) -> str | None:
    async with db.execute(
        """
        SELECT assertion_id FROM tom_trait_assertions
        WHERE entity_id = ? AND entity_type = ? AND trait_name = ? AND target_entity_id = ?
          AND status NOT IN ('superseded', 'archived', 'expired', 'user_rejected', 'shadow')
        ORDER BY updated_at DESC
        LIMIT 1
        """,
        (
            context.entity_id,
            context.entity_type,
            context.trait_name,
            context.target_entity_id,
        ),
    ) as cursor:
        old_authoritative = await cursor.fetchone()
    if old_authoritative is None:
        return None
    return str(old_authoritative["assertion_id"])


async def _promote_shadow_assertion(
    db: aiosqlite.Connection,
    context: _ShadowConflictContext,
) -> float:
    new_confidence = _confirmed_shadow_confidence(context.current_confidence)
    await db.execute(
        """
        UPDATE tom_trait_assertions
        SET status = 'stable',
            validation_state = 'stable',
            user_feedback = 'confirmed',
            user_feedback_at = ?,
            confidence_score = ?,
            updated_at = ?
        WHERE assertion_id = ?
        """,
        (
            context.now,
            new_confidence,
            context.now,
            context.shadow_id,
        ),
    )
    return new_confidence


def _confirmed_shadow_confidence(current_confidence: float) -> float:
    confidence_ceiling = assertion_float_setting(
        "confidence_ceiling",
        CONFIDENCE_CEILING,
    )
    return max(
        min(confidence_ceiling, current_confidence + 0.20),
        assertion_float_setting(
            "user_confirmed_confidence_floor",
            USER_CONFIRMED_CONFIDENCE_FLOOR,
        ),
    )


async def _refresh_snapshot_after_shadow_confirmation(
    host: _FeedbackHostProtocol,
    context: _ShadowConflictContext,
) -> None:
    try:
        await host.refresh_entity_snapshot(
            entity_id=context.entity_id,
            entity_type=context.entity_type,
        )
    except Exception as exc:
        logger.warning(
            "L2 snapshot refresh after shadow confirmation failed",
            shadow_id=context.shadow_id,
            entity_id=context.entity_id,
            error=str(exc),
        )
