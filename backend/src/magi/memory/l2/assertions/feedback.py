"""User feedback and correction helpers for the L2 cognition store."""

from __future__ import annotations

import time
import uuid
from dataclasses import asdict, dataclass
from typing import Any, Dict, Optional, Protocol, cast

import aiosqlite

from ....core.logger import get_logger
from ....core.sqlite import sqlite_connection_async
from ..corrections.models import (
    ApplyAssertionCorrectionCommand,
    CorrectionKind,
    CorrectionTargetKind,
)
from ..corrections.repository import MemoryCorrectionRepository
from ..corrections.service import MemoryCorrectionConflictError, MemoryCorrectionService
from .settings import (
    CONFIDENCE_CEILING,
    USER_CONFIRMED_CONFIDENCE_FLOOR,
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
        if feedback == "rejected":
            existing_assertion = await host.get_tom_assertion(assertion_id=assertion_id)
            if existing_assertion is None:
                return None
            if existing_assertion.get("status") == "user_rejected":
                return existing_assertion
            correction_result = await self.apply_assertion_correction(
                assertion_id=assertion_id,
                request_id=f"feedback_{uuid.uuid4().hex}",
                actor_id="local_user",
                correction_kind=CorrectionKind.RECORD_ERROR,
            )
            if correction_result is None:
                return None
            return await host.get_tom_assertion(assertion_id=assertion_id)

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
            if str(existing["status"]) in {
                "archived",
                "expired",
                "superseded",
                "user_rejected",
            }:
                raise MemoryCorrectionConflictError(
                    "Inactive assertions must be restored through correction history"
                )

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
        request_id: str | None = None,
        actor_id: str = "local_user",
        correction_kind: CorrectionKind | str = CorrectionKind.RECORD_ERROR,
        effective_at: float | None = None,
        scope: Dict[str, Any] | None = None,
        source_event_id: str | None = None,
        expected_updated_at: float | None = None,
    ) -> Optional[Dict[str, Any]]:
        """Apply a user-provided corrected value through correction governance."""
        host = cast(_FeedbackHostProtocol, self)
        await host.initialize()
        result = await self.apply_assertion_correction(
            assertion_id=assertion_id,
            request_id=request_id or f"correction_request_{uuid.uuid4().hex}",
            actor_id=actor_id,
            correction_kind=CorrectionKind(correction_kind),
            replacement_value=new_value,
            reason=reason,
            effective_at=effective_at,
            scope=scope,
            source_event_id=source_event_id,
            expected_updated_at=expected_updated_at,
        )
        if result is None or result["current_assertion"] is None:
            return None
        return cast(Dict[str, Any], result["current_assertion"])

    async def apply_assertion_correction(
        self,
        *,
        assertion_id: str,
        request_id: str,
        actor_id: str,
        correction_kind: CorrectionKind | str,
        replacement_value: str | None = None,
        reason: str | None = None,
        effective_at: float | None = None,
        scope: Dict[str, Any] | None = None,
        source_event_id: str | None = None,
        expected_updated_at: float | None = None,
    ) -> Optional[Dict[str, Any]]:
        """Apply one governed assertion correction and return its current claim."""
        host = cast(_FeedbackHostProtocol, self)
        await host.initialize()
        service = MemoryCorrectionService(host.db_path)
        result = await service.apply_assertion_correction(
            ApplyAssertionCorrectionCommand(
                assertion_id=assertion_id,
                request_id=request_id,
                actor_id=actor_id,
                correction_kind=CorrectionKind(correction_kind),
                replacement_value=replacement_value,
                reason=reason,
                effective_at=effective_at,
                scope=scope,
                source_event_id=source_event_id,
                expected_updated_at=expected_updated_at,
            )
        )
        if result is None:
            return None
        changed_assertion_id = result.current_assertion_id or assertion_id
        current_assertion = await host.get_tom_assertion(assertion_id=changed_assertion_id)
        await _notify_feedback_assertion_changed(host, current_assertion)
        logger.info(
            "L2 assertion correction applied",
            correction_id=result.correction.correction_id,
            assertion_id=assertion_id,
            replacement_assertion_id=result.correction.replacement_target_id,
            correction_kind=result.correction.correction_kind.value,
            created=result.created,
        )
        return {
            "correction": asdict(result.correction),
            "current_assertion": current_assertion,
            "subject_revision": result.subject_revision,
            "created": result.created,
        }

    async def revert_assertion_correction(
        self,
        *,
        correction_id: str,
        request_id: str,
        actor_id: str = "local_user",
    ) -> Optional[Dict[str, Any]]:
        """Revert one correction and return the restored current assertion."""
        host = cast(_FeedbackHostProtocol, self)
        await host.initialize()
        result = await MemoryCorrectionService(host.db_path).revert_assertion_correction(
            correction_id=correction_id,
            request_id=request_id,
            actor_id=actor_id,
        )
        if result is None:
            return None
        current_assertion = await host.get_tom_assertion(
            assertion_id=result.current_assertion_id or result.correction.target_id
        )
        await _notify_feedback_assertion_changed(host, current_assertion)
        return {
            "correction": asdict(result.correction),
            "current_assertion": current_assertion,
            "subject_revision": result.subject_revision,
            "created": result.created,
        }

    async def get_assertion_correction_history(
        self,
        *,
        slot_key: str,
    ) -> Dict[str, Any]:
        """Return assertion versions and user corrections for one logical slot."""
        host = cast(_FeedbackHostProtocol, self)
        await host.initialize()
        history = await MemoryCorrectionService(host.db_path).get_assertion_history(
            slot_key_value=slot_key
        )
        assertions: list[Dict[str, Any]] = []
        for row in history["assertions"]:
            assertion = await host.get_tom_assertion(assertion_id=str(row["assertion_id"]))
            if assertion is not None:
                assertions.append(assertion)
        return {
            "assertions": assertions,
            "corrections": [asdict(item) for item in history["corrections"]],
        }

    async def list_assertion_corrections(
        self,
        *,
        assertion_id: str,
        limit: int = 100,
    ) -> list[Dict[str, Any]]:
        """List corrections originally applied to one assertion version."""
        host = cast(_FeedbackHostProtocol, self)
        await host.initialize()
        corrections = await MemoryCorrectionRepository(host.db_path).list_for_target(
            target_kind=CorrectionTargetKind.ASSERTION,
            target_id=assertion_id,
            limit=limit,
        )
        return [asdict(item) for item in corrections]

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
