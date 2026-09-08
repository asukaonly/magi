"""Atomic identity changes and their durable projection invalidations."""

from __future__ import annotations

import uuid
from typing import Any

import aiosqlite

from ..assertions.assertion_rekey_coordinator import AssertionEntityRekeyCoordinator
from ..corrections.repository import MemoryCorrectionRepository
from ..graph.relationship_rekey_coordinator import RelationshipIdentityRekeyCoordinator
from ..projection.entity_links import stage_entity_identity_link_change
from .governance_models import EntityChangePreview
from .maintenance import L2EntityMaintenance


async def apply_identity_change(
    db: aiosqlite.Connection,
    *,
    db_path: str,
    preview: EntityChangePreview,
    state: dict[str, Any],
    operation_id: str,
    now: float,
) -> set[str]:
    """Apply catalog identity and all current references under one write lock."""
    command = preview.command
    maintenance = L2EntityMaintenance(db_path=db_path)
    invalidated: set[str] = set()
    if command.kind == "merge":
        assert command.target_entity_id is not None
        invalidated = await maintenance._merge_entity_into_locked(
            db,
            winner_id=command.target_entity_id,
            loser_id=command.entity_id,
            now=now,
            operation_id=operation_id,
        )
        # A review of the old identity must be requested anew against the survivor's evidence.
    else:
        await db.execute(
            "UPDATE entity_catalog SET entity_type = ?, embedding_status = 'pending', embedding_profile_id = NULL, last_embedded_at = NULL, updated_at = ? WHERE entity_id = ?",
            (command.new_type, now, command.entity_id),
        )
        await AssertionEntityRekeyCoordinator(db).rekey(
            source_entity_id=command.entity_id,
            target_entity_id=command.entity_id,
            now=now,
            refresh_type=True,
        )
        invalidated.clear()
        for row in state["relationships"]:
            result = await RelationshipIdentityRekeyCoordinator(db).rekey(
                source_triple_id=str(row["triple_id"]),
                subject_id=str(row["subject_id"]),
                predicate=str(row["predicate"]),
                object_id=str(row["object_id"]),
                now=now,
            )
            invalidated.update(result.invalidated_vector_ids)
            invalidated.add(str(row["triple_id"]))
        # Enrichment is versioned separately from immutable source Claims.
        await maintenance._rekey_claim_entity_refs_locked(
            db, source_entity_id=command.entity_id, target_entity_id=command.entity_id, now=now
        )
        await db.execute(
            "UPDATE entity_identity_reviews SET status = 'applied', version = version + 1, updated_at = ? WHERE entity_id = ? AND proposed_type = ? AND status = 'pending'",
            (now, command.entity_id, command.new_type),
        )
    current_id = command.target_entity_id or command.entity_id
    current_type = command.new_type or (
        preview.target.entity_type if preview.target else preview.entity.entity_type
    )
    await stage_entity_identity_link_change(
        db,
        source_entity_id=command.entity_id,
        target_entity_id=current_id,
        target_entity_type=current_type,
        operation_id=operation_id,
    )
    await db.execute(
        "UPDATE entity_catalog SET embedding_status = 'pending', embedding_profile_id = NULL, last_embedded_at = NULL, updated_at = ? WHERE entity_id = ?",
        (now, current_id),
    )
    # Every in-flight extraction may hold a stale candidate set, including batches that have
    # not written their first mention. Fence and retry those complete attempts after a user decision.
    await db.execute(
        """UPDATE l2_projection_jobs SET status = 'pending',
        attempt_count = MAX(attempt_count - 1, 0), lease_token = NULL, lease_heartbeat_at = NULL,
        batch_attempt_key = NULL, batch_descriptor_json = NULL, batch_bound_at = NULL,
        claimed_by = NULL, claimed_at = NULL, started_at = NULL, completed_at = NULL,
        terminal_at = NULL, next_retry_at = ?, last_error = 'entity_identity_changed', updated_at = ?
        WHERE status IN ('queued','running')""",
        (now, now),
    )
    return invalidated


async def enqueue_identity_derivations(
    db: aiosqlite.Connection, *, db_path: str, state: dict[str, Any], operation_id: str, now: float
) -> None:
    repository = MemoryCorrectionRepository(db_path)
    subjects = list(state["subjects"])
    await repository.invalidate_l3_insights_on_connection(
        db,
        source_kind="edge",
        source_ids=[row["triple_id"] for row in state["relationships"]],
        subject_keys=subjects,
        include_current_subjects=True,
        updated_at=now,
    )
    await repository.invalidate_l3_insights_on_connection(
        db,
        source_kind="assertion",
        source_ids=[row["assertion_id"] for row in state["assertions"]],
        subject_keys=subjects,
        include_current_subjects=True,
        updated_at=now,
    )
    for subject in subjects:
        revision = await repository.bump_subject_revision(db, subject_key=subject, updated_at=now)
        await db.execute("DELETE FROM tom_snapshots WHERE entity_id = ?", (subject,))
        job_kinds = ["snapshot", "l3_insight"]
        if subject.startswith("user:"):
            job_kinds.extend(("profile", "portrait"))
        for kind in job_kinds:
            await db.execute(
                """INSERT INTO memory_derivation_jobs(
                job_id, entity_operation_id, job_kind, target_key, target_revision, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?)""",
                (
                    f"identity_job_{uuid.uuid4().hex}",
                    operation_id,
                    kind,
                    subject,
                    revision,
                    now,
                    now,
                ),
            )
