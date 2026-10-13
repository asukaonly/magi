"""Persistence-neutral contracts for accepted conversation understanding."""

from dataclasses import dataclass
from typing import Any, Protocol


@dataclass(frozen=True, slots=True)
class PostTurnBatchLease:
    batch_id: str
    token: str
    outcome_ids: tuple[str, ...]
    attempt_count: int
    analysis: dict[str, Any] | None
    settled: frozenset[str]
    persona_id: str


class PostTurnLeaseLost(RuntimeError):
    """Durable post-turn ownership ended during analysis or settlement."""


class PostTurnOutbox(Protocol):
    """The source owner provides durable admission, leases, and effect settlement."""

    async def list_ready_post_turn_outcomes(self) -> list[dict[str, Any]]: ...
    async def claim_post_turn_batch(self, outcome_ids: tuple[str, ...], *, lease_seconds: float = 300) -> PostTurnBatchLease | None: ...
    async def ensure_post_turn_lease(self, lease: PostTurnBatchLease) -> None: ...
    async def save_post_turn_analysis(self, lease: PostTurnBatchLease, analysis: dict[str, Any]) -> None: ...
    async def replace_post_turn_attention(self, lease: PostTurnBatchLease, analysis: dict[str, Any]) -> None: ...
    async def settle_post_turn_effect(self, lease: PostTurnBatchLease, effect: str) -> None: ...
    async def finish_post_turn_batch(self, lease: PostTurnBatchLease, *, error: str | None = None) -> bool: ...
    async def cancel_post_turn_outcomes(self, *, session_id: str, turn_ids: tuple[str, ...] = (), cutoff_at: float | None = None) -> int: ...
    async def post_turn_status(self) -> dict[str, Any]: ...
    async def retry_failed_post_turn_batches(self, *, limit: int = 100) -> int: ...
