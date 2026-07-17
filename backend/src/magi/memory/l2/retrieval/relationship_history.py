"""Historical reconstruction for governed L2 relationships."""

from __future__ import annotations

import json
import math
from collections.abc import Mapping
from typing import Any, Dict, List

import aiosqlite

from ....core.sqlite import sqlite_connection_async
from ..corrections.fingerprints import scope_matches
from ..corrections.forget_governance import forget_rules_for_claims
from ..corrections.models import CorrectionTargetKind
from .common import (
    L2RetrievalQueryHostProtocol,
    bounded_scoped_candidate_limit,
    matching_scope_keys,
    select_governed_range_rows,
)
from .relationship_version_history import (
    _current_relationship_snapshot,
    _materialize_relationship_states,
    _relationship_overlaps_request,
    _relationship_scope_priority,
    _relationship_version_to_dict,
)


async def _list_governed_relationship_history(
    host: L2RetrievalQueryHostProtocol,
    *,
    subject_id: str | None,
    entity_ids: List[str] | None,
    direction: str,
    object_id: str | None,
    predicates: List[str] | None,
    object_types: List[str] | None,
    evidence_classes: List[str] | None,
    triple_ids: List[str] | None,
    requested_scope: Mapping[str, Any],
    effective_at: float,
    effective_range: tuple[float | None, float | None] | None,
    limit: int,
) -> List[Dict[str, Any]]:
    candidate_triple_ids = await _select_historical_candidate_triple_ids(
        host,
        subject_id=subject_id,
        entity_ids=entity_ids,
        direction=direction,
        object_id=object_id,
        predicates=predicates,
        object_types=object_types,
        evidence_classes=evidence_classes,
        triple_ids=triple_ids,
        requested_scope=requested_scope,
        effective_at=effective_at,
        effective_range=effective_range,
        limit=limit,
    )
    if not candidate_triple_ids:
        return []

    candidate_placeholders = ", ".join("?" for _ in candidate_triple_ids)
    version_sql = """
        SELECT v.*
        FROM knowledge_graph_versions v
        WHERE v.governance_complete = 1
          AND v.triple_id IN ({candidate_placeholders})
    """
    version_sql = version_sql.format(candidate_placeholders=candidate_placeholders)
    version_args = list(candidate_triple_ids)
    current_sql = (
        "SELECT g.* FROM knowledge_graph g " f"WHERE g.triple_id IN ({candidate_placeholders})"
    )
    current_args = list(candidate_triple_ids)

    async with sqlite_connection_async(host.db_path) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            version_sql + " ORDER BY v.triple_id, v.created_at, v.version_id",
            tuple(version_args),
        ) as cursor:
            version_rows = await cursor.fetchall()
        async with db.execute(current_sql, tuple(current_args)) as cursor:
            current_rows = await cursor.fetchall()

    snapshots = [_relationship_version_to_dict(dict(row)) for row in version_rows]
    snapshots.extend(_current_relationship_snapshot(host, row) for row in current_rows)
    relationships = _materialize_relationship_states(snapshots)
    relationships = await _apply_relationship_forget_rules(host, relationships)
    relationships = [
        relationship
        for relationship in relationships
        if _relationship_matches_requested_filters(
            relationship,
            subject_id=subject_id,
            entity_ids=entity_ids,
            direction=direction,
            object_id=object_id,
            predicates=predicates,
            object_types=object_types,
            evidence_classes=evidence_classes,
            triple_ids=triple_ids,
        )
        and scope_matches(relationship.get("scope"), requested_scope)
        and _relationship_overlaps_request(
            relationship,
            effective_at=effective_at,
            effective_range=effective_range,
        )
    ]
    relationships.sort(key=_relationship_scope_priority, reverse=True)

    if effective_range is not None:
        return select_governed_range_rows(
            relationships,
            identity_field="_governed_version_id",
            range_start=effective_range[0],
            range_end=effective_range[1],
            limit=limit,
        )

    current_by_slot: dict[str, Dict[str, Any]] = {}
    for relationship in relationships:
        slot = str(relationship.get("slot_key") or relationship.get("triple_id") or "")
        current_by_slot.setdefault(slot, relationship)
        if len(current_by_slot) >= limit:
            break
    return list(current_by_slot.values())


async def _batch_list_governed_relationship_history(
    host: L2RetrievalQueryHostProtocol,
    *,
    entity_ids: List[str],
    direction: str,
    object_id: str | None,
    predicates: List[str] | None,
    object_types: List[str] | None,
    evidence_classes: List[str] | None,
    requested_scope: Mapping[str, Any],
    effective_at: float,
    effective_range: tuple[float | None, float | None] | None,
    limit_per_entity: int,
) -> Dict[str, List[Dict[str, Any]]]:
    """Reconstruct governed history for many entities with fixed query count."""
    unique_ids = list(dict.fromkeys(str(item) for item in entity_ids if item))
    if not unique_ids:
        return {}
    candidate_sql, candidate_args = _build_batch_historical_candidate_query(
        entity_ids=unique_ids,
        direction=direction,
        object_id=object_id,
        predicates=predicates,
        object_types=object_types,
        evidence_classes=evidence_classes,
        requested_scope=requested_scope,
        effective_at=effective_at,
        effective_range=effective_range,
        limit_per_entity=limit_per_entity,
    )
    async with sqlite_connection_async(host.db_path) as db:
        async with db.execute(candidate_sql, tuple(candidate_args)) as cursor:
            candidate_rows = await cursor.fetchall()
    candidates_by_entity: dict[str, set[str]] = {entity_id: set() for entity_id in unique_ids}
    for entity_id, triple_id in candidate_rows:
        candidates_by_entity[str(entity_id)].add(str(triple_id))
    candidate_triple_ids = list(
        dict.fromkeys(
            triple_id for entity_id in unique_ids for triple_id in candidates_by_entity[entity_id]
        )
    )
    if not candidate_triple_ids:
        return {entity_id: [] for entity_id in unique_ids}

    candidate_placeholders = ", ".join("?" for _ in candidate_triple_ids)
    async with sqlite_connection_async(host.db_path) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            f"""
            SELECT v.*
            FROM knowledge_graph_versions AS v
            WHERE v.governance_complete = 1
              AND v.triple_id IN ({candidate_placeholders})
            ORDER BY v.triple_id, v.created_at, v.version_id
            """,
            tuple(candidate_triple_ids),
        ) as cursor:
            version_rows = await cursor.fetchall()
        async with db.execute(
            f"SELECT g.* FROM knowledge_graph AS g "
            f"WHERE g.triple_id IN ({candidate_placeholders})",
            tuple(candidate_triple_ids),
        ) as cursor:
            current_rows = await cursor.fetchall()

    snapshots = [_relationship_version_to_dict(dict(row)) for row in version_rows]
    snapshots.extend(_current_relationship_snapshot(host, row) for row in current_rows)
    materialized = _materialize_relationship_states(snapshots)
    materialized = await _apply_relationship_forget_rules(host, materialized)
    result: Dict[str, List[Dict[str, Any]]] = {}
    requested_limit = max(1, int(limit_per_entity))
    for entity_id in unique_ids:
        candidate_ids = candidates_by_entity[entity_id]
        relationships = [
            relationship
            for relationship in materialized
            if str(relationship.get("triple_id") or "") in candidate_ids
            and _relationship_matches_requested_filters(
                relationship,
                subject_id=None,
                entity_ids=[entity_id],
                direction=direction,
                object_id=object_id,
                predicates=predicates,
                object_types=object_types,
                evidence_classes=evidence_classes,
                triple_ids=None,
            )
            and scope_matches(relationship.get("scope"), requested_scope)
            and _relationship_overlaps_request(
                relationship,
                effective_at=effective_at,
                effective_range=effective_range,
            )
        ]
        relationships.sort(key=_relationship_scope_priority, reverse=True)
        if effective_range is not None:
            result[entity_id] = select_governed_range_rows(
                relationships,
                identity_field="_governed_version_id",
                range_start=effective_range[0],
                range_end=effective_range[1],
                limit=requested_limit,
            )
            continue
        current_by_slot: dict[str, Dict[str, Any]] = {}
        for relationship in relationships:
            slot = str(relationship.get("slot_key") or relationship.get("triple_id") or "")
            current_by_slot.setdefault(slot, relationship)
            if len(current_by_slot) >= requested_limit:
                break
        result[entity_id] = list(current_by_slot.values())
    return result


async def _apply_relationship_forget_rules(
    host: L2RetrievalQueryHostProtocol,
    relationships: List[Dict[str, Any]],
) -> List[Dict[str, Any]]:
    if not relationships:
        return relationships
    async with sqlite_connection_async(host.db_path) as db:
        rules_by_claim = await forget_rules_for_claims(
            db,
            target_kind=CorrectionTargetKind.EDGE,
            claim_fingerprints=(
                str(relationship.get("claim_fingerprint") or "") for relationship in relationships
            ),
        )
    governed: List[Dict[str, Any]] = []
    for relationship in relationships:
        fingerprint = str(relationship.get("claim_fingerprint") or "")
        segments = [relationship]
        for rule in rules_by_claim.get(fingerprint, ()):
            forget_kind = str(rule["forget_kind"])
            if forget_kind == "entity":
                segments = []
                break
            forgotten_event_ids = {
                str(event_id) for event_id in rule.get("forgotten_event_ids", ())
            }
            if forget_kind == "event":
                segments = [
                    filtered
                    for segment in segments
                    if (
                        filtered := _without_forgotten_relationship_evidence(
                            segment,
                            forgotten_event_ids=forgotten_event_ids,
                        )
                    )
                    is not None
                ]
                if not segments:
                    break
                continue
            effective_from = rule.get("effective_from")
            effective_to = rule.get("effective_to")
            if effective_from is None or effective_to is None:
                segments = []
                break
            filtered_segments: List[Dict[str, Any]] = []
            for segment in segments:
                segment_evidence = {
                    str(event_id) for event_id in segment.get("evidence_event_ids", ())
                }
                if not _relationship_overlaps_forget_interval(
                    segment,
                    forget_from=float(effective_from),
                    forget_to=float(effective_to),
                ):
                    if segment_evidence.intersection(forgotten_event_ids):
                        filtered_segments.append(
                            _without_forgotten_relationship_evidence(
                                segment,
                                forgotten_event_ids=forgotten_event_ids,
                                preserve_empty=True,
                            )
                        )
                    else:
                        filtered_segments.append(segment)
                    continue
                if segment_evidence.intersection(forgotten_event_ids):
                    filtered = _without_forgotten_relationship_evidence(
                        segment,
                        forgotten_event_ids=forgotten_event_ids,
                    )
                    if filtered is not None:
                        filtered_segments.append(filtered)
                    continue
                filtered_segments.extend(
                    _subtract_forgotten_relationship_interval(
                        segment,
                        forget_from=float(effective_from),
                        forget_to=float(effective_to),
                        rule_id=str(rule["rule_id"]),
                    )
                )
            segments = filtered_segments
            if not segments:
                break
        governed.extend(segments)
    return governed


def _without_forgotten_relationship_evidence(
    relationship: Dict[str, Any],
    *,
    forgotten_event_ids: set[str],
    preserve_empty: bool = False,
) -> Dict[str, Any] | None:
    if not forgotten_event_ids:
        return relationship
    original = [str(event_id) for event_id in relationship.get("evidence_event_ids", ())]
    retained = [str(event_id) for event_id in original if str(event_id) not in forgotten_event_ids]
    if len(retained) == len(original):
        return relationship
    if original and not retained and not preserve_empty:
        return None
    filtered = dict(relationship)
    filtered["evidence_event_ids"] = retained
    filtered["observation_count"] = len(retained)
    filtered["evidence_text"] = ""
    filtered["natural_summary"] = ""
    return filtered


def _relationship_overlaps_forget_interval(
    relationship: Mapping[str, Any],
    *,
    forget_from: float,
    forget_to: float,
) -> bool:
    start_raw = relationship.get("valid_from")
    end_raw = relationship.get("valid_to")
    start = float(start_raw) if start_raw is not None else -math.inf
    end = float(end_raw) if end_raw is not None else math.inf
    return max(start, forget_from) <= min(end, forget_to)


def _subtract_forgotten_relationship_interval(
    relationship: Dict[str, Any],
    *,
    forget_from: float,
    forget_to: float,
    rule_id: str,
) -> List[Dict[str, Any]]:
    start_raw = relationship.get("valid_from")
    end_raw = relationship.get("valid_to")
    start = float(start_raw) if start_raw is not None else -math.inf
    end = float(end_raw) if end_raw is not None else math.inf
    removed_end = math.nextafter(forget_to, math.inf)
    overlap_start = max(start, forget_from)
    overlap_end = min(end, removed_end)
    if overlap_start >= overlap_end:
        return [relationship]

    fragments: List[Dict[str, Any]] = []
    if start < overlap_start:
        left = dict(relationship)
        left["valid_to"] = overlap_start
        left["evidence_text"] = ""
        left["natural_summary"] = ""
        left["_governed_version_id"] = (
            f"{relationship.get('_governed_version_id')}:{rule_id}:before"
        )
        fragments.append(left)
    if overlap_end < end:
        right = dict(relationship)
        right["valid_from"] = overlap_end
        right["evidence_text"] = ""
        right["natural_summary"] = ""
        right["_governed_version_id"] = (
            f"{relationship.get('_governed_version_id')}:{rule_id}:after"
        )
        fragments.append(right)
    return fragments


def _build_batch_historical_candidate_query(
    *,
    entity_ids: List[str],
    direction: str,
    object_id: str | None,
    predicates: List[str] | None,
    object_types: List[str] | None,
    evidence_classes: List[str] | None,
    requested_scope: Mapping[str, Any],
    effective_at: float,
    effective_range: tuple[float | None, float | None] | None,
    limit_per_entity: int,
) -> tuple[str, list[Any]]:
    requested_json = json.dumps(entity_ids, ensure_ascii=False, separators=(",", ":"))
    version_join = _batch_entity_join_clause(alias="v", direction=direction)
    current_join = _batch_entity_join_clause(alias="g", direction=direction)
    version_select = f"""
        SELECT requested.entity_id AS bucket_entity_id,
               v.triple_id, v.scope_key, v.scope_json, v.evidence_class,
               v.created_at AS sort_at, 0 AS source_order,
               v.version_id AS snapshot_id, v.status, v.valid_from,
               v.valid_to, v.expires_at, v.first_observed_at,
               v.edge_created_at
        FROM requested_entities AS requested
        JOIN knowledge_graph_versions AS v ON {version_join}
        WHERE v.governance_complete = 1
          AND NOT EXISTS (
              SELECT 1 FROM memory_forget_claim_rules AS forgotten
              WHERE forgotten.target_kind = 'edge'
                AND forgotten.forget_kind = 'entity'
                AND forgotten.claim_fingerprint = v.claim_fingerprint
          )
    """
    version_select, version_args = _append_relationship_identity_filters(
        version_select,
        [],
        alias="v",
        evidence_alias=None,
        subject_id=None,
        entity_ids=None,
        direction=direction,
        object_id=object_id,
        predicates=predicates,
        object_types=object_types,
        evidence_classes=evidence_classes,
        triple_ids=None,
    )
    current_select = f"""
        SELECT requested.entity_id AS bucket_entity_id,
               g.triple_id, g.scope_key, g.scope_json, g.evidence_class,
               g.updated_at AS sort_at, 1 AS source_order,
               'current:' || g.triple_id AS snapshot_id, g.status,
               g.valid_from, g.valid_to, g.expires_at, g.first_observed_at,
               g.created_at AS edge_created_at
        FROM requested_entities AS requested
        JOIN knowledge_graph AS g ON {current_join}
        WHERE 1=1
          AND NOT EXISTS (
              SELECT 1 FROM memory_forget_claim_rules AS forgotten
              WHERE forgotten.target_kind = 'edge'
                AND forgotten.forget_kind = 'entity'
                AND forgotten.claim_fingerprint = g.claim_fingerprint
          )
    """
    current_select, current_args = _append_relationship_identity_filters(
        current_select,
        [],
        alias="g",
        evidence_alias=None,
        subject_id=None,
        entity_ids=None,
        direction=direction,
        object_id=object_id,
        predicates=predicates,
        object_types=object_types,
        evidence_classes=evidence_classes,
        triple_ids=None,
    )
    if requested_scope:
        eligible_scope_keys = matching_scope_keys(requested_scope)
        placeholders = ", ".join("?" for _ in eligible_scope_keys)
        scope_clause = f"scope_key IN ({placeholders})"
        scope_args: list[Any] = list(eligible_scope_keys)
    else:
        scope_clause = "scope_key = 'global'"
        scope_args = []
    if evidence_classes:
        placeholders = ", ".join("?" for _ in evidence_classes)
        evidence_clause = f"evidence_class IN ({placeholders})"
        evidence_args = [str(item).strip() for item in evidence_classes]
    else:
        evidence_clause = "1=1"
        evidence_args = []
    temporal_clause, temporal_args = _historical_candidate_temporal_clause(
        effective_at=effective_at,
        effective_range=effective_range,
    )
    candidate_sql = f"""
        WITH requested_entities(entity_id) AS (
            SELECT CAST(value AS TEXT) FROM json_each(?)
        ), snapshot_states AS (
            {version_select}
            UNION ALL
            {current_select}
        ), ordered_states AS (
            SELECT *,
                   MAX(CASE WHEN status = 'active' THEN sort_at END) OVER (
                       PARTITION BY bucket_entity_id, triple_id
                       ORDER BY sort_at, source_order, snapshot_id
                       ROWS BETWEEN UNBOUNDED PRECEDING AND 1 PRECEDING
                   ) AS previous_active_at,
                   MAX(
                       CASE
                           WHEN status != 'active' THEN COALESCE(valid_to, sort_at)
                       END
                   ) OVER (
                       PARTITION BY bucket_entity_id, triple_id
                       ORDER BY sort_at, source_order, snapshot_id
                       ROWS BETWEEN UNBOUNDED PRECEDING AND 1 PRECEDING
                   ) AS previous_inactive_closure,
                   MAX(CASE WHEN status != 'active' THEN sort_at END) OVER (
                       PARTITION BY bucket_entity_id, triple_id
                       ORDER BY sort_at, source_order, snapshot_id
                       ROWS BETWEEN UNBOUNDED PRECEDING AND 1 PRECEDING
                   ) AS previous_inactive_recorded_at
            FROM snapshot_states
        ), state_starts AS (
            SELECT *,
                   CASE
                       WHEN status != 'active' THEN NULL
                       WHEN previous_active_at IS NULL THEN COALESCE(
                           valid_from,
                           CASE
                               WHEN first_observed_at IS NOT NULL
                                    AND first_observed_at <= sort_at
                                    AND edge_created_at IS NOT NULL
                                    AND edge_created_at <= sort_at
                                   THEN MIN(first_observed_at, edge_created_at)
                               WHEN first_observed_at IS NOT NULL
                                    AND first_observed_at <= sort_at
                                   THEN first_observed_at
                               WHEN edge_created_at IS NOT NULL
                                    AND edge_created_at <= sort_at
                                   THEN edge_created_at
                               ELSE sort_at
                           END
                       )
                       WHEN valid_from IS NOT NULL
                            AND previous_inactive_closure IS NOT NULL
                            AND previous_inactive_recorded_at >= previous_active_at
                            AND valid_from >= previous_inactive_closure THEN valid_from
                       ELSE sort_at
                   END AS state_start
            FROM ordered_states
        ), candidate_states AS (
            SELECT *,
                   MIN(CASE WHEN status = 'active' THEN state_start END) OVER (
                       PARTITION BY bucket_entity_id, triple_id
                       ORDER BY sort_at, source_order, snapshot_id
                       ROWS BETWEEN 1 FOLLOWING AND UNBOUNDED FOLLOWING
                   ) AS next_active_start,
                   MIN(
                       CASE
                           WHEN status != 'active' THEN COALESCE(valid_to, sort_at)
                       END
                   ) OVER (
                       PARTITION BY bucket_entity_id, triple_id
                       ORDER BY sort_at, source_order, snapshot_id
                       ROWS BETWEEN 1 FOLLOWING AND UNBOUNDED FOLLOWING
                   ) AS next_inactive_closure
            FROM state_starts
        ), eligible_candidates AS (
            SELECT bucket_entity_id, triple_id,
                   MAX(json_array_length(scope_json, '$.all_of')) AS specificity,
                   MAX(sort_at) AS latest_at
            FROM candidate_states
            WHERE {scope_clause}
              AND {evidence_clause}
              AND {temporal_clause}
              AND status = 'active'
            GROUP BY bucket_entity_id, triple_id
        ), ranked_candidates AS (
            SELECT *, ROW_NUMBER() OVER (
                PARTITION BY bucket_entity_id
                ORDER BY specificity DESC, latest_at DESC, triple_id
            ) AS entity_rank
            FROM eligible_candidates
        )
        SELECT bucket_entity_id, triple_id
        FROM ranked_candidates
        WHERE entity_rank <= ?
        ORDER BY bucket_entity_id, entity_rank
    """
    return candidate_sql, [
        requested_json,
        *version_args,
        *current_args,
        *scope_args,
        *evidence_args,
        *temporal_args,
        bounded_scoped_candidate_limit(limit_per_entity),
    ]


def _batch_entity_join_clause(*, alias: str, direction: str) -> str:
    if direction == "incoming":
        return f"{alias}.object_id = requested.entity_id"
    if direction == "both":
        return (
            f"({alias}.subject_id = requested.entity_id "
            f"OR {alias}.object_id = requested.entity_id)"
        )
    return f"{alias}.subject_id = requested.entity_id"


async def _select_historical_candidate_triple_ids(
    host: L2RetrievalQueryHostProtocol,
    *,
    subject_id: str | None,
    entity_ids: List[str] | None,
    direction: str,
    object_id: str | None,
    predicates: List[str] | None,
    object_types: List[str] | None,
    evidence_classes: List[str] | None,
    triple_ids: List[str] | None,
    requested_scope: Mapping[str, Any],
    effective_at: float,
    effective_range: tuple[float | None, float | None] | None,
    limit: int,
) -> list[str]:
    """Select a bounded triple window before loading complete version chains."""
    candidate_sql, args = _build_historical_candidate_query(
        subject_id=subject_id,
        entity_ids=entity_ids,
        direction=direction,
        object_id=object_id,
        predicates=predicates,
        object_types=object_types,
        evidence_classes=evidence_classes,
        triple_ids=triple_ids,
        requested_scope=requested_scope,
        effective_at=effective_at,
        effective_range=effective_range,
        limit=limit,
    )
    async with sqlite_connection_async(host.db_path) as db:
        async with db.execute(candidate_sql, tuple(args)) as cursor:
            rows = await cursor.fetchall()
    return [str(row[0]) for row in rows]


def _build_historical_candidate_query(
    *,
    subject_id: str | None,
    entity_ids: List[str] | None,
    direction: str,
    object_id: str | None,
    predicates: List[str] | None,
    object_types: List[str] | None,
    evidence_classes: List[str] | None,
    triple_ids: List[str] | None,
    requested_scope: Mapping[str, Any],
    effective_at: float,
    effective_range: tuple[float | None, float | None] | None,
    limit: int,
) -> tuple[str, list[Any]]:
    """Build the bounded candidate query for execution and plan inspection."""
    version_select = """
        SELECT v.triple_id, v.scope_key, v.scope_json, v.evidence_class,
               v.created_at AS sort_at, 0 AS source_order,
               v.version_id AS snapshot_id, v.status, v.valid_from,
               v.valid_to, v.expires_at, v.first_observed_at,
               v.edge_created_at
        FROM knowledge_graph_versions v
        WHERE v.governance_complete = 1
          AND NOT EXISTS (
              SELECT 1 FROM memory_forget_claim_rules AS forgotten
              WHERE forgotten.target_kind = 'edge'
                AND forgotten.forget_kind = 'entity'
                AND forgotten.claim_fingerprint = v.claim_fingerprint
          )
    """
    version_select, version_args = _append_relationship_identity_filters(
        version_select,
        [],
        alias="v",
        evidence_alias=None,
        subject_id=subject_id,
        entity_ids=entity_ids,
        direction=direction,
        object_id=object_id,
        predicates=predicates,
        object_types=object_types,
        evidence_classes=evidence_classes,
        triple_ids=triple_ids,
    )
    current_select = """
        SELECT g.triple_id, g.scope_key, g.scope_json, g.evidence_class,
               g.updated_at AS sort_at, 1 AS source_order,
               'current:' || g.triple_id AS snapshot_id, g.status,
               g.valid_from, g.valid_to, g.expires_at, g.first_observed_at,
               g.created_at AS edge_created_at
        FROM knowledge_graph g
        WHERE 1=1
          AND NOT EXISTS (
              SELECT 1 FROM memory_forget_claim_rules AS forgotten
              WHERE forgotten.target_kind = 'edge'
                AND forgotten.forget_kind = 'entity'
                AND forgotten.claim_fingerprint = g.claim_fingerprint
          )
    """
    current_select, current_args = _append_relationship_identity_filters(
        current_select,
        [],
        alias="g",
        evidence_alias=None,
        subject_id=subject_id,
        entity_ids=entity_ids,
        direction=direction,
        object_id=object_id,
        predicates=predicates,
        object_types=object_types,
        evidence_classes=evidence_classes,
        triple_ids=triple_ids,
    )
    if requested_scope:
        eligible_scope_keys = matching_scope_keys(requested_scope)
        scope_placeholders = ", ".join("?" for _ in eligible_scope_keys)
        scope_clause = f"scope_key IN ({scope_placeholders})"
        scope_args: list[Any] = list(eligible_scope_keys)
    else:
        scope_clause = "scope_key = 'global'"
        scope_args = []
    if evidence_classes:
        evidence_placeholders = ", ".join("?" for _ in evidence_classes)
        evidence_clause = f"evidence_class IN ({evidence_placeholders})"
        evidence_args = [str(item).strip() for item in evidence_classes]
    else:
        evidence_clause = "1=1"
        evidence_args = []
    temporal_clause, temporal_args = _historical_candidate_temporal_clause(
        effective_at=effective_at,
        effective_range=effective_range,
    )

    candidate_sql = f"""
        WITH snapshot_states AS (
            {version_select}
            UNION ALL
            {current_select}
        ), ordered_states AS (
            SELECT *,
                   MAX(CASE WHEN status = 'active' THEN sort_at END) OVER (
                       PARTITION BY triple_id
                       ORDER BY sort_at, source_order, snapshot_id
                       ROWS BETWEEN UNBOUNDED PRECEDING AND 1 PRECEDING
                   ) AS previous_active_at,
                   MAX(
                       CASE
                           WHEN status != 'active' THEN COALESCE(valid_to, sort_at)
                       END
                   ) OVER (
                       PARTITION BY triple_id
                       ORDER BY sort_at, source_order, snapshot_id
                       ROWS BETWEEN UNBOUNDED PRECEDING AND 1 PRECEDING
                   ) AS previous_inactive_closure,
                   MAX(CASE WHEN status != 'active' THEN sort_at END) OVER (
                       PARTITION BY triple_id
                       ORDER BY sort_at, source_order, snapshot_id
                       ROWS BETWEEN UNBOUNDED PRECEDING AND 1 PRECEDING
                   ) AS previous_inactive_recorded_at
            FROM snapshot_states
        ), state_starts AS (
            SELECT *,
                   CASE
                       WHEN status != 'active' THEN NULL
                       WHEN previous_active_at IS NULL THEN COALESCE(
                           valid_from,
                           CASE
                               WHEN first_observed_at IS NOT NULL
                                    AND first_observed_at <= sort_at
                                    AND edge_created_at IS NOT NULL
                                    AND edge_created_at <= sort_at
                                   THEN MIN(first_observed_at, edge_created_at)
                               WHEN first_observed_at IS NOT NULL
                                    AND first_observed_at <= sort_at
                                   THEN first_observed_at
                               WHEN edge_created_at IS NOT NULL
                                    AND edge_created_at <= sort_at
                                   THEN edge_created_at
                               ELSE sort_at
                           END
                       )
                       WHEN valid_from IS NOT NULL
                            AND previous_inactive_closure IS NOT NULL
                            AND previous_inactive_recorded_at >= previous_active_at
                            AND valid_from >= previous_inactive_closure THEN valid_from
                       ELSE sort_at
                   END AS state_start
            FROM ordered_states
        ), candidate_states AS (
            SELECT *,
                   MIN(CASE WHEN status = 'active' THEN state_start END) OVER (
                       PARTITION BY triple_id
                       ORDER BY sort_at, source_order, snapshot_id
                       ROWS BETWEEN 1 FOLLOWING AND UNBOUNDED FOLLOWING
                   ) AS next_active_start,
                   MIN(
                       CASE
                           WHEN status != 'active' THEN COALESCE(valid_to, sort_at)
                       END
                   ) OVER (
                       PARTITION BY triple_id
                       ORDER BY sort_at, source_order, snapshot_id
                       ROWS BETWEEN 1 FOLLOWING AND UNBOUNDED FOLLOWING
                   ) AS next_inactive_closure
            FROM state_starts
        ), ranked_candidates AS (
            SELECT triple_id,
                   MAX(json_array_length(scope_json, '$.all_of')) AS specificity,
                   MAX(sort_at) AS latest_at
            FROM candidate_states
            WHERE {scope_clause}
              AND {evidence_clause}
              AND {temporal_clause}
              AND status = 'active'
            GROUP BY triple_id
            ORDER BY specificity DESC, latest_at DESC, triple_id
            LIMIT ?
        )
        SELECT triple_id
        FROM ranked_candidates
        ORDER BY specificity DESC, latest_at DESC, triple_id
    """
    args = [
        *version_args,
        *current_args,
        *scope_args,
        *evidence_args,
        *temporal_args,
        bounded_scoped_candidate_limit(limit),
    ]
    return candidate_sql, args


def _historical_candidate_temporal_clause(
    *,
    effective_at: float,
    effective_range: tuple[float | None, float | None] | None,
) -> tuple[str, list[float]]:
    clauses: list[str] = []
    args: list[float] = []
    if effective_range is None:
        clauses.extend(
            (
                "(state_start IS NULL OR state_start <= ?)",
                "(valid_to IS NULL OR valid_to > ?)",
                "(expires_at IS NULL OR expires_at > ?)",
                "(next_active_start IS NULL OR next_active_start > ?)",
                "(next_inactive_closure IS NULL OR next_inactive_closure > ?)",
            )
        )
        args.extend((effective_at,) * 5)
    else:
        range_start, range_end = effective_range
        if range_end is not None:
            clauses.append("(state_start IS NULL OR state_start <= ?)")
            args.append(float(range_end))
        if range_start is not None:
            clauses.append("(valid_to IS NULL OR valid_to > ?)")
            clauses.append("(expires_at IS NULL OR expires_at > ?)")
            clauses.append("(next_active_start IS NULL OR next_active_start > ?)")
            clauses.append("(next_inactive_closure IS NULL OR next_inactive_closure > ?)")
            args.extend((float(range_start),) * 4)
    return " AND ".join(clauses) if clauses else "1=1", args


def _append_relationship_identity_filters(
    sql: str,
    args: list[Any],
    *,
    alias: str,
    evidence_alias: str | None,
    subject_id: str | None,
    entity_ids: List[str] | None,
    direction: str,
    object_id: str | None,
    predicates: List[str] | None,
    object_types: List[str] | None,
    evidence_classes: List[str] | None,
    triple_ids: List[str] | None,
) -> tuple[str, list[Any]]:
    if subject_id:
        sql += f" AND {alias}.subject_id = ?"
        args.append(subject_id)
    if entity_ids:
        unique_ids = list(dict.fromkeys(str(item) for item in entity_ids if item))
        if not unique_ids:
            sql += " AND 0=1"
        else:
            placeholders = ", ".join("?" for _ in unique_ids)
            if direction == "incoming":
                sql += f" AND {alias}.object_id IN ({placeholders})"
                args.extend(unique_ids)
            elif direction == "both":
                sql += (
                    f" AND ({alias}.subject_id IN ({placeholders})"
                    f" OR {alias}.object_id IN ({placeholders}))"
                )
                args.extend(unique_ids)
                args.extend(unique_ids)
            else:
                sql += f" AND {alias}.subject_id IN ({placeholders})"
                args.extend(unique_ids)
    if object_id:
        sql += f" AND {alias}.object_id = ?"
        args.append(object_id)
    if predicates:
        placeholders = ", ".join("?" for _ in predicates)
        sql += f" AND {alias}.predicate IN ({placeholders})"
        args.extend(str(item).strip().upper() for item in predicates)
    if object_types:
        placeholders = ", ".join("?" for _ in object_types)
        sql += f" AND {alias}.object_type IN ({placeholders})"
        args.extend(str(item).strip().lower() for item in object_types)
    if evidence_classes and evidence_alias is not None:
        placeholders = ", ".join("?" for _ in evidence_classes)
        sql += f" AND {evidence_alias}.evidence_class IN ({placeholders})"
        args.extend(str(item).strip() for item in evidence_classes)
    if triple_ids:
        unique_triple_ids = list(dict.fromkeys(str(item) for item in triple_ids if item))
        if not unique_triple_ids:
            sql += " AND 0=1"
        else:
            placeholders = ", ".join("?" for _ in unique_triple_ids)
            sql += f" AND {alias}.triple_id IN ({placeholders})"
            args.extend(unique_triple_ids)
    return sql, args


def _relationship_matches_requested_filters(
    relationship: Mapping[str, Any],
    *,
    subject_id: str | None,
    entity_ids: List[str] | None,
    direction: str,
    object_id: str | None,
    predicates: List[str] | None,
    object_types: List[str] | None,
    evidence_classes: List[str] | None,
    triple_ids: List[str] | None,
) -> bool:
    """Apply identity filters after reconstructing a complete version chain."""
    relationship_subject = str(relationship.get("subject_id") or "")
    relationship_object = str(relationship.get("object_id") or "")
    if subject_id and relationship_subject != subject_id:
        return False
    if entity_ids:
        requested_entities = {str(item) for item in entity_ids if item}
        if not requested_entities:
            return False
        if direction == "incoming":
            if relationship_object not in requested_entities:
                return False
        elif direction == "both":
            if not ({relationship_subject, relationship_object} & requested_entities):
                return False
        elif relationship_subject not in requested_entities:
            return False
    if object_id and relationship_object != object_id:
        return False
    if predicates and str(relationship.get("predicate") or "").upper() not in {
        str(item).strip().upper() for item in predicates
    }:
        return False
    if object_types and str(relationship.get("object_type") or "").lower() not in {
        str(item).strip().lower() for item in object_types
    }:
        return False
    if evidence_classes and str(relationship.get("evidence_class") or "").strip() not in {
        str(item).strip() for item in evidence_classes
    }:
        return False
    if triple_ids and str(relationship.get("triple_id") or "") not in {
        str(item) for item in triple_ids if item
    }:
        return False
    return True


__all__ = ["_list_governed_relationship_history"]
