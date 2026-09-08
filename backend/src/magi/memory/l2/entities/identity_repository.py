"""Connection-scoped identity bindings and evidence-backed type proposals."""

from __future__ import annotations

import hashlib
import json
import time
from typing import Any, Iterable

import aiosqlite

from ..entity_types import ENTITY_TYPE_REGISTRY


def source_key_hash(key: str) -> str:
    return hashlib.sha256(key.encode("utf-8")).hexdigest()


async def current_catalog_entity(db: aiosqlite.Connection, entity_id: str) -> dict[str, Any] | None:
    """Follow durable redirects without reviving forgotten targets."""
    visited: set[str] = set()
    current = entity_id
    db.row_factory = aiosqlite.Row
    while current not in visited:
        visited.add(current)
        async with db.execute(
            "SELECT target_entity_id FROM entity_identity_redirects WHERE source_entity_id = ?",
            (current,),
        ) as cursor:
            redirect = await cursor.fetchone()
        if redirect is None:
            async with db.execute(
                "SELECT * FROM entity_catalog WHERE entity_id = ?", (current,)
            ) as cursor:
                row = await cursor.fetchone()
            return dict(row) if row is not None else None
        current = str(redirect[0])
    raise ValueError("Entity identity redirect cycle")


async def propose_entity_type(
    db: aiosqlite.Connection,
    *,
    entity_id: str,
    proposed_type: str,
    evidence_event_ids: Iterable[str],
    now: float | None = None,
) -> str | None:
    """Record a proposal without overriding classification or a user decision."""
    if not db.in_transaction:
        raise RuntimeError("Entity type proposals require an active transaction")
    row = await current_catalog_entity(db, entity_id)
    events = sorted(set(str(item) for item in evidence_event_ids if item))
    if (
        row is None
        or not events
        or proposed_type not in ENTITY_TYPE_REGISTRY
        or row["entity_type"] == proposed_type
    ):
        return None
    entity_id = str(row["entity_id"])
    review_id = hashlib.sha256(f"{entity_id}\n{proposed_type}".encode()).hexdigest()
    async with db.execute(
        "SELECT evidence_event_ids, status FROM entity_identity_reviews WHERE review_id = ?",
        (review_id,),
    ) as cursor:
        existing = await cursor.fetchone()
    if existing is not None:
        if existing["status"] != "pending":
            return review_id
        prior = json.loads(existing["evidence_event_ids"])
        combined = sorted(set(prior) | set(events))
        if combined != sorted(prior):
            await db.execute(
                "UPDATE entity_identity_reviews SET evidence_event_ids = ?, version = version + 1, updated_at = ? WHERE review_id = ?",
                (json.dumps(combined), now or time.time(), review_id),
            )
        return review_id
    timestamp = now or time.time()
    await db.execute(
        "INSERT INTO entity_identity_reviews(review_id, entity_id, proposed_type, evidence_event_ids, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?)",
        (review_id, entity_id, proposed_type, json.dumps(events), timestamp, timestamp),
    )
    return review_id
