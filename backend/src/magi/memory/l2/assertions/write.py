"""ToM assertion upsert helpers for the L2 cognition store."""

from __future__ import annotations

import ast
import json
import time
import uuid
from dataclasses import dataclass
from typing import Any, Dict, Protocol, cast

import aiosqlite

from ....core.logger import get_logger
from ....core.sqlite import sqlite_connection_async
from ...context_scope.models import normalize_context_scope
from ..corrections.fingerprints import (
    assertion_claim_fingerprint,
    assertion_slot_key,
    canonical_scope_json,
    scope_key,
)
from ..corrections.evidence_ledger import append_claim_evidence_event_ids
from ..corrections.forget_governance import (
    append_forget_evidence_event_ids,
    filter_candidate_evidence_by_forget_rules,
)
from ..corrections.models import CorrectionTargetKind
from ..corrections.policy import (
    CORRECTION_GOVERNED_EVIDENCE_ACTIONS,
    CorrectionPolicyAction,
    CorrectionPolicyDecision,
    CorrectionPolicyEvaluator,
)
from ..corrections.repository import MemoryCorrectionRepository
from ..storage.utils import (
    max_evidence_event_ids,
    normalize_event_ids,
    normalize_store_entity_ref,
    normalize_store_entity_type,
)
from .settings import (
    CONTRADICTED_CONFIDENCE_CEILING,
    assertion_float_setting,
)
from .source_tier import source_tier
from .state_machine import compute_confidence, derive_validation_state

logger = get_logger(__name__)


def _canonicalize_trait_value(value: Any) -> str:
    """Normalize structured assertion values into a stable serialized form."""
    if value is None:
        return ""
    if isinstance(value, (list, dict)):
        return json.dumps(value, ensure_ascii=False, sort_keys=True)

    text = str(value)
    if not text.strip():
        return ""

    parsed: Any | None = None
    try:
        parsed = json.loads(text)
    except (TypeError, ValueError):
        try:
            parsed = ast.literal_eval(text)
        except (SyntaxError, ValueError):
            parsed = None

    if isinstance(parsed, (list, dict)):
        return json.dumps(parsed, ensure_ascii=False, sort_keys=True)
    return text


class _AssertionHostProtocol(Protocol):
    db_path: str

    async def initialize(self) -> None: ...

    async def resolve_evidence_timestamps(
        self,
        event_ids: list[str],
    ) -> Dict[str, float]: ...

    def _derive_trait_family(self, trait_name: str) -> str: ...

    def _optional_text(self, value: Any) -> str | None: ...

    def _coerce_expires_at(
        self,
        value: Any,
        *,
        trait_family: str,
        trait_name: str,
        target_entity_id: str,
        anchor_at: float,
    ) -> float | None: ...

    async def refresh_entity_snapshot(
        self,
        *,
        entity_id: str,
        entity_type: str | None = None,
    ) -> Dict[str, Any] | None: ...

    async def _notify_assertion_changed(self, assertion: Dict[str, Any]) -> None: ...


_INSERT_SQL = """
INSERT INTO tom_trait_assertions(
    assertion_id, entity_id, entity_type, trait_family, trait_name, trait_value,
    confidence_score, evidence_events, volatility_index, source_domain,
    inference_depth, validation_state, first_inferred_at, last_validated_at,
    target_entity_id, target_entity_type, target_scope, temporal_scope,
    decay_policy, decay_anchor_at, context_ref_id, expires_at,
    status, memory_subdomain, natural_summary,
    created_at, updated_at, slot_key, claim_fingerprint, authority_ref,
    version_root_id, previous_version_id, valid_from, valid_to, scope_key, scope_json
) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
"""

_ACTIVE_ASSERTION_SQL = """
SELECT * FROM tom_trait_assertions
WHERE slot_key = ? AND scope_key = ?
  AND status NOT IN ('superseded', 'archived', 'expired', 'user_rejected', 'shadow')
ORDER BY updated_at DESC
LIMIT 1
"""

_UPDATE_VOLATILE_ASSERTION_SQL = """
UPDATE tom_trait_assertions
SET trait_value = ?, confidence_score = ?, evidence_events = ?,
    slot_key = ?, claim_fingerprint = ?, scope_key = ?, scope_json = ?,
    validation_state = ?, status = ?, last_validated_at = ?,
    first_inferred_at = ?,
    target_entity_type = ?, target_scope = ?, temporal_scope = ?,
    decay_policy = ?, decay_anchor_at = ?, context_ref_id = ?,
    expires_at = ?, natural_summary = ?, updated_at = ?
WHERE assertion_id = ?
"""

_SUPERSEDE_ASSERTION_SQL = """
UPDATE tom_trait_assertions
SET status = 'superseded', superseded_by = ?, superseded_at = ?, updated_at = ?,
    valid_to = ?
WHERE assertion_id = ?
"""

_UPDATE_SAME_VALUE_ASSERTION_SQL = """
UPDATE tom_trait_assertions
SET trait_value = ?, confidence_score = ?, evidence_events = ?,
    slot_key = ?, claim_fingerprint = ?, scope_key = ?, scope_json = ?,
    validation_state = ?, status = ?,
    last_validated_at = ?, first_inferred_at = ?,
    target_entity_type = ?, target_scope = ?, temporal_scope = ?,
    decay_policy = ?, decay_anchor_at = ?, context_ref_id = ?,
    expires_at = ?, natural_summary = ?, updated_at = ?
WHERE assertion_id = ?
"""


def _normalized_assertion_identity(
    candidate: Dict[str, Any],
    host: _AssertionHostProtocol,
) -> Dict[str, Any]:
    trait_name = str(candidate.get("trait_name", "")).strip()
    normalized_entity_type = normalize_store_entity_type(candidate.get("entity_type")) or "other"
    return {
        "entity_type": normalized_entity_type,
        "trait_family": str(candidate.get("trait_family", "")).strip().lower()
        or host._derive_trait_family(trait_name),
    }


def _normalized_assertion_target(candidate: Dict[str, Any]) -> Dict[str, Any]:
    target_entity_type = normalize_store_entity_type(candidate.get("target_entity_type")) or ""
    return {
        "target_entity_type": target_entity_type,
        "target_entity_id": (
            normalize_store_entity_ref(candidate.get("target_entity_id"), target_entity_type) or ""
        ),
        "target_scope": str(candidate.get("target_scope", "global")).strip() or "global",
        "temporal_scope": str(candidate.get("temporal_scope", "session")).strip() or "session",
    }


def _normalized_assertion_context(
    candidate: Dict[str, Any],
    host: _AssertionHostProtocol,
    normalized_candidate: Dict[str, Any],
    *,
    now: float,
) -> Dict[str, Any]:
    decay_anchor_at = float(
        candidate.get("decay_anchor_at", candidate.get("last_validated_at", now)) or now
    )
    trait_name = str(candidate.get("trait_name", "")).strip()
    return {
        "decay_policy": host._optional_text(candidate.get("decay_policy")),
        "decay_anchor_at": decay_anchor_at,
        "context_ref_id": host._optional_text(candidate.get("context_ref_id")) or "",
        "expires_at": host._coerce_expires_at(
            candidate.get("expires_at"),
            trait_family=normalized_candidate["trait_family"],
            trait_name=trait_name,
            target_entity_id=normalized_candidate["target_entity_id"],
            anchor_at=decay_anchor_at,
        ),
        "memory_subdomain": str(candidate.get("memory_subdomain", "")).strip() or "",
        "natural_summary": str(candidate.get("natural_summary", "") or "").strip()[:500],
    }


def _normalized_assertion_governance(candidate: Dict[str, Any]) -> Dict[str, Any]:
    raw_scope = candidate.get("scope")
    scope = normalize_context_scope(raw_scope if raw_scope is not None else {})
    slot_key_value = assertion_slot_key(
        entity_type=str(candidate["entity_type"]),
        entity_id=str(candidate["entity_id"]),
        trait_name=str(candidate.get("trait_name") or ""),
        target_entity_id=str(candidate["target_entity_id"]),
    )
    scope_key_value = scope_key(scope)
    return {
        "slot_key": slot_key_value,
        "claim_fingerprint": assertion_claim_fingerprint(
            slot_key_value=slot_key_value,
            trait_value=candidate.get("trait_value"),
            scope_key_value=scope_key_value,
        ),
        "scope": scope,
        "scope_key": scope_key_value,
        "scope_json": canonical_scope_json(scope),
    }


def normalize_assertion_candidate(
    candidate: Dict[str, Any],
    host: _AssertionHostProtocol,
    *,
    now: float,
) -> Dict[str, Any]:
    """Prepare an assertion candidate for durable L2 upsert decisions."""
    normalized_candidate = dict(candidate)
    normalized_candidate.update(_normalized_assertion_identity(candidate, host))
    normalized_candidate.update(_normalized_assertion_target(candidate))
    normalized_candidate.update(
        _normalized_assertion_context(candidate, host, normalized_candidate, now=now)
    )
    normalized_candidate["evidence_events"] = normalize_event_ids(
        candidate.get("evidence_events") or []
    )
    normalized_candidate["trait_value"] = _canonicalize_trait_value(candidate.get("trait_value"))
    normalized_candidate.update(_normalized_assertion_governance(normalized_candidate))
    return normalized_candidate


@dataclass(slots=True)
class AssertionMergeContext:
    """Computed comparison between an existing assertion and a new candidate."""

    existing_value: str
    next_value: str
    existing_temporal_scope: str
    merged_evidence: list[str]
    first_inferred_at: float
    last_validated_at: float
    candidate_tier: str
    existing_tier: str

    @property
    def value_changed(self) -> bool:
        return self.existing_value != self.next_value

    @property
    def inferred_conflicts_with_authoritative(self) -> bool:
        return (
            self.candidate_tier == "inferred"
            and self.existing_tier == "authoritative"
            and self.value_changed
        )

    @property
    def should_update_volatile_in_place(self) -> bool:
        return self.value_changed and self.existing_temporal_scope in ("session", "momentary")


@dataclass(slots=True)
class _AssertionWriteResult:
    assertion_id: str
    triggered_stable: bool = False
    should_notify: bool = True
    governance_action: CorrectionPolicyAction = CorrectionPolicyAction.ACCEPT_ACTIVE


def build_assertion_merge_context(
    existing: Any,
    normalized_candidate: Dict[str, Any],
) -> AssertionMergeContext:
    """Compare an existing assertion row with a normalized candidate."""
    merged_evidence = sorted(
        set(json.loads(existing["evidence_events"] or "[]")).union(
            normalized_candidate["evidence_events"]
        )
    )
    evidence_cap = max_evidence_event_ids()
    if len(merged_evidence) > evidence_cap:
        merged_evidence = merged_evidence[-evidence_cap:]

    return AssertionMergeContext(
        existing_value=_canonicalize_trait_value(existing["trait_value"]),
        next_value=_canonicalize_trait_value(normalized_candidate["trait_value"]),
        existing_temporal_scope=str(existing["temporal_scope"] or "session"),
        merged_evidence=merged_evidence,
        first_inferred_at=min(
            float(existing["first_inferred_at"]),
            float(normalized_candidate["first_inferred_at"]),
        ),
        last_validated_at=max(
            float(existing["last_validated_at"]),
            float(normalized_candidate["last_validated_at"]),
        ),
        candidate_tier=source_tier(
            source_domain=normalized_candidate.get("source_domain"),
            user_feedback=None,  # a fresh candidate carries no feedback yet
        ),
        existing_tier=source_tier(
            source_domain=existing["source_domain"],
            user_feedback=existing["user_feedback"],
        ),
    )


def _assertion_insert_values(
    *,
    assertion_id: str,
    candidate: Dict[str, Any],
    trait_name: str,
    trait_value: str,
    confidence: float,
    evidence_events: list[str],
    validation_state: str,
    first_inferred_at: float,
    last_validated_at: float,
    status: str,
    now: float,
    version_root_id: str | None = None,
    previous_version_id: str | None = None,
) -> tuple[Any, ...]:
    return (
        assertion_id,
        candidate["entity_id"],
        candidate["entity_type"],
        candidate["trait_family"],
        trait_name,
        trait_value,
        confidence,
        json.dumps(evidence_events, ensure_ascii=False),
        float(candidate["volatility_index"]),
        candidate["source_domain"],
        candidate["inference_depth"],
        validation_state,
        first_inferred_at,
        last_validated_at,
        candidate["target_entity_id"],
        candidate["target_entity_type"],
        candidate["target_scope"],
        candidate["temporal_scope"],
        candidate["decay_policy"],
        candidate["decay_anchor_at"],
        candidate["context_ref_id"],
        candidate["expires_at"],
        status,
        candidate["memory_subdomain"],
        candidate["natural_summary"],
        now,
        now,
        candidate["slot_key"],
        candidate["claim_fingerprint"],
        None,
        version_root_id or assertion_id,
        previous_version_id,
        first_inferred_at,
        None,
        candidate["scope_key"],
        candidate["scope_json"],
    )


def _existing_assertion_update_values(
    *,
    assertion_id: str,
    candidate: Dict[str, Any],
    merge_context: AssertionMergeContext,
    validation_state: str,
    confidence: float,
    now: float,
) -> tuple[Any, ...]:
    return (
        merge_context.next_value,
        confidence,
        json.dumps(merge_context.merged_evidence, ensure_ascii=False),
        candidate["slot_key"],
        candidate["claim_fingerprint"],
        candidate["scope_key"],
        candidate["scope_json"],
        validation_state,
        validation_state,
        merge_context.last_validated_at,
        merge_context.first_inferred_at,
        candidate["target_entity_type"],
        candidate["target_scope"],
        candidate["temporal_scope"],
        candidate["decay_policy"],
        candidate["decay_anchor_at"],
        candidate["context_ref_id"],
        candidate["expires_at"],
        candidate["natural_summary"],
        now,
        assertion_id,
    )


def _time_span_hours(first_inferred_at: float, last_validated_at: float) -> float:
    return max(0.0, (last_validated_at - first_inferred_at) / 3600.0)


def _initial_assertion_state(
    candidate: Dict[str, Any],
    *,
    trait_name: str,
) -> tuple[str, float]:
    evidence_count = len(candidate["evidence_events"])
    base_confidence = max(
        float(candidate.get("confidence_score", 0.0) or 0.0),
        compute_confidence(evidence_count),
    )
    validation_state, confidence, _ = derive_validation_state(
        current_state=str(candidate.get("validation_state", "tentative") or "tentative"),
        current_confidence=base_confidence,
        evidence_count=evidence_count,
        time_span_hours=0.0,
        trait_name=trait_name,
        user_feedback=None,
    )
    return validation_state, confidence


def _merged_assertion_state(
    *,
    merge_context: AssertionMergeContext,
    trait_name: str,
    current_state: str,
    current_confidence: float,
    user_feedback: Any,
) -> tuple[str, float]:
    evidence_count = len(merge_context.merged_evidence)
    base_confidence = compute_confidence(evidence_count)
    validation_state, confidence, _ = derive_validation_state(
        current_state=current_state,
        current_confidence=max(base_confidence, current_confidence),
        evidence_count=evidence_count,
        time_span_hours=_time_span_hours(
            merge_context.first_inferred_at,
            merge_context.last_validated_at,
        ),
        trait_name=trait_name,
        user_feedback=user_feedback,
    )
    return validation_state, confidence


class L2StoreAssertionMixin:
    """Persist and update ToM assertion records."""

    async def _upsert_assertion(self, candidate: Dict[str, Any]) -> str:
        host = cast(_AssertionHostProtocol, self)
        now = time.time()
        await host.initialize()
        normalized_candidate = normalize_assertion_candidate(candidate, host, now=now)
        normalized_candidate["forget_fingerprint"] = assertion_claim_fingerprint(
            slot_key_value=str(normalized_candidate["slot_key"]),
            trait_value=normalized_candidate["trait_value"],
        )
        trait_name = str(candidate.get("trait_name", "")).strip()
        evidence_timestamps = await host.resolve_evidence_timestamps(
            list(normalized_candidate["evidence_events"])
        )

        async with sqlite_connection_async(host.db_path) as db:
            db.row_factory = aiosqlite.Row
            await db.execute("BEGIN IMMEDIATE")
            try:
                original_evidence = list(normalized_candidate["evidence_events"])
                filtered_evidence = await filter_candidate_evidence_by_forget_rules(
                    db,
                    target_kind=CorrectionTargetKind.ASSERTION,
                    semantic_fingerprint=str(normalized_candidate["forget_fingerprint"]),
                    event_ids=original_evidence,
                    event_timestamps=evidence_timestamps,
                    observed_at=float(normalized_candidate["last_validated_at"]),
                    observed_from=float(normalized_candidate["first_inferred_at"]),
                    observed_to=float(normalized_candidate["last_validated_at"]),
                    entity_ids=(
                        str(normalized_candidate["entity_id"]),
                        str(normalized_candidate["target_entity_id"]),
                    ),
                )
                for rule_id, forgotten_event_ids in filtered_evidence.forgotten_by_rule.items():
                    await append_forget_evidence_event_ids(
                        db,
                        rule_id=rule_id,
                        event_ids=forgotten_event_ids,
                        created_at=now,
                    )
                normalized_candidate["evidence_events"] = list(filtered_evidence.retained_event_ids)
                normalized_candidate["forget_prechecked"] = bool(original_evidence)

                if original_evidence and not filtered_evidence.retained_event_ids:
                    policy = CorrectionPolicyDecision(
                        CorrectionPolicyAction.BLOCKED_BY_FORGET,
                        forget_rule_id=filtered_evidence.blocking_rule_id,
                    )
                    result = self._governed_noop_result(policy, normalized_candidate)
                    await db.commit()
                    return result.assertion_id

                if filtered_evidence.has_forgotten_evidence:
                    retained_bounds = filtered_evidence.retained_observation_bounds
                    if retained_bounds is None:
                        raise RuntimeError("Retained assertion evidence has no observation bounds")
                    first_inferred_at, last_validated_at = retained_bounds
                    normalized_candidate["first_inferred_at"] = first_inferred_at
                    normalized_candidate["last_validated_at"] = last_validated_at
                    normalized_candidate["decay_anchor_at"] = last_validated_at
                    if candidate.get("expires_at") is None:
                        normalized_candidate["expires_at"] = host._coerce_expires_at(
                            None,
                            trait_family=str(normalized_candidate["trait_family"]),
                            trait_name=trait_name,
                            target_entity_id=str(normalized_candidate["target_entity_id"]),
                            anchor_at=last_validated_at,
                        )

                await append_claim_evidence_event_ids(
                    db,
                    target_kind=CorrectionTargetKind.ASSERTION,
                    claim_fingerprint=str(normalized_candidate["claim_fingerprint"]),
                    event_ids=normalized_candidate["evidence_events"],
                    observed_at=filtered_evidence.fallback_observed_at,
                    created_at=now,
                    event_timestamps=filtered_evidence.resolved_timestamps,
                    observed_from=filtered_evidence.fallback_observed_from,
                    observed_to=filtered_evidence.fallback_observed_to,
                    mark_missing_timestamps_approximate=True,
                )
                policy = await CorrectionPolicyEvaluator().evaluate_assertion(
                    db,
                    normalized_candidate,
                )
                await self._record_governed_candidate_evidence(
                    db,
                    host=host,
                    policy=policy,
                    candidate=normalized_candidate,
                    now=now,
                )
                if policy.action in {
                    CorrectionPolicyAction.BLOCKED_BY_CORRECTION,
                    CorrectionPolicyAction.BLOCKED_BY_FORGET,
                    CorrectionPolicyAction.REQUIRES_SCOPE,
                }:
                    result = self._governed_noop_result(policy, normalized_candidate)
                elif policy.action == CorrectionPolicyAction.ACCEPT_HISTORICAL:
                    result = await self._merge_historical_evidence(
                        db,
                        policy=policy,
                        candidate=normalized_candidate,
                        now=now,
                    )
                else:
                    existing = await self._fetch_active_assertion(db, normalized_candidate)
                    if policy.action == CorrectionPolicyAction.CREATE_SHADOW:
                        existing = await self._load_authoritative_assertion(db, policy)
                        result = await self._shadow_authoritative_conflict(
                            db,
                            existing,
                            normalized_candidate,
                            trait_name,
                            build_assertion_merge_context(existing, normalized_candidate),
                            now,
                        )
                    elif existing is None:
                        result = await self._insert_new_assertion(
                            db=db,
                            candidate=normalized_candidate,
                            trait_name=trait_name,
                            now=now,
                        )
                    else:
                        result = await self._merge_existing_assertion(
                            db=db,
                            existing=existing,
                            candidate=normalized_candidate,
                            trait_name=trait_name,
                            now=now,
                        )
                await db.commit()
            except Exception:
                await db.rollback()
                raise

        await self._refresh_snapshot_after_stable(
            host=host,
            candidate=normalized_candidate,
            trait_name=trait_name,
            result=result,
        )
        await self._notify_assertion_change_after_write(
            host=host,
            candidate=normalized_candidate,
            trait_name=trait_name,
            result=result,
        )
        return result.assertion_id

    async def _record_governed_candidate_evidence(
        self,
        db: aiosqlite.Connection,
        *,
        host: _AssertionHostProtocol,
        policy: CorrectionPolicyDecision,
        candidate: Dict[str, Any],
        now: float,
    ) -> None:
        if policy.action == CorrectionPolicyAction.BLOCKED_BY_FORGET:
            if not policy.forget_rule_id:
                raise RuntimeError("Forgotten assertion write has no governance identity")
            await append_forget_evidence_event_ids(
                db,
                rule_id=policy.forget_rule_id,
                event_ids=candidate["evidence_events"],
                created_at=now,
            )
            return
        if policy.action not in CORRECTION_GOVERNED_EVIDENCE_ACTIONS:
            return
        if not policy.correction_id:
            raise RuntimeError("Governed assertion write has no correction identity")
        await MemoryCorrectionRepository(host.db_path).append_evidence_event_ids(
            db,
            correction_id=policy.correction_id,
            target_kind=CorrectionTargetKind.ASSERTION,
            event_ids=candidate["evidence_events"],
            created_at=now,
        )

    async def _fetch_active_assertion(
        self,
        db: aiosqlite.Connection,
        candidate: Dict[str, Any],
    ) -> Any | None:
        async with db.execute(
            _ACTIVE_ASSERTION_SQL,
            (
                candidate["slot_key"],
                candidate["scope_key"],
            ),
        ) as cursor:
            return await cursor.fetchone()

    def _governed_noop_result(
        self,
        policy: CorrectionPolicyDecision,
        candidate: Dict[str, Any],
    ) -> _AssertionWriteResult:
        assertion_id = policy.target_id or f"blocked:{candidate['claim_fingerprint']}"
        logger.info(
            "L2 assertion candidate governed without current write",
            assertion_id=assertion_id,
            entity_id=candidate["entity_id"],
            trait_name=candidate["trait_name"],
            correction_id=policy.correction_id,
            governance_action=policy.action.value,
        )
        return _AssertionWriteResult(
            assertion_id=assertion_id,
            should_notify=False,
            governance_action=policy.action,
        )

    async def _load_authoritative_assertion(
        self,
        db: aiosqlite.Connection,
        policy: CorrectionPolicyDecision,
    ) -> Any:
        if not policy.authoritative_target_id:
            raise RuntimeError("Authoritative correction rule has no replacement target")
        async with db.execute(
            "SELECT * FROM tom_trait_assertions WHERE assertion_id = ?",
            (policy.authoritative_target_id,),
        ) as cursor:
            row = await cursor.fetchone()
        if row is None or str(row["status"]) != "stable":
            raise RuntimeError("Authoritative assertion is not current")
        return row

    async def _merge_historical_evidence(
        self,
        db: aiosqlite.Connection,
        *,
        policy: CorrectionPolicyDecision,
        candidate: Dict[str, Any],
        now: float,
    ) -> _AssertionWriteResult:
        if not policy.target_id:
            return self._governed_noop_result(policy, candidate)
        async with db.execute(
            "SELECT * FROM tom_trait_assertions WHERE assertion_id = ?",
            (policy.target_id,),
        ) as cursor:
            row = await cursor.fetchone()
        if row is None:
            return self._governed_noop_result(policy, candidate)
        evidence = sorted(
            set(json.loads(row["evidence_events"] or "[]")).union(candidate["evidence_events"])
        )[-max_evidence_event_ids() :]
        valid_to = float(row["valid_to"]) if row["valid_to"] is not None else None
        last_validated_at = max(
            float(row["last_validated_at"]),
            float(candidate["last_validated_at"]),
        )
        if valid_to is not None:
            last_validated_at = min(last_validated_at, valid_to)
        await db.execute(
            """
            UPDATE tom_trait_assertions
            SET evidence_events = ?, first_inferred_at = ?, last_validated_at = ?,
                updated_at = ?
            WHERE assertion_id = ?
            """,
            (
                json.dumps(evidence, ensure_ascii=False),
                min(float(row["first_inferred_at"]), float(candidate["first_inferred_at"])),
                last_validated_at,
                now,
                policy.target_id,
            ),
        )
        return _AssertionWriteResult(
            assertion_id=policy.target_id,
            should_notify=False,
            governance_action=policy.action,
        )

    async def _merge_existing_assertion(
        self,
        *,
        db: aiosqlite.Connection,
        existing: Any,
        candidate: Dict[str, Any],
        trait_name: str,
        now: float,
    ) -> _AssertionWriteResult:
        merge_context = build_assertion_merge_context(existing, candidate)
        if existing["authority_ref"] and not merge_context.value_changed:
            return await self._merge_authoritative_evidence(
                db,
                existing=existing,
                merge_context=merge_context,
                now=now,
            )
        if merge_context.inferred_conflicts_with_authoritative:
            return await self._shadow_authoritative_conflict(
                db, existing, candidate, trait_name, merge_context, now
            )
        if merge_context.should_update_volatile_in_place:
            return await self._update_volatile_assertion_in_place(
                db, existing, candidate, trait_name, merge_context, now
            )
        if merge_context.value_changed:
            return await self._supersede_assertion(
                db, existing, candidate, trait_name, merge_context, now
            )
        return await self._merge_same_value_assertion(
            db, existing, candidate, trait_name, merge_context, now
        )

    async def _merge_authoritative_evidence(
        self,
        db: aiosqlite.Connection,
        *,
        existing: Any,
        merge_context: AssertionMergeContext,
        now: float,
    ) -> _AssertionWriteResult:
        assertion_id = str(existing["assertion_id"])
        await db.execute(
            """
            UPDATE tom_trait_assertions
            SET evidence_events = ?, first_inferred_at = ?, last_validated_at = ?,
                updated_at = ?
            WHERE assertion_id = ?
            """,
            (
                json.dumps(merge_context.merged_evidence, ensure_ascii=False),
                merge_context.first_inferred_at,
                merge_context.last_validated_at,
                now,
                assertion_id,
            ),
        )
        return _AssertionWriteResult(assertion_id=assertion_id, should_notify=False)

    async def _insert_new_assertion(
        self,
        *,
        db: aiosqlite.Connection,
        candidate: Dict[str, Any],
        trait_name: str,
        now: float,
    ) -> _AssertionWriteResult:
        """Insert a brand-new assertion row using the shared state machine."""
        evidence_count = len(candidate["evidence_events"])
        validation_state, confidence = _initial_assertion_state(candidate, trait_name=trait_name)
        assertion_id = f"assert_{uuid.uuid4().hex}"
        await db.execute(
            _INSERT_SQL,
            _assertion_insert_values(
                assertion_id=assertion_id,
                candidate=candidate,
                trait_name=trait_name,
                trait_value=_canonicalize_trait_value(candidate["trait_value"]),
                confidence=confidence,
                evidence_events=candidate["evidence_events"],
                validation_state=validation_state,
                first_inferred_at=float(candidate["first_inferred_at"]),
                last_validated_at=float(candidate["last_validated_at"]),
                status=validation_state,
                now=now,
            ),
        )
        logger.debug(
            "L2 assertion upserted",
            assertion_id=assertion_id,
            entity_id=candidate["entity_id"],
            trait_name=trait_name,
            validation_state=validation_state,
            confidence=confidence,
            evidence_count=evidence_count,
            action="inserted",
        )
        return _AssertionWriteResult(
            assertion_id=assertion_id,
            triggered_stable=validation_state == "stable",
        )

    async def _shadow_authoritative_conflict(
        self,
        db: aiosqlite.Connection,
        existing: Any,
        candidate: Dict[str, Any],
        trait_name: str,
        merge_context: AssertionMergeContext,
        now: float,
    ) -> _AssertionWriteResult:
        async with db.execute(
            """
            SELECT * FROM tom_trait_assertions
            WHERE slot_key = ? AND scope_key = ? AND claim_fingerprint = ?
              AND status = 'shadow'
            ORDER BY updated_at DESC
            LIMIT 1
            """,
            (
                candidate["slot_key"],
                candidate["scope_key"],
                candidate["claim_fingerprint"],
            ),
        ) as cursor:
            existing_shadow = await cursor.fetchone()
        if existing_shadow is not None:
            shadow_merge = build_assertion_merge_context(existing_shadow, candidate)
            shadow_id = str(existing_shadow["assertion_id"])
            await db.execute(
                """
                UPDATE tom_trait_assertions
                SET evidence_events = ?, first_inferred_at = ?, last_validated_at = ?,
                    updated_at = ?
                WHERE assertion_id = ?
                """,
                (
                    json.dumps(shadow_merge.merged_evidence, ensure_ascii=False),
                    shadow_merge.first_inferred_at,
                    shadow_merge.last_validated_at,
                    now,
                    shadow_id,
                ),
            )
            return _AssertionWriteResult(
                assertion_id=shadow_id,
                should_notify=False,
                governance_action=CorrectionPolicyAction.CREATE_SHADOW,
            )
        shadow_id = f"assert_{uuid.uuid4().hex}"
        await db.execute(
            _INSERT_SQL,
            _assertion_insert_values(
                assertion_id=shadow_id,
                candidate=candidate,
                trait_name=trait_name,
                trait_value=merge_context.next_value,
                confidence=compute_confidence(len(candidate["evidence_events"])),
                evidence_events=candidate["evidence_events"],
                validation_state="shadow",
                first_inferred_at=float(candidate["first_inferred_at"]),
                last_validated_at=float(candidate["last_validated_at"]),
                status="shadow",
                now=now,
                version_root_id=str(existing["version_root_id"] or existing["assertion_id"]),
                previous_version_id=str(existing["assertion_id"]),
            ),
        )
        logger.info(
            "L2 assertion shadowed (inferred vs authoritative conflict)",
            shadow_id=shadow_id,
            authoritative_id=str(existing["assertion_id"]),
            entity_id=candidate["entity_id"],
            trait_name=trait_name,
            authoritative_value=merge_context.existing_value,
            inferred_value=merge_context.next_value,
        )
        return _AssertionWriteResult(
            assertion_id=shadow_id,
            governance_action=CorrectionPolicyAction.CREATE_SHADOW,
        )

    async def _update_volatile_assertion_in_place(
        self,
        db: aiosqlite.Connection,
        existing: Any,
        candidate: Dict[str, Any],
        trait_name: str,
        merge_context: AssertionMergeContext,
        now: float,
    ) -> _AssertionWriteResult:
        contradicted_ceiling = assertion_float_setting(
            "contradicted_confidence_ceiling",
            CONTRADICTED_CONFIDENCE_CEILING,
        )
        confidence = min(
            contradicted_ceiling,
            max(0.15, float(existing["confidence_score"]) * contradicted_ceiling),
        )
        return await self._update_existing_assertion(
            db=db,
            existing=existing,
            candidate=candidate,
            trait_name=trait_name,
            merge_context=merge_context,
            validation_state="contradicted",
            confidence=confidence,
            action="updated_in_place",
            now=now,
        )

    async def _supersede_assertion(
        self,
        db: aiosqlite.Connection,
        existing: Any,
        candidate: Dict[str, Any],
        trait_name: str,
        merge_context: AssertionMergeContext,
        now: float,
    ) -> _AssertionWriteResult:
        new_assertion_id = f"assert_{uuid.uuid4().hex}"
        validation_state, confidence = _merged_assertion_state(
            merge_context=merge_context,
            trait_name=trait_name,
            current_state="tentative",
            current_confidence=0.0,
            user_feedback=None,
        )
        await db.execute(
            _SUPERSEDE_ASSERTION_SQL,
            (
                new_assertion_id,
                now,
                now,
                merge_context.last_validated_at,
                str(existing["assertion_id"]),
            ),
        )
        await self._insert_superseding_assertion(
            db=db,
            assertion_id=new_assertion_id,
            candidate=candidate,
            trait_name=trait_name,
            merge_context=merge_context,
            validation_state=validation_state,
            confidence=confidence,
            now=now,
            version_root_id=str(existing["version_root_id"] or existing["assertion_id"]),
            previous_version_id=str(existing["assertion_id"]),
        )
        logger.info(
            "L2 assertion superseded",
            old_assertion_id=str(existing["assertion_id"]),
            new_assertion_id=new_assertion_id,
            entity_id=candidate["entity_id"],
            trait_name=trait_name,
            old_value=merge_context.existing_value,
            new_value=merge_context.next_value,
            evidence_count=len(merge_context.merged_evidence),
            validation_state=validation_state,
        )
        return _AssertionWriteResult(
            assertion_id=new_assertion_id,
            triggered_stable=validation_state == "stable",
        )

    async def _insert_superseding_assertion(
        self,
        *,
        db: aiosqlite.Connection,
        assertion_id: str,
        candidate: Dict[str, Any],
        trait_name: str,
        merge_context: AssertionMergeContext,
        validation_state: str,
        confidence: float,
        now: float,
        version_root_id: str,
        previous_version_id: str,
    ) -> None:
        await db.execute(
            _INSERT_SQL,
            _assertion_insert_values(
                assertion_id=assertion_id,
                candidate=candidate,
                trait_name=trait_name,
                trait_value=merge_context.next_value,
                confidence=confidence,
                evidence_events=merge_context.merged_evidence,
                validation_state=validation_state,
                first_inferred_at=merge_context.first_inferred_at,
                last_validated_at=merge_context.last_validated_at,
                status=validation_state,
                now=now,
                version_root_id=version_root_id,
                previous_version_id=previous_version_id,
            ),
        )

    async def _merge_same_value_assertion(
        self,
        db: aiosqlite.Connection,
        existing: Any,
        candidate: Dict[str, Any],
        trait_name: str,
        merge_context: AssertionMergeContext,
        now: float,
    ) -> _AssertionWriteResult:
        validation_state, confidence = _merged_assertion_state(
            merge_context=merge_context,
            trait_name=trait_name,
            current_state=str(existing["validation_state"] or "tentative"),
            current_confidence=float(existing["confidence_score"]),
            user_feedback=existing["user_feedback"],
        )
        return await self._update_existing_assertion(
            db=db,
            existing=existing,
            candidate=candidate,
            trait_name=trait_name,
            merge_context=merge_context,
            validation_state=validation_state,
            confidence=confidence,
            action="updated",
            now=now,
        )

    async def _update_existing_assertion(
        self,
        *,
        db: aiosqlite.Connection,
        existing: Any,
        candidate: Dict[str, Any],
        trait_name: str,
        merge_context: AssertionMergeContext,
        validation_state: str,
        confidence: float,
        action: str,
        now: float,
    ) -> _AssertionWriteResult:
        sql = (
            _UPDATE_VOLATILE_ASSERTION_SQL
            if action == "updated_in_place"
            else _UPDATE_SAME_VALUE_ASSERTION_SQL
        )
        assertion_id = str(existing["assertion_id"])
        await db.execute(
            sql,
            _existing_assertion_update_values(
                assertion_id=assertion_id,
                candidate=candidate,
                merge_context=merge_context,
                validation_state=validation_state,
                confidence=confidence,
                now=now,
            ),
        )
        logger.debug(
            "L2 assertion upserted",
            assertion_id=assertion_id,
            entity_id=candidate["entity_id"],
            trait_name=trait_name,
            validation_state=validation_state,
            confidence=confidence,
            evidence_count=len(merge_context.merged_evidence),
            action=action,
        )
        return _AssertionWriteResult(
            assertion_id=assertion_id,
            triggered_stable=validation_state == "stable",
        )

    async def _refresh_snapshot_after_stable(
        self,
        *,
        host: _AssertionHostProtocol,
        candidate: Dict[str, Any],
        trait_name: str,
        result: _AssertionWriteResult,
    ) -> None:
        if not result.triggered_stable:
            return
        try:
            await host.refresh_entity_snapshot(
                entity_id=candidate["entity_id"],
                entity_type=candidate["entity_type"],
            )
        except Exception as exc:  # pragma: no cover - defensive
            logger.warning(
                "L2 snapshot refresh after stable assertion failed",
                entity_id=candidate["entity_id"],
                trait_name=trait_name,
                error=str(exc),
            )

    async def _notify_assertion_change_after_write(
        self,
        *,
        host: _AssertionHostProtocol,
        candidate: Dict[str, Any],
        trait_name: str,
        result: _AssertionWriteResult,
    ) -> None:
        if not result.should_notify:
            return
        try:
            await host._notify_assertion_changed(
                {
                    "assertion_id": result.assertion_id,
                    "entity_id": candidate["entity_id"],
                    "entity_type": candidate["entity_type"],
                    "trait_family": candidate["trait_family"],
                    "trait_name": trait_name,
                    "trait_value": candidate["trait_value"],
                }
            )
        except Exception as exc:  # pragma: no cover - defensive
            logger.warning(
                "L2 assertion change notification failed",
                assertion_id=result.assertion_id,
                entity_id=candidate["entity_id"],
                trait_name=trait_name,
                error=str(exc),
            )
