"""Reconcile correction lineages after user-driven memory forgetting."""

from __future__ import annotations

import json
from collections import deque
from collections.abc import Iterable, Mapping
from typing import Any

import aiosqlite

from ..graph.versions import append_knowledge_graph_version
from .relationship_conflict_effects import restore_relationship_conflict_effects
from .relationship_service import restore_relationship_snapshot_on_connection
from .service import restore_assertion_snapshot_on_connection
from .forget_governance import (
    ForgottenClaim,
    link_correction_forget_barrier,
    record_forget_claim_rules,
)
from .models import CorrectionKind, CorrectionTargetKind, MemoryCorrection


async def revert_corrections_for_forgotten_source_events(
    db: aiosqlite.Connection,
    *,
    event_ids: Iterable[str],
    now: float,
) -> tuple[str, ...]:
    """Withdraw active correction lineages whose own evidence was deleted."""
    normalized = tuple(
        dict.fromkeys(str(event_id).strip() for event_id in event_ids if str(event_id).strip())
    )
    if not normalized:
        return ()
    event_json = json.dumps(normalized, ensure_ascii=False, separators=(",", ":"))
    db.row_factory = aiosqlite.Row
    async with db.execute(
        """
        SELECT * FROM memory_corrections
        WHERE state = 'active' AND transition_cancelled_at IS NULL
          AND source_event_id IN (
              SELECT CAST(value AS TEXT) FROM json_each(?)
          )
        ORDER BY created_at, correction_id
        """,
        (event_json,),
    ) as cursor:
        source_rows = [dict(row) for row in await cursor.fetchall()]
    if not source_rows:
        return ()

    affected_rows = sorted(
        source_rows,
        key=lambda row: (float(row["created_at"]), str(row["correction_id"])),
    )
    affected_replacement_ids = {
        str(row["replacement_target_id"])
        for row in affected_rows
        if row.get("replacement_target_id") is not None
    }
    roots = [row for row in source_rows if str(row["target_id"]) not in affected_replacement_ids]
    subject_keys: set[str] = set()

    for row in reversed(affected_rows):
        correction = MemoryCorrection.from_row(row)
        subject_keys.update(_correction_subject_keys(correction))
        replacement_id = correction.replacement_target_id
        if correction.target_kind == CorrectionTargetKind.ASSERTION:
            if replacement_id:
                await db.execute(
                    """
                    UPDATE tom_trait_assertions
                    SET status = 'archived', valid_to = COALESCE(valid_to, ?),
                        updated_at = ?
                    WHERE assertion_id = ?
                    """,
                    (now, now, replacement_id),
                )
        else:
            await restore_relationship_conflict_effects(
                db,
                correction_id=correction.correction_id,
                replacement_id=replacement_id,
                now=now,
            )
            if replacement_id and replacement_id != correction.target_id:
                await db.execute(
                    """
                    UPDATE knowledge_graph
                    SET status = 'archived', status_reason = CASE
                            WHEN status_reason = 'user_forget' THEN status_reason
                            ELSE 'correction_cancelled'
                        END,
                        valid_to = COALESCE(valid_to, ?), updated_at = ?
                    WHERE triple_id = ?
                    """,
                    (now, now, replacement_id),
                )
                await append_knowledge_graph_version(
                    db,
                    triple_id=replacement_id,
                    correction_id=correction.correction_id,
                    created_at=now,
                )
        await db.execute(
            "UPDATE memory_correction_rules SET active = 0 WHERE correction_id = ?",
            (correction.correction_id,),
        )
        await db.execute(
            """
            UPDATE memory_corrections
            SET state = 'reverted', reverted_at = ?,
                reverted_by = 'system:forgotten_source_event'
            WHERE correction_id = ? AND state = 'active'
            """,
            (now, correction.correction_id),
        )

    for row in roots:
        correction = MemoryCorrection.from_row(row)
        restorable = await _nearest_restorable_ancestor(
            db,
            target_kind=correction.target_kind,
            correction=correction,
        )
        if restorable is None:
            continue
        if await _has_other_current_claim(
            db,
            target_kind=restorable.target_kind,
            correction=restorable,
            effective_at=now,
        ):
            continue
        if restorable.target_kind == CorrectionTargetKind.ASSERTION:
            await restore_assertion_snapshot_on_connection(
                db,
                assertion_id=restorable.target_id,
                before=restorable.before,
                now=now,
            )
        else:
            await restore_relationship_snapshot_on_connection(
                db,
                triple_id=restorable.target_id,
                before=restorable.before,
                now=now,
            )
            await append_knowledge_graph_version(
                db,
                triple_id=restorable.target_id,
                correction_id=restorable.correction_id,
                created_at=now,
            )
    return tuple(sorted(subject_keys))


async def apply_correction_forget_barriers(
    db: aiosqlite.Connection,
    *,
    forgotten_assertions: Mapping[str, ForgottenClaim],
    forgotten_edges: Mapping[str, ForgottenClaim],
    now: float,
    permanently_block_claims: bool,
    cancel_reason: str,
    forget_kind: str,
    effective_from: float | None,
    effective_to: float | None,
    assertion_event_ids_by_record: Mapping[str, Iterable[str]] | None = None,
    edge_event_ids_by_record: Mapping[str, Iterable[str]] | None = None,
) -> None:
    """Persist forget barriers and reconcile affected correction lineages."""
    for target_kind, forgotten_claims, event_ids_by_record in (
        (
            CorrectionTargetKind.ASSERTION,
            forgotten_assertions,
            assertion_event_ids_by_record,
        ),
        (CorrectionTargetKind.EDGE, forgotten_edges, edge_event_ids_by_record),
    ):
        if not forgotten_claims:
            continue
        rule_ids = await record_forget_claim_rules(
            db,
            target_kind=target_kind,
            claims=forgotten_claims,
            forget_kind=forget_kind,
            effective_from=effective_from,
            effective_to=effective_to,
            created_at=now,
            event_ids_by_record=event_ids_by_record,
        )
        corrections = await _affected_active_corrections(
            db,
            target_kind=target_kind,
            record_ids=tuple(dict.fromkeys(claim.record_id for claim in forgotten_claims.values())),
        )
        cancellation_seeds: dict[str, tuple[dict[str, Any], set[str]]] = {}
        for correction in corrections:
            correction_id = str(correction["correction_id"])
            target_id = str(correction["target_id"])
            replacement_id = str(correction["replacement_target_id"] or "")
            applicable_claim_keys = {
                claim_key
                for claim_key, claim in forgotten_claims.items()
                if claim.record_id in {target_id, replacement_id}
                and _correction_lineage_overlaps_forget(
                    correction,
                    record_id=claim.record_id,
                    forget_kind=forget_kind,
                    effective_from=effective_from,
                    effective_to=effective_to,
                )
            }
            applicable_rule_ids = {
                rule_ids[claim_key] for claim_key in applicable_claim_keys if claim_key in rule_ids
            }
            await link_correction_forget_barrier(
                db,
                correction_id=correction_id,
                rule_ids=applicable_rule_ids,
                created_at=now,
            )
            if permanently_block_claims:
                await _convert_matching_rules_to_permanent_blocks(
                    db,
                    correction_id=correction_id,
                    claim_fingerprints={
                        forgotten_claims[claim_key].claim_fingerprint
                        for claim_key in applicable_claim_keys
                        if forgotten_claims[claim_key].claim_fingerprint
                    },
                )

            if str(correction["correction_kind"]) != CorrectionKind.SITUATION_CHANGED.value:
                continue
            transition_applied = correction.get("transition_applied_at") is not None
            transition_fully_forgotten = False
            for claim_key in applicable_claim_keys:
                claim = forgotten_claims[claim_key]
                forgets_replacement = bool(replacement_id) and claim.record_id == replacement_id
                forgets_pending_target = not transition_applied and claim.record_id == str(
                    correction["target_id"]
                )
                if not forgets_replacement and not forgets_pending_target:
                    continue
                if await _claim_is_fully_forgotten(
                    db,
                    target_kind=target_kind,
                    record_id=replacement_id,
                    claim_fingerprint=claim.claim_fingerprint,
                ):
                    transition_fully_forgotten = True
                    break
            if not transition_fully_forgotten:
                continue
            cancellation_seeds[correction_id] = (correction, applicable_rule_ids)

        await _cancel_forgotten_transition_chains(
            db,
            target_kind=target_kind,
            seeds=cancellation_seeds,
            now=now,
            cancel_reason=cancel_reason,
        )


async def _affected_active_corrections(
    db: aiosqlite.Connection,
    *,
    target_kind: CorrectionTargetKind,
    record_ids: tuple[str, ...],
) -> list[dict[str, Any]]:
    if not record_ids:
        return []
    record_ids_json = json.dumps(record_ids, ensure_ascii=False, separators=(",", ":"))
    db.row_factory = aiosqlite.Row
    async with db.execute(
        """
        SELECT corrections.*
        FROM memory_corrections AS corrections
        JOIN (
            SELECT correction_id
            FROM memory_corrections
            WHERE state = 'active' AND target_kind = ?
              AND transition_cancelled_at IS NULL
              AND target_id IN (SELECT CAST(value AS TEXT) FROM json_each(?))
            UNION
            SELECT correction_id
            FROM memory_corrections
            WHERE state = 'active' AND target_kind = ?
              AND transition_cancelled_at IS NULL
              AND replacement_target_id IN (
                  SELECT CAST(value AS TEXT) FROM json_each(?)
              )
        ) AS matched USING(correction_id)
        ORDER BY corrections.created_at, corrections.correction_id
        """,
        (target_kind.value, record_ids_json, target_kind.value, record_ids_json),
    ) as cursor:
        return [dict(row) for row in await cursor.fetchall()]


async def _convert_matching_rules_to_permanent_blocks(
    db: aiosqlite.Connection,
    *,
    correction_id: str,
    claim_fingerprints: set[str],
) -> None:
    if not claim_fingerprints:
        return
    fingerprints_json = json.dumps(
        sorted(claim_fingerprints),
        ensure_ascii=False,
        separators=(",", ":"),
    )
    await db.execute(
        """
        UPDATE memory_correction_rules
        SET rule_kind = 'block_claim', effective_from = NULL, effective_to = NULL
        WHERE correction_id = ? AND active = 1
          AND claim_fingerprint IN (
              SELECT CAST(value AS TEXT) FROM json_each(?)
          )
        """,
        (correction_id, fingerprints_json),
    )


async def _cancel_forgotten_transition_chains(
    db: aiosqlite.Connection,
    *,
    target_kind: CorrectionTargetKind,
    seeds: Mapping[str, tuple[dict[str, Any], set[str]]],
    now: float,
    cancel_reason: str,
) -> None:
    """Invalidate forgotten transitions and cascade only through pending successors."""
    if not seeds:
        return
    seed_ids_json = json.dumps(sorted(seeds), ensure_ascii=False, separators=(",", ":"))
    async with db.execute(
        """
        WITH RECURSIVE descendants(correction_id) AS (
            SELECT CAST(value AS TEXT) FROM json_each(?)
            UNION
            SELECT successor.correction_id
            FROM memory_corrections AS successor
            JOIN memory_corrections AS predecessor
              ON predecessor.replacement_target_id = successor.target_id
            JOIN descendants
              ON descendants.correction_id = predecessor.correction_id
            WHERE successor.state = 'active'
              AND successor.target_kind = ?
              AND successor.correction_kind = 'situation_changed'
              AND successor.transition_cancelled_at IS NULL
              AND successor.transition_applied_at IS NULL
        )
        SELECT corrections.*
        FROM memory_corrections AS corrections
        JOIN descendants USING(correction_id)
        ORDER BY corrections.created_at, corrections.correction_id
        """,
        (seed_ids_json, target_kind.value),
    ) as cursor:
        transitions = [dict(row) for row in await cursor.fetchall()]
    by_target: dict[str, list[dict[str, Any]]] = {}
    for transition in transitions:
        by_target.setdefault(str(transition["target_id"]), []).append(transition)

    cancelled: dict[str, dict[str, Any]] = {}
    barrier_ids_by_correction: dict[str, set[str]] = {}
    pending: deque[tuple[dict[str, Any], set[str]]] = deque()
    for correction, barrier_ids in seeds.values():
        pending.append((dict(correction), set(barrier_ids)))
    while pending:
        correction, inherited_barrier_ids = pending.popleft()
        correction_id = str(correction["correction_id"])
        existing_ids = barrier_ids_by_correction.setdefault(correction_id, set())
        new_ids = inherited_barrier_ids - existing_ids
        existing_ids.update(inherited_barrier_ids)
        first_visit = correction_id not in cancelled
        cancelled[correction_id] = correction
        if not first_visit and not new_ids:
            continue
        replacement_id = str(correction.get("replacement_target_id") or "")
        if not replacement_id:
            continue
        for successor in by_target.get(replacement_id, ()):
            if successor.get("transition_applied_at") is not None:
                continue
            pending.append((successor, set(inherited_barrier_ids)))

    cancelled_rows = sorted(
        cancelled.values(),
        key=lambda row: (float(row["created_at"]), str(row["correction_id"])),
    )
    replacement_ids = {
        str(row["replacement_target_id"])
        for row in cancelled_rows
        if row.get("replacement_target_id") is not None
    }
    roots = [row for row in cancelled_rows if str(row["target_id"]) not in replacement_ids]

    for correction in reversed(cancelled_rows):
        correction_id = str(correction["correction_id"])
        result = await db.execute(
            """
            UPDATE memory_corrections
            SET transition_cancelled_at = ?, transition_cancel_reason = ?
            WHERE correction_id = ? AND transition_cancelled_at IS NULL
            """,
            (now, cancel_reason, correction_id),
        )
        if not result.rowcount:
            continue
        await db.execute(
            "UPDATE memory_correction_rules SET active = 0 WHERE correction_id = ?",
            (correction_id,),
        )
        await link_correction_forget_barrier(
            db,
            correction_id=correction_id,
            rule_ids=barrier_ids_by_correction.get(correction_id, ()),
            created_at=now,
        )
        replacement_id = str(correction.get("replacement_target_id") or "")
        if replacement_id:
            await _archive_cancelled_replacement(
                db,
                target_kind=target_kind,
                replacement_id=replacement_id,
                correction_id=correction_id,
                now=now,
            )

    for root in roots:
        restorable = await _nearest_restorable_ancestor(
            db,
            target_kind=target_kind,
            correction=MemoryCorrection.from_row(root),
        )
        if restorable is not None:
            await _restore_transition_root(
                db,
                target_kind=target_kind,
                correction=restorable,
                now=now,
            )


async def _claim_is_fully_forgotten(
    db: aiosqlite.Connection,
    *,
    target_kind: CorrectionTargetKind,
    record_id: str,
    claim_fingerprint: str,
) -> bool:
    if target_kind == CorrectionTargetKind.ASSERTION:
        query = """
            SELECT status, authority_ref, claim_fingerprint
            FROM tom_trait_assertions WHERE assertion_id = ?
        """
    else:
        query = """
            SELECT status, status_reason, authority_ref, claim_fingerprint
            FROM knowledge_graph WHERE triple_id = ?
        """
    async with db.execute(query, (record_id,)) as cursor:
        row = await cursor.fetchone()
    if row is None:
        return True
    if str(row[-1] or "") != str(claim_fingerprint or ""):
        return False
    if target_kind == CorrectionTargetKind.ASSERTION:
        return str(row[0]) == "archived" and str(row[1] or "").startswith("forget:")
    return str(row[0]) == "archived" and (
        str(row[1] or "") == "user_forget" or str(row[2] or "").startswith("forget:")
    )


async def _nearest_restorable_ancestor(
    db: aiosqlite.Connection,
    *,
    target_kind: CorrectionTargetKind,
    correction: MemoryCorrection,
) -> MemoryCorrection | None:
    visited: set[str] = set()
    current = correction
    while current.target_id not in visited:
        visited.add(current.target_id)
        if await _claim_can_be_restored(
            db,
            target_kind=target_kind,
            record_id=current.target_id,
        ):
            return current
        async with db.execute(
            """
            SELECT * FROM memory_corrections
            WHERE target_kind = ?
              AND replacement_target_id = ?
            ORDER BY COALESCE(effective_at, created_at) DESC,
                     created_at DESC, correction_id DESC
            LIMIT 1
            """,
            (target_kind.value, current.target_id),
        ) as cursor:
            predecessor = await cursor.fetchone()
        if predecessor is None:
            return None
        current = MemoryCorrection.from_row(dict(predecessor))
    return None


async def _claim_can_be_restored(
    db: aiosqlite.Connection,
    *,
    target_kind: CorrectionTargetKind,
    record_id: str,
) -> bool:
    if target_kind == CorrectionTargetKind.ASSERTION:
        async with db.execute(
            """
            SELECT status, authority_ref
            FROM tom_trait_assertions WHERE assertion_id = ?
            """,
            (record_id,),
        ) as cursor:
            row = await cursor.fetchone()
        if row is None or str(row[1] or "").startswith("forget:"):
            return False
        return True
    async with db.execute(
        """
        SELECT status, status_reason, authority_ref
        FROM knowledge_graph WHERE triple_id = ?
        """,
        (record_id,),
    ) as cursor:
        row = await cursor.fetchone()
    if row is None:
        return False
    if str(row[1] or "") == "user_forget" or str(row[2] or "").startswith("forget:"):
        return False
    return True


async def _archive_cancelled_replacement(
    db: aiosqlite.Connection,
    *,
    target_kind: CorrectionTargetKind,
    replacement_id: str,
    correction_id: str,
    now: float,
) -> None:
    if target_kind == CorrectionTargetKind.ASSERTION:
        await db.execute(
            """
            UPDATE tom_trait_assertions
            SET status = 'archived', valid_to = COALESCE(valid_to, valid_from),
                updated_at = ?
            WHERE assertion_id = ?
            """,
            (now, replacement_id),
        )
        return
    await db.execute(
        """
        UPDATE knowledge_graph
        SET status = 'archived',
            status_reason = CASE
                WHEN status_reason = 'user_forget' THEN status_reason
                ELSE 'correction_cancelled'
            END,
            valid_to = COALESCE(valid_to, valid_from), updated_at = ?
        WHERE triple_id = ?
        """,
        (now, replacement_id),
    )
    await append_knowledge_graph_version(
        db,
        triple_id=replacement_id,
        correction_id=correction_id,
        created_at=now,
    )


async def _restore_transition_root(
    db: aiosqlite.Connection,
    *,
    target_kind: CorrectionTargetKind,
    correction: MemoryCorrection,
    now: float,
) -> None:
    if await _has_other_current_claim(
        db,
        target_kind=target_kind,
        correction=correction,
        effective_at=now,
    ):
        return
    if target_kind == CorrectionTargetKind.ASSERTION:
        await db.execute(
            """
            UPDATE tom_trait_assertions
            SET status = ?, superseded_by = ?, superseded_at = ?,
                valid_to = ?, updated_at = ?
            WHERE assertion_id = ?
            """,
            (
                str(correction.before.get("status") or "stable"),
                correction.before.get("superseded_by"),
                correction.before.get("superseded_at"),
                correction.before.get("valid_to"),
                now,
                correction.target_id,
            ),
        )
        return
    await db.execute(
        """
        UPDATE knowledge_graph
        SET status = ?, status_reason = ?, deprecated_by = ?,
            deprecated_at = ?, valid_to = ?, updated_at = ?
        WHERE triple_id = ?
        """,
        (
            str(correction.before.get("status") or "active"),
            correction.before.get("status_reason"),
            correction.before.get("deprecated_by"),
            correction.before.get("deprecated_at"),
            correction.before.get("valid_to"),
            now,
            correction.target_id,
        ),
    )
    await append_knowledge_graph_version(
        db,
        triple_id=correction.target_id,
        correction_id=correction.correction_id,
        created_at=now,
    )


async def _has_other_current_claim(
    db: aiosqlite.Connection,
    *,
    target_kind: CorrectionTargetKind,
    correction: MemoryCorrection,
    effective_at: float,
) -> bool:
    scope_key = str(correction.before.get("scope_key") or "global")
    if target_kind == CorrectionTargetKind.ASSERTION:
        query = """
            SELECT 1 FROM tom_trait_assertions
            WHERE slot_key = ? AND scope_key = ? AND assertion_id != ?
              AND status NOT IN (
                  'superseded', 'archived', 'expired', 'user_rejected', 'shadow'
              )
              AND COALESCE(valid_from, first_inferred_at) <= ?
              AND (valid_to IS NULL OR valid_to > ?)
            LIMIT 1
        """
    else:
        query = """
            SELECT 1 FROM knowledge_graph
            WHERE slot_key = ? AND scope_key = ? AND triple_id != ?
              AND status = 'active'
              AND COALESCE(valid_from, first_observed_at) <= ?
              AND (valid_to IS NULL OR valid_to > ?)
              AND (expires_at IS NULL OR expires_at > ?)
            LIMIT 1
        """
    args: tuple[object, ...] = (
        correction.slot_key,
        scope_key,
        correction.target_id,
        effective_at,
        effective_at,
    )
    if target_kind == CorrectionTargetKind.EDGE:
        args = (*args, effective_at)
    async with db.execute(query, args) as cursor:
        return await cursor.fetchone() is not None


def _correction_lineage_overlaps_forget(
    correction: Mapping[str, Any],
    *,
    record_id: str,
    forget_kind: str,
    effective_from: float | None,
    effective_to: float | None,
) -> bool:
    if forget_kind in {"entity", "event"}:
        return True
    if effective_from is None or effective_to is None:
        return False
    transition_at = float(correction["effective_at"] or correction["created_at"])
    if record_id == str(correction["target_id"]):
        return float(effective_from) < transition_at
    return (
        correction["replacement_target_id"] is not None
        and record_id == str(correction["replacement_target_id"])
        and float(effective_to) >= transition_at
    )


async def _target_record_is_forgotten(
    db: aiosqlite.Connection,
    correction: MemoryCorrection,
) -> bool:
    if correction.target_kind == CorrectionTargetKind.ASSERTION:
        query = "SELECT authority_ref FROM tom_trait_assertions WHERE assertion_id = ?"
    else:
        query = "SELECT status_reason FROM knowledge_graph WHERE triple_id = ?"
    async with db.execute(query, (correction.target_id,)) as cursor:
        row = await cursor.fetchone()
    marker = str(row[0] or "") if row is not None else ""
    if correction.target_kind == CorrectionTargetKind.ASSERTION:
        return marker.startswith("forget:")
    return marker == "user_forget"


def _correction_subject_keys(correction: MemoryCorrection) -> tuple[str, ...]:
    before = correction.before
    if correction.target_kind == CorrectionTargetKind.ASSERTION:
        candidates = (before.get("entity_id"), before.get("target_entity_id"))
    else:
        candidates = (before.get("subject_id"), before.get("object_id"))
    return tuple(
        dict.fromkeys(
            str(candidate).strip()
            for candidate in candidates
            if str(candidate or "").strip()
            and (
                correction.target_kind == CorrectionTargetKind.ASSERTION
                or candidate == before.get("subject_id")
                or ":" in str(candidate)
            )
        )
    )


__all__ = [
    "apply_correction_forget_barriers",
    "revert_corrections_for_forgotten_source_events",
]
