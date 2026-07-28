"""Load and rank assertion rows during entity identity rekeys."""

from __future__ import annotations

import json
from collections.abc import Mapping
from typing import Any

import aiosqlite

from ..corrections.forget_governance import decode_evidence_event_ids
from ..corrections.ownership import has_correction_owner

_UNIQUE_INDEX_EXCLUDED_STATUSES = frozenset(
    {
        "archived",
        "expired",
        "shadow",
        "superseded",
        "user_rejected",
    }
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
