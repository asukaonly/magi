"""Resolve assertion-specific collisions and rejected-claim convergence."""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from typing import Any

import aiosqlite

from ..corrections.forget_governance import forgotten_evidence_event_ids_for_claims
from ..corrections.identity_resolution import resolve_correction_after_identity_merge
from ..corrections.models import CorrectionTargetKind
from ..corrections.revert_blocks import (
    IDENTITY_MERGE_REVERT_BLOCK,
    block_correction_reverts,
)
from .assertion_rekey_rows import (
    _UNIQUE_INDEX_EXCLUDED_STATUSES,
    _active_correction_metadata,
    _assertion_winner_rank,
    _is_current_independent_assertion,
    _merge_same_claim_evidence,
)


async def _resolve_active_identity_collisions(
    db: aiosqlite.Connection,
    *,
    rows: Sequence[Mapping[str, Any]],
    affected_ids: set[str],
    projected: Mapping[str, Mapping[str, str]],
    now: float,
) -> None:
    if not affected_ids:
        return
    groups: dict[tuple[str, str, str, str, str], list[Mapping[str, Any]]] = {}
    for row in rows:
        if str(row["status"] or "active") in _UNIQUE_INDEX_EXCLUDED_STATUSES:
            continue
        identity = projected[str(row["assertion_id"])]
        key = (
            identity["entity_id"],
            identity["entity_type"],
            str(row["trait_name"]),
            identity["target_entity_id"],
            str(row.get("scope_key") or "global"),
        )
        groups.setdefault(key, []).append(row)
    collision_groups = [
        candidates
        for candidates in groups.values()
        if len(candidates) >= 2
        and any(str(row["assertion_id"]) in affected_ids for row in candidates)
    ]
    if not collision_groups:
        return
    collision_assertion_ids = {
        str(row["assertion_id"]) for candidates in collision_groups for row in candidates
    }
    (
        correction_times,
        pending_target_ids,
        correction_targets_by_replacement,
    ) = await _active_correction_metadata(
        db,
        assertion_ids=collision_assertion_ids,
    )
    forgotten_event_ids = await forgotten_evidence_event_ids_for_claims(
        db,
        target_kind=CorrectionTargetKind.ASSERTION,
        claim_fingerprints=(
            str(row.get("claim_fingerprint") or "")
            for candidates in collision_groups
            for row in candidates
        ),
    )
    rows_by_id = {str(row["assertion_id"]): row for row in rows}
    correction_replacement_ids = set(correction_targets_by_replacement)
    for candidates in collision_groups:
        independent_claim_fingerprints = {
            projected[str(row["assertion_id"])]["claim_fingerprint"]
            for row in candidates
            if _is_current_independent_assertion(
                row,
                now=now,
                pending_target_ids=pending_target_ids,
            )
        }
        winner = max(
            candidates,
            key=lambda row: _assertion_winner_rank(
                row,
                correction_times=correction_times,
                pending_target_ids=pending_target_ids,
                correction_replacement_ids=correction_replacement_ids,
                independent_claim_fingerprints=independent_claim_fingerprints,
                projected_claim_fingerprint=projected[str(row["assertion_id"])][
                    "claim_fingerprint"
                ],
                now=now,
            ),
        )
        winner_id = str(winner["assertion_id"])
        winner_correction = correction_targets_by_replacement.get(winner_id)
        correction_target_id = winner_correction[0] if winner_correction is not None else None
        correction_target = (
            rows_by_id.get(correction_target_id) if correction_target_id is not None else None
        )
        if _is_current_independent_assertion(
            winner,
            now=now,
            pending_target_ids=pending_target_ids,
        ):
            unsafe_correction_ids: set[str] = set()
            winner_scope_key = str(winner.get("scope_key") or "global")
            for loser in candidates:
                loser_id = str(loser["assertion_id"])
                correction_metadata = correction_targets_by_replacement.get(loser_id)
                if (
                    loser_id == winner_id
                    or correction_metadata is None
                    or projected[loser_id]["claim_fingerprint"]
                    != projected[winner_id]["claim_fingerprint"]
                ):
                    continue
                loser_correction_target = rows_by_id.get(correction_metadata[0])
                if (
                    loser_correction_target is not None
                    and str(loser_correction_target.get("scope_key") or "global")
                    == winner_scope_key
                ):
                    unsafe_correction_ids.add(correction_metadata[1])
            await block_correction_reverts(
                db,
                correction_ids=unsafe_correction_ids,
                block_reason=IDENTITY_MERGE_REVERT_BLOCK,
                created_at=now,
            )
        for loser in candidates:
            loser_id = str(loser["assertion_id"])
            if loser_id == winner_id:
                continue
            if correction_target is not None:
                await _merge_same_claim_evidence(
                    db,
                    winner=correction_target,
                    loser=loser,
                    winner_identity=projected[str(correction_target["assertion_id"])],
                    loser_identity=projected[loser_id],
                    forgotten_event_ids=forgotten_event_ids,
                    now=now,
                )
            await db.execute(
                """
                UPDATE tom_trait_assertions
                SET status = 'superseded', superseded_by = ?,
                    superseded_at = COALESCE(superseded_at, ?),
                    valid_to = COALESCE(valid_to, ?), updated_at = ?
                WHERE assertion_id = ?
                """,
                (winner_id, now, now, now, loser_id),
            )
            await _merge_same_claim_evidence(
                db,
                winner=winner,
                loser=loser,
                winner_identity=projected[winner_id],
                loser_identity=projected[loser_id],
                forgotten_event_ids=forgotten_event_ids,
                now=now,
            )


async def _resolve_rejected_assertion_convergence(
    db: aiosqlite.Connection,
    *,
    affected_assertion_ids: set[str],
    now: float,
) -> None:
    """Retire a rejection when its target converges on an independent claim."""
    if not affected_assertion_ids:
        return
    assertion_ids_json = json.dumps(sorted(affected_assertion_ids), ensure_ascii=False)
    async with db.execute(
        """
        SELECT corrections.correction_id, survivor.*
        FROM memory_corrections AS corrections
        JOIN tom_trait_assertions AS rejected
          ON rejected.assertion_id = corrections.target_id
        JOIN tom_trait_assertions AS survivor
          ON survivor.claim_fingerprint = rejected.claim_fingerprint
         AND survivor.assertion_id != rejected.assertion_id
        WHERE corrections.target_kind = 'assertion'
          AND corrections.state = 'active'
          AND corrections.transition_cancelled_at IS NULL
          AND corrections.correction_kind = 'record_error'
          AND corrections.replacement_target_id IS NULL
          AND (
              corrections.replacement_json IS NULL
              OR corrections.replacement_json = 'null'
          )
          AND corrections.target_id IN (
              SELECT CAST(value AS TEXT) FROM json_each(?)
          )
        ORDER BY corrections.correction_id, survivor.assertion_id
        """,
        (assertion_ids_json,),
    ) as cursor:
        rows = [dict(row) for row in await cursor.fetchall()]
    if not rows:
        return
    survivor_ids = {str(row["assertion_id"]) for row in rows}
    _, pending_target_ids, _ = await _active_correction_metadata(
        db,
        assertion_ids=survivor_ids,
    )
    correction_ids = {
        str(row["correction_id"])
        for row in rows
        if _is_current_independent_assertion(
            row,
            now=now,
            pending_target_ids=pending_target_ids,
        )
    }
    for correction_id in sorted(correction_ids):
        await resolve_correction_after_identity_merge(
            db,
            correction_id=correction_id,
            resolved_at=now,
        )


async def _active_rejected_assertion_target_ids(
    db: aiosqlite.Connection,
    *,
    assertion_ids: set[str],
) -> set[str]:
    if not assertion_ids:
        return set()
    assertion_ids_json = json.dumps(sorted(assertion_ids), ensure_ascii=False)
    async with db.execute(
        """
        SELECT target_id
        FROM memory_corrections
        WHERE target_kind = 'assertion'
          AND state = 'active'
          AND transition_cancelled_at IS NULL
          AND correction_kind = 'record_error'
          AND replacement_target_id IS NULL
          AND (replacement_json IS NULL OR replacement_json = 'null')
          AND target_id IN (
              SELECT CAST(value AS TEXT) FROM json_each(?)
          )
        """,
        (assertion_ids_json,),
    ) as cursor:
        return {str(row[0]) for row in await cursor.fetchall()}


def _rejected_assertion_convergence_ids(
    rows: Sequence[Mapping[str, Any]],
    *,
    projected: Mapping[str, Mapping[str, str]],
    rejected_target_ids: set[str],
    pending_target_ids: set[str],
    now: float,
) -> set[str]:
    independent_by_fingerprint: dict[str, set[str]] = {}
    for row in rows:
        assertion_id = str(row["assertion_id"])
        if not _is_current_independent_assertion(
            row,
            now=now,
            pending_target_ids=pending_target_ids,
        ):
            continue
        independent_by_fingerprint.setdefault(
            projected[assertion_id]["claim_fingerprint"],
            set(),
        ).add(assertion_id)
    return {
        target_id
        for target_id in rejected_target_ids
        if any(
            assertion_id != target_id
            for assertion_id in independent_by_fingerprint.get(
                projected[target_id]["claim_fingerprint"],
                set(),
            )
        )
    }
