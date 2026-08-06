"""User-driven rejection and forgetting helpers for the L2 cognition store."""

from __future__ import annotations

import json
import math
import time
import uuid
from dataclasses import asdict
from typing import Any, Dict, Mapping, Optional, Protocol, cast

import aiosqlite

from ....core.logger import get_logger
from ....core.sqlite import sqlite_connection_async
from ..claims.repository import redact_grounded_claims_by_ids
from ..claims.reprojection_write import retire_claim_target_authority_on_connection
from ..corrections.cache_signals import mark_subject_changed
from ..corrections.evidence_ledger import (
    claim_evidence_records_for_claims,
    refresh_claim_evidence_timestamps,
)
from ..corrections.fingerprints import (
    assertion_claim_fingerprint,
    assertion_slot_key,
    relationship_claim_fingerprint,
    relationship_slot_key,
)
from ..corrections.forget_governance import ForgottenClaim, decode_evidence_event_ids
from ..corrections.forget_lineage import apply_correction_forget_barriers
from ..corrections.models import (
    ApplyRelationshipCorrectionCommand,
    CorrectionKind,
    CorrectionTargetKind,
)
from ..corrections.repository import MemoryCorrectionRepository
from ..corrections.service import MemoryCorrectionService
from ..experiences.episode_forgetting import (
    invalidate_episode_dependencies,
    invalidate_episode_dependencies_many,
)
from ..graph_conflicts import GraphConflictRule
from ..storage.utils import max_evidence_event_ids
from .derivation_refresh import (
    invalidate_forgotten_derivations,
    rebuild_forgotten_subject_views,
)

logger = get_logger(__name__)

_FORGET_AUTHORITY_PREFIX = "forget:"
_EVIDENCE_TIMESTAMP_REFRESH_BATCH_SIZE = 500


class _ForgettingHostProtocol(Protocol):
    db_path: str
    _graph_conflict_rules: Mapping[str, GraphConflictRule]

    async def initialize(self) -> None: ...

    async def get_relationship(self, *, triple_id: str) -> Optional[Dict[str, Any]]: ...

    def _relation_row_to_dict(self, row: Any) -> Dict[str, Any]: ...

    async def wake_memory_correction_jobs(self) -> bool: ...

    async def resolve_evidence_timestamps(
        self,
        event_ids: list[str],
    ) -> Dict[str, float]: ...

    async def _stage_entity_link_forget_on_connection(
        self,
        db: aiosqlite.Connection,
        *,
        entity_id: str,
        operation_key: str,
    ) -> int: ...


class L2StoreForgettingMixin:
    """Apply user rejection and forgetting actions to L2 records."""

    async def reject_edge(
        self,
        *,
        triple_id: str,
        audit_event_id: str | None = None,
    ) -> Optional[Dict[str, Any]]:
        """Reject a KG edge through durable correction governance."""
        host = cast(_ForgettingHostProtocol, self)
        await host.initialize()
        existing = await host.get_relationship(triple_id=triple_id)
        if existing is None:
            return None
        if existing["status"] == "user_rejected":
            return existing
        await self.apply_relationship_correction(
            triple_id=triple_id,
            request_id=f"edge_rejection_{uuid.uuid4().hex}",
            actor_id="local_user",
            correction_kind=CorrectionKind.RECORD_ERROR,
            audit_event_id=audit_event_id,
        )
        return await host.get_relationship(triple_id=triple_id)

    async def apply_relationship_correction(
        self,
        *,
        triple_id: str,
        request_id: str,
        actor_id: str,
        correction_kind: CorrectionKind | str,
        replacement: Dict[str, Any] | None = None,
        reason: str | None = None,
        effective_at: float | None = None,
        scope: Dict[str, Any] | None = None,
        source_event_id: str | None = None,
        audit_event_id: str | None = None,
        expected_updated_at: float | None = None,
    ) -> Optional[Dict[str, Any]]:
        """Apply a governed correction to one relationship."""
        host = cast(_ForgettingHostProtocol, self)
        await host.initialize()
        existing_request = await MemoryCorrectionRepository(host.db_path).get_by_request_id(
            request_id
        )
        current = (
            existing_request.before
            if existing_request is not None
            and existing_request.target_kind == CorrectionTargetKind.EDGE
            else await host.get_relationship(triple_id=triple_id)
        )
        if current is None and existing_request is None:
            return None
        normalized_replacement = dict(replacement) if replacement is not None else None
        source_event_timestamps = (
            await host.resolve_evidence_timestamps([source_event_id])
            if source_event_id is not None
            else {}
        )
        source_event_observed_at = (
            source_event_timestamps.get(source_event_id)
            if source_event_id is not None
            else None
        )
        result = await MemoryCorrectionService(
            host.db_path,
            graph_conflict_rules=host._graph_conflict_rules,
        ).apply_relationship_correction(
            ApplyRelationshipCorrectionCommand(
                triple_id=triple_id,
                request_id=request_id,
                actor_id=actor_id,
                correction_kind=CorrectionKind(correction_kind),
                replacement=normalized_replacement,
                reason=reason,
                effective_at=effective_at,
                scope=scope,
                source_event_id=source_event_id,
                source_event_observed_at=source_event_observed_at,
                audit_event_id=audit_event_id,
                expected_updated_at=expected_updated_at,
            )
        )
        if result is None:
            return None
        await host.wake_memory_correction_jobs()
        current_relationship = (
            host._relation_row_to_dict(result.current_claim)
            if result.current_claim is not None
            else None
        )
        logger.info(
            "L2 relationship correction applied",
            correction_id=result.correction.correction_id,
            triple_id=triple_id,
            replacement_triple_id=result.correction.replacement_target_id,
            correction_kind=result.correction.correction_kind.value,
            created=result.created,
        )
        return {
            "correction": asdict(result.correction),
            "current_relationship": current_relationship,
            "subject_revision": result.subject_revision,
            "created": result.created,
        }

    async def revert_relationship_correction(
        self,
        *,
        correction_id: str,
        request_id: str,
        actor_id: str = "local_user",
    ) -> Optional[Dict[str, Any]]:
        """Revert one relationship correction."""
        host = cast(_ForgettingHostProtocol, self)
        await host.initialize()
        result = await MemoryCorrectionService(host.db_path).revert_relationship_correction(
            correction_id=correction_id,
            request_id=request_id,
            actor_id=actor_id,
        )
        if result is None:
            return None
        await host.wake_memory_correction_jobs()
        current_relationship = (
            host._relation_row_to_dict(result.current_claim)
            if result.current_claim is not None
            else None
        )
        return {
            "correction": asdict(result.correction),
            "current_relationship": current_relationship,
            "subject_revision": result.subject_revision,
            "created": result.created,
        }

    async def get_relationship_correction_history(
        self,
        *,
        triple_id: str,
    ) -> Dict[str, Any]:
        """Return immutable versions and corrections for a relationship."""
        host = cast(_ForgettingHostProtocol, self)
        await host.initialize()
        history = await MemoryCorrectionService(host.db_path).get_relationship_correction_history(
            triple_id=triple_id
        )
        return {
            "versions": history["versions"],
            "corrections": [asdict(item) for item in history["corrections"]],
        }

    async def list_relationship_corrections(
        self,
        *,
        triple_id: str,
        limit: int = 100,
    ) -> list[Dict[str, Any]]:
        """List corrections originally applied to one relationship."""
        host = cast(_ForgettingHostProtocol, self)
        await host.initialize()
        corrections = await MemoryCorrectionRepository(host.db_path).list_for_target(
            target_kind=CorrectionTargetKind.EDGE,
            target_id=triple_id,
            limit=limit,
        )
        return [asdict(item) for item in corrections]

    async def forget_entity(
        self,
        *,
        entity_id: str,
        operation_key: str | None = None,
    ) -> Dict[str, int]:
        """Cascade soft-delete everything derived from an entity."""
        host = cast(_ForgettingHostProtocol, self)
        await host.initialize()
        counts: Dict[str, int] = {}

        async with sqlite_connection_async(host.db_path) as db:
            db.row_factory = aiosqlite.Row
            await db.execute("BEGIN IMMEDIATE")
            now = time.time()
            forgotten_edges = await _relationship_claims(
                db,
                "subject_id = ? OR object_id = ?",
                (entity_id, entity_id),
            )
            historical_edges = await _historical_relationship_claims_for_entity(
                db,
                entity_id=entity_id,
            )
            forgotten_edges = _merge_forgotten_claims(
                forgotten_edges,
                historical_edges,
            )
            forgotten_assertions = await _assertion_claims(
                db,
                "entity_id = ? OR target_entity_id = ?",
                (entity_id, entity_id),
            )
            async with db.execute(
                """
                SELECT DISTINCT claims.claim_id
                FROM l2_grounded_claims AS claims
                LEFT JOIN l2_claim_entity_refs AS refs
                  ON refs.claim_id = claims.claim_id
                WHERE claims.availability = 'active'
                  AND (claims.subject_ref = ? OR refs.entity_id = ?)
                ORDER BY claims.claim_id
                """,
                (entity_id, entity_id),
            ) as cursor:
                grounded_claim_ids = [str(row[0]) for row in await cursor.fetchall()]
            claim_target_retirement = await retire_claim_target_authority_on_connection(
                db,
                claim_ids=grounded_claim_ids,
                invalidated_reason="entity_forgotten",
                changed_at=now,
            )
            counts.update(
                await redact_grounded_claims_by_ids(
                    db,
                    claim_ids=grounded_claim_ids,
                    reason=f"forget_entity:{entity_id}",
                    invalidated_reason="entity_forgotten",
                    now=now,
                )
            )
            cursor = await db.execute(
                """
                UPDATE knowledge_graph
                SET status = 'archived', status_reason = 'user_forget',
                    authority_ref = ?, updated_at = ?
                WHERE (subject_id = ? OR object_id = ?) AND status NOT IN ('archived', 'user_rejected')
                """,
                (f"{_FORGET_AUTHORITY_PREFIX}entity", now, entity_id, entity_id),
            )
            counts["knowledge_graph"] = (
                max(int(cursor.rowcount or 0), 0) + claim_target_retirement.relationships_archived
            )
            await db.execute(
                """
                UPDATE knowledge_graph
                SET status = 'archived', status_reason = 'user_forget',
                    authority_ref = ?, updated_at = ?
                WHERE (subject_id = ? OR object_id = ?)
                  AND COALESCE(authority_ref, '') != ?
                """,
                (
                    f"{_FORGET_AUTHORITY_PREFIX}entity",
                    now,
                    entity_id,
                    entity_id,
                    f"{_FORGET_AUTHORITY_PREFIX}entity",
                ),
            )

            cursor = await db.execute(
                """
                UPDATE tom_trait_assertions SET status = 'archived', updated_at = ?
                WHERE (entity_id = ? OR target_entity_id = ?) AND status NOT IN ('archived', 'user_rejected')
                """,
                (now, entity_id, entity_id),
            )
            counts["tom_trait_assertions"] = (
                max(int(cursor.rowcount or 0), 0) + claim_target_retirement.assertions_archived
            )
            counts["l2_pending_reviews"] = claim_target_retirement.reviews_closed
            await db.execute(
                """
                UPDATE tom_trait_assertions
                SET status = 'archived', authority_ref = ?, updated_at = ?
                WHERE (entity_id = ? OR target_entity_id = ?)
                  AND COALESCE(authority_ref, '') != ?
                """,
                (
                    f"{_FORGET_AUTHORITY_PREFIX}entity",
                    now,
                    entity_id,
                    entity_id,
                    f"{_FORGET_AUTHORITY_PREFIX}entity",
                ),
            )

            cursor = await db.execute(
                """
                UPDATE entity_facets SET status = 'archived', updated_at = ?
                WHERE entity_id = ? AND status != 'archived'
                """,
                (now, entity_id),
            )
            counts["entity_facets"] = cursor.rowcount

            episode_counts = await _invalidate_matching_episodes(
                db,
                where_clause="""
                    EXISTS (
                        SELECT 1
                        FROM json_each(CASE
                            WHEN json_valid(episodes.primary_entity_ids)
                                THEN episodes.primary_entity_ids
                            ELSE '[]'
                        END) AS entity
                        WHERE CAST(entity.value AS TEXT) = ?
                    )
                """,
                parameters=(entity_id,),
                now=now,
            )
            counts.update(episode_counts)

            await apply_correction_forget_barriers(
                db,
                forgotten_assertions=forgotten_assertions,
                forgotten_edges=forgotten_edges,
                now=now,
                permanently_block_claims=True,
                cancel_reason="forget_entity",
                forget_kind="entity",
                effective_from=None,
                effective_to=None,
            )

            affected_subjects = await invalidate_forgotten_derivations(
                db,
                repository=MemoryCorrectionRepository(host.db_path),
                forgotten_assertions=forgotten_assertions,
                forgotten_edges=forgotten_edges,
                explicit_subject_keys=(
                    entity_id,
                    *claim_target_retirement.affected_subject_keys,
                ),
                now=now,
            )

            counts["event_entity_links"] = (
                await host._stage_entity_link_forget_on_connection(
                    db,
                    entity_id=entity_id,
                    operation_key=operation_key or f"direct:{entity_id}",
                )
            )

            await db.commit()

        for subject_key in affected_subjects:
            mark_subject_changed(host.db_path, subject_key)
        await rebuild_forgotten_subject_views(
            host=host,
            revisions=affected_subjects,
        )
        logger.info("L2 entity forgotten", entity_id=entity_id, counts=counts)
        return counts

    async def forget_time_range(
        self,
        *,
        start: float,
        end: float,
    ) -> Dict[str, int]:
        """Cascade invalidation for a time range."""
        if not math.isfinite(start) or not math.isfinite(end) or end <= start:
            raise ValueError("end must be greater than start")

        host = cast(_ForgettingHostProtocol, self)
        await host.initialize()
        counts: Dict[str, int] = {}

        async with sqlite_connection_async(host.db_path) as db:
            db.row_factory = aiosqlite.Row
            await db.execute("BEGIN IMMEDIATE")
            now = time.time()
            await _refresh_canonical_evidence_times(db, host=host)
            forgotten_assertions = await _assertion_claims(
                db,
                """
                EXISTS (
                    SELECT 1 FROM memory_claim_evidence_events AS evidence
                    WHERE evidence.target_kind = 'assertion'
                      AND evidence.claim_fingerprint = tom_trait_assertions.claim_fingerprint
                      AND evidence.observed_to >= ? AND evidence.observed_from <= ?
                      AND (
                          evidence.event_id IN (
                              SELECT CAST(value AS TEXT)
                              FROM json_each(CASE
                                  WHEN json_valid(tom_trait_assertions.evidence_events)
                                      THEN tom_trait_assertions.evidence_events
                                  ELSE '[]'
                              END)
                          )
                          OR EXISTS (
                              SELECT 1
                              FROM memory_corrections AS correction
                              WHERE tom_trait_assertions.authority_ref =
                                    'correction:' || correction.correction_id
                                AND correction.source_event_id = evidence.event_id
                          )
                          OR (
                              evidence.observed_to >= COALESCE(
                                  tom_trait_assertions.valid_from,
                                  tom_trait_assertions.first_inferred_at
                              )
                              AND (
                                  tom_trait_assertions.valid_to IS NULL
                                  OR evidence.observed_from <= tom_trait_assertions.valid_to
                              )
                          )
                      )
                )
                OR (
                    NOT EXISTS (
                        SELECT 1 FROM memory_claim_evidence_events AS evidence
                        WHERE evidence.target_kind = 'assertion'
                          AND evidence.claim_fingerprint = tom_trait_assertions.claim_fingerprint
                    )
                    AND COALESCE(valid_from, first_inferred_at) >= ?
                    AND COALESCE(valid_from, first_inferred_at) <= ?
                )
                """,
                (start, end, start, end),
            )
            forgotten_assertions = await _time_range_claims_requiring_work(
                db,
                target_kind=CorrectionTargetKind.ASSERTION,
                claims=forgotten_assertions,
                start=start,
                end=end,
            )
            forgotten_edges = await _relationship_claims(
                db,
                """
                EXISTS (
                    SELECT 1 FROM memory_claim_evidence_events AS evidence
                    WHERE evidence.target_kind = 'edge'
                      AND evidence.claim_fingerprint = knowledge_graph.claim_fingerprint
                      AND evidence.observed_to >= ? AND evidence.observed_from <= ?
                      AND (
                          evidence.event_id IN (
                              SELECT CAST(value AS TEXT)
                              FROM json_each(CASE
                                  WHEN json_valid(knowledge_graph.evidence_event_ids)
                                      THEN knowledge_graph.evidence_event_ids
                                  ELSE '[]'
                              END)
                          )
                          OR EXISTS (
                              SELECT 1
                              FROM memory_corrections AS correction
                              WHERE knowledge_graph.authority_ref =
                                    'correction:' || correction.correction_id
                                AND correction.source_event_id = evidence.event_id
                          )
                          OR (
                              evidence.observed_to >= COALESCE(
                                  knowledge_graph.valid_from,
                                  knowledge_graph.first_observed_at
                              )
                              AND (
                                  knowledge_graph.valid_to IS NULL
                                  OR evidence.observed_from <= knowledge_graph.valid_to
                              )
                          )
                      )
                )
                OR (
                    NOT EXISTS (
                        SELECT 1 FROM memory_claim_evidence_events AS evidence
                        WHERE evidence.target_kind = 'edge'
                          AND evidence.claim_fingerprint = knowledge_graph.claim_fingerprint
                    )
                    AND COALESCE(valid_from, first_observed_at) >= ?
                    AND COALESCE(valid_from, first_observed_at) <= ?
                )
                """,
                (start, end, start, end),
            )
            forgotten_edges = await _time_range_claims_requiring_work(
                db,
                target_kind=CorrectionTargetKind.EDGE,
                claims=forgotten_edges,
                start=start,
                end=end,
            )
            current_forgotten_edges = forgotten_edges
            historical_edges = await _historical_relationship_claims(
                db,
                start=start,
                end=end,
            )
            historical_edges = await _time_range_claims_requiring_work(
                db,
                target_kind=CorrectionTargetKind.EDGE,
                claims=historical_edges,
                start=start,
                end=end,
            )
            forgotten_edges = _merge_forgotten_claims(
                forgotten_edges,
                historical_edges,
            )
            episode_counts = await _invalidate_matching_episodes(
                db,
                where_clause="time_start <= ? AND time_end >= ?",
                parameters=(end, start),
                now=now,
            )
            counts.update(episode_counts)

            counts["tom_trait_assertions"] = await _apply_time_range_to_claim_rows(
                db,
                target_kind=CorrectionTargetKind.ASSERTION,
                claims=forgotten_assertions,
                start=start,
                end=end,
                now=now,
            )
            counts["knowledge_graph"] = await _apply_time_range_to_claim_rows(
                db,
                target_kind=CorrectionTargetKind.EDGE,
                claims=current_forgotten_edges,
                start=start,
                end=end,
                now=now,
            )

            await apply_correction_forget_barriers(
                db,
                forgotten_assertions=forgotten_assertions,
                forgotten_edges=forgotten_edges,
                now=now,
                permanently_block_claims=False,
                cancel_reason="forget_time_range",
                forget_kind="time_range",
                effective_from=start,
                effective_to=end,
            )

            affected_subjects = await invalidate_forgotten_derivations(
                db,
                repository=MemoryCorrectionRepository(host.db_path),
                forgotten_assertions=forgotten_assertions,
                forgotten_edges=forgotten_edges,
                now=now,
            )

            await db.commit()

        for subject_key in affected_subjects:
            mark_subject_changed(host.db_path, subject_key)
        await rebuild_forgotten_subject_views(
            host=host,
            revisions=affected_subjects,
        )
        logger.info("L2 time range forgotten", start=start, end=end, counts=counts)
        return counts

    async def forget_episode(
        self,
        *,
        episode_id: str,
        delete_events: bool = False,
    ) -> Optional[Dict[str, Any]]:
        """Invalidate an episode and every dependent user-visible derivation."""
        host = cast(_ForgettingHostProtocol, self)
        await host.initialize()
        now = time.time()

        async with sqlite_connection_async(host.db_path) as db:
            db.row_factory = aiosqlite.Row
            await db.execute("BEGIN IMMEDIATE")
            try:
                async with db.execute(
                    "SELECT episode_id FROM episodes WHERE episode_id = ?",
                    (episode_id,),
                ) as cursor:
                    existing = await cursor.fetchone()
                if existing is None:
                    await db.rollback()
                    return None

                event_ids: list[str] = []
                if delete_events:
                    async with db.execute(
                        "SELECT event_id FROM episode_events WHERE episode_id = ?",
                        (episode_id,),
                    ) as cursor:
                        rows = await cursor.fetchall()
                    event_ids = [str(row["event_id"]) for row in rows]

                impact = await invalidate_episode_dependencies(
                    db,
                    episode_id=episode_id,
                    now=now,
                )
                await db.commit()
            except Exception:
                await db.rollback()
                raise

        logger.info(
            "L2 episode forgotten",
            episode_id=episode_id,
            delete_events=delete_events,
            event_count=len(event_ids),
            **impact,
        )
        return {"episode_id": episode_id, "event_ids": event_ids, **impact}


async def _invalidate_matching_episodes(
    db: aiosqlite.Connection,
    *,
    where_clause: str,
    parameters: tuple[Any, ...],
    now: float,
) -> dict[str, int]:
    """Route broad forget selectors through the complete episode dependency path."""
    async with db.execute(
        f"""
        SELECT episode_id, status
        FROM episodes
        WHERE {where_clause}
        ORDER BY episode_id
        """,
        parameters,
    ) as cursor:
        rows = await cursor.fetchall()
    counts = {
        "episodes": sum(
            1 for row in rows if str(row["status"]) not in {"invalidated", "archived"}
        ),
        "experiences": 0,
        "experience_seeds": 0,
        "experience_drafts": 0,
        "summaries": 0,
    }
    impact = await invalidate_episode_dependencies_many(
        db,
        episode_ids=[str(row["episode_id"]) for row in rows],
        now=now,
    )
    for key, value in impact.items():
        counts[key] = int(value)
    return counts


async def _assertion_claims(
    db: aiosqlite.Connection,
    where_clause: str,
    parameters: tuple[Any, ...],
) -> dict[str, ForgottenClaim]:
    async with db.execute(
        f"""
        SELECT assertion_id, entity_id, entity_type, target_entity_id,
               trait_name, trait_value, slot_key, scope_key,
               claim_fingerprint, evidence_events
        FROM tom_trait_assertions
        WHERE {where_clause}
        """,
        parameters,
    ) as cursor:
        rows = await cursor.fetchall()
    claims: dict[str, ForgottenClaim] = {}
    for row in rows:
        record_id = str(row["assertion_id"])
        slot_key_value = str(row["slot_key"] or "") or assertion_slot_key(
            entity_type=str(row["entity_type"] or ""),
            entity_id=str(row["entity_id"] or ""),
            trait_name=str(row["trait_name"] or ""),
            target_entity_id=str(row["target_entity_id"] or ""),
        )
        fingerprint = str(row["claim_fingerprint"] or "") or assertion_claim_fingerprint(
            slot_key_value=slot_key_value,
            trait_value=row["trait_value"],
            scope_key_value=str(row["scope_key"] or "global"),
        )
        evidence_event_ids, evidence_fail_closed = decode_evidence_event_ids(row["evidence_events"])
        claims[record_id] = ForgottenClaim(
            record_id=record_id,
            claim_fingerprint=fingerprint,
            semantic_fingerprint=assertion_claim_fingerprint(
                slot_key_value=slot_key_value,
                trait_value=row["trait_value"],
            ),
            evidence_event_ids=evidence_event_ids,
            evidence_fail_closed=evidence_fail_closed,
            subject_keys=tuple(
                dict.fromkeys(
                    subject_key
                    for subject_key in (
                        str(row["entity_id"] or "").strip(),
                        str(row["target_entity_id"] or "").strip(),
                    )
                    if subject_key
                )
            ),
        )
    return claims


async def _relationship_claims(
    db: aiosqlite.Connection,
    where_clause: str,
    parameters: tuple[Any, ...],
) -> dict[str, ForgottenClaim]:
    async with db.execute(
        f"""
        SELECT triple_id, subject_id, predicate, object_id, slot_key,
               scope_key, claim_fingerprint, evidence_event_ids
        FROM knowledge_graph
        WHERE {where_clause}
        """,
        parameters,
    ) as cursor:
        rows = await cursor.fetchall()
    claims: dict[str, ForgottenClaim] = {}
    for row in rows:
        record_id = str(row["triple_id"])
        slot_key_value = str(row["slot_key"] or "") or relationship_slot_key(
            subject_id=str(row["subject_id"] or ""),
            predicate=str(row["predicate"] or ""),
            object_id=str(row["object_id"] or ""),
        )
        fingerprint = str(row["claim_fingerprint"] or "") or (
            relationship_claim_fingerprint(
                slot_key_value=slot_key_value,
                subject_id=str(row["subject_id"] or ""),
                predicate=str(row["predicate"] or ""),
                object_id=str(row["object_id"] or ""),
                scope_key_value=str(row["scope_key"] or "global"),
            )
        )
        evidence_event_ids, evidence_fail_closed = decode_evidence_event_ids(
            row["evidence_event_ids"]
        )
        subject_id = str(row["subject_id"] or "").strip()
        object_id = str(row["object_id"] or "").strip()
        claims[record_id] = ForgottenClaim(
            record_id=record_id,
            claim_fingerprint=fingerprint,
            semantic_fingerprint=relationship_claim_fingerprint(
                slot_key_value=slot_key_value,
                subject_id=str(row["subject_id"] or ""),
                predicate=str(row["predicate"] or ""),
                object_id=str(row["object_id"] or ""),
            ),
            evidence_event_ids=evidence_event_ids,
            evidence_fail_closed=evidence_fail_closed,
            subject_keys=tuple(
                dict.fromkeys(
                    subject_key
                    for subject_key in (subject_id, object_id if ":" in object_id else "")
                    if subject_key
                )
            ),
        )
    return claims


async def _historical_relationship_claims(
    db: aiosqlite.Connection,
    *,
    start: float,
    end: float,
) -> dict[str, ForgottenClaim]:
    """Capture versioned relationship occurrences no longer present in the live row."""
    return await _historical_relationship_claims_where(
        db,
        where_clause="""
            EXISTS (
                SELECT 1 FROM memory_claim_evidence_events AS evidence
                WHERE evidence.target_kind = 'edge'
                  AND evidence.claim_fingerprint = knowledge_graph_versions.claim_fingerprint
                  AND evidence.observed_to >= ? AND evidence.observed_from <= ?
                  AND (
                      evidence.event_id IN (
                          SELECT CAST(value AS TEXT)
                          FROM json_each(CASE
                              WHEN json_valid(knowledge_graph_versions.evidence_event_ids)
                                  THEN knowledge_graph_versions.evidence_event_ids
                              ELSE '[]'
                          END)
                      )
                      OR EXISTS (
                          SELECT 1
                          FROM memory_corrections AS correction
                          WHERE knowledge_graph_versions.authority_ref =
                                'correction:' || correction.correction_id
                            AND correction.source_event_id = evidence.event_id
                      )
                      OR (
                          evidence.observed_to >= COALESCE(
                              knowledge_graph_versions.valid_from,
                              knowledge_graph_versions.first_observed_at
                          )
                          AND (
                              knowledge_graph_versions.valid_to IS NULL
                              OR evidence.observed_from <= knowledge_graph_versions.valid_to
                          )
                      )
                  )
            )
            OR (
                NOT EXISTS (
                    SELECT 1 FROM memory_claim_evidence_events AS evidence
                    WHERE evidence.target_kind = 'edge'
                      AND evidence.claim_fingerprint = knowledge_graph_versions.claim_fingerprint
                )
                AND COALESCE(valid_from, first_observed_at) >= ?
                AND COALESCE(valid_from, first_observed_at) <= ?
            )
        """,
        parameters=(start, end, start, end),
    )


async def _historical_relationship_claims_for_entity(
    db: aiosqlite.Connection,
    *,
    entity_id: str,
) -> dict[str, ForgottenClaim]:
    """Capture purged relationship rows retained only in immutable history."""
    return await _historical_relationship_claims_where(
        db,
        where_clause="subject_id = ? OR object_id = ?",
        parameters=(entity_id, entity_id),
    )


async def _historical_relationship_claims_where(
    db: aiosqlite.Connection,
    *,
    where_clause: str,
    parameters: tuple[Any, ...],
) -> dict[str, ForgottenClaim]:
    async with db.execute(
        f"""
        SELECT triple_id, subject_id, predicate, object_id, slot_key,
               scope_key, claim_fingerprint, evidence_event_ids, correction_id
        FROM knowledge_graph_versions
        WHERE governance_complete = 1
          AND ({where_clause})
        ORDER BY created_at, version_id
        """,
        parameters,
    ) as cursor:
        rows = await cursor.fetchall()
    claims: dict[str, ForgottenClaim] = {}
    for row in rows:
        record_id = str(row["triple_id"])
        slot_key_value = str(row["slot_key"] or "") or relationship_slot_key(
            subject_id=str(row["subject_id"] or ""),
            predicate=str(row["predicate"] or ""),
            object_id=str(row["object_id"] or ""),
        )
        fingerprint = str(row["claim_fingerprint"] or "") or (
            relationship_claim_fingerprint(
                slot_key_value=slot_key_value,
                subject_id=str(row["subject_id"] or ""),
                predicate=str(row["predicate"] or ""),
                object_id=str(row["object_id"] or ""),
                scope_key_value=str(row["scope_key"] or "global"),
            )
        )
        evidence_event_ids, evidence_fail_closed = decode_evidence_event_ids(
            row["evidence_event_ids"]
        )
        subject_id = str(row["subject_id"] or "").strip()
        object_id = str(row["object_id"] or "").strip()
        claim = ForgottenClaim(
            record_id=record_id,
            claim_fingerprint=fingerprint,
            semantic_fingerprint=relationship_claim_fingerprint(
                slot_key_value=slot_key_value,
                subject_id=str(row["subject_id"] or ""),
                predicate=str(row["predicate"] or ""),
                object_id=str(row["object_id"] or ""),
            ),
            evidence_event_ids=evidence_event_ids,
            evidence_fail_closed=evidence_fail_closed,
            subject_keys=tuple(
                subject_key
                for subject_key in (subject_id, object_id if ":" in object_id else "")
                if subject_key
            ),
            correction_ids=(
                (str(row["correction_id"]),) if str(row["correction_id"] or "").strip() else ()
            ),
        )
        claims = _merge_forgotten_claims(claims, {record_id: claim})
    return claims


def _merge_forgotten_claims(
    *claim_maps: Mapping[str, ForgottenClaim],
) -> dict[str, ForgottenClaim]:
    merged: dict[str, ForgottenClaim] = {}
    for claims in claim_maps:
        for record_id, claim in claims.items():
            existing = merged.get(record_id)
            if existing is None:
                merged[record_id] = claim
                continue
            merged[record_id] = ForgottenClaim(
                record_id=record_id,
                claim_fingerprint=(existing.claim_fingerprint or claim.claim_fingerprint),
                semantic_fingerprint=(existing.semantic_fingerprint or claim.semantic_fingerprint),
                evidence_event_ids=tuple(
                    dict.fromkeys((*existing.evidence_event_ids, *claim.evidence_event_ids))
                ),
                evidence_fail_closed=(existing.evidence_fail_closed or claim.evidence_fail_closed),
                subject_keys=tuple(dict.fromkeys((*existing.subject_keys, *claim.subject_keys))),
                correction_ids=tuple(
                    dict.fromkeys((*existing.correction_ids, *claim.correction_ids))
                ),
            )
    return merged


async def _refresh_canonical_evidence_times(
    db: aiosqlite.Connection,
    *,
    host: _ForgettingHostProtocol,
) -> None:
    """Refresh legacy approximate evidence times from canonical L1 events."""
    after_event_id = ""
    while True:
        async with db.execute(
            """
            SELECT DISTINCT event_id
            FROM memory_claim_evidence_events
            WHERE observed_at_is_approximate = 1 AND event_id > ?
            ORDER BY event_id
            LIMIT ?
            """,
            (after_event_id, _EVIDENCE_TIMESTAMP_REFRESH_BATCH_SIZE),
        ) as cursor:
            event_ids = [str(row[0]) for row in await cursor.fetchall()]
        if not event_ids:
            return
        timestamps = await host.resolve_evidence_timestamps(event_ids)
        await refresh_claim_evidence_timestamps(db, timestamps=timestamps)
        after_event_id = event_ids[-1]


async def _apply_time_range_to_claim_rows(
    db: aiosqlite.Connection,
    *,
    target_kind: CorrectionTargetKind,
    claims: Mapping[str, ForgottenClaim],
    start: float,
    end: float,
    now: float,
) -> int:
    """Remove only in-range evidence while preserving independently supported claims."""
    if not claims:
        return 0
    evidence_by_claim = await claim_evidence_records_for_claims(
        db,
        target_kind=target_kind,
        claim_fingerprints=(claim.claim_fingerprint for claim in claims.values()),
    )
    affected = 0
    for record_id, claim in claims.items():
        records = evidence_by_claim.get(claim.claim_fingerprint, [])
        if target_kind == CorrectionTargetKind.ASSERTION:
            table = "tom_trait_assertions"
            identity_column = "assertion_id"
            evidence_column = "evidence_events"
            first_observed_column = "first_inferred_at"
        else:
            table = "knowledge_graph"
            identity_column = "triple_id"
            evidence_column = "evidence_event_ids"
            first_observed_column = "first_observed_at"
        async with db.execute(
            f"""
            SELECT claim_fingerprint, {evidence_column}, valid_from, valid_to,
                   {first_observed_column}, (
                       SELECT correction.source_event_id
                       FROM memory_corrections AS correction
                       WHERE {table}.authority_ref = 'correction:' || correction.correction_id
                       LIMIT 1
                   ) AS correction_source_event_id
            FROM {table}
            WHERE {identity_column} = ?
            """,
            (record_id,),
        ) as cursor:
            current = await cursor.fetchone()
        if current is None or str(current[0] or "") != claim.claim_fingerprint:
            continue
        current_evidence_ids, current_evidence_fail_closed = decode_evidence_event_ids(current[1])
        current_evidence = set(current_evidence_ids)
        segment_start = float(current[2]) if current[2] is not None else float(current[4])
        segment_end = float(current[3]) if current[3] is not None else math.inf
        correction_source_event_id = str(current[5] or "").strip()
        records = [
            record
            for record in records
            if record.event_id in current_evidence
            or record.event_id == correction_source_event_id
            or (record.observed_from <= segment_end and record.observed_to >= segment_start)
        ]
        forgotten_records = [record for record in records if record.overlaps(start, end)]
        if records and not forgotten_records:
            continue
        retained_records = [record for record in records if not record.overlaps(start, end)]
        current_records = [record for record in records if record.event_id in current_evidence]
        if current_evidence_fail_closed:
            current_records = records
        current_forgotten_records = [
            record for record in current_records if record.overlaps(start, end)
        ]
        current_retained_records = [
            record for record in current_records if not record.overlaps(start, end)
        ]

        if records and not current_forgotten_records:
            if target_kind == CorrectionTargetKind.EDGE and forgotten_records:
                cursor = await db.execute(
                    """
                    UPDATE knowledge_graph
                    SET evidence_text = '', natural_summary = '',
                        embedding_status = 'pending', updated_at = ?
                    WHERE triple_id = ?
                    """,
                    (now, record_id),
                )
                affected += int(cursor.rowcount or 0)
            continue

        effective_retained_records = current_retained_records
        if not effective_retained_records and retained_records:
            effective_retained_records = retained_records

        if effective_retained_records:
            retained_ids = [record.event_id for record in effective_retained_records]
            bounded_ids = retained_ids[-max_evidence_event_ids() :]
            first_at = min(record.observed_from for record in effective_retained_records)
            last_at = max(record.observed_to for record in effective_retained_records)
            if target_kind == CorrectionTargetKind.ASSERTION:
                cursor = await db.execute(
                    f"""
                    UPDATE {table}
                    SET {evidence_column} = ?, first_inferred_at = ?,
                        last_validated_at = ?, updated_at = ?
                    WHERE {identity_column} = ?
                    """,
                    (
                        json.dumps(bounded_ids, ensure_ascii=False),
                        first_at,
                        last_at,
                        now,
                        record_id,
                    ),
                )
            else:
                cursor = await db.execute(
                    f"""
                    UPDATE {table}
                    SET {evidence_column} = ?, observation_count = ?,
                        first_observed_at = ?, last_observed_at = ?,
                        last_confirmed_at = ?, evidence_text = '',
                        natural_summary = '', embedding_status = 'pending',
                        updated_at = ?
                    WHERE {identity_column} = ?
                    """,
                    (
                        json.dumps(bounded_ids, ensure_ascii=False),
                        len(effective_retained_records),
                        first_at,
                        last_at,
                        last_at,
                        now,
                        record_id,
                    ),
                )
        elif target_kind == CorrectionTargetKind.ASSERTION:
            cursor = await db.execute(
                """
                UPDATE tom_trait_assertions
                SET status = 'archived', evidence_events = '[]',
                    authority_ref = CASE
                        WHEN authority_ref = 'forget:entity' THEN authority_ref
                        ELSE 'forget:time_range'
                    END,
                    updated_at = ?
                WHERE assertion_id = ?
                """,
                (now, record_id),
            )
        else:
            cursor = await db.execute(
                """
                UPDATE knowledge_graph
                SET status = 'archived', status_reason = 'user_forget',
                    evidence_event_ids = '[]', observation_count = 0,
                    evidence_text = '', natural_summary = '',
                    embedding_status = 'pending',
                    authority_ref = CASE
                        WHEN authority_ref = 'forget:entity' THEN authority_ref
                        ELSE 'forget:time_range'
                    END,
                    updated_at = ?
                WHERE triple_id = ?
                """,
                (now, record_id),
            )
        affected += int(cursor.rowcount or 0)
    return affected


async def _time_range_claims_requiring_work(
    db: aiosqlite.Connection,
    *,
    target_kind: CorrectionTargetKind,
    claims: Mapping[str, ForgottenClaim],
    start: float,
    end: float,
) -> dict[str, ForgottenClaim]:
    """Skip an already-applied time rule unless forgotten evidence resurfaced."""
    if not claims:
        return {}
    if target_kind == CorrectionTargetKind.ASSERTION:
        table = "tom_trait_assertions"
        identity_column = "assertion_id"
        evidence_column = "evidence_events"
        text_columns = "'' AS evidence_text, '' AS natural_summary"
    else:
        table = "knowledge_graph"
        identity_column = "triple_id"
        evidence_column = "evidence_event_ids"
        text_columns = "evidence_text, natural_summary"

    pending: dict[str, ForgottenClaim] = {}
    for record_id, claim in claims.items():
        async with db.execute(
            """
            SELECT rule_id
            FROM memory_forget_claim_rules
            WHERE target_kind = ? AND claim_fingerprint = ?
              AND forget_kind = 'time_range'
              AND effective_from = ? AND effective_to = ?
            LIMIT 1
            """,
            (target_kind.value, claim.claim_fingerprint, start, end),
        ) as cursor:
            rule = await cursor.fetchone()
        if rule is None:
            pending[record_id] = claim
            continue

        async with db.execute(
            f"""
            SELECT {evidence_column}, {text_columns}
            FROM {table}
            WHERE {identity_column} = ? AND claim_fingerprint = ?
            """,
            (record_id, claim.claim_fingerprint),
        ) as cursor:
            current = await cursor.fetchone()
        if current is None:
            continue
        current_event_ids, fail_closed = decode_evidence_event_ids(current[0])
        if fail_closed:
            pending[record_id] = claim
            continue
        if target_kind == CorrectionTargetKind.EDGE and (
            str(current[1] or "").strip() or str(current[2] or "").strip()
        ):
            pending[record_id] = claim
            continue
        if not current_event_ids:
            continue

        event_json = json.dumps(current_event_ids, ensure_ascii=False, separators=(",", ":"))
        async with db.execute(
            """
            SELECT 1
            FROM memory_claim_evidence_events AS evidence
            WHERE evidence.target_kind = ? AND evidence.claim_fingerprint = ?
              AND evidence.observed_to >= ? AND evidence.observed_from <= ?
              AND evidence.event_id IN (
                  SELECT CAST(value AS TEXT) FROM json_each(?)
              )
            UNION ALL
            SELECT 1
            FROM memory_forget_evidence_events AS evidence
            WHERE evidence.rule_id = ?
              AND evidence.event_id IN (
                  SELECT CAST(value AS TEXT) FROM json_each(?)
              )
            LIMIT 1
            """,
            (
                target_kind.value,
                claim.claim_fingerprint,
                start,
                end,
                event_json,
                str(rule[0]),
                event_json,
            ),
        ) as cursor:
            dirty = await cursor.fetchone()
        if dirty is not None:
            pending[record_id] = claim
    return pending
