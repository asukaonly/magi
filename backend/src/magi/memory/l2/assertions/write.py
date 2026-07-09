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
    created_at, updated_at
) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
"""

_ACTIVE_ASSERTION_SQL = """
SELECT * FROM tom_trait_assertions
WHERE entity_id = ? AND entity_type = ? AND trait_name = ? AND target_entity_id = ?
  AND status NOT IN ('superseded', 'archived', 'expired', 'user_rejected', 'shadow')
ORDER BY updated_at DESC
LIMIT 1
"""

_UPDATE_VOLATILE_ASSERTION_SQL = """
UPDATE tom_trait_assertions
SET trait_value = ?, confidence_score = ?, evidence_events = ?,
    validation_state = ?, status = ?, last_validated_at = ?,
    first_inferred_at = ?,
    target_entity_type = ?, target_scope = ?, temporal_scope = ?,
    decay_policy = ?, decay_anchor_at = ?, context_ref_id = ?,
    expires_at = ?, natural_summary = ?, updated_at = ?
WHERE assertion_id = ?
"""

_SUPERSEDE_ASSERTION_SQL = """
UPDATE tom_trait_assertions
SET status = 'superseded', superseded_by = ?, superseded_at = ?, updated_at = ?
WHERE assertion_id = ?
"""

_UPDATE_SAME_VALUE_ASSERTION_SQL = """
UPDATE tom_trait_assertions
SET trait_value = ?, confidence_score = ?, evidence_events = ?,
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
            normalize_store_entity_ref(candidate.get("target_entity_id"), target_entity_type)
            or ""
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
        trait_name = str(candidate.get("trait_name", "")).strip()

        async with sqlite_connection_async(host.db_path) as db:
            db.row_factory = aiosqlite.Row
            await db.execute("BEGIN IMMEDIATE")
            try:
                existing = await self._fetch_active_assertion(db, normalized_candidate)
                if existing is None:
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

    async def _fetch_active_assertion(
        self,
        db: aiosqlite.Connection,
        candidate: Dict[str, Any],
    ) -> Any | None:
        async with db.execute(
            _ACTIVE_ASSERTION_SQL,
            (
                candidate["entity_id"],
                candidate["entity_type"],
                candidate["trait_name"],
                candidate["target_entity_id"],
            ),
        ) as cursor:
            return await cursor.fetchone()

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
        return _AssertionWriteResult(assertion_id=shadow_id)

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
            (new_assertion_id, now, now, str(existing["assertion_id"])),
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
