"""SQLite reads for governed self-report evidence and projection freshness."""

from __future__ import annotations

import json
from collections.abc import Awaitable, Callable, Iterable, Mapping
from typing import Any

import aiosqlite

from ....core.sqlite import sqlite_connection_async
from ..claim_text import load_claim_texts
from ..claims.route_selection import CURRENT_ENTITY_REF_VERSIONS_CTE, LATEST_ROUTE_ORDER_SQL
from ..claims.self_reports import SelfReportEvidence, SelfReportEvidenceBatch


class SqliteSelfReportRepository:
    def __init__(
        self,
        db_path: str,
        *,
        evidence_timestamps: Callable[[list[str]], Awaitable[Mapping[str, float]]],
    ) -> None:
        self._db_path = db_path
        self._evidence_timestamps = evidence_timestamps

    async def load(
        self,
        *,
        user_id: str,
        current_assertion_ids: Iterable[str],
        visible_assertion_ids: Iterable[str],
        effective_at: float,
    ) -> SelfReportEvidenceBatch:
        async with sqlite_connection_async(self._db_path) as db:
            rows = await _candidate_rows(db, user_id=user_id, effective_at=effective_at)
            texts = await load_claim_texts(db, list({str(row["claim_id"]) for row in rows}))
            current_keys = await _route_value_keys_for_assertions(
                db, _normalized_ids(current_assertion_ids)
            )
            visible_keys = await _route_value_keys_for_assertions(
                db, _normalized_ids(visible_assertion_ids)
            )
        grouped = _group_candidate_rows(rows)
        event_ids = sorted(
            {event_id for candidate in grouped.values() for event_id in candidate["event_ids"]}
        )
        visible_events = await self._evidence_timestamps(event_ids) if event_ids else {}
        if not isinstance(visible_events, Mapping):
            raise RuntimeError("L1 evidence visibility read returned an invalid payload")
        candidates = []
        for claim_id, candidate in grouped.items():
            text = texts.get(claim_id)
            candidates.append(
                SelfReportEvidence(
                    claim_id=claim_id,
                    claim={
                        **candidate["claim"],
                        "object_display_text": text.object_name if text is not None else None,
                    },
                    route_outcome=candidate["route_outcome"],
                    event_ids=tuple(
                        event_id
                        for event_id in candidate["event_ids"]
                        if event_id in visible_events
                    ),
                )
            )
        return SelfReportEvidenceBatch(
            tuple(candidates), frozenset(current_keys), frozenset(visible_keys)
        )

    async def latest_change_at(self, *, user_id: str) -> float:
        """Return the newest Claim/tombstone change that may invalidate a portrait cache."""

        db_path = self._db_path
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
                    SELECT outcomes.created_at AS changed_at
                    FROM l2_claim_projection_outcomes AS outcomes
                    JOIN l2_grounded_claims AS claims
                      ON claims.claim_id = outcomes.claim_id
                    WHERE claims.user_id = ?
                    UNION ALL
                    SELECT outcomes.invalidated_at AS changed_at
                    FROM l2_claim_projection_outcomes AS outcomes
                    JOIN l2_grounded_claims AS claims
                      ON claims.claim_id = outcomes.claim_id
                    WHERE claims.user_id = ?
                      AND outcomes.invalidated_at IS NOT NULL
                    UNION ALL
                    SELECT created_at AS changed_at
                    FROM memory_source_event_tombstones
                )
                """,
                (str(user_id).strip(), str(user_id).strip(), str(user_id).strip()),
            ) as cursor:
                row = await cursor.fetchone()
        return _float(row[0] if row is not None else None)


async def _candidate_rows(
    db: aiosqlite.Connection,
    *,
    user_id: str,
    effective_at: float,
) -> list[aiosqlite.Row]:
    async with db.execute(
        f"""
        WITH {CURRENT_ENTITY_REF_VERSIONS_CTE},
        latest_route_outcomes AS (
            SELECT
                outcomes.*,
                ROW_NUMBER() OVER (
                    PARTITION BY outcomes.claim_id
                    ORDER BY {LATEST_ROUTE_ORDER_SQL}
                ) AS route_rank
            FROM l2_claim_projection_outcomes AS outcomes
            LEFT JOIN current_entity_ref_versions AS route_refs
              ON route_refs.claim_id = outcomes.claim_id
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
              AND claims.polarity = 'positive'
              AND NOT EXISTS (
                  SELECT 1 FROM l2_claim_projection_outcomes AS receipt
                  JOIN tom_trait_assertions AS closed ON closed.assertion_id = receipt.target_id
                  WHERE receipt.claim_id = claims.claim_id AND receipt.target_kind = 'assertion'
                    AND receipt.invalidated_at IS NULL
                    AND closed.status IN ('superseded', 'archived', 'expired', 'invalidated', 'user_rejected')
                    AND (closed.valid_to IS NULL OR closed.valid_to <= ?)
                    AND NOT EXISTS (
                        SELECT 1 FROM l2_claim_projection_outcomes AS active_receipt
                        JOIN tom_trait_assertions AS current ON current.assertion_id = active_receipt.target_id
                        WHERE active_receipt.claim_id = claims.claim_id
                          AND active_receipt.target_kind = 'assertion'
                          AND active_receipt.invalidated_at IS NULL
                          AND current.status NOT IN ('superseded', 'archived', 'expired', 'invalidated', 'user_rejected', 'shadow')
                    )
              )
              AND (claims.fact_valid_from IS NULL OR claims.fact_valid_from <= ?)
              AND (claims.fact_valid_to IS NULL OR claims.fact_valid_to > ?)
              AND (claims.target_from IS NULL OR claims.target_from <= ?)
              AND (claims.target_to IS NULL OR claims.target_to > ?)
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
            effective_at,
        ),
    ) as cursor:
        return list(await cursor.fetchall())


async def _route_value_keys_for_assertions(
    db: aiosqlite.Connection,
    assertion_ids: tuple[str, ...],
) -> set[tuple[str, str]]:
    if not assertion_ids:
        return set()
    payload = json.dumps(assertion_ids, ensure_ascii=False, separators=(",", ":"))
    async with db.execute(
        """
        SELECT DISTINCT
            routes.target_slot_key,
            CAST(json_extract(routes.details_json, '$.value_fingerprint') AS TEXT)
        FROM l2_claim_projection_outcomes AS assertion_outcomes
        JOIN l2_claim_projection_outcomes AS routes
          ON routes.claim_id = assertion_outcomes.claim_id
         AND routes.attempt_key = assertion_outcomes.attempt_key
         AND routes.target_kind = 'route'
         AND routes.outcome = 'routed'
         AND routes.invalidated_at IS NULL
         AND routes.route_contract_version = assertion_outcomes.route_contract_version
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
            route_details = _json_value(row["route_details_json"])
            candidate = {
                "claim_id": claim_id,
                "claim": {
                    "availability": row["availability"],
                    "canonical_predicate": row["canonical_predicate"],
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
