"""ToM assertion retrieval helpers for the L2 cognition store."""

from __future__ import annotations

import json
import time
from collections.abc import Mapping
from typing import Any, Dict, List, Optional, cast

import aiosqlite

from ....core.sqlite import sqlite_connection_async
from ..assertions.state_machine import RETRIEVAL_EXCLUDED_STATUSES
from ..corrections.fingerprints import scope_matches, scope_specificity
from ...sql_search import build_like_search_clause
from .common import (
    L2RetrievalQueryHostProtocol,
    bounded_scoped_candidate_limit,
    matching_scope_keys,
    select_governed_range_rows,
)

CURRENT_EXCLUDED_STATUSES = ("superseded", *RETRIEVAL_EXCLUDED_STATUSES)


def _excluded_status_clause(*, include_superseded: bool = False) -> tuple[str, list[str]]:
    """SQL fragment + params excluding non-current assertion statuses."""
    statuses = RETRIEVAL_EXCLUDED_STATUSES if include_superseded else CURRENT_EXCLUDED_STATUSES
    placeholders = ", ".join("?" for _ in statuses)
    return f" AND status NOT IN ({placeholders})", list(statuses)


class L2StoreAssertionQueryMixin:
    """Read and batch-query ToM assertions."""

    async def list_current_assertions(
        self,
        *,
        entity_id: str | None = None,
        entity_ids: List[str] | None = None,
        entity_type: str | None = None,
        trait_families: List[str] | None = None,
        validation_states: List[str] | None = None,
        target_entity_id: str | None = None,
        context_scope: Mapping[str, Any] | None = None,
        effective_at: float | None = None,
        effective_range: tuple[float | None, float | None] | None = None,
        include_expired: bool = False,
        limit: int = 100,
    ) -> List[Dict[str, Any]]:
        """Return governed assertions that are valid at one point in time.

        This is the product-facing assertion read boundary. Lifecycle state,
        validity interval, expiration, and correction scope are applied before
        one winner per slot is selected. A superseded row is eligible only when
        it has an explicit ``valid_to`` and the requested point precedes it;
        this keeps future-dated situation changes continuous without reviving
        legacy superseded rows that have no governed validity interval.
        """
        host = cast(L2RetrievalQueryHostProtocol, self)
        await host.initialize()
        at = float(effective_at if effective_at is not None else time.time())
        requested_scope = dict(context_scope or {})
        query = "SELECT * FROM tom_trait_assertions WHERE 1=1"
        args: list[Any] = []
        if entity_id:
            query += " AND entity_id = ?"
            args.append(entity_id)
        if entity_ids:
            unique_entity_ids = list(dict.fromkeys(str(item) for item in entity_ids if item))
            if not unique_entity_ids:
                return []
            placeholders = ", ".join("?" for _ in unique_entity_ids)
            query += f" AND entity_id IN ({placeholders})"
            args.extend(unique_entity_ids)
        if entity_type:
            query += " AND entity_type = ?"
            args.append(entity_type)
        if trait_families:
            placeholders = ", ".join("?" for _ in trait_families)
            query += f" AND trait_family IN ({placeholders})"
            args.extend(str(item).strip().lower() for item in trait_families)
        if validation_states:
            placeholders = ", ".join("?" for _ in validation_states)
            query += f" AND validation_state IN ({placeholders})"
            args.extend(str(item).strip() for item in validation_states)
        if target_entity_id:
            query += " AND target_entity_id = ?"
            args.append(target_entity_id)
        status_sql, status_args = _excluded_status_clause(include_superseded=True)
        query += status_sql
        args.extend(status_args)
        query += " AND (status != 'superseded' OR valid_to IS NOT NULL)"
        if effective_range is None:
            query += " AND (valid_from IS NULL OR valid_from <= ?)"
            query += " AND (valid_to IS NULL OR valid_to > ?)"
            args.extend((at, at))
            if not include_expired:
                query += " AND (expires_at IS NULL OR expires_at > ?)"
                args.append(at)
        else:
            range_start, range_end = effective_range
            if range_end is not None:
                query += " AND (valid_from IS NULL OR valid_from <= ?)"
                args.append(float(range_end))
            if range_start is not None:
                query += " AND (valid_to IS NULL OR valid_to > ?)"
                args.append(float(range_start))
                if not include_expired:
                    query += " AND (expires_at IS NULL OR expires_at > ?)"
                    args.append(float(range_start))
        if not requested_scope:
            query += " AND scope_key = 'global'"
            query += " ORDER BY updated_at DESC"
            query += " LIMIT ?"
            args.append(max(1, int(limit)) * 4)
        else:
            eligible_scope_keys = matching_scope_keys(requested_scope)
            placeholders = ", ".join("?" for _ in eligible_scope_keys)
            query += f" AND scope_key IN ({placeholders})"
            args.extend(eligible_scope_keys)
            query += (
                " ORDER BY (SELECT COUNT(*) FROM json_each(scope_json)) DESC,"
                " updated_at DESC LIMIT ?"
            )
            args.append(bounded_scoped_candidate_limit(limit))

        async with sqlite_connection_async(host.db_path) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute(query, tuple(args)) as cursor:
                rows = await cursor.fetchall()

        assertions = [host._assertion_row_to_dict(row) for row in rows]
        assertions = [
            assertion
            for assertion in assertions
            if scope_matches(assertion.get("scope"), requested_scope)
        ]
        assertions.sort(
            key=lambda assertion: (
                scope_specificity(assertion.get("scope")),
                float(assertion.get("updated_at") or 0.0),
            ),
            reverse=True,
        )

        if effective_range is not None:
            return select_governed_range_rows(
                assertions,
                identity_field="assertion_id",
                range_start=effective_range[0],
                range_end=effective_range[1],
                include_expired=include_expired,
                limit=limit,
            )

        current_by_slot: dict[str, Dict[str, Any]] = {}
        for assertion in assertions:
            slot = assertion["slot_key"] or "\x1f".join(
                (
                    assertion["entity_type"],
                    assertion["entity_id"],
                    assertion["trait_name"],
                    assertion["target_entity_id"],
                )
            )
            current_by_slot.setdefault(slot, assertion)
            if len(current_by_slot) >= limit:
                break
        return list(current_by_slot.values())

    async def batch_list_current_assertions(
        self,
        *,
        entity_ids: List[str],
        entity_type: str | None = None,
        trait_families: List[str] | None = None,
        validation_states: List[str] | None = None,
        target_entity_id: str | None = None,
        context_scope: Mapping[str, Any] | None = None,
        effective_at: float | None = None,
        effective_range: tuple[float | None, float | None] | None = None,
        include_expired: bool = False,
        limit_per_entity: int = 100,
    ) -> Dict[str, List[Dict[str, Any]]]:
        """Return governed assertions for many entities using one SQL query."""
        host = cast(L2RetrievalQueryHostProtocol, self)
        await host.initialize()
        unique_ids = list(dict.fromkeys(str(item) for item in entity_ids if item))
        if not unique_ids:
            return {}

        at = float(effective_at if effective_at is not None else time.time())
        requested_scope = dict(context_scope or {})
        requested_limit = max(1, int(limit_per_entity))
        query = "SELECT assertions.* FROM tom_trait_assertions AS assertions WHERE 1=1"
        args: list[Any] = []
        query += " AND assertions.entity_id IN (SELECT CAST(value AS TEXT) FROM json_each(?))"
        args.append(json.dumps(unique_ids, ensure_ascii=False, separators=(",", ":")))
        if entity_type:
            query += " AND assertions.entity_type = ?"
            args.append(entity_type)
        if trait_families:
            placeholders = ", ".join("?" for _ in trait_families)
            query += f" AND assertions.trait_family IN ({placeholders})"
            args.extend(str(item).strip().lower() for item in trait_families)
        if validation_states:
            placeholders = ", ".join("?" for _ in validation_states)
            query += f" AND assertions.validation_state IN ({placeholders})"
            args.extend(str(item).strip() for item in validation_states)
        if target_entity_id:
            query += " AND assertions.target_entity_id = ?"
            args.append(target_entity_id)
        status_sql, status_args = _excluded_status_clause(include_superseded=True)
        query += status_sql
        args.extend(status_args)
        query += " AND (assertions.status != 'superseded' OR assertions.valid_to IS NOT NULL)"
        if effective_range is None:
            query += " AND (assertions.valid_from IS NULL OR assertions.valid_from <= ?)"
            query += " AND (assertions.valid_to IS NULL OR assertions.valid_to > ?)"
            args.extend((at, at))
            if not include_expired:
                query += " AND (assertions.expires_at IS NULL OR assertions.expires_at > ?)"
                args.append(at)
        else:
            range_start, range_end = effective_range
            if range_end is not None:
                query += " AND (assertions.valid_from IS NULL OR assertions.valid_from <= ?)"
                args.append(float(range_end))
            if range_start is not None:
                query += " AND (assertions.valid_to IS NULL OR assertions.valid_to > ?)"
                args.append(float(range_start))
                if not include_expired:
                    query += " AND (assertions.expires_at IS NULL OR assertions.expires_at > ?)"
                    args.append(float(range_start))
        if not requested_scope:
            query += " AND assertions.scope_key = 'global'"
            ordering = "assertions.updated_at DESC"
            candidate_limit = requested_limit * 4
        else:
            eligible_scope_keys = matching_scope_keys(requested_scope)
            placeholders = ", ".join("?" for _ in eligible_scope_keys)
            query += f" AND assertions.scope_key IN ({placeholders})"
            args.extend(eligible_scope_keys)
            ordering = (
                "(SELECT COUNT(*) FROM json_each(assertions.scope_json)) DESC, "
                "assertions.updated_at DESC"
            )
            candidate_limit = bounded_scoped_candidate_limit(requested_limit)

        ranked_query = f"""
            WITH ranked_assertions AS (
                SELECT candidates.*,
                       ROW_NUMBER() OVER (
                           PARTITION BY candidates.entity_id
                           ORDER BY {ordering.replace('assertions.', 'candidates.')}
                       ) AS governed_entity_rank
                FROM ({query}) AS candidates
            )
            SELECT *
            FROM ranked_assertions
            WHERE governed_entity_rank <= ?
            ORDER BY entity_id, governed_entity_rank
        """
        args.append(candidate_limit)
        async with sqlite_connection_async(host.db_path) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute(ranked_query, tuple(args)) as cursor:
                rows = await cursor.fetchall()

        candidates: Dict[str, List[Dict[str, Any]]] = {entity_id: [] for entity_id in unique_ids}
        for row in rows:
            assertion = host._assertion_row_to_dict(row)
            candidates[str(assertion["entity_id"])].append(assertion)

        result: Dict[str, List[Dict[str, Any]]] = {}
        for entity_id, assertions in candidates.items():
            assertions = [
                assertion
                for assertion in assertions
                if scope_matches(assertion.get("scope"), requested_scope)
            ]
            assertions.sort(
                key=lambda assertion: (
                    scope_specificity(assertion.get("scope")),
                    float(assertion.get("updated_at") or 0.0),
                ),
                reverse=True,
            )
            if effective_range is not None:
                result[entity_id] = select_governed_range_rows(
                    assertions,
                    identity_field="assertion_id",
                    range_start=effective_range[0],
                    range_end=effective_range[1],
                    include_expired=include_expired,
                    limit=requested_limit,
                )
                continue
            current_by_slot: dict[str, Dict[str, Any]] = {}
            for assertion in assertions:
                slot = assertion["slot_key"] or "\x1f".join(
                    (
                        assertion["entity_type"],
                        assertion["entity_id"],
                        assertion["trait_name"],
                        assertion["target_entity_id"],
                    )
                )
                current_by_slot.setdefault(slot, assertion)
                if len(current_by_slot) >= requested_limit:
                    break
            result[entity_id] = list(current_by_slot.values())
        return result

    async def count_tom_assertions(
        self,
        *,
        entity_id: Optional[str] = None,
        entity_type: Optional[str] = None,
        trait_families: Optional[List[str]] = None,
        validation_states: Optional[List[str]] = None,
        include_expired: bool = True,
        include_inactive: bool = False,
        include_superseded: bool = False,
        target_entity_id: Optional[str] = None,
        temporal_clause: Optional[tuple[str, list[Any]]] = None,
        query: str | None = None,
    ) -> int:
        """Count ToM assertions with the same filters as list_tom_assertions."""
        host = cast(L2RetrievalQueryHostProtocol, self)
        await host.initialize()
        search_query = query
        sql = "SELECT COUNT(*) FROM tom_trait_assertions WHERE 1=1"
        args: list[Any] = []
        if entity_id:
            sql += " AND entity_id = ?"
            args.append(entity_id)
        if entity_type:
            sql += " AND entity_type = ?"
            args.append(entity_type)
        if trait_families:
            placeholders = ", ".join("?" for _ in trait_families)
            sql += f" AND trait_family IN ({placeholders})"
            args.extend([str(item).strip().lower() for item in trait_families])
        if validation_states:
            placeholders = ", ".join("?" for _ in validation_states)
            sql += f" AND validation_state IN ({placeholders})"
            args.extend([str(item).strip() for item in validation_states])
        if target_entity_id:
            sql += " AND target_entity_id = ?"
            args.append(target_entity_id)
        if not include_expired:
            now = time.time()
            sql += " AND (expires_at IS NULL OR expires_at > ?)"
            args.append(now)
        if not include_inactive:
            status_sql, status_args = _excluded_status_clause(include_superseded=include_superseded)
            sql += status_sql
            args.extend(status_args)
        if temporal_clause:
            tc_sql, tc_params = temporal_clause
            if tc_sql:
                sql += f" AND {tc_sql}"
                args.extend(tc_params)
        search_sql, search_args = build_like_search_clause(
            [
                "assertion_id",
                "entity_id",
                "entity_type",
                "trait_family",
                "trait_name",
                "trait_value",
                "evidence_events",
                "source_domain",
                "inference_depth",
                "validation_state",
                "target_entity_id",
                "target_entity_type",
                "target_scope",
                "temporal_scope",
                "context_ref_id",
                "status",
                "superseded_by",
                "memory_subdomain",
                "natural_summary",
            ],
            search_query,
        )
        sql += search_sql
        args.extend(search_args)
        async with sqlite_connection_async(host.db_path) as db:
            async with db.execute(sql, tuple(args)) as cursor:
                row = await cursor.fetchone()
        return int(row[0]) if row else 0

    async def list_tom_assertions(
        self,
        *,
        entity_id: Optional[str] = None,
        entity_type: Optional[str] = None,
        trait_families: Optional[List[str]] = None,
        validation_states: Optional[List[str]] = None,
        include_expired: bool = True,
        include_inactive: bool = False,
        include_superseded: bool = False,
        target_entity_id: Optional[str] = None,
        limit: int = 100,
        offset: int = 0,
        temporal_clause: Optional[tuple[str, list[Any]]] = None,
        query: str | None = None,
    ) -> List[Dict[str, Any]]:
        """List ToM assertions ordered by recency.

        By default non-current rows are excluded; pass ``include_superseded=True``
        for historical reads or ``include_inactive=True`` for admin/debug reads.
        """
        host = cast(L2RetrievalQueryHostProtocol, self)
        await host.initialize()
        search_query = query
        query = "SELECT * FROM tom_trait_assertions WHERE 1=1"
        args: list[Any] = []
        if entity_id:
            query += " AND entity_id = ?"
            args.append(entity_id)
        if entity_type:
            query += " AND entity_type = ?"
            args.append(entity_type)
        if trait_families:
            placeholders = ", ".join("?" for _ in trait_families)
            query += f" AND trait_family IN ({placeholders})"
            args.extend([str(item).strip().lower() for item in trait_families])
        if validation_states:
            placeholders = ", ".join("?" for _ in validation_states)
            query += f" AND validation_state IN ({placeholders})"
            args.extend([str(item).strip() for item in validation_states])
        if target_entity_id:
            query += " AND target_entity_id = ?"
            args.append(target_entity_id)
        if not include_expired:
            now = time.time()
            query += " AND (expires_at IS NULL OR expires_at > ?)"
            args.append(now)
        if not include_inactive:
            status_sql, status_args = _excluded_status_clause(include_superseded=include_superseded)
            query += status_sql
            args.extend(status_args)
        if temporal_clause:
            tc_sql, tc_params = temporal_clause
            if tc_sql:
                query += f" AND {tc_sql}"
                args.extend(tc_params)
        search_sql, search_args = build_like_search_clause(
            [
                "assertion_id",
                "entity_id",
                "entity_type",
                "trait_family",
                "trait_name",
                "trait_value",
                "evidence_events",
                "source_domain",
                "inference_depth",
                "validation_state",
                "target_entity_id",
                "target_entity_type",
                "target_scope",
                "temporal_scope",
                "context_ref_id",
                "status",
                "superseded_by",
                "memory_subdomain",
                "natural_summary",
            ],
            search_query,
        )
        query += search_sql
        args.extend(search_args)
        query += " ORDER BY updated_at DESC LIMIT ? OFFSET ?"
        args.append(int(limit))
        args.append(int(offset))

        async with sqlite_connection_async(host.db_path) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute(query, tuple(args)) as cursor:
                rows = await cursor.fetchall()
        return [host._assertion_row_to_dict(row) for row in rows]

    async def list_assertions_for_episode(
        self,
        *,
        episode_id: str,
        limit: int = 100,
        event_limit: int = 500,
    ) -> List[Dict[str, Any]]:
        """List live assertions inferred from events in an episode.

        The link is derived, not stored: an assertion belongs to an episode when
        its ``evidence_events`` JSON array overlaps the episode's membership
        rows. Keep the event-id set bounded so this query stays a detail-page
        lookup instead of becoming an unbounded scan.
        """
        host = cast(L2RetrievalQueryHostProtocol, self)
        await host.initialize()

        async with sqlite_connection_async(host.db_path) as db:
            async with db.execute(
                """
                SELECT event_id
                FROM episode_events
                WHERE episode_id = ?
                ORDER BY added_at ASC
                LIMIT ?
                """,
                (episode_id, int(event_limit)),
            ) as cursor:
                event_rows = await cursor.fetchall()

        event_ids = [str(row[0]) for row in event_rows if row and row[0]]
        if not event_ids:
            return []

        event_placeholders = ", ".join("?" for _ in event_ids)
        status_sql, status_args = _excluded_status_clause()
        query = f"""
            SELECT DISTINCT a.*
            FROM tom_trait_assertions AS a
            JOIN json_each(a.evidence_events) AS evidence
              ON evidence.value IN ({event_placeholders})
            WHERE 1=1
            {status_sql}
            ORDER BY a.updated_at DESC
            LIMIT ?
        """
        args: list[Any] = [*event_ids, *status_args, int(limit)]

        async with sqlite_connection_async(host.db_path) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute(query, tuple(args)) as cursor:
                rows = await cursor.fetchall()
        return [host._assertion_row_to_dict(row) for row in rows]

    async def expire_session_decay_assertions(
        self,
        *,
        entity_ids: List[str],
    ) -> int:
        """Mark tentative session-decay assertions as expired for the given entities."""
        if not entity_ids:
            return 0
        host = cast(L2RetrievalQueryHostProtocol, self)
        await host.initialize()
        now = time.time()
        placeholders = ", ".join("?" for _ in entity_ids)
        async with sqlite_connection_async(host.db_path) as db:
            cursor = await db.execute(
                f"""
                UPDATE tom_trait_assertions
                SET validation_state = 'expired', status = 'expired',
                    expires_at = ?, updated_at = ?
                WHERE entity_id IN ({placeholders})
                  AND decay_policy = 'session_decay'
                  AND validation_state = 'tentative'
                """,
                (now, now, *entity_ids),
            )
            count = int(cursor.rowcount)
            await db.commit()
        return count

    async def list_assertions_by_status(
        self,
        status: str,
        *,
        entity_id: Optional[str] = None,
        limit: int = 500,
    ) -> List[Dict[str, Any]]:
        """Return all assertion rows with the given ``status`` value.

        This is a low-level admin/maintenance query that bypasses the normal
        ``RETRIEVAL_EXCLUDED_STATUSES`` filter intentionally — for example, to
        fetch ``status='shadow'`` rows that the normal read path hides.
        """
        host = cast(L2RetrievalQueryHostProtocol, self)
        await host.initialize()
        query = "SELECT * FROM tom_trait_assertions WHERE status = ?"
        args: list[Any] = [status]
        if entity_id:
            query += " AND entity_id = ?"
            args.append(entity_id)
        query += " ORDER BY updated_at DESC LIMIT ?"
        args.append(int(limit))
        async with sqlite_connection_async(host.db_path) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute(query, tuple(args)) as cursor:
                rows = await cursor.fetchall()
        return [host._assertion_row_to_dict(row) for row in rows]

    async def get_tom_assertion(self, *, assertion_id: str) -> Optional[Dict[str, Any]]:
        """Fetch one ToM assertion by id."""
        host = cast(L2RetrievalQueryHostProtocol, self)
        await host.initialize()
        async with aiosqlite.connect(host.db_path) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute(
                "SELECT * FROM tom_trait_assertions WHERE assertion_id = ?",
                (assertion_id,),
            ) as cursor:
                row = await cursor.fetchone()
        return host._assertion_row_to_dict(row) if row else None

    async def batch_list_tom_assertions(
        self,
        *,
        entity_ids: List[str],
        entity_type: Optional[str] = None,
        trait_families: Optional[List[str]] = None,
        validation_states: Optional[List[str]] = None,
        include_expired: bool = False,
        include_inactive: bool = False,
        include_superseded: bool = False,
        target_entity_id: Optional[str] = None,
        limit_per_entity: int = 100,
        temporal_clause: Optional[tuple[str, list[Any]]] = None,
    ) -> Dict[str, List[Dict[str, Any]]]:
        """Batch-fetch assertions for multiple entities in one query.

        Non-current rows are excluded by default; pass ``include_superseded=True``
        for historical reads or ``include_inactive=True`` for admin/debug reads.
        """
        host = cast(L2RetrievalQueryHostProtocol, self)
        await host.initialize()
        if not entity_ids:
            return {}

        unique_ids = list(dict.fromkeys(entity_ids))
        id_placeholders = ", ".join("?" for _ in unique_ids)
        query = f"SELECT * FROM tom_trait_assertions WHERE entity_id IN ({id_placeholders})"
        args: list[Any] = list(unique_ids)

        if entity_type:
            query += " AND entity_type = ?"
            args.append(entity_type)
        if trait_families:
            tf_ph = ", ".join("?" for _ in trait_families)
            query += f" AND trait_family IN ({tf_ph})"
            args.extend(str(tf).strip().lower() for tf in trait_families)
        if validation_states:
            vs_ph = ", ".join("?" for _ in validation_states)
            query += f" AND validation_state IN ({vs_ph})"
            args.extend(str(vs).strip() for vs in validation_states)
        if target_entity_id:
            query += " AND target_entity_id = ?"
            args.append(target_entity_id)
        if not include_expired:
            now = time.time()
            query += " AND (expires_at IS NULL OR expires_at > ?)"
            args.append(now)
        if not include_inactive:
            status_sql, status_args = _excluded_status_clause(include_superseded=include_superseded)
            query += status_sql
            args.extend(status_args)
        if temporal_clause:
            tc_sql, tc_params = temporal_clause
            if tc_sql:
                query += f" AND {tc_sql}"
                args.extend(tc_params)
        query += " ORDER BY updated_at DESC"

        async with sqlite_connection_async(host.db_path) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute(query, tuple(args)) as cursor:
                rows = await cursor.fetchall()

        result: Dict[str, List[Dict[str, Any]]] = {eid: [] for eid in unique_ids}
        for row in rows:
            assertion = host._assertion_row_to_dict(row)
            eid = assertion["entity_id"]
            if eid in result and len(result[eid]) < limit_per_entity:
                result[eid].append(assertion)
        return result
