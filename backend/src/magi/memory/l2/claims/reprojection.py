"""Durable visibility and deterministic reprojection for Claim routes."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

import aiosqlite

from ....core.logger import get_logger
from ....core.sqlite import sqlite_connection_async
from ..semantic_routing import ROUTE_CONTRACT_VERSION, RouteDisposition
from .reprojection_write import reproject_claim_route
from .route_selection import (
    CURRENT_ENTITY_REF_VERSIONS_CTE,
    LATEST_ROUTE_ORDER_SQL,
)

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
    target_outcomes_invalidated: int = 0
    target_outcomes_revalidated: int = 0
    targets_archived: int = 0
    shared_targets_preserved: int = 0
    authority_targets_preserved: int = 0
    failed: int = 0


class _ClaimRouteReprojectionStore(Protocol):
    db_path: str

    async def initialize(self) -> None: ...


async def list_unrouted_claim_backlog(
    db_path: str,
) -> list[UnroutedClaimBacklogGroup]:
    """Group active Claims whose latest valid route outcome is unrouted."""

    async with sqlite_connection_async(db_path) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(f"""
            WITH {CURRENT_ENTITY_REF_VERSIONS_CTE},
            latest_route_outcomes AS (
                SELECT
                    outcomes.claim_id,
                    outcomes.outcome,
                    ROW_NUMBER() OVER (
                        PARTITION BY outcomes.claim_id
                        ORDER BY {LATEST_ROUTE_ORDER_SQL}
                    ) AS row_number
                FROM l2_claim_projection_outcomes AS outcomes
                LEFT JOIN current_entity_ref_versions AS route_refs
                  ON route_refs.claim_id = outcomes.claim_id
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
    limit: int = 200,
) -> ClaimRouteReprojectionStats:
    """Append current route outcomes for active unrouted or stale Claims.

    Selection uses the highest non-invalidated route contract before wall-clock
    time, then also repairs stale target receipts. The deterministic attempt key
    makes retries idempotent while preserving every historical outcome.
    """

    await store.initialize()
    candidates = await _list_reprojection_candidates(
        store.db_path,
        limit=limit,
    )
    appended = 0
    already_present = 0
    no_longer_active = 0
    failed = 0
    target_outcomes_invalidated = 0
    target_outcomes_revalidated = 0
    targets_archived = 0
    shared_targets_preserved = 0
    authority_targets_preserved = 0
    dispositions = {disposition: 0 for disposition in RouteDisposition}

    for claim_id in candidates:
        try:
            result = await reproject_claim_route(
                store.db_path,
                claim_id=claim_id,
            )
            if not result.claim_active or result.decision is None:
                no_longer_active += 1
                continue
            dispositions[result.decision.disposition] += 1
            if result.route_outcome_appended:
                appended += 1
            else:
                already_present += 1
            target_outcomes_invalidated += result.target_outcomes_invalidated
            target_outcomes_revalidated += result.target_outcomes_revalidated
            targets_archived += result.targets_archived
            shared_targets_preserved += result.shared_targets_preserved
            authority_targets_preserved += result.authority_targets_preserved
        except Exception as exc:
            failed += 1
            logger.warning(
                "L2 Claim route reprojection candidate failed",
                claim_id=claim_id,
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
        target_outcomes_invalidated=target_outcomes_invalidated,
        target_outcomes_revalidated=target_outcomes_revalidated,
        targets_archived=targets_archived,
        shared_targets_preserved=shared_targets_preserved,
        authority_targets_preserved=authority_targets_preserved,
        failed=failed,
    )


async def _list_reprojection_candidates(
    db_path: str,
    *,
    limit: int,
) -> list[str]:
    bounded_limit = max(1, min(int(limit), 5000))
    async with sqlite_connection_async(db_path) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            f"""
            WITH latest_entity_refs AS (
                SELECT
                    refs.claim_id,
                    refs.ref_role,
                    refs.entity_id,
                    refs.resolution_version,
                    ROW_NUMBER() OVER (
                        PARTITION BY refs.claim_id, refs.ref_role
                        ORDER BY refs.resolution_version DESC,
                                 refs.created_at DESC,
                                 refs.entity_id
                    ) AS row_number
                FROM l2_claim_entity_refs AS refs
                WHERE refs.invalidated_at IS NULL
            ),
            {CURRENT_ENTITY_REF_VERSIONS_CTE},
            latest_route_outcomes AS (
                SELECT
                    outcomes.claim_id,
                    outcomes.attempt_key,
                    outcomes.outcome,
                    outcomes.route_contract_version,
                    outcomes.details_json,
                    ROW_NUMBER() OVER (
                        PARTITION BY outcomes.claim_id
                        ORDER BY {LATEST_ROUTE_ORDER_SQL}
                    ) AS row_number
                FROM l2_claim_projection_outcomes AS outcomes
                LEFT JOIN current_entity_ref_versions AS route_refs
                  ON route_refs.claim_id = outcomes.claim_id
                WHERE outcomes.target_kind = 'route'
                  AND outcomes.invalidated_at IS NULL
            )
            SELECT claims.claim_id
            FROM l2_grounded_claims AS claims
            LEFT JOIN latest_route_outcomes AS latest
              ON latest.claim_id = claims.claim_id
             AND latest.row_number = 1
            LEFT JOIN latest_entity_refs AS subject_refs
              ON subject_refs.claim_id = claims.claim_id
             AND subject_refs.ref_role = 'subject'
             AND subject_refs.row_number = 1
            LEFT JOIN latest_entity_refs AS object_refs
              ON object_refs.claim_id = claims.claim_id
             AND object_refs.ref_role = 'object'
             AND object_refs.row_number = 1
            WHERE claims.availability = 'active'
              AND (
                    latest.claim_id IS NULL
                    OR latest.route_contract_version <= ?
              )
              AND (
                    latest.claim_id IS NULL
                    OR latest.route_contract_version < ?
                    OR (
                        latest.route_contract_version = ?
                        AND latest.outcome = 'unrouted'
                        AND latest.attempt_key != (
                            'route-reproject:v' || CAST(? AS TEXT)
                            || ':' || CASE
                                WHEN COALESCE(subject_refs.resolution_version, 0) > 0
                                THEN 's' || CAST(
                                    subject_refs.resolution_version AS TEXT
                                ) || ':'
                                ELSE ''
                            END
                            || 'r' || CAST(
                                COALESCE(object_refs.resolution_version, 0) AS TEXT
                            )
                            || ':' || claims.claim_id
                        )
                    )
                    OR (
                        latest.route_contract_version = ?
                        AND (
                            (
                                json_type(
                                    latest.details_json,
                                    '$.subject_resolution_version'
                                ) IS NOT NULL
                                AND CAST(json_extract(
                                    latest.details_json,
                                    '$.subject_resolution_version'
                                ) AS INTEGER) != COALESCE(
                                    subject_refs.resolution_version,
                                    0
                                )
                            )
                            OR (
                                json_type(
                                    latest.details_json,
                                    '$.object_resolution_version'
                                ) IS NOT NULL
                                AND CAST(json_extract(
                                    latest.details_json,
                                    '$.object_resolution_version'
                                ) AS INTEGER) != COALESCE(
                                    object_refs.resolution_version,
                                    0
                                )
                            )
                        )
                    )
                    OR EXISTS (
                        SELECT 1
                        FROM l2_claim_projection_outcomes AS target_outcomes
                        WHERE target_outcomes.claim_id = claims.claim_id
                          AND target_outcomes.target_kind IN (
                              'assertion', 'relationship'
                          )
                          AND target_outcomes.outcome = 'projected'
                          AND target_outcomes.invalidated_at IS NULL
                          AND target_outcomes.route_contract_version < ?
                    )
              )
            ORDER BY claims.created_at, claims.claim_id
            LIMIT ?
            """,
            (
                ROUTE_CONTRACT_VERSION,
                ROUTE_CONTRACT_VERSION,
                ROUTE_CONTRACT_VERSION,
                ROUTE_CONTRACT_VERSION,
                ROUTE_CONTRACT_VERSION,
                ROUTE_CONTRACT_VERSION,
                bounded_limit,
            ),
        ) as cursor:
            return [str(row["claim_id"]) for row in await cursor.fetchall()]


__all__ = [
    "ClaimRouteReprojectionStats",
    "UnroutedClaimBacklogGroup",
    "list_unrouted_claim_backlog",
    "reproject_stale_claim_routes",
]
