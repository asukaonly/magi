"""Reduce governed Claim observations to one factual timeline per assertion slot."""
from __future__ import annotations

from dataclasses import dataclass, field
import hashlib
import json
import uuid
from typing import Any

import aiosqlite

from ..claims.outcomes import ClaimTargetOutcomeContext, append_claim_target_outcomes_on_connection
from ..claims.route_selection import CURRENT_ENTITY_REF_VERSIONS_CTE, LATEST_ROUTE_ORDER_SQL
from ..projection.governance import active_projection_event_predicate


@dataclass(frozen=True)
class Observation:
    at: float
    event_id: str
    claim_id: str
    value: str


@dataclass
class Segment:
    value: str
    start: float
    observations: list[Observation] = field(default_factory=list)
    end: float | None = None
    exclusion_at: float | None = None
    successor_at: float | None = None


def reduce_observations(
    observations: list[Observation], exclusions: list[tuple[float, str]],
) -> list[Segment]:
    """Use occurrence time only; unresolved simultaneous conflicts leave a gap."""
    points: dict[float, tuple[list[Observation], set[str]]] = {}
    for item in observations:
        points.setdefault(item.at, ([], set()))[0].append(item)
    for at, value in exclusions:
        points.setdefault(at, ([], set()))[1].add(value)
    segments: list[Segment] = []
    active: Segment | None = None
    for at in sorted(points):
        positive, negative = points[at]
        values = {item.value for item in positive}
        if len(values) > 1 or values.intersection(negative):
            if active is not None:
                active.end = at
            active = None
            continue
        if active is not None and active.value in negative:
            active.end = active.exclusion_at = at
            active = None
        if not positive:
            continue
        value = positive[0].value
        if active is not None and active.value == value:
            active.observations.extend(positive)
            continue
        if active is not None:
            active.end = at
        if segments and segments[-1].exclusion_at is not None:
            segments[-1].successor_at = at
        active = Segment(value=value, start=at, observations=list(positive))
        segments.append(active)
    return segments


async def rebuild_observation_timeline(
    db: aiosqlite.Connection,
    candidate: dict[str, Any],
    context: ClaimTargetOutcomeContext | None,
    *,
    trait_name: str,
    now: float,
) -> Any | None:
    """Rebuild a Claim-backed unbounded slot inside its admitted write transaction.

    Explicit calendar intervals and non-Claim writes retain their own contracts.
    Corrections have already passed the caller's policy; manual authority and
    confirmed assertions are never reinterpreted by this reducer.
    """
    if context is None or candidate.get("valid_to") is not None:
        return None
    from .write import (
        _AssertionWriteResult, _canonicalize_trait_value, _merged_assertion_state,
        _assertion_insert_values, _INSERT_SQL, build_assertion_merge_context,
    )
    async with db.execute(
        """SELECT * FROM tom_trait_assertions WHERE slot_key = ? AND scope_key = ?
        AND status NOT IN ('expired', 'invalidated', 'user_rejected', 'shadow', 'deprecated')
        AND (status != 'archived' OR EXISTS (
            SELECT 1 FROM l2_claim_projection_outcomes receipt WHERE receipt.target_id = tom_trait_assertions.assertion_id
              AND receipt.target_kind = 'assertion' AND receipt.invalidated_reason = 'assertion_timeline_reassigned'
        ))""",
        (candidate["slot_key"], candidate["scope_key"]),
    ) as cursor:
        existing = [dict(row) for row in await cursor.fetchall()]
    authorities = [row for row in existing if row["authority_ref"] or row["user_feedback"] == "confirmed"]
    if authorities:
        return None
    # Calendar-bounded Claims are separate interval facts. Never rewrite them
    # merely because an unbounded observation shares their semantic slot.
    async with db.execute(
        """SELECT DISTINCT receipt.target_id FROM l2_claim_projection_outcomes receipt
        JOIN l2_grounded_claims claim ON claim.claim_id = receipt.claim_id
        WHERE receipt.target_kind = 'assertion' AND receipt.outcome = 'projected'
          AND (receipt.invalidated_at IS NULL OR receipt.invalidated_reason = 'assertion_timeline_reassigned')
          AND claim.availability = 'active'
          AND claim.fact_valid_from IS NULL AND claim.fact_valid_to IS NULL
          AND receipt.target_id IN (SELECT value FROM json_each(?))""",
        (json.dumps([row["assertion_id"] for row in existing]),),
    ) as cursor:
        observation_ids = {row[0] for row in await cursor.fetchall()}
    if any(row["valid_to"] is None and row["assertion_id"] not in observation_ids for row in existing):
        return None
    existing = [row for row in existing if row["assertion_id"] in observation_ids]
    if candidate["trait_name"] == "preference.affinity":
        from ..claims.preference_exclusions import _has_pending_preference_routes
        if await _has_pending_preference_routes(db, candidate["entity_id"]):
            return None
    from ..corrections.policy import CorrectionPolicyAction, CorrectionPolicyEvaluator
    evaluator = CorrectionPolicyEvaluator()
    candidate_policy = await evaluator.evaluate_assertion(db, candidate)
    if candidate_policy.action not in {CorrectionPolicyAction.ACCEPT_ACTIVE, CorrectionPolicyAction.ACCEPT_HISTORICAL}:
        return None
    for row in existing:
        if row["expires_at"] is not None and float(row["expires_at"]) <= now:
            return None
        if row["valid_to"] is not None and row["status"] != "superseded":
            return None
        policy = await evaluator.evaluate_assertion(db, row)
        if policy.action not in {CorrectionPolicyAction.ACCEPT_ACTIVE, CorrectionPolicyAction.ACCEPT_HISTORICAL}:
            return None
    observations, target_keys = await _observations(db, existing, candidate, context)
    if not observations or not set(context.claim_ids).issubset({item.claim_id for item in observations}):
        return None
    from ..claims.preference_exclusions import _eligible_negatives
    negatives = await _eligible_negatives(db, subject_id=candidate["entity_id"], now=now)
    exclusions = [
        (float(row["effective_at"]), "like" if row["canonical_predicate"] == "LIKES" else "dislike")
        for row in negatives if row["semantic_target_key"] in target_keys
    ] if candidate["scope_key"] == "global" else []
    segments = reduce_observations(observations, exclusions)
    incoming = set(context.claim_ids)
    # Retire current positions before assigning the rebuilt nonoverlapping runs.
    # Readers cannot observe this intermediate state inside the fenced transaction.
    existing_ids = [row["assertion_id"] for row in existing]
    if existing_ids:
        await db.execute(
            "UPDATE tom_trait_assertions SET status = 'superseded' WHERE assertion_id IN (SELECT value FROM json_each(?))",
            (json.dumps(existing_ids),),
        )
    used: set[str] = set()
    assigned: list[tuple[Segment, str]] = []
    for segment in segments:
        event_ids = sorted({item.event_id for item in segment.observations})
        matching = [row for row in existing if row["assertion_id"] not in used
                    and _canonicalize_trait_value(row["trait_value"]) == segment.value
                    and set(json.loads(row["evidence_events"] or "[]")).intersection(event_ids)]
        # Preserve the identifier most strongly associated with this segment.
        match = max(matching, key=lambda row: (
            len(set(json.loads(row["evidence_events"] or "[]")).intersection(event_ids)),
            row["valid_from"] == segment.start,
            row["assertion_id"],
        )) if matching else None
        template = match or next((row for row in existing if _canonicalize_trait_value(row["trait_value"]) == segment.value), None)
        material = dict(candidate if segment.value == candidate["trait_value"] else template or candidate)
        material.update(trait_value=segment.value, evidence_events=event_ids,
                        valid_from=segment.start, valid_to=segment.end,
                        first_inferred_at=segment.start,
                        last_validated_at=max(item.at for item in segment.observations))
        from ..corrections.fingerprints import assertion_claim_fingerprint
        material["claim_fingerprint"] = assertion_claim_fingerprint(
            slot_key_value=candidate["slot_key"], trait_value=segment.value,
            scope_key_value=candidate["scope_key"],
        )
        from ..claim_text import load_claim_texts, persisted_claim_to_phase1
        from ..factual_rendering import render_grounded_fact
        source_claim = max(segment.observations, key=lambda item: (item.at, item.claim_id)).claim_id
        async with db.execute("SELECT * FROM l2_grounded_claims WHERE claim_id = ?", (source_claim,)) as cursor:
            claim_row = await cursor.fetchone()
        texts = await load_claim_texts(db, [source_claim])
        if claim_row is not None and source_claim in texts:
            material["natural_summary"] = render_grounded_fact(
                persisted_claim_to_phase1(dict(claim_row)), resolved_text=texts[source_claim],
            )
        async with db.execute(
            "SELECT MIN(confidence) FROM l2_grounded_claims WHERE claim_id IN (SELECT value FROM json_each(?)) AND availability = 'active'",
            (json.dumps(sorted({item.claim_id for item in segment.observations})),),
        ) as cursor:
            confidence_row = await cursor.fetchone()
        material["confidence_score"] = float(confidence_row[0] or 0.0)
        segment_context = build_assertion_merge_context(
            {**material, "evidence_events": json.dumps(event_ids), "user_feedback": None}, material,
        )
        state, confidence = _merged_assertion_state(
            merge_context=segment_context, trait_name=trait_name,
            evidence_count=await _independent_count(db, event_ids),
            current_state=str((match or {}).get("validation_state") or "tentative"),
            current_confidence=material["confidence_score"], user_feedback=None,
        )
        if match is None:
            identity = f"assert_{uuid.uuid4().hex}"
            await db.execute(_INSERT_SQL, _assertion_insert_values(
                assertion_id=identity, candidate=material, trait_name=trait_name,
                trait_value=segment.value, confidence=confidence, evidence_events=event_ids,
                validation_state=state, first_inferred_at=segment.start,
                last_validated_at=material["last_validated_at"],
                status="superseded" if segment.end is not None else state, now=now,
            ))
        else:
            identity = str(match["assertion_id"])
            await db.execute(
                """UPDATE tom_trait_assertions SET evidence_events = ?, valid_from = ?, valid_to = ?,
                first_inferred_at = ?, last_validated_at = ?, validation_state = ?, confidence_score = ?,
                status = ?, natural_summary = ?, updated_at = ?, superseded_by = NULL, superseded_at = NULL
                WHERE assertion_id = ?""",
                (json.dumps(event_ids), segment.start, segment.end, segment.start,
                 material["last_validated_at"], state, confidence,
                 "superseded" if segment.end is not None else state,
                 material["natural_summary"], now, identity),
            )
        used.add(identity)
        assigned.append((segment, identity))
    unused = set(existing_ids) - used
    if unused:
        await db.execute(
            "UPDATE tom_trait_assertions SET status = 'archived', updated_at = ? WHERE assertion_id IN (SELECT value FROM json_each(?))",
            (now, json.dumps(sorted(unused))),
        )
    await _bind_receipts(db, assigned, existing_ids, context, candidate["slot_key"], now)
    await _bind_exclusions(db, assigned, existing_ids, candidate["entity_id"], now)
    for index, (segment, identity) in enumerate(assigned):
        await db.execute(
            "UPDATE tom_trait_assertions SET version_root_id = ?, previous_version_id = ?, superseded_by = ? WHERE assertion_id = ?",
            (assigned[0][1], assigned[index-1][1] if index else None,
             assigned[index+1][1] if index+1 < len(assigned) else None, identity),
        )
    assigned_claims = {item.claim_id for segment, _ in assigned for item in segment.observations}
    deferred_claims = {item.claim_id for item in observations} - assigned_claims
    deferred_target = f"timeline-conflict:{candidate['slot_key']}"
    for claim_id in sorted(deferred_claims):
        await append_claim_target_outcomes_on_connection(
            db, context=ClaimTargetOutcomeContext.for_claim(
                claim_id=claim_id, route_contract_version=context.route_contract_version,
                attempt_key=(context.attempt_key if claim_id in incoming
                    else f"assertion-timeline-conflict:v{context.route_contract_version}:{claim_id}"),
            ), target_kind="assertion", target_id=deferred_target,
            target_slot_key=candidate["slot_key"], outcome="skipped",
            reason_code="ambiguous_observation_time", created_at=now,
        )
    target = next((identity for segment, identity in reversed(assigned)
                   if incoming.intersection(item.claim_id for item in segment.observations)), None)
    return _AssertionWriteResult(
        assertion_id=target or deferred_target, claim_outcomes_written=True,
        persisted=target is not None, should_notify=target is not None,
        reason_code=None if target is not None else "ambiguous_observation_time",
    )


async def _observations(db, existing, candidate, context):
    from ..claims.reprojection_write import _derive_candidate_route, _load_route_candidate
    ids = [row["assertion_id"] for row in existing]
    async with db.execute(
        f"""WITH {CURRENT_ENTITY_REF_VERSIONS_CTE}, latest_routes AS (
            SELECT outcomes.*, ROW_NUMBER() OVER (PARTITION BY outcomes.claim_id ORDER BY {LATEST_ROUTE_ORDER_SQL}) AS rn
            FROM l2_claim_projection_outcomes outcomes
            LEFT JOIN current_entity_ref_versions route_refs ON route_refs.claim_id = outcomes.claim_id
            WHERE outcomes.target_kind = 'route' AND outcomes.invalidated_at IS NULL
        )
        SELECT DISTINCT c.claim_id, e.event_id, e.event_time
        FROM l2_grounded_claims c JOIN latest_routes r ON r.claim_id = c.claim_id AND r.rn = 1
          AND r.outcome = 'routed' AND r.target_slot_key = ?
          AND r.route_contract_version = {context.route_contract_version}
          AND EXISTS (SELECT 1 FROM json_each(r.details_json, '$.projection_targets') WHERE value = 'assertion')
        JOIN l2_claim_evidence e ON e.claim_id = c.claim_id AND e.link_role = 'supporting'
        WHERE c.availability = 'active' AND c.polarity = 'positive'
          AND c.fact_valid_from IS NULL AND c.fact_valid_to IS NULL
          AND e.timestamp_quality IN ('exact', 'calendar_anchor') AND e.event_time > 0
          AND {active_projection_event_predicate('e.event_id')}
          AND (c.claim_id IN (SELECT value FROM json_each(?)) OR EXISTS (
              SELECT 1 FROM l2_claim_projection_outcomes receipt WHERE receipt.claim_id = c.claim_id
                AND receipt.target_kind = 'assertion' AND receipt.invalidated_at IS NULL
                AND ((receipt.outcome = 'projected' AND receipt.target_id IN (SELECT value FROM json_each(?)))
                     OR (receipt.outcome = 'skipped' AND receipt.reason_code = 'ambiguous_observation_time'
                         AND receipt.target_slot_key = r.target_slot_key))
          ))""", (candidate["slot_key"], json.dumps(context.claim_ids), json.dumps(ids)),
    ) as cursor:
        rows = await cursor.fetchall()
    decisions = {}
    for identity in {str(row[0]) for row in rows}:
        claim = await _load_route_candidate(db, identity)
        if claim is not None:
            decisions[identity] = _derive_candidate_route(claim)
    observations = []
    targets = set()
    for claim_id, event_id, at in rows:
        decision = decisions.get(claim_id)
        if decision is None or decision.slot_key != candidate["slot_key"] or decision.scope_key != candidate["scope_key"]:
            continue
        # This is the materializer's value contract, derived from Claim truth.
        value = decision.object_surface if decision.family == "goal_profile" else decision.canonical_value
        if value is None:
            continue
        from .write import _canonicalize_trait_value
        value = _canonicalize_trait_value(str(value).strip())
        if claim_id in context.claim_ids and value != candidate["trait_value"]:
            continue
        observations.append(Observation(float(at), str(event_id), str(claim_id), value))
        targets.add(decision.semantic_target_key)
    return observations, targets


async def _bind_receipts(db, assigned, existing_ids, context, slot_key, now):
    desired = {(item.claim_id, identity) for segment, identity in assigned for item in segment.observations}
    async with db.execute(
        """SELECT outcome_id, claim_id, target_id FROM l2_claim_projection_outcomes
        WHERE target_kind = 'assertion' AND outcome = 'projected' AND invalidated_at IS NULL
          AND target_id IN (SELECT value FROM json_each(?))""", (json.dumps(existing_ids),),
    ) as cursor:
        receipts = await cursor.fetchall()
    for outcome_id, claim_id, target_id in receipts:
        if (claim_id, target_id) not in desired:
            await db.execute(
                "UPDATE l2_claim_projection_outcomes SET invalidated_at = ?, invalidated_reason = 'assertion_timeline_reassigned' WHERE outcome_id = ?",
                (now, outcome_id),
            )
    fingerprint = hashlib.sha256(json.dumps(sorted(desired)).encode()).hexdigest()[:24]
    active_pairs = {(claim_id, target_id) for _, claim_id, target_id in receipts}
    for claim_id, identity in sorted(desired):
        if (claim_id, identity) in active_pairs and (
            claim_id not in context.claim_ids or context.attempt_key.startswith("assertion-timeline-reconcile:")
        ):
            continue
        receipt_context = ClaimTargetOutcomeContext.for_claim(
            claim_id=claim_id,
            attempt_key=context.attempt_key if claim_id in context.claim_ids else f"assertion-timeline:v{context.route_contract_version}:{fingerprint}:{claim_id}",
            route_contract_version=context.route_contract_version,
        )
        receipt_context = await _receipt_revision(db, receipt_context, identity)
        async with db.execute(
            f"""WITH {CURRENT_ENTITY_REF_VERSIONS_CTE}
            SELECT outcomes.* FROM l2_claim_projection_outcomes outcomes
            LEFT JOIN current_entity_ref_versions route_refs ON route_refs.claim_id = outcomes.claim_id
            WHERE outcomes.claim_id = ? AND outcomes.target_kind = 'route' AND outcomes.invalidated_at IS NULL
            ORDER BY {LATEST_ROUTE_ORDER_SQL} LIMIT 1""", (claim_id,),
        ) as cursor:
            source_route = await cursor.fetchone()
        if source_route is None:
            raise RuntimeError("Timeline target has no active source route")
        await append_claim_target_outcomes_on_connection(
            db, context=receipt_context, target_kind="route", target_id=source_route["target_id"],
            target_slot_key=source_route["target_slot_key"], outcome=source_route["outcome"],
            reason_code=source_route["reason_code"], details=json.loads(source_route["details_json"]), created_at=now,
        )
        await append_claim_target_outcomes_on_connection(
            db, context=receipt_context, target_kind="assertion", target_id=identity,
            target_slot_key=slot_key, outcome="projected", created_at=now,
        )


async def _bind_exclusions(db, assigned, existing_ids, subject_id, now):
    await db.execute(
        "DELETE FROM l2_preference_exclusion_effects WHERE target_kind = 'assertion' AND target_id IN (SELECT value FROM json_each(?))",
        (json.dumps(existing_ids),),
    )
    for segment, identity in assigned:
        if segment.exclusion_at is not None:
            async with db.execute("SELECT validation_state FROM tom_trait_assertions WHERE assertion_id = ?", (identity,)) as cursor:
                row = await cursor.fetchone()
            await db.execute(
                "INSERT OR REPLACE INTO l2_preference_exclusion_effects VALUES ('assertion', ?, ?, ?, ?, ?, ?)",
                (identity, subject_id, "superseded" if segment.successor_at is not None else row[0],
                 segment.successor_at, segment.exclusion_at, now),
            )


async def _independent_count(db: aiosqlite.Connection, event_ids: list[str]) -> int:
    async with db.execute(
        """SELECT COUNT(DISTINCT COALESCE(
            json_extract(evidence_locator_json, '$.independent_evidence_key'), event_id))
        FROM l2_claim_evidence WHERE link_role = 'supporting'
          AND event_id IN (SELECT value FROM json_each(?))""", (json.dumps(event_ids),),
    ) as cursor:
        row = await cursor.fetchone()
    return int(row[0])


async def rebuild_preference_observation_timelines(
    db: aiosqlite.Connection, *, subject_id: str, now: float,
) -> bool:
    """Reapply the same reducer when negatives, forgetting, or route replay change."""
    from ..semantic_routing import ROUTE_CONTRACT_VERSION
    from ..claims.preference_exclusions import _eligible_negatives
    negatives = await _eligible_negatives(db, subject_id=subject_id, now=now)
    target_keys = sorted({row["semantic_target_key"] for row in negatives})
    async with db.execute(
        """SELECT assertion.slot_key FROM l2_preference_exclusion_effects effect
        JOIN tom_trait_assertions assertion ON assertion.assertion_id = effect.target_id
        WHERE effect.target_kind = 'assertion' AND effect.subject_id = ?
        UNION SELECT receipt.target_slot_key FROM l2_claim_projection_outcomes receipt
        JOIN l2_grounded_claims claim ON claim.claim_id = receipt.claim_id
          AND claim.availability = 'active' AND claim.subject_ref = ?
        WHERE receipt.invalidated_at IS NULL AND (
            (receipt.target_kind = 'assertion' AND receipt.outcome = 'skipped'
             AND receipt.reason_code = 'ambiguous_observation_time')
            OR (receipt.target_kind = 'route'
                AND json_extract(receipt.details_json, '$.semantic_target_key') IN (SELECT value FROM json_each(?)))
        )""", (subject_id, subject_id, json.dumps(target_keys)),
    ) as cursor:
        affected_slots = sorted({row[0] for row in await cursor.fetchall() if row[0]})
    # Source forgetting can remove the first observation after every negative
    # has gone. Its remaining active receipts still carry a repair obligation.
    async with db.execute(
        f"""SELECT assertion.slot_key FROM tom_trait_assertions assertion
        JOIN l2_claim_projection_outcomes receipt ON receipt.target_id = assertion.assertion_id
          AND receipt.target_kind = 'assertion' AND receipt.outcome = 'projected' AND receipt.invalidated_at IS NULL
        JOIN l2_grounded_claims claim ON claim.claim_id = receipt.claim_id
          AND claim.availability = 'active' AND claim.fact_valid_from IS NULL AND claim.fact_valid_to IS NULL
        JOIN l2_claim_evidence evidence ON evidence.claim_id = claim.claim_id AND evidence.link_role = 'supporting'
          AND evidence.timestamp_quality IN ('exact', 'calendar_anchor') AND evidence.event_time > 0
          AND {active_projection_event_predicate('evidence.event_id')}
        WHERE assertion.entity_id = ? AND assertion.trait_name = 'preference.affinity'
          AND assertion.status NOT IN ('archived', 'expired', 'invalidated', 'user_rejected', 'shadow', 'deprecated')
        GROUP BY assertion.assertion_id
        HAVING assertion.valid_from != MIN(evidence.event_time)""", (subject_id,),
    ) as cursor:
        affected_slots = sorted(set(affected_slots).union(row[0] for row in await cursor.fetchall()))
    if not affected_slots:
        return False
    async with db.execute(
        """SELECT DISTINCT assertions.* FROM tom_trait_assertions assertions
        JOIN l2_claim_projection_outcomes receipt ON receipt.target_id = assertions.assertion_id
          AND receipt.target_kind = 'assertion' AND receipt.outcome = 'projected'
          AND (receipt.invalidated_at IS NULL OR receipt.invalidated_reason = 'assertion_timeline_reassigned')
        JOIN l2_grounded_claims claim ON claim.claim_id = receipt.claim_id
          AND claim.availability = 'active' AND claim.polarity = 'positive'
          AND claim.fact_valid_from IS NULL AND claim.fact_valid_to IS NULL
        WHERE assertions.entity_id = ? AND assertions.trait_name = 'preference.affinity'
          AND assertions.slot_key IN (SELECT value FROM json_each(?))
          AND assertions.status NOT IN ('expired', 'invalidated', 'user_rejected', 'shadow', 'deprecated')
          AND (assertions.status != 'archived' OR receipt.invalidated_reason = 'assertion_timeline_reassigned')""",
        (subject_id, json.dumps(affected_slots)),
    ) as cursor:
        rows = [dict(row) for row in await cursor.fetchall()]
    slots: dict[tuple[str, str], dict[str, Any]] = {}
    for row in rows:
        slots.setdefault((row["slot_key"], row["scope_key"]), row)
    changed = False
    for row in slots.values():
        async with db.execute(
            """SELECT receipt.claim_id FROM l2_claim_projection_outcomes receipt
            JOIN l2_grounded_claims claim ON claim.claim_id = receipt.claim_id
              AND claim.availability = 'active' AND claim.fact_valid_from IS NULL AND claim.fact_valid_to IS NULL
            WHERE receipt.target_kind = 'assertion' AND receipt.target_id = ?
              AND receipt.outcome = 'projected'
              AND (receipt.invalidated_at IS NULL OR receipt.invalidated_reason = 'assertion_timeline_reassigned')
            ORDER BY receipt.claim_id LIMIT 1""", (row["assertion_id"],),
        ) as cursor:
            anchor = await cursor.fetchone()
        if anchor is None:
            continue
        candidate = {**row, "valid_to": None, "evidence_events": json.loads(row["evidence_events"] or "[]")}
        context = ClaimTargetOutcomeContext.for_claim(
            claim_id=anchor[0], attempt_key=f"assertion-timeline-reconcile:v{ROUTE_CONTRACT_VERSION}:{row['slot_key']}:{anchor[0]}",
            route_contract_version=ROUTE_CONTRACT_VERSION,
        )
        result = await rebuild_observation_timeline(db, candidate, context, trait_name=row["trait_name"], now=now)
        changed = changed or result is not None
    return changed


async def _receipt_revision(
    db: aiosqlite.Connection, context: ClaimTargetOutcomeContext, target_id: str,
) -> ClaimTargetOutcomeContext:
    base = context.attempt_key
    async with db.execute(
        """SELECT attempt_key, invalidated_at FROM l2_claim_projection_outcomes
        WHERE claim_id = ? AND target_kind = 'assertion' AND target_id = ?
          AND (attempt_key = ? OR substr(attempt_key, 1, ?) = ?)
        ORDER BY created_at DESC, outcome_id DESC""",
        (context.claim_ids[0], target_id, base, len(base + ':revision:'), base + ':revision:'),
    ) as cursor:
        previous = await cursor.fetchall()
    active = next((row[0] for row in previous if row[1] is None), None)
    attempt = active or (f"{base}:revision:{len(previous)}" if previous else base)
    return ClaimTargetOutcomeContext(
        claim_ids=context.claim_ids, attempt_key=attempt, route_contract_version=context.route_contract_version,
    )
