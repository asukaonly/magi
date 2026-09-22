"""Reversible current-preference closure from grounded direct user negation."""

from __future__ import annotations

import time
from collections.abc import Sequence
from typing import Any

import aiosqlite

from ....core.sqlite import sqlite_connection_async
from ..corrections.cache_signals import mark_subject_changed
from ..corrections.policy import CorrectionPolicyAction, CorrectionPolicyEvaluator
from ..graph.versions import append_knowledge_graph_version
from ..models import L2ProjectionLease
from ..projection.fencing import assert_current_projection_attempt
from ..projection.governance import active_projection_event_predicate
from ..semantic_routing import ROUTE_CONTRACT_VERSION, preference_exclusion_time_supported
from .outcomes import ClaimTargetOutcomeContext, append_claim_target_outcomes_on_connection
from .route_selection import CURRENT_ENTITY_REF_VERSIONS_CTE, LATEST_ROUTE_ORDER_SQL

_TABLES = {
    "assertion": ("tom_trait_assertions", "assertion_id"),
    "relationship": ("knowledge_graph", "triple_id"),
}
_INACTIVE = {
    "superseded",
    "archived",
    "expired",
    "invalidated",
    "user_rejected",
    "shadow",
    "deprecated",
}


async def reconcile_preference_exclusions(
    db_path: str,
    *,
    subject_ids: Sequence[str],
    projection_leases: Sequence[L2ProjectionLease],
) -> set[str]:
    """Recompute effects while fenced to the caller's live source projection."""
    async with sqlite_connection_async(db_path) as db:
        db.row_factory = aiosqlite.Row
        await db.execute("BEGIN IMMEDIATE")
        try:
            await assert_current_projection_attempt(db, projection_leases)
            changed = await reconcile_preference_exclusions_on_connection(
                db, subject_ids=subject_ids, now=time.time()
            )
            await db.commit()
        except BaseException:
            await db.rollback()
            raise
    for subject_id in changed:
        mark_subject_changed(db_path, subject_id)
    return changed


async def reconcile_preference_exclusions_on_connection(
    db: aiosqlite.Connection,
    *,
    subject_ids: Sequence[str],
    now: float,
) -> set[str]:
    """Apply or release only owned effects; the caller owns the write transaction."""
    changed: set[str] = set()
    for subject_id in sorted(set(subject_ids)):
        pending_routes = await _has_pending_preference_routes(db, subject_id)
        negatives = await _eligible_negatives(db, subject_id=subject_id, now=now)
        if not pending_routes:
            from ..assertions.observation_timeline import rebuild_preference_observation_timelines
            if await rebuild_preference_observation_timelines(db, subject_id=subject_id, now=now):
                changed.add(subject_id)
        effects = await _rows(
            db, "SELECT * FROM l2_preference_exclusion_effects WHERE subject_id = ?", (subject_id,)
        )
        effect_by_target = {(row["target_kind"], row["target_id"]): row for row in effects}
        targets = await _preference_targets(db, subject_id)
        seen: set[tuple[str, str]] = set()
        for kind, row in targets:
            target_id = str(row[_TABLES[kind][1]])
            key = (kind, target_id)
            seen.add(key)
            effect = effect_by_target.get(key)
            owned = effect is not None and _owns_effect(row, effect)
            if effect is not None and not owned:
                await _delete_effect(db, kind, target_id)
                effect = None
            if row["status"] in _INACTIVE and not owned:
                continue
            if not owned and any(
                row.get(field) is not None and float(row[field]) <= now
                for field in ("valid_to", "expires_at")
            ):
                continue
            # Explicit correction authority is never overridden by extraction.
            if row.get("authority_ref"):
                if effect is not None:
                    await _delete_effect(db, kind, target_id)
                continue
            predicate = (
                row["predicate"]
                if kind == "relationship"
                else {"like": "LIKES", "dislike": "DISLIKES"}.get(row["trait_value"])
            )
            supported_at, target_keys = await _positive_support(db, kind=kind, row=row)
            successor_start = await _successor_start(db, kind, row)
            original_end = effect["before_valid_to"] if effect is not None else row.get("valid_to")
            boundary = min(
                (float(value) for value in (original_end, successor_start) if value is not None),
                default=None,
            )
            matching = [
                item
                for item in negatives
                if item["canonical_predicate"] == predicate
                and item["semantic_target_key"] in target_keys
                and supported_at is not None
                and item["effective_at"] > supported_at
            ]
            if matching:
                earliest = min(matching, key=lambda item: (item["effective_at"], item["claim_id"]))
                effective_at = float(earliest["effective_at"])
                if boundary is not None:
                    effective_at = min(effective_at, boundary)
                if effect is None or not owned or float(effect["effective_at"]) != effective_at:
                    if effect is None:
                        await db.execute(
                            "INSERT INTO l2_preference_exclusion_effects VALUES (?, ?, ?, ?, ?, ?, ?)",
                            (
                                kind,
                                target_id,
                                subject_id,
                                row["status"],
                                row.get("valid_to"),
                                effective_at,
                                now,
                            ),
                        )
                    else:
                        await db.execute(
                            "UPDATE l2_preference_exclusion_effects SET effective_at = ?, applied_at = ? WHERE target_kind = ? AND target_id = ?",
                            (effective_at, now, kind, target_id),
                        )
                    await _set_state(
                        db, kind, target_id, status="superseded", valid_to=effective_at, now=now
                    )
                    changed.add(subject_id)
                for item in matching:
                    await _record_effect(db, item, kind=kind, target_id=target_id, now=now)
            elif owned and effect is not None:
                if pending_routes:
                    continue
                if (
                    supported_at is not None
                    and await _restoration_allowed(db, kind, row)
                ):
                    await _set_state(
                        db,
                        kind,
                        target_id,
                        status=("superseded" if successor_start is not None else effect["before_status"]),
                        valid_to=boundary,
                        now=now,
                    )
                    changed.add(subject_id)
                await _delete_effect(db, kind, target_id)
        for key in effect_by_target.keys() - seen:
            await _delete_effect(db, *key)
    for subject_id in changed:
        await db.execute(
            """INSERT INTO memory_subject_revisions(subject_key, revision, updated_at) VALUES (?, 1, ?)
            ON CONFLICT(subject_key) DO UPDATE SET revision = revision + 1, updated_at = excluded.updated_at""",
            (subject_id, now),
        )
    return changed


async def _has_pending_preference_routes(db: aiosqlite.Connection, subject_id: str) -> bool:
    """An unevaluated route is unknown, not evidence that an exclusion disappeared."""
    rows = await _rows(
        db,
        f"""WITH {CURRENT_ENTITY_REF_VERSIONS_CTE}, latest_routes AS (
            SELECT outcomes.*, ROW_NUMBER() OVER (
                PARTITION BY outcomes.claim_id ORDER BY {LATEST_ROUTE_ORDER_SQL}
            ) AS rn FROM l2_claim_projection_outcomes outcomes
            LEFT JOIN current_entity_ref_versions route_refs ON route_refs.claim_id = outcomes.claim_id
            WHERE outcomes.target_kind = 'route' AND outcomes.invalidated_at IS NULL
        )
        SELECT 1 FROM l2_grounded_claims c
        LEFT JOIN latest_routes route ON route.claim_id = c.claim_id AND route.rn = 1
        LEFT JOIN current_entity_ref_versions refs ON refs.claim_id = c.claim_id
        WHERE c.availability = 'active' AND c.subject_ref = ?
          AND c.canonical_predicate IN ('LIKES', 'DISLIKES')
          AND (route.claim_id IS NULL OR route.route_contract_version != ?
               OR COALESCE(json_extract(route.details_json, '$.subject_resolution_version'), 0)
                    != COALESCE(refs.subject_resolution_version, 0)
               OR COALESCE(json_extract(route.details_json, '$.object_resolution_version'), 0)
                    != COALESCE(refs.object_resolution_version, 0))
        LIMIT 1""",
        (subject_id, ROUTE_CONTRACT_VERSION),
    )
    return bool(rows)


async def _eligible_negatives(
    db: aiosqlite.Connection, *, subject_id: str, now: float
) -> list[dict[str, Any]]:
    # Identity comes from the current host route, including canonical text targets.
    rows = await _rows(
        db,
        f"""
        WITH {CURRENT_ENTITY_REF_VERSIONS_CTE},
        latest_routes AS (
            SELECT outcomes.*, ROW_NUMBER() OVER (
                PARTITION BY outcomes.claim_id ORDER BY {LATEST_ROUTE_ORDER_SQL}
            ) AS rn
            FROM l2_claim_projection_outcomes outcomes
            LEFT JOIN current_entity_ref_versions route_refs ON route_refs.claim_id = outcomes.claim_id
            WHERE outcomes.target_kind = 'route' AND outcomes.invalidated_at IS NULL
        ), latest_refs AS (
            SELECT *, ROW_NUMBER() OVER (PARTITION BY claim_id, ref_role ORDER BY resolution_version DESC, created_at DESC) AS rn
            FROM l2_claim_entity_refs WHERE invalidated_at IS NULL
        )
        SELECT c.claim_id, c.canonical_predicate,
               json_extract(route.details_json, '$.semantic_target_key') AS semantic_target_key,
               e.event_time AS effective_at, c.origin_attempt_key, c.temporal_cue,
               json_extract(c.raw_time_frame_json, '$.raw') AS raw_expression,
               json_extract(c.raw_time_frame_json, '$.resolution') AS time_resolution
        FROM l2_grounded_claims c
        JOIN latest_routes route ON route.claim_id = c.claim_id AND route.rn = 1
          AND route.outcome = 'routed' AND route.route_contract_version = {ROUTE_CONTRACT_VERSION}
          AND json_extract(route.details_json, '$.projection_targets') = '["exclusion"]'
          AND json_extract(route.details_json, '$.scope_key') = 'global'
        LEFT JOIN latest_refs o ON o.claim_id = c.claim_id AND o.ref_role = 'object' AND o.rn = 1
        LEFT JOIN latest_refs s ON s.claim_id = c.claim_id AND s.ref_role = 'subject' AND s.rn = 1
        JOIN l2_claim_evidence e ON e.claim_id = c.claim_id AND e.link_role = 'supporting'
        WHERE c.availability = 'active' AND c.polarity = 'negative'
          AND c.canonical_predicate IN ('LIKES', 'DISLIKES')
          AND (json_extract(route.details_json, '$.semantic_target_key') = 'entity:' || o.entity_id
               OR (o.entity_id IS NULL AND json_extract(route.details_json, '$.semantic_target_key') LIKE 'text:%'))
          AND c.fact_kind IN ('explicit_fact', 'stable_preference')
          AND c.temporal_cue != 'one_off'
          AND COALESCE(s.entity_id, c.subject_ref) = ?
          AND COALESCE(s.entity_id, c.subject_ref) = 'user:' || c.user_id
          AND c.fact_valid_from IS NULL AND c.fact_valid_to IS NULL
          AND e.author_type = 'user' AND e.evidence_class = 'user_self_report'
          AND e.evidence_mode = 'direct' AND e.timestamp_quality = 'exact'
          AND e.event_time > 0 AND e.event_time <= ?
          AND json_extract(e.evidence_locator_json, '$.assertion_mode') = 'asserted'
          AND {active_projection_event_predicate('e.event_id')}
    """,
        (subject_id, now),
    )
    return [
        row
        for row in rows
        if preference_exclusion_time_supported(
            temporal_cue=row["temporal_cue"],
            raw_expression=row["raw_expression"],
            time_resolution=row["time_resolution"],
        )
    ]


async def _preference_targets(
    db: aiosqlite.Connection, subject_id: str
) -> list[tuple[str, dict[str, Any]]]:
    assertions = await _rows(
        db,
        """SELECT * FROM tom_trait_assertions WHERE entity_id = ?
        AND trait_family = 'preference_profile' AND trait_name = 'preference.affinity'
        AND trait_value IN ('like', 'dislike') AND scope_key = 'global'""",
        (subject_id,),
    )
    relationships = await _rows(
        db,
        "SELECT * FROM knowledge_graph WHERE subject_id = ? AND predicate IN ('LIKES', 'DISLIKES') AND scope_key = 'global'",
        (subject_id,),
    )
    return [("assertion", row) for row in assertions] + [
        ("relationship", row) for row in relationships
    ]


async def _positive_support(
    db: aiosqlite.Connection, *, kind: str, row: dict[str, Any]
) -> tuple[float | None, set[str]]:
    target_id = row[_TABLES[kind][1]]
    records = await _rows(
        db,
        f"""WITH {CURRENT_ENTITY_REF_VERSIONS_CTE}, latest_routes AS (
            SELECT outcomes.*, ROW_NUMBER() OVER (
                PARTITION BY outcomes.claim_id ORDER BY {LATEST_ROUTE_ORDER_SQL}
            ) AS rn FROM l2_claim_projection_outcomes outcomes
            LEFT JOIN current_entity_ref_versions route_refs ON route_refs.claim_id = outcomes.claim_id
            WHERE outcomes.target_kind = 'route' AND outcomes.invalidated_at IS NULL
        )
        SELECT MAX(e.event_time) AS observed_at,
               json_extract(route.details_json, '$.semantic_target_key') AS semantic_target_key
        FROM l2_claim_projection_outcomes receipt
        JOIN l2_grounded_claims c ON c.claim_id = receipt.claim_id AND c.availability = 'active' AND c.polarity = 'positive'
        JOIN latest_routes route ON route.claim_id = c.claim_id AND route.rn = 1
          AND route.outcome = 'routed' AND route.route_contract_version = {ROUTE_CONTRACT_VERSION}
        JOIN l2_claim_evidence e ON e.claim_id = c.claim_id AND e.link_role = 'supporting'
        WHERE receipt.target_kind = ? AND receipt.target_id = ? AND receipt.invalidated_at IS NULL
          AND e.event_time > 0 AND {active_projection_event_predicate('e.event_id')}
        GROUP BY json_extract(route.details_json, '$.semantic_target_key')
    """,
        (kind, target_id),
    )
    observations = [float(item["observed_at"]) for item in records if item["observed_at"] is not None]
    target_keys = {str(item["semantic_target_key"]) for item in records if item["semantic_target_key"]}
    if not observations:
        return None, target_keys
    observed = max(observations)
    feedback_at = (
        row.get("user_feedback_at") if kind == "assertion" else row.get("last_confirmed_at")
    )
    if kind == "relationship":
        confirmations = await _rows(
            db,
            """SELECT MAX(user_feedback_at) AS confirmed_at FROM tom_trait_assertions
            WHERE entity_id = ? AND target_entity_id = ? AND scope_key = ?
              AND trait_name = 'preference.affinity' AND trait_value = ?
              AND user_feedback = 'confirmed'""",
            (
                row["subject_id"],
                row["object_id"],
                row["scope_key"],
                "like" if row["predicate"] == "LIKES" else "dislike",
            ),
        )
        feedback_at = max(float(feedback_at or 0), float(confirmations[0]["confirmed_at"] or 0))
    return max(float(observed), float(feedback_at or 0), float(row.get("valid_from") or 0)), target_keys


def _owns_effect(row: dict[str, Any], effect: dict[str, Any]) -> bool:
    return bool(
        row["status"] == "superseded"
        and row.get("valid_to") == effect["effective_at"]
        and row.get("updated_at") == effect["applied_at"]
    )


async def _restoration_allowed(db: aiosqlite.Connection, kind: str, row: dict[str, Any]) -> bool:
    evaluator = CorrectionPolicyEvaluator()
    decision = await (
        evaluator.evaluate_assertion(db, row)
        if kind == "assertion"
        else evaluator.evaluate_relationship(db, row)
    )
    return bool(decision.action == CorrectionPolicyAction.ACCEPT_ACTIVE)


async def _successor_start(
    db: aiosqlite.Connection, kind: str, row: dict[str, Any]
) -> float | None:
    """Bound restoration by surviving successors, including their historical versions."""
    table, key = _TABLES[kind]
    rows = await _rows(
        db,
        f"""SELECT MIN(valid_from) AS starts_at FROM {table}
        WHERE slot_key = ? AND scope_key = ? AND {key} != ? AND valid_from > ?
          AND status NOT IN ('archived', 'invalidated', 'user_rejected', 'shadow', 'deprecated')""",
        (row["slot_key"], row["scope_key"], row[key], float(row.get("valid_from") or 0)),
    )
    value = rows[0]["starts_at"] if rows else None
    return float(value) if value is not None else None


async def _set_state(
    db: aiosqlite.Connection,
    kind: str,
    target_id: str,
    *,
    status: str,
    valid_to: float | None,
    now: float,
) -> None:
    table, key = _TABLES[kind]
    await db.execute(
        f"UPDATE {table} SET status = ?, valid_to = ?, updated_at = ? WHERE {key} = ?",
        (status, valid_to, now, target_id),
    )
    if kind == "relationship":
        await append_knowledge_graph_version(db, triple_id=target_id, created_at=now)


async def _record_effect(
    db: aiosqlite.Connection, claim: dict[str, Any], *, kind: str, target_id: str, now: float
) -> None:
    await append_claim_target_outcomes_on_connection(
        db,
        context=ClaimTargetOutcomeContext.for_claim(
            claim_id=claim["claim_id"],
            attempt_key=f"preference-exclusion:v{ROUTE_CONTRACT_VERSION}:{claim['claim_id']}",
            route_contract_version=ROUTE_CONTRACT_VERSION,
        ),
        target_kind="exclusion",
        target_id=f"{kind}:{target_id}",
        target_slot_key=None,
        outcome="applied",
        reason_code="explicit_preference_negation",
        details={"target_kind": kind, "target_id": target_id},
        created_at=now,
    )


async def _delete_effect(db: aiosqlite.Connection, kind: str, target_id: str) -> None:
    await db.execute(
        "DELETE FROM l2_preference_exclusion_effects WHERE target_kind = ? AND target_id = ?",
        (kind, target_id),
    )


async def _rows(
    db: aiosqlite.Connection, query: str, args: tuple[Any, ...]
) -> list[dict[str, Any]]:
    async with db.execute(query, args) as cursor:
        return [dict(row) for row in await cursor.fetchall()]
