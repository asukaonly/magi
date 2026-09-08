"""Read a consistent identity preview, including evidence and governance state."""

from __future__ import annotations

import hashlib
import json
from typing import Any

import aiosqlite

from ..entity_types import EXTRACTABLE_ENTITY_TYPES
from .catalog import _active_source_event_ids
from .governance_models import (
    EntityChangeCommand,
    EntityChangeImpact,
    EntityChangePreview,
    IdentityEntity,
)
from .identity_repository import current_catalog_entity


class EntityIdentityConflictError(ValueError):
    """The preview or selected review no longer describes the current identity."""


class EntityIdentityNotFoundError(ValueError):
    """One requested identity or evidence-backed proposal is unavailable."""


def fingerprint(value: Any) -> str:
    return hashlib.sha256(
        json.dumps(
            value, sort_keys=True, ensure_ascii=False, separators=(",", ":"), default=str
        ).encode()
    ).hexdigest()


async def query_rows(
    db: aiosqlite.Connection, sql: str, args: tuple[Any, ...] = ()
) -> list[dict[str, Any]]:
    db.row_factory = aiosqlite.Row
    async with db.execute(sql, args) as cursor:
        return [dict(row) for row in await cursor.fetchall()]


async def active_type_review(db: aiosqlite.Connection, review_id: str) -> dict[str, Any]:
    rows = await query_rows(
        db,
        "SELECT * FROM entity_identity_reviews WHERE review_id = ? AND status = 'pending'",
        (review_id,),
    )
    if not rows:
        raise EntityIdentityNotFoundError("Entity type review is unavailable")
    review = rows[0]
    entity = await current_catalog_entity(db, str(review["entity_id"]))
    if entity is None or entity["entity_type"] == review["proposed_type"]:
        raise EntityIdentityNotFoundError("Entity type review is no longer applicable")
    evidence = await _active_source_event_ids(
        db,
        json.loads(review["evidence_event_ids"]),
        target_entity_id=str(entity["entity_id"]),
        normalized_surface=str(entity["canonical_name"]).casefold(),
        entity_type=str(entity["entity_type"]),
        promote_candidates=False,
    )
    if not evidence:
        raise EntityIdentityNotFoundError("Entity type review has no available evidence")
    return {**review, "evidence_event_ids": list(evidence), "entity": entity}


async def identity_preview(
    db: aiosqlite.Connection, command: EntityChangeCommand
) -> tuple[EntityChangePreview, dict[str, Any]]:
    """Hash the actual affected state, including correction and deletion barriers."""
    entities: list[dict[str, Any]] = []
    for entity_id in (command.entity_id, command.target_entity_id):
        if not entity_id:
            continue
        entity = await current_catalog_entity(db, entity_id)
        if entity is None:
            raise EntityIdentityNotFoundError("Entity is unavailable")
        if entity["entity_id"] != entity_id:
            raise EntityIdentityConflictError("Entity identity has changed; refresh the selection")
        if entity_id.startswith("user:") or entity["entity_type"] not in EXTRACTABLE_ENTITY_TYPES:
            raise EntityIdentityConflictError(
                "Reserved source and user identities cannot be changed here"
            )
        entities.append(entity)
    if command.kind == "type_correction" and entities[0]["entity_type"] == command.new_type:
        raise EntityIdentityConflictError("Entity already has the requested type")
    review = await active_type_review(db, command.review_id) if command.review_id else None
    if review and (
        review["entity_id"] != command.entity_id or review["proposed_type"] != command.new_type
    ):
        raise EntityIdentityConflictError("Review does not match the requested classification")
    ids = tuple(str(entity["entity_id"]) for entity in entities)
    placeholders = ",".join("?" for _ in ids)
    state: dict[str, Any] = {
        "command": command.model_dump(),
        "entities": entities,
        "review": review,
    }
    for name, table, where, args in (
        (
            "relationships",
            "knowledge_graph",
            f"subject_id IN ({placeholders}) OR object_id IN ({placeholders})",
            ids + ids,
        ),
        (
            "assertions",
            "tom_trait_assertions",
            f"entity_id IN ({placeholders}) OR target_entity_id IN ({placeholders})",
            ids + ids,
        ),
        ("mentions", "entity_mentions", f"resolved_entity_id IN ({placeholders})", ids),
        ("refs", "l2_claim_entity_refs", f"entity_id IN ({placeholders})", ids),
        (
            "claims",
            "l2_grounded_claims",
            f"subject_ref IN ({placeholders}) OR claim_id IN (SELECT claim_id FROM l2_claim_entity_refs WHERE entity_id IN ({placeholders}))",
            ids + ids,
        ),
        ("aliases", "entity_aliases", f"entity_id IN ({placeholders})", ids),
        ("names", "entity_name_evidence", f"entity_id IN ({placeholders})", ids),
        ("source_bindings", "entity_source_bindings", f"entity_id IN ({placeholders})", ids),
        ("reviews", "entity_identity_reviews", f"entity_id IN ({placeholders})", ids),
    ):
        state[name] = await query_rows(
            db, f"SELECT * FROM {table} WHERE {where} ORDER BY rowid", args
        )
    state["entity_links"] = await query_rows(
        db,
        f"SELECT * FROM l2_event_entity_link_outbox WHERE EXISTS (SELECT 1 FROM json_each(desired_links_json) AS link WHERE json_extract(link.value, '$.entity_id') IN ({placeholders})) ORDER BY event_id, revision",
        ids,
    )
    target_ids = [row["triple_id"] for row in state["relationships"]] + [
        row["assertion_id"] for row in state["assertions"]
    ]
    targets_json = json.dumps(target_ids)
    state["corrections"] = await query_rows(
        db,
        "SELECT * FROM memory_corrections WHERE target_id IN (SELECT value FROM json_each(?)) OR replacement_target_id IN (SELECT value FROM json_each(?)) ORDER BY correction_id",
        (targets_json, targets_json),
    )
    # Governance can change independently from materialized rows. Hash the durable barrier ledger.
    for table in (
        "memory_projection_blocks",
        "memory_entity_projection_identity_blocks",
        "memory_correction_rules",
        "memory_correction_revert_blocks",
    ):
        state[table] = await query_rows(db, f"SELECT * FROM {table} ORDER BY rowid")
    subjects = sorted(
        set(ids)
        | {str(row["subject_id"]) for row in state["relationships"]}
        | {str(row["entity_id"]) for row in state["assertions"]}
    )
    state["subjects"] = subjects
    impact = EntityChangeImpact(
        **{
            key: len(state[key])
            for key in (
                "relationships",
                "assertions",
                "mentions",
                "claims",
                "corrections",
                "source_bindings",
            )
        },
        affected_subjects=len(subjects),
    )
    evidence_by_entity: dict[str, list[str]] = {}
    for entity in entities:
        entity_id = str(entity["entity_id"])
        mention_events = list(
            dict.fromkeys(
                str(event_id)
                for row in reversed(state["mentions"])
                if row["resolved_entity_id"] == entity_id
                for event_id in json.loads(row["evidence_event_ids"] or "[]")
            )
        )
        active_events = await _active_source_event_ids(
            db,
            mention_events,
            target_entity_id=entity_id,
            normalized_surface=str(entity["canonical_name"]).casefold(),
            entity_type=str(entity["entity_type"]),
            promote_candidates=False,
        )
        evidence_by_entity[entity_id] = list(active_events)[:3]
    return (
        EntityChangePreview(
            command=command,
            entity=IdentityEntity.model_validate(entities[0]),
            target=IdentityEntity.model_validate(entities[1]) if len(entities) > 1 else None,
            fingerprint=fingerprint(state),
            impact=impact,
            correction_history_may_block_revert=bool(state["corrections"]),
            evidence_event_ids=evidence_by_entity,
        ),
        state,
    )
