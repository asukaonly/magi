"""Current-source validation for L3 insight publication."""

from __future__ import annotations

import aiosqlite


class StaleL3CandidateError(RuntimeError):
    """Raised when an L3 candidate references evidence that is no longer current."""


async def ensure_l3_dependencies_current(
    db: aiosqlite.Connection,
    dependencies: list[tuple[str, str, str, int]],
    *,
    effective_at: float,
) -> None:
    """Validate referenced evidence in the same transaction as the L3 write."""
    assertions = await _dependency_rows(
        db,
        table="tom_trait_assertions",
        identity_column="assertion_id",
        identity_values=[
            source_id
            for source_kind, source_id, _subject_key, _revision in dependencies
            if source_kind == "assertion"
        ],
    )
    edges = await _dependency_rows(
        db,
        table="knowledge_graph",
        identity_column="triple_id",
        identity_values=[
            source_id
            for source_kind, source_id, _subject_key, _revision in dependencies
            if source_kind == "edge"
        ],
    )
    for source_kind, source_id, subject_key, _revision in dependencies:
        row = assertions.get(source_id) if source_kind == "assertion" else edges.get(source_id)
        if row is None:
            raise StaleL3CandidateError(f"Missing {source_kind} dependency {source_id}")
        if source_kind == "assertion":
            if str(row["entity_id"]) != subject_key or not _assertion_is_current(
                row,
                effective_at=effective_at,
            ):
                raise StaleL3CandidateError(
                    f"Assertion dependency {source_id} is no longer current"
                )
            continue
        if subject_key not in {str(row["subject_id"]), str(row["object_id"])}:
            raise StaleL3CandidateError(
                f"Edge dependency {source_id} does not belong to {subject_key}"
            )
        if not _edge_is_current(row, effective_at=effective_at):
            raise StaleL3CandidateError(f"Edge dependency {source_id} is no longer current")


async def _dependency_rows(
    db: aiosqlite.Connection,
    *,
    table: str,
    identity_column: str,
    identity_values: list[str],
) -> dict[str, aiosqlite.Row]:
    normalized = list(dict.fromkeys(identity_values))
    if not normalized:
        return {}
    placeholders = ", ".join("?" for _ in normalized)
    async with db.execute(
        f"SELECT * FROM {table} WHERE {identity_column} IN ({placeholders})",
        tuple(normalized),
    ) as cursor:
        rows = await cursor.fetchall()
    return {str(row[identity_column]): row for row in rows}


def _assertion_is_current(row: aiosqlite.Row, *, effective_at: float) -> bool:
    status = str(row["status"] or "").strip().lower()
    validation_state = str(row["validation_state"] or "").strip().lower()
    if status in {
        "archived",
        "expired",
        "invalidated",
        "shadow",
        "superseded",
        "user_rejected",
    } or validation_state in {"expired", "user_rejected"}:
        return False
    return _valid_at(row, effective_at=effective_at)


def _edge_is_current(row: aiosqlite.Row, *, effective_at: float) -> bool:
    status = str(row["status"] or "").strip().lower()
    if status not in {"active", "deprecated"}:
        return False
    if status == "deprecated" and row["valid_to"] is None:
        return False
    return _valid_at(row, effective_at=effective_at)


def _valid_at(row: aiosqlite.Row, *, effective_at: float) -> bool:
    valid_from = row["valid_from"]
    valid_to = row["valid_to"]
    expires_at = row["expires_at"]
    return (
        (valid_from is None or float(valid_from) <= effective_at)
        and (valid_to is None or float(valid_to) > effective_at)
        and (expires_at is None or float(expires_at) > effective_at)
    )


__all__ = ["StaleL3CandidateError", "ensure_l3_dependencies_current"]
