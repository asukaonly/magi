"""Recomputable occurrence statistics for assertion promotion."""

from __future__ import annotations

import json
import math
import time
from collections import defaultdict
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import datetime, tzinfo
from typing import Any

import aiosqlite

from ....core.sqlite import sqlite_connection_async
from ..claims.route_selection import (
    CURRENT_ENTITY_REF_VERSIONS_CTE,
    LATEST_ROUTE_ORDER_SQL,
)

MAX_FUTURE_CLOCK_SKEW_SECONDS = 5 * 60
_SUSTAINED_ENGAGEMENT_PREDICATES = frozenset(
    {
        "ATTENDED",
        "CONTRIBUTES_TO",
        "CREATES",
        "DEVELOPS",
        "MAINTAINS",
        "MEMBER_OF",
        "OWNS",
        "USES",
        "WORKS_ON",
    }
)
_FACT_KIND_CONSERVATIVE_ORDER = (
    "public_topology",
    "future_intent",
    "interaction_evidence",
    "explicit_fact",
    "stable_preference",
)
_TEMPORAL_CUE_CONSERVATIVE_ORDER = (
    "recent",
    "unspecified",
    "recurring",
    "stable",
)


def _required_text(value: Any, *, field_name: str) -> str:
    text = str(value or "").strip()
    if not text:
        raise ValueError(f"{field_name} must not be blank")
    return text


@dataclass(frozen=True, slots=True)
class ClaimRouteValueKey:
    """Stable assertion-promotion identity derived by host semantic routing."""

    target_slot_key: str
    value_fingerprint: str

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "target_slot_key",
            _required_text(self.target_slot_key, field_name="target_slot_key"),
        )
        object.__setattr__(
            self,
            "value_fingerprint",
            _required_text(self.value_fingerprint, field_name="value_fingerprint"),
        )


@dataclass(frozen=True, slots=True)
class OccurrenceTimelineStats:
    """Trusted-time portion of occurrence statistics.

    Event identity counts are intentionally owned by the caller. This value only
    summarizes event times that the caller has already classified as suitable
    for calendar arithmetic.
    """

    trusted_event_ids: tuple[str, ...]
    distinct_days: int
    first_observed_at: float | None
    last_observed_at: float | None
    span_days: float
    recency_days: float | None


@dataclass(frozen=True, slots=True)
class ClaimOccurrenceStats:
    """Full-ledger promotion statistics for one routed slot and typed value."""

    key: ClaimRouteValueKey
    fact_kind: str
    canonical_predicate: str
    temporal_cue: str
    evidence_class: str
    source_strength: str
    durable_permitted: bool
    claim_ids: tuple[str, ...]
    supporting_event_ids: tuple[str, ...]
    trusted_event_ids: tuple[str, ...]
    observation_count: int
    evidence_count: int
    distinct_days: int
    first_observed_at: float | None
    last_observed_at: float | None
    span_days: float
    recency_days: float | None

    def promotion_fields(self) -> dict[str, object]:
        """Return all ledger-owned fields consumed by AssertionPromotionInput."""

        return {
            "fact_kind": self.fact_kind,
            "predicate": self.canonical_predicate,
            "temporal_cue": self.temporal_cue,
            "evidence_class": self.evidence_class,
            "source_strength": self.source_strength,
            "durable_permitted": self.durable_permitted,
            "observation_count": self.observation_count,
            "evidence_count": self.evidence_count,
            "distinct_days": self.distinct_days,
            "span_days": self.span_days,
            "recency_days": self.recency_days,
        }


@dataclass(frozen=True, slots=True)
class _ClaimPolicyEvidence:
    claim_id: str
    fact_kind: str
    canonical_predicate: str
    temporal_cue: str
    evidence_class: str


def _aggregate_promotion_policy(
    rows: Iterable[_ClaimPolicyEvidence],
) -> dict[str, object]:
    """Aggregate promotion semantics by deterministic source-authority tiers."""

    material = tuple(rows)
    if not material:
        raise ValueError("promotion policy requires supporting Claim evidence")
    all_claim_ids = {row.claim_id for row in material}
    direct_claim_ids = {
        row.claim_id for row in material if row.evidence_class == "user_self_report"
    }
    sustained_claim_ids = {
        row.claim_id
        for row in material
        if row.canonical_predicate in _SUSTAINED_ENGAGEMENT_PREDICATES
    }
    external_claim_ids = {
        row.claim_id for row in material if row.evidence_class == "external_observation"
    }
    if direct_claim_ids:
        source_strength = "direct_user"
        policy_claim_ids = direct_claim_ids
    elif sustained_claim_ids:
        source_strength = "sustained_engagement"
        policy_claim_ids = sustained_claim_ids
    elif external_claim_ids:
        source_strength = "passive_exposure"
        policy_claim_ids = external_claim_ids
    else:
        source_strength = "structured_source"
        policy_claim_ids = all_claim_ids

    selected = tuple(row for row in material if row.claim_id in policy_claim_ids)
    fact_kinds = {row.fact_kind for row in selected}
    predicates = {row.canonical_predicate for row in selected if row.canonical_predicate}
    temporal_cues = {row.temporal_cue for row in selected}
    evidence_classes = {row.evidence_class for row in selected if row.evidence_class}
    return {
        "fact_kind": _conservative_value(
            fact_kinds,
            order=_FACT_KIND_CONSERVATIVE_ORDER,
            fallback="explicit_fact",
        ),
        "canonical_predicate": _aggregate_predicate(
            predicates,
            source_strength=source_strength,
        ),
        "temporal_cue": _aggregate_temporal_cue(temporal_cues),
        "evidence_class": _aggregate_evidence_class(
            evidence_classes,
            source_strength=source_strength,
        ),
        "source_strength": source_strength,
        "durable_permitted": source_strength == "direct_user",
    }


def _conservative_value(
    values: set[str],
    *,
    order: tuple[str, ...],
    fallback: str,
) -> str:
    normalized = {str(value or "").strip().casefold() for value in values}
    normalized.discard("")
    if len(normalized) == 1:
        return next(iter(normalized))
    for candidate in order:
        if candidate in normalized:
            return candidate
    return fallback


def _aggregate_predicate(values: set[str], *, source_strength: str) -> str:
    normalized = {str(value or "").strip().upper() for value in values}
    normalized.discard("")
    if len(normalized) == 1:
        return next(iter(normalized))
    if source_strength == "sustained_engagement":
        sustained = sorted(normalized & _SUSTAINED_ENGAGEMENT_PREDICATES)
        if sustained:
            return sustained[0]
    return ""


def _aggregate_temporal_cue(values: set[str]) -> str:
    normalized = {str(value or "").strip().casefold() for value in values}
    normalized.discard("")
    if len(normalized) == 1:
        return next(iter(normalized))
    if "one_off" in normalized:
        return "recent"
    for candidate in _TEMPORAL_CUE_CONSERVATIVE_ORDER:
        if candidate in normalized:
            return candidate
    return "unspecified"


def _aggregate_evidence_class(values: set[str], *, source_strength: str) -> str:
    if source_strength == "direct_user":
        return "user_self_report"
    if source_strength == "passive_exposure":
        return "external_observation"
    normalized = {str(value or "").strip().casefold() for value in values}
    normalized.discard("")
    return next(iter(normalized)) if len(normalized) == 1 else "mixed"


def _normalized_evidence_class(
    value: object,
    *,
    source_domain: object,
    author_type: object,
) -> str:
    explicit = str(value or "").strip().casefold()
    if explicit:
        return explicit
    domain = str(source_domain or "").strip().casefold()
    author = str(author_type or "").strip().casefold()
    if domain == "user_authored" and author in {"", "user"}:
        return "user_self_report"
    if domain == "external_activity":
        return "external_observation"
    if domain == "runtime_telemetry":
        return "system_runtime"
    return "unknown"


def summarize_occurrence_times(
    event_times: Iterable[tuple[str, float]],
    *,
    now: float,
    local_timezone: tzinfo | None = None,
) -> OccurrenceTimelineStats:
    """Summarize distinct exact event times using the user's local calendar days.

    A conflicting timestamp for the same event is excluded instead of selecting
    an arbitrary value and inventing date, span, or recency evidence.
    """

    times_by_event: dict[str, set[float]] = defaultdict(set)
    resolved_now = float(now)
    latest_trusted_time = resolved_now + MAX_FUTURE_CLOCK_SKEW_SECONDS
    for raw_event_id, raw_timestamp in event_times:
        event_id = str(raw_event_id or "").strip()
        try:
            timestamp = float(raw_timestamp)
        except (TypeError, ValueError):
            continue
        if event_id and math.isfinite(timestamp) and 0 < timestamp <= latest_trusted_time:
            times_by_event[event_id].add(timestamp)
    trusted_times = sorted(
        (
            (event_id, next(iter(timestamps)))
            for event_id, timestamps in times_by_event.items()
            if len(timestamps) == 1
        ),
        key=lambda item: (item[1], item[0]),
    )
    if not trusted_times:
        return OccurrenceTimelineStats(
            trusted_event_ids=(),
            distinct_days=0,
            first_observed_at=None,
            last_observed_at=None,
            span_days=0.0,
            recency_days=None,
        )

    def calendar_day(timestamp: float):  # type: ignore[no-untyped-def]
        if local_timezone is None:
            return datetime.fromtimestamp(timestamp).date()
        return datetime.fromtimestamp(timestamp, tz=local_timezone).date()

    timestamps = [timestamp for _event_id, timestamp in trusted_times]
    first_observed_at = timestamps[0]
    last_observed_at = timestamps[-1]
    return OccurrenceTimelineStats(
        trusted_event_ids=tuple(event_id for event_id, _timestamp in trusted_times),
        distinct_days=len({calendar_day(timestamp) for timestamp in timestamps}),
        first_observed_at=first_observed_at,
        last_observed_at=last_observed_at,
        span_days=max(0.0, (last_observed_at - first_observed_at) / 86_400),
        recency_days=max(0.0, (resolved_now - last_observed_at) / 86_400),
    )


async def load_routed_claim_occurrence_stats(
    db_path: str,
    *,
    keys: Iterable[ClaimRouteValueKey],
    now: float | None = None,
    local_timezone: tzinfo | None = None,
) -> dict[ClaimRouteValueKey, ClaimOccurrenceStats]:
    """Recompute promotion counts from active Claims and their latest valid route.

    Occurrence and evidence counts include all distinct grounded Claims and
    supporting events. Calendar-day, span, and recency statistics include only
    supporting evidence with ``exact`` or ``calendar_anchor`` quality. A
    document date is precise enough for day arithmetic even when it does not
    identify an exact instant; file order and file mtime are not.
    """

    normalized_keys = tuple(
        sorted(
            set(keys),
            key=lambda key: (key.target_slot_key, key.value_fingerprint),
        )
    )
    if not normalized_keys:
        return {}
    query_keys_json = json.dumps(
        [
            {
                "target_slot_key": key.target_slot_key,
                "value_fingerprint": key.value_fingerprint,
            }
            for key in normalized_keys
        ],
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    )
    async with sqlite_connection_async(db_path) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            f"""
            WITH requested_keys AS (
                SELECT
                    CAST(json_extract(value, '$.target_slot_key') AS TEXT)
                        AS target_slot_key,
                    CAST(json_extract(value, '$.value_fingerprint') AS TEXT)
                        AS value_fingerprint
                FROM json_each(?)
            ),
            {CURRENT_ENTITY_REF_VERSIONS_CTE},
            latest_route_outcomes AS (
                SELECT
                    outcomes.claim_id,
                    outcomes.target_slot_key,
                    outcomes.outcome,
                    CAST(
                        json_extract(outcomes.details_json, '$.value_fingerprint')
                        AS TEXT
                    ) AS value_fingerprint,
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
                latest.target_slot_key,
                latest.value_fingerprint,
                claims.claim_id,
                claims.fact_kind,
                claims.canonical_predicate,
                claims.temporal_cue,
                evidence.event_id,
                evidence.event_time,
                evidence.timestamp_quality,
                evidence.evidence_class,
                evidence.source_domain,
                evidence.author_type
            FROM latest_route_outcomes AS latest
            JOIN requested_keys AS requested
              ON requested.target_slot_key = latest.target_slot_key
             AND requested.value_fingerprint = latest.value_fingerprint
            JOIN l2_grounded_claims AS claims
              ON claims.claim_id = latest.claim_id
             AND claims.availability = 'active'
            JOIN l2_claim_evidence AS evidence
              ON evidence.claim_id = claims.claim_id
             AND evidence.link_role = 'supporting'
            WHERE latest.row_number = 1
              AND latest.outcome = 'routed'
            ORDER BY latest.target_slot_key, latest.value_fingerprint,
                     claims.claim_id, evidence.event_id
            """,
            (query_keys_json,),
        ) as cursor:
            rows = await cursor.fetchall()

    claims_by_key: dict[ClaimRouteValueKey, set[str]] = defaultdict(set)
    evidence_by_key: dict[ClaimRouteValueKey, set[str]] = defaultdict(set)
    exact_times_by_key: dict[ClaimRouteValueKey, list[tuple[str, float]]] = defaultdict(list)
    policy_evidence_by_key: dict[ClaimRouteValueKey, list[_ClaimPolicyEvidence]] = defaultdict(list)
    for row in rows:
        key = ClaimRouteValueKey(
            target_slot_key=str(row["target_slot_key"]),
            value_fingerprint=str(row["value_fingerprint"]),
        )
        claim_id = str(row["claim_id"])
        event_id = str(row["event_id"])
        claims_by_key[key].add(claim_id)
        evidence_by_key[key].add(event_id)
        policy_evidence_by_key[key].append(
            _ClaimPolicyEvidence(
                claim_id=claim_id,
                fact_kind=str(row["fact_kind"] or "").strip().casefold(),
                canonical_predicate=str(row["canonical_predicate"] or "").strip().upper(),
                temporal_cue=str(row["temporal_cue"] or "").strip().casefold(),
                evidence_class=_normalized_evidence_class(
                    row["evidence_class"],
                    source_domain=row["source_domain"],
                    author_type=row["author_type"],
                ),
            )
        )
        if str(row["timestamp_quality"] or "").strip().casefold() not in {
            "exact",
            "calendar_anchor",
        }:
            continue
        event_time = row["event_time"]
        if event_time is None:
            continue
        try:
            exact_times_by_key[key].append((event_id, float(event_time)))
        except (TypeError, ValueError):
            continue

    resolved_now = float(time.time() if now is None else now)
    result: dict[ClaimRouteValueKey, ClaimOccurrenceStats] = {}
    for key in normalized_keys:
        claim_ids = claims_by_key.get(key)
        if not claim_ids:
            continue
        supporting_event_ids = evidence_by_key[key]
        timeline = summarize_occurrence_times(
            exact_times_by_key.get(key, ()),
            now=resolved_now,
            local_timezone=local_timezone,
        )
        promotion_policy = _aggregate_promotion_policy(policy_evidence_by_key[key])
        result[key] = ClaimOccurrenceStats(
            key=key,
            fact_kind=str(promotion_policy["fact_kind"]),
            canonical_predicate=str(promotion_policy["canonical_predicate"]),
            temporal_cue=str(promotion_policy["temporal_cue"]),
            evidence_class=str(promotion_policy["evidence_class"]),
            source_strength=str(promotion_policy["source_strength"]),
            durable_permitted=bool(promotion_policy["durable_permitted"]),
            claim_ids=tuple(sorted(claim_ids)),
            supporting_event_ids=tuple(sorted(supporting_event_ids)),
            trusted_event_ids=timeline.trusted_event_ids,
            observation_count=len(claim_ids),
            evidence_count=len(supporting_event_ids),
            distinct_days=timeline.distinct_days,
            first_observed_at=timeline.first_observed_at,
            last_observed_at=timeline.last_observed_at,
            span_days=timeline.span_days,
            recency_days=timeline.recency_days,
        )
    return result


__all__ = [
    "ClaimOccurrenceStats",
    "ClaimRouteValueKey",
    "MAX_FUTURE_CLOCK_SKEW_SECONDS",
    "OccurrenceTimelineStats",
    "load_routed_claim_occurrence_stats",
    "summarize_occurrence_times",
]
