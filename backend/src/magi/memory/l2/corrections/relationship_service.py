"""Transactional user correction service for L2 relationship claims."""

from __future__ import annotations

import json
import math
import time
import uuid
from collections.abc import Mapping
from typing import Any

import aiosqlite

from ....core.sqlite import sqlite_connection_async
from ..graph.versions import append_knowledge_graph_version, list_knowledge_graph_versions
from ..graph_conflicts import GraphConflictRule, relationship_predicate_slot
from ..storage.utils import normalize_store_entity_ref, normalize_store_entity_type
from .cache_signals import mark_subject_changed
from .current_claim import resolve_current_claim
from .evidence_ledger import append_claim_evidence_event_ids
from .fingerprints import (
    SUPPORTED_SCOPE_FIELDS,
    canonical_scope_json,
    relationship_claim_fingerprint,
    relationship_slot_key,
    relationship_triple_id,
    scope_key,
    stored_context_scope,
)
from .forget_guard import correction_target_was_forgotten
from .models import (
    ApplyRelationshipCorrectionCommand,
    CorrectionKind,
    CorrectionRule,
    CorrectionRuleKind,
    CorrectionState,
    CorrectionTargetKind,
    MemoryCorrection,
    NewMemoryCorrection,
    RelationshipCorrectionResult,
)
from .ownership import correction_authority_ref, has_correction_owner
from .repository import MemoryCorrectionRepository
from .relationship_conflict_effects import (
    RelationshipConflictEffects,
    apply_relationship_conflict_effects,
    load_relationship_graph_conflict_rules,
    restore_relationship_conflict_effects,
)
from .request_identity import correction_request_fingerprint
from .revert_blocks import correction_revert_block_reason_on_connection
from .service import (
    MemoryCorrectionConflictError,
    MemoryCorrectionValidationError,
    ensure_correction_source_event_is_active,
)

_RESTORABLE_RELATIONSHIP_COLUMNS = (
    "subject_id",
    "subject_type",
    "predicate",
    "object_id",
    "object_type",
    "fact_kind",
    "confidence",
    "evidence_event_ids",
    "evidence_text",
    "natural_summary",
    "observation_count",
    "first_observed_at",
    "last_observed_at",
    "last_confirmed_at",
    "source_type",
    "extraction_method",
    "embedding_status",
    "embedding_profile_id",
    "last_embedded_at",
    "expires_at",
    "valid_from",
    "valid_to",
    "status",
    "status_reason",
    "deprecated_by",
    "deprecated_at",
    "created_at",
    "evidence_class",
    "slot_key",
    "claim_fingerprint",
    "authority_ref",
    "scope_key",
    "scope_json",
)
_ALLOWED_REPLACEMENT_FIELDS = frozenset(
    {
        "subject_id",
        "subject_type",
        "predicate",
        "object_id",
        "object_type",
        "fact_kind",
    }
)


class RelationshipCorrectionService:
    """Apply and revert durable relationship corrections."""

    def __init__(
        self,
        db_path: str,
        *,
        graph_conflict_rules: Mapping[str, GraphConflictRule] | None = None,
    ):
        self.db_path = db_path
        self.repository = MemoryCorrectionRepository(db_path)
        self._graph_conflict_rules = (
            dict(graph_conflict_rules) if graph_conflict_rules is not None else None
        )

    async def apply(
        self,
        command: ApplyRelationshipCorrectionCommand,
    ) -> RelationshipCorrectionResult | None:
        async with sqlite_connection_async(self.db_path) as db:
            db.row_factory = aiosqlite.Row
            await db.execute("BEGIN IMMEDIATE")
            now = time.time()
            try:
                existing_correction = await self.repository.get_by_request_id_on_connection(
                    db,
                    command.request_id,
                )
                if existing_correction is not None:
                    await _ensure_relationship_retry_matches(
                        db,
                        self.repository,
                        existing_correction,
                        command,
                    )
                    await db.commit()
                    return await _relationship_correction_result(
                        self.db_path,
                        existing_correction,
                        created=False,
                        subject_revision=None,
                    )
                graph_conflict_rules = await self._load_graph_conflict_rules(db)
                _validate_command(command)
                await ensure_correction_source_event_is_active(
                    db,
                    source_event_id=command.source_event_id,
                )
                row = await _load_edge(db, command.triple_id)
                if row is None:
                    await db.commit()
                    return None
                before = dict(row)
                _ensure_correctable(before, command)
                old_slot_key, old_claim_fingerprint = await _ensure_edge_identity(db, before)
                await _ensure_initial_version(db, command.triple_id, now=now)

                effective_at = _effective_at(command, now)
                _ensure_effective_at_not_before_relationship(before, command, effective_at)
                transition_is_future = _is_future_situation_change(
                    command.correction_kind,
                    effective_at=effective_at,
                    now=now,
                )
                correction_id = f"correction_{uuid.uuid4().hex}"
                replacement = _normalize_replacement(
                    command,
                    before,
                    effective_at,
                    graph_conflict_rules=graph_conflict_rules,
                )
                replacement_scope = _effective_relationship_scope(command, before)
                _ensure_relationship_correction_changes_claim(
                    before,
                    command,
                    replacement,
                    replacement_scope,
                )
                replacement_id = str(replacement["triple_id"]) if replacement is not None else None
                if command.correction_kind == CorrectionKind.SCOPE_REFINEMENT:
                    assert replacement is not None
                    await _ensure_relationship_scope_available(
                        db,
                        slot_key_value=old_slot_key,
                        scope_key_value=str(replacement.get("scope_key") or "global"),
                        excluded_triple_ids={command.triple_id, replacement_id or ""},
                        effective_at=now,
                        message=(
                            "The selected scope already has a current memory. "
                            "Review it before moving this memory."
                        ),
                    )
                if replacement_id and replacement_id != command.triple_id:
                    replacement_exists = await _ensure_replacement_reactivatable(
                        db,
                        replacement_id,
                        effective_at=effective_at,
                    )
                    if replacement_exists:
                        await _ensure_initial_version(
                            db,
                            replacement_id,
                            now=now - 0.000001,
                        )

                correction = NewMemoryCorrection(
                    correction_id=correction_id,
                    request_id=command.request_id,
                    actor_id=command.actor_id,
                    target_kind=CorrectionTargetKind.EDGE,
                    target_id=command.triple_id,
                    slot_key=old_slot_key,
                    claim_fingerprint=old_claim_fingerprint,
                    correction_kind=command.correction_kind,
                    reason=command.reason,
                    before=before,
                    request_fingerprint=_relationship_request_fingerprint(command),
                    replacement=replacement,
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
                await _close_original_edge(
                    db,
                    command=command,
                    replacement_id=replacement_id,
                    effective_at=effective_at,
                    now=now,
                )
                await append_knowledge_graph_version(
                    db,
                    triple_id=command.triple_id,
                    correction_id=correction_id,
                    created_at=now,
                )
                conflict_effects = RelationshipConflictEffects()
                if replacement is not None:
                    await _write_authoritative_replacement(
                        db,
                        replacement=replacement,
                        correction_id=correction_id,
                        source_event_id=command.source_event_id,
                        now=now,
                    )
                    if command.source_event_id is not None:
                        await append_claim_evidence_event_ids(
                            db,
                            target_kind=CorrectionTargetKind.EDGE,
                            claim_fingerprint=str(replacement["claim_fingerprint"]),
                            event_ids=[command.source_event_id],
                            observed_at=(
                                command.source_event_observed_at
                                if command.source_event_observed_at is not None
                                else now
                            ),
                            created_at=now,
                            event_timestamps=(
                                {
                                    command.source_event_id: command.source_event_observed_at,
                                }
                                if command.source_event_observed_at is not None
                                else None
                            ),
                            observed_from=float(before["first_observed_at"]),
                            observed_to=now,
                            mark_missing_timestamps_approximate=True,
                        )
                    await append_knowledge_graph_version(
                        db,
                        triple_id=replacement_id,
                        correction_id=correction_id,
                        created_at=now + 0.000001,
                    )
                    if not transition_is_future:
                        conflict_effects = await apply_relationship_conflict_effects(
                            db,
                            replacement=replacement,
                            correction_id=correction_id,
                            graph_conflict_rules=graph_conflict_rules,
                            effective_at=effective_at,
                            now=now + 0.000002,
                        )
                for rule in _build_rules(
                    correction_id=correction_id,
                    command=command,
                    old_slot_key=old_slot_key,
                    old_claim_fingerprint=old_claim_fingerprint,
                    old_scope_key=str(before.get("scope_key") or "global"),
                    replacement=replacement,
                    effective_at=effective_at,
                    now=now,
                ):
                    await self.repository.insert_rule(db, rule)
                affected_subjects: list[str] = []
                subject_revision: int | None = None
                if not transition_is_future:
                    correction_subjects = list(
                        dict.fromkeys(
                            [
                                *_affected_subject_keys(before, replacement),
                                *conflict_effects.subject_keys,
                            ]
                        )
                    )
                    l3_subjects = await self.repository.invalidate_l3_insights_on_connection(
                        db,
                        source_kind="edge",
                        source_ids=[
                            command.triple_id,
                            replacement_id or "",
                            *conflict_effects.edge_ids,
                        ],
                        subject_keys=correction_subjects,
                        updated_at=now,
                    )
                    affected_subjects = list(dict.fromkeys([*correction_subjects, *l3_subjects]))
                    subject_revisions: dict[str, int] = {}
                    for subject_key in affected_subjects:
                        revision = await self.repository.bump_subject_revision(
                            db,
                            subject_key=subject_key,
                            updated_at=now,
                        )
                        subject_revisions[subject_key] = revision
                        await self.repository.enqueue_subject_derivations(
                            db,
                            correction_id=correction_id,
                            subject_key=subject_key,
                            target_revision=revision,
                            include_l3=subject_key in l3_subjects,
                            now=now,
                        )
                    subject_revision = subject_revisions[str(before["subject_id"])]
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

        for subject_key in affected_subjects:
            mark_subject_changed(self.db_path, subject_key)

        stored = await self.repository.get(correction_id)
        assert stored is not None
        return await _relationship_correction_result(
            self.db_path,
            stored,
            created=True,
            subject_revision=subject_revision,
        )

    async def _load_graph_conflict_rules(
        self,
        db: aiosqlite.Connection,
    ) -> dict[str, GraphConflictRule]:
        if self._graph_conflict_rules is not None:
            return self._graph_conflict_rules
        rules = await load_relationship_graph_conflict_rules(db)
        self._graph_conflict_rules = rules
        return rules

    async def revert(
        self,
        *,
        correction_id: str,
        request_id: str,
        actor_id: str,
    ) -> RelationshipCorrectionResult | None:
        async with sqlite_connection_async(self.db_path) as db:
            db.row_factory = aiosqlite.Row
            await db.execute("BEGIN IMMEDIATE")
            now = time.time()
            try:
                correction_row = await _load_correction(db, correction_id)
                if correction_row is None:
                    await db.commit()
                    return None
                correction = MemoryCorrection.from_row(dict(correction_row))
                transition_was_pending = (
                    correction.correction_kind == CorrectionKind.SITUATION_CHANGED
                    and correction_row["transition_applied_at"] is None
                )
                if correction.target_kind != CorrectionTargetKind.EDGE:
                    raise MemoryCorrectionValidationError(
                        "Correction does not target a relationship"
                    )
                if correction.state == CorrectionState.REVERTED:
                    await db.commit()
                    return await _relationship_correction_result(
                        self.db_path,
                        correction,
                        created=False,
                        subject_revision=None,
                    )
                if await correction_target_was_forgotten(db, correction):
                    raise MemoryCorrectionConflictError(
                        "Forgotten memories cannot be restored",
                        code="memory_forgotten",
                    )
                revert_block_reason = await correction_revert_block_reason_on_connection(
                    db,
                    correction_id,
                )
                if revert_block_reason:
                    raise MemoryCorrectionConflictError(
                        "This correction can no longer be safely reverted after correction histories converged",
                        code=(
                            "identity_merge_revert_blocked"
                            if revert_block_reason == "identity_merge"
                            else "correction_lineage_revert_blocked"
                        ),
                    )
                if await _has_newer_correction(db, correction):
                    raise MemoryCorrectionConflictError("A newer correction must be reverted first")

                replacement_id = correction.replacement_target_id
                await _ensure_relationship_scope_available(
                    db,
                    slot_key_value=correction.slot_key,
                    scope_key_value=str(correction.before.get("scope_key") or "global"),
                    excluded_triple_ids={correction.target_id, replacement_id or ""},
                    effective_at=now,
                    message=(
                        "The original scope now has a current memory. "
                        "Review it before reverting this correction."
                    ),
                )
                if replacement_id and replacement_id != correction.target_id:
                    archive_cursor = await db.execute(
                        """
                        UPDATE knowledge_graph
                        SET status = 'archived', valid_to = COALESCE(valid_to, ?),
                            updated_at = ?
                        WHERE triple_id = ? AND authority_ref = ?
                        """,
                        (
                            now,
                            now,
                            replacement_id,
                            correction_authority_ref(correction_id),
                        ),
                    )
                    if archive_cursor.rowcount:
                        await append_knowledge_graph_version(
                            db,
                            triple_id=replacement_id,
                            correction_id=correction_id,
                            created_at=now,
                        )
                conflict_effects = await restore_relationship_conflict_effects(
                    db,
                    correction_id=correction_id,
                    replacement_id=replacement_id,
                    now=now + 0.000001,
                )
                await _restore_original_edge(
                    db,
                    triple_id=correction.target_id,
                    before=correction.before,
                    now=now,
                )
                await append_knowledge_graph_version(
                    db,
                    triple_id=correction.target_id,
                    correction_id=correction_id,
                    created_at=now + 0.000001,
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
                affected_subjects: list[str] = []
                subject_revision: int | None = None
                if not transition_was_pending:
                    correction_subjects = list(
                        dict.fromkeys(
                            [
                                *_affected_subject_keys(
                                    correction.before,
                                    correction.replacement,
                                ),
                                *conflict_effects.subject_keys,
                            ]
                        )
                    )
                    l3_subjects = await self.repository.invalidate_l3_insights_on_connection(
                        db,
                        source_kind="edge",
                        source_ids=[
                            correction.target_id,
                            correction.replacement_target_id or "",
                            *conflict_effects.edge_ids,
                        ],
                        subject_keys=correction_subjects,
                        updated_at=now,
                    )
                    affected_subjects = list(dict.fromkeys([*correction_subjects, *l3_subjects]))
                    subject_revisions: dict[str, int] = {}
                    for subject_key in affected_subjects:
                        revision = await self.repository.bump_subject_revision(
                            db,
                            subject_key=subject_key,
                            updated_at=now,
                        )
                        subject_revisions[subject_key] = revision
                        await self.repository.enqueue_subject_derivations(
                            db,
                            correction_id=correction_id,
                            subject_key=subject_key,
                            target_revision=revision,
                            include_l3=subject_key in l3_subjects,
                            now=now,
                        )
                    subject_revision = subject_revisions[str(correction.before["subject_id"])]
                await db.commit()
            except Exception:
                await db.rollback()
                raise

        for subject_key in affected_subjects:
            mark_subject_changed(self.db_path, subject_key)

        stored = await self.repository.get(correction_id)
        assert stored is not None
        return await _relationship_correction_result(
            self.db_path,
            stored,
            created=True,
            subject_revision=subject_revision,
        )

    async def history(self, *, triple_id: str) -> dict[str, Any]:
        async with sqlite_connection_async(self.db_path) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute(
                "SELECT slot_key FROM knowledge_graph WHERE triple_id = ?",
                (triple_id,),
            ) as cursor:
                edge_row = await cursor.fetchone()
            slot_key_value = str(edge_row["slot_key"] or "") if edge_row else ""
            async with db.execute(
                """
                WITH RECURSIVE correction_lineage AS (
                    SELECT * FROM memory_corrections
                    WHERE target_kind = 'edge'
                      AND (
                        (? != '' AND slot_key = ?)
                        OR target_id = ?
                        OR replacement_target_id = ?
                      )

                    UNION

                    SELECT candidate.*
                    FROM memory_corrections AS candidate
                    JOIN correction_lineage AS known
                      ON (known.slot_key != '' AND candidate.slot_key = known.slot_key)
                      OR candidate.target_id = known.target_id
                      OR candidate.target_id = known.replacement_target_id
                      OR candidate.replacement_target_id = known.target_id
                      OR candidate.replacement_target_id = known.replacement_target_id
                    WHERE candidate.target_kind = 'edge'
                )
                SELECT * FROM correction_lineage
                ORDER BY created_at
                """,
                (slot_key_value, slot_key_value, triple_id, triple_id),
            ) as cursor:
                rows = await cursor.fetchall()
            triple_ids = [triple_id]
            for row in rows:
                triple_ids.extend(
                    [
                        str(row["target_id"]),
                        str(row["replacement_target_id"] or ""),
                    ]
                )
            versions: list[dict[str, Any]] = []
            for versioned_triple_id in dict.fromkeys(item for item in triple_ids if item):
                versions.extend(
                    await list_knowledge_graph_versions(
                        db,
                        triple_id=versioned_triple_id,
                    )
                )
            versions.sort(key=lambda item: float(item.get("created_at") or 0.0))
        return {
            "versions": versions,
            "corrections": [MemoryCorrection.from_row(dict(row)) for row in rows],
        }


def _validate_command(command: ApplyRelationshipCorrectionCommand) -> None:
    if not command.request_id.strip() or not command.actor_id.strip():
        raise MemoryCorrectionValidationError("request_id and actor_id are required")
    if command.correction_kind == CorrectionKind.SITUATION_CHANGED:
        if command.replacement is None or command.effective_at is None:
            raise MemoryCorrectionValidationError(
                "situation_changed requires replacement and effective_at"
            )
    if command.correction_kind == CorrectionKind.SCOPE_REFINEMENT:
        if command.replacement is None or not command.scope:
            raise MemoryCorrectionValidationError("scope_refinement requires replacement and scope")
    if command.correction_kind != CorrectionKind.SCOPE_REFINEMENT and command.scope:
        raise MemoryCorrectionValidationError("scope is only supported for scope_refinement")
    if (
        command.correction_kind != CorrectionKind.SITUATION_CHANGED
        and command.effective_at is not None
    ):
        raise MemoryCorrectionValidationError(
            "effective_at is only supported for situation_changed"
        )
    _reject_embedded_replacement_scope(command)
    _reject_unknown_replacement_fields(command)
    unknown_scope_keys = set(command.scope or {}) - SUPPORTED_SCOPE_FIELDS
    if unknown_scope_keys:
        unknown = ", ".join(sorted(str(item) for item in unknown_scope_keys))
        raise MemoryCorrectionValidationError(f"Unsupported scope fields: {unknown}")


async def _ensure_relationship_retry_matches(
    db: aiosqlite.Connection,
    repository: MemoryCorrectionRepository,
    existing: MemoryCorrection,
    command: ApplyRelationshipCorrectionCommand,
) -> None:
    _reject_embedded_replacement_scope(command)
    _reject_unknown_replacement_fields(command)
    if command.correction_kind != CorrectionKind.SCOPE_REFINEMENT and command.scope:
        raise MemoryCorrectionConflictError(
            "request_id was already used for a different correction"
        )
    if (
        command.correction_kind != CorrectionKind.SITUATION_CHANGED
        and command.effective_at is not None
    ):
        raise MemoryCorrectionConflictError(
            "request_id was already used for a different correction"
        )
    stored_fingerprint = await repository.request_fingerprint_on_connection(
        db,
        existing.correction_id,
    )
    if _relationship_request_fingerprint(command) == stored_fingerprint:
        return
    raise MemoryCorrectionConflictError("request_id was already used for a different correction")


def _relationship_request_fingerprint(
    command: ApplyRelationshipCorrectionCommand,
) -> str:
    return correction_request_fingerprint(
        actor_id=command.actor_id,
        target_kind=CorrectionTargetKind.EDGE,
        target_id=command.triple_id,
        correction_kind=command.correction_kind,
        reason=command.reason,
        replacement=command.replacement,
        effective_at=command.effective_at,
        scope=command.scope,
        source_event_id=command.source_event_id,
    )


def _reject_embedded_replacement_scope(
    command: ApplyRelationshipCorrectionCommand,
) -> None:
    embedded_scope_fields = {
        "scope",
        "scope_json",
        "scope_key",
    }.intersection(command.replacement or {})
    if embedded_scope_fields:
        raise MemoryCorrectionValidationError(
            "relationship replacement scope must use the top-level scope field"
        )


def _reject_unknown_replacement_fields(
    command: ApplyRelationshipCorrectionCommand,
) -> None:
    unknown_fields = set(command.replacement or {}) - _ALLOWED_REPLACEMENT_FIELDS
    if not unknown_fields:
        return
    unknown = ", ".join(sorted(str(item) for item in unknown_fields))
    raise MemoryCorrectionValidationError(f"Unsupported replacement fields: {unknown}")


def _ensure_correctable(
    before: Mapping[str, Any],
    command: ApplyRelationshipCorrectionCommand,
) -> None:
    if str(before["status"]) != "active":
        raise MemoryCorrectionConflictError("Relationship is no longer current")
    if command.expected_updated_at is not None and not math.isclose(
        float(before["updated_at"]),
        float(command.expected_updated_at),
        rel_tol=0.0,
        abs_tol=1e-6,
    ):
        raise MemoryCorrectionConflictError("Relationship changed after it was loaded")


async def _load_edge(
    db: aiosqlite.Connection,
    triple_id: str,
) -> aiosqlite.Row | None:
    async with db.execute(
        "SELECT * FROM knowledge_graph WHERE triple_id = ?",
        (triple_id,),
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


async def _ensure_relationship_scope_available(
    db: aiosqlite.Connection,
    *,
    slot_key_value: str,
    scope_key_value: str,
    excluded_triple_ids: set[str],
    effective_at: float,
    message: str,
) -> None:
    """Reject a scope move before it creates two current relationships."""
    async with db.execute(
        """
        SELECT triple_id
        FROM knowledge_graph AS graph
        WHERE slot_key = ? AND scope_key = ?
          AND (
              status = 'active'
              OR EXISTS (
                  SELECT 1
                  FROM memory_corrections AS correction
                  WHERE correction.target_kind = 'edge'
                    AND correction.state = 'active'
                    AND correction.transition_applied_at IS NULL
                    AND correction.transition_cancelled_at IS NULL
                    AND correction.correction_kind = 'situation_changed'
                    AND (
                        correction.target_id = graph.triple_id
                        OR correction.replacement_target_id = graph.triple_id
                    )
              )
          )
          AND (valid_to IS NULL OR valid_to > ?)
          AND (expires_at IS NULL OR expires_at > ?)
        ORDER BY updated_at DESC, triple_id DESC
        """,
        (
            slot_key_value,
            scope_key_value,
            effective_at,
            effective_at,
        ),
    ) as cursor:
        rows = await cursor.fetchall()
    if all(str(row["triple_id"]) in excluded_triple_ids for row in rows):
        return
    raise MemoryCorrectionConflictError(
        message,
        code="relationship_scope_occupied",
    )


async def _ensure_edge_identity(
    db: aiosqlite.Connection,
    before: dict[str, Any],
) -> tuple[str, str]:
    slot_key_value = str(before.get("slot_key") or "") or relationship_slot_key(
        subject_id=str(before["subject_id"]),
        predicate=str(before["predicate"]),
        object_id=str(before["object_id"]),
    )
    scope_key_value = str(before.get("scope_key") or "global")
    fingerprint = str(before.get("claim_fingerprint") or "") or (
        relationship_claim_fingerprint(
            slot_key_value=slot_key_value,
            subject_id=str(before["subject_id"]),
            predicate=str(before["predicate"]),
            object_id=str(before["object_id"]),
            scope_key_value=scope_key_value,
        )
    )
    if before.get("slot_key") != slot_key_value or before.get("claim_fingerprint") != fingerprint:
        await db.execute(
            "UPDATE knowledge_graph SET slot_key = ?, claim_fingerprint = ? WHERE triple_id = ?",
            (slot_key_value, fingerprint, before["triple_id"]),
        )
        before["slot_key"] = slot_key_value
        before["claim_fingerprint"] = fingerprint
    return slot_key_value, fingerprint


async def _ensure_initial_version(
    db: aiosqlite.Connection,
    triple_id: str,
    *,
    now: float,
) -> None:
    async with db.execute(
        """
        SELECT 1 FROM knowledge_graph_versions
        WHERE triple_id = ? AND governance_complete = 1
        LIMIT 1
        """,
        (triple_id,),
    ) as cursor:
        exists = await cursor.fetchone()
    if exists is None:
        await append_knowledge_graph_version(db, triple_id=triple_id, created_at=now - 0.000001)


def _effective_at(command: ApplyRelationshipCorrectionCommand, now: float) -> float:
    if command.correction_kind == CorrectionKind.SITUATION_CHANGED:
        assert command.effective_at is not None
        return float(command.effective_at)
    return now


def _is_future_situation_change(
    correction_kind: CorrectionKind,
    *,
    effective_at: float,
    now: float,
) -> bool:
    return correction_kind == CorrectionKind.SITUATION_CHANGED and float(effective_at) > float(now)


def _ensure_effective_at_not_before_relationship(
    before: Mapping[str, Any],
    command: ApplyRelationshipCorrectionCommand,
    effective_at: float,
) -> None:
    if command.correction_kind != CorrectionKind.SITUATION_CHANGED:
        return
    valid_from = float(
        before.get("valid_from")
        or before.get("first_observed_at")
        or before.get("created_at")
        or 0.0
    )
    if valid_from > 0 and effective_at < valid_from - 0.000001:
        raise MemoryCorrectionValidationError(
            "effective_at cannot be earlier than the relationship start time",
            code="effective_at_before_target",
        )


def _normalize_replacement(
    command: ApplyRelationshipCorrectionCommand,
    before: Mapping[str, Any],
    effective_at: float,
    *,
    graph_conflict_rules: Mapping[str, GraphConflictRule],
) -> dict[str, Any] | None:
    if command.replacement is None:
        return None
    claim = _relationship_claim_fields(command.replacement, before)
    assert claim is not None
    subject_id = claim["subject_id"]
    subject_type = claim["subject_type"]
    predicate = claim["predicate"]
    object_id = claim["object_id"]
    object_type = claim["object_type"]
    replacement_scope = _effective_relationship_scope(command, before)
    replacement_scope_key = scope_key(replacement_scope)
    triple_id = relationship_triple_id(
        subject_id=subject_id,
        predicate=predicate,
        object_id=object_id,
        scope_key_value=replacement_scope_key,
    )
    slot_key_value = relationship_slot_key(
        subject_id=subject_id,
        predicate=predicate,
        object_id=object_id,
        predicate_slot=relationship_predicate_slot(
            graph_conflict_rules,
            predicate=predicate,
            object_id=object_id,
        ),
    )
    return {
        "triple_id": triple_id,
        "subject_id": subject_id,
        "subject_type": subject_type,
        "predicate": predicate,
        "object_id": object_id,
        "object_type": object_type,
        "fact_kind": claim["fact_kind"],
        "slot_key": slot_key_value,
        "claim_fingerprint": relationship_claim_fingerprint(
            slot_key_value=slot_key_value,
            subject_id=subject_id,
            predicate=predicate,
            object_id=object_id,
            scope_key_value=replacement_scope_key,
        ),
        "scope_key": replacement_scope_key,
        "scope_json": canonical_scope_json(replacement_scope),
        "valid_from": effective_at,
    }


def _relationship_claim_fields(
    replacement: Mapping[str, Any] | None,
    before: Mapping[str, Any],
) -> dict[str, str] | None:
    """Normalize only caller-controlled relationship claim fields."""
    if replacement is None:
        return None
    raw = dict(replacement)
    subject_type = normalize_store_entity_type(
        str(raw.get("subject_type") or before["subject_type"])
    ) or str(before["subject_type"])
    object_type = normalize_store_entity_type(
        str(raw.get("object_type") or before["object_type"])
    ) or str(before["object_type"])
    raw_object_id = str(raw.get("object_id") or before["object_id"])
    return {
        "subject_id": str(raw.get("subject_id") or before["subject_id"]),
        "subject_type": subject_type,
        "predicate": str(raw.get("predicate") or before["predicate"]).strip().upper(),
        "object_id": (normalize_store_entity_ref(raw_object_id, object_type) or raw_object_id),
        "object_type": object_type,
        "fact_kind": str(raw.get("fact_kind") or before["fact_kind"]),
    }


def _effective_relationship_scope(
    command: ApplyRelationshipCorrectionCommand,
    before: Mapping[str, Any],
) -> dict[str, list[dict[str, str]]]:
    if command.correction_kind == CorrectionKind.SCOPE_REFINEMENT:
        return dict(command.scope or {})
    return stored_context_scope(before)


def _ensure_relationship_correction_changes_claim(
    before: Mapping[str, Any],
    command: ApplyRelationshipCorrectionCommand,
    replacement: Mapping[str, Any] | None,
    replacement_scope: Mapping[str, Any],
) -> None:
    if command.correction_kind == CorrectionKind.SCOPE_REFINEMENT:
        assert replacement is not None
        before_claim = (
            str(before.get("subject_id") or "").strip(),
            str(before.get("subject_type") or "").strip(),
            str(before.get("predicate") or "").strip().upper(),
            str(before.get("object_id") or "").strip(),
            str(before.get("object_type") or "").strip(),
            str(before.get("fact_kind") or "").strip(),
        )
        replacement_claim = (
            str(replacement.get("subject_id") or "").strip(),
            str(replacement.get("subject_type") or "").strip(),
            str(replacement.get("predicate") or "").strip().upper(),
            str(replacement.get("object_id") or "").strip(),
            str(replacement.get("object_type") or "").strip(),
            str(replacement.get("fact_kind") or "").strip(),
        )
        if replacement_claim != before_claim:
            raise MemoryCorrectionValidationError(
                "scope_refinement cannot change the relationship",
                code="scope_refinement_changes_claim",
            )
        if canonical_scope_json(replacement_scope) == canonical_scope_json(
            stored_context_scope(before)
        ):
            raise MemoryCorrectionValidationError(
                "scope_refinement must change the scope",
                code="scope_unchanged",
            )
        return
    if replacement is None:
        return
    before_identity = (
        str(before.get("subject_id") or "").strip(),
        str(before.get("predicate") or "").strip().upper(),
        str(before.get("object_id") or "").strip(),
    )
    replacement_identity = (
        str(replacement.get("subject_id") or "").strip(),
        str(replacement.get("predicate") or "").strip().upper(),
        str(replacement.get("object_id") or "").strip(),
    )
    if replacement_identity == before_identity:
        raise MemoryCorrectionValidationError(
            "replacement must change the relationship",
            code="replacement_unchanged",
        )


async def _ensure_replacement_reactivatable(
    db: aiosqlite.Connection,
    triple_id: str,
    *,
    effective_at: float,
) -> bool:
    existing = await _load_edge(db, triple_id)
    if existing is None:
        return False
    status = str(existing["status"] or "")
    is_time_range_forget = (
        status == "archived"
        and str(existing["status_reason"] or "") == "user_forget"
        and str(existing["authority_ref"] or "") == "forget:time_range"
    )
    if is_time_range_forget:
        return True
    if status != "deprecated":
        raise MemoryCorrectionConflictError(
            "Replacement relationship already exists and must be corrected directly"
        )
    if str(existing["status_reason"] or "") == "user_forget":
        raise MemoryCorrectionConflictError("Forgotten relationships cannot be reactivated")
    valid_to = existing["valid_to"]
    if valid_to is None or float(valid_to) > float(effective_at) + 0.000001:
        raise MemoryCorrectionConflictError(
            "Replacement relationship overlaps an existing validity period"
        )
    return True


async def _close_original_edge(
    db: aiosqlite.Connection,
    *,
    command: ApplyRelationshipCorrectionCommand,
    replacement_id: str | None,
    effective_at: float,
    now: float,
) -> None:
    if command.correction_kind == CorrectionKind.RECORD_ERROR:
        await db.execute(
            """
            UPDATE knowledge_graph
            SET status = 'user_rejected', status_reason = 'user_correction',
                deprecated_by = ?, deprecated_at = ?, updated_at = ?
            WHERE triple_id = ?
            """,
            (replacement_id, now, now, command.triple_id),
        )
        return
    await db.execute(
        """
        UPDATE knowledge_graph
        SET status = 'deprecated', status_reason = 'user_correction',
            deprecated_by = ?, deprecated_at = ?, valid_to = ?, updated_at = ?
        WHERE triple_id = ?
        """,
        (replacement_id, now, effective_at, now, command.triple_id),
    )


async def _write_authoritative_replacement(
    db: aiosqlite.Connection,
    *,
    replacement: Mapping[str, Any],
    correction_id: str,
    source_event_id: str | None,
    now: float,
) -> None:
    evidence = [source_event_id] if source_event_id else []
    evidence_json = json.dumps(evidence, ensure_ascii=False)
    valid_from = float(replacement["valid_from"])
    authority_ref = correction_authority_ref(correction_id)
    existing = await _load_edge(db, str(replacement["triple_id"]))
    if existing is not None:
        await db.execute(
            """
            UPDATE knowledge_graph
            SET subject_id = ?, subject_type = ?, predicate = ?, object_id = ?,
                object_type = ?, fact_kind = ?, confidence = 0.95,
                evidence_event_ids = ?, evidence_text = '', natural_summary = '',
                observation_count = 1, first_observed_at = ?, last_observed_at = ?,
                last_confirmed_at = ?, source_type = 'user_correction',
                extraction_method = 'explicit', embedding_status = 'pending',
                expires_at = NULL, valid_from = ?, valid_to = NULL, status = 'active',
                status_reason = NULL, deprecated_by = NULL, deprecated_at = NULL,
                evidence_class = 'user_self_report', authority_ref = ?, slot_key = ?,
                claim_fingerprint = ?, scope_key = ?, scope_json = ?, updated_at = ?
            WHERE triple_id = ?
            """,
            (
                str(replacement["subject_id"]),
                str(replacement["subject_type"]),
                str(replacement["predicate"]),
                str(replacement["object_id"]),
                str(replacement["object_type"]),
                str(replacement["fact_kind"]),
                evidence_json,
                valid_from,
                valid_from,
                now,
                valid_from,
                authority_ref,
                str(replacement["slot_key"]),
                str(replacement["claim_fingerprint"]),
                str(replacement["scope_key"]),
                str(replacement["scope_json"]),
                now,
                str(replacement["triple_id"]),
            ),
        )
        return
    await db.execute(
        """
        INSERT INTO knowledge_graph(
            triple_id, subject_id, subject_type, predicate, object_id, object_type,
            fact_kind, confidence, evidence_event_ids, evidence_text, natural_summary,
            observation_count, first_observed_at, last_observed_at, last_confirmed_at,
            source_type, extraction_method, embedding_status, expires_at, valid_from,
            valid_to, status, status_reason, deprecated_by, deprecated_at, created_at,
            updated_at, evidence_class, slot_key, claim_fingerprint, authority_ref,
            scope_key, scope_json
        ) VALUES (?, ?, ?, ?, ?, ?, ?, 0.95, ?, '', '', 1, ?, ?, ?,
                  'user_correction', 'explicit', 'pending', NULL, ?, NULL, 'active',
                  NULL, NULL, NULL, ?, ?, 'user_self_report', ?, ?, ?, ?, ?)
        """,
        (
            str(replacement["triple_id"]),
            str(replacement["subject_id"]),
            str(replacement["subject_type"]),
            str(replacement["predicate"]),
            str(replacement["object_id"]),
            str(replacement["object_type"]),
            str(replacement["fact_kind"]),
            evidence_json,
            valid_from,
            valid_from,
            now,
            valid_from,
            now,
            now,
            str(replacement["slot_key"]),
            str(replacement["claim_fingerprint"]),
            authority_ref,
            str(replacement["scope_key"]),
            str(replacement["scope_json"]),
        ),
    )


def _build_rules(
    *,
    correction_id: str,
    command: ApplyRelationshipCorrectionCommand,
    old_slot_key: str,
    old_claim_fingerprint: str,
    old_scope_key: str,
    replacement: Mapping[str, Any] | None,
    effective_at: float,
    now: float,
) -> list[CorrectionRule]:
    if command.correction_kind == CorrectionKind.RECORD_ERROR:
        old_kind = CorrectionRuleKind.BLOCK_CLAIM
    elif command.correction_kind == CorrectionKind.SITUATION_CHANGED:
        old_kind = CorrectionRuleKind.CLOSE_BEFORE
    else:
        old_kind = CorrectionRuleKind.SCOPE_ONLY
    rules = [
        CorrectionRule(
            rule_id=f"correction_rule_{uuid.uuid4().hex}",
            correction_id=correction_id,
            target_kind=CorrectionTargetKind.EDGE,
            rule_kind=old_kind,
            slot_key=old_slot_key,
            claim_fingerprint=old_claim_fingerprint,
            scope_key=(
                str(replacement["scope_key"])
                if old_kind == CorrectionRuleKind.SCOPE_ONLY and replacement is not None
                else old_scope_key
            ),
            effective_to=(effective_at if old_kind == CorrectionRuleKind.CLOSE_BEFORE else None),
            created_at=now,
        )
    ]
    if replacement is not None:
        rules.append(
            CorrectionRule(
                rule_id=f"correction_rule_{uuid.uuid4().hex}",
                correction_id=correction_id,
                target_kind=CorrectionTargetKind.EDGE,
                rule_kind=CorrectionRuleKind.AUTHORITATIVE_SLOT,
                slot_key=str(replacement["slot_key"]),
                claim_fingerprint=str(replacement["claim_fingerprint"]),
                scope_key=str(replacement["scope_key"]),
                effective_from=effective_at,
                created_at=now,
            )
        )
    return rules


async def _restore_original_edge(
    db: aiosqlite.Connection,
    *,
    triple_id: str,
    before: Mapping[str, Any],
    now: float,
) -> None:
    missing = [column for column in _RESTORABLE_RELATIONSHIP_COLUMNS if column not in before]
    if missing:
        raise MemoryCorrectionValidationError(
            f"Correction snapshot is missing relationship fields: {', '.join(missing)}"
        )
    restored = dict(before)
    evidence_snapshot = await _latest_relationship_evidence_for_segment(
        db,
        triple_id=triple_id,
        before=before,
    )
    if evidence_snapshot is not None:
        for column in (
            "confidence",
            "evidence_event_ids",
            "evidence_text",
            "natural_summary",
            "observation_count",
            "first_observed_at",
            "last_observed_at",
            "last_confirmed_at",
        ):
            restored[column] = evidence_snapshot[column]
    assignments = ", ".join(f"{column} = ?" for column in _RESTORABLE_RELATIONSHIP_COLUMNS)
    values = [restored[column] for column in _RESTORABLE_RELATIONSHIP_COLUMNS]
    cursor = await db.execute(
        f"UPDATE knowledge_graph SET {assignments}, updated_at = ? WHERE triple_id = ?",
        (*values, now, triple_id),
    )
    if cursor.rowcount > 0:
        return
    columns = ("triple_id", *_RESTORABLE_RELATIONSHIP_COLUMNS, "updated_at")
    placeholders = ", ".join("?" for _ in columns)
    await db.execute(
        f"INSERT INTO knowledge_graph({', '.join(columns)}) VALUES ({placeholders})",
        (triple_id, *values, now),
    )


async def restore_relationship_snapshot_on_connection(
    db: aiosqlite.Connection,
    *,
    triple_id: str,
    before: Mapping[str, Any],
    now: float,
) -> None:
    """Restore a relationship preimage inside an existing governance transaction."""
    await _restore_original_edge(
        db,
        triple_id=triple_id,
        before=before,
        now=now,
    )


async def _latest_relationship_evidence_for_segment(
    db: aiosqlite.Connection,
    *,
    triple_id: str,
    before: Mapping[str, Any],
) -> Mapping[str, Any] | None:
    current = await _load_edge(db, triple_id)
    if current is not None:
        current_snapshot = dict(current)
        if _same_relationship_evidence_segment(before, current_snapshot):
            return current_snapshot
        if (
            _same_relationship_claim_identity(before, current_snapshot)
            and not has_correction_owner(current_snapshot.get("authority_ref"))
            and not str(current_snapshot.get("authority_ref") or "").startswith("forget:")
            and str(current_snapshot.get("status_reason") or "") != "user_forget"
        ):
            return current_snapshot
    async with db.execute(
        """
        SELECT * FROM knowledge_graph_versions
        WHERE triple_id = ? AND governance_complete = 1
        ORDER BY created_at DESC, version_id DESC
        """,
        (triple_id,),
    ) as cursor:
        versions = await cursor.fetchall()
    for version in versions:
        version_snapshot = dict(version)
        if _same_relationship_evidence_segment(before, version_snapshot):
            return version_snapshot
    return None


def _same_relationship_evidence_segment(
    before: Mapping[str, Any],
    current: Mapping[str, Any],
) -> bool:
    """Return whether current evidence still belongs to the corrected segment."""
    identity_columns = (
        "subject_id",
        "predicate",
        "object_id",
        "scope_key",
        "claim_fingerprint",
    )
    if any(
        str(before.get(column) or "") != str(current.get(column) or "")
        for column in identity_columns
    ):
        return False
    before_start = before.get("valid_from")
    current_start = current.get("valid_from")
    if before_start is None or current_start is None:
        return before_start is None and current_start is None
    return math.isclose(
        float(before_start),
        float(current_start),
        rel_tol=0.0,
        abs_tol=1e-6,
    )


def _same_relationship_claim_identity(
    before: Mapping[str, Any],
    current: Mapping[str, Any],
) -> bool:
    return all(
        str(before.get(column) or "") == str(current.get(column) or "")
        for column in (
            "subject_id",
            "predicate",
            "object_id",
            "scope_key",
            "claim_fingerprint",
        )
    )


async def _has_newer_correction(
    db: aiosqlite.Connection,
    correction: MemoryCorrection,
) -> bool:
    async with db.execute(
        """
        SELECT * FROM memory_corrections
        WHERE target_kind = 'edge' AND state = 'active' AND correction_id != ?
          AND transition_cancelled_at IS NULL
          AND (created_at > ? OR (created_at = ? AND correction_id > ?))
          AND (slot_key = ? OR target_id = ?)
        """,
        (
            correction.correction_id,
            correction.created_at,
            correction.created_at,
            correction.correction_id,
            correction.slot_key,
            correction.replacement_target_id or "",
        ),
    ) as cursor:
        rows = await cursor.fetchall()
    return any(
        _newer_correction_blocks_revert(
            correction,
            MemoryCorrection.from_row(dict(row)),
        )
        for row in rows
    )


def _newer_correction_blocks_revert(
    correction: MemoryCorrection,
    candidate: MemoryCorrection,
) -> bool:
    if candidate.target_id in {
        correction.target_id,
        correction.replacement_target_id,
    }:
        return True
    return canonical_scope_json(candidate.scope) == canonical_scope_json(correction.scope)


async def _relationship_correction_result(
    db_path: str,
    correction: MemoryCorrection,
    *,
    created: bool,
    subject_revision: int | None,
) -> RelationshipCorrectionResult:
    current_claim = await resolve_current_claim(
        db_path,
        correction={"correction_id": correction.correction_id},
    )
    return RelationshipCorrectionResult(
        correction=correction,
        created=created,
        current_triple_id=(
            str(current_claim["triple_id"]) if current_claim is not None else None
        ),
        subject_revision=subject_revision,
        current_claim=current_claim,
    )


def _affected_subject_keys(
    before: Mapping[str, Any],
    replacement: Mapping[str, Any] | None,
) -> list[str]:
    """Return entity keys whose derived relationship views changed."""
    keys: list[str] = []
    for payload in (before, replacement or {}):
        subject_id = str(payload.get("subject_id") or "").strip()
        object_id = str(payload.get("object_id") or "").strip()
        if subject_id:
            keys.append(subject_id)
        if ":" in object_id:
            keys.append(object_id)
    return list(dict.fromkeys(keys))


__all__ = ["RelationshipCorrectionService"]
