"""Identity projection and correction-payload helpers for assertion rekeys."""

from __future__ import annotations

import json
from collections.abc import Mapping
from typing import Any, Literal, overload

import aiosqlite

from ..corrections.fingerprints import (
    assertion_claim_fingerprint,
    assertion_slot_key,
)


def _project_assertion_identity(
    row: Mapping[str, Any],
    *,
    source_entity_id: str,
    target_entity_id: str,
    resolved_entity_type: str | None,
) -> dict[str, str]:
    entity_changed = str(row["entity_id"]) == source_entity_id
    entity_id = target_entity_id if entity_changed else str(row["entity_id"])
    entity_type = (
        resolved_entity_type if entity_changed and resolved_entity_type else str(row["entity_type"])
    )
    current_target = str(row.get("target_entity_id") or "")
    target_changed = current_target == source_entity_id
    assertion_target = target_entity_id if target_changed else current_target
    target_type = (
        resolved_entity_type
        if target_changed and resolved_entity_type
        else str(row.get("target_entity_type") or "")
    )
    slot_key_value = assertion_slot_key(
        entity_type=entity_type,
        entity_id=entity_id,
        trait_name=str(row["trait_name"]),
        target_entity_id=assertion_target,
    )
    claim_fingerprint = assertion_claim_fingerprint(
        slot_key_value=slot_key_value,
        trait_value=row["trait_value"],
        scope_key_value=str(row.get("scope_key") or "global"),
    )
    return {
        "entity_id": entity_id,
        "entity_type": entity_type,
        "target_entity_id": assertion_target,
        "target_entity_type": target_type,
        "slot_key": slot_key_value,
        "claim_fingerprint": claim_fingerprint,
        "semantic_fingerprint": assertion_claim_fingerprint(
            slot_key_value=slot_key_value,
            trait_value=row["trait_value"],
        ),
    }


async def _load_catalog_entity_type(
    db: aiosqlite.Connection,
    entity_id: str,
) -> str | None:
    async with db.execute(
        "SELECT entity_type FROM entity_catalog WHERE entity_id = ?",
        (entity_id,),
    ) as cursor:
        row = await cursor.fetchone()
    if row is None:
        return None
    normalized = str(row[0] or "").strip()
    return normalized or None


@overload
def _decode_object(
    value: Any,
    correction_id: Any,
    *,
    allow_none: Literal[False] = False,
) -> dict[str, Any]: ...


@overload
def _decode_object(
    value: Any,
    correction_id: Any,
    *,
    allow_none: Literal[True],
) -> dict[str, Any] | None: ...


def _decode_object(
    value: Any,
    correction_id: Any,
    *,
    allow_none: bool = False,
) -> dict[str, Any] | None:
    if value is None and allow_none:
        return None
    try:
        parsed = json.loads(str(value))
    except (TypeError, ValueError, json.JSONDecodeError) as exc:
        raise ValueError(f"Correction payload is invalid: {correction_id}") from exc
    if not isinstance(parsed, dict):
        raise ValueError(f"Correction payload is not an object: {correction_id}")
    return parsed


def _encode_object(value: Mapping[str, Any]) -> str:
    return json.dumps(
        dict(value),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
