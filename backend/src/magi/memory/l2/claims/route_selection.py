"""Shared SQL contract for selecting one current Claim route outcome."""

from __future__ import annotations

CURRENT_ENTITY_REF_VERSIONS_CTE = """
current_entity_ref_versions AS (
    SELECT
        refs.claim_id,
        MAX(
            CASE WHEN refs.ref_role = 'subject'
                THEN refs.resolution_version ELSE 0 END
        ) AS subject_resolution_version,
        MAX(
            CASE WHEN refs.ref_role = 'object'
                THEN refs.resolution_version ELSE 0 END
        ) AS object_resolution_version
    FROM l2_claim_entity_refs AS refs
    WHERE refs.invalidated_at IS NULL
    GROUP BY refs.claim_id
)
""".strip()

LATEST_ROUTE_ORDER_SQL = """
outcomes.route_contract_version DESC,
CASE WHEN outcomes.attempt_key = (
    'route-reproject:v' || CAST(outcomes.route_contract_version AS TEXT)
    || ':' || CASE
        WHEN COALESCE(route_refs.subject_resolution_version, 0) > 0
        THEN 's' || CAST(route_refs.subject_resolution_version AS TEXT) || ':'
        ELSE ''
    END || 'r' || CAST(
        COALESCE(route_refs.object_resolution_version, 0) AS TEXT
    ) || ':' || outcomes.claim_id
) THEN 1 ELSE 0 END DESC,
outcomes.created_at DESC,
outcomes.outcome_id DESC
""".strip()

__all__ = ["CURRENT_ENTITY_REF_VERSIONS_CTE", "LATEST_ROUTE_ORDER_SQL"]
