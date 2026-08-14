"""User-driven forgetting of canonical source events and their L2 evidence."""

from __future__ import annotations

import json
import math
import time
from collections.abc import Iterable, Mapping
from datetime import datetime
from typing import Any, Protocol, cast

import aiosqlite

from ....core.logger import get_logger
from ....core.sqlite import sqlite_connection_async
from ...source_event_governance import (
    normalize_source_event_ids,
    source_event_tombstone_ids,
    tombstone_source_event_ids,
)
from ..assertion_family_policy import get_assertion_family_policy
from ..assertions.occurrence_stats import (
    ClaimOccurrenceStats,
    ClaimRouteValueKey,
    load_routed_claim_occurrence_stats_on_connection,
)
from ..assertions.promotion import (
    AssertionPromotionDecision,
    AssertionPromotionInput,
    PromotionHorizon,
    evaluate_assertion_promotion,
)
from ..assertions.settings import momentary_ttl_seconds
from ..assertions.state_machine import (
    ACTIVE_VALIDATION_STATES,
    compute_confidence,
    derive_validation_state,
)
from ..assertions.subdomain import classify_memory_subdomain
from ..claims.route_selection import (
    CURRENT_ENTITY_REF_VERSIONS_CTE,
    LATEST_ROUTE_ORDER_SQL,
)
from ..claims.outcomes import (
    ClaimTargetOutcomeContext,
    append_claim_target_outcomes_on_connection,
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

    async def _stage_source_event_link_forget_on_connection(
        self,
        db: aiosqlite.Connection,
        *,
        event_ids: tuple[str, ...],
        reason: str,
    ) -> int: ...


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
        """Block source events and reconcile Claim-backed assertions atomically."""
        host = cast(_SourceEventForgettingHostProtocol, self)
        await host.initialize()
        normalized = normalize_source_event_ids(event_ids)
        if not normalized:
            return 0
        affected_subjects: dict[str, int] = {}
        async with host.memory_correction_job_guard():
            async with sqlite_connection_async(host.db_path) as db:
                db.row_factory = aiosqlite.Row
                await db.execute("BEGIN IMMEDIATE")
                try:
                    now = time.time()
                    inserted = int(
                        await tombstone_source_event_ids(
                            db,
                            event_ids=normalized,
                            reason=reason,
                            created_at=now,
                        )
                    )
                    await _complete_forgotten_projection_jobs(
                        db,
                        event_ids=normalized,
                        now=now,
                    )
                    assertion_route_keys = await _assertion_route_keys_for_source_events(
                        db,
                        event_ids=normalized,
                    )
                    await redact_grounded_claims_for_source_events(
                        db,
                        event_ids=normalized,
                        reason=reason,
                        now=now,
                    )
                    reconciled_assertions = await _reconcile_assertion_promotion_after_forget(
                        db,
                        route_keys_by_assertion=assertion_route_keys,
                        now=now,
                    )
                    affected_subjects = await invalidate_forgotten_derivations(
                        db,
                        repository=MemoryCorrectionRepository(host.db_path),
                        forgotten_assertions=reconciled_assertions,
                        forgotten_edges={},
                        now=now,
                    )
                    await db.commit()
                except Exception:
                    await db.rollback()
                    raise
        for subject_key in affected_subjects:
            mark_subject_changed(host.db_path, subject_key)
        await rebuild_forgotten_subject_views(host=host, revisions=affected_subjects)
        return inserted

    async def forget_source_events(
        self,
        event_ids: Iterable[str],
        *,
        reason: str,
        persist_barrier: bool = True,
        retain_replay_barriers: bool = True,
    ) -> dict[str, int]:
        """Forget source events and govern whether their stable IDs may replay."""
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
                    if retain_replay_barriers:
                        result["projection_jobs"] = await _complete_forgotten_projection_jobs(
                            db,
                            event_ids=normalized,
                            now=now,
                        )
                    else:
                        reimportable_event_ids = await _reimportable_source_event_ids(
                            db,
                            event_ids=normalized,
                        )
                        result["projection_jobs"] = await _release_reimportable_projection_jobs(
                            db,
                            event_ids=reimportable_event_ids,
                            now=now,
                        )
                        await _release_reimportable_event_forget_rules(
                            db,
                            event_ids=reimportable_event_ids,
                        )
                    assertion_route_keys = await _assertion_route_keys_for_source_events(
                        db,
                        event_ids=normalized,
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
                    result["tom_trait_assertions"] += await _remove_assertion_evidence(
                        db,
                        claims=assertion_claims,
                        forgotten_by_claim=assertion_events,
                        now=now,
                    )
                    result["knowledge_graph"] += await _remove_relationship_evidence(
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
                    if retain_replay_barriers:
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
                    reconciled_assertions = await _reconcile_assertion_promotion_after_forget(
                        db,
                        route_keys_by_assertion=assertion_route_keys,
                        now=now,
                    )
                    result["tom_trait_assertions"] = max(
                        result["tom_trait_assertions"],
                        len(reconciled_assertions),
                    )

                    forgotten_assertions = _claims_by_record_id(assertion_claims)
                    forgotten_assertions.update(reconciled_assertions)
                    affected_subjects = await invalidate_forgotten_derivations(
                        db,
                        repository=MemoryCorrectionRepository(host.db_path),
                        forgotten_assertions=forgotten_assertions,
                        forgotten_edges=_claims_by_record_id(edge_claims),
                        now=now,
                        explicit_subject_keys=correction_subjects,
                    )
                    result[
                        "event_entity_links"
                    ] = await host._stage_source_event_link_forget_on_connection(
                        db,
                        event_ids=normalized,
                        reason=reason,
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
        "event_entity_links": 0,
        "l2_claim_evidence": 0,
        "l2_claim_entity_refs": 0,
        "l2_grounded_claims": 0,
        "l2_claim_projection_outcomes": 0,
        "l2_pending_reviews": 0,
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


async def _assertion_route_keys_for_source_events(
    db: aiosqlite.Connection,
    *,
    event_ids: tuple[str, ...],
) -> dict[str, set[ClaimRouteValueKey]]:
    """Capture current Claim-owned assertion identities before Claim redaction."""

    event_json = _event_json(event_ids)
    async with db.execute(
        f"""
        WITH affected_claims AS (
            SELECT DISTINCT evidence.claim_id
            FROM l2_claim_evidence AS evidence
            JOIN l2_grounded_claims AS claims
              ON claims.claim_id = evidence.claim_id
             AND claims.availability = 'active'
            WHERE evidence.event_id IN (
                SELECT CAST(value AS TEXT) FROM json_each(?)
            )
        ),
        {CURRENT_ENTITY_REF_VERSIONS_CTE},
        latest_routes AS (
            SELECT
                outcomes.claim_id,
                outcomes.attempt_key,
                outcomes.target_slot_key,
                outcomes.route_contract_version,
                outcomes.outcome,
                CAST(
                    json_extract(outcomes.details_json, '$.value_fingerprint')
                    AS TEXT
                ) AS value_fingerprint,
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
        affected_route_keys AS (
            SELECT DISTINCT
                latest_routes.target_slot_key,
                latest_routes.value_fingerprint
            FROM affected_claims
            JOIN latest_routes
              ON latest_routes.claim_id = affected_claims.claim_id
             AND latest_routes.route_rank = 1
             AND latest_routes.outcome = 'routed'
            WHERE latest_routes.target_slot_key IS NOT NULL
              AND latest_routes.value_fingerprint IS NOT NULL
        ),
        material_assertion_candidates AS (
            SELECT
                receipts.target_id AS assertion_id,
                current_routes.target_slot_key,
                current_routes.value_fingerprint,
                assertions.scope_key,
                assertions.status,
                assertions.updated_at,
                MAX(receipts.created_at) AS receipt_created_at
            FROM affected_route_keys
            JOIN latest_routes AS current_routes
              ON current_routes.target_slot_key = affected_route_keys.target_slot_key
             AND current_routes.value_fingerprint = affected_route_keys.value_fingerprint
             AND current_routes.route_rank = 1
             AND current_routes.outcome = 'routed'
            JOIN l2_grounded_claims AS current_claims
              ON current_claims.claim_id = current_routes.claim_id
             AND current_claims.availability = 'active'
            JOIN l2_claim_projection_outcomes AS receipts
              ON receipts.claim_id = current_routes.claim_id
             AND receipts.attempt_key = current_routes.attempt_key
             AND receipts.route_contract_version = current_routes.route_contract_version
             AND receipts.target_kind = 'assertion'
             AND receipts.outcome = 'projected'
             AND receipts.invalidated_at IS NULL
            JOIN tom_trait_assertions AS assertions
              ON assertions.assertion_id = receipts.target_id
             AND assertions.slot_key = current_routes.target_slot_key
             AND (
                    assertions.status IN ('tentative', 'corroborated', 'stable')
                    OR (
                        assertions.status = 'archived'
                        AND assertions.authority_ref = 'forget:event'
                    )
             )
            GROUP BY receipts.target_id, current_routes.target_slot_key,
                     current_routes.value_fingerprint, assertions.scope_key,
                     assertions.status, assertions.updated_at
        ),
        ranked_material_assertions AS (
            SELECT
                assertion_id,
                target_slot_key,
                value_fingerprint,
                ROW_NUMBER() OVER (
                    PARTITION BY target_slot_key, value_fingerprint, scope_key
                    ORDER BY
                        CASE
                            WHEN status IN ('tentative', 'corroborated', 'stable')
                                THEN 0
                            ELSE 1
                        END,
                        updated_at DESC,
                        receipt_created_at DESC,
                        assertion_id DESC
                ) AS assertion_rank
            FROM material_assertion_candidates
        )
        SELECT assertion_id, target_slot_key, value_fingerprint
        FROM ranked_material_assertions
        WHERE assertion_rank = 1
        ORDER BY assertion_id, target_slot_key, value_fingerprint
        """,
        (event_json,),
    ) as cursor:
        rows = await cursor.fetchall()

    result: dict[str, set[ClaimRouteValueKey]] = {}
    for row in rows:
        assertion_id = str(row["assertion_id"] or "").strip()
        if not assertion_id:
            continue
        result.setdefault(assertion_id, set()).add(
            ClaimRouteValueKey(
                target_slot_key=str(row["target_slot_key"]),
                value_fingerprint=str(row["value_fingerprint"]),
            )
        )
    return result


async def _reconcile_assertion_promotion_after_forget(
    db: aiosqlite.Connection,
    *,
    route_keys_by_assertion: Mapping[str, set[ClaimRouteValueKey]],
    now: float,
) -> dict[str, ForgottenClaim]:
    """Recompute materialized assertion horizons from the surviving Claim ledger."""

    if not route_keys_by_assertion:
        return {}
    route_keys = {key for keys in route_keys_by_assertion.values() for key in keys}
    stats_by_key = await load_routed_claim_occurrence_stats_on_connection(
        db,
        keys=route_keys,
        now=now,
        local_timezone=datetime.now().astimezone().tzinfo,
    )
    assertion_json = json.dumps(
        sorted(route_keys_by_assertion),
        ensure_ascii=False,
        separators=(",", ":"),
    )
    async with db.execute(
        """
        SELECT assertion_id, entity_id, entity_type, target_entity_id,
               trait_family, trait_name, trait_value, status, slot_key, scope_key,
               claim_fingerprint,
               validation_state, confidence_score, evidence_events,
               first_inferred_at, last_validated_at, temporal_scope,
               decay_policy, decay_anchor_at, expires_at, memory_subdomain,
               authority_ref, user_feedback
        FROM tom_trait_assertions
        WHERE assertion_id IN (
            SELECT CAST(value AS TEXT) FROM json_each(?)
        )
        """,
        (assertion_json,),
    ) as cursor:
        assertion_rows = {str(row["assertion_id"]): dict(row) for row in await cursor.fetchall()}

    changed: dict[str, ForgottenClaim] = {}
    for assertion_id in sorted(route_keys_by_assertion):
        row = assertion_rows.get(assertion_id)
        if row is None or _assertion_status_is_terminal(row.get("status")):
            continue
        if (
            str(row.get("status") or "").strip().casefold() == "archived"
            and str(row.get("authority_ref") or "") != "forget:event"
        ):
            continue
        if await _has_independent_assertion_authority(
            db,
            authority_ref=row.get("authority_ref"),
            user_feedback=row.get("user_feedback"),
        ):
            continue
        keys = route_keys_by_assertion[assertion_id]
        stats = stats_by_key.get(next(iter(keys))) if len(keys) == 1 else None
        decision = _promotion_after_forget(row=row, stats=stats) if stats is not None else None
        if (
            decision is not None
            and stats is not None
            and str(row.get("trait_family") or "").strip().casefold() == "goal_profile"
            and not await _goal_claims_remain_projectable(
                db,
                stats=stats,
                now=now,
            )
        ):
            decision = None
        if decision is None or decision.horizon is PromotionHorizon.EVENT_ONLY:
            updated = await _archive_assertion_after_promotion_loss(
                db,
                assertion_id=assertion_id,
                row=row,
                stats=stats,
                decision=decision,
                now=now,
            )
            if updated:
                changed[assertion_id] = _reconciled_assertion_claim(row)
            continue
        if str(
            row.get("status") or ""
        ).strip().casefold() == "archived" and await _slot_has_other_active_assertion(
            db,
            assertion_id=assertion_id,
            slot_key=str(row.get("slot_key") or ""),
            scope_key=str(row.get("scope_key") or "global"),
        ):
            continue
        if stats is None:
            raise RuntimeError("Promotion decision is missing occurrence statistics")
        await _bind_surviving_claims_to_assertion(
            db,
            assertion_id=assertion_id,
            stats=stats,
            now=now,
        )
        updated = await _apply_recomputed_assertion_lifecycle(
            db,
            assertion_id=assertion_id,
            row=row,
            stats=stats,
            decision=decision,
            now=now,
        )
        if updated:
            changed[assertion_id] = _reconciled_assertion_claim(row)
    return changed


async def _slot_has_other_active_assertion(
    db: aiosqlite.Connection,
    *,
    assertion_id: str,
    slot_key: str,
    scope_key: str,
) -> bool:
    async with db.execute(
        """
        SELECT 1
        FROM tom_trait_assertions
        WHERE slot_key = ? AND scope_key = ? AND assertion_id != ?
          AND status IN ('tentative', 'corroborated', 'stable')
        LIMIT 1
        """,
        (slot_key, scope_key, assertion_id),
    ) as cursor:
        return await cursor.fetchone() is not None


def _reconciled_assertion_claim(row: Mapping[str, Any]) -> ForgottenClaim:
    assertion_id = str(row.get("assertion_id") or "")
    slot_key = str(row.get("slot_key") or "")
    entity_id = str(row.get("entity_id") or "").strip()
    target_entity_id = str(row.get("target_entity_id") or "").strip()
    evidence_event_ids, malformed = decode_evidence_event_ids(row.get("evidence_events"))
    return ForgottenClaim(
        record_id=assertion_id,
        claim_fingerprint=str(row.get("claim_fingerprint") or ""),
        semantic_fingerprint=assertion_claim_fingerprint(
            slot_key_value=slot_key,
            trait_value=row.get("trait_value"),
        ),
        evidence_event_ids=evidence_event_ids,
        evidence_fail_closed=malformed,
        subject_keys=tuple(
            value
            for value in (
                entity_id,
                target_entity_id if ":" in target_entity_id else "",
            )
            if value
        ),
    )


async def _bind_surviving_claims_to_assertion(
    db: aiosqlite.Connection,
    *,
    assertion_id: str,
    stats: ClaimOccurrenceStats,
    now: float,
) -> None:
    """Persist collective-promotion provenance for Claims without target receipts."""

    claim_json = json.dumps(stats.claim_ids, ensure_ascii=False, separators=(",", ":"))
    async with db.execute(
        f"""
        WITH requested_claims AS (
            SELECT CAST(value AS TEXT) AS claim_id FROM json_each(?)
        ),
        {CURRENT_ENTITY_REF_VERSIONS_CTE},
        latest_routes AS (
            SELECT
                outcomes.claim_id,
                outcomes.attempt_key,
                outcomes.target_slot_key,
                outcomes.route_contract_version,
                outcomes.outcome,
                CAST(
                    json_extract(outcomes.details_json, '$.value_fingerprint')
                    AS TEXT
                ) AS value_fingerprint,
                ROW_NUMBER() OVER (
                    PARTITION BY outcomes.claim_id
                    ORDER BY {LATEST_ROUTE_ORDER_SQL}
                ) AS route_rank
            FROM l2_claim_projection_outcomes AS outcomes
            JOIN requested_claims
              ON requested_claims.claim_id = outcomes.claim_id
            LEFT JOIN current_entity_ref_versions AS route_refs
              ON route_refs.claim_id = outcomes.claim_id
            WHERE outcomes.target_kind = 'route'
              AND outcomes.invalidated_at IS NULL
        )
        SELECT claim_id, attempt_key, route_contract_version
        FROM latest_routes
        WHERE route_rank = 1
          AND outcome = 'routed'
          AND target_slot_key = ?
          AND value_fingerprint = ?
          AND NOT EXISTS (
                SELECT 1
                FROM l2_claim_projection_outcomes AS target
                WHERE target.claim_id = latest_routes.claim_id
                  AND target.attempt_key = latest_routes.attempt_key
                  AND target.route_contract_version = latest_routes.route_contract_version
                  AND target.target_kind = 'assertion'
                  AND target.outcome = 'projected'
                  AND target.invalidated_at IS NULL
          )
        ORDER BY claim_id
        """,
        (
            claim_json,
            stats.key.target_slot_key,
            stats.key.value_fingerprint,
        ),
    ) as cursor:
        rows = await cursor.fetchall()
    for row in rows:
        await append_claim_target_outcomes_on_connection(
            db,
            context=ClaimTargetOutcomeContext.for_claim(
                claim_id=str(row[0]),
                attempt_key=str(row[1]),
                route_contract_version=int(row[2]),
            ),
            target_kind="assertion",
            target_id=assertion_id,
            target_slot_key=stats.key.target_slot_key,
            outcome="projected",
            reason_code="promotion_reconciled_after_forget",
            created_at=now,
        )


def _promotion_after_forget(
    *,
    row: Mapping[str, Any],
    stats: ClaimOccurrenceStats,
) -> AssertionPromotionDecision | None:
    if str(stats.temporal_cue or "").strip().casefold() == "recent":
        policy_event_ids = set(stats.recent_policy_event_ids)
        if not policy_event_ids or not policy_event_ids.issubset(set(stats.trusted_event_ids)):
            return None
    family = str(row.get("trait_family") or "").strip().casefold()
    trait_name = str(row.get("trait_name") or "").strip().casefold()
    policy = get_assertion_family_policy(family)
    baseline_scope: str | None
    baseline_decay: str | None
    baseline_ttl: float | None
    if trait_name in {"annoyance", "irritation", "frustration"}:
        baseline_scope = "momentary"
        baseline_decay = "fast_decay"
        baseline_ttl = momentary_ttl_seconds()
    else:
        baseline_scope = policy.default_temporal_scope if policy is not None else None
        baseline_decay = policy.default_decay_policy if policy is not None else None
        baseline_ttl = policy.default_ttl_seconds if policy is not None else None
    decision = evaluate_assertion_promotion(
        AssertionPromotionInput(
            trait_family=family,
            **stats.promotion_fields(),
            baseline_temporal_scope=baseline_scope,
            baseline_decay_policy=baseline_decay,
            baseline_ttl_seconds=baseline_ttl,
        )
    )
    if decision.horizon is PromotionHorizon.RECENT and stats.last_observed_at is None:
        return None
    return decision


async def _archive_assertion_after_promotion_loss(
    db: aiosqlite.Connection,
    *,
    assertion_id: str,
    row: Mapping[str, Any],
    stats: ClaimOccurrenceStats | None,
    decision: AssertionPromotionDecision | None,
    now: float,
) -> int:
    expiry = decision.expiry if decision is not None else None
    evidence_event_ids = _bounded_claim_evidence_ids(stats)
    first_inferred_at, last_validated_at, validation_state, confidence = (
        _recomputed_assertion_evidence(row=row, stats=stats)
    )
    anchor = stats.last_observed_at if stats is not None else None
    anchor = anchor or now
    expires_at = (
        anchor + float(expiry.ttl_seconds)
        if expiry is not None and expiry.ttl_seconds is not None
        else now
    )
    temporal_scope = expiry.temporal_scope if expiry is not None else "momentary"
    decay_policy = expiry.decay_policy if expiry is not None else "fast_decay"
    cursor = await db.execute(
        """
        UPDATE tom_trait_assertions
        SET status = 'archived', validation_state = ?, confidence_score = ?,
            evidence_events = ?, first_inferred_at = ?, last_validated_at = ?,
            temporal_scope = ?, decay_policy = ?, decay_anchor_at = ?,
            expires_at = ?, memory_subdomain = ?,
            authority_ref = CASE
                WHEN COALESCE(authority_ref, '') = '' THEN 'forget:event'
                ELSE authority_ref
            END,
            updated_at = ?
        WHERE assertion_id = ?
          AND (
                status IN ('tentative', 'corroborated', 'stable')
                OR (status = 'archived' AND authority_ref = 'forget:event')
          )
        """,
        (
            validation_state,
            confidence,
            json.dumps(evidence_event_ids, ensure_ascii=False),
            first_inferred_at,
            last_validated_at,
            temporal_scope,
            decay_policy,
            anchor,
            expires_at,
            classify_memory_subdomain(temporal_scope, decay_policy),
            now,
            assertion_id,
        ),
    )
    return max(int(cursor.rowcount or 0), 0)


async def _apply_recomputed_assertion_lifecycle(
    db: aiosqlite.Connection,
    *,
    assertion_id: str,
    row: Mapping[str, Any],
    stats: ClaimOccurrenceStats,
    decision: AssertionPromotionDecision,
    now: float,
) -> int:
    expiry = decision.expiry
    anchor = stats.last_observed_at
    if decision.horizon is PromotionHorizon.RECENT:
        assert anchor is not None
        if str(row.get("trait_family") or "").strip().casefold() == "goal_profile":
            expires_at = await _remaining_goal_target_end(
                db,
                claim_ids=stats.claim_ids,
            )
            if expires_at is None:
                expires_at = anchor + float(expiry.ttl_seconds or 0.0)
        else:
            expires_at = anchor + float(expiry.ttl_seconds or 0.0)
    else:
        expires_at = None
        anchor = stats.last_observed_at or _safe_float(row.get("decay_anchor_at")) or now
    evidence_event_ids = _bounded_claim_evidence_ids(stats)
    first_inferred_at, last_validated_at, validation_state, confidence = (
        _recomputed_assertion_evidence(row=row, stats=stats)
    )
    if expires_at is not None and expires_at <= now:
        next_status = "expired"
    elif str(row.get("status") or "") == "archived":
        next_status = validation_state
    else:
        next_status = validation_state
    persisted_validation_state = "expired" if next_status == "expired" else validation_state
    memory_subdomain = classify_memory_subdomain(
        expiry.temporal_scope,
        expiry.decay_policy,
    )
    cursor = await db.execute(
        """
        UPDATE tom_trait_assertions
        SET status = ?, validation_state = ?, confidence_score = ?, evidence_events = ?,
            first_inferred_at = ?, last_validated_at = ?,
            temporal_scope = ?, decay_policy = ?, decay_anchor_at = ?,
            expires_at = ?, memory_subdomain = ?,
            authority_ref = CASE
                WHEN authority_ref = 'forget:event' THEN NULL
                ELSE authority_ref
            END,
            updated_at = ?
        WHERE assertion_id = ?
        """,
        (
            next_status,
            persisted_validation_state,
            confidence,
            json.dumps(evidence_event_ids, ensure_ascii=False),
            first_inferred_at,
            last_validated_at,
            expiry.temporal_scope,
            expiry.decay_policy,
            anchor,
            expires_at,
            memory_subdomain,
            now,
            assertion_id,
        ),
    )
    return max(int(cursor.rowcount or 0), 0)


def _bounded_claim_evidence_ids(stats: ClaimOccurrenceStats | None) -> list[str]:
    if stats is None:
        return []
    return sorted(set(stats.supporting_event_ids))[-max_evidence_event_ids() :]


def _recomputed_assertion_evidence(
    *,
    row: Mapping[str, Any],
    stats: ClaimOccurrenceStats | None,
) -> tuple[float, float, str, float]:
    evidence_event_ids = _bounded_claim_evidence_ids(stats)
    first_inferred_at = (stats.first_observed_at if stats is not None else None) or _safe_float(
        row.get("first_inferred_at")
    )
    last_validated_at = (stats.last_observed_at if stats is not None else None) or _safe_float(
        row.get("last_validated_at")
    )
    current_confidence = _safe_float(row.get("confidence_score"))
    confidence = min(current_confidence, compute_confidence(len(evidence_event_ids)))
    validation_state, confidence, _ = derive_validation_state(
        current_state=str(row.get("validation_state") or "tentative"),
        current_confidence=confidence,
        evidence_count=len(evidence_event_ids),
        time_span_hours=max(0.0, (last_validated_at - first_inferred_at) / 3600.0),
        trait_name=str(row.get("trait_name") or ""),
        user_feedback=None,
    )
    return first_inferred_at, last_validated_at, validation_state, confidence


async def _remaining_goal_target_end(
    db: aiosqlite.Connection,
    *,
    claim_ids: tuple[str, ...],
) -> float | None:
    if not claim_ids:
        return None
    claim_json = json.dumps(claim_ids, ensure_ascii=False, separators=(",", ":"))
    async with db.execute(
        """
        SELECT MIN(target_to)
        FROM l2_grounded_claims
        WHERE availability = 'active'
          AND target_to IS NOT NULL
          AND claim_id IN (
              SELECT CAST(value AS TEXT) FROM json_each(?)
          )
        """,
        (claim_json,),
    ) as cursor:
        row = await cursor.fetchone()
    return float(row[0]) if row is not None and row[0] is not None else None


async def _goal_claims_remain_projectable(
    db: aiosqlite.Connection,
    *,
    stats: ClaimOccurrenceStats,
    now: float,
) -> bool:
    """Reapply the goal-specific safety gates to the surviving Claim ledger."""

    supporting_event_ids = set(stats.supporting_event_ids)
    if not supporting_event_ids or not supporting_event_ids.issubset(set(stats.trusted_event_ids)):
        return False
    claim_json = json.dumps(stats.claim_ids, ensure_ascii=False, separators=(",", ":"))
    async with db.execute(
        """
        SELECT claims.claim_id, claims.target_to, claims.raw_time_frame_json,
               evidence.event_id, evidence.evidence_mode
        FROM l2_grounded_claims AS claims
        JOIN l2_claim_evidence AS evidence
          ON evidence.claim_id = claims.claim_id
         AND evidence.link_role = 'supporting'
        WHERE claims.availability = 'active'
          AND claims.claim_id IN (
              SELECT CAST(value AS TEXT) FROM json_each(?)
          )
        ORDER BY claims.claim_id, evidence.event_id
        """,
        (claim_json,),
    ) as cursor:
        rows = await cursor.fetchall()
    if not rows:
        return False
    if any(str(row[4] or "").strip().casefold() != "direct" for row in rows):
        return False

    target_ends: list[float] = []
    frames_by_claim: dict[str, Mapping[str, Any]] = {}
    for row in rows:
        claim_id = str(row[0])
        if row[1] is not None:
            target_ends.append(float(row[1]))
        frames_by_claim.setdefault(claim_id, _safe_json_mapping(row[2]))
    for frame in frames_by_claim.values():
        raw_expression = str(frame.get("raw") or "").strip()
        resolution = str(frame.get("resolution") or "unscheduled").strip().casefold()
        if raw_expression and resolution not in {"exact", "calendar_anchor"}:
            return False
    if target_ends:
        return min(target_ends) > now
    last_observed_at = stats.last_observed_at
    return bool(last_observed_at is not None and last_observed_at + 30 * 24 * 60 * 60 > now)


def _safe_json_mapping(value: Any) -> Mapping[str, Any]:
    try:
        decoded = json.loads(value) if isinstance(value, str) else value
    except (TypeError, json.JSONDecodeError):
        return {}
    return decoded if isinstance(decoded, dict) else {}


async def _has_independent_assertion_authority(
    db: aiosqlite.Connection,
    *,
    authority_ref: Any,
    user_feedback: Any,
    forgotten_event_ids: Iterable[str] = (),
) -> bool:
    authority = str(authority_ref or "").strip()
    if authority.startswith("correction:"):
        correction_id = authority.removeprefix("correction:").strip()
        if not correction_id:
            return False
        async with db.execute(
            """
            SELECT state, source_event_id
            FROM memory_corrections
            WHERE correction_id = ?
            """,
            (correction_id,),
        ) as cursor:
            row = await cursor.fetchone()
        if row is None or str(row[0] or "").strip().casefold() != "active":
            return False
        forgotten = {str(event_id).strip() for event_id in forgotten_event_ids}
        source_event_id = str(row[1] or "").strip()
        return not source_event_id or source_event_id not in forgotten
    if str(user_feedback or "").strip().casefold() == "confirmed":
        return True
    if not authority or authority.startswith("forget:"):
        return False
    return True


def _assertion_status_is_terminal(value: Any) -> bool:
    return str(value or "").strip().casefold() in {
        "contradicted",
        "expired",
        "invalidated",
        "shadow",
        "superseded",
        "user_rejected",
    }


def _safe_float(value: Any) -> float:
    try:
        return float(value or 0.0)
    except (TypeError, ValueError):
        return 0.0


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
    async with db.execute(
        """
        SELECT DISTINCT batch_attempt_key
        FROM l2_projection_jobs
        WHERE event_id IN (SELECT CAST(value AS TEXT) FROM json_each(?))
          AND status IN ('queued', 'running')
          AND batch_attempt_key IS NOT NULL
        """,
        (event_json,),
    ) as cursor:
        invalidated_attempt_keys = [str(row[0]) for row in await cursor.fetchall()]
    if invalidated_attempt_keys:
        placeholders = ", ".join("?" for _ in invalidated_attempt_keys)
        await db.execute(
            f"""
            UPDATE l2_projection_jobs
            SET status = 'pending',
                attempt_count = CASE
                    WHEN replay_requested = 1 THEN 0
                    ELSE MAX(attempt_count - 1, 0)
                END,
                lease_token = NULL, lease_heartbeat_at = NULL,
                batch_attempt_key = NULL, batch_descriptor_json = NULL,
                batch_bound_at = NULL,
                next_retry_at = NULL, terminal_at = NULL,
                replay_requested = 0,
                claimed_by = NULL, claimed_at = NULL,
                started_at = NULL, completed_at = NULL,
                last_error = 'projection_batch_invalidated_by_source_forgetting',
                updated_at = ?
            WHERE batch_attempt_key IN ({placeholders})
              AND event_id NOT IN (
                  SELECT CAST(value AS TEXT) FROM json_each(?)
              )
              AND status IN ('queued', 'running')
            """,
            (now, *invalidated_attempt_keys, event_json),
        )
    cursor = await db.execute(
        """
        UPDATE l2_projection_jobs
        SET status = 'completed', lease_token = NULL, lease_heartbeat_at = NULL,
            batch_attempt_key = NULL, batch_descriptor_json = NULL,
            batch_bound_at = NULL,
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


async def _release_reimportable_projection_jobs(
    db: aiosqlite.Connection,
    *,
    event_ids: tuple[str, ...],
    now: float,
) -> int:
    """Remove selected queue identities after invalidating shared active batches."""

    if not event_ids:
        return 0
    await _complete_forgotten_projection_jobs(
        db,
        event_ids=event_ids,
        now=now,
    )
    cursor = await db.execute(
        """
        DELETE FROM l2_projection_jobs
        WHERE event_id IN (SELECT CAST(value AS TEXT) FROM json_each(?))
        """,
        (_event_json(event_ids),),
    )
    return max(int(cursor.rowcount or 0), 0)


async def _release_reimportable_event_forget_rules(
    db: aiosqlite.Connection,
    *,
    event_ids: tuple[str, ...],
) -> None:
    """Release only event-scoped L2 replay rules attached to selected evidence."""

    if not event_ids:
        return
    event_json = _event_json(event_ids)
    async with db.execute(
        """
        SELECT DISTINCT rules.rule_id
        FROM memory_forget_claim_rules AS rules
        JOIN memory_forget_evidence_events AS evidence
          ON evidence.rule_id = rules.rule_id
        WHERE rules.forget_kind = 'event'
          AND evidence.event_id IN (
              SELECT CAST(value AS TEXT) FROM json_each(?)
          )
        ORDER BY rules.rule_id
        """,
        (event_json,),
    ) as cursor:
        rule_ids = tuple(str(row[0]) for row in await cursor.fetchall())
    if not rule_ids:
        return
    rule_json = json.dumps(rule_ids, ensure_ascii=False, separators=(",", ":"))
    await db.execute(
        """
        DELETE FROM memory_forget_evidence_events
        WHERE rule_id IN (SELECT CAST(value AS TEXT) FROM json_each(?))
          AND event_id IN (SELECT CAST(value AS TEXT) FROM json_each(?))
        """,
        (rule_json, event_json),
    )
    await db.execute(
        """
        DELETE FROM memory_correction_forget_barriers
        WHERE rule_id IN (SELECT CAST(value AS TEXT) FROM json_each(?))
          AND NOT EXISTS (
              SELECT 1
              FROM memory_forget_evidence_events AS evidence
              WHERE evidence.rule_id = memory_correction_forget_barriers.rule_id
          )
        """,
        (rule_json,),
    )
    await db.execute(
        """
        DELETE FROM memory_forget_claim_rules
        WHERE forget_kind = 'event'
          AND rule_id IN (SELECT CAST(value AS TEXT) FROM json_each(?))
          AND NOT EXISTS (
              SELECT 1
              FROM memory_forget_evidence_events AS evidence
              WHERE evidence.rule_id = memory_forget_claim_rules.rule_id
          )
        """,
        (rule_json,),
    )


async def _reimportable_source_event_ids(
    db: aiosqlite.Connection,
    *,
    event_ids: tuple[str, ...],
) -> tuple[str, ...]:
    """Exclude events already protected by any permanent replay tombstone."""

    if not event_ids:
        return ()
    async with db.execute(
        """
        SELECT CAST(candidate.value AS TEXT)
        FROM json_each(?) AS candidate
        WHERE NOT EXISTS (
            SELECT 1
            FROM memory_source_event_tombstones AS tombstones
            WHERE tombstones.event_id = CAST(candidate.value AS TEXT)
        )
        ORDER BY CAST(candidate.value AS TEXT)
        """,
        (_event_json(event_ids),),
    ) as cursor:
        return tuple(str(row[0]) for row in await cursor.fetchall())


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
        linked = {record.event_id for record in evidence_by_claim.get(claim.claim_fingerprint, ())}
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
        (event_id for linked in linked_by_claim.values() for event_id in linked),
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
                   user_feedback, authority_ref, valid_from, valid_to
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
            segment_start=float(row[9]) if row[9] is not None else float(row[1]),
            segment_end=float(row[10]) if row[10] is not None else math.inf,
        )
        retained_records = [record for record in records if record.event_id not in forgotten]
        retained_ids = _bounded_retained_ids(
            [record.event_id for record in retained_records]
            + [event_id for event_id in raw_ids if event_id not in forgotten]
        )
        if malformed or not retained_ids:
            if await _has_independent_assertion_authority(
                db,
                authority_ref=row[8],
                user_feedback=row[7],
                forgotten_event_ids=forgotten,
            ):
                cursor = await db.execute(
                    """
                    UPDATE tom_trait_assertions
                    SET evidence_events = '[]', updated_at = ?
                    WHERE assertion_id = ?
                    """,
                    (now, claim.record_id),
                )
            else:
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
