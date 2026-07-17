"""Privacy-safe presentation helpers for public memory correction history."""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from dataclasses import asdict, is_dataclass
from typing import Any

import aiosqlite

from .....core.sqlite import sqlite_connection_async
from .....memory.l2.corrections.fingerprints import (
    assertion_claim_fingerprint,
    canonical_scope_json,
    relationship_claim_fingerprint,
    scope_key,
    stored_context_scope,
)
from .....memory.l2.corrections.evidence_ledger import claim_evidence_records_for_claims
from .....memory.l2.corrections.models import (
    CorrectionKind,
    CorrectionState,
    CorrectionTargetKind,
    MemoryCorrection,
)
from .....memory.l2.corrections.repository import MemoryCorrectionRepository

_ASSERTION_VALUE_FIELDS = frozenset({"trait_value", "value"})
_RELATIONSHIP_VALUE_FIELDS = frozenset(
    {
        "subject_id",
        "subject_type",
        "predicate",
        "object_id",
        "object_type",
        "fact_kind",
    }
)


async def prepare_correction_history(
    db_path: str,
    *,
    target_kind: CorrectionTargetKind,
    versions: Sequence[Mapping[str, Any]],
    corrections: Sequence[object],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Return public versions and correction records without forgotten content."""
    normalized = _normalize_corrections(corrections)
    barrier_ids = await MemoryCorrectionRepository(db_path).correction_ids_with_forget_barriers(
        correction.correction_id for correction in normalized
    )
    record_ids = _record_ids(normalized)
    record_ids.update(_version_record_ids(target_kind, versions))
    forgotten_ids = await _fully_forgotten_record_ids(
        db_path,
        target_kind=target_kind,
        record_ids=record_ids,
        corrections=normalized,
        versions=versions,
        barrier_ids=barrier_ids,
    )
    decorated = await _decorate_normalized_corrections(
        db_path,
        normalized,
        forgotten_ids_by_kind={target_kind: forgotten_ids},
        barrier_ids=barrier_ids,
    )
    public_versions = [
        public_version
        for version in versions
        if (
            public_version := _public_version(
                target_kind,
                version,
                forgotten_ids=forgotten_ids,
            )
        )
        is not None
    ]
    return public_versions, decorated


async def decorate_correction_records(
    db_path: str,
    corrections: Sequence[object],
) -> list[dict[str, Any]]:
    """Decorate command records with the same server-side history policy."""
    normalized = _normalize_corrections(corrections)
    barrier_ids = await MemoryCorrectionRepository(db_path).correction_ids_with_forget_barriers(
        correction.correction_id for correction in normalized
    )
    ids_by_kind: dict[CorrectionTargetKind, set[str]] = {}
    for correction in normalized:
        ids_by_kind.setdefault(correction.target_kind, set()).update(
            item for item in (correction.target_id, correction.replacement_target_id) if item
        )
    forgotten_ids_by_kind = {
        target_kind: await _fully_forgotten_record_ids(
            db_path,
            target_kind=target_kind,
            record_ids=record_ids,
            corrections=[
                correction for correction in normalized if correction.target_kind == target_kind
            ],
            versions=(),
            barrier_ids=barrier_ids,
        )
        for target_kind, record_ids in ids_by_kind.items()
    }
    return await _decorate_normalized_corrections(
        db_path,
        normalized,
        forgotten_ids_by_kind=forgotten_ids_by_kind,
        barrier_ids=barrier_ids,
    )


async def correction_history_slot_key(
    db_path: str,
    *,
    target_kind: CorrectionTargetKind,
    target_id: str,
) -> str | None:
    """Resolve a correction lineage after its base memory row was removed."""
    async with sqlite_connection_async(db_path) as db:
        async with db.execute(
            """
            SELECT slot_key
            FROM memory_corrections
            WHERE target_kind = ?
              AND (target_id = ? OR replacement_target_id = ?)
            ORDER BY created_at DESC, correction_id DESC
            LIMIT 1
            """,
            (target_kind.value, target_id, target_id),
        ) as cursor:
            row = await cursor.fetchone()
    if row is None:
        return None
    value = str(row[0] or "").strip()
    return value or None


def _normalize_corrections(corrections: Sequence[object]) -> list[MemoryCorrection]:
    normalized: list[MemoryCorrection] = []
    for correction in corrections:
        if isinstance(correction, MemoryCorrection):
            normalized.append(correction)
        elif is_dataclass(correction) and not isinstance(correction, type):
            normalized.append(_memory_correction_from_public_mapping(asdict(correction)))
        elif isinstance(correction, Mapping):
            normalized.append(_memory_correction_from_public_mapping(correction))
        else:
            raise TypeError("Memory correction history contains an invalid record")
    return normalized


def _memory_correction_from_public_mapping(value: Mapping[str, Any]) -> MemoryCorrection:
    if "before_json" in value:
        return MemoryCorrection.from_row(value)
    return MemoryCorrection(
        correction_id=str(value["correction_id"]),
        request_id=str(value["request_id"]),
        actor_id=str(value["actor_id"]),
        target_kind=CorrectionTargetKind(_enum_value(value["target_kind"])),
        target_id=str(value["target_id"]),
        slot_key=str(value["slot_key"]),
        claim_fingerprint=str(value["claim_fingerprint"]),
        correction_kind=CorrectionKind(_enum_value(value["correction_kind"])),
        before=dict(value.get("before") or {}),
        created_at=float(value["created_at"]),
        state=CorrectionState(_enum_value(value["state"])),
        reason=_optional_text(value.get("reason")),
        replacement=(dict(value["replacement"]) if value.get("replacement") else None),
        effective_at=_optional_float(value.get("effective_at")),
        scope=(dict(value["scope"]) if value.get("scope") else None),
        source_event_id=_optional_text(value.get("source_event_id")),
        audit_event_id=_optional_text(value.get("audit_event_id")),
        replacement_target_id=_optional_text(value.get("replacement_target_id")),
        reverted_at=_optional_float(value.get("reverted_at")),
        reverted_by=_optional_text(value.get("reverted_by")),
        transition_applied_at=_optional_float(value.get("transition_applied_at")),
        transition_cancelled_at=_optional_float(value.get("transition_cancelled_at")),
        transition_cancel_reason=_optional_text(value.get("transition_cancel_reason")),
    )


async def _decorate_normalized_corrections(
    db_path: str,
    corrections: Sequence[MemoryCorrection],
    *,
    forgotten_ids_by_kind: Mapping[CorrectionTargetKind, set[str]],
    barrier_ids: set[str],
) -> list[dict[str, Any]]:
    newer_candidates = await _load_relevant_active_corrections(db_path, corrections)
    forgotten_source_ids = await _forgotten_correction_source_ids(db_path, corrections)
    records: list[dict[str, Any]] = []
    for correction in corrections:
        forgotten_ids = forgotten_ids_by_kind.get(correction.target_kind, set())
        target_forgotten = correction.target_id in forgotten_ids
        replacement_forgotten = bool(
            correction.replacement_target_id and correction.replacement_target_id in forgotten_ids
        )
        content_redacted = target_forgotten or replacement_forgotten
        forget_affected = (
            correction.correction_id in barrier_ids
            or correction.correction_id in forgotten_source_ids
            or content_redacted
        )
        blocked_by_newer = any(
            _newer_correction_blocks_revert(correction, candidate) for candidate in newer_candidates
        )
        before = (
            None
            if target_forgotten
            else _public_claim_value(
                correction.target_kind,
                correction.before,
                include_lifecycle=True,
            )
        )
        replacement = (
            None
            if replacement_forgotten
            else _public_claim_value(correction.target_kind, correction.replacement)
        )
        record = {
            "correction_id": correction.correction_id,
            "correction_kind": correction.correction_kind.value,
            "before": before,
            "created_at": correction.created_at,
            "state": correction.state.value,
            # A reason may quote a forgotten source. Once a forget barrier exists,
            # fail closed instead of trying to infer whether free text is safe.
            "reason": None if forget_affected else correction.reason,
            "replacement": replacement,
            "effective_at": correction.effective_at,
            "scope": correction.scope,
            "transition_applied_at": correction.transition_applied_at,
            "transition_cancelled_at": correction.transition_cancelled_at,
            "target_forgotten": target_forgotten,
            "forget_affected": forget_affected,
            "content_redacted": content_redacted,
            "can_revert": (
                correction.state == CorrectionState.ACTIVE
                and correction.transition_cancelled_at is None
                and not forget_affected
                and not blocked_by_newer
            ),
        }
        records.append(record)
    return records


async def _forgotten_correction_source_ids(
    db_path: str,
    corrections: Sequence[MemoryCorrection],
) -> set[str]:
    source_event_ids = sorted(
        {
            correction.source_event_id
            for correction in corrections
            if correction.source_event_id is not None
        }
    )
    if not source_event_ids:
        return set()
    event_ids_json = json.dumps(source_event_ids, ensure_ascii=False, separators=(",", ":"))
    async with sqlite_connection_async(db_path) as db:
        async with db.execute(
            """
            SELECT event_id
            FROM memory_source_event_tombstones
            WHERE event_id IN (SELECT CAST(value AS TEXT) FROM json_each(?))
            """,
            (event_ids_json,),
        ) as cursor:
            forgotten_events = {str(row[0]) for row in await cursor.fetchall()}
    return {
        correction.correction_id
        for correction in corrections
        if correction.source_event_id in forgotten_events
    }


async def _fully_forgotten_record_ids(
    db_path: str,
    *,
    target_kind: CorrectionTargetKind,
    record_ids: set[str],
    corrections: Sequence[MemoryCorrection],
    versions: Sequence[Mapping[str, Any]],
    barrier_ids: set[str],
) -> set[str]:
    if not record_ids:
        return set()
    fingerprints_by_record = _record_fingerprints(
        target_kind,
        corrections=corrections,
        versions=versions,
    )
    barrier_record_ids = {
        record_id
        for correction in corrections
        if correction.correction_id in barrier_ids
        for record_id in (correction.target_id, correction.replacement_target_id)
        if record_id
    }
    record_ids_json = json.dumps(sorted(record_ids), ensure_ascii=False, separators=(",", ":"))
    async with sqlite_connection_async(db_path) as db:
        db.row_factory = aiosqlite.Row
        if target_kind == CorrectionTargetKind.ASSERTION:
            query = """
                SELECT assertion_id AS record_id, status, authority_ref,
                       NULL AS status_reason, claim_fingerprint
                FROM tom_trait_assertions
                WHERE assertion_id IN (SELECT CAST(value AS TEXT) FROM json_each(?))
            """
        else:
            query = """
                SELECT triple_id AS record_id, status, authority_ref, status_reason,
                       claim_fingerprint
                FROM knowledge_graph
                WHERE triple_id IN (SELECT CAST(value AS TEXT) FROM json_each(?))
            """
        async with db.execute(query, (record_ids_json,)) as cursor:
            rows = await cursor.fetchall()
        rows_by_id = {str(row["record_id"]): dict(row) for row in rows}
        for record_id, row in rows_by_id.items():
            fingerprint = str(row.get("claim_fingerprint") or "").strip()
            if fingerprint:
                fingerprints_by_record.setdefault(record_id, set()).add(fingerprint)
        fully_forgotten_fingerprints = await _fully_forgotten_claim_fingerprints(
            db,
            target_kind=target_kind,
            claim_fingerprints={
                fingerprint
                for fingerprints in fingerprints_by_record.values()
                for fingerprint in fingerprints
            },
        )

    forgotten = {
        record_id
        for record_id, row in rows_by_id.items()
        if _row_is_fully_forgotten(target_kind, row)
        or bool(fingerprints_by_record.get(record_id, set()) & fully_forgotten_fingerprints)
    }
    # A maintenance pass may physically remove a forgotten row. The immutable
    # correction barrier is then the final privacy signal, so absence fails closed.
    forgotten.update((record_ids - rows_by_id.keys()) & barrier_record_ids)
    return forgotten


async def _fully_forgotten_claim_fingerprints(
    db: aiosqlite.Connection,
    *,
    target_kind: CorrectionTargetKind,
    claim_fingerprints: set[str],
) -> set[str]:
    if not claim_fingerprints:
        return set()
    fingerprints_json = json.dumps(
        sorted(claim_fingerprints),
        ensure_ascii=False,
        separators=(",", ":"),
    )
    async with db.execute(
        """
        SELECT rules.claim_fingerprint, rules.forget_kind,
               rules.evidence_fail_closed, evidence.event_id
        FROM memory_forget_claim_rules AS rules
        LEFT JOIN memory_forget_evidence_events AS evidence
          ON evidence.rule_id = rules.rule_id
        WHERE rules.target_kind = ?
          AND rules.claim_fingerprint IN (
              SELECT CAST(value AS TEXT) FROM json_each(?)
          )
        ORDER BY rules.claim_fingerprint, rules.rule_id, evidence.event_id
        """,
        (target_kind.value, fingerprints_json),
    ) as cursor:
        rows = await cursor.fetchall()
    rules_by_fingerprint: dict[str, list[tuple[str, bool, str | None]]] = {}
    for fingerprint, forget_kind, fail_closed, event_id in rows:
        rules_by_fingerprint.setdefault(str(fingerprint), []).append(
            (
                str(forget_kind),
                bool(fail_closed),
                str(event_id) if event_id is not None else None,
            )
        )
    evidence_by_fingerprint = await claim_evidence_records_for_claims(
        db,
        target_kind=target_kind,
        claim_fingerprints=claim_fingerprints,
    )
    forgotten: set[str] = set()
    for fingerprint, rules in rules_by_fingerprint.items():
        if any(forget_kind == "entity" for forget_kind, _, _ in rules):
            forgotten.add(fingerprint)
            continue
        evidence_ids = {record.event_id for record in evidence_by_fingerprint.get(fingerprint, [])}
        governed_event_ids = {event_id for _, _, event_id in rules if event_id}
        if evidence_ids and evidence_ids <= governed_event_ids:
            forgotten.add(fingerprint)
        elif not evidence_ids and any(fail_closed for _, fail_closed, _ in rules):
            forgotten.add(fingerprint)
    return forgotten


def _row_is_fully_forgotten(
    target_kind: CorrectionTargetKind,
    row: Mapping[str, Any],
) -> bool:
    if str(row.get("status") or "") != "archived":
        return False
    authority_ref = str(row.get("authority_ref") or "")
    if target_kind == CorrectionTargetKind.ASSERTION:
        return authority_ref.startswith("forget:")
    return (
        authority_ref.startswith("forget:") or str(row.get("status_reason") or "") == "user_forget"
    )


async def _load_relevant_active_corrections(
    db_path: str,
    corrections: Sequence[MemoryCorrection],
) -> list[MemoryCorrection]:
    if not corrections:
        return []
    target_kinds = sorted({correction.target_kind.value for correction in corrections})
    slot_keys = sorted({correction.slot_key for correction in corrections if correction.slot_key})
    target_ids = sorted(
        {
            item
            for correction in corrections
            for item in (correction.target_id, correction.replacement_target_id)
            if item
        }
    )
    async with sqlite_connection_async(db_path) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            """
            SELECT * FROM memory_corrections
            WHERE state = 'active' AND transition_cancelled_at IS NULL
              AND target_kind IN (SELECT CAST(value AS TEXT) FROM json_each(?))
              AND (
                  slot_key IN (SELECT CAST(value AS TEXT) FROM json_each(?))
                  OR target_id IN (SELECT CAST(value AS TEXT) FROM json_each(?))
              )
            """,
            (
                json.dumps(target_kinds, separators=(",", ":")),
                json.dumps(slot_keys, separators=(",", ":")),
                json.dumps(target_ids, separators=(",", ":")),
            ),
        ) as cursor:
            rows = await cursor.fetchall()
    return [MemoryCorrection.from_row(dict(row)) for row in rows]


def _newer_correction_blocks_revert(
    correction: MemoryCorrection,
    candidate: MemoryCorrection,
) -> bool:
    if candidate.correction_id == correction.correction_id:
        return False
    if candidate.target_kind != correction.target_kind:
        return False
    if (candidate.created_at, candidate.correction_id) <= (
        correction.created_at,
        correction.correction_id,
    ):
        return False
    if correction.target_kind == CorrectionTargetKind.ASSERTION:
        if candidate.slot_key != correction.slot_key:
            return False
    elif (
        candidate.slot_key != correction.slot_key
        and candidate.target_id != correction.replacement_target_id
    ):
        return False
    if candidate.target_id in {correction.target_id, correction.replacement_target_id}:
        return True
    return canonical_scope_json(candidate.scope) == canonical_scope_json(correction.scope)


def _public_claim_value(
    target_kind: CorrectionTargetKind,
    value: Mapping[str, Any] | None,
    *,
    include_lifecycle: bool = False,
) -> dict[str, Any] | None:
    if value is None:
        return None
    if target_kind == CorrectionTargetKind.ASSERTION:
        allowed = _ASSERTION_VALUE_FIELDS
    else:
        allowed = _RELATIONSHIP_VALUE_FIELDS
    result = {key: value[key] for key in allowed if key in value and value[key] is not None}
    if include_lifecycle and target_kind == CorrectionTargetKind.ASSERTION:
        lifecycle = str(value.get("status") or value.get("validation_state") or "").lower()
        if lifecycle in {"shadow", "pending"}:
            result["status"] = lifecycle
            result["validation_state"] = lifecycle
    try:
        public_scope = stored_context_scope(value)
    except (TypeError, ValueError):
        public_scope = {}
    if public_scope:
        result["scope"] = public_scope
    return result


def public_current_claim(
    target_kind: CorrectionTargetKind,
    value: Mapping[str, Any] | None,
) -> dict[str, Any] | None:
    """Return only the user-facing semantic fields of a command result claim."""
    return _public_claim_value(target_kind, value)


def _public_version(
    target_kind: CorrectionTargetKind,
    version: Mapping[str, Any],
    *,
    forgotten_ids: set[str],
) -> dict[str, Any] | None:
    record_id = _version_record_id(target_kind, version)
    if record_id and record_id in forgotten_ids:
        return None
    if target_kind == CorrectionTargetKind.ASSERTION:
        allowed = (
            "trait_value",
            "status",
            "validation_state",
            "valid_from",
            "valid_to",
            "first_inferred_at",
            "created_at",
        )
    else:
        allowed = (
            "subject_id",
            "subject_type",
            "predicate",
            "object_id",
            "object_type",
            "status",
            "valid_from",
            "valid_to",
            "first_observed_at",
            "created_at",
        )
    result = {key: version[key] for key in allowed if key in version and version[key] is not None}
    try:
        scope = stored_context_scope(version)
    except (TypeError, ValueError):
        scope = {}
    if scope:
        result["scope"] = scope
    return result


def _record_ids(corrections: Sequence[MemoryCorrection]) -> set[str]:
    return {
        item
        for correction in corrections
        for item in (correction.target_id, correction.replacement_target_id)
        if item
    }


def _record_fingerprints(
    target_kind: CorrectionTargetKind,
    *,
    corrections: Sequence[MemoryCorrection],
    versions: Sequence[Mapping[str, Any]],
) -> dict[str, set[str]]:
    result: dict[str, set[str]] = {}
    for correction in corrections:
        if correction.target_kind != target_kind:
            continue
        _add_record_fingerprint(result, correction.target_id, correction.claim_fingerprint)
        if correction.replacement_target_id:
            _add_record_fingerprint(
                result,
                correction.replacement_target_id,
                _replacement_claim_fingerprint(correction),
            )
    for version in versions:
        _add_record_fingerprint(
            result,
            _version_record_id(target_kind, version),
            str(version.get("claim_fingerprint") or ""),
        )
    return result


def _replacement_claim_fingerprint(correction: MemoryCorrection) -> str:
    replacement = correction.replacement or {}
    replacement_scope_key = scope_key(correction.scope)
    if correction.target_kind == CorrectionTargetKind.ASSERTION:
        value = replacement.get("value", replacement.get("trait_value"))
        if value is None:
            return ""
        return assertion_claim_fingerprint(
            slot_key_value=correction.slot_key,
            trait_value=value,
            scope_key_value=replacement_scope_key,
        )
    subject_id = str(replacement.get("subject_id") or "").strip()
    predicate = str(replacement.get("predicate") or "").strip()
    object_id = str(replacement.get("object_id") or "").strip()
    if not subject_id or not predicate or not object_id:
        return ""
    return relationship_claim_fingerprint(
        slot_key_value=correction.slot_key,
        subject_id=subject_id,
        predicate=predicate,
        object_id=object_id,
        scope_key_value=replacement_scope_key,
    )


def _add_record_fingerprint(
    result: dict[str, set[str]],
    record_id: str | None,
    claim_fingerprint: str | None,
) -> None:
    normalized_id = str(record_id or "").strip()
    normalized_fingerprint = str(claim_fingerprint or "").strip()
    if normalized_id and normalized_fingerprint:
        result.setdefault(normalized_id, set()).add(normalized_fingerprint)


def _version_record_ids(
    target_kind: CorrectionTargetKind,
    versions: Sequence[Mapping[str, Any]],
) -> set[str]:
    return {
        record_id for version in versions if (record_id := _version_record_id(target_kind, version))
    }


def _version_record_id(
    target_kind: CorrectionTargetKind,
    version: Mapping[str, Any],
) -> str:
    key = "assertion_id" if target_kind == CorrectionTargetKind.ASSERTION else "triple_id"
    return str(version.get(key) or "").strip()


def _optional_text(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _optional_float(value: Any) -> float | None:
    return float(value) if value is not None else None


def _enum_value(value: Any) -> str:
    return str(getattr(value, "value", value))


__all__ = [
    "correction_history_slot_key",
    "decorate_correction_records",
    "prepare_correction_history",
    "public_current_claim",
]
