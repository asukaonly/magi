"""Shared helpers and protocol for L2 cognition retrieval mixins."""

from __future__ import annotations

import json
import math
from collections.abc import Mapping, Sequence
from itertools import combinations
from typing import Any, Dict, Protocol

import aiosqlite

from ...context_scope.models import context_conditions
from ..corrections.fingerprints import scope_specificity
from ..corrections.fingerprints import scope_key as correction_scope_key

SCOPED_QUERY_OVERFETCH_FACTOR = 8
SCOPED_QUERY_MIN_CANDIDATES = 32
SCOPED_QUERY_MAX_CANDIDATES = 512


def bounded_committed_candidates_sql(
    *,
    base_sql: str,
    committed_head_sql: str,
    normal_eligibility_sql: str,
    ordering_sql: str,
    partition_by_sql: str | None = None,
    result_ordering_sql: str | None = None,
    cte_prefix_sql: str | None = None,
) -> str:
    """Keep every committed transition head plus bounded ordinary candidates.

    A future transition can reuse an older deterministic record identity and
    temporarily overwrite that row with future metadata. Committed heads must
    bypass metadata filters and ranking until their durable snapshots have been
    restored. Ordinary candidates remain bounded by the caller's final bind.
    """
    rank_partition = "governed_candidate.governed_committed_head"
    if partition_by_sql:
        rank_partition = (
            f"{partition_by_sql}, governed_candidate.governed_committed_head"
        )
    result_ordering = (
        f"ORDER BY {result_ordering_sql}" if result_ordering_sql else ""
    )
    cte_prefix = f"{cte_prefix_sql}," if cte_prefix_sql else ""
    if partition_by_sql is None:
        return f"""
            WITH {cte_prefix} governed_base AS NOT MATERIALIZED (
                {base_sql}
            ), governed_heads AS (
                SELECT governed_candidate.*, 1 AS governed_committed_head,
                       0 AS governed_candidate_rank
                FROM governed_base AS governed_candidate
                WHERE {committed_head_sql}
            ), governed_normal AS (
                SELECT governed_candidate.*, 0 AS governed_committed_head,
                       0 AS governed_candidate_rank
                FROM governed_base AS governed_candidate
                WHERE NOT ({committed_head_sql})
                  AND ({normal_eligibility_sql})
                ORDER BY {ordering_sql}
                LIMIT ?
            )
            SELECT * FROM governed_heads
            UNION ALL
            SELECT * FROM governed_normal
            {result_ordering}
        """
    return f"""
        WITH {cte_prefix} governed_base AS (
            {base_sql}
        ), governed_classified AS (
            SELECT governed_candidate.*,
                   CASE WHEN {committed_head_sql} THEN 1 ELSE 0 END
                       AS governed_committed_head
            FROM governed_base AS governed_candidate
        ), governed_eligible AS (
            SELECT governed_candidate.*
            FROM governed_classified AS governed_candidate
            WHERE governed_candidate.governed_committed_head = 1
               OR ({normal_eligibility_sql})
        ), governed_ranked AS (
            SELECT governed_candidate.*,
                   ROW_NUMBER() OVER (
                       PARTITION BY {rank_partition}
                       ORDER BY {ordering_sql}
                   ) AS governed_candidate_rank
            FROM governed_eligible AS governed_candidate
        )
        SELECT *
        FROM governed_ranked
        WHERE governed_committed_head = 1
           OR governed_candidate_rank <= ?
        {result_ordering}
    """


def bounded_normal_candidates_sql(
    *,
    base_sql: str,
    normal_eligibility_sql: str,
    ordering_sql: str,
    partition_by_sql: str | None = None,
    result_ordering_sql: str | None = None,
    cte_prefix_sql: str | None = None,
) -> str:
    """Bound ordinary candidates without transition-head bookkeeping."""
    if partition_by_sql is None:
        return f"""
            SELECT governed_candidate.*
            FROM ({base_sql}) AS governed_candidate
            WHERE {normal_eligibility_sql}
            ORDER BY {ordering_sql}
            LIMIT ?
        """

    result_ordering = (
        f"ORDER BY {result_ordering_sql}" if result_ordering_sql else ""
    )
    cte_prefix = f"{cte_prefix_sql}," if cte_prefix_sql else ""
    return f"""
        WITH {cte_prefix} governed_base AS (
            {base_sql}
        ), governed_eligible AS (
            SELECT governed_candidate.*
            FROM governed_base AS governed_candidate
            WHERE {normal_eligibility_sql}
        ), governed_ranked AS (
            SELECT governed_candidate.*,
                   ROW_NUMBER() OVER (
                       PARTITION BY {partition_by_sql}
                       ORDER BY {ordering_sql}
                   ) AS governed_candidate_rank
            FROM governed_eligible AS governed_candidate
        )
        SELECT *
        FROM governed_ranked
        WHERE governed_candidate_rank <= ?
        {result_ordering}
    """


async def select_bounded_committed_candidates(
    db: aiosqlite.Connection,
    *,
    target_kind: str,
    identity_field: str,
    probe_base_sql: str,
    probe_base_args: tuple[Any, ...],
    probe_cte_prefix_sql: str | None = None,
    normal_sql: str,
    committed_sql: str,
    args: tuple[Any, ...],
) -> list[dict[str, Any]]:
    """Select committed candidates from one stable read snapshot.

    The ordinary query avoids transition bookkeeping when no scheduled
    transition exists. Once one does exist, the governed query keeps every
    durable head so snapshot restoration can run before mutable filters and
    final ranking.
    """
    if target_kind not in {"assertion", "edge"}:
        raise ValueError(f"Unsupported correction target kind: {target_kind}")
    probe_prefix = f"{probe_cte_prefix_sql}," if probe_cte_prefix_sql else ""
    probe_head = committed_situation_change_head_sql(
        target_kind=target_kind,
        row_id_sql=f"governed_probe.{identity_field}",
        authority_ref_sql="governed_probe.authority_ref",
    )
    pending_probe_sql = f"""
        WITH {probe_prefix} governed_probe_base AS NOT MATERIALIZED (
            {probe_base_sql}
        ), governed_pending_targets AS NOT MATERIALIZED (
            SELECT target_id
            FROM memory_corrections
                INDEXED BY idx_memory_corrections_due_transition
            WHERE target_kind = ?
              AND correction_kind = 'situation_changed'
              AND state = 'active'
              AND transition_applied_at IS NULL
              AND transition_cancelled_at IS NULL
        )
        SELECT EXISTS (
            SELECT 1
            FROM governed_pending_targets
            JOIN governed_probe_base AS governed_probe
              ON governed_probe.{identity_field}
                 = governed_pending_targets.target_id
            WHERE {probe_head}
            LIMIT 1
        )
    """
    await db.execute("BEGIN")
    try:
        async with db.execute(
            pending_probe_sql,
            (*probe_base_args, target_kind),
        ) as cursor:
            pending_row = await cursor.fetchone()
        has_pending_transition = bool(pending_row and pending_row[0])
        selected_sql = committed_sql if has_pending_transition else normal_sql
        async with db.execute(selected_sql, args) as cursor:
            rows = [dict(row) for row in await cursor.fetchall()]
        if has_pending_transition:
            rows = await restore_committed_situation_change_heads(
                db,
                target_kind=target_kind,
                rows=rows,
                identity_field=identity_field,
            )
        await db.commit()
        return rows
    except BaseException:
        await db.rollback()
        raise


def pending_situation_change_exists_sql(
    *,
    target_kind: str,
    row_id_sql: str,
    identity_column: str,
    authority_ref_sql: str | None = None,
) -> str:
    """Return one correlated check for an unapplied scheduled transition."""
    if target_kind not in {"assertion", "edge"}:
        raise ValueError(f"Unsupported correction target kind: {target_kind}")
    if identity_column not in {"target_id", "replacement_target_id"}:
        raise ValueError(f"Unsupported correction identity column: {identity_column}")
    ownership_sql = ""
    if authority_ref_sql is not None:
        if identity_column != "replacement_target_id":
            raise ValueError("Correction ownership applies only to replacement targets")
        ownership_sql = (
            f"\n              AND {authority_ref_sql} = "
            "'correction:' || pending_transition.correction_id"
        )
    return f"""
        EXISTS (
            SELECT 1
            FROM memory_corrections AS pending_transition
            WHERE pending_transition.target_kind = '{target_kind}'
              AND pending_transition.correction_kind = 'situation_changed'
              AND pending_transition.state = 'active'
              AND pending_transition.transition_applied_at IS NULL
              AND pending_transition.transition_cancelled_at IS NULL
              AND pending_transition.{identity_column} = {row_id_sql}
              {ownership_sql}
        )
    """


def committed_situation_change_head_sql(
    *,
    target_kind: str,
    row_id_sql: str,
    authority_ref_sql: str,
) -> str:
    """Return whether a row is the durable head of one pending transition chain.

    Pending transitions form a directed chain from the last committed claim to
    future replacements. A row can occur on both sides when a future sequence
    returns to an earlier value, so checking target/replacement membership
    independently is insufficient. The committed head is the target whose
    earliest outgoing transition precedes every pending transition into it.
    """
    if target_kind not in {"assertion", "edge"}:
        raise ValueError(f"Unsupported correction target kind: {target_kind}")
    return f"""
        EXISTS (
            SELECT 1
            FROM memory_corrections AS committed_outgoing
            WHERE committed_outgoing.target_kind = '{target_kind}'
              AND committed_outgoing.correction_kind = 'situation_changed'
              AND committed_outgoing.state = 'active'
              AND committed_outgoing.transition_applied_at IS NULL
              AND committed_outgoing.transition_cancelled_at IS NULL
              AND committed_outgoing.target_id = {row_id_sql}
              AND NOT EXISTS (
                  SELECT 1
                  FROM memory_corrections AS committed_incoming
                  WHERE committed_incoming.target_kind = '{target_kind}'
                    AND committed_incoming.correction_kind = 'situation_changed'
                    AND committed_incoming.state = 'active'
                    AND committed_incoming.transition_applied_at IS NULL
                    AND committed_incoming.transition_cancelled_at IS NULL
                    AND committed_incoming.replacement_target_id = {row_id_sql}
                    AND {authority_ref_sql}
                        = 'correction:' || committed_incoming.correction_id
                    AND (
                        COALESCE(
                            committed_incoming.effective_at,
                            committed_incoming.created_at
                        ) < COALESCE(
                            committed_outgoing.effective_at,
                            committed_outgoing.created_at
                        )
                        OR (
                            COALESCE(
                                committed_incoming.effective_at,
                                committed_incoming.created_at
                            ) = COALESCE(
                                committed_outgoing.effective_at,
                                committed_outgoing.created_at
                            )
                            AND (
                                committed_incoming.created_at
                                    < committed_outgoing.created_at
                                OR (
                                    committed_incoming.created_at
                                        = committed_outgoing.created_at
                                    AND committed_incoming.correction_id
                                        < committed_outgoing.correction_id
                                )
                            )
                        )
                    )
              )
        )
    """


async def restore_committed_situation_change_heads(
    db: aiosqlite.Connection,
    *,
    target_kind: str,
    rows: Sequence[Mapping[str, Any]],
    identity_field: str,
) -> list[dict[str, Any]]:
    """Replace reused future rows with the last committed durable snapshot."""
    if target_kind not in {"assertion", "edge"}:
        raise ValueError(f"Unsupported correction target kind: {target_kind}")
    row_dicts = [dict(row) for row in rows]
    candidate_ids = list(
        dict.fromkeys(str(row.get(identity_field) or "") for row in row_dicts if row.get(identity_field))
    )
    if not candidate_ids:
        return row_dicts

    candidate_json = json.dumps(candidate_ids, ensure_ascii=False, separators=(",", ":"))
    pending_sql = """
        correction_kind = 'situation_changed'
        AND state = 'active'
        AND transition_applied_at IS NULL
        AND transition_cancelled_at IS NULL
    """
    async with db.execute(
        f"""
        SELECT correction_id, target_id, replacement_target_id, before_json,
               effective_at, created_at, 'outgoing' AS transition_role
        FROM memory_corrections
        WHERE target_kind = ?
          AND {pending_sql}
          AND target_id IN (SELECT CAST(value AS TEXT) FROM json_each(?))
        UNION ALL
        SELECT correction_id, target_id, replacement_target_id, before_json,
               effective_at, created_at, 'incoming' AS transition_role
        FROM memory_corrections
        WHERE target_kind = ?
          AND {pending_sql}
          AND replacement_target_id IN (
              SELECT CAST(value AS TEXT) FROM json_each(?)
          )
        """,
        (target_kind, candidate_json, target_kind, candidate_json),
    ) as cursor:
        transitions = [dict(row) for row in await cursor.fetchall()]

    outgoing_by_id: dict[str, list[dict[str, Any]]] = {}
    incoming_by_id: dict[str, list[dict[str, Any]]] = {}
    for transition in transitions:
        if transition["transition_role"] == "outgoing":
            outgoing_by_id.setdefault(str(transition["target_id"]), []).append(transition)
        else:
            replacement_id = str(transition.get("replacement_target_id") or "")
            incoming_by_id.setdefault(replacement_id, []).append(transition)

    restored_by_id: dict[str, dict[str, Any]] = {}
    for row in row_dicts:
        row_id = str(row.get(identity_field) or "")
        authority_ref = str(row.get("authority_ref") or "")
        owned_incoming = [
            transition
            for transition in incoming_by_id.get(row_id, ())
            if authority_ref == f"correction:{transition['correction_id']}"
        ]
        incoming_keys = [_scheduled_transition_order(transition) for transition in owned_incoming]
        for outgoing in sorted(
            outgoing_by_id.get(row_id, ()),
            key=_scheduled_transition_order,
        ):
            outgoing_key = _scheduled_transition_order(outgoing)
            if any(incoming_key < outgoing_key for incoming_key in incoming_keys):
                continue
            snapshot = json.loads(str(outgoing["before_json"] or "{}"))
            if not isinstance(snapshot, dict):
                break
            restored_by_id[row_id] = snapshot
            break

    restored_rows: list[dict[str, Any]] = []
    for row in row_dicts:
        restored = restored_by_id.get(str(row.get(identity_field) or ""))
        if restored is None:
            restored_rows.append(row)
            continue
        restored_row = dict(restored)
        for transient_key in ("governed_bucket_entity_id", "governed_entity_rank"):
            if transient_key in row:
                restored_row[transient_key] = row[transient_key]
        restored_rows.append(restored_row)
    return restored_rows


def _scheduled_transition_order(transition: Mapping[str, Any]) -> tuple[float, float, str]:
    created_at = float(transition.get("created_at") or 0.0)
    return (
        float(transition.get("effective_at") or created_at),
        created_at,
        str(transition.get("correction_id") or ""),
    )


def bounded_scoped_candidate_limit(limit: int) -> int:
    """Bound scope-aware SQL candidates while leaving room for slot de-dup."""
    requested = max(1, int(limit))
    if requested >= SCOPED_QUERY_MAX_CANDIDATES:
        return requested
    return min(
        SCOPED_QUERY_MAX_CANDIDATES,
        max(
            SCOPED_QUERY_MIN_CANDIDATES,
            requested * SCOPED_QUERY_OVERFETCH_FACTOR,
        ),
    )


def matching_scope_keys(context_scope: Mapping[str, Any]) -> list[str]:
    """Return indexed scope identities for every subset of a query context."""
    conditions = context_conditions(context_scope)
    keys = ["global"]
    for size in range(1, len(conditions) + 1):
        for subset in combinations(conditions, size):
            keys.append(
                correction_scope_key({"all_of": [condition.to_dict() for condition in subset]})
            )
    return keys


def select_governed_range_rows(
    rows: list[Dict[str, Any]],
    *,
    identity_field: str,
    range_start: float | None,
    range_end: float | None,
    include_expired: bool = False,
    limit: int,
) -> list[Dict[str, Any]]:
    """Select every claim version that wins for some part of a time range.

    A more specific matching scope masks a broader scope only while the more
    specific row is valid. This preserves the broader historical version before
    a scoped override starts, while preventing two concurrent scope variants
    from leaking into the same range answer.
    """

    def priority(row: Dict[str, Any]) -> tuple[int, float, str]:
        return (
            scope_specificity(row.get("scope")),
            float(row.get("updated_at") or 0.0),
            str(row.get(identity_field) or ""),
        )

    ordered = sorted(rows, key=priority, reverse=True)
    rows_by_slot: dict[str, list[Dict[str, Any]]] = {}
    for row in ordered:
        slot = str(row.get("slot_key") or row.get(identity_field) or "")
        rows_by_slot.setdefault(slot, []).append(row)

    selected: list[Dict[str, Any]] = []
    for slot_rows in rows_by_slot.values():
        covered: list[tuple[float, float]] = []
        for row in slot_rows:
            interval = _claim_range_interval(
                row,
                range_start=range_start,
                range_end=range_end,
                include_expired=include_expired,
            )
            if interval is None:
                continue
            uncovered = _subtract_covered_interval(interval, covered)
            if not uncovered:
                continue
            selected_row = dict(row)
            selected_row["_governed_range_segments"] = [
                {
                    "start": None if math.isinf(start) and start < 0 else start,
                    "end": None if math.isinf(end) and end > 0 else end,
                }
                for start, end in uncovered
            ]
            selected.append(selected_row)
            covered = _merge_intervals([*covered, interval])

    selected.sort(key=priority, reverse=True)
    return selected[: max(1, int(limit))]


def _claim_range_interval(
    row: Dict[str, Any],
    *,
    range_start: float | None,
    range_end: float | None,
    include_expired: bool,
) -> tuple[float, float] | None:
    start = float(row["valid_from"]) if row.get("valid_from") is not None else -math.inf
    end_values = [
        float(value)
        for value in (
            row.get("valid_to"),
            None if include_expired else row.get("expires_at"),
        )
        if value is not None
    ]
    end = min(end_values, default=math.inf)
    if range_start is not None:
        start = max(start, float(range_start))
    if range_end is not None:
        end = min(end, float(range_end))
    return (start, end) if start < end else None


def _subtract_covered_interval(
    interval: tuple[float, float],
    covered: list[tuple[float, float]],
) -> list[tuple[float, float]]:
    remaining = [interval]
    for covered_start, covered_end in covered:
        next_remaining: list[tuple[float, float]] = []
        for start, end in remaining:
            if covered_end <= start or covered_start >= end:
                next_remaining.append((start, end))
                continue
            if covered_start > start:
                next_remaining.append((start, covered_start))
            if covered_end < end:
                next_remaining.append((covered_end, end))
        remaining = next_remaining
        if not remaining:
            break
    return remaining


def _merge_intervals(intervals: list[tuple[float, float]]) -> list[tuple[float, float]]:
    merged: list[tuple[float, float]] = []
    for start, end in sorted(intervals):
        if not merged or start > merged[-1][1]:
            merged.append((start, end))
            continue
        previous_start, previous_end = merged[-1]
        merged[-1] = (previous_start, max(previous_end, end))
    return merged


class L2RetrievalQueryHostProtocol(Protocol):
    db_path: str

    async def initialize(self) -> None: ...

    def _assertion_row_to_dict(self, row: aiosqlite.Row) -> Dict[str, Any]: ...

    def _snapshot_row_to_dict(self, row: aiosqlite.Row) -> Dict[str, Any]: ...

    def _relation_row_to_dict(self, row: aiosqlite.Row) -> Dict[str, Any]: ...
