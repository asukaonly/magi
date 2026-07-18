"""Transactional identity rewrites for governed L2 assertions."""

from __future__ import annotations

import json
from collections.abc import Mapping
from typing import Any

import aiosqlite

from ..corrections.fingerprints import (
    assertion_claim_fingerprint,
    assertion_slot_key,
    scope_key,
)
from ..corrections.forget_governance import (
    ClaimGovernanceIdentityRewrite,
    decode_evidence_event_ids,
    forgotten_evidence_event_ids_for_claims,
    rewrite_claim_governance_identities,
)
from ..corrections.identity_resolution import (
    resolve_correction_after_identity_merge,
)
from ..corrections.models import CorrectionTargetKind
from ..corrections.ownership import has_correction_owner
from ..corrections.revert_blocks import (
    IDENTITY_MERGE_REVERT_BLOCK,
    block_correction_reverts,
    block_colliding_correction_lineages,
)

_UNIQUE_INDEX_EXCLUDED_STATUSES = frozenset(
    {
        "archived",
        "expired",
        "shadow",
        "superseded",
        "user_rejected",
    }
)


async def rekey_assertion_entity_identity(
    db: aiosqlite.Connection,
    *,
    source_entity_id: str,
    target_entity_id: str,
    now: float,
) -> None:
    """Rewrite assertion identities, history, corrections, and durable governance."""
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


async def _load_affected_assertions(
    db: aiosqlite.Connection,
    *,
    source_entity_id: str,
) -> list[dict[str, Any]]:
    async with db.execute(
        """
        SELECT * FROM tom_trait_assertions
        WHERE entity_id = ? OR target_entity_id = ?
        ORDER BY assertion_id
        """,
        (source_entity_id, source_entity_id),
    ) as cursor:
        return [dict(row) for row in await cursor.fetchall()]


async def _load_projected_collision_candidates(
    db: aiosqlite.Connection,
    *,
    projected_slot_keys: set[str],
    excluded_assertion_ids: set[str],
) -> list[dict[str, Any]]:
    if not projected_slot_keys:
        return []
    slot_keys_json = json.dumps(sorted(projected_slot_keys), ensure_ascii=False)
    excluded_ids_json = json.dumps(sorted(excluded_assertion_ids), ensure_ascii=False)
    async with db.execute(
        """
        SELECT * FROM tom_trait_assertions
        WHERE slot_key IN (SELECT CAST(value AS TEXT) FROM json_each(?))
          AND assertion_id NOT IN (SELECT CAST(value AS TEXT) FROM json_each(?))
        ORDER BY assertion_id
        """,
        (slot_keys_json, excluded_ids_json),
    ) as cursor:
        return [dict(row) for row in await cursor.fetchall()]


def _project_assertion_identity(
    row: Mapping[str, Any],
    *,
    source_entity_id: str,
    target_entity_id: str,
    resolved_entity_type: str | None,
) -> dict[str, str]:
    entity_changed = str(row["entity_id"]) == source_entity_id
    entity_id = target_entity_id if entity_changed else str(row["entity_id"])
    entity_type = (
        resolved_entity_type if entity_changed and resolved_entity_type else str(row["entity_type"])
    )
    current_target = str(row.get("target_entity_id") or "")
    target_changed = current_target == source_entity_id
    assertion_target = target_entity_id if target_changed else current_target
    target_type = (
        resolved_entity_type
        if target_changed and resolved_entity_type
        else str(row.get("target_entity_type") or "")
    )
    slot_key_value = assertion_slot_key(
        entity_type=entity_type,
        entity_id=entity_id,
        trait_name=str(row["trait_name"]),
        target_entity_id=assertion_target,
    )
    claim_fingerprint = assertion_claim_fingerprint(
        slot_key_value=slot_key_value,
        trait_value=row["trait_value"],
        scope_key_value=str(row.get("scope_key") or "global"),
    )
    return {
        "entity_id": entity_id,
        "entity_type": entity_type,
        "target_entity_id": assertion_target,
        "target_entity_type": target_type,
        "slot_key": slot_key_value,
        "claim_fingerprint": claim_fingerprint,
        "semantic_fingerprint": assertion_claim_fingerprint(
            slot_key_value=slot_key_value,
            trait_value=row["trait_value"],
        ),
    }


async def _resolve_active_identity_collisions(
    db: aiosqlite.Connection,
    *,
    rows: list[Mapping[str, Any]],
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
                    winner_identity=projected[correction_target_id],
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
    rows: list[Mapping[str, Any]],
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


async def _active_correction_metadata(
    db: aiosqlite.Connection,
    *,
    assertion_ids: set[str],
) -> tuple[dict[str, float], set[str], dict[str, tuple[str, str]]]:
    if not assertion_ids:
        return {}, set(), {}
    assertion_ids_json = json.dumps(sorted(assertion_ids), ensure_ascii=False)
    async with db.execute(
        """
        SELECT correction_id, target_id, replacement_target_id, created_at,
               correction_kind, transition_applied_at
        FROM memory_corrections
        WHERE target_kind = 'assertion' AND state = 'active'
          AND transition_cancelled_at IS NULL
          AND target_id IN (SELECT CAST(value AS TEXT) FROM json_each(?))
        UNION
        SELECT correction_id, target_id, replacement_target_id, created_at,
               correction_kind, transition_applied_at
        FROM memory_corrections
        WHERE target_kind = 'assertion' AND state = 'active'
          AND transition_cancelled_at IS NULL
          AND replacement_target_id IN (
              SELECT CAST(value AS TEXT) FROM json_each(?)
          )
        """,
        (assertion_ids_json, assertion_ids_json),
    ) as cursor:
        rows = await cursor.fetchall()
    result: dict[str, float] = {}
    pending_target_ids: set[str] = set()
    correction_targets_by_replacement: dict[str, tuple[float, str, str]] = {}
    for (
        correction_id,
        target_id,
        replacement_target_id,
        created_at,
        correction_kind,
        transition_applied_at,
    ) in rows:
        for assertion_id in (target_id, replacement_target_id):
            normalized = str(assertion_id or "").strip()
            if normalized:
                result[normalized] = max(result.get(normalized, 0.0), float(created_at))
        if str(correction_kind) == "situation_changed" and transition_applied_at is None:
            pending_target_ids.add(str(target_id))
        normalized_replacement_id = str(replacement_target_id or "").strip()
        if normalized_replacement_id:
            existing = correction_targets_by_replacement.get(normalized_replacement_id)
            candidate = (float(created_at), str(correction_id), str(target_id))
            if existing is None or candidate[:2] > existing[:2]:
                correction_targets_by_replacement[normalized_replacement_id] = candidate
    return (
        result,
        pending_target_ids,
        {
            replacement_id: (target_id, correction_id)
            for replacement_id, (_, correction_id, target_id) in (
                correction_targets_by_replacement.items()
            )
        },
    )


def _assertion_winner_rank(
    row: Mapping[str, Any],
    *,
    correction_times: Mapping[str, float],
    pending_target_ids: set[str],
    correction_replacement_ids: set[str],
    independent_claim_fingerprints: set[str],
    projected_claim_fingerprint: str,
    now: float,
) -> tuple[Any, ...]:
    assertion_id = str(row["assertion_id"])
    correction_at = correction_times.get(assertion_id, 0.0)
    is_independent = _is_current_independent_assertion(
        row,
        now=now,
        pending_target_ids=pending_target_ids,
    )
    is_authoritative_change = (
        assertion_id in correction_replacement_ids
        and projected_claim_fingerprint not in independent_claim_fingerprints
    )
    return (
        is_authoritative_change,
        is_independent,
        str(row.get("status") or "active") != "invalidated",
        correction_at > 0,
        correction_at,
        bool(str(row.get("authority_ref") or "").strip()),
        str(row.get("source_domain") or "") == "user_correction",
        float(row.get("confidence_score") or 0.0),
        float(row.get("updated_at") or 0.0),
        assertion_id,
    )


def _is_current_independent_assertion(
    row: Mapping[str, Any],
    *,
    now: float,
    pending_target_ids: set[str],
) -> bool:
    authority_ref = row.get("authority_ref")
    if has_correction_owner(authority_ref) or str(authority_ref or "").startswith("forget:"):
        return False
    valid_from = row.get("valid_from")
    if valid_from is None:
        valid_from = row.get("first_inferred_at")
    if valid_from is not None and float(valid_from) > now:
        return False
    expires_at = row.get("expires_at")
    if expires_at is not None and float(expires_at) <= now:
        return False
    assertion_id = str(row["assertion_id"])
    pending_target = assertion_id in pending_target_ids
    valid_to = row.get("valid_to")
    if valid_to is not None and float(valid_to) <= now and not pending_target:
        return False
    status = str(row.get("status") or "active")
    if status == "superseded":
        return valid_to is not None and (float(valid_to) > now or pending_target)
    return status not in _UNIQUE_INDEX_EXCLUDED_STATUSES and status != "invalidated"


async def _merge_same_claim_evidence(
    db: aiosqlite.Connection,
    *,
    winner: Mapping[str, Any],
    loser: Mapping[str, Any],
    winner_identity: Mapping[str, str],
    loser_identity: Mapping[str, str],
    forgotten_event_ids: set[str],
    now: float,
) -> None:
    if winner_identity["claim_fingerprint"] != loser_identity["claim_fingerprint"]:
        return
    async with db.execute(
        "SELECT * FROM tom_trait_assertions WHERE assertion_id = ?",
        (winner["assertion_id"],),
    ) as cursor:
        current_winner_row = await cursor.fetchone()
    if current_winner_row is None:
        return
    current_winner = dict(current_winner_row)
    winner_evidence, winner_invalid = decode_evidence_event_ids(
        current_winner.get("evidence_events")
    )
    loser_evidence, loser_invalid = decode_evidence_event_ids(loser.get("evidence_events"))
    if winner_invalid or loser_invalid:
        return
    original_loser_evidence_count = len(loser_evidence)
    winner_evidence = tuple(
        event_id for event_id in winner_evidence if event_id not in forgotten_event_ids
    )
    loser_evidence = tuple(
        event_id for event_id in loser_evidence if event_id not in forgotten_event_ids
    )
    merged = tuple(dict.fromkeys((*winner_evidence, *loser_evidence)))
    merge_loser_metadata = bool(loser_evidence) and len(loser_evidence) == (
        original_loser_evidence_count
    )
    winner_confidence = float(current_winner.get("confidence_score") or 0.0)
    winner_first_inferred_at = float(current_winner.get("first_inferred_at") or 0.0)
    winner_last_validated_at = float(current_winner.get("last_validated_at") or 0.0)
    await db.execute(
        """
        UPDATE tom_trait_assertions
        SET evidence_events = ?, confidence_score = MAX(confidence_score, ?),
            first_inferred_at = MIN(first_inferred_at, ?),
            last_validated_at = MAX(last_validated_at, ?), updated_at = ?
        WHERE assertion_id = ?
        """,
        (
            json.dumps(merged, ensure_ascii=False),
            (
                float(loser.get("confidence_score") or 0.0)
                if merge_loser_metadata
                else winner_confidence
            ),
            (
                float(loser.get("first_inferred_at") or 0.0)
                if merge_loser_metadata
                else winner_first_inferred_at
            ),
            (
                float(loser.get("last_validated_at") or 0.0)
                if merge_loser_metadata
                else winner_last_validated_at
            ),
            now,
            winner["assertion_id"],
        ),
    )


async def _rewrite_assertion_corrections(
    db: aiosqlite.Connection,
    *,
    source_entity_id: str,
    target_entity_id: str,
    resolved_entity_type: str | None,
    affected_assertion_ids: set[str],
) -> list[ClaimGovernanceIdentityRewrite]:
    if not affected_assertion_ids:
        return []
    assertion_ids_json = json.dumps(sorted(affected_assertion_ids), ensure_ascii=False)
    async with db.execute(
        """
        SELECT * FROM memory_corrections
        WHERE target_kind = 'assertion'
          AND target_id IN (SELECT CAST(value AS TEXT) FROM json_each(?))
        UNION
        SELECT * FROM memory_corrections
        WHERE target_kind = 'assertion'
          AND replacement_target_id IN (
              SELECT CAST(value AS TEXT) FROM json_each(?)
          )
        ORDER BY correction_id
        """,
        (assertion_ids_json, assertion_ids_json),
    ) as cursor:
        corrections = await cursor.fetchall()
    rewrites: list[ClaimGovernanceIdentityRewrite] = []
    for correction in corrections:
        before = _decode_object(correction["before_json"], correction["correction_id"])
        directly_affected = (
            str(correction["target_id"]) in affected_assertion_ids
            or str(correction["replacement_target_id"] or "") in affected_assertion_ids
        )
        if not directly_affected:
            continue
        old_before_fingerprint = str(
            before.get("claim_fingerprint") or correction["claim_fingerprint"] or ""
        ).strip()
        old_slot_key = str(before.get("slot_key") or correction["slot_key"])
        before_identity = _project_assertion_identity(
            before,
            source_entity_id=source_entity_id,
            target_entity_id=target_entity_id,
            resolved_entity_type=resolved_entity_type,
        )
        before.update(
            {
                "entity_id": before_identity["entity_id"],
                "entity_type": before_identity["entity_type"],
                "target_entity_id": before_identity["target_entity_id"],
                "target_entity_type": before_identity["target_entity_type"],
                "slot_key": before_identity["slot_key"],
                "claim_fingerprint": before_identity["claim_fingerprint"],
            }
        )
        if str(correction["target_id"]) in affected_assertion_ids:
            async with db.execute(
                """
                SELECT evidence_events, confidence_score,
                       first_inferred_at, last_validated_at
                FROM tom_trait_assertions
                WHERE assertion_id = ?
                """,
                (correction["target_id"],),
            ) as cursor:
                current_target = await cursor.fetchone()
            if current_target is not None:
                before.update(
                    {
                        "evidence_events": current_target["evidence_events"],
                        "confidence_score": current_target["confidence_score"],
                        "first_inferred_at": current_target["first_inferred_at"],
                        "last_validated_at": current_target["last_validated_at"],
                    }
                )
        if old_before_fingerprint:
            rewrites.append(
                ClaimGovernanceIdentityRewrite(
                    old_claim_fingerprint=old_before_fingerprint,
                    new_claim_fingerprint=before_identity["claim_fingerprint"],
                    new_semantic_fingerprint=before_identity["semantic_fingerprint"],
                )
            )
        replacement = _decode_object(
            correction["replacement_json"],
            correction["correction_id"],
            allow_none=True,
        )
        replacement_fingerprint: str | None = None
        replacement_semantic: str | None = None
        old_replacement_fingerprint: str | None = None
        if replacement is not None and replacement.get("value") is not None:
            replacement_scope = replacement.get("scope")
            if not isinstance(replacement_scope, Mapping):
                replacement_scope = {}
            replacement_fingerprint = assertion_claim_fingerprint(
                slot_key_value=before_identity["slot_key"],
                trait_value=replacement["value"],
                scope_key_value=scope_key(replacement_scope),
            )
            old_replacement_fingerprint = assertion_claim_fingerprint(
                slot_key_value=old_slot_key,
                trait_value=replacement["value"],
                scope_key_value=scope_key(replacement_scope),
            )
            replacement_semantic = assertion_claim_fingerprint(
                slot_key_value=before_identity["slot_key"],
                trait_value=replacement["value"],
            )
        await db.execute(
            """
            UPDATE memory_corrections
            SET slot_key = ?, claim_fingerprint = ?, before_json = ?
            WHERE correction_id = ?
            """,
            (
                before_identity["slot_key"],
                before_identity["claim_fingerprint"],
                _encode_object(before),
                correction["correction_id"],
            ),
        )
        async with db.execute(
            "SELECT * FROM memory_correction_rules WHERE correction_id = ?",
            (correction["correction_id"],),
        ) as cursor:
            rules = await cursor.fetchall()
        for rule in rules:
            old_rule_fingerprint = str(rule["claim_fingerprint"] or "").strip()
            is_authoritative = str(rule["rule_kind"]) == "authoritative_slot"
            represents_replacement = bool(
                replacement_fingerprint is not None
                and old_replacement_fingerprint is not None
                and old_rule_fingerprint == old_replacement_fingerprint
            )
            new_rule_fingerprint = (
                replacement_fingerprint
                if (is_authoritative or represents_replacement)
                and replacement_fingerprint is not None
                else before_identity["claim_fingerprint"]
            )
            new_semantic_fingerprint = (
                replacement_semantic
                if (is_authoritative or represents_replacement) and replacement_semantic is not None
                else before_identity["semantic_fingerprint"]
            )
            await db.execute(
                """
                UPDATE memory_correction_rules
                SET slot_key = ?, claim_fingerprint = ?
                WHERE rule_id = ?
                """,
                (before_identity["slot_key"], new_rule_fingerprint, rule["rule_id"]),
            )
            if old_rule_fingerprint:
                rewrites.append(
                    ClaimGovernanceIdentityRewrite(
                        old_claim_fingerprint=old_rule_fingerprint,
                        new_claim_fingerprint=new_rule_fingerprint,
                        new_semantic_fingerprint=new_semantic_fingerprint,
                    )
                )
    return rewrites


async def _load_catalog_entity_type(
    db: aiosqlite.Connection,
    entity_id: str,
) -> str | None:
    async with db.execute(
        "SELECT entity_type FROM entity_catalog WHERE entity_id = ?",
        (entity_id,),
    ) as cursor:
        row = await cursor.fetchone()
    if row is None:
        return None
    normalized = str(row[0] or "").strip()
    return normalized or None


def _decode_object(
    value: Any,
    correction_id: Any,
    *,
    allow_none: bool = False,
) -> dict[str, Any] | None:
    if value is None and allow_none:
        return None
    try:
        parsed = json.loads(str(value))
    except (TypeError, ValueError, json.JSONDecodeError) as exc:
        raise ValueError(f"Correction payload is invalid: {correction_id}") from exc
    if not isinstance(parsed, dict):
        raise ValueError(f"Correction payload is not an object: {correction_id}")
    return parsed


def _encode_object(value: Mapping[str, Any]) -> str:
    return json.dumps(
        dict(value),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )


__all__ = ["rekey_assertion_entity_identity"]
