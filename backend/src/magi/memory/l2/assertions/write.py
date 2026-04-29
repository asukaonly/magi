"""ToM assertion upsert helpers for the L2 cognition store."""

from __future__ import annotations

import json
import time
import uuid
from typing import Any, Dict, List, Protocol, cast

import aiosqlite

from ....core.logger import get_logger
from ....core.sqlite import sqlite_connection_async
from ..storage.utils import (
    MAX_EVIDENCE_EVENT_IDS,
    normalize_store_entity_ref,
    normalize_store_entity_type,
)

logger = get_logger(__name__)


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

    async def _materialize_snapshot(
        self,
        *,
        entity_id: str,
        entity_type: str,
        trait_name: str,
        trait_value: str,
        assertion_ids: List[str],
        last_interaction_at: float,
    ) -> None:
        ...


class L2StoreAssertionMixin:
    """Persist and update ToM assertion records."""

    async def _upsert_assertion(self, candidate: Dict[str, Any]) -> str:
        host = cast(_AssertionHostProtocol, self)
        now = time.time()
        await host.initialize()
        normalized_entity_type = normalize_store_entity_type(candidate.get("entity_type")) or "other"
        normalized_candidate = dict(candidate)
        normalized_candidate["entity_type"] = normalized_entity_type
        normalized_candidate["trait_family"] = str(candidate.get("trait_family", "")).strip().lower() or host._derive_trait_family(
            str(candidate.get("trait_name", "")).strip()
        )
        normalized_candidate["target_entity_type"] = normalize_store_entity_type(candidate.get("target_entity_type")) or ""
        normalized_candidate["target_entity_id"] = (
            normalize_store_entity_ref(candidate.get("target_entity_id"), normalized_candidate["target_entity_type"]) or ""
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

        async with sqlite_connection_async(host.db_path) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute(
                """
                SELECT * FROM tom_trait_assertions
                WHERE entity_id = ? AND entity_type = ? AND trait_name = ? AND target_entity_id = ?
                  AND status NOT IN ('superseded', 'archived', 'expired', 'user_rejected')
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
                assertion_id = f"assert_{uuid.uuid4().hex}"
                await db.execute(
                    """
                    INSERT INTO tom_trait_assertions(
                        assertion_id, entity_id, entity_type, trait_family, trait_name, trait_value,
                        confidence_score, evidence_events, volatility_index, source_domain,
                        inference_depth, validation_state, first_inferred_at, last_validated_at,
                        target_entity_id, target_entity_type, target_scope, temporal_scope,
                        decay_policy, decay_anchor_at, context_ref_id, expires_at,
                        status, privacy_scope, memory_subdomain, created_at, updated_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        assertion_id,
                        normalized_candidate["entity_id"],
                        normalized_candidate["entity_type"],
                        normalized_candidate["trait_family"],
                        normalized_candidate["trait_name"],
                        normalized_candidate["trait_value"],
                        float(normalized_candidate["confidence_score"]),
                        json.dumps(normalized_candidate["evidence_events"], ensure_ascii=False),
                        float(normalized_candidate["volatility_index"]),
                        normalized_candidate["source_domain"],
                        normalized_candidate["inference_depth"],
                        normalized_candidate["validation_state"],
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
                        normalized_candidate["validation_state"],
                        "private",
                        normalized_candidate["memory_subdomain"],
                        now,
                        now,
                    ),
                )
                await db.commit()
                logger.debug(
                    "L2 assertion upserted",
                    assertion_id=assertion_id,
                    entity_id=normalized_candidate["entity_id"],
                    trait_name=normalized_candidate["trait_name"],
                    validation_state=normalized_candidate["validation_state"],
                    confidence=float(normalized_candidate["confidence_score"]),
                    evidence_count=len(normalized_candidate["evidence_events"]),
                    action="inserted",
                )
                return assertion_id

            evidence = sorted(
                set(json.loads(existing["evidence_events"] or "[]")).union(normalized_candidate["evidence_events"])
            )
            if len(evidence) > MAX_EVIDENCE_EVENT_IDS:
                evidence = evidence[-MAX_EVIDENCE_EVENT_IDS:]
            first_inferred_at = float(existing["first_inferred_at"])
            last_validated_at = float(normalized_candidate["last_validated_at"])
            existing_value = str(existing["trait_value"])
            next_value = str(normalized_candidate["trait_value"])
            existing_temporal_scope = str(existing["temporal_scope"] or "session")

            if existing_value != next_value:
                if existing_temporal_scope in ("session", "momentary"):
                    confidence = max(0.15, float(existing["confidence_score"]) * 0.35)
                    validation_state = "contradicted"
                    status = "contradicted"
                    await db.execute(
                        """
                        UPDATE tom_trait_assertions
                        SET trait_value = ?, confidence_score = ?, evidence_events = ?,
                            validation_state = ?, status = ?, last_validated_at = ?,
                            target_entity_type = ?, target_scope = ?, temporal_scope = ?,
                            decay_policy = ?, decay_anchor_at = ?, context_ref_id = ?,
                            expires_at = ?, updated_at = ?
                        WHERE assertion_id = ?
                        """,
                        (
                            next_value,
                            confidence,
                            json.dumps(evidence, ensure_ascii=False),
                            validation_state,
                            status,
                            last_validated_at,
                            normalized_candidate["target_entity_type"],
                            normalized_candidate["target_scope"],
                            normalized_candidate["temporal_scope"],
                            normalized_candidate["decay_policy"],
                            normalized_candidate["decay_anchor_at"],
                            normalized_candidate["context_ref_id"],
                            normalized_candidate["expires_at"],
                            now,
                            str(existing["assertion_id"]),
                        ),
                    )
                    await db.commit()
                    logger.debug(
                        "L2 assertion upserted",
                        assertion_id=str(existing["assertion_id"]),
                        entity_id=normalized_candidate["entity_id"],
                        trait_name=normalized_candidate["trait_name"],
                        validation_state=validation_state,
                        confidence=confidence,
                        evidence_count=len(evidence),
                        action="updated_in_place",
                    )
                    return str(existing["assertion_id"])

                new_assertion_id = f"assert_{uuid.uuid4().hex}"
                await db.execute(
                    """
                    UPDATE tom_trait_assertions
                    SET status = 'superseded', superseded_by = ?, superseded_at = ?, updated_at = ?
                    WHERE assertion_id = ?
                    """,
                    (new_assertion_id, now, now, str(existing["assertion_id"])),
                )
                await db.execute(
                    """
                    INSERT INTO tom_trait_assertions(
                        assertion_id, entity_id, entity_type, trait_family, trait_name, trait_value,
                        confidence_score, evidence_events, volatility_index, source_domain,
                        inference_depth, validation_state, first_inferred_at, last_validated_at,
                        target_entity_id, target_entity_type, target_scope, temporal_scope,
                        decay_policy, decay_anchor_at, context_ref_id, expires_at,
                        status, privacy_scope, memory_subdomain, created_at, updated_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        new_assertion_id,
                        normalized_candidate["entity_id"],
                        normalized_candidate["entity_type"],
                        normalized_candidate["trait_family"],
                        normalized_candidate["trait_name"],
                        next_value,
                        float(normalized_candidate["confidence_score"]),
                        json.dumps(normalized_candidate["evidence_events"], ensure_ascii=False),
                        float(normalized_candidate["volatility_index"]),
                        normalized_candidate["source_domain"],
                        normalized_candidate["inference_depth"],
                        "tentative",
                        float(normalized_candidate["first_inferred_at"]),
                        last_validated_at,
                        normalized_candidate["target_entity_id"],
                        normalized_candidate["target_entity_type"],
                        normalized_candidate["target_scope"],
                        normalized_candidate["temporal_scope"],
                        normalized_candidate["decay_policy"],
                        normalized_candidate["decay_anchor_at"],
                        normalized_candidate["context_ref_id"],
                        normalized_candidate["expires_at"],
                        "tentative",
                        str(existing["privacy_scope"] or "private"),
                        normalized_candidate["memory_subdomain"],
                        now,
                        now,
                    ),
                )
                await db.commit()
                logger.info(
                    "L2 assertion superseded",
                    old_assertion_id=str(existing["assertion_id"]),
                    new_assertion_id=new_assertion_id,
                    entity_id=normalized_candidate["entity_id"],
                    trait_name=normalized_candidate["trait_name"],
                    old_value=existing_value,
                    new_value=next_value,
                )
                return new_assertion_id

            confidence = min(0.95, 0.3 + 0.25 * max(0, len(evidence) - 1))
            enough_events = len(evidence) >= 3
            enough_span = (last_validated_at - first_inferred_at) > 24 * 60 * 60
            validation_state = "stable" if enough_events and enough_span and confidence >= 0.8 else "corroborated"
            status = validation_state

            await db.execute(
                """
                UPDATE tom_trait_assertions
                SET confidence_score = ?, evidence_events = ?,
                    validation_state = ?, status = ?, last_validated_at = ?, target_entity_type = ?,
                    target_scope = ?, temporal_scope = ?, decay_policy = ?, decay_anchor_at = ?,
                    context_ref_id = ?, expires_at = ?, updated_at = ?
                WHERE assertion_id = ?
                """,
                (
                    confidence,
                    json.dumps(evidence, ensure_ascii=False),
                    validation_state,
                    status,
                    last_validated_at,
                    normalized_candidate["target_entity_type"],
                    normalized_candidate["target_scope"],
                    normalized_candidate["temporal_scope"],
                    normalized_candidate["decay_policy"],
                    normalized_candidate["decay_anchor_at"],
                    normalized_candidate["context_ref_id"],
                    normalized_candidate["expires_at"],
                    now,
                    str(existing["assertion_id"]),
                ),
            )
            await db.commit()

        logger.debug(
            "L2 assertion upserted",
            assertion_id=str(existing["assertion_id"]),
            entity_id=normalized_candidate["entity_id"],
            trait_name=normalized_candidate["trait_name"],
            validation_state=validation_state,
            confidence=confidence,
            evidence_count=len(evidence),
            action="updated",
        )

        if validation_state == "stable":
            await host._materialize_snapshot(
                entity_id=normalized_candidate["entity_id"],
                entity_type=normalized_candidate["entity_type"],
                trait_name=normalized_candidate["trait_name"],
                trait_value=next_value,
                assertion_ids=[str(existing["assertion_id"])],
                last_interaction_at=last_validated_at,
            )
        return str(existing["assertion_id"])
