"""Durable visibility and deterministic reprojection for Claim routes."""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Protocol

import aiosqlite

from ....core.logger import get_logger
from ....core.sqlite import sqlite_connection_async
from ..semantic_routing import (
    ROUTE_CONTRACT_VERSION,
    RouteDisposition,
    SemanticRouteDecision,
    SemanticRouteInput,
    derive_semantic_route,
)
from .identity import projection_outcome_id
from .models import ProjectionOutcomeInput

logger = get_logger(__name__)


@dataclass(frozen=True, slots=True)
class UnroutedClaimBacklogGroup:
    """One canonical-predicate group in the active unrouted backlog."""

    canonical_predicate: str
    claim_count: int
    oldest_claim_at: float
    newest_claim_at: float


@dataclass(frozen=True, slots=True)
class ClaimRouteReprojectionStats:
    """Counters from one bounded route reprojection pass."""

    candidates_selected: int = 0
    outcomes_appended: int = 0
    outcomes_already_present: int = 0
    claims_no_longer_active: int = 0
    routed: int = 0
    deferred: int = 0
    not_applicable: int = 0
    unrouted: int = 0
    failed: int = 0


class _ClaimRouteReprojectionStore(Protocol):
    db_path: str

    async def initialize(self) -> None: ...

    async def append_reprojected_claim_route_outcome(
        self,
        outcome: ProjectionOutcomeInput,
    ) -> dict[str, Any] | None: ...


async def list_unrouted_claim_backlog(
    db_path: str,
) -> list[UnroutedClaimBacklogGroup]:
    """Group active Claims whose latest valid route outcome is unrouted."""

    async with sqlite_connection_async(db_path) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute("""
            WITH latest_route_outcomes AS (
                SELECT
                    outcomes.claim_id,
                    outcomes.outcome,
                    ROW_NUMBER() OVER (
                        PARTITION BY outcomes.claim_id
                        ORDER BY outcomes.created_at DESC, outcomes.outcome_id DESC
                    ) AS row_number
                FROM l2_claim_projection_outcomes AS outcomes
                WHERE outcomes.target_kind = 'route'
                  AND outcomes.invalidated_at IS NULL
            )
            SELECT
                claims.canonical_predicate,
                COUNT(*) AS claim_count,
                MIN(claims.created_at) AS oldest_claim_at,
                MAX(claims.created_at) AS newest_claim_at
            FROM l2_grounded_claims AS claims
            JOIN latest_route_outcomes AS latest
              ON latest.claim_id = claims.claim_id
             AND latest.row_number = 1
            WHERE claims.availability = 'active'
              AND latest.outcome = 'unrouted'
            GROUP BY claims.canonical_predicate
            ORDER BY claim_count DESC, claims.canonical_predicate
            """) as cursor:
            rows = await cursor.fetchall()
    return [
        UnroutedClaimBacklogGroup(
            canonical_predicate=str(row["canonical_predicate"]),
            claim_count=int(row["claim_count"]),
            oldest_claim_at=float(row["oldest_claim_at"]),
            newest_claim_at=float(row["newest_claim_at"]),
        )
        for row in rows
    ]


async def reproject_stale_claim_routes(
    store: _ClaimRouteReprojectionStore,
    *,
    route_contract_version: int = ROUTE_CONTRACT_VERSION,
    limit: int = 200,
) -> ClaimRouteReprojectionStats:
    """Append current route outcomes for active unrouted or stale Claims.

    Selection is based only on the latest non-invalidated route outcome. The
    deterministic attempt key makes retries idempotent while preserving every
    historical outcome.
    """

    version = max(0, int(route_contract_version))
    await store.initialize()
    candidates = await _list_reprojection_candidates(
        store.db_path,
        route_contract_version=version,
        limit=limit,
    )
    appended = 0
    already_present = 0
    no_longer_active = 0
    failed = 0
    dispositions = {disposition: 0 for disposition in RouteDisposition}

    for candidate in candidates:
        try:
            decision = _derive_candidate_route(candidate)
            dispositions[decision.disposition] += 1
            outcome = _route_outcome(candidate, decision, route_contract_version=version)
            expected_outcome_id = projection_outcome_id(
                claim_id=outcome.claim_id,
                attempt_key=outcome.attempt_key,
                target_kind=outcome.target_kind,
                target_id=outcome.target_id,
            )
            existed = await _projection_outcome_exists(store.db_path, expected_outcome_id)
            stored = await store.append_reprojected_claim_route_outcome(outcome)
            if stored is None:
                no_longer_active += 1
            elif existed:
                already_present += 1
            else:
                appended += 1
        except Exception as exc:
            failed += 1
            logger.warning(
                "L2 Claim route reprojection candidate failed",
                claim_id=str(candidate.get("claim_id") or ""),
                error=str(exc),
            )

    return ClaimRouteReprojectionStats(
        candidates_selected=len(candidates),
        outcomes_appended=appended,
        outcomes_already_present=already_present,
        claims_no_longer_active=no_longer_active,
        routed=dispositions[RouteDisposition.ROUTED],
        deferred=dispositions[RouteDisposition.DEFERRED],
        not_applicable=dispositions[RouteDisposition.NOT_APPLICABLE],
        unrouted=dispositions[RouteDisposition.UNROUTED],
        failed=failed,
    )


async def _list_reprojection_candidates(
    db_path: str,
    *,
    route_contract_version: int,
    limit: int,
) -> list[dict[str, Any]]:
    bounded_limit = max(1, min(int(limit), 5000))
    async with sqlite_connection_async(db_path) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            """
            WITH latest_route_outcomes AS (
                SELECT
                    outcomes.claim_id,
                    outcomes.attempt_key,
                    outcomes.outcome,
                    outcomes.route_contract_version,
                    ROW_NUMBER() OVER (
                        PARTITION BY outcomes.claim_id
                        ORDER BY outcomes.created_at DESC, outcomes.outcome_id DESC
                    ) AS row_number
                FROM l2_claim_projection_outcomes AS outcomes
                WHERE outcomes.target_kind = 'route'
                  AND outcomes.invalidated_at IS NULL
            ),
            latest_object_refs AS (
                SELECT
                    refs.claim_id,
                    refs.entity_id,
                    refs.resolution_version,
                    ROW_NUMBER() OVER (
                        PARTITION BY refs.claim_id
                        ORDER BY refs.resolution_version DESC,
                                 refs.created_at DESC,
                                 refs.entity_id
                    ) AS row_number
                FROM l2_claim_entity_refs AS refs
                WHERE refs.ref_role = 'object'
                  AND refs.invalidated_at IS NULL
            )
            SELECT
                claims.claim_id,
                claims.subject_ref,
                claims.subject_type,
                claims.canonical_predicate,
                claims.fact_kind,
                claims.object_type,
                claims.object_value_json,
                claims.temporal_cue,
                object_refs.entity_id AS object_entity_id,
                COALESCE(object_refs.resolution_version, 0) AS object_resolution_version
            FROM l2_grounded_claims AS claims
            LEFT JOIN latest_route_outcomes AS latest
              ON latest.claim_id = claims.claim_id
             AND latest.row_number = 1
            LEFT JOIN latest_object_refs AS object_refs
              ON object_refs.claim_id = claims.claim_id
             AND object_refs.row_number = 1
            WHERE claims.availability = 'active'
              AND (
                    latest.claim_id IS NULL
                    OR latest.route_contract_version < ?
                    OR (
                        latest.route_contract_version = ?
                        AND latest.outcome = 'unrouted'
                        AND latest.attempt_key != (
                            'route-reproject:v' || CAST(? AS TEXT)
                            || ':r' || CAST(
                                COALESCE(object_refs.resolution_version, 0) AS TEXT
                            )
                            || ':' || claims.claim_id
                        )
                    )
              )
            ORDER BY claims.created_at, claims.claim_id
            LIMIT ?
            """,
            (
                route_contract_version,
                route_contract_version,
                route_contract_version,
                bounded_limit,
            ),
        ) as cursor:
            return [dict(row) for row in await cursor.fetchall()]


def _derive_candidate_route(candidate: dict[str, Any]) -> SemanticRouteDecision:
    return derive_semantic_route(
        SemanticRouteInput(
            claim_id=str(candidate["claim_id"]),
            subject_id=str(candidate["subject_ref"]),
            subject_type=str(candidate["subject_type"]),
            canonical_predicate=str(candidate["canonical_predicate"]),
            fact_kind=str(candidate["fact_kind"]),
            object_type=str(candidate["object_type"]),
            object_value=_decode_json(candidate.get("object_value_json")),
            object_entity_id=(
                str(candidate["object_entity_id"])
                if candidate.get("object_entity_id") is not None
                else None
            ),
            temporal_cue=str(candidate["temporal_cue"]),
        )
    )


def _route_outcome(
    candidate: dict[str, Any],
    decision: SemanticRouteDecision,
    *,
    route_contract_version: int,
) -> ProjectionOutcomeInput:
    predicate = str(candidate["canonical_predicate"]).strip().upper()
    resolution_version = max(0, int(candidate.get("object_resolution_version") or 0))
    return ProjectionOutcomeInput(
        claim_id=decision.claim_id,
        attempt_key=(
            f"route-reproject:v{route_contract_version}:"
            f"r{resolution_version}:{decision.claim_id}"
        ),
        target_kind="route",
        target_id=decision.route_key or f"predicate:{predicate}",
        target_slot_key=decision.slot_key,
        route_contract_version=route_contract_version,
        outcome=decision.disposition.value,
        reason_code=decision.reason_code,
        details={
            "semantic_route_id": decision.semantic_route_id,
            "family": decision.family,
            "trait_code": decision.trait_code,
            "object_role": decision.object_role.value,
            "value_fingerprint": decision.value_fingerprint,
            "target_entity_type": decision.target_entity_type,
            "scope_key": decision.scope_key,
        },
    )


async def _projection_outcome_exists(db_path: str, outcome_id: str) -> bool:
    async with sqlite_connection_async(db_path) as db:
        async with db.execute(
            "SELECT 1 FROM l2_claim_projection_outcomes WHERE outcome_id = ?",
            (outcome_id,),
        ) as cursor:
            return await cursor.fetchone() is not None


def _decode_json(raw: Any) -> Any | None:
    if raw is None:
        return None
    try:
        return json.loads(str(raw))
    except (TypeError, ValueError):
        return None


__all__ = [
    "ClaimRouteReprojectionStats",
    "UnroutedClaimBacklogGroup",
    "list_unrouted_claim_backlog",
    "reproject_stale_claim_routes",
]
