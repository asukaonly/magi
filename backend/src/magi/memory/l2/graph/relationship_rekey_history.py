"""Rewrite relationship correction history and durable governance identities."""

from __future__ import annotations

from typing import Any

import aiosqlite

from ..corrections.fingerprints import relationship_claim_fingerprint
from ..corrections.forget_governance import (
    ClaimGovernanceIdentityRewrite,
    rewrite_claim_governance_identities,
)
from ..corrections.models import CorrectionTargetKind
from .relationship_rekey_corrections import _rewrite_correction_rules
from .relationship_rekey_identity import (
    _decode_payload,
    _encode_payload,
    _set_payload_identity,
    relationship_slot_key_on_connection,
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
        return [row for row in await cursor.fetchall()]


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
