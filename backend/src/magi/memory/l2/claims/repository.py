"""SQLite repository for grounded Claims, evidence links, and outcomes."""

from __future__ import annotations

import hashlib
import json
import time
import uuid
from collections.abc import Iterable
from typing import Any, Protocol, cast

import aiosqlite

from ....core.sqlite import sqlite_connection_async
from ..batch_models import L2ProjectionLease, derive_projection_attempt_key
from ..projection.fencing import (
    assert_current_projection_attempt,
    assert_projection_attempt_key,
    normalize_projection_leases,
)
from ..projection.models import TerminalClaimFailureContext
from .identity import canonical_json, derive_claim_identity_key, projection_outcome_id
from .models import (
    ClaimEntityRefInput,
    ClaimEvidenceInput,
    GroundedClaimInput,
    ProjectionOutcomeInput,
)
from .outcomes import ClaimTargetOutcomeContext, append_claim_target_outcomes_on_connection


class _GroundedClaimHostProtocol(Protocol):
    db_path: str

    async def initialize(self) -> None: ...


def _required_text(value: Any, *, field_name: str) -> str:
    text = str(value or "").strip()
    if not text:
        raise ValueError(f"{field_name} must not be blank")
    return text


def _optional_text(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _json_or_none(value: Any) -> str | None:
    return None if value is None else canonical_json(value)


def _record(row: aiosqlite.Row | None) -> dict[str, Any] | None:
    if row is None:
        return None
    result = dict(row)
    for column in (
        "object_value_json",
        "raw_time_frame_json",
        "evidence_locator_json",
        "details_json",
    ):
        if column not in result or result[column] is None:
            continue
        try:
            result[column.removesuffix("_json")] = json.loads(result[column])
        except (TypeError, ValueError):
            result[column.removesuffix("_json")] = None
    return result


class L2GroundedClaimStoreMixin:
    """Persist normalized Claim semantics separately from projection lifecycle."""

    async def upsert_grounded_claim(
        self,
        *,
        claim: GroundedClaimInput,
        evidence: Iterable[ClaimEvidenceInput],
        projection_leases: Iterable[L2ProjectionLease],
    ) -> dict[str, Any]:
        """Create one Claim idempotently and attach normalized evidence occurrences."""

        host = cast(_GroundedClaimHostProtocol, self)
        await host.initialize()
        identity_key = _required_text(claim.identity_key, field_name="identity_key")
        claim_id = f"clm_{uuid.uuid4().hex}"
        evidence_items = tuple(evidence)
        lease_items = normalize_projection_leases(projection_leases, required=True)
        assert_projection_attempt_key(claim.origin_attempt_key, lease_items)
        if not evidence_items:
            raise ValueError("grounded Claim must have at least one evidence link")
        supporting_event_ids = [
            _required_text(item.event_id, field_name="event_id")
            for item in evidence_items
            if item.link_role == "supporting"
        ]
        antecedent_event_ids = [
            _required_text(item.event_id, field_name="event_id")
            for item in evidence_items
            if item.link_role == "antecedent"
        ]
        if not supporting_event_ids:
            raise ValueError("grounded Claim must have supporting evidence")
        lease_event_ids = {lease.event_id for lease in lease_items}
        if not set(supporting_event_ids).issubset(lease_event_ids):
            raise ValueError("supporting_event_ids must be a subset of projection lease event IDs")
        evidence_modes = {
            _required_text(item.evidence_mode, field_name="evidence_mode")
            for item in evidence_items
        }
        if len(evidence_modes) != 1:
            raise ValueError("all Claim event links must use one evidence mode")
        if any(
            int(item.evidence_rule_version) != int(claim.evidence_rule_version)
            for item in evidence_items
        ):
            raise ValueError("Claim and event links must use the same evidence rule version")
        expected_identity = derive_claim_identity_key(
            extractor_contract_version=claim.extractor_contract_version,
            evidence_rule_version=claim.evidence_rule_version,
            user_id=claim.user_id,
            subject_ref=claim.subject_ref,
            subject_type=claim.subject_type,
            canonical_predicate=claim.canonical_predicate,
            fact_kind=claim.fact_kind,
            object_type=claim.object_type,
            polarity=claim.polarity,
            specificity=claim.specificity,
            temporal_cue=claim.temporal_cue,
            fact_valid_from=claim.fact_valid_from,
            fact_valid_to=claim.fact_valid_to,
            target_from=claim.target_from,
            target_to=claim.target_to,
            raw_time_frame=claim.raw_time_frame,
            evidence_mode=next(iter(evidence_modes)),
            object_surface=claim.object_surface,
            object_value=claim.object_value,
            supporting_event_ids=supporting_event_ids,
            antecedent_event_ids=antecedent_event_ids,
        )
        if identity_key != expected_identity:
            raise ValueError("identity_key does not match the grounded Claim contract")
        now = time.time()

        async with sqlite_connection_async(host.db_path) as db:
            db.row_factory = aiosqlite.Row
            await db.execute("BEGIN IMMEDIATE")
            try:
                event_ids = sorted(
                    {
                        _required_text(item.event_id, field_name="event_id")
                        for item in evidence_items
                    }
                )
                event_json = canonical_json(event_ids)
                async with db.execute(
                    """
                    SELECT event_id FROM memory_source_event_tombstones
                    WHERE event_id IN (SELECT CAST(value AS TEXT) FROM json_each(?))
                    ORDER BY event_id
                    """,
                    (event_json,),
                ) as cursor:
                    blocked_event_ids = [str(row[0]) for row in await cursor.fetchall()]
                if blocked_event_ids:
                    await db.rollback()
                    return {
                        "claim_id": None,
                        "created": False,
                        "inserted_evidence_count": 0,
                        "replay_blocked": True,
                        "blocked_event_ids": blocked_event_ids,
                    }
                await assert_current_projection_attempt(db, lease_items)
                async with db.execute(
                    "SELECT * FROM l2_grounded_claims WHERE identity_key = ?",
                    (identity_key,),
                ) as cursor:
                    existing = await cursor.fetchone()
                created = existing is None
                if created:
                    insert_cursor = await db.execute(
                        """
                        INSERT INTO l2_grounded_claims(
                            claim_id, identity_key, extractor_contract_version,
                            evidence_rule_version, origin_attempt_key, profile_id,
                            user_id, subject_ref, subject_type,
                            canonical_predicate, fact_kind, object_type, polarity,
                            specificity, confidence, object_value_json, object_surface,
                            temporal_cue,
                            fact_valid_from, fact_valid_to, target_from, target_to,
                            raw_time_frame_json, availability, created_at, updated_at
                        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?,
                                  ?, ?, ?, ?, ?, 'active', ?, ?)
                        """,
                        (
                            claim_id,
                            identity_key,
                            int(claim.extractor_contract_version),
                            int(claim.evidence_rule_version),
                            _required_text(
                                claim.origin_attempt_key,
                                field_name="origin_attempt_key",
                            ),
                            _optional_text(claim.profile_id),
                            _optional_text(claim.user_id),
                            _required_text(claim.subject_ref, field_name="subject_ref"),
                            _required_text(claim.subject_type, field_name="subject_type"),
                            _required_text(
                                claim.canonical_predicate,
                                field_name="canonical_predicate",
                            ),
                            _required_text(claim.fact_kind, field_name="fact_kind"),
                            _required_text(claim.object_type, field_name="object_type"),
                            _required_text(claim.polarity, field_name="polarity"),
                            _required_text(claim.specificity, field_name="specificity"),
                            max(0.0, min(1.0, float(claim.confidence))),
                            _json_or_none(claim.object_value),
                            _optional_text(claim.object_surface),
                            _required_text(claim.temporal_cue, field_name="temporal_cue"),
                            claim.fact_valid_from,
                            claim.fact_valid_to,
                            claim.target_from,
                            claim.target_to,
                            _json_or_none(claim.raw_time_frame),
                            now,
                            now,
                        ),
                    )
                    created = bool(insert_cursor.rowcount)
                    availability = "active"
                else:
                    assert existing is not None
                    claim_id = str(existing["claim_id"])
                    availability = str(existing["availability"])

                inserted_evidence = 0
                if availability == "active":
                    for item in evidence_items:
                        cursor = await db.execute(
                            """
                            INSERT OR IGNORE INTO l2_claim_evidence(
                                claim_id, event_id, link_role, required_for_grounding,
                                event_time, timestamp_confidence,
                                timestamp_quality, timestamp_anchor_source,
                                evidence_rule_version,
                                evidence_mode, source_type, source_domain, author_type,
                                evidence_class,
                                evidence_locator_json, created_at
                            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                            """,
                            (
                                claim_id,
                                _required_text(item.event_id, field_name="event_id"),
                                _required_text(item.link_role, field_name="link_role"),
                                int(bool(item.required_for_grounding)),
                                item.event_time,
                                _required_text(
                                    item.timestamp_confidence,
                                    field_name="timestamp_confidence",
                                ),
                                _required_text(
                                    item.timestamp_quality,
                                    field_name="timestamp_quality",
                                ),
                                _optional_text(item.timestamp_anchor_source),
                                int(item.evidence_rule_version),
                                _required_text(item.evidence_mode, field_name="evidence_mode"),
                                _optional_text(item.source_type),
                                _optional_text(item.source_domain),
                                _optional_text(item.author_type),
                                _optional_text(item.evidence_class),
                                _json_or_none(item.evidence_locator),
                                now,
                            ),
                        )
                        inserted_evidence += max(int(cursor.rowcount or 0), 0)
                await db.commit()
            except Exception:
                await db.rollback()
                raise

        stored = await self.get_grounded_claim(claim_id, include_forgotten=True)
        if stored is None:  # pragma: no cover - transaction invariant
            raise RuntimeError("grounded Claim disappeared after commit")
        stored["created"] = created
        stored["inserted_evidence_count"] = inserted_evidence
        stored["replay_blocked"] = availability == "forgotten"
        return stored

    async def get_grounded_claim(
        self,
        claim_id: str,
        *,
        include_forgotten: bool = False,
    ) -> dict[str, Any] | None:
        """Return a Claim and its active evidence links."""

        host = cast(_GroundedClaimHostProtocol, self)
        await host.initialize()
        availability_clause = "" if include_forgotten else "AND availability = 'active'"
        async with sqlite_connection_async(host.db_path) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute(
                f"""
                SELECT * FROM l2_grounded_claims
                WHERE claim_id = ? {availability_clause}
                """,
                (_required_text(claim_id, field_name="claim_id"),),
            ) as cursor:
                row = await cursor.fetchone()
            result = _record(row)
            if result is None:
                return None
            async with db.execute(
                """
                SELECT * FROM l2_claim_evidence
                WHERE claim_id = ? ORDER BY event_time, event_id
                """,
                (claim_id,),
            ) as cursor:
                result["evidence"] = [
                    cast(dict[str, Any], _record(item)) for item in await cursor.fetchall()
                ]
            return result

    async def upsert_claim_entity_ref(
        self,
        ref: ClaimEntityRefInput,
        *,
        projection_leases: Iterable[L2ProjectionLease],
    ) -> dict[str, Any] | None:
        """Append one versioned resolver result for an active Claim."""

        host = cast(_GroundedClaimHostProtocol, self)
        await host.initialize()
        lease_items = normalize_projection_leases(projection_leases, required=True)
        claim_id = _required_text(ref.claim_id, field_name="claim_id")
        ref_role = _required_text(ref.ref_role, field_name="ref_role")
        entity_id = _required_text(ref.entity_id, field_name="entity_id")
        resolution_version = max(1, int(ref.resolution_version))
        async with sqlite_connection_async(host.db_path) as db:
            db.row_factory = aiosqlite.Row
            await db.execute("BEGIN IMMEDIATE")
            try:
                await assert_current_projection_attempt(db, lease_items)
                await db.execute(
                    """
                INSERT OR IGNORE INTO l2_claim_entity_refs(
                    claim_id, ref_role, entity_id, resolution_version, created_at
                )
                SELECT ?, ?, ?, ?, ?
                WHERE EXISTS (
                    SELECT 1 FROM l2_grounded_claims
                    WHERE claim_id = ? AND availability = 'active'
                )
                    """,
                    (
                        claim_id,
                        ref_role,
                        entity_id,
                        resolution_version,
                        time.time(),
                        claim_id,
                    ),
                )
                async with db.execute(
                    """
                    SELECT * FROM l2_claim_entity_refs
                    WHERE claim_id = ? AND ref_role = ? AND resolution_version = ?
                    """,
                    (claim_id, ref_role, resolution_version),
                ) as cursor:
                    stored_row = await cursor.fetchone()
                if stored_row is not None and str(stored_row["entity_id"]) != entity_id:
                    raise RuntimeError(
                        "Claim entity resolution version maps to conflicting entity IDs"
                    )
                await db.commit()
            except Exception:
                await db.rollback()
                raise
        return dict(stored_row) if stored_row is not None else None

    async def list_claim_entity_refs(self, *, claim_id: str) -> list[dict[str, Any]]:
        """List active resolver enrichments for one Claim."""

        host = cast(_GroundedClaimHostProtocol, self)
        await host.initialize()
        async with sqlite_connection_async(host.db_path) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute(
                """
                SELECT * FROM l2_claim_entity_refs
                WHERE claim_id = ? AND invalidated_at IS NULL
                ORDER BY ref_role, resolution_version
                """,
                (_required_text(claim_id, field_name="claim_id"),),
            ) as cursor:
                return [dict(row) for row in await cursor.fetchall()]

    async def list_grounded_claims(
        self,
        *,
        user_id: str | None = None,
        availability: str = "active",
        limit: int = 200,
    ) -> list[dict[str, Any]]:
        """List Claim semantic bodies for governance and deterministic recomputation."""

        host = cast(_GroundedClaimHostProtocol, self)
        await host.initialize()
        clauses = ["availability = ?"]
        params: list[Any] = [_required_text(availability, field_name="availability")]
        if user_id is not None:
            clauses.append("user_id = ?")
            params.append(_required_text(user_id, field_name="user_id"))
        params.append(max(1, min(int(limit), 5000)))
        async with sqlite_connection_async(host.db_path) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute(
                f"""
                SELECT * FROM l2_grounded_claims
                WHERE {' AND '.join(clauses)}
                ORDER BY created_at, claim_id
                LIMIT ?
                """,
                tuple(params),
            ) as cursor:
                return [cast(dict[str, Any], _record(row)) for row in await cursor.fetchall()]

    async def append_claim_projection_outcome(
        self,
        outcome: ProjectionOutcomeInput,
        *,
        projection_leases: Iterable[L2ProjectionLease],
    ) -> dict[str, Any] | None:
        """Append one idempotent target result for an active Claim."""

        lease_items = normalize_projection_leases(projection_leases, required=True)
        return await self._append_claim_projection_outcome(
            outcome,
            projection_leases=lease_items,
        )

    async def append_reprojected_claim_route_outcome(
        self,
        outcome: ProjectionOutcomeInput,
    ) -> dict[str, Any] | None:
        """Append one trusted, idempotent route-maintenance result."""

        if str(outcome.target_kind or "").strip() != "route":
            raise ValueError("reprojected Claim outcome must target route")
        if not str(outcome.attempt_key or "").startswith("route-reproject:"):
            raise ValueError("reprojected Claim outcome has an invalid attempt key")
        return await self._append_claim_projection_outcome(
            outcome,
            projection_leases=(),
        )

    async def _append_terminal_claim_projection_failure_outcomes_on_connection(
        self,
        db: aiosqlite.Connection,
        *,
        context: TerminalClaimFailureContext,
        terminal_leases: tuple[L2ProjectionLease, ...],
    ) -> int:
        """Append Claim outcomes inside the owning projection queue transaction."""

        lease_items = normalize_projection_leases(terminal_leases, required=True)
        normalized_error_type = _required_text(context.error_type, field_name="error_type")
        normalized_reason_code = _required_text(context.reason_code, field_name="reason_code")
        explicit_attempt_key = _optional_text(context.attempt_key)
        explicit_target_id = _optional_text(context.target_id)
        if (explicit_attempt_key is None) != (explicit_target_id is None):
            raise ValueError("terminal Claim failure attempt_key and target_id must be paired")
        if explicit_attempt_key is not None:
            assert_projection_attempt_key(explicit_attempt_key, lease_items)

        groups = (
            [
                (
                    explicit_attempt_key,
                    explicit_target_id,
                    sorted(lease.event_id for lease in lease_items),
                )
            ]
            if explicit_attempt_key is not None and explicit_target_id is not None
            else [
                (
                    derive_projection_attempt_key((lease,)),
                    f"projection_event:{lease.event_id}",
                    [lease.event_id],
                )
                for lease in lease_items
            ]
        )
        inserted = 0
        now = time.time()
        for attempt_key, target_id, terminal_event_ids in groups:
            placeholders = ", ".join("?" for _ in terminal_event_ids)
            async with db.execute(
                f"""
                SELECT DISTINCT claims.claim_id
                FROM l2_grounded_claims AS claims
                JOIN l2_claim_evidence AS evidence
                  ON evidence.claim_id = claims.claim_id
                WHERE claims.availability = 'active'
                  AND evidence.link_role = 'supporting'
                  AND evidence.event_id IN ({placeholders})
                ORDER BY claims.claim_id
                """,
                tuple(terminal_event_ids),
            ) as cursor:
                claim_ids = [str(row["claim_id"]) for row in await cursor.fetchall()]

            if claim_ids:
                outcome_ids = await append_claim_target_outcomes_on_connection(
                    db,
                    context=ClaimTargetOutcomeContext(
                        claim_ids=tuple(claim_ids),
                        attempt_key=attempt_key,
                        route_contract_version=0,
                    ),
                    target_kind="pipeline",
                    target_id=target_id,
                    target_slot_key=None,
                    outcome="failed",
                    reason_code=normalized_reason_code,
                    details={
                        "error_type": normalized_error_type,
                        "terminal_event_ids": sorted(terminal_event_ids),
                    },
                    created_at=now,
                )
                inserted += len(outcome_ids)
        return inserted

    async def _append_claim_projection_outcome(
        self,
        outcome: ProjectionOutcomeInput,
        *,
        projection_leases: tuple[L2ProjectionLease, ...],
    ) -> dict[str, Any] | None:
        """Write one outcome, optionally fenced by a live extraction attempt."""

        host = cast(_GroundedClaimHostProtocol, self)
        await host.initialize()
        claim_id = _required_text(outcome.claim_id, field_name="claim_id")
        attempt_key = _required_text(outcome.attempt_key, field_name="attempt_key")
        if projection_leases:
            assert_projection_attempt_key(attempt_key, projection_leases)
        target_kind = _required_text(outcome.target_kind, field_name="target_kind")
        target_id = str(outcome.target_id or "").strip()
        target_slot_key = _optional_text(outcome.target_slot_key)
        route_contract_version = max(0, int(outcome.route_contract_version))
        normalized_outcome = _required_text(outcome.outcome, field_name="outcome")
        reason_code = _optional_text(outcome.reason_code)
        details_json = _json_or_none(outcome.details)
        outcome_id = projection_outcome_id(
            claim_id=claim_id,
            attempt_key=attempt_key,
            target_kind=target_kind,
            target_id=target_id,
        )
        async with sqlite_connection_async(host.db_path) as db:
            db.row_factory = aiosqlite.Row
            await db.execute("BEGIN IMMEDIATE")
            try:
                if projection_leases:
                    await assert_current_projection_attempt(db, projection_leases)
                async with db.execute(
                    """
                    SELECT 1 FROM l2_grounded_claims
                    WHERE claim_id = ? AND availability = 'active'
                    """,
                    (claim_id,),
                ) as claim_cursor:
                    if await claim_cursor.fetchone() is None:
                        await db.commit()
                        return None
                cursor = await db.execute(
                    """
                INSERT OR IGNORE INTO l2_claim_projection_outcomes(
                    outcome_id, claim_id, attempt_key, target_kind, target_id,
                    target_slot_key, route_contract_version, outcome,
                    reason_code, details_json, created_at
                )
                SELECT ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?
                WHERE EXISTS (
                    SELECT 1 FROM l2_grounded_claims
                    WHERE claim_id = ? AND availability = 'active'
                )
                    """,
                    (
                        outcome_id,
                        claim_id,
                        attempt_key,
                        target_kind,
                        target_id,
                        target_slot_key,
                        route_contract_version,
                        normalized_outcome,
                        reason_code,
                        details_json,
                        time.time(),
                        claim_id,
                    ),
                )
                if not cursor.rowcount:
                    async with db.execute(
                        "SELECT * FROM l2_claim_projection_outcomes WHERE outcome_id = ?",
                        (outcome_id,),
                    ) as existing_cursor:
                        stored = _record(await existing_cursor.fetchone())
                    expected = {
                        "claim_id": claim_id,
                        "attempt_key": attempt_key,
                        "target_kind": target_kind,
                        "target_id": target_id,
                        "target_slot_key": target_slot_key,
                        "route_contract_version": route_contract_version,
                        "outcome": normalized_outcome,
                        "reason_code": reason_code,
                        "details_json": details_json,
                    }
                    if stored is None or any(
                        stored.get(field) != value for field, value in expected.items()
                    ):
                        raise RuntimeError("claim_projection_outcome_conflict")
                else:
                    async with db.execute(
                        "SELECT * FROM l2_claim_projection_outcomes WHERE outcome_id = ?",
                        (outcome_id,),
                    ) as stored_cursor:
                        stored = _record(await stored_cursor.fetchone())
                await db.commit()
                return stored
            except Exception:
                await db.rollback()
                raise

    async def list_claim_projection_outcomes(
        self,
        *,
        claim_id: str,
    ) -> list[dict[str, Any]]:
        """List immutable outcomes for one Claim in creation order."""

        host = cast(_GroundedClaimHostProtocol, self)
        await host.initialize()
        async with sqlite_connection_async(host.db_path) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute(
                """
                SELECT * FROM l2_claim_projection_outcomes
                WHERE claim_id = ? ORDER BY created_at, outcome_id
                """,
                (_required_text(claim_id, field_name="claim_id"),),
            ) as cursor:
                return [cast(dict[str, Any], _record(row)) for row in await cursor.fetchall()]


async def redact_grounded_claims_for_source_events(
    db: aiosqlite.Connection,
    *,
    event_ids: Iterable[str],
    reason: str,
    now: float,
) -> dict[str, int]:
    """Detach forgotten evidence and irreversibly redact unsupported Claims."""

    normalized_ids = sorted(
        {str(event_id).strip() for event_id in event_ids if str(event_id).strip()}
    )
    if not normalized_ids:
        return _empty_claim_redaction_counts()
    event_json = canonical_json(normalized_ids)
    async with db.execute(
        """
        SELECT claim_id FROM l2_claim_evidence
        WHERE event_id IN (SELECT CAST(value AS TEXT) FROM json_each(?))
        """,
        (event_json,),
    ) as cursor:
        affected_rows = await cursor.fetchall()
    affected_claim_ids = sorted({str(row[0]) for row in affected_rows})
    deleted = await db.execute(
        """
        DELETE FROM l2_claim_evidence
        WHERE event_id IN (SELECT CAST(value AS TEXT) FROM json_each(?))
        """,
        (event_json,),
    )

    counts = await redact_grounded_claims_by_ids(
        db,
        claim_ids=affected_claim_ids,
        reason=reason,
        invalidated_reason="source_event_forgotten",
        now=now,
    )
    counts["l2_claim_evidence"] += max(int(deleted.rowcount or 0), 0)
    return counts


async def redact_grounded_claims_by_ids(
    db: aiosqlite.Connection,
    *,
    claim_ids: Iterable[str],
    reason: str,
    invalidated_reason: str,
    now: float,
) -> dict[str, int]:
    """Irreversibly redact active Claims while retaining opaque tombstones."""

    normalized_claim_ids = sorted(
        {str(claim_id).strip() for claim_id in claim_ids if str(claim_id).strip()}
    )
    if not normalized_claim_ids:
        return _empty_claim_redaction_counts()

    redacted = 0
    scrubbed_outcomes = 0
    deleted_entity_refs = 0
    deleted_evidence = 0
    normalized_reason = _required_text(reason, field_name="reason")
    normalized_invalidated_reason = _required_text(
        invalidated_reason,
        field_name="invalidated_reason",
    )
    for claim_id in normalized_claim_ids:
        async with db.execute(
            """
            SELECT identity_key FROM l2_grounded_claims
            WHERE claim_id = ? AND availability = 'active'
            """,
            (claim_id,),
        ) as cursor:
            claim_row = await cursor.fetchone()
        if claim_row is None:
            continue
        tombstone_material = f"{claim_row[0]}:{normalized_reason}"
        tombstone_key = hashlib.sha256(tombstone_material.encode("utf-8")).hexdigest()
        remaining_evidence = await db.execute(
            "DELETE FROM l2_claim_evidence WHERE claim_id = ?",
            (claim_id,),
        )
        deleted_evidence += max(int(remaining_evidence.rowcount or 0), 0)
        entity_refs = await db.execute(
            "DELETE FROM l2_claim_entity_refs WHERE claim_id = ?",
            (claim_id,),
        )
        deleted_entity_refs += max(int(entity_refs.rowcount or 0), 0)
        async with db.execute(
            """
            SELECT outcome_id, target_id, target_slot_key
            FROM l2_claim_projection_outcomes
            WHERE claim_id = ?
            """,
            (claim_id,),
        ) as cursor:
            outcome_rows = await cursor.fetchall()
        for outcome_row in outcome_rows:
            outcome_id = str(outcome_row[0])
            redacted_target = (
                "redacted:"
                + hashlib.sha256(
                    f"{outcome_id}:{outcome_row[1] or ''}".encode("utf-8")
                ).hexdigest()[:24]
            )
            redacted_slot = None
            if outcome_row[2] is not None:
                redacted_slot = (
                    "redacted:"
                    + hashlib.sha256(f"{outcome_id}:{outcome_row[2]}".encode("utf-8")).hexdigest()[
                        :24
                    ]
                )
            cursor = await db.execute(
                """
                UPDATE l2_claim_projection_outcomes
                SET target_id = ?, target_slot_key = ?, details_json = NULL,
                    invalidated_at = COALESCE(invalidated_at, ?),
                    invalidated_reason = COALESCE(invalidated_reason, ?)
                WHERE outcome_id = ?
                """,
                (
                    redacted_target,
                    redacted_slot,
                    now,
                    normalized_invalidated_reason,
                    outcome_id,
                ),
            )
            scrubbed_outcomes += max(int(cursor.rowcount or 0), 0)
        cursor = await db.execute(
            """
            UPDATE l2_grounded_claims
            SET origin_attempt_key = NULL, profile_id = NULL, user_id = NULL,
                subject_ref = NULL, subject_type = NULL,
                canonical_predicate = NULL, fact_kind = NULL,
                object_type = NULL, polarity = NULL, specificity = NULL,
                confidence = NULL, object_value_json = NULL, object_surface = NULL,
                temporal_cue = NULL,
                fact_valid_from = NULL, fact_valid_to = NULL,
                target_from = NULL, target_to = NULL,
                raw_time_frame_json = NULL, availability = 'forgotten',
                forgotten_at = ?, forget_tombstone_key = ?, updated_at = ?
            WHERE claim_id = ? AND availability = 'active'
            """,
            (now, tombstone_key, now, claim_id),
        )
        redacted += max(int(cursor.rowcount or 0), 0)
    return {
        "l2_claim_evidence": deleted_evidence,
        "l2_claim_entity_refs": deleted_entity_refs,
        "l2_grounded_claims": redacted,
        "l2_claim_projection_outcomes": scrubbed_outcomes,
    }


def _empty_claim_redaction_counts() -> dict[str, int]:
    return {
        "l2_claim_evidence": 0,
        "l2_claim_entity_refs": 0,
        "l2_grounded_claims": 0,
        "l2_claim_projection_outcomes": 0,
    }


__all__ = [
    "L2GroundedClaimStoreMixin",
    "redact_grounded_claims_by_ids",
    "redact_grounded_claims_for_source_events",
]
