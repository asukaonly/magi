"""Connection-scoped orchestration for governed relationship identity rekeys."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass

import aiosqlite

from ..corrections.fingerprints import (
    relationship_claim_fingerprint,
    relationship_triple_id,
)
from ..corrections.forget_governance import rewrite_claim_governance_identities
from ..corrections.models import CorrectionTargetKind
from ..corrections.revert_blocks import (
    LINEAGE_COLLISION_REVERT_BLOCK,
    block_colliding_correction_lineages,
)
from .relationship_rekey_current import (
    _load_edge,
    _load_identity_duplicate,
    _rejected_relationship_convergence_ids,
    _rejected_relationship_target_ids,
    _write_current_edge,
)
from .relationship_rekey_corrections import _rewrite_corrections
from .relationship_rekey_history import (
    _collect_relationship_governance_rewrites,
    _load_affected_edge_corrections,
)
from .relationship_rekey_identity import relationship_slot_key_on_connection
from .relationship_rekey_reconciliation import _reconcile_rewritten_corrections
from .relationship_rekey_references import (
    _rewrite_conflict_effect_references,
    _rewrite_current_edge_references,
    _rewrite_dependencies,
    _rewrite_materialized_json_references,
    _rewrite_versions,
)


@dataclass(frozen=True, slots=True)
class RelationshipIdentityRekeyResult:
    """Describe one completed current-edge identity rewrite."""

    rewritten: bool
    merged: bool
    triple_id: str | None
    invalidated_vector_ids: frozenset[str]
    rewritten_reference_ids: tuple[tuple[str, str], ...]


class RelationshipIdentityRekeyCoordinator:
    """Coordinate one atomic relationship rekey on a caller-owned transaction."""

    def __init__(self, db: aiosqlite.Connection) -> None:
        self._db = db

    async def rekey(
        self,
        *,
        source_triple_id: str,
        subject_id: str,
        predicate: str,
        object_id: str,
        now: float,
        reference_replacements: Mapping[str, str] | None = None,
        rewrite_materialized_references: bool = True,
    ) -> RelationshipIdentityRekeyResult:
        """Move one relationship to its deterministic identity and rewrite all references."""
        db = self._db
        if not db.in_transaction:
            raise RuntimeError("Relationship identity rekey requires an active transaction")
        db.row_factory = aiosqlite.Row
        source = await _load_edge(db, source_triple_id)
        if source is None:
            return RelationshipIdentityRekeyResult(
                False,
                False,
                None,
                frozenset(),
                (),
            )

        normalized_predicate = str(predicate).strip().upper()
        scope_key = str(source["scope_key"] or "global")
        target_triple_id = relationship_triple_id(
            subject_id=subject_id,
            predicate=normalized_predicate,
            object_id=object_id,
            scope_key_value=scope_key,
        )
        target_slot_key = await relationship_slot_key_on_connection(
            db,
            subject_id=subject_id,
            predicate=normalized_predicate,
            object_id=object_id,
        )
        target_fingerprint = relationship_claim_fingerprint(
            slot_key_value=target_slot_key,
            subject_id=subject_id,
            predicate=normalized_predicate,
            object_id=object_id,
            scope_key_value=scope_key,
        )
        duplicate = await _load_identity_duplicate(
            db,
            source_triple_id=source_triple_id,
            subject_id=subject_id,
            predicate=normalized_predicate,
            object_id=object_id,
            scope_key=scope_key,
        )
        content_identity_changed = (
            str(source["subject_id"]) != subject_id
            or str(source["predicate"]).strip().upper() != normalized_predicate
            or str(source["object_id"]) != object_id
            or source_triple_id != target_triple_id
            or duplicate is not None
        )

        affected_rows = [source, *([duplicate] if duplicate is not None else [])]
        affected_ids = {str(row["triple_id"]) for row in affected_rows}
        id_map = {old_id: target_triple_id for old_id in affected_ids if old_id != target_triple_id}
        affected_corrections = await _load_affected_edge_corrections(db, affected_ids)
        rejected_target_ids = _rejected_relationship_target_ids(affected_corrections)
        converged_rejected_target_ids = _rejected_relationship_convergence_ids(
            affected_rows,
            rejected_target_ids=rejected_target_ids,
            now=now,
        )
        rejected_claim_fingerprints = {
            str(row["claim_fingerprint"] or "").strip()
            for row in affected_rows
            if str(row["triple_id"]) in converged_rejected_target_ids
            and str(row["claim_fingerprint"] or "").strip()
        }
        governance_rewrites = await _collect_relationship_governance_rewrites(
            db,
            affected_rows=affected_rows,
            affected_ids=affected_ids,
            affected_corrections=affected_corrections,
            subject_id=subject_id,
            predicate=normalized_predicate,
            object_id=object_id,
            slot_key=target_slot_key,
        )
        governance_rewrites = tuple(
            rewrite
            for rewrite in governance_rewrites
            if rewrite.old_claim_fingerprint not in rejected_claim_fingerprints
        )
        await _write_current_edge(
            db,
            rows=affected_rows,
            target_triple_id=target_triple_id,
            subject_id=subject_id,
            predicate=normalized_predicate,
            object_id=object_id,
            slot_key=target_slot_key,
            claim_fingerprint=target_fingerprint,
            now=now,
            content_identity_changed=content_identity_changed,
            excluded_evidence_ids=converged_rejected_target_ids,
        )
        await _rewrite_versions(
            db,
            affected_ids=affected_ids,
            target_triple_id=target_triple_id,
            subject_id=subject_id,
            predicate=normalized_predicate,
            object_id=object_id,
        )
        await _rewrite_current_edge_references(db, id_map)
        await _rewrite_conflict_effect_references(db, id_map)
        await _rewrite_corrections(
            db,
            affected_ids=affected_ids,
            id_map=id_map,
            target_triple_id=target_triple_id,
            subject_id=subject_id,
            predicate=normalized_predicate,
            object_id=object_id,
            reference_replacements=reference_replacements,
            corrections=affected_corrections,
        )
        await _reconcile_rewritten_corrections(
            db,
            correction_ids={
                str(correction["correction_id"]) for correction in affected_corrections
            },
            now=now,
        )
        await block_colliding_correction_lineages(
            db,
            target_kind=CorrectionTargetKind.EDGE,
            slot_keys={target_slot_key},
            block_reason=LINEAGE_COLLISION_REVERT_BLOCK,
            created_at=now,
        )
        await rewrite_claim_governance_identities(
            db,
            target_kind=CorrectionTargetKind.EDGE,
            rewrites=governance_rewrites,
        )
        await _rewrite_dependencies(db, id_map)
        combined_reference_map = dict(reference_replacements or {})
        combined_reference_map.update(id_map)
        if rewrite_materialized_references:
            await _rewrite_materialized_json_references(db, combined_reference_map)

        invalidated_ids = (
            frozenset({*affected_ids, target_triple_id})
            if content_identity_changed
            else frozenset()
        )
        return RelationshipIdentityRekeyResult(
            rewritten=duplicate is None,
            merged=duplicate is not None,
            triple_id=target_triple_id,
            invalidated_vector_ids=invalidated_ids,
            rewritten_reference_ids=tuple(sorted(id_map.items())),
        )
