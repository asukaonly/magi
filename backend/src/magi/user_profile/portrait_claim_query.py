"""Read-only Claim query for tentative self-report portrait lines."""

from __future__ import annotations

import inspect
import json
import time
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import aiosqlite

from ..core.sqlite import sqlite_connection_async
from .portrait_signal_policy import (
    classify_tentative_portrait_claim,
    tentative_portrait_prompt_line,
)


@dataclass(frozen=True, slots=True)
class TentativePortraitClaim:
    """One visible, deterministic self-report candidate for the portrait prompt."""

    claim_id: str
    slot_key: str
    value_fingerprint: str
    prompt_line: str
    basis_refs: tuple[str, ...]
    changed_at: float


async def list_tentative_portrait_claims(
    l2_store: Any,
    *,
    user_id: str,
    current_assertion_ids: Iterable[str] = (),
    visible_assertion_ids: Iterable[str] = (),
    limit: int = 100,
    effective_at: float | None = None,
) -> list[TentativePortraitClaim]:
    """Return current self-reports that have no durable portrait assertion."""

    db_path = _store_db_path(l2_store)
    if db_path is None:
        return []
    await _initialize_store(l2_store)
    at = float(effective_at if effective_at is not None else time.time())
    current_ids = _normalized_ids(current_assertion_ids)
    visible_ids = _normalized_ids(visible_assertion_ids)

    async with sqlite_connection_async(db_path) as db:
        db.row_factory = aiosqlite.Row
        rows = await _candidate_rows(
            db,
            user_id=user_id,
            effective_at=at,
            limit=max(1, min(int(limit), 500)),
        )
        claims_with_current_assertions = await _claim_ids_for_assertions(db, current_ids)
        visible_route_value_keys = await _route_value_keys_for_assertions(db, visible_ids)

    grouped = _group_candidate_rows(rows)
    event_ids = sorted(
        {
            event_id
            for candidate in grouped.values()
            for event_id in candidate["event_ids"]
        }
    )
    visible_event_ids = await _visible_l1_event_ids(l2_store, event_ids)
    candidates: list[TentativePortraitClaim] = []
    seen_route_values: set[tuple[str, str]] = set(visible_route_value_keys)

    for candidate in grouped.values():
        claim_id = str(candidate["claim_id"])
        if claim_id in claims_with_current_assertions:
            continue
        decision = classify_tentative_portrait_claim(
            candidate["claim"],
            candidate["route_outcome"],
        )
        if decision is None:
            continue
        route_value_key = (decision.slot_key, decision.value_fingerprint)
        if route_value_key in seen_route_values:
            continue
        basis_event_ids = [
            event_id
            for event_id in candidate["event_ids"]
            if event_id in visible_event_ids
        ][:3]
        if not basis_event_ids:
            continue
        prompt_line = tentative_portrait_prompt_line(decision.statement)
        if not prompt_line:
            continue
        seen_route_values.add(route_value_key)
        candidates.append(
            TentativePortraitClaim(
                claim_id=claim_id,
                slot_key=decision.slot_key,
                value_fingerprint=decision.value_fingerprint,
                prompt_line=prompt_line,
                basis_refs=tuple(f"event:{event_id}" for event_id in basis_event_ids),
                changed_at=max(
                    _float(candidate["claim"].get("updated_at")),
                    _float(candidate["route_outcome"].get("created_at")),
                ),
            )
        )
    return candidates


async def latest_portrait_claim_change_at(l2_store: Any, *, user_id: str) -> float:
    """Return the newest Claim/tombstone change that may invalidate a portrait cache."""

    db_path = _store_db_path(l2_store)
    if db_path is None:
        return 0.0
    await _initialize_store(l2_store)
    async with sqlite_connection_async(db_path) as db:
        async with db.execute(
            """
            SELECT MAX(changed_at)
            FROM (
                SELECT updated_at AS changed_at
                FROM l2_grounded_claims
                WHERE availability = 'active' AND user_id = ?
                UNION ALL
                SELECT forgotten_at AS changed_at
                FROM l2_grounded_claims
                WHERE availability = 'forgotten'
                UNION ALL
                SELECT created_at AS changed_at
                FROM memory_source_event_tombstones
            )
            """,
            (str(user_id).strip(),),
        ) as cursor:
            row = await cursor.fetchone()
    return _float(row[0] if row is not None else None)


async def _candidate_rows(
    db: aiosqlite.Connection,
    *,
    user_id: str,
    effective_at: float,
    limit: int,
) -> list[aiosqlite.Row]:
    async with db.execute(
        """
        WITH latest_route_outcomes AS (
            SELECT
                outcomes.*,
                ROW_NUMBER() OVER (
                    PARTITION BY outcomes.claim_id
                    ORDER BY outcomes.created_at DESC, outcomes.outcome_id DESC
                ) AS route_rank
            FROM l2_claim_projection_outcomes AS outcomes
            WHERE outcomes.target_kind = 'route'
              AND outcomes.invalidated_at IS NULL
        ),
        candidate_claims AS (
            SELECT
                claims.*,
                routes.outcome_id AS route_outcome_id,
                routes.target_kind AS route_target_kind,
                routes.target_slot_key AS route_target_slot_key,
                routes.route_contract_version,
                routes.outcome AS route_outcome,
                routes.details_json AS route_details_json,
                routes.created_at AS route_created_at
            FROM l2_grounded_claims AS claims
            JOIN latest_route_outcomes AS routes
              ON routes.claim_id = claims.claim_id
             AND routes.route_rank = 1
            WHERE claims.availability = 'active'
              AND claims.user_id = ?
              AND claims.subject_ref = ?
              AND LOWER(TRIM(claims.subject_type)) = 'user'
              AND routes.outcome = 'routed'
              AND claims.fact_kind != 'future_intent'
              AND (claims.fact_valid_from IS NULL OR claims.fact_valid_from <= ?)
              AND (claims.fact_valid_to IS NULL OR claims.fact_valid_to > ?)
              AND (claims.target_from IS NULL OR claims.target_from <= ?)
              AND (claims.target_to IS NULL OR claims.target_to > ?)
            ORDER BY routes.created_at DESC, claims.created_at DESC, claims.claim_id DESC
            LIMIT ?
        )
        SELECT
            candidates.*,
            evidence.event_id,
            evidence.event_time
        FROM candidate_claims AS candidates
        JOIN l2_claim_evidence AS evidence
          ON evidence.claim_id = candidates.claim_id
         AND evidence.link_role = 'supporting'
         AND LOWER(TRIM(COALESCE(evidence.author_type, ''))) = 'user'
         AND LOWER(TRIM(COALESCE(evidence.evidence_class, ''))) = 'user_self_report'
        LEFT JOIN memory_source_event_tombstones AS tombstones
          ON tombstones.event_id = evidence.event_id
        WHERE tombstones.event_id IS NULL
        ORDER BY candidates.route_created_at DESC,
                 candidates.created_at DESC,
                 candidates.claim_id DESC,
                 COALESCE(evidence.event_time, 0) DESC,
                 evidence.event_id
        """,
        (
            str(user_id).strip(),
            f"user:{str(user_id).strip()}",
            effective_at,
            effective_at,
            effective_at,
            effective_at,
            limit,
        ),
    ) as cursor:
        return list(await cursor.fetchall())


async def _claim_ids_for_assertions(
    db: aiosqlite.Connection,
    assertion_ids: tuple[str, ...],
) -> set[str]:
    if not assertion_ids:
        return set()
    payload = json.dumps(assertion_ids, ensure_ascii=False, separators=(",", ":"))
    async with db.execute(
        """
        SELECT DISTINCT outcomes.claim_id
        FROM l2_claim_projection_outcomes AS outcomes
        WHERE outcomes.target_kind = 'assertion'
          AND outcomes.outcome = 'projected'
          AND outcomes.invalidated_at IS NULL
          AND outcomes.target_id IN (
              SELECT CAST(value AS TEXT) FROM json_each(?)
          )
        """,
        (payload,),
    ) as cursor:
        return {str(row[0]) for row in await cursor.fetchall()}


async def _route_value_keys_for_assertions(
    db: aiosqlite.Connection,
    assertion_ids: tuple[str, ...],
) -> set[tuple[str, str]]:
    if not assertion_ids:
        return set()
    payload = json.dumps(assertion_ids, ensure_ascii=False, separators=(",", ":"))
    async with db.execute(
        """
        WITH latest_route_outcomes AS (
            SELECT
                outcomes.claim_id,
                outcomes.target_slot_key,
                outcomes.details_json,
                ROW_NUMBER() OVER (
                    PARTITION BY outcomes.claim_id
                    ORDER BY outcomes.created_at DESC, outcomes.outcome_id DESC
                ) AS route_rank
            FROM l2_claim_projection_outcomes AS outcomes
            WHERE outcomes.target_kind = 'route'
              AND outcomes.outcome = 'routed'
              AND outcomes.invalidated_at IS NULL
        )
        SELECT DISTINCT
            routes.target_slot_key,
            CAST(json_extract(routes.details_json, '$.value_fingerprint') AS TEXT)
        FROM l2_claim_projection_outcomes AS assertion_outcomes
        JOIN latest_route_outcomes AS routes
          ON routes.claim_id = assertion_outcomes.claim_id
         AND routes.route_rank = 1
        WHERE assertion_outcomes.target_kind = 'assertion'
          AND assertion_outcomes.outcome = 'projected'
          AND assertion_outcomes.invalidated_at IS NULL
          AND assertion_outcomes.target_id IN (
              SELECT CAST(value AS TEXT) FROM json_each(?)
          )
        """,
        (payload,),
    ) as cursor:
        return {
            (str(row[0]), str(row[1]))
            for row in await cursor.fetchall()
            if row[0] is not None and row[1] is not None
        }


def _group_candidate_rows(rows: list[aiosqlite.Row]) -> dict[str, dict[str, Any]]:
    grouped: dict[str, dict[str, Any]] = {}
    for row in rows:
        claim_id = str(row["claim_id"])
        candidate = grouped.get(claim_id)
        if candidate is None:
            object_value = _json_value(row["object_value_json"])
            route_details = _json_value(row["route_details_json"])
            candidate = {
                "claim_id": claim_id,
                "claim": {
                    "availability": row["availability"],
                    "canonical_predicate": row["canonical_predicate"],
                    "object_value": object_value,
                    "object_surface": row["object_surface"],
                    "updated_at": row["updated_at"],
                },
                "route_outcome": {
                    "target_kind": row["route_target_kind"],
                    "target_slot_key": row["route_target_slot_key"],
                    "route_contract_version": row["route_contract_version"],
                    "outcome": row["route_outcome"],
                    "details": route_details if isinstance(route_details, Mapping) else None,
                    "created_at": row["route_created_at"],
                },
                "event_ids": [],
            }
            grouped[claim_id] = candidate
        event_id = str(row["event_id"] or "").strip()
        if event_id and event_id not in candidate["event_ids"]:
            candidate["event_ids"].append(event_id)
    return grouped


async def _visible_l1_event_ids(l2_store: Any, event_ids: list[str]) -> set[str]:
    if not event_ids:
        return set()
    resolver = getattr(l2_store, "resolve_evidence_timestamps", None)
    if not callable(resolver):
        return set()
    try:
        resolved = resolver(event_ids)
        if inspect.isawaitable(resolved):
            resolved = await resolved
    except Exception:
        return set()
    if not isinstance(resolved, Mapping):
        return set()
    requested = set(event_ids)
    return {
        str(event_id)
        for event_id in resolved
        if str(event_id) in requested
    }


async def _initialize_store(l2_store: Any) -> None:
    initializer = getattr(l2_store, "initialize", None)
    if not callable(initializer):
        return
    result = initializer()
    if inspect.isawaitable(result):
        await result


def _store_db_path(l2_store: Any) -> str | None:
    if inspect.getattr_static(l2_store, "list_grounded_claims", None) is None:
        return None
    raw_path = getattr(l2_store, "db_path", None)
    if not isinstance(raw_path, (str, Path)):
        return None
    path = str(raw_path).strip()
    return path or None


def _normalized_ids(values: Iterable[str]) -> tuple[str, ...]:
    return tuple(sorted({str(value).strip() for value in values if str(value).strip()}))


def _json_value(value: Any) -> Any:
    if value is None or not isinstance(value, str):
        return value
    try:
        return json.loads(value)
    except (TypeError, ValueError, json.JSONDecodeError):
        return None


def _float(value: Any) -> float:
    try:
        return float(value or 0.0)
    except (TypeError, ValueError):
        return 0.0


__all__ = [
    "TentativePortraitClaim",
    "latest_portrait_claim_change_at",
    "list_tentative_portrait_claims",
]
