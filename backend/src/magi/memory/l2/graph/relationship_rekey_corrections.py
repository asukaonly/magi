"""Rewrite relationship correction targets, payloads, and active rules."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

import aiosqlite

from .relationship_rekey_identity import (
    _decode_payload,
    _encode_payload,
    _set_payload_identity,
)
from .relationship_rekey_references import _rewrite_reference_value


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
