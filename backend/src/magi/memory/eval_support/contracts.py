"""Benchmark-agnostic contracts for memory evaluation support."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(slots=True)
class EvalMemoryWriteRecord:
    """Normalized replay record for writing benchmark data into memory."""

    namespace: str
    session_id: str
    timestamp: float
    role: str
    content: str
    turn_id: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class EvalMemoryQuery:
    """Benchmark-facing memory query contract."""

    namespace: str
    query: str
    query_timestamp: float | None = None
    top_k: int = 10
    mode: str = "auto"
    answer_with_llm: bool = False


@dataclass(slots=True)
class EvalMemoryHit:
    """Normalized retrieval hit returned by eval support."""

    event_id: str
    session_id: str | None
    turn_id: str | None
    score: float | None
    content: str
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class EvalMemoryQueryResult:
    """Normalized query result plus retrieval-trace identifiers."""

    hits: list[EvalMemoryHit] = field(default_factory=list)
    trace: dict[str, Any] = field(default_factory=dict)
    answer: str | None = None
    answer_trace: dict[str, Any] = field(default_factory=dict)
    retrieved_session_ids: list[str] = field(init=False)
    retrieved_turn_ids: list[str] = field(init=False)
    retrieved_event_ids: list[str] = field(init=False)

    def __post_init__(self) -> None:
        self.retrieved_session_ids = self._dedupe(hit.session_id for hit in self.hits)
        self.retrieved_turn_ids = self._dedupe(hit.turn_id for hit in self.hits)
        self.retrieved_event_ids = self._dedupe(hit.event_id for hit in self.hits)

    @staticmethod
    def _dedupe(values: Any) -> list[str]:
        deduped: list[str] = []
        for value in values:
            if value is None:
                continue
            text = str(value).strip()
            if not text or text in deduped:
                continue
            deduped.append(text)
        return deduped
