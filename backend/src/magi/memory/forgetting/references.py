"""Typed replay barriers and downstream cleanup identities."""

from __future__ import annotations

import json
from collections.abc import Iterable
from typing import Any

from ...core.sqlite import sqlite_connection_async
from ..source_event_governance import (
    business_source_references,
    chat_session_source_reference,
    normalize_source_event_ids,
)
from .models import ForgetReference, ForgetSelector, ReferenceType

_SOURCE_ITEM_PREFIX = "source-item:v1:"
_IDEMPOTENCY_PREFIX = "source-idempotency:v1:"


class ForgetReferenceBuilder:
    """Resolve public event identities into typed barrier and cleanup refs."""

    def __init__(self, *, memory_db_path: str, l1: Any) -> None:
        self._memory_db_path = memory_db_path
        self._l1 = l1

    async def selector_references(
        self,
        selector: ForgetSelector,
    ) -> tuple[ForgetReference, ...]:
        if selector.kind == "chat_session":
            session_ref = chat_session_source_reference(
                user_id=str(selector.payload["user_id"]),
                session_id=str(selector.payload["session_id"]),
            )
            references = [
                ForgetReference("", "barrier", "chat_session", session_ref),
                ForgetReference("", "cleanup", "chat_session", session_ref),
                ForgetReference(
                    "",
                    "target",
                    "chat_projection",
                    _chat_projection_reference(
                        user_id=str(selector.payload["user_id"]),
                        session_id=str(selector.payload["session_id"]),
                    ),
                ),
            ]
            for turn_id in normalize_source_event_ids(selector.payload.get("turn_ids", [])):
                references.extend(
                    (
                        ForgetReference("", "barrier", "turn", turn_id),
                        ForgetReference("", "cleanup", "turn", turn_id),
                    )
                )
            return _dedupe_references(references)

        if selector.kind == "chat_history":
            payload = selector.payload
            references: list[ForgetReference] = [
                ForgetReference(
                    "",
                    "target",
                    "chat_projection",
                    _chat_projection_reference(
                        user_id=str(payload["user_id"]),
                        session_id=str(payload["session_id"]),
                    ),
                )
            ]
            for turn_id in normalize_source_event_ids(payload.get("turn_ids", [])):
                references.extend(
                    (
                        ForgetReference("", "barrier", "turn", turn_id),
                        ForgetReference("", "cleanup", "turn", turn_id),
                    )
                )
            for message in payload.get("messages", []):
                if not isinstance(message, dict):
                    continue
                for value in business_source_references(
                    source=str(message.get("source") or ""),
                    event_type=str(message.get("event_type") or ""),
                    source_item_id=str(message.get("message_id") or ""),
                    idempotency_key=str(message.get("message_id") or ""),
                ):
                    references.append(
                        ForgetReference(
                            "",
                            "barrier",
                            _business_reference_type(value),
                            value,
                        )
                    )
            return _dedupe_references(references)

        if selector.kind == "chat_message":
            payload = selector.payload
            references = business_source_references(
                source=str(payload["source"]),
                event_type=str(payload["event_type"]),
                source_item_id=str(payload["message_id"]),
                idempotency_key=str(payload["message_id"]),
            )
            references = [
                ForgetReference("", "barrier", _business_reference_type(value), value)
                for value in references
            ]
            references.append(
                ForgetReference(
                    "",
                    "target",
                    "chat_projection",
                    _chat_projection_reference(
                        user_id=str(payload["user_id"]),
                        session_id=str(payload["session_id"]),
                    ),
                )
            )
            return _dedupe_references(references)
        return ()

    async def event_references(
        self,
        event_ids: Iterable[str],
        *,
        include_turn_references: bool,
        block_source_item: bool,
    ) -> tuple[ForgetReference, ...]:
        normalized = normalize_source_event_ids(event_ids)
        if not normalized:
            return ()
        identities: dict[str, dict[str, Any]] = {}
        if self._l1 is not None:
            identities = await self._l1.get_raw_event_source_identities(list(normalized))

        references: list[ForgetReference] = []
        cleanup_values: list[str] = []
        for event_id in normalized:
            references.extend(
                (
                    ForgetReference(event_id, "barrier", "exact_event", event_id),
                    ForgetReference(event_id, "cleanup", "exact_event", event_id),
                )
            )
            cleanup_values.append(event_id)
            identity = identities.get(event_id)
            if not identity:
                continue
            user_id = str(identity.get("user_id") or "").strip()
            session_id = str(identity.get("session_id") or "").strip()
            if user_id and session_id:
                references.append(
                    ForgetReference(
                        event_id,
                        "target",
                        "chat_projection",
                        _chat_projection_reference(
                            user_id=user_id,
                            session_id=session_id,
                        ),
                    )
                )
            for business_ref in business_source_references(
                source=str(identity.get("source") or ""),
                event_type=str(identity.get("event_type") or ""),
                source_item_id=identity.get("source_item_id"),
                idempotency_key=identity.get("idempotency_key"),
                include_source_item=block_source_item,
            ):
                references.append(
                    ForgetReference(
                        event_id,
                        "barrier",
                        _business_reference_type(business_ref),
                        business_ref,
                    )
                )
            if include_turn_references:
                turn_id = str(identity.get("turn_id") or "").strip()
                if turn_id:
                    cleanup_values.append(turn_id)
                    references.append(ForgetReference(event_id, "cleanup", "turn", turn_id))

        audit_event_ids = await self._correction_audit_event_ids(cleanup_values)
        owner_event_id = normalized[0]
        for audit_event_id in audit_event_ids:
            references.extend(
                (
                    ForgetReference(
                        owner_event_id,
                        "barrier",
                        "audit_event",
                        audit_event_id,
                    ),
                    ForgetReference(
                        owner_event_id,
                        "cleanup",
                        "audit_event",
                        audit_event_id,
                    ),
                )
            )
        return _dedupe_references(references)

    async def _correction_audit_event_ids(
        self,
        source_references: Iterable[str],
    ) -> tuple[str, ...]:
        normalized = normalize_source_event_ids(source_references)
        if not normalized:
            return ()
        placeholders = ", ".join("?" for _ in normalized)
        args = (*normalized, *normalized)
        async with sqlite_connection_async(self._memory_db_path) as db:
            async with db.execute(
                f"""
                SELECT DISTINCT corrections.audit_event_id
                FROM memory_corrections AS corrections
                WHERE TRIM(COALESCE(corrections.audit_event_id, '')) != ''
                  AND (
                        corrections.source_event_id IN ({placeholders})
                        OR EXISTS (
                            SELECT 1
                            FROM memory_claim_evidence_events AS evidence
                            WHERE evidence.target_kind = corrections.target_kind
                              AND evidence.claim_fingerprint = corrections.claim_fingerprint
                              AND evidence.event_id IN ({placeholders})
                        )
                  )
                ORDER BY corrections.audit_event_id
                """,
                args,
            ) as cursor:
                rows = await cursor.fetchall()
        return normalize_source_event_ids(str(row[0]) for row in rows)


def _business_reference_type(value: str) -> ReferenceType:
    if value.startswith(_SOURCE_ITEM_PREFIX):
        return "source_item"
    if value.startswith(_IDEMPOTENCY_PREFIX):
        return "idempotency"
    raise ValueError("Unknown business source reference type")


def _chat_projection_reference(*, user_id: str, session_id: str) -> str:
    return json.dumps(
        [str(user_id).strip(), str(session_id).strip()],
        ensure_ascii=False,
        separators=(",", ":"),
    )


def _dedupe_references(
    references: Iterable[ForgetReference],
) -> tuple[ForgetReference, ...]:
    unique: dict[tuple[str, str, str, str], ForgetReference] = {}
    for reference in references:
        key = (
            reference.item_event_id,
            reference.role,
            reference.ref_type,
            reference.value,
        )
        unique.setdefault(key, reference)
    return tuple(unique.values())


__all__ = ["ForgetReferenceBuilder"]
