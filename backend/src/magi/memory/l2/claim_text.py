"""Resolve Claim wording from host-owned identities and evidence surfaces."""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any

import aiosqlite

from .ontology_aliases import canonicalize_predicate
from .phase1_models import L2Phase1FactClaim, L2Phase1Result
from .semantic_routing import ObjectRole, assertion_predicate_descriptors


@dataclass(frozen=True, slots=True)
class ResolvedClaimText:
    """Names are display inputs, never identity or evidence replacements."""

    subject_name: str | None = None
    object_name: str | None = None
    subject_is_self: bool = False
    subject_entity_id: str | None = None
    object_entity_id: str | None = None
    object_surface: str | None = None
    subject_resolution_version: int = 0
    object_resolution_version: int = 0


def claim_object_is_literal(predicate: str) -> bool:
    """Use the owning route's value contract, independently of entity type."""
    canonical = canonicalize_predicate(predicate) or predicate.upper()
    return any(
        item.predicate == canonical
        and item.object_role in {ObjectRole.CANONICAL_VALUE, ObjectRole.GOAL_TEXT}
        for item in assertion_predicate_descriptors()
    )


def grounded_reference_surface(
    claim: L2Phase1FactClaim,
    result: L2Phase1Result,
    *,
    role: str,
    antecedent_texts: Sequence[str] = (),
) -> str | None:
    """Select exact source wording; a resolver ID is never a source name."""
    ref = claim.object_ref if role == "object" else claim.subject_ref
    if role == "object" and claim_object_is_literal(claim.predicate):
        return ref
    sources = [claim.evidence_text, *antecedent_texts]
    matches = [
        entity for entity in result.entities
        if ref in {entity.surface, entity.normalized_name, entity.resolved_id, *entity.alias_signals}
    ]
    surfaces = {
        entity.surface for entity in matches
        if entity.surface and any(entity.surface in text for text in sources)
        and entity.surface != entity.resolved_id
    }
    if len(surfaces) == 1:
        return next(iter(surfaces))
    if matches or any(entity.resolved_id == ref for entity in result.entities):
        return None
    if ref and any(ref in text for text in sources):
        return ref
    return None


def persisted_claim_to_phase1(row: Mapping[str, Any]) -> L2Phase1FactClaim:
    """Reload immutable semantic fields without using presentation as a reference."""
    frame = _json_value(row.get("raw_time_frame_json", row.get("raw_time_frame")))
    frame = frame if isinstance(frame, dict) else None
    value = _json_value(row.get("object_value_json")) if "object_value_json" in row else row.get("object_value")
    return L2Phase1FactClaim(
        claim_id=str(row["claim_id"]),
        subject_ref=str(row["subject_ref"]),
        subject_type=str(row["subject_type"]),
        predicate=str(row["canonical_predicate"]),
        object_ref=value if isinstance(value, str) else "",
        object_type=str(row["object_type"]),
        object_surface=row.get("object_surface"),
        fact_kind=str(row["fact_kind"]),
        temporal_cue=str(row["temporal_cue"]),
        polarity=str(row["polarity"]),
        specificity=str(row["specificity"]),
        confidence=float(row["confidence"]),
        raw_time_expression=str((frame or {}).get("raw") or ""),
        raw_time_frame=frame,
        fact_valid_from=row.get("fact_valid_from"),
        fact_valid_to=row.get("fact_valid_to"),
        target_from=row.get("target_from"),
        target_to=row.get("target_to"),
    )


async def load_claim_texts(
    db: aiosqlite.Connection, claim_ids: Sequence[str]
) -> dict[str, ResolvedClaimText]:
    """Batch hydrate names for active Claims inside the caller's read/write fence.

    Consumers retain their own admission, forgetting and lease checks. Resolved
    entities require a catalog name. Unresolved objects may use an independently
    grounded surface, but never the raw reference as a fallback.
    """
    if not claim_ids:
        return {}
    async with db.execute(
        """
        WITH selected AS (SELECT value AS claim_id FROM json_each(?)),
        ranked_refs AS (
            SELECT refs.*, ROW_NUMBER() OVER (
                PARTITION BY refs.claim_id, refs.ref_role
                ORDER BY refs.resolution_version DESC, refs.created_at DESC, refs.entity_id
            ) AS rank
            FROM l2_claim_entity_refs refs JOIN selected USING (claim_id)
            WHERE refs.invalidated_at IS NULL
        )
        SELECT claims.*, subject_ref.entity_id AS resolved_subject_id,
               object_ref.entity_id AS resolved_object_id,
               subject_ref.resolution_version AS subject_resolution_version,
               object_ref.resolution_version AS object_resolution_version,
               subject.canonical_name AS subject_name,
               object.canonical_name AS object_name,
               raw_subject.canonical_name AS raw_subject_name,
               raw_object.entity_id AS raw_object_id,
               EXISTS (
                   SELECT 1 FROM l2_claim_entity_refs history
                   WHERE history.claim_id = claims.claim_id
                     AND history.ref_role = 'object'
                     AND history.entity_id = claims.object_surface
               ) AS surface_is_historical_object_id,
               EXISTS (
                   SELECT 1 FROM l2_claim_evidence evidence
                   WHERE evidence.claim_id = claims.claim_id
                     AND json_extract(evidence.evidence_locator_json,
                         '$.reference_surfaces.object') = claims.object_surface
               ) OR EXISTS (
                   SELECT 1 FROM entity_name_evidence names
                   JOIN l2_claim_evidence evidence ON evidence.event_id = names.event_id
                   WHERE evidence.claim_id = claims.claim_id
                     AND names.display_name = claims.object_surface
               ) AS object_surface_grounded,
               (SELECT json_extract(evidence.evidence_locator_json,
                           '$.reference_surfaces.subject')
                FROM l2_claim_evidence evidence
                WHERE evidence.claim_id = claims.claim_id
                  AND json_extract(evidence.evidence_locator_json,
                      '$.reference_surfaces.subject') IS NOT NULL
                ORDER BY evidence.event_id LIMIT 1) AS subject_surface
        FROM l2_grounded_claims claims JOIN selected USING (claim_id)
        LEFT JOIN ranked_refs subject_ref ON subject_ref.claim_id = claims.claim_id
            AND subject_ref.ref_role = 'subject' AND subject_ref.rank = 1
        LEFT JOIN ranked_refs object_ref ON object_ref.claim_id = claims.claim_id
            AND object_ref.ref_role = 'object' AND object_ref.rank = 1
        LEFT JOIN entity_catalog subject ON subject.entity_id = subject_ref.entity_id
        LEFT JOIN entity_catalog object ON object.entity_id = object_ref.entity_id
        LEFT JOIN entity_catalog raw_subject ON raw_subject.entity_id = claims.subject_ref
        LEFT JOIN entity_catalog raw_object ON raw_object.entity_id = claims.object_surface
        WHERE claims.availability = 'active'
        """,
        (json.dumps(list(claim_ids)),),
    ) as cursor:
        columns = [item[0] for item in cursor.description or ()]
        rows = [dict(zip(columns, row)) for row in await cursor.fetchall()]
    texts: dict[str, ResolvedClaimText] = {}
    for row in rows:
        subject_id = row["resolved_subject_id"] or row["subject_ref"]
        subject_is_self = bool(row["user_id"]) and subject_id == f"user:{row['user_id']}"
        subject_name = _name(
            row["subject_name"] if row["resolved_subject_id"] else row["raw_subject_name"],
            subject_id,
        )
        if not subject_name and not row["resolved_subject_id"]:
            subject_name = _name(row["subject_surface"], subject_id)
        object_surface = (
            None if row["raw_object_id"] or row["surface_is_historical_object_id"]
            or not row["object_surface_grounded"]
            else _name(row["object_surface"], None)
        )
        literal = claim_object_is_literal(str(row["canonical_predicate"]))
        if literal:
            value = _json_value(row["object_value_json"])
            object_name = value if isinstance(value, str) and value.strip() else None
            object_surface = object_name
        elif row["resolved_object_id"]:
            object_name = _name(row["object_name"], row["resolved_object_id"])
        else:
            object_name = object_surface
        texts[str(row["claim_id"])] = ResolvedClaimText(
            subject_name=subject_name, object_name=object_name, subject_is_self=subject_is_self,
            subject_entity_id=subject_id,
            object_entity_id=None if literal else row["resolved_object_id"],
            object_surface=object_surface,
            subject_resolution_version=int(row["subject_resolution_version"] or 0),
            object_resolution_version=0 if literal else int(row["object_resolution_version"] or 0),
        )
    return texts


def _name(value: Any, entity_id: str | None) -> str | None:
    text = value.strip() if isinstance(value, str) else ""
    return text if text and text != entity_id else None


def _json_value(value: Any) -> Any:
    if not isinstance(value, str):
        return value
    try:
        return json.loads(value)
    except (TypeError, ValueError):
        return None
