"""User-driven forgetting of canonical source events and their L2 evidence."""

from __future__ import annotations

import json
import math
import time
from collections.abc import Iterable, Mapping
from typing import Any, Protocol, cast

import aiosqlite

from ....core.logger import get_logger
from ....core.sqlite import sqlite_connection_async
from ...source_event_governance import (
    normalize_source_event_ids,
    source_event_tombstone_ids,
    tombstone_source_event_ids,
)
from ..assertions.state_machine import (
    ACTIVE_VALIDATION_STATES,
    compute_confidence,
    derive_validation_state,
)
from ..corrections.cache_signals import mark_subject_changed
from ..claims.repository import redact_grounded_claims_for_source_events
from ..corrections.evidence_ledger import claim_evidence_records_for_claims
from ..corrections.fingerprints import (
    assertion_claim_fingerprint,
    assertion_slot_key,
    relationship_claim_fingerprint,
    relationship_slot_key,
)
from ..corrections.forget_governance import (
    ForgottenClaim,
    decode_evidence_event_ids,
)
from ..corrections.forget_lineage import (
    apply_correction_forget_barriers,
    revert_corrections_for_forgotten_source_events,
)
from ..corrections.models import CorrectionTargetKind
from ..corrections.repository import MemoryCorrectionRepository
from ..experiences.source_event_forgetting import delete_experience_drafts_for_source_events
from ..graph.versions import append_knowledge_graph_version
from ..storage.utils import max_evidence_event_ids
from .derivation_refresh import (
    invalidate_forgotten_derivations,
    rebuild_forgotten_subject_views,
)

logger = get_logger(__name__)


class _SourceEventForgettingHostProtocol(Protocol):
    db_path: str

    async def initialize(self) -> None: ...

    def memory_correction_job_guard(self) -> Any: ...


class L2StoreSourceEventForgettingMixin:
    """Remove L2 support from user-deleted source events."""

    async def is_source_event_tombstoned(self, event_id: str) -> bool:
        """Return whether an event has completed durable delete governance."""
        host = cast(_SourceEventForgettingHostProtocol, self)
        await host.initialize()
        normalized = normalize_source_event_ids([event_id])
        if not normalized:
            return False
        async with sqlite_connection_async(host.db_path) as db:
            return bool(await source_event_tombstone_ids(db, normalized))

    async def tombstone_source_events(
        self,
        event_ids: Iterable[str],
        *,
        reason: str,
    ) -> int:
        """Block source events globally without changing existing claim rows."""
        host = cast(_SourceEventForgettingHostProtocol, self)
        await host.initialize()
        normalized = normalize_source_event_ids(event_ids)
        if not normalized:
            return 0
        async with host.memory_correction_job_guard():
            async with sqlite_connection_async(host.db_path) as db:
                await db.execute("BEGIN IMMEDIATE")
                try:
                    inserted = int(
                        await tombstone_source_event_ids(
                            db,
                            event_ids=normalized,
                            reason=reason,
                            created_at=time.time(),
                        )
                    )
                    await _complete_forgotten_projection_jobs(
                        db,
                        event_ids=normalized,
                        now=time.time(),
                    )
                    await db.commit()
                except Exception:
                    await db.rollback()
                    raise
        return inserted

    async def forget_source_events(
        self,
        event_ids: Iterable[str],
        *,
        reason: str,
        persist_barrier: bool = True,
    ) -> dict[str, int]:
        """Forget source events, remove their claim support, and block replay."""
        host = cast(_SourceEventForgettingHostProtocol, self)
        await host.initialize()
        normalized = normalize_source_event_ids(event_ids)
        if not normalized:
            return _empty_result()

        affected_subjects: dict[str, int] = {}
        result = _empty_result()
        async with host.memory_correction_job_guard():
            async with sqlite_connection_async(host.db_path) as db:
                db.row_factory = aiosqlite.Row
                await db.execute("BEGIN IMMEDIATE")
                try:
                    now = time.time()
                    if persist_barrier:
                        result["source_event_tombstones"] = await tombstone_source_event_ids(
                            db,
                            event_ids=normalized,
                            reason=reason,
                            created_at=now,
                        )
                    result["projection_jobs"] = await _complete_forgotten_projection_jobs(
                        db,
                        event_ids=normalized,
                        now=now,
                    )
                    result.update(
                        await redact_grounded_claims_for_source_events(
                            db,
                            event_ids=normalized,
                            reason=reason,
                            now=now,
                        )
                    )
                    assertion_claims = await _assertion_claims_for_events(db, normalized)
                    edge_claims = await _relationship_claims_for_events(db, normalized)
                    assertion_events = await _forgotten_events_by_claim(
                        db,
                        target_kind=CorrectionTargetKind.ASSERTION,
                        claims=assertion_claims,
                        event_ids=normalized,
                    )
                    edge_events = await _forgotten_events_by_claim(
                        db,
                        target_kind=CorrectionTargetKind.EDGE,
                        claims=edge_claims,
                        event_ids=normalized,
                    )
                    result["tom_trait_assertions"] = await _remove_assertion_evidence(
                        db,
                        claims=assertion_claims,
                        forgotten_by_claim=assertion_events,
                        now=now,
                    )
                    result["knowledge_graph"] = await _remove_relationship_evidence(
                        db,
                        claims=edge_claims,
                        forgotten_by_claim=edge_events,
                        now=now,
                    )
                    result.update(
                        await _forget_entity_evidence(
                            db,
                            event_ids=normalized,
                            now=now,
                        )
                    )
                    result["experience_drafts"] = await delete_experience_drafts_for_source_events(
                        db,
                        event_ids=normalized,
                    )
                    derivation_counts = await _invalidate_source_event_memberships(
                        db,
                        event_ids=normalized,
                        now=now,
                    )
                    result.update(derivation_counts)
                    await apply_correction_forget_barriers(
                        db,
                        forgotten_assertions=assertion_claims,
                        forgotten_edges=edge_claims,
                        now=now,
                        permanently_block_claims=False,
                        cancel_reason="forget_event",
                        forget_kind="event",
                        effective_from=None,
                        effective_to=None,
                        assertion_event_ids_by_record=assertion_events,
                        edge_event_ids_by_record=edge_events,
                    )
                    correction_subjects = await revert_corrections_for_forgotten_source_events(
                        db,
                        event_ids=normalized,
                        now=now,
                    )

                    affected_subjects = await invalidate_forgotten_derivations(
                        db,
                        repository=MemoryCorrectionRepository(host.db_path),
                        forgotten_assertions=_claims_by_record_id(assertion_claims),
                        forgotten_edges=_claims_by_record_id(edge_claims),
                        now=now,
                        explicit_subject_keys=correction_subjects,
                    )
                    await db.commit()
                except Exception:
                    await db.rollback()
                    raise

        for subject_key in affected_subjects:
            mark_subject_changed(host.db_path, subject_key)
        await rebuild_forgotten_subject_views(host=host, revisions=affected_subjects)
        result["affected_subjects"] = len(affected_subjects)
        logger.info(
            "L2 source events forgotten",
            event_count=len(normalized),
            reason=reason,
            counts=result,
        )
        return result


def _empty_result() -> dict[str, int]:
    return {
        "source_event_tombstones": 0,
        "projection_jobs": 0,
        "l2_claim_evidence": 0,
        "l2_claim_entity_refs": 0,
        "l2_grounded_claims": 0,
        "l2_claim_projection_outcomes": 0,
        "tom_trait_assertions": 0,
        "knowledge_graph": 0,
        "entity_mentions": 0,
        "entity_aliases": 0,
        "entity_name_evidence": 0,
        "entity_catalog": 0,
        "entity_facets": 0,
        "episodes": 0,
        "experiences": 0,
        "experience_drafts": 0,
        "experience_seeds": 0,
        "affected_subjects": 0,
    }


async def _forget_entity_evidence(
    db: aiosqlite.Connection,
    *,
    event_ids: tuple[str, ...],
    now: float,
) -> dict[str, int]:
    target_ids = set(event_ids)
    event_json = _event_json(event_ids)
    async with db.execute(
        """
        SELECT * FROM entity_mentions AS mention
        WHERE EXISTS (
            SELECT 1
            FROM json_each(CASE
                WHEN json_valid(mention.evidence_event_ids)
                    THEN mention.evidence_event_ids
                ELSE '[]'
            END) AS evidence
            WHERE TRIM(CAST(evidence.value AS TEXT)) IN (
                SELECT CAST(value AS TEXT) FROM json_each(?)
            )
        )
        """,
        (event_json,),
    ) as cursor:
        mention_rows = await cursor.fetchall()
    affected_entity_ids = tuple(
        sorted(
            {
                str(row["resolved_entity_id"]).strip()
                for row in mention_rows
                if row["resolved_entity_id"] is not None and str(row["resolved_entity_id"]).strip()
            }
        )
    )
    for row in mention_rows:
        evidence_ids = _safe_json_id_list(row["evidence_event_ids"])
        retained_ids = [event_id for event_id in evidence_ids if event_id not in target_ids]
        if not retained_ids:
            await db.execute(
                "DELETE FROM entity_mentions WHERE mention_id = ?",
                (row["mention_id"],),
            )
            continue
        await db.execute(
            """
            UPDATE entity_mentions
            SET evidence_event_ids = ?, evidence_text = mention_text
            WHERE mention_id = ?
            """,
            (json.dumps(retained_ids, ensure_ascii=False), row["mention_id"]),
        )

    event_name_rows = await _name_evidence_rows_for_events(db, event_json=event_json)
    name_entity_ids = {
        str(row["entity_id"]).strip() for row in event_name_rows if str(row["entity_id"]).strip()
    }
    affected_entity_ids = tuple(sorted(set(affected_entity_ids) | name_entity_ids))
    deleted_name_evidence = await db.execute(
        """
        DELETE FROM entity_name_evidence
        WHERE event_id IN (SELECT CAST(value AS TEXT) FROM json_each(?))
        """,
        (event_json,),
    )
    alias_count = await _reconcile_affected_aliases(
        db,
        evidence_rows=event_name_rows,
        entity_ids=affected_entity_ids,
        now=now,
    )

    async with db.execute(
        """
        SELECT * FROM entity_facets AS facet
        WHERE EXISTS (
            SELECT 1
            FROM json_each(CASE
                WHEN json_valid(facet.evidence_event_ids)
                    THEN facet.evidence_event_ids
                ELSE '[]'
            END) AS evidence
            WHERE TRIM(CAST(evidence.value AS TEXT)) IN (
                SELECT CAST(value AS TEXT) FROM json_each(?)
            )
        )
        """,
        (event_json,),
    ) as cursor:
        facet_rows = await cursor.fetchall()
    for row in facet_rows:
        evidence_ids = _safe_json_id_list(row["evidence_event_ids"])
        retained_ids = [event_id for event_id in evidence_ids if event_id not in target_ids]
        if not retained_ids:
            await db.execute(
                """
                UPDATE entity_facets
                SET status = 'archived', evidence_event_ids = '[]', updated_at = ?
                WHERE facet_id = ?
                """,
                (now, row["facet_id"]),
            )
            continue
        await db.execute(
            """
            UPDATE entity_facets
            SET evidence_event_ids = ?, confidence = ?, updated_at = ?
            WHERE facet_id = ?
            """,
            (
                json.dumps(retained_ids, ensure_ascii=False),
                _reduced_relationship_confidence(
                    float(row["confidence"]),
                    retained_count=len(retained_ids),
                    original_count=max(len(evidence_ids), 1),
                ),
                now,
                row["facet_id"],
            ),
        )
    entity_count = await _reconcile_affected_entities(
        db,
        entity_ids=affected_entity_ids,
        now=now,
    )
    return {
        "entity_mentions": len(mention_rows),
        "entity_aliases": alias_count,
        "entity_name_evidence": max(int(deleted_name_evidence.rowcount or 0), 0),
        "entity_catalog": entity_count,
        "entity_facets": len(facet_rows),
    }


async def _reconcile_affected_entities(
    db: aiosqlite.Connection,
    *,
    entity_ids: tuple[str, ...],
    now: float,
) -> int:
    changed = 0
    for entity_id in entity_ids:
        async with db.execute(
            """
            SELECT 1
            WHERE EXISTS (
                SELECT 1 FROM entity_catalog
                WHERE entity_id = ? AND canonical_name_is_independent = 1
            ) OR EXISTS (
                SELECT 1 FROM entity_aliases
                WHERE entity_id = ? AND is_independent = 1
            ) OR EXISTS (
                SELECT 1 FROM entity_name_evidence
                WHERE entity_id = ?
            ) OR EXISTS (
                SELECT 1 FROM entity_mentions
                WHERE resolved_entity_id = ?
            ) OR EXISTS (
                SELECT 1 FROM entity_facets
                WHERE entity_id = ? AND status = 'active'
            ) OR EXISTS (
                SELECT 1 FROM knowledge_graph
                WHERE status = 'active' AND (subject_id = ? OR object_id = ?)
            ) OR EXISTS (
                SELECT 1 FROM tom_trait_assertions
                WHERE status NOT IN (
                    'superseded', 'archived', 'expired', 'user_rejected', 'shadow'
                ) AND (entity_id = ? OR target_entity_id = ?)
            )
            """,
            (
                entity_id,
                entity_id,
                entity_id,
                entity_id,
                entity_id,
                entity_id,
                entity_id,
                entity_id,
                entity_id,
            ),
        ) as cursor:
            has_support = await cursor.fetchone() is not None
        if not has_support:
            await db.execute(
                "DELETE FROM entity_name_evidence WHERE entity_id = ?",
                (entity_id,),
            )
            await db.execute(
                "DELETE FROM entity_aliases WHERE entity_id = ?",
                (entity_id,),
            )
            deleted = await db.execute(
                "DELETE FROM entity_catalog WHERE entity_id = ?",
                (entity_id,),
            )
            changed += max(int(deleted.rowcount or 0), 0)
            continue
        async with db.execute(
            """
            SELECT canonical_name, entity_type, canonical_name_is_independent
            FROM entity_catalog
            WHERE entity_id = ?
            """,
            (entity_id,),
        ) as cursor:
            catalog_row = await cursor.fetchone()
        if catalog_row is None:
            continue
        canonical_name = str(catalog_row["canonical_name"])
        canonical_is_independent = bool(catalog_row["canonical_name_is_independent"])
        if not canonical_is_independent:
            normalized_name = canonical_name.strip().casefold()
            async with db.execute(
                """
                SELECT display_name
                FROM entity_name_evidence
                WHERE entity_id = ? AND name_kind = 'canonical'
                  AND normalized_name = ?
                ORDER BY confidence DESC, updated_at DESC, event_id
                LIMIT 1
                """,
                (entity_id, normalized_name),
            ) as cursor:
                retained_current = await cursor.fetchone()
            if retained_current is None:
                async with db.execute(
                    """
                    SELECT display_name
                    FROM entity_name_evidence
                    WHERE entity_id = ? AND name_kind = 'canonical'
                    ORDER BY confidence DESC, updated_at DESC,
                             normalized_name, event_id
                    LIMIT 1
                    """,
                    (entity_id,),
                ) as cursor:
                    replacement = await cursor.fetchone()
                if replacement is not None:
                    canonical_name = str(replacement["display_name"])
                else:
                    async with db.execute(
                        """
                        SELECT mention_text
                        FROM entity_mentions
                        WHERE resolved_entity_id = ? AND TRIM(mention_text) != ''
                        ORDER BY COALESCE(confidence, 0.0) DESC, mention_id ASC
                        LIMIT 1
                        """,
                        (entity_id,),
                    ) as cursor:
                        retained_mention = await cursor.fetchone()
                    canonical_name = (
                        str(retained_mention["mention_text"])
                        if retained_mention is not None
                        else f"{str(catalog_row['entity_type']).replace('_', ' ')} entity"
                    )
        updated = await db.execute(
            """
            UPDATE entity_catalog
            SET canonical_name = ?,
                embedding_status = CASE
                    WHEN embedding_status = 'disabled' THEN 'disabled'
                    ELSE 'pending'
                END,
                embedding_profile_id = CASE
                    WHEN embedding_status = 'disabled' THEN embedding_profile_id
                    ELSE NULL
                END,
                last_embedded_at = CASE
                    WHEN embedding_status = 'disabled' THEN last_embedded_at
                    ELSE NULL
                END,
                updated_at = ?
            WHERE entity_id = ?
            """,
            (canonical_name, now, entity_id),
        )
        changed += max(int(updated.rowcount or 0), 0)
    return changed


async def _name_evidence_rows_for_events(
    db: aiosqlite.Connection,
    *,
    event_json: str,
) -> list[aiosqlite.Row]:
    async with db.execute(
        """
        SELECT entity_id, name_kind, normalized_name
        FROM entity_name_evidence
        WHERE event_id IN (SELECT CAST(value AS TEXT) FROM json_each(?))
        ORDER BY entity_id, name_kind, normalized_name
        """,
        (event_json,),
    ) as cursor:
        return list(await cursor.fetchall())


async def _reconcile_affected_aliases(
    db: aiosqlite.Connection,
    *,
    evidence_rows: Iterable[Mapping[str, Any]],
    entity_ids: tuple[str, ...],
    now: float,
) -> int:
    affected_keys = {
        (str(row["entity_id"]), str(row["normalized_name"]))
        for row in evidence_rows
        if str(row["name_kind"]) == "alias"
    }
    if entity_ids:
        entity_json = json.dumps(entity_ids, ensure_ascii=False, separators=(",", ":"))
        async with db.execute(
            """
            SELECT alias.entity_id, alias.normalized_alias
            FROM entity_aliases AS alias
            WHERE alias.is_independent = 0
              AND alias.entity_id IN (
                  SELECT CAST(value AS TEXT) FROM json_each(?)
              )
              AND NOT EXISTS (
                  SELECT 1
                  FROM entity_name_evidence AS evidence
                  WHERE evidence.entity_id = alias.entity_id
                    AND evidence.name_kind = 'alias'
                    AND evidence.normalized_name = alias.normalized_alias
              )
            """,
            (entity_json,),
        ) as cursor:
            affected_keys.update(
                (str(row["entity_id"]), str(row["normalized_alias"]))
                for row in await cursor.fetchall()
            )
    changed = 0
    for entity_id, normalized_alias in sorted(affected_keys):
        async with db.execute(
            """
            SELECT is_independent
            FROM entity_aliases
            WHERE entity_id = ? AND normalized_alias = ?
            """,
            (entity_id, normalized_alias),
        ) as cursor:
            alias_row = await cursor.fetchone()
        if alias_row is None or bool(alias_row["is_independent"]):
            continue
        async with db.execute(
            """
            SELECT display_name, confidence
            FROM entity_name_evidence
            WHERE entity_id = ? AND name_kind = 'alias' AND normalized_name = ?
            ORDER BY confidence DESC, updated_at DESC, event_id
            LIMIT 1
            """,
            (entity_id, normalized_alias),
        ) as cursor:
            retained = await cursor.fetchone()
        if retained is None:
            retained = await _retained_legacy_alias_mention(
                db,
                entity_id=entity_id,
                normalized_alias=normalized_alias,
            )
        if retained is None:
            deleted = await db.execute(
                """
                DELETE FROM entity_aliases
                WHERE entity_id = ? AND normalized_alias = ?
                """,
                (entity_id, normalized_alias),
            )
            changed += max(int(deleted.rowcount or 0), 0)
            continue
        updated = await db.execute(
            """
            UPDATE entity_aliases
            SET alias_text = ?, confidence = ?, updated_at = ?
            WHERE entity_id = ? AND normalized_alias = ?
            """,
            (
                str(retained["display_name"]),
                float(retained["confidence"]),
                now,
                entity_id,
                normalized_alias,
            ),
        )
        changed += max(int(updated.rowcount or 0), 0)
    return changed


async def _retained_legacy_alias_mention(
    db: aiosqlite.Connection,
    *,
    entity_id: str,
    normalized_alias: str,
) -> dict[str, Any] | None:
    """Recover only exact Python-normalized support for a pre-ledger alias."""
    async with db.execute(
        """
        SELECT mention_text, normalized_surface, confidence
        FROM entity_mentions
        WHERE resolved_entity_id = ?
        ORDER BY COALESCE(confidence, 0.0) DESC, mention_id ASC
        """,
        (entity_id,),
    ) as cursor:
        rows = await cursor.fetchall()
    for row in rows:
        surfaces = {
            str(row["mention_text"] or "").strip().casefold(),
            str(row["normalized_surface"] or "").strip().casefold(),
        }
        if normalized_alias not in surfaces:
            continue
        return {
            "display_name": str(row["mention_text"]),
            "confidence": float(row["confidence"] or 0.0),
        }
    return None


async def _complete_forgotten_projection_jobs(
    db: aiosqlite.Connection,
    *,
    event_ids: tuple[str, ...],
    now: float,
) -> int:
    event_json = _event_json(event_ids)
    cursor = await db.execute(
        """
        UPDATE l2_projection_jobs
        SET status = 'completed', lease_token = NULL, lease_heartbeat_at = NULL,
            next_retry_at = NULL, terminal_at = NULL,
            claimed_by = NULL, claimed_at = NULL,
            started_at = NULL, completed_at = ?,
            last_error = 'source_event_forgotten', updated_at = ?
        WHERE event_id IN (SELECT CAST(value AS TEXT) FROM json_each(?))
          AND status != 'completed'
        """,
        (now, now, event_json),
    )
    return max(int(cursor.rowcount or 0), 0)


async def _invalidate_source_event_memberships(
    db: aiosqlite.Connection,
    *,
    event_ids: tuple[str, ...],
    now: float,
) -> dict[str, int]:
    """Detach explicit L2 derivations while preserving user-authored fields."""
    event_json = _event_json(event_ids)
    affected_episodes = await _select_ids(
        db,
        """
        SELECT DISTINCT episode_id FROM episode_events
        WHERE event_id IN (SELECT CAST(value AS TEXT) FROM json_each(?))
        """,
        (event_json,),
    )
    affected_summaries = await _select_ids(
        db,
        """
        SELECT DISTINCT summaries.summary_id
        FROM summaries
        WHERE EXISTS (
            SELECT 1 FROM summary_event_links AS links
            WHERE links.summary_id = summaries.summary_id
              AND links.event_id IN (SELECT CAST(value AS TEXT) FROM json_each(?))
        ) OR EXISTS (
            SELECT 1
            FROM json_each(CASE
                WHEN json_valid(summaries.source_event_ids)
                    THEN summaries.source_event_ids
                ELSE '[]'
            END) AS source
            WHERE CAST(source.value AS TEXT) IN (
                SELECT CAST(value AS TEXT) FROM json_each(?)
            )
        )
        """,
        (event_json, event_json),
    )
    episode_json = _event_json(tuple(affected_episodes))
    affected_experiences = await _select_ids(
        db,
        """
        SELECT DISTINCT experience_id FROM experience_members
        WHERE (member_type = 'event' AND member_id IN (
            SELECT CAST(value AS TEXT) FROM json_each(?)
        )) OR (member_type = 'episode' AND member_id IN (
            SELECT CAST(value AS TEXT) FROM json_each(?)
        ))
        UNION
        SELECT DISTINCT experience_id FROM experience_key_events
        WHERE event_id IN (SELECT CAST(value AS TEXT) FROM json_each(?))
        UNION
        SELECT DISTINCT experience_id FROM experience_chapters AS chapter
        WHERE EXISTS (
            SELECT 1
            FROM json_each(CASE
                WHEN json_valid(chapter.event_ids_json)
                    THEN chapter.event_ids_json
                ELSE '[]'
            END) AS event_ref
            WHERE CAST(event_ref.value AS TEXT) IN (
                SELECT CAST(value AS TEXT) FROM json_each(?)
            )
        ) OR EXISTS (
            SELECT 1
            FROM json_each(CASE
                WHEN json_valid(chapter.episode_ids_json)
                    THEN chapter.episode_ids_json
                ELSE '[]'
            END) AS episode_ref
            WHERE CAST(episode_ref.value AS TEXT) IN (
                SELECT CAST(value AS TEXT) FROM json_each(?)
            )
        )
        """,
        (event_json, episode_json, event_json, event_json, episode_json),
    )
    summary_json = _event_json(tuple(affected_summaries))
    affected_seeds = await _select_ids(
        db,
        """
        SELECT DISTINCT seed_id FROM experience_seed_evidence
        WHERE (ref_type = 'event' AND ref_id IN (
            SELECT CAST(value AS TEXT) FROM json_each(?)
        )) OR (ref_type = 'episode' AND ref_id IN (
            SELECT CAST(value AS TEXT) FROM json_each(?)
        )) OR (ref_type = 'summary' AND ref_id IN (
            SELECT CAST(value AS TEXT) FROM json_each(?)
        ))
        UNION
        SELECT DISTINCT seed_id FROM experience_seeds
        WHERE (source_ref_type = 'event' AND source_ref_id IN (
            SELECT CAST(value AS TEXT) FROM json_each(?)
        )) OR (source_ref_type = 'episode' AND source_ref_id IN (
            SELECT CAST(value AS TEXT) FROM json_each(?)
        )) OR (source_ref_type = 'summary' AND source_ref_id IN (
            SELECT CAST(value AS TEXT) FROM json_each(?)
        ))
        """,
        (
            event_json,
            episode_json,
            summary_json,
            event_json,
            episode_json,
            summary_json,
        ),
    )
    seed_json = _event_json(tuple(affected_seeds))
    affected_experiences.extend(
        experience_id
        for experience_id in await _select_ids(
            db,
            """
            SELECT experience_id FROM experiences
            WHERE source_seed_id IN (
                SELECT CAST(value AS TEXT) FROM json_each(?)
            )
            """,
            (seed_json,),
        )
        if experience_id not in affected_experiences
    )

    await db.execute(
        """
        DELETE FROM episode_events
        WHERE event_id IN (SELECT CAST(value AS TEXT) FROM json_each(?))
        """,
        (event_json,),
    )
    await db.execute(
        """
        DELETE FROM experience_members
        WHERE (member_type = 'event' AND member_id IN (
            SELECT CAST(value AS TEXT) FROM json_each(?)
        )) OR (member_type = 'episode' AND member_id IN (
            SELECT CAST(value AS TEXT) FROM json_each(?)
        ))
        """,
        (event_json, episode_json),
    )
    await db.execute(
        """
        DELETE FROM experience_key_events
        WHERE event_id IN (SELECT CAST(value AS TEXT) FROM json_each(?))
        """,
        (event_json,),
    )
    await _remove_forgotten_chapter_refs(
        db,
        experience_ids=affected_experiences,
        event_ids=set(event_ids),
        episode_ids=set(affected_episodes),
        now=now,
    )
    await db.execute(
        """
        DELETE FROM experience_seed_evidence
        WHERE (ref_type = 'event' AND ref_id IN (
            SELECT CAST(value AS TEXT) FROM json_each(?)
        )) OR (ref_type = 'episode' AND ref_id IN (
            SELECT CAST(value AS TEXT) FROM json_each(?)
        )) OR (ref_type = 'summary' AND ref_id IN (
            SELECT CAST(value AS TEXT) FROM json_each(?)
        ))
        """,
        (event_json, episode_json, summary_json),
    )
    await db.execute(
        """
        UPDATE summaries
        SET derivation_state = 'retired', updated_at = ?
        WHERE summary_id IN (
            SELECT CAST(value AS TEXT) FROM json_each(?)
        )
        """,
        (now, summary_json),
    )
    await db.execute(
        """
        DELETE FROM l3_summaries_fts
        WHERE summary_id IN (
            SELECT CAST(value AS TEXT) FROM json_each(?)
        )
        """,
        (summary_json,),
    )

    for episode_id in affected_episodes:
        async with db.execute(
            "SELECT COUNT(*) FROM episode_events WHERE episode_id = ?",
            (episode_id,),
        ) as cursor:
            row = await cursor.fetchone()
        source_count = int(row[0]) if row else 0
        await db.execute(
            """
            UPDATE episodes
            SET status = 'invalidated', source_event_count = ?,
                embedding_status = 'pending', embedding_profile_id = NULL,
                last_embedded_at = NULL, last_recomputed_at = ?, updated_at = ?
            WHERE episode_id = ?
            """,
            (source_count, now, now, episode_id),
        )
        await db.execute("DELETE FROM episodes_fts WHERE episode_id = ?", (episode_id,))

    for experience_id in affected_experiences:
        source_episode_count, source_event_count = await _experience_source_counts(
            db,
            experience_id=experience_id,
        )
        await db.execute(
            """
            UPDATE experiences
            SET status = 'invalidated', source_episode_count = ?,
                source_event_count = ?, last_recomputed_at = ?, updated_at = ?
            WHERE experience_id = ?
            """,
            (source_episode_count, source_event_count, now, now, experience_id),
        )

    for seed_id in affected_seeds:
        await db.execute(
            """
            UPDATE experience_seeds
            SET status = 'stale',
                title = CASE WHEN created_by = 'user' THEN title ELSE NULL END,
                description = NULL,
                source_ref_type = CASE
                    WHEN (source_ref_type = 'event' AND source_ref_id IN (
                        SELECT CAST(value AS TEXT) FROM json_each(?)
                    )) OR (source_ref_type = 'episode' AND source_ref_id IN (
                        SELECT CAST(value AS TEXT) FROM json_each(?)
                    )) OR (source_ref_type = 'summary' AND source_ref_id IN (
                        SELECT CAST(value AS TEXT) FROM json_each(?)
                    )) THEN NULL ELSE source_ref_type END,
                source_ref_id = CASE
                    WHEN (source_ref_type = 'event' AND source_ref_id IN (
                        SELECT CAST(value AS TEXT) FROM json_each(?)
                    )) OR (source_ref_type = 'episode' AND source_ref_id IN (
                        SELECT CAST(value AS TEXT) FROM json_each(?)
                    )) OR (source_ref_type = 'summary' AND source_ref_id IN (
                        SELECT CAST(value AS TEXT) FROM json_each(?)
                    )) THEN NULL ELSE source_ref_id END,
                updated_at = ?, last_evaluated_at = ?
            WHERE seed_id = ?
            """,
            (
                event_json,
                episode_json,
                summary_json,
                event_json,
                episode_json,
                summary_json,
                now,
                now,
                seed_id,
            ),
        )

    return {
        "episodes": len(affected_episodes),
        "experiences": len(affected_experiences),
        "experience_seeds": len(affected_seeds),
    }


async def _select_ids(
    db: aiosqlite.Connection,
    query: str,
    args: tuple[Any, ...],
) -> list[str]:
    async with db.execute(query, args) as cursor:
        return list(dict.fromkeys(str(row[0]) for row in await cursor.fetchall() if row[0]))


async def _remove_forgotten_chapter_refs(
    db: aiosqlite.Connection,
    *,
    experience_ids: Iterable[str],
    event_ids: set[str],
    episode_ids: set[str],
    now: float,
) -> None:
    for experience_id in experience_ids:
        async with db.execute(
            """
            SELECT chapter_id, event_ids_json, episode_ids_json
            FROM experience_chapters WHERE experience_id = ?
            """,
            (experience_id,),
        ) as cursor:
            rows = await cursor.fetchall()
        for row in rows:
            chapter_event_ids = _safe_json_id_list(row[1])
            chapter_episode_ids = _safe_json_id_list(row[2])
            await db.execute(
                """
                UPDATE experience_chapters
                SET event_ids_json = ?, episode_ids_json = ?, updated_at = ?
                WHERE experience_id = ? AND chapter_id = ?
                """,
                (
                    json.dumps(
                        [event_id for event_id in chapter_event_ids if event_id not in event_ids],
                        ensure_ascii=False,
                    ),
                    json.dumps(
                        [
                            episode_id
                            for episode_id in chapter_episode_ids
                            if episode_id not in episode_ids
                        ],
                        ensure_ascii=False,
                    ),
                    now,
                    experience_id,
                    str(row[0]),
                ),
            )


async def _experience_source_counts(
    db: aiosqlite.Connection,
    *,
    experience_id: str,
) -> tuple[int, int]:
    async with db.execute(
        """
        SELECT COUNT(DISTINCT member_id) FROM experience_members
        WHERE experience_id = ? AND member_type = 'episode' AND role != 'excluded'
        """,
        (experience_id,),
    ) as cursor:
        episode_row = await cursor.fetchone()
    async with db.execute(
        """
        SELECT COUNT(DISTINCT event_id) FROM (
            SELECT episode_events.event_id
            FROM experience_members
            JOIN episode_events ON episode_events.episode_id = experience_members.member_id
            WHERE experience_members.experience_id = ?
              AND experience_members.member_type = 'episode'
              AND experience_members.role != 'excluded'
            UNION
            SELECT member_id AS event_id FROM experience_members
            WHERE experience_id = ? AND member_type = 'event' AND role != 'excluded'
        )
        """,
        (experience_id, experience_id),
    ) as cursor:
        event_row = await cursor.fetchone()
    return (
        int(episode_row[0]) if episode_row else 0,
        int(event_row[0]) if event_row else 0,
    )


def _safe_json_id_list(value: Any) -> list[str]:
    try:
        decoded = json.loads(value) if isinstance(value, str) else value
    except (TypeError, json.JSONDecodeError):
        return []
    if not isinstance(decoded, list):
        return []
    return list(dict.fromkeys(str(item).strip() for item in decoded if str(item).strip()))


async def _assertion_claims_for_events(
    db: aiosqlite.Connection,
    event_ids: tuple[str, ...],
) -> dict[str, ForgottenClaim]:
    event_json = _event_json(event_ids)
    async with db.execute(
        """
        SELECT assertion_id, entity_id, entity_type, target_entity_id,
               trait_name, trait_value, slot_key, scope_key,
               claim_fingerprint, evidence_events
        FROM tom_trait_assertions AS assertion
        WHERE EXISTS (
            SELECT 1 FROM memory_claim_evidence_events AS evidence
            WHERE evidence.target_kind = 'assertion'
              AND evidence.claim_fingerprint = assertion.claim_fingerprint
              AND evidence.event_id IN (
                  SELECT CAST(value AS TEXT) FROM json_each(?)
              )
        ) OR EXISTS (
            SELECT 1
            FROM json_each(CASE
                WHEN json_valid(assertion.evidence_events)
                    THEN assertion.evidence_events
                ELSE '[]'
            END) AS raw
            WHERE CAST(raw.value AS TEXT) IN (
                SELECT CAST(value AS TEXT) FROM json_each(?)
            )
        ) OR EXISTS (
            SELECT 1 FROM memory_corrections AS correction
            WHERE assertion.authority_ref = 'correction:' || correction.correction_id
              AND correction.source_event_id IN (
                  SELECT CAST(value AS TEXT) FROM json_each(?)
              )
        )
        ORDER BY assertion_id
        """,
        (event_json, event_json, event_json),
    ) as cursor:
        rows = await cursor.fetchall()

    claims: dict[str, ForgottenClaim] = {}
    for row in rows:
        record_id = str(row["assertion_id"])
        slot = str(row["slot_key"] or "") or assertion_slot_key(
            entity_type=str(row["entity_type"] or ""),
            entity_id=str(row["entity_id"] or ""),
            trait_name=str(row["trait_name"] or ""),
            target_entity_id=str(row["target_entity_id"] or ""),
        )
        fingerprint = str(row["claim_fingerprint"] or "") or assertion_claim_fingerprint(
            slot_key_value=slot,
            trait_value=row["trait_value"],
            scope_key_value=str(row["scope_key"] or "global"),
        )
        evidence_ids, _ = decode_evidence_event_ids(row["evidence_events"])
        entity_id = str(row["entity_id"] or "").strip()
        target_id = str(row["target_entity_id"] or "").strip()
        claims[record_id] = ForgottenClaim(
            record_id=record_id,
            claim_fingerprint=fingerprint,
            semantic_fingerprint=assertion_claim_fingerprint(
                slot_key_value=slot,
                trait_value=row["trait_value"],
            ),
            evidence_event_ids=evidence_ids,
            evidence_fail_closed=False,
            subject_keys=tuple(
                key for key in (entity_id, target_id if ":" in target_id else "") if key
            ),
        )
    return claims


async def _relationship_claims_for_events(
    db: aiosqlite.Connection,
    event_ids: tuple[str, ...],
) -> dict[str, ForgottenClaim]:
    event_json = _event_json(event_ids)
    claims: dict[str, ForgottenClaim] = {}
    async with db.execute(
        """
        SELECT triple_id, subject_id, predicate, object_id, slot_key, scope_key,
               claim_fingerprint, evidence_event_ids
        FROM knowledge_graph AS edge
        WHERE EXISTS (
            SELECT 1 FROM memory_claim_evidence_events AS evidence
            WHERE evidence.target_kind = 'edge'
              AND evidence.claim_fingerprint = edge.claim_fingerprint
              AND evidence.event_id IN (
                  SELECT CAST(value AS TEXT) FROM json_each(?)
              )
        ) OR EXISTS (
            SELECT 1
            FROM json_each(CASE
                WHEN json_valid(edge.evidence_event_ids)
                    THEN edge.evidence_event_ids
                ELSE '[]'
            END) AS raw
            WHERE CAST(raw.value AS TEXT) IN (
                SELECT CAST(value AS TEXT) FROM json_each(?)
            )
        ) OR EXISTS (
            SELECT 1 FROM memory_corrections AS correction
            WHERE edge.authority_ref = 'correction:' || correction.correction_id
              AND correction.source_event_id IN (
                  SELECT CAST(value AS TEXT) FROM json_each(?)
              )
        )
        ORDER BY triple_id
        """,
        (event_json, event_json, event_json),
    ) as cursor:
        current_rows = await cursor.fetchall()
    for row in current_rows:
        _add_relationship_claim(claims, key=str(row["triple_id"]), row=row)

    async with db.execute(
        """
        SELECT version_id, triple_id, subject_id, predicate, object_id, slot_key,
               scope_key, claim_fingerprint, evidence_event_ids, correction_id
        FROM knowledge_graph_versions AS version
        WHERE version.governance_complete = 1 AND (
            EXISTS (
                SELECT 1 FROM memory_claim_evidence_events AS evidence
                WHERE evidence.target_kind = 'edge'
                  AND evidence.claim_fingerprint = version.claim_fingerprint
                  AND evidence.event_id IN (
                      SELECT CAST(value AS TEXT) FROM json_each(?)
                  )
            ) OR EXISTS (
                SELECT 1
                FROM json_each(CASE
                    WHEN json_valid(version.evidence_event_ids)
                        THEN version.evidence_event_ids
                    ELSE '[]'
                END) AS raw
                WHERE CAST(raw.value AS TEXT) IN (
                    SELECT CAST(value AS TEXT) FROM json_each(?)
                )
            ) OR EXISTS (
                SELECT 1 FROM memory_corrections AS correction
                WHERE version.correction_id = correction.correction_id
                  AND correction.source_event_id IN (
                      SELECT CAST(value AS TEXT) FROM json_each(?)
                  )
            )
        )
        ORDER BY version.created_at, version.version_id
        """,
        (event_json, event_json, event_json),
    ) as cursor:
        history_rows = await cursor.fetchall()
    for row in history_rows:
        _add_relationship_claim(
            claims,
            key=f"history:{row['version_id']}",
            row=row,
            correction_id=str(row["correction_id"] or ""),
        )
    return claims


def _add_relationship_claim(
    claims: dict[str, ForgottenClaim],
    *,
    key: str,
    row: Mapping[str, Any],
    correction_id: str = "",
) -> None:
    record_id = str(row["triple_id"])
    slot = str(row["slot_key"] or "") or relationship_slot_key(
        subject_id=str(row["subject_id"] or ""),
        predicate=str(row["predicate"] or ""),
        object_id=str(row["object_id"] or ""),
    )
    fingerprint = str(row["claim_fingerprint"] or "") or relationship_claim_fingerprint(
        slot_key_value=slot,
        subject_id=str(row["subject_id"] or ""),
        predicate=str(row["predicate"] or ""),
        object_id=str(row["object_id"] or ""),
        scope_key_value=str(row["scope_key"] or "global"),
    )
    evidence_ids, _ = decode_evidence_event_ids(row["evidence_event_ids"])
    subject_id = str(row["subject_id"] or "").strip()
    object_id = str(row["object_id"] or "").strip()
    claims[key] = ForgottenClaim(
        record_id=record_id,
        claim_fingerprint=fingerprint,
        semantic_fingerprint=relationship_claim_fingerprint(
            slot_key_value=slot,
            subject_id=subject_id,
            predicate=str(row["predicate"] or ""),
            object_id=object_id,
        ),
        evidence_event_ids=evidence_ids,
        evidence_fail_closed=False,
        subject_keys=tuple(
            key for key in (subject_id, object_id if ":" in object_id else "") if key
        ),
        correction_ids=((correction_id,) if correction_id else ()),
    )


async def _forgotten_events_by_claim(
    db: aiosqlite.Connection,
    *,
    target_kind: CorrectionTargetKind,
    claims: Mapping[str, ForgottenClaim],
    event_ids: tuple[str, ...],
) -> dict[str, tuple[str, ...]]:
    if not claims:
        return {}
    target_ids = set(event_ids)
    evidence_by_claim = await claim_evidence_records_for_claims(
        db,
        target_kind=target_kind,
        claim_fingerprints=(claim.claim_fingerprint for claim in claims.values()),
    )
    linked_by_claim: dict[str, set[str]] = {}
    for key, claim in claims.items():
        linked = {
            record.event_id
            for record in evidence_by_claim.get(claim.claim_fingerprint, ())
        }
        linked.update(claim.evidence_event_ids)
        if claim.correction_ids:
            placeholders = ", ".join("?" for _ in claim.correction_ids)
            async with db.execute(
                f"""
                SELECT source_event_id
                FROM memory_corrections
                WHERE correction_id IN ({placeholders})
                  AND source_event_id IS NOT NULL
                """,
                claim.correction_ids,
            ) as cursor:
                linked.update(
                    str(row[0]).strip()
                    for row in await cursor.fetchall()
                    if row[0] is not None and str(row[0]).strip()
                )
        linked_by_claim[key] = linked

    tombstoned_event_ids = await source_event_tombstone_ids(
        db,
        (
            event_id
            for linked in linked_by_claim.values()
            for event_id in linked
        ),
    )
    governed_event_ids = target_ids | tombstoned_event_ids
    result: dict[str, tuple[str, ...]] = {}
    for key, linked in linked_by_claim.items():
        forgotten = linked & governed_event_ids
        if forgotten:
            result[key] = tuple(sorted(forgotten))
    return result


async def _remove_assertion_evidence(
    db: aiosqlite.Connection,
    *,
    claims: Mapping[str, ForgottenClaim],
    forgotten_by_claim: Mapping[str, tuple[str, ...]],
    now: float,
) -> int:
    current_claims = {key: claim for key, claim in claims.items() if not key.startswith("history:")}
    evidence_by_claim = await claim_evidence_records_for_claims(
        db,
        target_kind=CorrectionTargetKind.ASSERTION,
        claim_fingerprints=(claim.claim_fingerprint for claim in current_claims.values()),
    )
    affected = 0
    for key, claim in current_claims.items():
        forgotten = set(forgotten_by_claim.get(key, ()))
        if not forgotten:
            continue
        async with db.execute(
            """
            SELECT evidence_events, first_inferred_at, last_validated_at,
                   confidence_score, validation_state, status, trait_name,
                   user_feedback, valid_from, valid_to
            FROM tom_trait_assertions
            WHERE assertion_id = ? AND claim_fingerprint = ?
            """,
            (claim.record_id, claim.claim_fingerprint),
        ) as cursor:
            row = await cursor.fetchone()
        if row is None:
            continue
        raw_ids, malformed = decode_evidence_event_ids(row[0])
        records = _records_for_segment(
            evidence_by_claim.get(claim.claim_fingerprint, ()),
            raw_event_ids=set(raw_ids),
            segment_start=float(row[8]) if row[8] is not None else float(row[1]),
            segment_end=float(row[9]) if row[9] is not None else math.inf,
        )
        retained_records = [record for record in records if record.event_id not in forgotten]
        retained_ids = _bounded_retained_ids(
            [record.event_id for record in retained_records]
            + [event_id for event_id in raw_ids if event_id not in forgotten]
        )
        if malformed or not retained_ids:
            cursor = await db.execute(
                """
                UPDATE tom_trait_assertions
                SET status = 'archived', evidence_events = '[]',
                    authority_ref = CASE
                        WHEN authority_ref = 'forget:entity' THEN authority_ref
                        ELSE 'forget:event'
                    END,
                    updated_at = ?
                WHERE assertion_id = ?
                """,
                (now, claim.record_id),
            )
        else:
            first_at, last_at = _retained_bounds(
                retained_records,
                fallback_from=float(row[1]),
                fallback_to=float(row[2]),
            )
            confidence = min(float(row[3]), compute_confidence(len(retained_ids)))
            validation_state, confidence, _ = derive_validation_state(
                current_state=str(row[4] or "tentative"),
                current_confidence=confidence,
                evidence_count=len(retained_ids),
                time_span_hours=max(0.0, (last_at - first_at) / 3600.0),
                trait_name=str(row[6] or ""),
                user_feedback=str(row[7]) if row[7] is not None else None,
            )
            current_status = str(row[5] or "")
            next_status = (
                validation_state if current_status in ACTIVE_VALIDATION_STATES else current_status
            )
            cursor = await db.execute(
                """
                UPDATE tom_trait_assertions
                SET evidence_events = ?, first_inferred_at = ?,
                    last_validated_at = ?, confidence_score = ?,
                    validation_state = ?, status = ?, updated_at = ?
                WHERE assertion_id = ?
                """,
                (
                    json.dumps(retained_ids, ensure_ascii=False),
                    first_at,
                    last_at,
                    confidence,
                    validation_state,
                    next_status,
                    now,
                    claim.record_id,
                ),
            )
        affected += max(int(cursor.rowcount or 0), 0)
    return affected


async def _remove_relationship_evidence(
    db: aiosqlite.Connection,
    *,
    claims: Mapping[str, ForgottenClaim],
    forgotten_by_claim: Mapping[str, tuple[str, ...]],
    now: float,
) -> int:
    current_claims = {key: claim for key, claim in claims.items() if not key.startswith("history:")}
    evidence_by_claim = await claim_evidence_records_for_claims(
        db,
        target_kind=CorrectionTargetKind.EDGE,
        claim_fingerprints=(claim.claim_fingerprint for claim in current_claims.values()),
    )
    affected = 0
    for key, claim in current_claims.items():
        forgotten = set(forgotten_by_claim.get(key, ()))
        if not forgotten:
            continue
        async with db.execute(
            """
            SELECT evidence_event_ids, first_observed_at, last_observed_at,
                   confidence, observation_count, valid_from, valid_to
            FROM knowledge_graph
            WHERE triple_id = ? AND claim_fingerprint = ?
            """,
            (claim.record_id, claim.claim_fingerprint),
        ) as cursor:
            row = await cursor.fetchone()
        if row is None:
            continue
        raw_ids, malformed = decode_evidence_event_ids(row[0])
        records = _records_for_segment(
            evidence_by_claim.get(claim.claim_fingerprint, ()),
            raw_event_ids=set(raw_ids),
            segment_start=float(row[5]) if row[5] is not None else float(row[1]),
            segment_end=float(row[6]) if row[6] is not None else math.inf,
        )
        retained_records = [record for record in records if record.event_id not in forgotten]
        retained_ids = _bounded_retained_ids(
            [record.event_id for record in retained_records]
            + [event_id for event_id in raw_ids if event_id not in forgotten]
        )
        if malformed or not retained_ids:
            cursor = await db.execute(
                """
                UPDATE knowledge_graph
                SET status = 'archived', status_reason = 'user_forget',
                    evidence_event_ids = '[]', observation_count = 0,
                    evidence_text = '', natural_summary = '',
                    embedding_status = 'pending',
                    authority_ref = CASE
                        WHEN authority_ref = 'forget:entity' THEN authority_ref
                        ELSE 'forget:event'
                    END,
                    updated_at = ?
                WHERE triple_id = ?
                """,
                (now, claim.record_id),
            )
        else:
            first_at, last_at = _retained_bounds(
                retained_records,
                fallback_from=float(row[1]),
                fallback_to=float(row[2]),
            )
            original_count = max(int(row[4] or 0), len(raw_ids), 1)
            retained_count = len(retained_ids)
            confidence = _reduced_relationship_confidence(
                float(row[3]),
                retained_count=retained_count,
                original_count=original_count,
            )
            cursor = await db.execute(
                """
                UPDATE knowledge_graph
                SET evidence_event_ids = ?, observation_count = ?,
                    confidence = ?, first_observed_at = ?, last_observed_at = ?,
                    last_confirmed_at = ?, evidence_text = '', natural_summary = '',
                    embedding_status = 'pending', updated_at = ?
                WHERE triple_id = ?
                """,
                (
                    json.dumps(retained_ids, ensure_ascii=False),
                    retained_count,
                    confidence,
                    first_at,
                    last_at,
                    last_at,
                    now,
                    claim.record_id,
                ),
            )
        affected += max(int(cursor.rowcount or 0), 0)
        await append_knowledge_graph_version(
            db,
            triple_id=claim.record_id,
            created_at=now,
        )
    return affected


def _claims_by_record_id(
    claims: Mapping[str, ForgottenClaim],
) -> dict[str, ForgottenClaim]:
    result: dict[str, ForgottenClaim] = {}
    for claim in claims.values():
        result.setdefault(claim.record_id, claim)
    return result


def _records_for_segment(
    records: Iterable[Any],
    *,
    raw_event_ids: set[str],
    segment_start: float,
    segment_end: float,
) -> list[Any]:
    return [
        record
        for record in records
        if record.event_id in raw_event_ids
        or (record.observed_from <= segment_end and record.observed_to >= segment_start)
    ]


def _bounded_retained_ids(event_ids: Iterable[str]) -> list[str]:
    normalized = list(dict.fromkeys(str(event_id) for event_id in event_ids if str(event_id)))
    return normalized[-max_evidence_event_ids() :]


def _retained_bounds(
    records: Iterable[Any],
    *,
    fallback_from: float,
    fallback_to: float,
) -> tuple[float, float]:
    materialized = list(records)
    if not materialized:
        return min(fallback_from, fallback_to), max(fallback_from, fallback_to)
    return (
        min(record.observed_from for record in materialized),
        max(record.observed_to for record in materialized),
    )


def _reduced_relationship_confidence(
    confidence: float,
    *,
    retained_count: int,
    original_count: int,
) -> float:
    if retained_count >= original_count:
        return confidence
    bounded = min(max(confidence, 0.0), 1.0)
    if retained_count <= 0:
        return 0.0
    return 1.0 - math.pow(1.0 - bounded, retained_count / original_count)


def _event_json(event_ids: tuple[str, ...]) -> str:
    return json.dumps(event_ids, ensure_ascii=False, separators=(",", ":"))


__all__ = ["L2StoreSourceEventForgettingMixin"]
