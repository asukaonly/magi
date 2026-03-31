"""Benchmark-facing reader that queries memory without chat rendering."""

from __future__ import annotations

import re
from typing import Any

from .contracts import EvalMemoryHit, EvalMemoryQuery, EvalMemoryQueryResult
from .trace import build_eval_query_result
from ..hybrid_retrieval import build_query

_STOP_WORDS = {
    "a",
    "an",
    "and",
    "after",
    "are",
    "as",
    "at",
    "be",
    "before",
    "did",
    "do",
    "does",
    "first",
    "for",
    "had",
    "have",
    "how",
    "i",
    "in",
    "is",
    "it",
    "last",
    "me",
    "my",
    "of",
    "on",
    "or",
    "the",
    "to",
    "was",
    "were",
    "what",
    "when",
    "where",
    "which",
    "who",
    "with",
}


class EvalMemoryReader:
    """Read memory through the retrieval layer using eval namespaces as scope."""

    def __init__(self, retrieval_service: Any, *, l1_store: Any | None = None) -> None:
        self._retrieval_service = retrieval_service
        self._l1_store = l1_store

    async def query_memory(self, query: EvalMemoryQuery) -> EvalMemoryQueryResult:
        if query.mode == "l1_only":
            return await self._query_l1_only(query)

        # Benchmark data uses fictional timestamps that don't align with the
        # current wall-clock time.  Supply an explicit wide time_range so the
        # intent-decider's rule engine does NOT parse temporal keywords like
        # "last month" relative to *now*.  Temporal reasoning is left to the
        # LLM working on retrieved evidence.
        time_range: dict = {}
        if query.query_timestamp:
            time_range = {"start": 0, "end": query.query_timestamp}

        request = build_query(
            query=query.query,
            user_id=query.namespace,
            session_id=None,
            time_range=time_range,
            query_mode=None if query.mode == "auto" else query.mode,
            source_filters=[],
            domain_filters=[],
            limit=query.top_k,
        )
        payload = await self._retrieval_service.query(request)
        return build_eval_query_result(payload)

    async def _query_l1_only(self, query: EvalMemoryQuery) -> EvalMemoryQueryResult:
        if self._l1_store is None:
            raise RuntimeError("L1 store is required for l1_only eval queries")

        candidate_limit = max(int(query.top_k) * 10, 50)
        events = await self._l1_store.query_events(
            user_id=query.namespace,
            limit=candidate_limit,
        )
        ranked_events = self._rank_l1_events(query=query.query, events=events)
        hits = [
            EvalMemoryHit(
                event_id=str(event.get("event_id") or ""),
                session_id=self._normalize_optional_text(event.get("session_id")),
                turn_id=self._normalize_optional_text(event.get("turn_id")),
                score=float(score),
                content=str(event.get("content") or ""),
                metadata={"retrieval_mode": "l1_only"},
            )
            for score, event in ranked_events[: query.top_k]
            if str(event.get("event_id") or "").strip()
        ]
        return EvalMemoryQueryResult(
            hits=hits,
            trace={
                "intent_source": "eval_l1_only",
                "query_mode": "l1_only",
                "candidate_count": len(events),
            },
        )

    def _rank_l1_events(self, *, query: str, events: list[dict[str, Any]]) -> list[tuple[float, dict[str, Any]]]:
        query_tokens = self._tokenize(query)
        ranked: list[tuple[float, dict[str, Any]]] = []
        fallback: list[tuple[float, dict[str, Any]]] = []
        for raw_event in events:
            event = self._normalize_event(raw_event)
            content = str(event.get("content") or "")
            content_lower = content.lower()
            timestamp = float(event.get("timestamp") or event.get("created_at") or 0.0)
            match_count = sum(1 for token in query_tokens if token in content_lower)
            if match_count > 0:
                ranked.append((float(match_count) * 1000.0 + timestamp, event))
            else:
                fallback.append((timestamp, event))
        ordered = sorted(ranked, key=lambda item: item[0], reverse=True)
        if ordered:
            return ordered
        return sorted(fallback, key=lambda item: item[0], reverse=True)

    @staticmethod
    def _tokenize(text: str) -> list[str]:
        tokens = re.findall(r"[a-zA-Z0-9_]+", str(text).lower())
        return [token for token in tokens if token and token not in _STOP_WORDS]

    @staticmethod
    def _normalize_optional_text(value: Any) -> str | None:
        text = str(value or "").strip()
        return text or None

    @staticmethod
    def _normalize_event(event: Any) -> dict[str, Any]:
        if isinstance(event, dict):
            return dict(event)
        if hasattr(event, "to_dict"):
            payload = event.to_dict()
            if isinstance(payload, dict):
                return dict(payload)
        if hasattr(event, "__dict__"):
            return dict(vars(event))
        raise TypeError(f"Unsupported L1 event shape for eval query: {type(event)!r}")
