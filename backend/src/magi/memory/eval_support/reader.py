"""Benchmark-facing reader that queries memory without chat rendering."""

from __future__ import annotations

import logging
import re
from datetime import datetime, timezone
from typing import Any

from ...utils.diagnostic_logging import full_content_logging_enabled
from .contracts import EvalMemoryHit, EvalMemoryQuery, EvalMemoryQueryResult
from .trace import build_eval_query_result
from ..hybrid_retrieval import build_query

logger = logging.getLogger(__name__)

# Padding (seconds) added before the earliest resolved temporal anchor
# so the hard time-range filter does not accidentally exclude nearby events.
_TEMPORAL_PADDING_SECS = 7 * 86_400  # 7 days

# Regex matching month-level temporal expressions (e.g. "in January",
# "last month", "during February 2023").  When the dateparser match text
# corresponds to an entire month the padding is expanded to cover the
# full calendar month instead of the default 7-day window.
_MONTH_LEVEL_RE = re.compile(
    r"(?:in|during)\s+"
    r"(?:January|February|March|April|May|June|July|August|September|October|November|December)"
    r"(?:\s+\d{4})?"
    r"|last\s+month",
    re.IGNORECASE,
)

# Regex to strip a leading preposition that `search_dates` may have
# greedily absorbed into the matched span, e.g. "in a week ago" where
# "in" belongs to the verb phrase ("participated in") not the temporal
# expression ("a week ago").
_LEADING_PREP_RE = re.compile(r"^(?:in|at|on|for|from)\s+", re.IGNORECASE)


def _temporal_search_settings(query_timestamp: float) -> dict:
    reference_dt = datetime.fromtimestamp(query_timestamp, tz=timezone.utc)
    return {
        "RELATIVE_BASE": reference_dt.replace(tzinfo=None),
        "PREFER_DATES_FROM": "past",
    }


def _search_temporal_dates(query: str, settings: dict) -> list[tuple[str, Any]] | None:
    try:
        from dateparser.search import search_dates
    except ImportError:
        return None

    try:
        return search_dates(query, settings=settings, languages=["en"])
    except Exception:
        logger.debug(
            "dateparser.search_dates failed for query=%r",
            query if full_content_logging_enabled() else "[content omitted]",
        )
        return None


def _past_resolved_timestamps(
    results: list[tuple[str, Any]],
    query_timestamp: float,
) -> list[float]:
    resolved: list[float] = []
    for _matched_text, resolved_dt in results:
        ts = resolved_dt.replace(tzinfo=timezone.utc).timestamp()
        if ts <= query_timestamp:
            resolved.append(ts)
    return resolved


def _reparse_with_stripped_preposition(
    results: list[tuple[str, Any]],
    settings: dict,
    query_timestamp: float,
) -> list[float]:
    """Re-parse matched texts after stripping a leading preposition.

    ``dateparser.search.search_dates`` sometimes captures a preceding
    preposition as part of the temporal span (e.g. *"in a week ago"*
    instead of *"a week ago"*), causing a future-directed parse.  This
    helper strips the preposition and retries ``dateparser.parse``.
    """
    import dateparser

    resolved: list[float] = []
    for matched_text, _ in results:
        stripped = _LEADING_PREP_RE.sub("", matched_text)
        if stripped == matched_text:
            continue
        retry_dt = dateparser.parse(stripped, settings=settings)
        if retry_dt is None:
            continue
        ts = retry_dt.replace(tzinfo=timezone.utc).timestamp()
        if ts <= query_timestamp:
            resolved.append(ts)
            logger.debug(
                "Temporal reparse succeeded: %r → %r → %s",
                matched_text,
                stripped,
                retry_dt,
            )
    return resolved


def _is_month_level_match(results: list[tuple[str, Any]]) -> bool:
    return all(_MONTH_LEVEL_RE.search(matched_text) for matched_text, _ in results)


def _temporal_range_start(earliest: float, *, is_month_level: bool) -> float:
    if is_month_level:
        earliest_dt = datetime.fromtimestamp(earliest, tz=timezone.utc)
        month_start = earliest_dt.replace(
            day=1,
            hour=0,
            minute=0,
            second=0,
            microsecond=0,
        )
        return max(0, month_start.timestamp())
    return max(0, earliest - _TEMPORAL_PADDING_SECS)


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

        # Resolve relative time phrases (e.g. "last Friday", "two weeks ago")
        # against query_timestamp so the retrieval layer can narrow its search
        # window instead of scanning all events.
        time_range: dict = {}
        if query.query_timestamp:
            time_range = self._resolve_temporal_range(
                query.query,
                query.query_timestamp,
            )

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

    # ------------------------------------------------------------------
    # Temporal range resolution
    # ------------------------------------------------------------------

    @staticmethod
    def _resolve_temporal_range(query: str, query_timestamp: float) -> dict:
        """Resolve relative time phrases in *query* against *query_timestamp*.

        Uses ``dateparser.search`` to detect temporal expressions (e.g.
        "last Friday", "two weeks ago") and anchors them to the
        *query_timestamp* instead of wall-clock *now*.

        When a temporal expression is found the returned range is narrowed to
        ``[earliest_resolved - padding, ∞)``.  The end is left open so
        that events whose replay-assigned timestamps slightly exceed
        *query_timestamp* are not inadvertently excluded (the BM25 /
        vector paths already handle relevance scoring).
        Otherwise falls back to a start-only range so events whose
        replay-assigned timestamps slightly exceed ``query_timestamp``
        are not inadvertently excluded.
        """
        wide: dict = {"start": 0}
        settings = _temporal_search_settings(query_timestamp)
        results = _search_temporal_dates(query, settings)

        if not results:
            return wide

        resolved = _past_resolved_timestamps(results, query_timestamp)
        if not resolved:
            # Fallback: search_dates may mismatch spans (e.g. "in a week
            # ago" parsed as "in a week" → future).  Re-parse each matched
            # text after stripping a leading preposition.
            resolved = _reparse_with_stripped_preposition(
                results,
                settings,
                query_timestamp,
            )

        if not resolved:
            return wide

        earliest = min(resolved)
        is_month_level = _is_month_level_match(results)
        start = _temporal_range_start(earliest, is_month_level=is_month_level)

        logger.debug(
            "Temporal range narrowed query=%r earliest=%s start=%s" " month_level=%s",
            (
                query
                if full_content_logging_enabled()
                else f"[content omitted; {len(query)} chars]"
            ),
            earliest,
            start,
            is_month_level,
        )
        return {"start": start}

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

    def _rank_l1_events(
        self, *, query: str, events: list[dict[str, Any]]
    ) -> list[tuple[float, dict[str, Any]]]:
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
