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
from .cache_signals import mark_subject_changed
from .fingerprints import (
    SUPPORTED_SCOPE_FIELDS,
    canonical_scope_json,
    relationship_claim_fingerprint,
    relationship_slot_key,
    scope_key,
)
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
from .repository import MemoryCorrectionRepository
from .service import MemoryCorrectionConflictError, MemoryCorrectionValidationError

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


class RelationshipCorrectionService:
    """Apply and revert durable relationship corrections."""

    def __init__(self, db_path: str):
        self.db_path = db_path
        self.repository = MemoryCorrectionRepository(db_path)

    async def apply(
        self,
        command: ApplyRelationshipCorrectionCommand,
    ) -> RelationshipCorrectionResult | None:
        _validate_command(command)
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
                    return _existing_result(existing_correction)
                row = await _load_edge(db, command.triple_id)
                if row is None:
                    await db.commit()
                    return None
                before = dict(row)
                _ensure_correctable(before, command)
                old_slot_key, old_claim_fingerprint = await _ensure_edge_identity(db, before)
                await _ensure_initial_version(db, command.triple_id, now=now)

                effective_at = _effective_at(command, now)
                correction_id = f"correction_{uuid.uuid4().hex}"
                replacement = _normalize_replacement(command, before, effective_at)
                replacement_id = str(replacement["triple_id"]) if replacement is not None else None
                if replacement_id and replacement_id != command.triple_id:
                    await _ensure_replacement_absent(db, replacement_id)

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
                    replacement=replacement,
                    effective_at=(
                        effective_at
                        if command.correction_kind == CorrectionKind.SITUATION_CHANGED
                        else None
                    ),
                    scope=(dict(command.scope) if command.scope else None),
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
                if replacement is not None:
                    await _write_authoritative_replacement(
                        db,
                        replacement=replacement,
                        correction_id=correction_id,
                        source_event_id=command.source_event_id,
                        now=now,
                    )
                    await append_knowledge_graph_version(
                        db,
                        triple_id=replacement_id,
                        correction_id=correction_id,
                        created_at=now + 0.000001,
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
                l3_subjects = await self.repository.invalidate_l3_insights_on_connection(
                    db,
                    source_kind="edge",
                    source_ids=[command.triple_id],
                    subject_keys=_affected_subject_keys(before, replacement),
                    updated_at=now,
                )
                affected_subjects = list(
                    dict.fromkeys(
                        [*_affected_subject_keys(before, replacement), *l3_subjects]
                    )
                )
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
        return RelationshipCorrectionResult(
            correction=stored,
            created=True,
            current_triple_id=replacement_id,
            subject_revision=subject_revision,
        )

    async def revert(
        self,
        *,
        correction_id: str,
        request_id: str,
        actor_id: str,
    ) -> RelationshipCorrectionResult | None:
        now = time.time()
        async with sqlite_connection_async(self.db_path) as db:
            db.row_factory = aiosqlite.Row
            await db.execute("BEGIN IMMEDIATE")
            try:
                correction_row = await _load_correction(db, correction_id)
                if correction_row is None:
                    await db.commit()
                    return None
                correction = MemoryCorrection.from_row(dict(correction_row))
                if correction.target_kind != CorrectionTargetKind.EDGE:
                    raise MemoryCorrectionValidationError(
                        "Correction does not target a relationship"
                    )
                if correction.state == CorrectionState.REVERTED:
                    await db.commit()
                    return RelationshipCorrectionResult(
                        correction=correction,
                        created=False,
                        current_triple_id=correction.target_id,
                        subject_revision=None,
                    )
                if await _has_newer_correction(db, correction):
                    raise MemoryCorrectionConflictError("A newer correction must be reverted first")

                replacement_id = correction.replacement_target_id
                if replacement_id and replacement_id != correction.target_id:
                    await db.execute(
                        """
                        UPDATE knowledge_graph
                        SET status = 'archived', valid_to = COALESCE(valid_to, ?),
                            updated_at = ?
                        WHERE triple_id = ?
                        """,
                        (now, now, replacement_id),
                    )
                    await append_knowledge_graph_version(
                        db,
                        triple_id=replacement_id,
                        correction_id=correction_id,
                        created_at=now,
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
                l3_subjects = await self.repository.invalidate_l3_insights_on_connection(
                    db,
                    source_kind="edge",
                    source_ids=[
                        correction.target_id,
                        correction.replacement_target_id or "",
                    ],
                    subject_keys=_affected_subject_keys(
                        correction.before,
                        correction.replacement,
                    ),
                    updated_at=now,
                )
                affected_subjects = _affected_subject_keys(
                    correction.before,
                    correction.replacement,
                )
                affected_subjects = list(
                    dict.fromkeys([*affected_subjects, *l3_subjects])
                )
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
        return RelationshipCorrectionResult(
            correction=stored,
            created=True,
            current_triple_id=correction.target_id,
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
                SELECT * FROM memory_corrections
                WHERE target_kind = 'edge'
                  AND (
                    (? != '' AND slot_key = ?)
                    OR target_id = ?
                    OR replacement_target_id = ?
                  )
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
    unknown_scope_keys = set(command.scope or {}) - SUPPORTED_SCOPE_FIELDS
    if unknown_scope_keys:
        unknown = ", ".join(sorted(str(item) for item in unknown_scope_keys))
        raise MemoryCorrectionValidationError(f"Unsupported scope fields: {unknown}")


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


def _normalize_replacement(
    command: ApplyRelationshipCorrectionCommand,
    before: Mapping[str, Any],
    effective_at: float,
) -> dict[str, Any] | None:
    if command.replacement is None:
        return None
    raw = dict(command.replacement)
    subject_id = str(raw.get("subject_id") or before["subject_id"])
    subject_type = str(raw.get("subject_type") or before["subject_type"])
    predicate = str(raw.get("predicate") or before["predicate"]).strip().upper()
    object_id = str(raw.get("object_id") or before["object_id"])
    object_type = str(raw.get("object_type") or before["object_type"])
    triple_key = f"{subject_id}:{predicate}:{object_id}"
    triple_id = f"triple_{uuid.uuid5(uuid.NAMESPACE_DNS, triple_key)}"
    replacement_scope = dict(command.scope or raw.get("scope") or {})
    replacement_scope_key = scope_key(replacement_scope)
    slot_key_value = str(raw.get("slot_key") or "") or relationship_slot_key(
        subject_id=subject_id,
        predicate=predicate,
        object_id=object_id,
    )
    return {
        "triple_id": triple_id,
        "subject_id": subject_id,
        "subject_type": subject_type,
        "predicate": predicate,
        "object_id": object_id,
        "object_type": object_type,
        "fact_kind": str(raw.get("fact_kind") or before["fact_kind"]),
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


async def _ensure_replacement_absent(
    db: aiosqlite.Connection,
    triple_id: str,
) -> None:
    if await _load_edge(db, triple_id) is not None:
        raise MemoryCorrectionConflictError(
            "Replacement relationship already exists and must be corrected directly"
        )


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
    authority_ref = f"correction:{correction_id}"
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
    assignments = ", ".join(f"{column} = ?" for column in _RESTORABLE_RELATIONSHIP_COLUMNS)
    values = [before[column] for column in _RESTORABLE_RELATIONSHIP_COLUMNS]
    await db.execute(
        f"UPDATE knowledge_graph SET {assignments}, updated_at = ? WHERE triple_id = ?",
        (*values, now, triple_id),
    )


async def _has_newer_correction(
    db: aiosqlite.Connection,
    correction: MemoryCorrection,
) -> bool:
    async with db.execute(
        """
        SELECT 1 FROM memory_corrections
        WHERE target_kind = 'edge' AND state = 'active' AND correction_id != ?
          AND created_at >= ?
          AND (slot_key = ? OR target_id = ?)
        LIMIT 1
        """,
        (
            correction.correction_id,
            correction.created_at,
            correction.slot_key,
            correction.replacement_target_id or "",
        ),
    ) as cursor:
        return await cursor.fetchone() is not None


def _existing_result(correction: MemoryCorrection) -> RelationshipCorrectionResult:
    current_id = correction.replacement_target_id
    if correction.state == CorrectionState.REVERTED:
        current_id = correction.target_id
    return RelationshipCorrectionResult(
        correction=correction,
        created=False,
        current_triple_id=current_id,
        subject_revision=None,
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
