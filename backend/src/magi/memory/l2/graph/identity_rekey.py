"""Transactional identity rewrites for governed L2 relationships."""

from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

import aiosqlite

from ..corrections.fingerprints import (
    relationship_claim_fingerprint,
    relationship_slot_key,
    relationship_triple_id,
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
from ..corrections.models import CorrectionTargetKind, MemoryCorrection
from ..corrections.ownership import has_correction_owner
from ..corrections.revert_blocks import (
    IDENTITY_MERGE_REVERT_BLOCK,
    LINEAGE_COLLISION_REVERT_BLOCK,
    block_correction_reverts,
    block_colliding_correction_lineages,
)
from ..graph_conflicts import (
    GraphConflictRule,
    build_graph_conflict_matrix,
    relationship_predicate_slot,
)
from ..storage.utils import max_evidence_event_ids
from .versions import append_knowledge_graph_version


def _merge_evidence_json(left: str, right: str) -> str:
    """Merge event-id arrays without coupling graph identity to maintenance."""
    try:
        left_items = json.loads(left or "[]")
    except (TypeError, ValueError, json.JSONDecodeError):
        left_items = []
    if not isinstance(left_items, list):
        left_items = []
    try:
        right_items = json.loads(right or "[]")
    except (TypeError, ValueError, json.JSONDecodeError):
        right_items = []
    if not isinstance(right_items, list):
        right_items = []
    merged = list(
        dict.fromkeys(str(item) for item in [*left_items, *right_items] if str(item).strip())
    )
    cap = max_evidence_event_ids()
    if len(merged) > cap:
        merged = merged[-cap:]
    return json.dumps(merged, ensure_ascii=False)


@dataclass(frozen=True, slots=True)
class RelationshipIdentityRekeyResult:
    """Describe one completed current-edge identity rewrite."""

    rewritten: bool
    merged: bool
    triple_id: str | None
    invalidated_vector_ids: frozenset[str]
    rewritten_reference_ids: tuple[tuple[str, str], ...]


async def rekey_relationship_identity(
    db: aiosqlite.Connection,
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
        frozenset({*affected_ids, target_triple_id}) if content_identity_changed else frozenset()
    )
    return RelationshipIdentityRekeyResult(
        rewritten=duplicate is None,
        merged=duplicate is not None,
        triple_id=target_triple_id,
        invalidated_vector_ids=invalidated_ids,
        rewritten_reference_ids=tuple(sorted(id_map.items())),
    )


async def _reconcile_rewritten_corrections(
    db: aiosqlite.Connection,
    *,
    correction_ids: set[str],
    now: float,
) -> None:
    """Reapply active correction semantics after relationship identities move."""
    if not correction_ids:
        return
    from ..corrections.relationship_conflict_effects import (
        apply_relationship_conflict_effects,
        load_relationship_graph_conflict_rules,
        restore_relationship_conflict_effects,
    )
    from ..corrections.relationship_service import (
        restore_relationship_snapshot_on_connection,
    )

    graph_conflict_rules: dict[str, GraphConflictRule] | None = None
    for correction_id in sorted(correction_ids):
        async with db.execute(
            "SELECT * FROM memory_corrections WHERE correction_id = ?",
            (correction_id,),
        ) as cursor:
            correction = await cursor.fetchone()
        if (
            correction is None
            or str(correction["state"]) != "active"
            or correction["transition_cancelled_at"] is not None
        ):
            continue
        model = MemoryCorrection.from_row(dict(correction))
        target_id = str(correction["target_id"])
        replacement_id = str(correction["replacement_target_id"] or "")
        independent_target = await _independent_relationship_survivor(
            db,
            triple_id=target_id,
            now=now,
        )
        if (
            not replacement_id
            and model.correction_kind.value == "record_error"
            and model.replacement is None
            and independent_target is not None
        ):
            await resolve_correction_after_identity_merge(
                db,
                correction_id=correction_id,
                resolved_at=now,
            )
            continue
        if replacement_id and target_id == replacement_id:
            await restore_relationship_conflict_effects(
                db,
                correction_id=correction_id,
                replacement_id=replacement_id,
                now=now,
            )
            if independent_target is None:
                await restore_relationship_snapshot_on_connection(
                    db,
                    triple_id=target_id,
                    before=model.before,
                    now=now,
                )
                await append_knowledge_graph_version(
                    db,
                    triple_id=target_id,
                    correction_id=correction_id,
                    created_at=now,
                )
            await resolve_correction_after_identity_merge(
                db,
                correction_id=correction_id,
                resolved_at=now,
            )
            continue
        if not replacement_id:
            continue
        replacement_row = await _independent_relationship_survivor(
            db,
            triple_id=replacement_id,
            now=now,
        )
        if (
            replacement_row is not None
            and str(model.before.get("slot_key") or correction["slot_key"])
            == str(replacement_row["slot_key"])
            and str(model.before.get("scope_key") or "global")
            == str(replacement_row["scope_key"] or "global")
        ):
            await block_correction_reverts(
                db,
                correction_ids={correction_id},
                block_reason=IDENTITY_MERGE_REVERT_BLOCK,
                created_at=now,
            )
        if not _correction_transition_is_committed(correction):
            continue
        replacement = _decode_payload(
            correction["replacement_json"],
            correction_id,
            allow_none=True,
        )
        if replacement is None or not await _relationship_is_current_at(
            db,
            triple_id=replacement_id,
            now=now,
        ):
            continue
        if graph_conflict_rules is None:
            graph_conflict_rules = await load_relationship_graph_conflict_rules(db)
        await apply_relationship_conflict_effects(
            db,
            replacement=replacement,
            correction_id=correction_id,
            graph_conflict_rules=graph_conflict_rules,
            effective_at=now,
            now=now,
        )


def _correction_transition_is_committed(correction: Mapping[str, Any]) -> bool:
    return (
        str(correction["correction_kind"]) != "situation_changed"
        or correction["transition_applied_at"] is not None
    )


async def _relationship_is_current_at(
    db: aiosqlite.Connection,
    *,
    triple_id: str,
    now: float,
) -> bool:
    async with db.execute(
        """
        SELECT status, valid_from, valid_to, expires_at
        FROM knowledge_graph
        WHERE triple_id = ?
        """,
        (triple_id,),
    ) as cursor:
        row = await cursor.fetchone()
    if row is None or str(row["status"]) not in {"active", "deprecated"}:
        return False
    valid_from = float(row["valid_from"]) if row["valid_from"] is not None else -float("inf")
    valid_to = float(row["valid_to"]) if row["valid_to"] is not None else float("inf")
    expires_at = float(row["expires_at"]) if row["expires_at"] is not None else float("inf")
    return valid_from <= now < valid_to and now < expires_at


async def _independent_relationship_survivor(
    db: aiosqlite.Connection,
    *,
    triple_id: str,
    now: float,
) -> Mapping[str, Any] | None:
    row = await _load_edge(db, triple_id)
    if row is None:
        return None
    authority_ref = row["authority_ref"]
    if has_correction_owner(authority_ref):
        return None
    if str(authority_ref or "").startswith("forget:"):
        return None
    if str(row["status_reason"] or "") in {"user_correction", "user_forget"}:
        return None
    if str(row["status"] or "") != "active":
        return None
    if not await _relationship_is_current_at(db, triple_id=triple_id, now=now):
        return None
    return dict(row)


async def rewrite_materialized_relationship_references(
    db: aiosqlite.Connection,
    reference_map: Mapping[str, str],
) -> None:
    """Rewrite derived relationship references once for a completed rekey batch."""
    await _rewrite_materialized_json_references(db, reference_map)


async def relationship_slot_key_on_connection(
    db: aiosqlite.Connection,
    *,
    subject_id: str,
    predicate: str,
    object_id: str,
) -> str:
    """Build the same conflict-aware slot identity used by graph writes."""
    normalized_predicate = str(predicate).strip().upper()
    async with db.execute(
        """
        SELECT predicate, opposite_predicates, opposite_resolution,
               exclusive_group, exclusive_scope, exclusive_resolution
        FROM graph_conflict_rules
        WHERE predicate = ?
        """,
        (normalized_predicate,),
    ) as cursor:
        rule = await cursor.fetchone()
    rules = build_graph_conflict_matrix()
    if rule is not None:
        normalized_rule = GraphConflictRule.from_mapping(dict(rule))
        rules[normalized_rule.predicate] = normalized_rule
    return relationship_slot_key(
        subject_id=subject_id,
        predicate=normalized_predicate,
        object_id=object_id,
        predicate_slot=relationship_predicate_slot(
            rules,
            predicate=normalized_predicate,
            object_id=object_id,
        ),
    )


async def refresh_relationship_governance_history_for_predicate(
    db: aiosqlite.Connection,
    *,
    predicate: str,
) -> None:
    """Refresh historical slots after a persisted conflict rule changes."""
    db.row_factory = aiosqlite.Row
    normalized_predicate = str(predicate).strip().upper()
    governance_rewrites: list[ClaimGovernanceIdentityRewrite] = []
    async with db.execute(
        """
        SELECT * FROM knowledge_graph_versions
        WHERE predicate = ?
        ORDER BY version_id
        """,
        (normalized_predicate,),
    ) as cursor:
        versions = await cursor.fetchall()
    for version in versions:
        old_fingerprint = str(version["claim_fingerprint"] or "").strip()
        slot_key = await relationship_slot_key_on_connection(
            db,
            subject_id=str(version["subject_id"]),
            predicate=normalized_predicate,
            object_id=str(version["object_id"]),
        )
        fingerprint = relationship_claim_fingerprint(
            slot_key_value=slot_key,
            subject_id=str(version["subject_id"]),
            predicate=normalized_predicate,
            object_id=str(version["object_id"]),
            scope_key_value=str(version["scope_key"] or "global"),
        )
        if old_fingerprint:
            governance_rewrites.append(
                ClaimGovernanceIdentityRewrite(
                    old_claim_fingerprint=old_fingerprint,
                    new_claim_fingerprint=fingerprint,
                    new_semantic_fingerprint=relationship_claim_fingerprint(
                        slot_key_value=slot_key,
                        subject_id=str(version["subject_id"]),
                        predicate=normalized_predicate,
                        object_id=str(version["object_id"]),
                    ),
                )
            )
        await db.execute(
            """
            UPDATE knowledge_graph_versions
            SET slot_key = ?, claim_fingerprint = ?
            WHERE version_id = ?
            """,
            (slot_key, fingerprint, version["version_id"]),
        )

    async with db.execute("SELECT * FROM memory_corrections WHERE target_kind = 'edge'") as cursor:
        corrections = await cursor.fetchall()
    for correction in corrections:
        before = _decode_payload(correction["before_json"], correction["correction_id"])
        replacement = _decode_payload(
            correction["replacement_json"],
            correction["correction_id"],
            allow_none=True,
        )
        before_matches = str(before.get("predicate") or "").strip().upper() == normalized_predicate
        replacement_matches = bool(
            replacement is not None
            and str(replacement.get("predicate") or "").strip().upper() == normalized_predicate
        )
        if not before_matches and not replacement_matches:
            continue
        if before_matches:
            old_before_fingerprint = str(before.get("claim_fingerprint") or "").strip()
            await _set_payload_identity(
                db,
                before,
                triple_id=str(before.get("triple_id") or correction["target_id"]),
                subject_id=str(before["subject_id"]),
                predicate=normalized_predicate,
                object_id=str(before["object_id"]),
            )
            if old_before_fingerprint:
                governance_rewrites.append(
                    ClaimGovernanceIdentityRewrite(
                        old_claim_fingerprint=old_before_fingerprint,
                        new_claim_fingerprint=str(before["claim_fingerprint"]),
                        new_semantic_fingerprint=relationship_claim_fingerprint(
                            slot_key_value=str(before["slot_key"]),
                            subject_id=str(before["subject_id"]),
                            predicate=normalized_predicate,
                            object_id=str(before["object_id"]),
                        ),
                    )
                )
        if replacement_matches and replacement is not None:
            old_replacement_fingerprint = str(replacement.get("claim_fingerprint") or "").strip()
            await _set_payload_identity(
                db,
                replacement,
                triple_id=str(
                    replacement.get("triple_id") or correction["replacement_target_id"] or ""
                ),
                subject_id=str(replacement["subject_id"]),
                predicate=normalized_predicate,
                object_id=str(replacement["object_id"]),
            )
            if old_replacement_fingerprint:
                governance_rewrites.append(
                    ClaimGovernanceIdentityRewrite(
                        old_claim_fingerprint=old_replacement_fingerprint,
                        new_claim_fingerprint=str(replacement["claim_fingerprint"]),
                        new_semantic_fingerprint=relationship_claim_fingerprint(
                            slot_key_value=str(replacement["slot_key"]),
                            subject_id=str(replacement["subject_id"]),
                            predicate=normalized_predicate,
                            object_id=str(replacement["object_id"]),
                        ),
                    )
                )
        await db.execute(
            """
            UPDATE memory_corrections
            SET slot_key = ?, claim_fingerprint = ?,
                before_json = ?, replacement_json = ?
            WHERE correction_id = ?
            """,
            (
                str(before.get("slot_key") or correction["slot_key"]),
                str(before.get("claim_fingerprint") or correction["claim_fingerprint"]),
                _encode_payload(before),
                _encode_payload(replacement) if replacement is not None else None,
                correction["correction_id"],
            ),
        )
        await _rewrite_correction_rules(
            db,
            correction=correction,
            before=before,
            replacement=replacement,
        )
    await rewrite_claim_governance_identities(
        db,
        target_kind=CorrectionTargetKind.EDGE,
        rewrites=governance_rewrites,
    )


async def _load_edge(
    db: aiosqlite.Connection,
    triple_id: str,
) -> aiosqlite.Row | None:
    async with db.execute(
        "SELECT * FROM knowledge_graph WHERE triple_id = ?",
        (triple_id,),
    ) as cursor:
        return await cursor.fetchone()


async def _load_identity_duplicate(
    db: aiosqlite.Connection,
    *,
    source_triple_id: str,
    subject_id: str,
    predicate: str,
    object_id: str,
    scope_key: str,
) -> aiosqlite.Row | None:
    async with db.execute(
        """
        SELECT * FROM knowledge_graph
        WHERE subject_id = ? AND predicate = ? AND object_id = ?
          AND scope_key = ? AND triple_id != ?
        ORDER BY triple_id
        LIMIT 1
        """,
        (subject_id, predicate, object_id, scope_key, source_triple_id),
    ) as cursor:
        return await cursor.fetchone()


async def _collect_relationship_governance_rewrites(
    db: aiosqlite.Connection,
    *,
    affected_rows: list[aiosqlite.Row],
    affected_ids: set[str],
    affected_corrections: list[aiosqlite.Row],
    subject_id: str,
    predicate: str,
    object_id: str,
    slot_key: str,
) -> tuple[ClaimGovernanceIdentityRewrite, ...]:
    """Capture every claim identity before relationship rows are rewritten."""
    rewrites: list[ClaimGovernanceIdentityRewrite] = []
    for row in affected_rows:
        _append_relationship_governance_rewrite(
            rewrites,
            old_claim_fingerprint=row["claim_fingerprint"],
            scope_key_value=str(row["scope_key"] or "global"),
            subject_id=subject_id,
            predicate=predicate,
            object_id=object_id,
            slot_key=slot_key,
        )

    placeholders = ", ".join("?" for _ in affected_ids)
    async with db.execute(
        f"""
        SELECT claim_fingerprint, scope_key
        FROM knowledge_graph_versions
        WHERE triple_id IN ({placeholders})
        """,
        tuple(sorted(affected_ids)),
    ) as cursor:
        versions = await cursor.fetchall()
    for version in versions:
        _append_relationship_governance_rewrite(
            rewrites,
            old_claim_fingerprint=version["claim_fingerprint"],
            scope_key_value=str(version["scope_key"] or "global"),
            subject_id=subject_id,
            predicate=predicate,
            object_id=object_id,
            slot_key=slot_key,
        )

    for correction in affected_corrections:
        before = _decode_payload(correction["before_json"], correction["correction_id"])
        replacement = _decode_payload(
            correction["replacement_json"],
            correction["correction_id"],
            allow_none=True,
        )
        for payload, direct in (
            (
                before,
                str(correction["target_id"]) in affected_ids
                or str(before.get("triple_id") or "") in affected_ids,
            ),
            (
                replacement,
                bool(
                    replacement is not None
                    and (
                        str(correction["replacement_target_id"] or "") in affected_ids
                        or str(replacement.get("triple_id") or "") in affected_ids
                    )
                ),
            ),
        ):
            if not direct or payload is None:
                continue
            _append_relationship_governance_rewrite(
                rewrites,
                old_claim_fingerprint=payload.get("claim_fingerprint"),
                scope_key_value=str(payload.get("scope_key") or "global"),
                subject_id=subject_id,
                predicate=predicate,
                object_id=object_id,
                slot_key=slot_key,
            )
    return tuple(rewrites)


async def _load_affected_edge_corrections(
    db: aiosqlite.Connection,
    affected_ids: set[str],
) -> list[aiosqlite.Row]:
    """Load only corrections anchored to the relationship identities being moved."""
    if not affected_ids:
        return []
    placeholders = ", ".join("?" for _ in affected_ids)
    parameters = tuple(sorted(affected_ids))
    # Direct target ids are the correction contract; payload ids are snapshots,
    # not an alternate identity index. Both lookup arms have dedicated indexes.
    async with db.execute(
        f"""
        SELECT * FROM memory_corrections
        WHERE target_kind = 'edge'
          AND target_id IN ({placeholders})
        UNION
        SELECT * FROM memory_corrections
        WHERE target_kind = 'edge'
          AND replacement_target_id IN ({placeholders})
        ORDER BY correction_id
        """,
        (*parameters, *parameters),
    ) as cursor:
        return await cursor.fetchall()


def _append_relationship_governance_rewrite(
    rewrites: list[ClaimGovernanceIdentityRewrite],
    *,
    old_claim_fingerprint: Any,
    scope_key_value: str,
    subject_id: str,
    predicate: str,
    object_id: str,
    slot_key: str,
) -> None:
    old_fingerprint = str(old_claim_fingerprint or "").strip()
    if not old_fingerprint:
        return
    rewrites.append(
        ClaimGovernanceIdentityRewrite(
            old_claim_fingerprint=old_fingerprint,
            new_claim_fingerprint=relationship_claim_fingerprint(
                slot_key_value=slot_key,
                subject_id=subject_id,
                predicate=predicate,
                object_id=object_id,
                scope_key_value=scope_key_value,
            ),
            new_semantic_fingerprint=relationship_claim_fingerprint(
                slot_key_value=slot_key,
                subject_id=subject_id,
                predicate=predicate,
                object_id=object_id,
            ),
        )
    )


async def _write_current_edge(
    db: aiosqlite.Connection,
    *,
    rows: list[aiosqlite.Row],
    target_triple_id: str,
    subject_id: str,
    predicate: str,
    object_id: str,
    slot_key: str,
    claim_fingerprint: str,
    now: float,
    content_identity_changed: bool,
    excluded_evidence_ids: set[str],
) -> None:
    source_ids = {str(row["triple_id"]) for row in rows}
    unrelated = await _load_edge(db, target_triple_id)
    if unrelated is not None and str(unrelated["triple_id"]) not in source_ids:
        raise ValueError(f"Deterministic relationship id is already used: {target_triple_id}")
    winner = await _pick_current_winner(db, rows, now=now)
    final = dict(winner)
    final.update(
        {
            "triple_id": target_triple_id,
            "subject_id": subject_id,
            "predicate": predicate,
            "object_id": object_id,
            "slot_key": slot_key,
            "claim_fingerprint": claim_fingerprint,
        }
    )
    if content_identity_changed:
        final.update(
            {
                "updated_at": now,
                "embedding_status": (
                    "pending" if str(winner["status"] or "active") == "active" else "disabled"
                ),
                "embedding_profile_id": None,
                "last_embedded_at": None,
            }
        )
    if len(rows) > 1:
        forgotten_event_ids = await forgotten_evidence_event_ids_for_claims(
            db,
            target_kind=CorrectionTargetKind.EDGE,
            claim_fingerprints=(str(row["claim_fingerprint"] or "") for row in rows),
        )
        final.update(
            _merged_current_evidence(
                rows,
                forgotten_event_ids=forgotten_event_ids,
                winner_id=str(winner["triple_id"]),
                excluded_evidence_ids=excluded_evidence_ids,
            )
        )
    deprecated_by = final.get("deprecated_by")
    if deprecated_by in source_ids:
        deprecated_by = target_triple_id
    if deprecated_by == target_triple_id:
        deprecated_by = None
    final["deprecated_by"] = deprecated_by

    placeholders = ", ".join("?" for _ in source_ids)
    await db.execute(
        f"DELETE FROM knowledge_graph WHERE triple_id IN ({placeholders})",
        tuple(sorted(source_ids)),
    )
    columns = list(final)
    await db.execute(
        f"INSERT INTO knowledge_graph({', '.join(columns)}) "
        f"VALUES ({', '.join('?' for _ in columns)})",
        tuple(final[column] for column in columns),
    )


async def _pick_current_winner(
    db: aiosqlite.Connection,
    rows: list[aiosqlite.Row],
    *,
    now: float,
) -> aiosqlite.Row:
    correction_times: dict[str, float | None] = {}
    pending_target_ids: set[str] = set()
    for row in rows:
        triple_id = str(row["triple_id"])
        async with db.execute(
            """
            SELECT created_at, target_id, correction_kind, transition_applied_at
            FROM (
                SELECT created_at, target_id, correction_kind, transition_applied_at
                FROM memory_corrections
                WHERE target_kind = 'edge' AND state = 'active'
                  AND transition_cancelled_at IS NULL AND target_id = ?
                UNION ALL
                SELECT created_at, target_id, correction_kind, transition_applied_at
                FROM memory_corrections
                WHERE target_kind = 'edge' AND state = 'active'
                  AND transition_cancelled_at IS NULL
                  AND replacement_target_id = ?
            )
            """,
            (triple_id, triple_id),
        ) as cursor:
            matches = await cursor.fetchall()
        correction_times[triple_id] = max(
            (float(match["created_at"]) for match in matches),
            default=None,
        )
        pending_target_ids.update(
            str(match["target_id"])
            for match in matches
            if str(match["correction_kind"]) == "situation_changed"
            and match["transition_applied_at"] is None
        )

    def rank(row: aiosqlite.Row) -> tuple[Any, ...]:
        triple_id = str(row["triple_id"])
        correction_at = correction_times[triple_id]
        user_governed = correction_at is not None or str(row["status_reason"] or "") in {
            "user_correction",
            "user_forget",
        }
        return (
            _is_current_independent_relationship(
                dict(row),
                now=now,
                pending_target_ids=pending_target_ids,
            ),
            user_governed,
            correction_at or 0.0,
            bool(row["authority_ref"]),
            str(row["status"] or "active") == "active",
            str(row["evidence_class"] or "") == "user_self_report",
            float(row["updated_at"] or 0.0),
            float(row["created_at"] or 0.0),
            triple_id,
        )

    return max(rows, key=rank)


def _is_current_independent_relationship(
    row: Mapping[str, Any],
    *,
    now: float,
    pending_target_ids: set[str],
) -> bool:
    authority_ref = row.get("authority_ref")
    if has_correction_owner(authority_ref) or str(authority_ref or "").startswith("forget:"):
        return False
    if str(row.get("status_reason") or "") == "user_forget":
        return False
    valid_from = row.get("valid_from")
    if valid_from is None:
        valid_from = row.get("first_observed_at")
    if valid_from is not None and float(valid_from) > now:
        return False
    expires_at = row.get("expires_at")
    if expires_at is not None and float(expires_at) <= now:
        return False
    triple_id = str(row["triple_id"])
    valid_to = row.get("valid_to")
    pending_target = triple_id in pending_target_ids
    if valid_to is not None and float(valid_to) <= now and not pending_target:
        return False
    status = str(row.get("status") or "active")
    return status == "active" or (
        status == "deprecated" and valid_to is not None and (float(valid_to) > now or pending_target)
    )


def _merged_current_evidence(
    rows: list[aiosqlite.Row],
    *,
    forgotten_event_ids: set[str],
    winner_id: str,
    excluded_evidence_ids: set[str],
) -> dict[str, Any]:
    evidence = "[]"
    metadata_rows: list[aiosqlite.Row] = []
    for row in rows:
        if (
            str(row["triple_id"]) in excluded_evidence_ids
            and str(row["triple_id"]) != winner_id
        ):
            continue
        raw_evidence = str(row["evidence_event_ids"] or "[]")
        if not forgotten_event_ids:
            metadata_rows.append(row)
            evidence = _merge_evidence_json(evidence, raw_evidence)
            continue
        decoded_evidence, invalid_evidence = decode_evidence_event_ids(raw_evidence)
        normalized_evidence = None if invalid_evidence else list(decoded_evidence)
        retained_evidence = (
            [event_id for event_id in normalized_evidence if event_id not in forgotten_event_ids]
            if normalized_evidence is not None
            else []
        )
        raw_evidence = json.dumps(retained_evidence, ensure_ascii=False)
        evidence = _merge_evidence_json(evidence, raw_evidence)
        forget_marker = str(row["status_reason"] or "") == "user_forget" or str(
            row["authority_ref"] or ""
        ).startswith("forget:")
        if (
            str(row["triple_id"]) == winner_id
            or bool(retained_evidence)
            or (normalized_evidence == [] and not forget_marker)
        ):
            metadata_rows.append(row)
    confirmed = [
        float(row["last_confirmed_at"])
        for row in metadata_rows
        if row["last_confirmed_at"] is not None
    ]
    return {
        "evidence_event_ids": evidence,
        "observation_count": sum(int(row["observation_count"] or 0) for row in metadata_rows),
        "confidence": max(float(row["confidence"] or 0.0) for row in metadata_rows),
        "first_observed_at": min(float(row["first_observed_at"]) for row in metadata_rows),
        "last_observed_at": max(float(row["last_observed_at"]) for row in metadata_rows),
        "last_confirmed_at": max(confirmed) if confirmed else None,
    }


def _rejected_relationship_target_ids(
    corrections: list[aiosqlite.Row],
) -> set[str]:
    """Return correction targets whose rejected evidence must not cross a merge."""
    return {
        str(correction["target_id"])
        for correction in corrections
        if str(correction["state"]) == "active"
        and correction["transition_cancelled_at"] is None
        and str(correction["correction_kind"]) == "record_error"
        and not str(correction["replacement_target_id"] or "").strip()
        and correction["replacement_json"] in (None, "", "null")
    }


def _rejected_relationship_convergence_ids(
    rows: list[aiosqlite.Row],
    *,
    rejected_target_ids: set[str],
    now: float,
) -> set[str]:
    """Return rejected branches that collided with an independent same claim."""
    independent_ids = {
        str(row["triple_id"])
        for row in rows
        if _is_current_independent_relationship(
            dict(row),
            now=now,
            pending_target_ids=set(),
        )
        and str(row["status_reason"] or "") not in {"user_correction", "user_forget"}
    }
    if not independent_ids:
        return set()
    return {
        target_id
        for target_id in rejected_target_ids
        if any(independent_id != target_id for independent_id in independent_ids)
    }


async def _rewrite_versions(
    db: aiosqlite.Connection,
    *,
    affected_ids: set[str],
    target_triple_id: str,
    subject_id: str,
    predicate: str,
    object_id: str,
) -> None:
    placeholders = ", ".join("?" for _ in affected_ids)
    async with db.execute(
        f"SELECT * FROM knowledge_graph_versions WHERE triple_id IN ({placeholders})",
        tuple(sorted(affected_ids)),
    ) as cursor:
        versions = await cursor.fetchall()
    for version in versions:
        scope_key = str(version["scope_key"] or "global")
        slot_key = await relationship_slot_key_on_connection(
            db,
            subject_id=subject_id,
            predicate=predicate,
            object_id=object_id,
        )
        fingerprint = relationship_claim_fingerprint(
            slot_key_value=slot_key,
            subject_id=subject_id,
            predicate=predicate,
            object_id=object_id,
            scope_key_value=scope_key,
        )
        await db.execute(
            """
            UPDATE knowledge_graph_versions
            SET triple_id = ?, subject_id = ?, predicate = ?, object_id = ?,
                slot_key = ?, claim_fingerprint = ?
            WHERE version_id = ?
            """,
            (
                target_triple_id,
                subject_id,
                predicate,
                object_id,
                slot_key,
                fingerprint,
                version["version_id"],
            ),
        )
    await _rebuild_version_chain(db, target_triple_id)


async def _rebuild_version_chain(
    db: aiosqlite.Connection,
    triple_id: str,
) -> None:
    async with db.execute(
        """
        SELECT version_id FROM knowledge_graph_versions
        WHERE triple_id = ?
        ORDER BY created_at, version_id
        """,
        (triple_id,),
    ) as cursor:
        versions = await cursor.fetchall()
    previous: str | None = None
    for version in versions:
        await db.execute(
            "UPDATE knowledge_graph_versions SET previous_version_id = ? WHERE version_id = ?",
            (previous, version["version_id"]),
        )
        previous = str(version["version_id"])


async def _rewrite_current_edge_references(
    db: aiosqlite.Connection,
    id_map: Mapping[str, str],
) -> None:
    for old_id, new_id in id_map.items():
        await db.execute(
            "UPDATE knowledge_graph SET deprecated_by = ? WHERE deprecated_by = ?",
            (new_id, old_id),
        )
        await db.execute(
            "UPDATE knowledge_graph_versions SET authority_ref = ? WHERE authority_ref = ?",
            (new_id, old_id),
        )


async def _rewrite_conflict_effect_references(
    db: aiosqlite.Connection,
    id_map: Mapping[str, str],
) -> None:
    """Keep durable correction side effects aligned with graph identity merges."""
    for old_id, new_id in sorted(id_map.items()):
        await db.execute(
            """
            UPDATE memory_relationship_conflict_effects
            SET replacement_triple_id = ?
            WHERE replacement_triple_id = ?
            """,
            (new_id, old_id),
        )
        await db.execute(
            """
            UPDATE memory_relationship_conflict_effects
            SET pre_deprecated_by = ?
            WHERE pre_deprecated_by = ?
            """,
            (new_id, old_id),
        )
        async with db.execute(
            """
            SELECT * FROM memory_relationship_conflict_effects
            WHERE victim_triple_id = ?
            ORDER BY created_at, effect_id
            """,
            (old_id,),
        ) as cursor:
            source_effects = await cursor.fetchall()
        for source in source_effects:
            async with db.execute(
                """
                SELECT * FROM memory_relationship_conflict_effects
                WHERE correction_id = ? AND victim_triple_id = ?
                  AND effect_id != ?
                ORDER BY created_at, effect_id
                LIMIT 1
                """,
                (source["correction_id"], new_id, source["effect_id"]),
            ) as cursor:
                existing = await cursor.fetchone()
            if existing is None:
                await db.execute(
                    """
                    UPDATE memory_relationship_conflict_effects
                    SET victim_triple_id = ?
                    WHERE effect_id = ?
                    """,
                    (new_id, source["effect_id"]),
                )
                continue

            preimage = min(
                (source, existing),
                key=lambda row: (float(row["created_at"]), str(row["effect_id"])),
            )
            restored_values = [
                float(row["restored_at"])
                for row in (source, existing)
                if row["restored_at"] is not None
            ]
            restored_at = max(restored_values) if len(restored_values) == 2 else None
            await db.execute(
                """
                UPDATE memory_relationship_conflict_effects
                SET replacement_triple_id = ?, pre_status = ?,
                    pre_status_reason = ?, pre_deprecated_by = ?,
                    pre_deprecated_at = ?, pre_valid_to = ?, effective_at = ?,
                    created_at = ?, restored_at = ?
                WHERE effect_id = ?
                """,
                (
                    preimage["replacement_triple_id"],
                    preimage["pre_status"],
                    preimage["pre_status_reason"],
                    preimage["pre_deprecated_by"],
                    preimage["pre_deprecated_at"],
                    preimage["pre_valid_to"],
                    min(float(source["effective_at"]), float(existing["effective_at"])),
                    min(float(source["created_at"]), float(existing["created_at"])),
                    restored_at,
                    existing["effect_id"],
                ),
            )
            await db.execute(
                "DELETE FROM memory_relationship_conflict_effects WHERE effect_id = ?",
                (source["effect_id"],),
            )


async def _rewrite_corrections(
    db: aiosqlite.Connection,
    *,
    affected_ids: set[str],
    id_map: Mapping[str, str],
    target_triple_id: str,
    subject_id: str,
    predicate: str,
    object_id: str,
    reference_replacements: Mapping[str, str] | None,
    corrections: list[aiosqlite.Row],
) -> None:
    reference_map = dict(reference_replacements or {})
    reference_map.update(id_map)
    for correction in corrections:
        before = _decode_payload(correction["before_json"], correction["correction_id"])
        replacement = _decode_payload(
            correction["replacement_json"],
            correction["correction_id"],
            allow_none=True,
        )
        target_id = str(correction["target_id"])
        replacement_target_id = str(correction["replacement_target_id"] or "")
        before_direct = (
            target_id in affected_ids or str(before.get("triple_id") or "") in affected_ids
        )
        replacement_direct = bool(
            replacement is not None
            and (
                replacement_target_id in affected_ids
                or str(replacement.get("triple_id") or "") in affected_ids
            )
        )
        rewritten_before = _rewrite_reference_value(before, reference_map)
        rewritten_replacement = (
            _rewrite_reference_value(replacement, reference_map)
            if replacement is not None
            else None
        )
        assert isinstance(rewritten_before, dict)
        assert rewritten_replacement is None or isinstance(rewritten_replacement, dict)
        if before_direct:
            await _set_payload_identity(
                db,
                rewritten_before,
                triple_id=target_triple_id,
                subject_id=subject_id,
                predicate=predicate,
                object_id=object_id,
            )
        if replacement_direct and rewritten_replacement is not None:
            await _set_payload_identity(
                db,
                rewritten_replacement,
                triple_id=target_triple_id,
                subject_id=subject_id,
                predicate=predicate,
                object_id=object_id,
            )
        new_target_id = target_triple_id if before_direct else id_map.get(target_id, target_id)
        new_replacement_target_id: str | None
        if replacement_target_id:
            new_replacement_target_id = (
                target_triple_id
                if replacement_direct
                else id_map.get(replacement_target_id, replacement_target_id)
            )
        else:
            new_replacement_target_id = None
        new_slot_key = str(rewritten_before.get("slot_key") or correction["slot_key"])
        new_fingerprint = str(
            rewritten_before.get("claim_fingerprint") or correction["claim_fingerprint"]
        )
        changed = (
            before_direct
            or replacement_direct
            or rewritten_before != before
            or rewritten_replacement != replacement
            or new_target_id != target_id
            or new_replacement_target_id != (replacement_target_id or None)
        )
        if not changed:
            continue
        await db.execute(
            """
            UPDATE memory_corrections
            SET target_id = ?, replacement_target_id = ?, slot_key = ?,
                claim_fingerprint = ?, before_json = ?, replacement_json = ?
            WHERE correction_id = ?
            """,
            (
                new_target_id,
                new_replacement_target_id,
                new_slot_key,
                new_fingerprint,
                _encode_payload(rewritten_before),
                (
                    _encode_payload(rewritten_replacement)
                    if rewritten_replacement is not None
                    else None
                ),
                correction["correction_id"],
            ),
        )
        await _rewrite_correction_rules(
            db,
            correction=correction,
            before=rewritten_before,
            replacement=rewritten_replacement,
        )


async def _set_payload_identity(
    db: aiosqlite.Connection,
    payload: dict[str, Any],
    *,
    triple_id: str,
    subject_id: str,
    predicate: str,
    object_id: str,
) -> None:
    scope_key = str(payload.get("scope_key") or "global")
    slot_key = await relationship_slot_key_on_connection(
        db,
        subject_id=subject_id,
        predicate=predicate,
        object_id=object_id,
    )
    payload.update(
        {
            "triple_id": triple_id,
            "subject_id": subject_id,
            "predicate": predicate,
            "object_id": object_id,
            "slot_key": slot_key,
            "claim_fingerprint": relationship_claim_fingerprint(
                slot_key_value=slot_key,
                subject_id=subject_id,
                predicate=predicate,
                object_id=object_id,
                scope_key_value=scope_key,
            ),
        }
    )


async def _rewrite_correction_rules(
    db: aiosqlite.Connection,
    *,
    correction: aiosqlite.Row,
    before: Mapping[str, Any],
    replacement: Mapping[str, Any] | None,
) -> None:
    before_slot = str(before.get("slot_key") or correction["slot_key"])
    before_fingerprint = str(before.get("claim_fingerprint") or correction["claim_fingerprint"])
    before_scope = str(before.get("scope_key") or "global")
    replacement_slot = str((replacement or {}).get("slot_key") or before_slot)
    replacement_fingerprint = str(
        (replacement or {}).get("claim_fingerprint") or before_fingerprint
    )
    replacement_scope = str((replacement or {}).get("scope_key") or before_scope)
    old_replacement = _decode_payload(
        correction["replacement_json"],
        correction["correction_id"],
        allow_none=True,
    )
    old_replacement_fingerprint = str(
        (old_replacement or {}).get("claim_fingerprint") or ""
    ).strip()
    async with db.execute(
        "SELECT * FROM memory_correction_rules WHERE correction_id = ?",
        (correction["correction_id"],),
    ) as cursor:
        rules = await cursor.fetchall()
    converged_record_error = (
        str(correction["correction_kind"]) == "record_error"
        and replacement is not None
        and before_fingerprint == replacement_fingerprint
        and before_scope == replacement_scope
    )
    for rule in rules:
        rule_kind = str(rule["rule_kind"])
        represents_replacement = bool(
            old_replacement_fingerprint
            and str(rule["claim_fingerprint"] or "") == old_replacement_fingerprint
        )
        if rule_kind == "authoritative_slot" or represents_replacement:
            slot_key = replacement_slot
            fingerprint = replacement_fingerprint
            scope_key = replacement_scope
        elif rule_kind == "scope_only":
            slot_key = before_slot
            fingerprint = before_fingerprint
            scope_key = replacement_scope
        else:
            slot_key = before_slot
            fingerprint = before_fingerprint
            scope_key = before_scope
        active = int(rule["active"])
        if converged_record_error and rule_kind == "block_claim":
            active = 0
        await db.execute(
            """
            UPDATE memory_correction_rules
            SET slot_key = ?, claim_fingerprint = ?, scope_key = ?, active = ?
            WHERE rule_id = ?
            """,
            (slot_key, fingerprint, scope_key, active, rule["rule_id"]),
        )


def _decode_payload(
    raw: Any,
    correction_id: Any,
    *,
    allow_none: bool = False,
) -> dict[str, Any] | None:
    if raw is None and allow_none:
        return None
    try:
        decoded = json.loads(str(raw))
    except (TypeError, ValueError, json.JSONDecodeError) as exc:
        raise ValueError(f"Correction payload is invalid: {correction_id}") from exc
    if not isinstance(decoded, dict):
        raise ValueError(f"Correction payload is not an object: {correction_id}")
    return decoded


def _encode_payload(payload: Mapping[str, Any]) -> str:
    return json.dumps(
        dict(payload),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )


async def _rewrite_dependencies(
    db: aiosqlite.Connection,
    id_map: Mapping[str, str],
) -> None:
    for old_id, new_id in id_map.items():
        async with db.execute(
            """
            SELECT * FROM memory_derivation_dependencies
            WHERE source_kind = 'edge' AND source_id = ?
            """,
            (old_id,),
        ) as cursor:
            rows = await cursor.fetchall()
        for row in rows:
            await db.execute(
                """
                INSERT INTO memory_derivation_dependencies(
                    artifact_kind, artifact_id, source_kind, source_id,
                    subject_key, source_revision, created_at
                ) VALUES (?, ?, 'edge', ?, ?, ?, ?)
                ON CONFLICT(artifact_kind, artifact_id, source_kind, source_id)
                DO UPDATE SET
                    subject_key = excluded.subject_key,
                    source_revision = MAX(
                        memory_derivation_dependencies.source_revision,
                        excluded.source_revision
                    ),
                    created_at = MIN(
                        memory_derivation_dependencies.created_at,
                        excluded.created_at
                    )
                """,
                (
                    row["artifact_kind"],
                    row["artifact_id"],
                    new_id,
                    row["subject_key"],
                    row["source_revision"],
                    row["created_at"],
                ),
            )
        await db.execute(
            """
            DELETE FROM memory_derivation_dependencies
            WHERE source_kind = 'edge' AND source_id = ?
            """,
            (old_id,),
        )


_JSON_REFERENCE_COLUMNS: dict[str, tuple[str, tuple[str, ...]]] = {
    "tom_snapshots": (
        "snapshot_id",
        (
            "preferences",
            "relationship_topology",
            "preferences_history",
            "relationship_history",
            "active_record_ids",
            "superseded_record_ids",
        ),
    ),
    "user_portrait_projection": (
        "user_id",
        (
            "world_json",
            "review_json",
            "recent_json",
            "prompt_summary_json",
            "evidence_refs_json",
            "source_counts_json",
        ),
    ),
    "user_profile_projection": (
        "user_id",
        (
            "communication_json",
            "identity_json",
            "preferences_json",
            "state_json",
            "field_sources_json",
            "field_conflicts_json",
        ),
    ),
}


async def _rewrite_materialized_json_references(
    db: aiosqlite.Connection,
    reference_map: Mapping[str, str],
) -> None:
    if not reference_map:
        return
    for table, (identity_column, columns) in _JSON_REFERENCE_COLUMNS.items():
        selected = ", ".join((identity_column, *columns))
        async with db.execute(f"SELECT {selected} FROM {table}") as cursor:
            rows = await cursor.fetchall()
        for row in rows:
            assignments: list[str] = []
            values: list[Any] = []
            for column in columns:
                raw = row[column]
                if raw is None:
                    continue
                try:
                    decoded = json.loads(str(raw))
                except (TypeError, ValueError, json.JSONDecodeError):
                    continue
                rewritten = _rewrite_reference_value(decoded, reference_map)
                if rewritten == decoded:
                    continue
                assignments.append(f"{column} = ?")
                values.append(
                    json.dumps(
                        rewritten,
                        ensure_ascii=False,
                        sort_keys=True,
                        separators=(",", ":"),
                    )
                )
            if assignments:
                await db.execute(
                    f"UPDATE {table} SET {', '.join(assignments)} WHERE {identity_column} = ?",
                    (*values, row[identity_column]),
                )


def _rewrite_reference_value(value: Any, id_map: Mapping[str, str]) -> Any:
    if isinstance(value, str):
        replacement = id_map.get(value)
        if replacement is not None:
            return replacement
        for prefix in ("edge:", "relationship:"):
            if value.startswith(prefix):
                replacement = id_map.get(value[len(prefix) :])
                if replacement is not None:
                    return f"{prefix}{replacement}"
        return value
    if isinstance(value, list):
        return [_rewrite_reference_value(item, id_map) for item in value]
    if isinstance(value, Mapping):
        return {str(key): _rewrite_reference_value(item, id_map) for key, item in value.items()}
    return value


__all__ = [
    "RelationshipIdentityRekeyResult",
    "refresh_relationship_governance_history_for_predicate",
    "relationship_slot_key_on_connection",
    "rekey_relationship_identity",
]
