"""Reconcile active relationship corrections after an identity change."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

import aiosqlite

from ..corrections.identity_resolution import resolve_correction_after_identity_merge
from ..corrections.models import MemoryCorrection
from ..corrections.ownership import has_correction_owner
from ..corrections.revert_blocks import (
    IDENTITY_MERGE_REVERT_BLOCK,
    block_correction_reverts,
)
from ..graph_conflicts import GraphConflictRule
from .relationship_rekey_current import _load_edge
from .relationship_rekey_identity import _decode_payload
from .versions import append_knowledge_graph_version


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
