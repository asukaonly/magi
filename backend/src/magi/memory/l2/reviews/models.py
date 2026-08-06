"""Typed contracts for pre-materialization memory reviews."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal, Mapping

PendingReviewKind = Literal[
    "goal_currentness",
    "assertion_currentness",
    "materialization",
    "conflict",
]
PendingReviewAction = Literal["confirm", "reject", "confirm_with_edit"]


@dataclass(frozen=True, slots=True)
class PendingReviewProposal:
    """Host-owned proposed meaning for one unresolved Claim group."""

    subject_id: str
    kind: PendingReviewKind
    slot_key: str
    value_fingerprint: str
    semantic_lineage_key: str
    claim_ids: tuple[str, ...]
    reason_code: str
    proposed: Mapping[str, Any]
    route_contract_version: int
    evidence_rule_version: int


@dataclass(frozen=True, slots=True)
class PendingReviewWriteResult:
    """Result of an idempotent pending-review materialization."""

    review_id: str
    status: str
    version: int
    created: bool
    changed: bool
    atomically_completed_claim_ids: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class PendingReviewResolution:
    """Committed user decision for one pending review."""

    review_id: str
    status: str
    version: int
    assertion_id: str | None


__all__ = [
    "PendingReviewAction",
    "PendingReviewKind",
    "PendingReviewProposal",
    "PendingReviewResolution",
    "PendingReviewWriteResult",
]
