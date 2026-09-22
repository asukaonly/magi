"""Hydrate answer objects only for assertions already admitted by governance."""
from __future__ import annotations

import json
from typing import Any

import aiosqlite

from ....core.sqlite import sqlite_connection_async
from ..claim_text import load_claim_texts
from ..claims.route_selection import CURRENT_ENTITY_REF_VERSIONS_CTE, LATEST_ROUTE_ORDER_SQL
from ..projection.governance import active_projection_event_predicate
from ..semantic_routing import ObjectRole, assertion_predicate_descriptors

_TARGET_DESCRIPTORS = {
    item.predicate: item for item in assertion_predicate_descriptors()
    if item.object_role in {ObjectRole.TARGET_IDENTITY, ObjectRole.TARGET_ID_OR_TEXT}
}


async def hydrate_assertion_targets(
    db_path: str,
    assertions: list[dict[str, Any]],
    *,
    effective_at: float,
    effective_range: tuple[float | None, float | None] | None,
) -> None:
    """Attach catalog names or governed Claim literals without proposing facts."""
    if not assertions:
        return
    selected = {str(item["assertion_id"]): item for item in assertions}
    target_ids = list(dict.fromkeys(
        str(item["target_entity_id"]) for item in assertions if item.get("target_entity_id")
    ))
    literal_ids = [identity for identity, item in selected.items() if not item.get("target_entity_id")]
    async with sqlite_connection_async(db_path) as db:
        db.row_factory = aiosqlite.Row
        await db.execute("BEGIN")
        if target_ids:
            async with db.execute(
                "SELECT entity_id, canonical_name FROM entity_catalog "
                "WHERE entity_id IN (SELECT value FROM json_each(?))",
                (json.dumps(target_ids),),
            ) as result:
                names = {str(row[0]): str(row[1]) for row in await result.fetchall()}
            for item in assertions:
                if item.get("target_entity_id") in names:
                    item["target_entity_name"] = names[item["target_entity_id"]]
        if literal_ids:
            await _hydrate_correction_literals(db, selected, literal_ids)
            unresolved_ids = [identity for identity in literal_ids if not selected[identity].get("target")]
            if unresolved_ids:
                await _hydrate_literals(db, selected, unresolved_ids, effective_at, effective_range)
        await db.commit()


async def capture_assertion_target_on_connection(
    db: aiosqlite.Connection,
    assertion: dict[str, Any],
    *,
    observed_at: float,
) -> None:
    """Capture a literal target inside the transaction granting correction authority."""
    if assertion.get("target_entity_id"):
        return
    identity = str(assertion["assertion_id"])
    selected = {identity: assertion}
    await _hydrate_correction_literals(db, selected, [identity])
    if not assertion.get("target"):
        await _hydrate_literals(
            db,
            selected,
            [identity],
            observed_at,
            (assertion.get("valid_from"), assertion.get("valid_to")),
        )


async def _hydrate_correction_literals(
    db: aiosqlite.Connection,
    selected: dict[str, dict[str, Any]],
    literal_ids: list[str],
) -> None:
    async with db.execute(
        """
        SELECT correction_id, target_id, replacement_target_id, slot_key,
               before_json, replacement_json
        FROM memory_corrections
        WHERE replacement_target_id IN (SELECT value FROM json_each(?))
          AND target_kind = 'assertion' AND state = 'active'
          AND transition_cancelled_at IS NULL
        """,
        (json.dumps(literal_ids),),
    ) as cursor:
        rows = [dict(row) for row in await cursor.fetchall()]
    for row in rows:
        assertion = selected[str(row["replacement_target_id"])]
        before = _json_object(row["before_json"])
        replacement = _json_object(row["replacement_json"])
        target = before.get("target")
        if not isinstance(target, str) or not target.strip():
            continue
        if assertion.get("authority_ref") != f"correction:{row['correction_id']}":
            continue
        if (before.get("assertion_id") != row["target_id"]
                or assertion.get("previous_version_id") != row["target_id"]
                or assertion.get("slot_key") != row["slot_key"]
                or replacement.get("value") != assertion.get("trait_value")):
            continue
        # Scope refinement changes context, not the structured assertion target.
        identity_fields = (
            "entity_id", "entity_type", "trait_family", "trait_name", "slot_key",
            "target_entity_id", "target_entity_type", "target_scope",
        )
        if any(before.get(field) != assertion.get(field) for field in identity_fields):
            continue
        assertion["target"] = target


def _json_object(value: Any) -> dict[str, Any]:
    try:
        decoded = json.loads(value) if isinstance(value, str) else value
    except (TypeError, json.JSONDecodeError):
        return {}
    return decoded if isinstance(decoded, dict) else {}


async def _hydrate_literals(
    db: aiosqlite.Connection,
    selected: dict[str, dict[str, Any]],
    literal_ids: list[str],
    effective_at: float,
    effective_range: tuple[float | None, float | None] | None,
) -> None:
    async with db.execute(
        f"""
        WITH selected_receipts AS (
            SELECT * FROM l2_claim_projection_outcomes
            WHERE target_id IN (SELECT value FROM json_each(?))
              AND target_kind = 'assertion' AND outcome = 'projected'
              AND invalidated_at IS NULL
        ), {CURRENT_ENTITY_REF_VERSIONS_CTE}, latest_routes AS (
            SELECT outcomes.*, ROW_NUMBER() OVER (
                PARTITION BY outcomes.claim_id ORDER BY {LATEST_ROUTE_ORDER_SQL}
            ) AS route_rank
            FROM l2_claim_projection_outcomes outcomes
            LEFT JOIN current_entity_ref_versions route_refs ON route_refs.claim_id = outcomes.claim_id
            WHERE outcomes.target_kind = 'route' AND outcomes.invalidated_at IS NULL
              AND outcomes.claim_id IN (SELECT claim_id FROM selected_receipts)
        )
        SELECT receipt.target_id, receipt.target_slot_key, claims.claim_id,
               claims.canonical_predicate, claims.fact_valid_from, claims.fact_valid_to,
               route.target_slot_key AS route_slot,
               json_extract(route.details_json, '$.trait_code') AS route_trait,
               json_extract(route.details_json, '$.scope_key') AS route_scope
        FROM selected_receipts receipt
        JOIN latest_routes route ON route.claim_id = receipt.claim_id AND route.route_rank = 1
          AND route.outcome = 'routed'
          AND EXISTS (SELECT 1 FROM json_each(route.details_json, '$.projection_targets') WHERE value = 'assertion')
          AND json_extract(route.details_json, '$.semantic_target_key') LIKE 'text:%'
        JOIN l2_grounded_claims claims ON claims.claim_id = receipt.claim_id
          AND claims.availability = 'active' AND claims.polarity = 'positive'
        WHERE EXISTS (
            SELECT 1 FROM l2_claim_evidence evidence
            WHERE evidence.claim_id = claims.claim_id AND evidence.link_role = 'supporting'
        ) AND NOT EXISTS (
            SELECT 1 FROM l2_claim_evidence evidence
            WHERE evidence.claim_id = claims.claim_id
              AND NOT ({active_projection_event_predicate('evidence.event_id')})
        )
        """,
        (json.dumps(literal_ids),),
    ) as cursor:
        rows = [dict(row) for row in await cursor.fetchall()]
    candidates: list[dict[str, Any]] = []
    for row in rows:
        assertion = selected[str(row["target_id"])]
        descriptor = _TARGET_DESCRIPTORS.get(str(row["canonical_predicate"]))
        if descriptor is None or descriptor.trait_code != assertion.get("trait_name"):
            continue
        if str(descriptor.canonical_value or "") != str(assertion.get("trait_value") or ""):
            continue
        if not (row["target_slot_key"] == row["route_slot"] == assertion.get("slot_key")):
            continue
        if row["route_trait"] != assertion.get("trait_name") or row["route_scope"] != assertion.get("scope_key"):
            continue
        if (assertion.get("valid_from") is not None and row["fact_valid_to"] is not None
                and float(row["fact_valid_to"]) <= float(assertion["valid_from"])):
            continue
        if (assertion.get("valid_to") is not None and row["fact_valid_from"] is not None
                and float(assertion["valid_to"]) <= float(row["fact_valid_from"])):
            continue
        start, end = effective_range if effective_range is not None else (effective_at, effective_at)
        if start is not None and row["fact_valid_to"] is not None and float(row["fact_valid_to"]) <= start:
            continue
        if end is not None and row["fact_valid_from"] is not None and float(row["fact_valid_from"]) > end:
            continue
        candidates.append(row)
    texts = await load_claim_texts(db, list(dict.fromkeys(str(row["claim_id"]) for row in candidates)))
    targets: dict[str, set[str]] = {}
    for row in candidates:
        text = texts.get(str(row["claim_id"]))
        if (text is not None and text.object_surface and not text.object_entity_id
                and text.subject_entity_id == selected[str(row["target_id"])].get("entity_id")):
            targets.setdefault(str(row["target_id"]), set()).add(text.object_surface)
    for identity, values in targets.items():
        if len(values) == 1:
            selected[identity]["target"] = next(iter(values))
