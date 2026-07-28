"""Correction and forget-governance rewrites for assertion identity changes."""

from __future__ import annotations

import json
from collections.abc import Mapping

import aiosqlite

from ..corrections.fingerprints import assertion_claim_fingerprint, scope_key
from ..corrections.forget_governance import ClaimGovernanceIdentityRewrite
from .assertion_rekey_identity import (
    _decode_object,
    _encode_object,
    _project_assertion_identity,
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
