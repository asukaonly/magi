"""Shared chat persistence contracts and value codecs."""

from dataclasses import dataclass
from typing import Any


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
