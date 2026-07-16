"""Graph-conflict persistence and resolution helpers for the L2 cognition store."""

from __future__ import annotations

from typing import Any, Mapping

import aiosqlite

from ....core.logger import get_logger
from ..graph_conflicts import (
    GraphConflictRule,
    build_graph_conflict_matrix,
    build_exclusive_group_index,
    iter_opposite_predicates,
)
from .versions import append_knowledge_graph_version

logger = get_logger(__name__)


class L2StoreGraphConflictMixin:
    """Resolve mutually exclusive graph facts and manage persisted conflict rules."""

    _exclusive_group_index: dict[str, tuple[str, ...]]
    _graph_conflict_rules: dict[str, GraphConflictRule]
    _seed_graph_conflict_rules: Mapping[str, GraphConflictRule | Mapping[str, Any]] | None

    async def _resolve_graph_conflicts(
        self,
        *,
        db: aiosqlite.Connection,
        triple_id: str,
        subject_id: str,
        predicate: str,
        object_id: str,
        scope_key: str,
        observed_at: float,
        now: float,
    ) -> None:
        rule = self._graph_conflict_rules.get(predicate)
        if rule is None:
            return

        for opposite_predicate in iter_opposite_predicates(rule):
            await self._apply_graph_status(
                db=db,
                status=self._status_from_action(rule.opposite_resolution),
                triple_id=triple_id,
                observed_at=observed_at,
                now=now,
                query="""
                UPDATE knowledge_graph
                SET status = ?, deprecated_by = ?, deprecated_at = ?, updated_at = ?
                WHERE subject_id = ? AND object_id = ? AND predicate = ?
                  AND scope_key = ? AND triple_id != ? AND status = 'active'
                  AND (valid_from IS NULL OR valid_from <= ?)
                  AND (valid_to IS NULL OR valid_to > ?)
                  AND (expires_at IS NULL OR expires_at > ?)
                """,
                args=(
                    subject_id,
                    object_id,
                    opposite_predicate,
                    scope_key,
                    triple_id,
                    observed_at,
                    observed_at,
                    observed_at,
                ),
            )

        if not rule.exclusive_group:
            return

        group_predicates = self._exclusive_group_index.get(rule.exclusive_group, ())
        if not group_predicates:
            return

        placeholders = ", ".join("?" for _ in group_predicates)
        await self._apply_graph_status(
            db=db,
            status=self._status_from_action(rule.exclusive_resolution),
            triple_id=triple_id,
            observed_at=observed_at,
            now=now,
            query=f"""
            UPDATE knowledge_graph
            SET status = ?, deprecated_by = ?, deprecated_at = ?, updated_at = ?
            WHERE subject_id = ? AND predicate IN ({placeholders})
              AND scope_key = ? AND triple_id != ? AND status = 'active'
              AND (predicate != ? OR object_id != ?)
              AND (valid_from IS NULL OR valid_from <= ?)
              AND (valid_to IS NULL OR valid_to > ?)
              AND (expires_at IS NULL OR expires_at > ?)
            """,
            args=(
                subject_id,
                *group_predicates,
                scope_key,
                triple_id,
                predicate,
                object_id,
                observed_at,
                observed_at,
                observed_at,
            ),
        )

    async def _apply_graph_status(
        self,
        *,
        db: aiosqlite.Connection,
        status: str,
        triple_id: str,
        observed_at: float,
        now: float,
        query: str,
        args: tuple[Any, ...],
    ) -> None:
        cursor = await db.execute(
            query,
            (
                status,
                triple_id,
                observed_at,
                now,
                *args,
            ),
        )
        if int(cursor.rowcount or 0) > 0:
            async with db.execute(
                """
                SELECT triple_id FROM knowledge_graph
                WHERE deprecated_by = ? AND deprecated_at = ?
                """,
                (triple_id, observed_at),
            ) as affected_cursor:
                affected_ids = [str(row[0]) for row in await affected_cursor.fetchall()]
            for affected_id in affected_ids:
                await append_knowledge_graph_version(
                    db,
                    triple_id=affected_id,
                    created_at=now,
                )
            logger.debug(
                "L2 graph conflict applied",
                source_triple_id=triple_id,
                next_status=status,
                affected_count=int(cursor.rowcount or 0),
            )

    @staticmethod
    def _status_from_action(action: str) -> str:
        if action == "mark_conflicted":
            return "conflicted"
        return "deprecated"

    async def _reload_graph_conflict_rules(self, db: aiosqlite.Connection) -> None:
        db.row_factory = aiosqlite.Row
        rules = build_graph_conflict_matrix(self._seed_graph_conflict_rules)
        async with db.execute(
            """
            SELECT predicate, opposite_predicates, opposite_resolution,
                   exclusive_group, exclusive_scope, exclusive_resolution
            FROM graph_conflict_rules
            ORDER BY predicate ASC
            """
        ) as cursor:
            rows = await cursor.fetchall()
        for row in rows:
            rule = GraphConflictRule.from_mapping(dict(row))
            rules[rule.predicate] = rule

        self._graph_conflict_rules = rules
        self._exclusive_group_index = build_exclusive_group_index(self._graph_conflict_rules)
