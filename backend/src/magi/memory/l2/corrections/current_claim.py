"""Resolve one coherent current claim after correction retries and reverts."""

from __future__ import annotations

import json
import time
from collections.abc import Mapping
from typing import Any

import aiosqlite

from ....core.sqlite import sqlite_connection_async
from ..assertions.state_machine import RETRIEVAL_EXCLUDED_STATUSES
from ..retrieval.common import (
    committed_situation_change_head_sql,
    matching_scope_keys,
    pending_situation_change_exists_sql,
    restore_committed_situation_change_heads,
)
from .fingerprints import scope_matches, scope_specificity, stored_context_scope
from .models import CorrectionKind, CorrectionState, CorrectionTargetKind

_CURRENT_ASSERTION_EXCLUDED_STATUSES = RETRIEVAL_EXCLUDED_STATUSES


async def resolve_current_claim(
    db_path: str,
    *,
    correction: Mapping[str, Any],
) -> dict[str, Any] | None:
    """Return the current descendant of one correction from a single read snapshot."""
    correction_id = str(correction["correction_id"])
    async with sqlite_connection_async(db_path) as db:
        db.row_factory = aiosqlite.Row
        await db.execute("BEGIN")
        try:
            root = await _correction_on_connection(
                db,
                correction_id=correction_id,
            )
            if root is None:
                await db.commit()
                return None
            as_of = time.time()
            target_kind = CorrectionTargetKind(str(root["target_kind"]))
            candidate = await _follow_lineage_on_connection(
                db,
                root=root,
                target_kind=target_kind,
            )
            if candidate is None:
                await db.commit()
                return None
            _, slot_key, context_scope = candidate
            if target_kind == CorrectionTargetKind.ASSERTION:
                current = await _current_assertion(
                    db,
                    slot_key=slot_key,
                    context_scope=context_scope,
                    effective_at=as_of,
                )
            else:
                current = await _current_relationship(
                    db,
                    slot_key=slot_key,
                    context_scope=context_scope,
                    effective_at=as_of,
                )
            await db.commit()
            return current
        except Exception:
            await db.rollback()
            raise


async def _correction_on_connection(
    db: aiosqlite.Connection,
    *,
    correction_id: str,
) -> dict[str, Any] | None:
    async with db.execute(
        """
        SELECT *
        FROM memory_corrections
        WHERE correction_id = ?
        """,
        (correction_id,),
    ) as cursor:
        row = await cursor.fetchone()
    return dict(row) if row is not None else None


async def _follow_lineage_on_connection(
    db: aiosqlite.Connection,
    *,
    root: dict[str, Any],
    target_kind: CorrectionTargetKind,
) -> tuple[str, str, dict[str, Any]] | None:
    current = root
    visited = {str(root["correction_id"])}
    while True:
        candidate = _correction_result_candidate(current)
        if candidate is None:
            return None
        record_id, slot_key, context_scope = candidate
        async with db.execute(
            """
            SELECT *
            FROM memory_corrections
            WHERE target_kind = ?
              AND target_id = ?
              AND (
                  created_at > ?
                  OR (created_at = ? AND correction_id > ?)
              )
            ORDER BY created_at, correction_id
            LIMIT 1
            """,
            (
                target_kind.value,
                record_id,
                float(current["created_at"]),
                float(current["created_at"]),
                str(current["correction_id"]),
            ),
        ) as cursor:
            row = await cursor.fetchone()
        if row is None:
            return record_id, slot_key, context_scope
        next_correction = dict(row)
        next_correction_id = str(next_correction["correction_id"])
        if next_correction_id in visited:
            return record_id, slot_key, context_scope
        visited.add(next_correction_id)
        current = next_correction


def _correction_result_candidate(
    correction: Mapping[str, Any],
) -> tuple[str, str, dict[str, Any]] | None:
    before = _decode_object(correction.get("before_json", correction.get("before")))
    replacement = _decode_optional_object(
        correction.get("replacement_json", correction.get("replacement"))
    )
    state = CorrectionState(getattr(correction["state"], "value", correction["state"]))
    correction_kind = CorrectionKind(
        getattr(correction["correction_kind"], "value", correction["correction_kind"])
    )
    transition_cancelled_at = correction.get("transition_cancelled_at")
    transition_applied_at = correction.get("transition_applied_at")
    uses_before = state == CorrectionState.REVERTED or (
        transition_cancelled_at is not None and transition_applied_at is None
    )
    if correction_kind == CorrectionKind.SITUATION_CHANGED and transition_applied_at is None:
        uses_before = True
    if uses_before:
        return (
            str(correction["target_id"]),
            str(before.get("slot_key") or correction["slot_key"]),
            stored_context_scope(before),
        )
    if replacement is None or not correction.get("replacement_target_id"):
        return (
            str(correction["target_id"]),
            str(before.get("slot_key") or correction["slot_key"]),
            stored_context_scope(before),
        )
    replacement_scope = stored_context_scope(replacement)
    if not replacement_scope:
        raw_scope = correction.get("scope_json", correction.get("scope"))
        replacement_scope = _decode_scope(raw_scope)
    return (
        str(correction["replacement_target_id"]),
        str(replacement.get("slot_key") or correction["slot_key"]),
        replacement_scope,
    )


async def _current_assertion(
    db: aiosqlite.Connection,
    *,
    slot_key: str,
    context_scope: Mapping[str, Any],
    effective_at: float,
) -> dict[str, Any] | None:
    return await _current_assertion_for_slot(
        db,
        slot_key=slot_key,
        context_scope=context_scope,
        effective_at=effective_at,
    )


async def _current_assertion_for_slot(
    db: aiosqlite.Connection,
    *,
    slot_key: str,
    context_scope: Mapping[str, Any],
    effective_at: float,
) -> dict[str, Any] | None:
    eligible_scope_keys = matching_scope_keys(context_scope)
    scope_placeholders = ", ".join("?" for _ in eligible_scope_keys)
    status_placeholders = ", ".join("?" for _ in _CURRENT_ASSERTION_EXCLUDED_STATUSES)
    committed_head = committed_situation_change_head_sql(
        target_kind="assertion",
        row_id_sql="tom_trait_assertions.assertion_id",
        authority_ref_sql="tom_trait_assertions.authority_ref",
    )
    pending_replacement = pending_situation_change_exists_sql(
        target_kind="assertion",
        row_id_sql="tom_trait_assertions.assertion_id",
        identity_column="replacement_target_id",
        authority_ref_sql="tom_trait_assertions.authority_ref",
    )
    async with db.execute(
        f"""
        SELECT *
        FROM tom_trait_assertions
        WHERE slot_key = ?
          AND status NOT IN ({status_placeholders})
          AND (status != 'superseded' OR valid_to IS NOT NULL)
          AND (
              {committed_head}
              OR (
                  (valid_from IS NULL OR valid_from <= ?)
                  AND NOT ({pending_replacement})
                  AND (valid_to IS NULL OR valid_to > ?)
              )
          )
          AND COALESCE(authority_ref, '') NOT LIKE 'forget:%'
          AND scope_key IN ({scope_placeholders})
        ORDER BY json_array_length(scope_json, '$.all_of') DESC,
                 updated_at DESC, assertion_id DESC
        """,
        (
            slot_key,
            *_CURRENT_ASSERTION_EXCLUDED_STATUSES,
            effective_at,
            effective_at,
            *eligible_scope_keys,
        ),
    ) as cursor:
        rows = await cursor.fetchall()
    rows = await restore_committed_situation_change_heads(
        db,
        target_kind="assertion",
        rows=rows,
        identity_field="assertion_id",
    )
    rows = [
        row
        for row in rows
        if row.get("expires_at") is None or float(row["expires_at"]) > effective_at
    ]
    return _first_scope_match(rows, context_scope)


async def _current_relationship(
    db: aiosqlite.Connection,
    *,
    slot_key: str,
    context_scope: Mapping[str, Any],
    effective_at: float,
) -> dict[str, Any] | None:
    return await _current_relationship_for_slot(
        db,
        slot_key=slot_key,
        context_scope=context_scope,
        effective_at=effective_at,
    )


async def _current_relationship_for_slot(
    db: aiosqlite.Connection,
    *,
    slot_key: str,
    context_scope: Mapping[str, Any],
    effective_at: float,
) -> dict[str, Any] | None:
    eligible_scope_keys = matching_scope_keys(context_scope)
    scope_placeholders = ", ".join("?" for _ in eligible_scope_keys)
    committed_head = committed_situation_change_head_sql(
        target_kind="edge",
        row_id_sql="knowledge_graph.triple_id",
        authority_ref_sql="knowledge_graph.authority_ref",
    )
    pending_replacement = pending_situation_change_exists_sql(
        target_kind="edge",
        row_id_sql="knowledge_graph.triple_id",
        identity_column="replacement_target_id",
        authority_ref_sql="knowledge_graph.authority_ref",
    )
    async with db.execute(
        f"""
        SELECT *
        FROM knowledge_graph
        WHERE slot_key = ?
          AND status IN ('active', 'deprecated')
          AND (status != 'deprecated' OR valid_to IS NOT NULL)
          AND (
              {committed_head}
              OR (
                  (valid_from IS NULL OR valid_from <= ?)
                  AND NOT ({pending_replacement})
                  AND (valid_to IS NULL OR valid_to > ?)
              )
          )
          AND COALESCE(authority_ref, '') NOT LIKE 'forget:%'
          AND COALESCE(status_reason, '') != 'user_forget'
          AND scope_key IN ({scope_placeholders})
        ORDER BY json_array_length(scope_json, '$.all_of') DESC,
                 updated_at DESC, triple_id DESC
        """,
        (
            slot_key,
            effective_at,
            effective_at,
            *eligible_scope_keys,
        ),
    ) as cursor:
        rows = await cursor.fetchall()
    rows = await restore_committed_situation_change_heads(
        db,
        target_kind="edge",
        rows=rows,
        identity_field="triple_id",
    )
    rows = [
        row
        for row in rows
        if row.get("expires_at") is None or float(row["expires_at"]) > effective_at
    ]
    return _first_scope_match(rows, context_scope)


def _first_scope_match(
    rows: list[Mapping[str, Any]],
    context_scope: Mapping[str, Any],
) -> dict[str, Any] | None:
    ordered = sorted(
        rows,
        key=lambda row: (
            scope_specificity(_decode_scope(row["scope_json"])),
            float(row.get("updated_at") or 0.0),
        ),
        reverse=True,
    )
    for row in ordered:
        if scope_matches(_decode_scope(row["scope_json"]), context_scope):
            return dict(row)
    return None


def _decode_optional_object(value: Any) -> dict[str, Any] | None:
    if value in (None, ""):
        return None
    return _decode_object(value)


def _decode_object(value: Any) -> dict[str, Any]:
    if isinstance(value, Mapping):
        return dict(value)
    if value in (None, ""):
        return {}
    parsed = json.loads(str(value))
    if not isinstance(parsed, dict):
        raise ValueError("Stored correction payload is not an object")
    return parsed


def _decode_scope(value: Any) -> dict[str, Any]:
    if isinstance(value, Mapping):
        return dict(value)
    if value in (None, ""):
        return {}
    parsed = json.loads(str(value))
    if not isinstance(parsed, dict):
        raise ValueError("Stored correction scope is not an object")
    return parsed


__all__ = ["resolve_current_claim"]
