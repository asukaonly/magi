"""Session-local evidence bundle assembly for L1 retrieval hits."""

from __future__ import annotations

import asyncio
import logging
from typing import Any, Dict, List

from ..service_policy import bundle_neighbor_window, hit_score, parse_turn_number

logger = logging.getLogger(__name__)

# Over-fetch factor for session event loading in evidence bundles.
# Loads N× the hit count per session so neighbor-turn expansion has
# enough context without fetching the entire session.
_SESSION_EVENTS_OVER_FETCH = 8


class EvidenceBundleMixin:
    """Build grouped L1 evidence bundles with session-local neighbors."""

    _memory: Any
    _config: Any

    async def _build_l1_evidence_bundles(
        self,
        hits: List[Dict[str, Any]],
        *,
        query: str = "",
    ) -> List[Dict[str, Any]]:
        """Group L1 hits into session-local evidence bundles with lightweight neighbors."""
        if not hits or getattr(self._memory, "l1", None) is None:
            return []

        grouped_hits: Dict[str, List[Dict[str, Any]]] = {}
        for hit in hits:
            session_id = str(hit.get("session_id") or "").strip()
            if not session_id:
                continue
            grouped_hits.setdefault(session_id, []).append(hit)

        min_score = self._config.evidence_bundle_min_score
        max_bundles = self._config.evidence_bundle_max_count
        session_best_score: Dict[str, float] = {}
        for session_id, session_hits in grouped_hits.items():
            best = max(
                (self._hit_score(hit) for hit in session_hits),
                default=0.0,
            )
            session_best_score[session_id] = best

        qualified_ids = [
            session_id
            for session_id, score in session_best_score.items()
            if score >= min_score
        ]
        qualified_ids.sort(key=lambda session_id: session_best_score[session_id], reverse=True)
        if max_bundles > 0:
            qualified_ids = qualified_ids[:max_bundles]

        if not qualified_ids:
            return []

        neighbor_window = self._bundle_neighbor_window(query)
        bundles: List[Dict[str, Any]] = []

        session_ids = qualified_ids
        session_limits = [
            max(len(grouped_hits[session_id]) * _SESSION_EVENTS_OVER_FETCH, 24)
            for session_id in session_ids
        ]
        session_events_list = await asyncio.gather(
            *(
                self._load_session_events(
                    session_id,
                    session_hits=grouped_hits[session_id],
                    neighbor_window=neighbor_window,
                    limit=limit,
                )
                for session_id, limit in zip(session_ids, session_limits)
            ),
        )

        for session_id, session_events in zip(session_ids, session_events_list):
            session_hits = grouped_hits[session_id]
            bundle_events, neighbor_expansion_applied = self._select_bundle_events(
                session_events=session_events,
                session_hits=session_hits,
                neighbor_window=neighbor_window,
            )
            bundles.append(
                {
                    "session_id": session_id,
                    "session_best_score": session_best_score[session_id],
                    "hit_event_ids": [
                        str(hit.get("event_id") or "")
                        for hit in session_hits
                        if hit.get("event_id")
                    ],
                    "hit_turn_ids": [
                        str(hit.get("turn_id") or "")
                        for hit in session_hits
                        if hit.get("turn_id")
                    ],
                    "events": bundle_events,
                    "neighbor_expansion_applied": neighbor_expansion_applied,
                }
            )

        bundles.sort(key=lambda bundle: bundle.get("session_best_score", 0.0), reverse=True)
        return bundles

    async def _load_session_events(
        self,
        session_id: str,
        *,
        session_hits: List[Dict[str, Any]],
        neighbor_window: int,
        limit: int,
    ) -> List[Dict[str, Any]]:
        """Load a bounded set of events for a single session."""
        store = getattr(self._memory, "l1", None)
        if store is None:
            return []
        hit_session_seqs = sorted(
            {
                session_seq
                for hit in session_hits
                for session_seq in [self._session_seq(hit.get("session_seq"))]
                if session_seq is not None
            }
        )
        window_loader = getattr(store, "query_session_event_window", None)
        if hit_session_seqs and callable(window_loader):
            try:
                window_events_list = await asyncio.gather(
                    *(
                        window_loader(
                            session_id=session_id,
                            center_session_seq=session_seq,
                            window=max(neighbor_window, 0),
                            include_embedding_fields=False,
                        )
                        for session_seq in hit_session_seqs
                    )
                )
            except Exception:
                logger.debug(
                    "Failed to load session-sequence L1 window for evidence bundle",
                    exc_info=True,
                )
            else:
                merged_events = self._dedupe_events(
                    event for window_events in window_events_list for event in window_events
                )
                if merged_events:
                    return merged_events
        try:
            events = await store.query_events(session_id=session_id, limit=limit)
        except Exception:
            logger.debug("Failed to load session-local L1 events for evidence bundle", exc_info=True)
            return []
        return sorted(events, key=self._event_sort_key)

    def _select_bundle_events(
        self,
        *,
        session_events: List[Dict[str, Any]],
        session_hits: List[Dict[str, Any]],
        neighbor_window: int = 1,
    ) -> tuple[List[Dict[str, Any]], bool]:
        """Select hit-centered session events, expanding to adjacent turns when possible."""
        if not session_events:
            return list(session_hits), False

        hit_event_ids = {str(hit.get("event_id") or "") for hit in session_hits}
        hit_turn_numbers = {
            turn_number
            for hit in session_hits
            for turn_number in [self._parse_turn_number(str(hit.get("turn_id") or ""))]
            if turn_number is not None
        }
        hit_session_seqs = {
            session_seq
            for hit in session_hits
            for session_seq in [self._session_seq(hit.get("session_seq"))]
            if session_seq is not None
        }

        selected: List[Dict[str, Any]] = []
        for event in session_events:
            event_id = str(event.get("event_id") or "")
            if event_id in hit_event_ids:
                selected.append(event)
                continue
            session_seq = self._session_seq(event.get("session_seq"))
            if session_seq is not None and hit_session_seqs:
                if any(
                    abs(session_seq - hit_session_seq) <= max(neighbor_window, 0)
                    for hit_session_seq in hit_session_seqs
                ):
                    selected.append(event)
                continue
            turn_number = self._parse_turn_number(str(event.get("turn_id") or ""))
            if turn_number is None or not hit_turn_numbers:
                continue
            if any(
                abs(turn_number - hit_turn_number) <= max(neighbor_window, 0)
                for hit_turn_number in hit_turn_numbers
            ):
                selected.append(event)

        unique_events = self._dedupe_events(selected)
        neighbor_expansion_applied = len(unique_events) > len(session_hits)
        return unique_events or list(session_hits), neighbor_expansion_applied

    @classmethod
    def _dedupe_events(cls, events: Any) -> List[Dict[str, Any]]:
        unique_events: List[Dict[str, Any]] = []
        seen_event_ids: set[str] = set()
        for event in events:
            event_id = str(event.get("event_id") or "")
            if event_id and event_id in seen_event_ids:
                continue
            if event_id:
                seen_event_ids.add(event_id)
            unique_events.append(event)
        unique_events.sort(key=cls._event_sort_key)
        return unique_events

    @classmethod
    def _event_sort_key(cls, event: Dict[str, Any]) -> tuple[int, int | float]:
        session_seq = cls._session_seq(event.get("session_seq"))
        if session_seq is not None:
            return (0, session_seq)
        return (1, float(event.get("timestamp") or 0.0))

    @staticmethod
    def _session_seq(value: Any) -> int | None:
        if value is None:
            return None
        try:
            return int(value)
        except (TypeError, ValueError):
            return None

    @staticmethod
    def _bundle_neighbor_window(query: str) -> int:
        """Return the neighbor turn window for evidence bundle assembly."""
        return bundle_neighbor_window(query)

    @staticmethod
    def _hit_score(hit: Dict[str, Any]) -> float:
        """Extract the best available relevance score from a retrieval hit."""
        return hit_score(hit)

    @staticmethod
    def _parse_turn_number(turn_id: str) -> int | None:
        """Extract a numeric turn suffix from session turn ids like `session:turn-3`."""
        return parse_turn_number(turn_id)


__all__ = ["EvidenceBundleMixin"]
