"""L1 retrieval search path implementations."""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

from .answerability import extract_query_tokens, extract_quoted_spans
from .models import L1Conditions, TimeRange

logger = logging.getLogger(__name__)


class L1SearchPathMixin:
    """Run the BM25, vector, keyword, and temporal L1 search paths."""

    async def _bm25_path(
        self,
        query: str,
        limit: int,
        *,
        user_id: Optional[str] = None,
        l1_retrieval_scopes: Optional[List[str]] = None,
    ) -> List[str]:
        """BM25 search via FTS5, optionally scoped to *user_id*."""
        try:
            hits = await self._store.bm25_search(
                query,
                limit=limit,
                user_id=user_id,
                l1_retrieval_scopes=l1_retrieval_scopes,
            )
            return [event_id for event_id, _score in hits]
        except Exception as exc:
            logger.warning("BM25 path failed: %s", exc)
            return []

    async def _temporal_bm25_path(
        self,
        query: str,
        limit: int,
        time_range: TimeRange,
        *,
        user_id: Optional[str] = None,
        l1_retrieval_scopes: Optional[List[str]] = None,
    ) -> List[str]:
        """Time-constrained BM25 search to boost recall for temporal queries."""
        try:
            hits = await self._store.bm25_search(
                query,
                limit=limit,
                user_id=user_id,
                start_time=time_range.start,
                end_time=time_range.end,
                strict=True,
                l1_retrieval_scopes=l1_retrieval_scopes,
            )
            return [event_id for event_id, _score in hits]
        except Exception as exc:
            logger.warning("Temporal BM25 path failed: %s", exc)
            return []

    async def _vector_path(
        self,
        query: str,
        limit: int,
        *,
        user_id: Optional[str] = None,
        l1_retrieval_scopes: Optional[List[str]] = None,
    ) -> List[str]:
        """Vector similarity search via sqlite-vec."""
        try:
            chunk_density_multiplier = 10
            vec_limit = limit * chunk_density_multiplier
            hits = await self._store.vector_search(
                query=query, limit=vec_limit, user_id=user_id,
            )
            if not hits:
                return []

            seen: set[str] = set()
            event_ids: List[str] = []
            for hit in hits:
                event_id = hit.entity_id.split("::")[0] if "::" in hit.entity_id else hit.entity_id
                if event_id not in seen:
                    seen.add(event_id)
                    event_ids.append(event_id)

            return await self._filter_ids_by_l1_retrieval_scope(
                event_ids,
                l1_retrieval_scopes,
                user_id=user_id,
            )
        except Exception as exc:
            logger.warning("Vector path failed: %s", exc)
            return []

    async def _keyword_path(
        self,
        conditions: L1Conditions,
        limit: int,
        *,
        session_id: Optional[str] = None,
        user_id: Optional[str] = None,
        l1_retrieval_scopes: Optional[List[str]] = None,
    ) -> List[str]:
        """SQL LIKE keyword search via query_events + in-memory token filtering."""
        try:
            events = await self._store.query_events(
                session_id=session_id,
                user_id=user_id,
                event_type=conditions.event_types[0] if conditions.event_types else None,
                source_filters=conditions.source_filters,
                query=conditions.content_query or None,
                l1_retrieval_scopes=l1_retrieval_scopes,
                limit=limit,
            )
            quoted_phrases = extract_quoted_spans(conditions.content_query)
            if quoted_phrases:
                matched_scored: list[tuple[int, str]] = []
                for event in events:
                    normalized_content = " ".join(extract_query_tokens(event.get("content", "")))
                    quote_hits = sum(1 for phrase in quoted_phrases if phrase and phrase in normalized_content)
                    if quote_hits > 0:
                        matched_scored.append((quote_hits, str(event.get("event_id") or "")))
                matched_scored.sort(key=lambda item: item[0], reverse=True)
                return [event_id for _, event_id in matched_scored if event_id]

            query_tokens = [token for token in conditions.content_query.lower().split() if token]
            matched = [
                event["event_id"]
                for event in events
                if all(token in event.get("content", "").lower() for token in query_tokens)
            ]
            return matched
        except Exception as exc:
            logger.warning("Keyword path failed: %s", exc)
            return []

    async def _filter_ids_by_user(self, event_ids: List[str], user_id: str) -> List[str]:
        """Return the subset of *event_ids* that belong to *user_id*."""
        return await self._store.filter_ids_by_user(event_ids, user_id)

    async def _filter_ids_by_l1_retrieval_scope(
        self,
        event_ids: List[str],
        scopes: Optional[List[str]],
        *,
        user_id: Optional[str] = None,
    ) -> List[str]:
        """Return event IDs whose persisted L1 evidence scope is allowed."""
        if scopes is None:
            return event_ids
        if not scopes or not event_ids:
            return []
        events = await self._store.fetch_events(
            event_ids,
            user_id=user_id,
            l1_retrieval_scopes=scopes,
        )
        allowed = {str(event.get("event_id") or "") for event in events}
        return [event_id for event_id in event_ids if event_id in allowed]

    async def _fetch_and_filter(
        self,
        *,
        event_ids: List[str],
        conditions: L1Conditions,
        time_range: Optional[TimeRange],
        session_id: Optional[str],
        user_id: Optional[str],
        l1_retrieval_scopes: Optional[List[str]] = None,
    ) -> List[Dict[str, Any]]:
        """Fetch full event dicts for given IDs and apply post-filters."""
        from ..event_contracts import MemoryDomain

        if not event_ids:
            return []

        return await self._store.fetch_events(
            event_ids,
            session_id=session_id,
            user_id=user_id,
            event_types=conditions.event_types or None,
            source_filters=conditions.source_filters or None,
            domain_filters=conditions.domain_filters or None,
            exclude_domain=MemoryDomain.RUNTIME_TELEMETRY.label if not conditions.domain_filters else None,
            time_start=time_range.start if time_range else None,
            time_end=time_range.end if time_range else None,
            l1_retrieval_scopes=l1_retrieval_scopes,
        )


__all__ = ["L1SearchPathMixin"]
