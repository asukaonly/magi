"""Connection-scoped orchestration for governed assertion identity rekeys."""

from __future__ import annotations

import aiosqlite

from ..corrections.forget_governance import (
    ClaimGovernanceIdentityRewrite,
    rewrite_claim_governance_identities,
)
from ..corrections.models import CorrectionTargetKind
from ..corrections.revert_blocks import (
    IDENTITY_MERGE_REVERT_BLOCK,
    block_colliding_correction_lineages,
)
from .assertion_rekey_collisions import (
    _active_rejected_assertion_target_ids,
    _rejected_assertion_convergence_ids,
    _resolve_active_identity_collisions,
    _resolve_rejected_assertion_convergence,
)
from .assertion_rekey_governance import _rewrite_assertion_corrections
from .assertion_rekey_identity import (
    _load_catalog_entity_type,
    _project_assertion_identity,
)
from .assertion_rekey_rows import (
    _active_correction_metadata,
    _load_affected_assertions,
    _load_projected_collision_candidates,
)


class AssertionEntityRekeyCoordinator:
    """Coordinate one atomic assertion rekey on a caller-owned transaction."""

    def __init__(self, db: aiosqlite.Connection) -> None:
        self._db = db

    async def rekey(
        self,
        *,
        source_entity_id: str,
        target_entity_id: str,
        now: float,
    ) -> None:
        """Rewrite assertion identities, history, corrections, and durable governance."""
        db = self._db
        if not db.in_transaction:
            raise RuntimeError("Assertion identity rekey requires an active transaction")
        if not source_entity_id or source_entity_id == target_entity_id:
            return
        db.row_factory = aiosqlite.Row
        resolved_entity_type = await _load_catalog_entity_type(db, target_entity_id)
        affected = await _load_affected_assertions(
            db,
            source_entity_id=source_entity_id,
        )
        affected_ids = {str(row["assertion_id"]) for row in affected}
        affected_projected = {
            str(row["assertion_id"]): _project_assertion_identity(
                row,
                source_entity_id=source_entity_id,
                target_entity_id=target_entity_id,
                resolved_entity_type=resolved_entity_type,
            )
            for row in affected
        }
        collision_candidates = await _load_projected_collision_candidates(
            db,
            projected_slot_keys={identity["slot_key"] for identity in affected_projected.values()},
            excluded_assertion_ids=affected_ids,
        )
        rows = [*affected, *collision_candidates]
        projected = {
            **affected_projected,
            **{
                str(row["assertion_id"]): _project_assertion_identity(
                    row,
                    source_entity_id=source_entity_id,
                    target_entity_id=target_entity_id,
                    resolved_entity_type=resolved_entity_type,
                )
                for row in collision_candidates
            },
        }
        rejected_target_ids = await _active_rejected_assertion_target_ids(
            db,
            assertion_ids=affected_ids,
        )
        _, pending_target_ids, _ = await _active_correction_metadata(
            db,
            assertion_ids={str(row["assertion_id"]) for row in rows},
        )
        converged_rejected_target_ids = _rejected_assertion_convergence_ids(
            rows,
            projected=projected,
            rejected_target_ids=rejected_target_ids,
            pending_target_ids=pending_target_ids,
            now=now,
        )
        rejected_claim_fingerprints = {
            str(row["claim_fingerprint"] or "").strip()
            for row in affected
            if str(row["assertion_id"]) in converged_rejected_target_ids
            and str(row["claim_fingerprint"] or "").strip()
        }
        await _resolve_active_identity_collisions(
            db,
            rows=rows,
            affected_ids=affected_ids,
            projected=projected,
            now=now,
        )

        governance_rewrites: list[ClaimGovernanceIdentityRewrite] = []
        for row in affected:
            identity = projected[str(row["assertion_id"])]
            old_fingerprint = str(row["claim_fingerprint"] or "").strip()
            if old_fingerprint:
                governance_rewrites.append(
                    ClaimGovernanceIdentityRewrite(
                        old_claim_fingerprint=old_fingerprint,
                        new_claim_fingerprint=identity["claim_fingerprint"],
                        new_semantic_fingerprint=identity["semantic_fingerprint"],
                    )
                )
            await db.execute(
                """
                UPDATE tom_trait_assertions
                SET entity_id = ?, entity_type = ?, target_entity_id = ?,
                    target_entity_type = ?, slot_key = ?, claim_fingerprint = ?,
                    updated_at = MAX(updated_at, ?)
                WHERE assertion_id = ?
                """,
                (
                    identity["entity_id"],
                    identity["entity_type"],
                    identity["target_entity_id"],
                    identity["target_entity_type"],
                    identity["slot_key"],
                    identity["claim_fingerprint"],
                    now,
                    row["assertion_id"],
                ),
            )

        governance_rewrites.extend(
            await _rewrite_assertion_corrections(
                db,
                source_entity_id=source_entity_id,
                target_entity_id=target_entity_id,
                resolved_entity_type=resolved_entity_type,
                affected_assertion_ids=affected_ids,
            )
        )
        governance_rewrites = [
            rewrite
            for rewrite in governance_rewrites
            if rewrite.old_claim_fingerprint not in rejected_claim_fingerprints
        ]
        await _resolve_rejected_assertion_convergence(
            db,
            affected_assertion_ids=affected_ids,
            now=now,
        )
        await block_colliding_correction_lineages(
            db,
            target_kind=CorrectionTargetKind.ASSERTION,
            slot_keys={identity["slot_key"] for identity in projected.values()},
            block_reason=IDENTITY_MERGE_REVERT_BLOCK,
            created_at=now,
        )
        await rewrite_claim_governance_identities(
            db,
            target_kind=CorrectionTargetKind.ASSERTION,
            rewrites=governance_rewrites,
        )
        await db.execute(
            """
            UPDATE memory_derivation_dependencies
            SET subject_key = ?
            WHERE source_kind = 'assertion' AND subject_key = ?
            """,
            (target_entity_id, source_entity_id),
        )
        await db.execute(
            "DELETE FROM tom_snapshots WHERE entity_id IN (?, ?)",
            (source_entity_id, target_entity_id),
        )
