"""Transactional services for user-authoritative L2 memory corrections."""

from __future__ import annotations

import json
import math
import time
import uuid
from collections.abc import Mapping
from typing import Any

import aiosqlite

from ....core.sqlite import sqlite_connection_async
from ..assertions.settings import (
    USER_REJECTED_CONFIDENCE,
    assertion_float_setting,
)
from .cache_signals import mark_subject_changed
from .fingerprints import (
    SUPPORTED_SCOPE_FIELDS,
    assertion_claim_fingerprint,
    assertion_slot_key,
    canonical_scope_json,
    scope_key,
)
from .models import (
    ApplyAssertionCorrectionCommand,
    ApplyRelationshipCorrectionCommand,
    AssertionCorrectionResult,
    CorrectionKind,
    CorrectionRule,
    CorrectionRuleKind,
    CorrectionState,
    CorrectionTargetKind,
    MemoryCorrection,
    NewMemoryCorrection,
    RelationshipCorrectionResult,
)
from .repository import MemoryCorrectionRepository

_INACTIVE_ASSERTION_STATUSES = {
    "archived",
    "expired",
    "invalidated",
    "shadow",
    "superseded",
    "user_rejected",
}
_ALLOWED_SCOPE_KEYS = SUPPORTED_SCOPE_FIELDS
_RESTORABLE_ASSERTION_COLUMNS = (
    "entity_id",
    "entity_type",
    "trait_family",
    "trait_name",
    "trait_value",
    "confidence_score",
    "evidence_events",
    "volatility_index",
    "source_domain",
    "inference_depth",
    "validation_state",
    "first_inferred_at",
    "last_validated_at",
    "target_entity_id",
    "target_entity_type",
    "target_scope",
    "temporal_scope",
    "decay_policy",
    "decay_anchor_at",
    "context_ref_id",
    "expires_at",
    "user_feedback",
    "user_feedback_at",
    "status",
    "superseded_by",
    "superseded_at",
    "memory_subdomain",
    "natural_summary",
    "created_at",
    "slot_key",
    "claim_fingerprint",
    "authority_ref",
    "version_root_id",
    "previous_version_id",
    "valid_from",
    "valid_to",
    "scope_key",
    "scope_json",
)


class MemoryCorrectionConflictError(RuntimeError):
    """Raised when a correction targets a stale or already changed claim."""


class MemoryCorrectionValidationError(ValueError):
    """Raised when correction semantics are incomplete or not executable."""

    def __init__(self, message: str, *, code: str | None = None):
        super().__init__(message)
        self.code = code


class MemoryCorrectionService:
    """Apply and revert assertion corrections in one SQLite transaction."""

    def __init__(self, db_path: str):
        self.db_path = db_path
        self.repository = MemoryCorrectionRepository(db_path)

    async def apply_relationship_correction(
        self,
        command: ApplyRelationshipCorrectionCommand,
    ) -> RelationshipCorrectionResult | None:
        """Apply a governed relationship correction."""
        from .relationship_service import RelationshipCorrectionService

        return await RelationshipCorrectionService(self.db_path).apply(command)

    async def revert_relationship_correction(
        self,
        *,
        correction_id: str,
        request_id: str,
        actor_id: str,
    ) -> RelationshipCorrectionResult | None:
        """Revert a governed relationship correction."""
        from .relationship_service import RelationshipCorrectionService

        return await RelationshipCorrectionService(self.db_path).revert(
            correction_id=correction_id,
            request_id=request_id,
            actor_id=actor_id,
        )

    async def get_relationship_correction_history(
        self,
        *,
        triple_id: str,
    ) -> dict[str, Any]:
        """Return immutable versions and corrections for a relationship."""
        from .relationship_service import RelationshipCorrectionService

        return await RelationshipCorrectionService(self.db_path).history(
            triple_id=triple_id
        )

    async def apply_assertion_correction(
        self,
        command: ApplyAssertionCorrectionCommand,
    ) -> AssertionCorrectionResult | None:
        """Apply one idempotent correction to the current assertion version."""
        _validate_assertion_command(command)
        now = time.time()

        async with sqlite_connection_async(self.db_path) as db:
            db.row_factory = aiosqlite.Row
            await db.execute("BEGIN IMMEDIATE")
            try:
                existing_correction = await self.repository.get_by_request_id_on_connection(
                    db,
                    command.request_id,
                )
                if existing_correction is not None:
                    await db.commit()
                    return _result_for_existing_correction(existing_correction)

                row = await _load_assertion(db, command.assertion_id)
                if row is None:
                    await db.commit()
                    return None

                before = dict(row)
                _ensure_assertion_is_correctable(before, command)
                old_slot_key, old_claim_fingerprint = await _ensure_assertion_identity(db, before)
                old_scope_key = str(before.get("scope_key") or "global")
                effective_at = _effective_at(command, now)
                _ensure_effective_at_not_before_assertion(before, command, effective_at)
                correction_id = f"correction_{uuid.uuid4().hex}"
                replacement_id = (
                    f"assert_{uuid.uuid4().hex}" if command.replacement_value is not None else None
                )
                replacement_scope = dict(command.scope or {})
                replacement_scope_key = scope_key(replacement_scope)
                replacement_fingerprint = (
                    assertion_claim_fingerprint(
                        slot_key_value=old_slot_key,
                        trait_value=command.replacement_value,
                        scope_key_value=replacement_scope_key,
                    )
                    if command.replacement_value is not None
                    else None
                )

                correction = NewMemoryCorrection(
                    correction_id=correction_id,
                    request_id=command.request_id,
                    actor_id=command.actor_id,
                    target_kind=CorrectionTargetKind.ASSERTION,
                    target_id=command.assertion_id,
                    slot_key=old_slot_key,
                    claim_fingerprint=old_claim_fingerprint,
                    correction_kind=command.correction_kind,
                    reason=command.reason,
                    before=before,
                    replacement=(
                        {
                            "value": command.replacement_value,
                            "scope": replacement_scope,
                        }
                        if command.replacement_value is not None
                        else None
                    ),
                    effective_at=(
                        effective_at
                        if command.correction_kind == CorrectionKind.SITUATION_CHANGED
                        else None
                    ),
                    scope=(replacement_scope or None),
                    source_event_id=command.source_event_id,
                    audit_event_id=command.audit_event_id,
                    replacement_target_id=replacement_id,
                    created_at=now,
                )
                await self.repository.insert_correction(db, correction)
                await _deactivate_original_assertion(
                    db,
                    command=command,
                    replacement_id=replacement_id,
                    effective_at=effective_at,
                    now=now,
                )
                if replacement_id is not None and replacement_fingerprint is not None:
                    await _insert_replacement_assertion(
                        db,
                        before=before,
                        assertion_id=replacement_id,
                        correction_id=correction_id,
                        trait_value=str(command.replacement_value),
                        claim_fingerprint=replacement_fingerprint,
                        scope=replacement_scope,
                        scope_key_value=replacement_scope_key,
                        source_event_id=command.source_event_id,
                        valid_from=effective_at,
                        now=now,
                    )
                for rule in _build_assertion_rules(
                    correction_id=correction_id,
                    command=command,
                    slot_key_value=old_slot_key,
                    old_claim_fingerprint=old_claim_fingerprint,
                    old_scope_key=old_scope_key,
                    replacement_fingerprint=replacement_fingerprint,
                    replacement_scope_key=replacement_scope_key,
                    effective_at=effective_at,
                    now=now,
                ):
                    await self.repository.insert_rule(db, rule)
                l3_subjects = await self.repository.invalidate_l3_insights_on_connection(
                    db,
                    source_kind="assertion",
                    source_ids=[command.assertion_id],
                    subject_keys=[str(before["entity_id"])],
                    updated_at=now,
                )
                subject_revision = await self.repository.bump_subject_revision(
                    db,
                    subject_key=str(before["entity_id"]),
                    updated_at=now,
                )
                await self.repository.enqueue_subject_derivations(
                    db,
                    correction_id=correction_id,
                    subject_key=str(before["entity_id"]),
                    target_revision=subject_revision,
                    include_l3=str(before["entity_id"]) in l3_subjects,
                    now=now,
                )
                if command.audit_event_id is not None:
                    await self.repository.enqueue_derivation_job(
                        db,
                        correction_id=correction_id,
                        job_kind="l1_audit",
                        target_key=command.audit_event_id,
                        target_revision=0,
                        now=now,
                    )
                await db.commit()
            except Exception:
                await db.rollback()
                raise

        mark_subject_changed(self.db_path, str(before["entity_id"]))

        stored = await self.repository.get(correction_id)
        assert stored is not None
        return AssertionCorrectionResult(
            correction=stored,
            created=True,
            current_assertion_id=replacement_id,
            subject_revision=subject_revision,
        )

    async def revert_assertion_correction(
        self,
        *,
        correction_id: str,
        request_id: str,
        actor_id: str,
    ) -> AssertionCorrectionResult | None:
        """Revert an assertion correction unless a newer correction depends on it."""
        now = time.time()
        async with sqlite_connection_async(self.db_path) as db:
            db.row_factory = aiosqlite.Row
            await db.execute("BEGIN IMMEDIATE")
            try:
                row = await _load_correction(db, correction_id)
                if row is None:
                    await db.commit()
                    return None
                correction = MemoryCorrection.from_row(dict(row))
                if correction.target_kind != CorrectionTargetKind.ASSERTION:
                    raise MemoryCorrectionValidationError("Correction does not target an assertion")
                if correction.state == CorrectionState.REVERTED:
                    await db.commit()
                    return AssertionCorrectionResult(
                        correction=correction,
                        created=False,
                        current_assertion_id=correction.target_id,
                        subject_revision=None,
                    )
                if await _has_newer_active_correction(db, correction):
                    raise MemoryCorrectionConflictError("A newer correction must be reverted first")

                if correction.replacement_target_id:
                    await db.execute(
                        """
                        UPDATE tom_trait_assertions
                        SET status = 'archived', valid_to = COALESCE(valid_to, ?),
                            updated_at = ?
                        WHERE assertion_id = ?
                        """,
                        (now, now, correction.replacement_target_id),
                    )
                await _restore_original_assertion(
                    db,
                    assertion_id=correction.target_id,
                    before=correction.before,
                    now=now,
                )
                await db.execute(
                    "UPDATE memory_correction_rules SET active = 0 WHERE correction_id = ?",
                    (correction_id,),
                )
                await db.execute(
                    """
                    UPDATE memory_corrections
                    SET state = 'reverted', reverted_at = ?, reverted_by = ?
                    WHERE correction_id = ?
                    """,
                    (now, f"{actor_id}:{request_id}", correction_id),
                )
                l3_subjects = await self.repository.invalidate_l3_insights_on_connection(
                    db,
                    source_kind="assertion",
                    source_ids=[
                        correction.target_id,
                        correction.replacement_target_id or "",
                    ],
                    subject_keys=[str(correction.before["entity_id"])],
                    updated_at=now,
                )
                subject_revision = await self.repository.bump_subject_revision(
                    db,
                    subject_key=str(correction.before["entity_id"]),
                    updated_at=now,
                )
                await self.repository.enqueue_subject_derivations(
                    db,
                    correction_id=correction_id,
                    subject_key=str(correction.before["entity_id"]),
                    target_revision=subject_revision,
                    include_l3=str(correction.before["entity_id"]) in l3_subjects,
                    now=now,
                )
                await db.commit()
            except Exception:
                await db.rollback()
                raise

        mark_subject_changed(self.db_path, str(correction.before["entity_id"]))

        stored = await self.repository.get(correction_id)
        assert stored is not None
        return AssertionCorrectionResult(
            correction=stored,
            created=True,
            current_assertion_id=correction.target_id,
            subject_revision=subject_revision,
        )

    async def get_assertion_history(self, *, slot_key_value: str) -> dict[str, Any]:
        """Return claim versions and correction records for one assertion slot."""
        async with sqlite_connection_async(self.db_path) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute(
                """
                SELECT * FROM tom_trait_assertions
                WHERE slot_key = ?
                ORDER BY COALESCE(valid_from, first_inferred_at), created_at
                """,
                (slot_key_value,),
            ) as cursor:
                assertion_rows = await cursor.fetchall()
            async with db.execute(
                """
                SELECT * FROM memory_corrections
                WHERE target_kind = 'assertion' AND slot_key = ?
                ORDER BY created_at
                """,
                (slot_key_value,),
            ) as cursor:
                correction_rows = await cursor.fetchall()
        return {
            "assertions": [dict(row) for row in assertion_rows],
            "corrections": [MemoryCorrection.from_row(dict(row)) for row in correction_rows],
        }


def _validate_assertion_command(command: ApplyAssertionCorrectionCommand) -> None:
    if not command.request_id.strip():
        raise MemoryCorrectionValidationError("request_id is required")
    if not command.actor_id.strip():
        raise MemoryCorrectionValidationError("actor_id is required")
    if command.replacement_value is not None and not command.replacement_value.strip():
        raise MemoryCorrectionValidationError("replacement_value cannot be blank")
    if command.correction_kind == CorrectionKind.SITUATION_CHANGED:
        if command.replacement_value is None:
            raise MemoryCorrectionValidationError("situation_changed requires replacement_value")
        if command.effective_at is None:
            raise MemoryCorrectionValidationError("situation_changed requires effective_at")
    if command.correction_kind == CorrectionKind.SCOPE_REFINEMENT:
        if command.replacement_value is None:
            raise MemoryCorrectionValidationError("scope_refinement requires replacement_value")
        if not command.scope:
            raise MemoryCorrectionValidationError("scope_refinement requires scope")
    unknown_scope_keys = set(command.scope or {}) - _ALLOWED_SCOPE_KEYS
    if unknown_scope_keys:
        unknown = ", ".join(sorted(str(item) for item in unknown_scope_keys))
        raise MemoryCorrectionValidationError(f"Unsupported scope fields: {unknown}")


def _ensure_assertion_is_correctable(
    before: Mapping[str, Any],
    command: ApplyAssertionCorrectionCommand,
) -> None:
    status = str(before.get("status") or "active")
    if status in _INACTIVE_ASSERTION_STATUSES:
        raise MemoryCorrectionConflictError("Assertion is no longer current")
    if command.expected_updated_at is None:
        return
    actual_updated_at = float(before["updated_at"])
    if not math.isclose(
        actual_updated_at,
        float(command.expected_updated_at),
        rel_tol=0.0,
        abs_tol=1e-6,
    ):
        raise MemoryCorrectionConflictError("Assertion changed after it was loaded")


async def _load_assertion(
    db: aiosqlite.Connection,
    assertion_id: str,
) -> aiosqlite.Row | None:
    async with db.execute(
        "SELECT * FROM tom_trait_assertions WHERE assertion_id = ?",
        (assertion_id,),
    ) as cursor:
        return await cursor.fetchone()


async def _load_correction(
    db: aiosqlite.Connection,
    correction_id: str,
) -> aiosqlite.Row | None:
    async with db.execute(
        "SELECT * FROM memory_corrections WHERE correction_id = ?",
        (correction_id,),
    ) as cursor:
        return await cursor.fetchone()


async def _ensure_assertion_identity(
    db: aiosqlite.Connection,
    before: dict[str, Any],
) -> tuple[str, str]:
    slot_key_value = str(before.get("slot_key") or "") or assertion_slot_key(
        entity_type=str(before["entity_type"]),
        entity_id=str(before["entity_id"]),
        trait_name=str(before["trait_name"]),
        target_entity_id=str(before.get("target_entity_id") or ""),
    )
    scope_key_value = str(before.get("scope_key") or "global")
    claim_fingerprint = str(before.get("claim_fingerprint") or "") or (
        assertion_claim_fingerprint(
            slot_key_value=slot_key_value,
            trait_value=before["trait_value"],
            scope_key_value=scope_key_value,
        )
    )
    if (
        before.get("slot_key") != slot_key_value
        or before.get("claim_fingerprint") != claim_fingerprint
    ):
        await db.execute(
            """
            UPDATE tom_trait_assertions
            SET slot_key = ?, claim_fingerprint = ?
            WHERE assertion_id = ?
            """,
            (slot_key_value, claim_fingerprint, before["assertion_id"]),
        )
        before["slot_key"] = slot_key_value
        before["claim_fingerprint"] = claim_fingerprint
    return slot_key_value, claim_fingerprint


def _effective_at(command: ApplyAssertionCorrectionCommand, now: float) -> float:
    if command.correction_kind == CorrectionKind.SITUATION_CHANGED:
        assert command.effective_at is not None
        return float(command.effective_at)
    return now


def _ensure_effective_at_not_before_assertion(
    before: Mapping[str, Any],
    command: ApplyAssertionCorrectionCommand,
    effective_at: float,
) -> None:
    if command.correction_kind != CorrectionKind.SITUATION_CHANGED:
        return
    valid_from = float(
        before.get("valid_from")
        or before.get("first_inferred_at")
        or before.get("created_at")
        or 0.0
    )
    if valid_from > 0 and effective_at < valid_from - 0.000001:
        raise MemoryCorrectionValidationError(
            "effective_at cannot be earlier than the assertion start time",
            code="effective_at_before_target",
        )


async def _deactivate_original_assertion(
    db: aiosqlite.Connection,
    *,
    command: ApplyAssertionCorrectionCommand,
    replacement_id: str | None,
    effective_at: float,
    now: float,
) -> None:
    if command.correction_kind == CorrectionKind.RECORD_ERROR:
        rejected_confidence = assertion_float_setting(
            "user_rejected_confidence",
            USER_REJECTED_CONFIDENCE,
        )
        await db.execute(
            """
            UPDATE tom_trait_assertions
            SET status = 'user_rejected', validation_state = 'user_rejected',
                user_feedback = 'rejected', user_feedback_at = ?,
                confidence_score = ?, superseded_by = ?, superseded_at = ?,
                updated_at = ?
            WHERE assertion_id = ?
            """,
            (
                now,
                rejected_confidence,
                replacement_id,
                now if replacement_id else None,
                now,
                command.assertion_id,
            ),
        )
        return
    await db.execute(
        """
        UPDATE tom_trait_assertions
        SET status = 'superseded', superseded_by = ?, superseded_at = ?,
            valid_to = ?, updated_at = ?
        WHERE assertion_id = ?
        """,
        (replacement_id, now, effective_at, now, command.assertion_id),
    )


async def _insert_replacement_assertion(
    db: aiosqlite.Connection,
    *,
    before: Mapping[str, Any],
    assertion_id: str,
    correction_id: str,
    trait_value: str,
    claim_fingerprint: str,
    scope: Mapping[str, Any],
    scope_key_value: str,
    source_event_id: str | None,
    valid_from: float,
    now: float,
) -> None:
    evidence_events = [source_event_id] if source_event_id else []
    await db.execute(
        """
        INSERT INTO tom_trait_assertions(
            assertion_id, entity_id, entity_type, trait_family, trait_name,
            trait_value, confidence_score, evidence_events, volatility_index,
            source_domain, inference_depth, validation_state, first_inferred_at,
            last_validated_at, target_entity_id, target_entity_type, target_scope,
            temporal_scope, decay_policy, decay_anchor_at, context_ref_id,
            expires_at, user_feedback, user_feedback_at, status, superseded_by,
            superseded_at, memory_subdomain, natural_summary, created_at, updated_at,
            slot_key, claim_fingerprint, authority_ref, version_root_id,
            previous_version_id, valid_from, valid_to, scope_key, scope_json
        ) VALUES (
            ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?,
            ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?
        )
        """,
        (
            assertion_id,
            str(before["entity_id"]),
            str(before["entity_type"]),
            str(before["trait_family"]),
            str(before["trait_name"]),
            trait_value,
            0.95,
            json.dumps(evidence_events, ensure_ascii=False),
            float(before["volatility_index"]),
            "user_correction",
            "explicit",
            "stable",
            valid_from,
            now,
            str(before.get("target_entity_id") or ""),
            str(before.get("target_entity_type") or ""),
            str(before.get("target_scope") or "global"),
            str(before.get("temporal_scope") or "session"),
            None,
            None,
            str(source_event_id or ""),
            None,
            "confirmed",
            now,
            "stable",
            None,
            None,
            str(before.get("memory_subdomain") or "state"),
            "",
            now,
            now,
            str(before["slot_key"]),
            claim_fingerprint,
            f"correction:{correction_id}",
            str(before.get("version_root_id") or before["assertion_id"]),
            str(before["assertion_id"]),
            valid_from,
            None,
            scope_key_value,
            canonical_scope_json(scope),
        ),
    )


def _build_assertion_rules(
    *,
    correction_id: str,
    command: ApplyAssertionCorrectionCommand,
    slot_key_value: str,
    old_claim_fingerprint: str,
    old_scope_key: str,
    replacement_fingerprint: str | None,
    replacement_scope_key: str,
    effective_at: float,
    now: float,
) -> list[CorrectionRule]:
    rules: list[CorrectionRule] = []
    if command.correction_kind == CorrectionKind.RECORD_ERROR:
        rules.append(
            _new_rule(
                correction_id=correction_id,
                rule_kind=CorrectionRuleKind.BLOCK_CLAIM,
                slot_key_value=slot_key_value,
                claim_fingerprint=old_claim_fingerprint,
                scope_key_value=old_scope_key,
                now=now,
            )
        )
    elif command.correction_kind == CorrectionKind.SITUATION_CHANGED:
        rules.append(
            _new_rule(
                correction_id=correction_id,
                rule_kind=CorrectionRuleKind.CLOSE_BEFORE,
                slot_key_value=slot_key_value,
                claim_fingerprint=old_claim_fingerprint,
                scope_key_value=old_scope_key,
                effective_to=effective_at,
                now=now,
            )
        )
    else:
        rules.append(
            _new_rule(
                correction_id=correction_id,
                rule_kind=CorrectionRuleKind.SCOPE_ONLY,
                slot_key_value=slot_key_value,
                claim_fingerprint=old_claim_fingerprint,
                scope_key_value=replacement_scope_key,
                now=now,
            )
        )
    if replacement_fingerprint is not None:
        rules.append(
            _new_rule(
                correction_id=correction_id,
                rule_kind=CorrectionRuleKind.AUTHORITATIVE_SLOT,
                slot_key_value=slot_key_value,
                claim_fingerprint=replacement_fingerprint,
                scope_key_value=replacement_scope_key,
                effective_from=effective_at,
                now=now,
            )
        )
    return rules


def _new_rule(
    *,
    correction_id: str,
    rule_kind: CorrectionRuleKind,
    slot_key_value: str,
    claim_fingerprint: str | None,
    scope_key_value: str,
    now: float,
    effective_from: float | None = None,
    effective_to: float | None = None,
) -> CorrectionRule:
    return CorrectionRule(
        rule_id=f"correction_rule_{uuid.uuid4().hex}",
        correction_id=correction_id,
        target_kind=CorrectionTargetKind.ASSERTION,
        rule_kind=rule_kind,
        slot_key=slot_key_value,
        claim_fingerprint=claim_fingerprint,
        scope_key=scope_key_value,
        effective_from=effective_from,
        effective_to=effective_to,
        created_at=now,
    )


async def _has_newer_active_correction(
    db: aiosqlite.Connection,
    correction: MemoryCorrection,
) -> bool:
    async with db.execute(
        """
        SELECT 1 FROM memory_corrections
        WHERE target_kind = 'assertion' AND slot_key = ? AND state = 'active'
          AND correction_id != ? AND created_at >= ?
        LIMIT 1
        """,
        (correction.slot_key, correction.correction_id, correction.created_at),
    ) as cursor:
        return await cursor.fetchone() is not None


async def _restore_original_assertion(
    db: aiosqlite.Connection,
    *,
    assertion_id: str,
    before: Mapping[str, Any],
    now: float,
) -> None:
    missing = [column for column in _RESTORABLE_ASSERTION_COLUMNS if column not in before]
    if missing:
        raise MemoryCorrectionValidationError(
            f"Correction snapshot is missing assertion fields: {', '.join(missing)}"
        )
    assignments = ", ".join(f"{column} = ?" for column in _RESTORABLE_ASSERTION_COLUMNS)
    values = [before[column] for column in _RESTORABLE_ASSERTION_COLUMNS]
    await db.execute(
        f"UPDATE tom_trait_assertions SET {assignments}, updated_at = ? WHERE assertion_id = ?",
        (*values, now, assertion_id),
    )


def _result_for_existing_correction(
    correction: MemoryCorrection,
) -> AssertionCorrectionResult:
    current_assertion_id = correction.replacement_target_id
    if correction.state == CorrectionState.REVERTED:
        current_assertion_id = correction.target_id
    return AssertionCorrectionResult(
        correction=correction,
        created=False,
        current_assertion_id=current_assertion_id,
        subject_revision=None,
    )


__all__ = [
    "MemoryCorrectionConflictError",
    "MemoryCorrectionService",
    "MemoryCorrectionValidationError",
]
