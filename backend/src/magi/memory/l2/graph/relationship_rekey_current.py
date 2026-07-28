"""Current relationship row selection and evidence merging during identity rekeys."""

from __future__ import annotations

import json
from collections.abc import Mapping
from typing import Any

import aiosqlite

from ..corrections.forget_governance import (
    decode_evidence_event_ids,
    forgotten_evidence_event_ids_for_claims,
)
from ..corrections.models import CorrectionTargetKind
from ..corrections.ownership import has_correction_owner
from ..storage.utils import max_evidence_event_ids


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
        status == "deprecated"
        and valid_to is not None
        and (float(valid_to) > now or pending_target)
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
        if str(row["triple_id"]) in excluded_evidence_ids and str(row["triple_id"]) != winner_id:
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
