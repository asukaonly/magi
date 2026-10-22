"""Governed self-report inputs independent of the structured storage engine."""

from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from typing import Any, Protocol


@dataclass(frozen=True, slots=True)
class SelfReportEvidence:
    claim_id: str
    claim: Mapping[str, Any]
    route_outcome: Mapping[str, Any]
    event_ids: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class SelfReportEvidenceBatch:
    candidates: tuple[SelfReportEvidence, ...] = ()
    current_route_value_keys: frozenset[tuple[str, str]] = frozenset()
    visible_route_value_keys: frozenset[tuple[str, str]] = frozenset()


class SelfReportRepository(Protocol):
    async def load(
        self,
        *,
        user_id: str,
        current_assertion_ids: Iterable[str],
        visible_assertion_ids: Iterable[str],
        effective_at: float,
    ) -> SelfReportEvidenceBatch: ...

    async def latest_change_at(self, *, user_id: str) -> float: ...
