"""Atomic on-connection writes for Claim target projection outcomes."""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Any, Mapping

import aiosqlite

from .identity import canonical_json, projection_outcome_id


def _required_text(value: Any, *, field_name: str) -> str:
    text = str(value or "").strip()
    if not text:
        raise ValueError(f"{field_name} must not be blank")
    return text


def _optional_text(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


@dataclass(frozen=True, slots=True)
class ClaimTargetOutcomeContext:
    """Attempt identity shared by one atomic target-and-outcome write."""

    claim_ids: tuple[str, ...]
    attempt_key: str
    route_contract_version: int

    def __post_init__(self) -> None:
        normalized_claim_ids = tuple(
            dict.fromkeys(
                _required_text(claim_id, field_name="claim_id") for claim_id in self.claim_ids
            )
        )
        if not normalized_claim_ids:
            raise ValueError("claim_ids must not be empty")
        object.__setattr__(self, "claim_ids", normalized_claim_ids)
        object.__setattr__(
            self,
            "attempt_key",
            _required_text(self.attempt_key, field_name="attempt_key"),
        )
        object.__setattr__(
            self,
            "route_contract_version",
            max(0, int(self.route_contract_version)),
        )

    @classmethod
    def for_claim(
        cls,
        *,
        claim_id: str,
        attempt_key: str,
        route_contract_version: int,
    ) -> "ClaimTargetOutcomeContext":
        """Build a context for a target backed by exactly one Claim."""

        return cls(
            claim_ids=(claim_id,),
            attempt_key=attempt_key,
            route_contract_version=route_contract_version,
        )


async def append_claim_target_outcomes_on_connection(
    db: aiosqlite.Connection,
    *,
    context: ClaimTargetOutcomeContext,
    target_kind: str,
    target_id: str,
    target_slot_key: str | None,
    outcome: str,
    reason_code: str | None = None,
    details: Mapping[str, Any] | None = None,
    created_at: float | None = None,
) -> tuple[str, ...]:
    """Append target outcomes without owning or committing the caller's transaction.

    The caller must establish and fence a ``BEGIN IMMEDIATE`` transaction before
    mutating the target. Any error raised here therefore rolls the target mutation
    back with the outcome write.
    """

    normalized_target_kind = _required_text(target_kind, field_name="target_kind")
    normalized_target_id = _required_text(target_id, field_name="target_id")
    normalized_outcome = _required_text(outcome, field_name="outcome")
    normalized_slot_key = _optional_text(target_slot_key)
    normalized_reason_code = _optional_text(reason_code)
    details_json = None if details is None else canonical_json(details)
    write_time = float(created_at if created_at is not None else time.time())
    outcome_ids: list[str] = []

    for claim_id in context.claim_ids:
        async with db.execute(
            """
            SELECT 1 FROM l2_grounded_claims
            WHERE claim_id = ? AND availability = 'active'
            """,
            (claim_id,),
        ) as claim_cursor:
            if await claim_cursor.fetchone() is None:
                raise RuntimeError("active grounded Claim did not accept a target outcome")
        outcome_id = projection_outcome_id(
            claim_id=claim_id,
            attempt_key=context.attempt_key,
            target_kind=normalized_target_kind,
            target_id=normalized_target_id,
        )
        cursor = await db.execute(
            """
            INSERT OR IGNORE INTO l2_claim_projection_outcomes(
                outcome_id, claim_id, attempt_key, target_kind, target_id,
                target_slot_key, route_contract_version, outcome,
                reason_code, details_json, created_at
            )
            SELECT ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?
            WHERE EXISTS (
                SELECT 1 FROM l2_grounded_claims
                WHERE claim_id = ? AND availability = 'active'
            )
            """,
            (
                outcome_id,
                claim_id,
                context.attempt_key,
                normalized_target_kind,
                normalized_target_id,
                normalized_slot_key,
                context.route_contract_version,
                normalized_outcome,
                normalized_reason_code,
                details_json,
                write_time,
                claim_id,
            ),
        )
        if not cursor.rowcount:
            async with db.execute(
                """
                SELECT claim_id, attempt_key, target_kind, target_id,
                       target_slot_key, route_contract_version, outcome,
                       reason_code, details_json
                FROM l2_claim_projection_outcomes
                WHERE outcome_id = ?
                """,
                (outcome_id,),
            ) as existing_cursor:
                existing = await existing_cursor.fetchone()
            if existing is None:
                raise RuntimeError("active grounded Claim did not accept a target outcome")
            expected = (
                claim_id,
                context.attempt_key,
                normalized_target_kind,
                normalized_target_id,
                normalized_slot_key,
                context.route_contract_version,
                normalized_outcome,
                normalized_reason_code,
                details_json,
            )
            stored = tuple(existing[index] for index in range(len(expected)))
            if stored != expected:
                raise RuntimeError("claim_projection_outcome_conflict")
        outcome_ids.append(outcome_id)

    return tuple(outcome_ids)


__all__ = [
    "ClaimTargetOutcomeContext",
    "append_claim_target_outcomes_on_connection",
]
