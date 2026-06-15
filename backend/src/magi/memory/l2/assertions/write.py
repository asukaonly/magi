"""ToM assertion upsert helpers for the L2 cognition store."""

from __future__ import annotations

import ast
import json
import time
import uuid
from typing import Any, Dict, List, Protocol, cast

import aiosqlite

from ....core.logger import get_logger
from ....core.sqlite import sqlite_connection_async
from ..storage.utils import (
    MAX_EVIDENCE_EVENT_IDS,
    normalize_event_ids,
    normalize_store_entity_ref,
    normalize_store_entity_type,
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

    async def initialize(self) -> None:
        ...

    def _derive_trait_family(self, trait_name: str) -> str:
        ...

    def _optional_text(self, value: Any) -> str | None:
        ...

    def _coerce_expires_at(
        self,
        value: Any,
        *,
        trait_family: str,
        trait_name: str,
        target_entity_id: str,
        anchor_at: float,
    ) -> float | None:
        ...

    async def refresh_entity_snapshot(
        self,
        *,
        entity_id: str,
        entity_type: str | None = None,
    ) -> Dict[str, Any] | None:
        ...


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


class L2StoreAssertionMixin:
    """Persist and update ToM assertion records."""

    async def _upsert_assertion(self, candidate: Dict[str, Any]) -> str:
        host = cast(_AssertionHostProtocol, self)
        now = time.time()
        await host.initialize()
        normalized_entity_type = normalize_store_entity_type(candidate.get("entity_type")) or "other"
        normalized_candidate = dict(candidate)
        normalized_candidate["entity_type"] = normalized_entity_type
        normalized_candidate["trait_family"] = (
            str(candidate.get("trait_family", "")).strip().lower()
            or host._derive_trait_family(str(candidate.get("trait_name", "")).strip())
        )
        normalized_candidate["target_entity_type"] = (
            normalize_store_entity_type(candidate.get("target_entity_type")) or ""
        )
        normalized_candidate["target_entity_id"] = (
            normalize_store_entity_ref(
                candidate.get("target_entity_id"),
                normalized_candidate["target_entity_type"],
            )
            or ""
        )
        normalized_candidate["target_scope"] = str(candidate.get("target_scope", "global")).strip() or "global"
        normalized_candidate["temporal_scope"] = str(candidate.get("temporal_scope", "session")).strip() or "session"
        normalized_candidate["decay_policy"] = host._optional_text(candidate.get("decay_policy"))
        normalized_candidate["decay_anchor_at"] = float(
            candidate.get("decay_anchor_at", candidate.get("last_validated_at", now)) or now
        )
        normalized_candidate["context_ref_id"] = host._optional_text(candidate.get("context_ref_id")) or ""
        normalized_candidate["expires_at"] = host._coerce_expires_at(
            candidate.get("expires_at"),
            trait_family=normalized_candidate["trait_family"],
            trait_name=str(candidate.get("trait_name", "")).strip(),
            target_entity_id=normalized_candidate["target_entity_id"],
            anchor_at=normalized_candidate["decay_anchor_at"],
        )
        normalized_candidate["memory_subdomain"] = str(candidate.get("memory_subdomain", "")).strip() or ""
        normalized_candidate["natural_summary"] = (
            str(candidate.get("natural_summary", "") or "").strip()[:500]
        )
        normalized_candidate["evidence_events"] = normalize_event_ids(
            candidate.get("evidence_events") or []
        )
        normalized_candidate["trait_value"] = _canonicalize_trait_value(
            candidate.get("trait_value")
        )

        trait_name = str(candidate.get("trait_name", "")).strip()
        triggered_stable = False

        async with sqlite_connection_async(host.db_path) as db:
            db.row_factory = aiosqlite.Row
            await db.execute("BEGIN IMMEDIATE")
            try:
                async with db.execute(
                    """
                    SELECT * FROM tom_trait_assertions
                    WHERE entity_id = ? AND entity_type = ? AND trait_name = ? AND target_entity_id = ?
                      AND status NOT IN ('superseded', 'archived', 'expired', 'user_rejected', 'shadow')
                    ORDER BY updated_at DESC
                    LIMIT 1
                    """,
                    (
                        normalized_candidate["entity_id"],
                        normalized_candidate["entity_type"],
                        normalized_candidate["trait_name"],
                        normalized_candidate["target_entity_id"],
                    ),
                ) as cursor:
                    existing = await cursor.fetchone()

                if existing is None:
                    assertion_id, validation_state, confidence = await self._insert_new_assertion(
                        db=db,
                        candidate=normalized_candidate,
                        trait_name=trait_name,
                        now=now,
                    )
                    await db.commit()
                    logger.debug(
                        "L2 assertion upserted",
                        assertion_id=assertion_id,
                        entity_id=normalized_candidate["entity_id"],
                        trait_name=trait_name,
                        validation_state=validation_state,
                        confidence=confidence,
                        evidence_count=len(normalized_candidate["evidence_events"]),
                        action="inserted",
                    )
                    triggered_stable = validation_state == "stable"
                    result_id = assertion_id
                else:
                    existing_value = _canonicalize_trait_value(existing["trait_value"])
                    next_value = _canonicalize_trait_value(normalized_candidate["trait_value"])
                    existing_temporal_scope = str(existing["temporal_scope"] or "session")

                    merged_evidence = sorted(
                        set(json.loads(existing["evidence_events"] or "[]")).union(
                            normalized_candidate["evidence_events"]
                        )
                    )
                    if len(merged_evidence) > MAX_EVIDENCE_EVENT_IDS:
                        merged_evidence = merged_evidence[-MAX_EVIDENCE_EVENT_IDS:]
                    first_inferred_at = min(
                        float(existing["first_inferred_at"]),
                        float(normalized_candidate["first_inferred_at"]),
                    )
                    last_validated_at = max(
                        float(existing["last_validated_at"]),
                        float(normalized_candidate["last_validated_at"]),
                    )

                    candidate_tier = source_tier(
                        source_domain=normalized_candidate.get("source_domain"),
                        user_feedback=None,  # a fresh candidate carries no feedback yet
                    )
                    existing_tier = source_tier(
                        source_domain=existing["source_domain"],
                        user_feedback=existing["user_feedback"],
                    )
                    if (
                        candidate_tier == "inferred"
                        and existing_tier == "authoritative"
                        and existing_value != next_value
                    ):
                        # Inferred contradicts the user's own statement: never touch
                        # the authoritative row. Persist as a 'shadow' sibling (the
                        # active key stays owned by the authoritative assertion).
                        shadow_id = f"assert_{uuid.uuid4().hex}"
                        await db.execute(
                            _INSERT_SQL,
                            (
                                shadow_id,
                                normalized_candidate["entity_id"],
                                normalized_candidate["entity_type"],
                                normalized_candidate["trait_family"],
                                trait_name,
                                next_value,
                                compute_confidence(len(normalized_candidate["evidence_events"])),
                                json.dumps(normalized_candidate["evidence_events"], ensure_ascii=False),
                                float(normalized_candidate["volatility_index"]),
                                normalized_candidate["source_domain"],
                                normalized_candidate["inference_depth"],
                                "shadow",                                   # validation_state
                                float(normalized_candidate["first_inferred_at"]),
                                float(normalized_candidate["last_validated_at"]),
                                normalized_candidate["target_entity_id"],
                                normalized_candidate["target_entity_type"],
                                normalized_candidate["target_scope"],
                                normalized_candidate["temporal_scope"],
                                normalized_candidate["decay_policy"],
                                normalized_candidate["decay_anchor_at"],
                                normalized_candidate["context_ref_id"],
                                normalized_candidate["expires_at"],
                                "shadow",                                   # status
                                normalized_candidate["memory_subdomain"],
                                normalized_candidate["natural_summary"],
                                now,
                                now,
                            ),
                        )
                        await db.commit()
                        logger.info(
                            "L2 assertion shadowed (inferred vs authoritative conflict)",
                            shadow_id=shadow_id,
                            authoritative_id=str(existing["assertion_id"]),
                            entity_id=normalized_candidate["entity_id"],
                            trait_name=trait_name,
                            authoritative_value=existing_value,
                            inferred_value=next_value,
                        )
                        return shadow_id

                    if existing_value != next_value and existing_temporal_scope in ("session", "momentary"):
                        # In-place rewrite for volatile temporal traits.
                        confidence = max(0.15, float(existing["confidence_score"]) * 0.35)
                        validation_state = "contradicted"
                        await db.execute(
                            """
                            UPDATE tom_trait_assertions
                            SET trait_value = ?, confidence_score = ?, evidence_events = ?,
                                validation_state = ?, status = ?, last_validated_at = ?,
                                first_inferred_at = ?,
                                target_entity_type = ?, target_scope = ?, temporal_scope = ?,
                                decay_policy = ?, decay_anchor_at = ?, context_ref_id = ?,
                                expires_at = ?, natural_summary = ?, updated_at = ?
                            WHERE assertion_id = ?
                            """,
                            (
                                next_value,
                                confidence,
                                json.dumps(merged_evidence, ensure_ascii=False),
                                validation_state,
                                validation_state,
                                last_validated_at,
                                first_inferred_at,
                                normalized_candidate["target_entity_type"],
                                normalized_candidate["target_scope"],
                                normalized_candidate["temporal_scope"],
                                normalized_candidate["decay_policy"],
                                normalized_candidate["decay_anchor_at"],
                                normalized_candidate["context_ref_id"],
                                normalized_candidate["expires_at"],
                                normalized_candidate["natural_summary"],
                                now,
                                str(existing["assertion_id"]),
                            ),
                        )
                        await db.commit()
                        result_id = str(existing["assertion_id"])
                        logger.debug(
                            "L2 assertion upserted",
                            assertion_id=result_id,
                            entity_id=normalized_candidate["entity_id"],
                            trait_name=trait_name,
                            validation_state=validation_state,
                            confidence=confidence,
                            evidence_count=len(merged_evidence),
                            action="updated_in_place",
                        )
                    elif existing_value != next_value:
                        # Supersede: keep accumulated evidence on the new row so it
                        # can mature instead of resetting to tentative.
                        new_assertion_id = f"assert_{uuid.uuid4().hex}"
                        await db.execute(
                            """
                            UPDATE tom_trait_assertions
                            SET status = 'superseded', superseded_by = ?, superseded_at = ?, updated_at = ?
                            WHERE assertion_id = ?
                            """,
                            (new_assertion_id, now, now, str(existing["assertion_id"])),
                        )
                        evidence_count = len(merged_evidence)
                        time_span_hours = max(0.0, (last_validated_at - first_inferred_at) / 3600.0)
                        confidence = compute_confidence(evidence_count)
                        validation_state, confidence, _ = derive_validation_state(
                            current_state="tentative",
                            current_confidence=confidence,
                            evidence_count=evidence_count,
                            time_span_hours=time_span_hours,
                            trait_name=trait_name,
                            user_feedback=None,
                        )
                        await db.execute(
                            _INSERT_SQL,
                            (
                                new_assertion_id,
                                normalized_candidate["entity_id"],
                                normalized_candidate["entity_type"],
                                normalized_candidate["trait_family"],
                                trait_name,
                                next_value,
                                confidence,
                                json.dumps(merged_evidence, ensure_ascii=False),
                                float(normalized_candidate["volatility_index"]),
                                normalized_candidate["source_domain"],
                                normalized_candidate["inference_depth"],
                                validation_state,
                                first_inferred_at,
                                last_validated_at,
                                normalized_candidate["target_entity_id"],
                                normalized_candidate["target_entity_type"],
                                normalized_candidate["target_scope"],
                                normalized_candidate["temporal_scope"],
                                normalized_candidate["decay_policy"],
                                normalized_candidate["decay_anchor_at"],
                                normalized_candidate["context_ref_id"],
                                normalized_candidate["expires_at"],
                                validation_state,
                                normalized_candidate["memory_subdomain"],
                                normalized_candidate["natural_summary"],
                                now,
                                now,
                            ),
                        )
                        await db.commit()
                        result_id = new_assertion_id
                        triggered_stable = validation_state == "stable"
                        logger.info(
                            "L2 assertion superseded",
                            old_assertion_id=str(existing["assertion_id"]),
                            new_assertion_id=new_assertion_id,
                            entity_id=normalized_candidate["entity_id"],
                            trait_name=trait_name,
                            old_value=existing_value,
                            new_value=next_value,
                            evidence_count=evidence_count,
                            validation_state=validation_state,
                        )
                    else:
                        # Same value: accumulate evidence and recompute state.
                        evidence_count = len(merged_evidence)
                        time_span_hours = max(0.0, (last_validated_at - first_inferred_at) / 3600.0)
                        confidence = compute_confidence(evidence_count)
                        current_state = str(existing["validation_state"] or "tentative")
                        validation_state, confidence, _ = derive_validation_state(
                            current_state=current_state,
                            current_confidence=max(confidence, float(existing["confidence_score"])),
                            evidence_count=evidence_count,
                            time_span_hours=time_span_hours,
                            trait_name=trait_name,
                            user_feedback=existing["user_feedback"],
                        )
                        await db.execute(
                            """
                            UPDATE tom_trait_assertions
                            SET trait_value = ?, confidence_score = ?, evidence_events = ?,
                                validation_state = ?, status = ?,
                                last_validated_at = ?, first_inferred_at = ?,
                                target_entity_type = ?, target_scope = ?, temporal_scope = ?,
                                decay_policy = ?, decay_anchor_at = ?, context_ref_id = ?,
                                expires_at = ?, natural_summary = ?, updated_at = ?
                            WHERE assertion_id = ?
                            """,
                            (
                                next_value,
                                confidence,
                                json.dumps(merged_evidence, ensure_ascii=False),
                                validation_state,
                                validation_state,
                                last_validated_at,
                                first_inferred_at,
                                normalized_candidate["target_entity_type"],
                                normalized_candidate["target_scope"],
                                normalized_candidate["temporal_scope"],
                                normalized_candidate["decay_policy"],
                                normalized_candidate["decay_anchor_at"],
                                normalized_candidate["context_ref_id"],
                                normalized_candidate["expires_at"],
                                normalized_candidate["natural_summary"],
                                now,
                                str(existing["assertion_id"]),
                            ),
                        )
                        await db.commit()
                        result_id = str(existing["assertion_id"])
                        triggered_stable = validation_state == "stable"
                        logger.debug(
                            "L2 assertion upserted",
                            assertion_id=result_id,
                            entity_id=normalized_candidate["entity_id"],
                            trait_name=trait_name,
                            validation_state=validation_state,
                            confidence=confidence,
                            evidence_count=evidence_count,
                            action="updated",
                        )
            except Exception:
                await db.rollback()
                raise

        if triggered_stable:
            try:
                await host.refresh_entity_snapshot(
                    entity_id=normalized_candidate["entity_id"],
                    entity_type=normalized_candidate["entity_type"],
                )
            except Exception as exc:  # pragma: no cover - defensive
                logger.warning(
                    "L2 snapshot refresh after stable assertion failed",
                    entity_id=normalized_candidate["entity_id"],
                    trait_name=trait_name,
                    error=str(exc),
                )
        return result_id

    async def _insert_new_assertion(
        self,
        *,
        db: aiosqlite.Connection,
        candidate: Dict[str, Any],
        trait_name: str,
        now: float,
    ) -> tuple[str, str, float]:
        """Insert a brand-new assertion row using the shared state machine."""
        evidence_count = len(candidate["evidence_events"])
        time_span_hours = 0.0  # single observation, no span
        base_confidence = max(
            float(candidate.get("confidence_score", 0.0) or 0.0),
            compute_confidence(evidence_count),
        )
        validation_state, confidence, _ = derive_validation_state(
            current_state=str(candidate.get("validation_state", "tentative") or "tentative"),
            current_confidence=base_confidence,
            evidence_count=evidence_count,
            time_span_hours=time_span_hours,
            trait_name=trait_name,
            user_feedback=None,
        )
        assertion_id = f"assert_{uuid.uuid4().hex}"
        await db.execute(
            _INSERT_SQL,
            (
                assertion_id,
                candidate["entity_id"],
                candidate["entity_type"],
                candidate["trait_family"],
                trait_name,
                _canonicalize_trait_value(candidate["trait_value"]),
                confidence,
                json.dumps(candidate["evidence_events"], ensure_ascii=False),
                float(candidate["volatility_index"]),
                candidate["source_domain"],
                candidate["inference_depth"],
                validation_state,
                float(candidate["first_inferred_at"]),
                float(candidate["last_validated_at"]),
                candidate["target_entity_id"],
                candidate["target_entity_type"],
                candidate["target_scope"],
                candidate["temporal_scope"],
                candidate["decay_policy"],
                candidate["decay_anchor_at"],
                candidate["context_ref_id"],
                candidate["expires_at"],
                validation_state,
                candidate["memory_subdomain"],
                candidate["natural_summary"],
                now,
                now,
            ),
        )
        return assertion_id, validation_state, confidence
