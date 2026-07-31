"""L1 retrieval search path implementations."""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

from ...utils.diagnostic_logging import full_content_logging_enabled
from .answerability import extract_query_tokens, extract_quoted_spans
from .debug_detail import DETAIL_LIMIT, event_record, log_detail
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
        ids, details = await self._bm25_path_with_details(
            query,
            limit,
            user_id=user_id,
            l1_retrieval_scopes=l1_retrieval_scopes,
        )
        self._last_bm25_path_details = details
        return ids

    async def _bm25_path_with_details(
        self,
        query: str,
        limit: int,
        *,
        user_id: Optional[str] = None,
        l1_retrieval_scopes: Optional[List[str]] = None,
    ) -> tuple[List[str], Dict[str, Dict[str, Any]]]:
        """BM25 search with rank and score details for temporary debugging."""
        try:
            hits = await self._store.bm25_search(
                query,
                limit=limit,
                user_id=user_id,
                l1_retrieval_scopes=l1_retrieval_scopes,
            )
            details: Dict[str, Dict[str, Any]] = {}
            ids: List[str] = []
            for rank, (event_id, score) in enumerate(hits, start=1):
                ids.append(event_id)
                details[event_id] = {"rank": rank, "score": score}
            return ids, details
        except Exception as exc:
            logger.warning("BM25 path failed: %s", exc)
            return [], {}

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
        ids, details = await self._temporal_bm25_path_with_details(
            query,
            limit,
            time_range,
            user_id=user_id,
            l1_retrieval_scopes=l1_retrieval_scopes,
        )
        self._last_temporal_bm25_path_details = details
        return ids

    async def _temporal_bm25_path_with_details(
        self,
        query: str,
        limit: int,
        time_range: TimeRange,
        *,
        user_id: Optional[str] = None,
        l1_retrieval_scopes: Optional[List[str]] = None,
    ) -> tuple[List[str], Dict[str, Dict[str, Any]]]:
        """Time-constrained BM25 search with rank and score details."""
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
            details: Dict[str, Dict[str, Any]] = {}
            ids: List[str] = []
            for rank, (event_id, score) in enumerate(hits, start=1):
                ids.append(event_id)
                details[event_id] = {"rank": rank, "score": score}
            return ids, details
        except Exception as exc:
            logger.warning("Temporal BM25 path failed: %s", exc)
            return [], {}

    async def _vector_path(
        self,
        query: str,
        limit: int,
        *,
        user_id: Optional[str] = None,
        l1_retrieval_scopes: Optional[List[str]] = None,
    ) -> List[str]:
        """Vector similarity search via sqlite-vec."""
        ids, details = await self._vector_path_with_details(
            query,
            limit,
            user_id=user_id,
            l1_retrieval_scopes=l1_retrieval_scopes,
        )
        self._last_vector_path_details = details
        return ids

    async def _vector_path_with_details(
        self,
        query: str,
        limit: int,
        *,
        user_id: Optional[str] = None,
        l1_retrieval_scopes: Optional[List[str]] = None,
    ) -> tuple[List[str], Dict[str, Dict[str, Any]]]:
        """Vector search with event rank, best distance, and chunk details."""
        try:
            chunk_density_multiplier = 10
            vec_limit = limit * chunk_density_multiplier
            hits = await self._store.vector_search(
                query=query,
                limit=vec_limit,
                user_id=user_id,
            )
            if not hits:
                return [], {}

            seen: set[str] = set()
            event_ids: List[str] = []
            details: Dict[str, Dict[str, Any]] = {}
            for chunk_rank, hit in enumerate(hits, start=1):
                event_id = hit.entity_id.split("::")[0] if "::" in hit.entity_id else hit.entity_id
                detail = details.setdefault(
                    event_id,
                    {
                        "rank": len(event_ids) + 1,
                        "best_distance": float(hit.distance),
                        "best_chunk_id": hit.entity_id,
                        "best_chunk_rank": chunk_rank,
                        "chunk_hits": [],
                    },
                )
                detail["best_distance"] = min(float(detail["best_distance"]), float(hit.distance))
                if float(hit.distance) <= float(detail.get("best_distance") or hit.distance):
                    detail["best_chunk_id"] = hit.entity_id
                    detail["best_chunk_rank"] = chunk_rank
                if len(detail["chunk_hits"]) < 5:
                    detail["chunk_hits"].append(
                        {
                            "chunk_rank": chunk_rank,
                            "chunk_id": hit.entity_id,
                            "distance": float(hit.distance),
                        }
                    )
                if event_id not in seen:
                    seen.add(event_id)
                    event_ids.append(event_id)

            filtered_ids = await self._filter_ids_by_l1_retrieval_scope(
                event_ids,
                l1_retrieval_scopes,
                user_id=user_id,
            )
            filtered_set = set(filtered_ids)
            return filtered_ids, {
                event_id: details[event_id]
                for event_id in filtered_ids
                if event_id in details and event_id in filtered_set
            }
        except Exception as exc:
            logger.warning("Vector path failed: %s", exc)
            return [], {}

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
                    quote_hits = sum(
                        1 for phrase in quoted_phrases if phrase and phrase in normalized_content
                    )
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
        if not event_ids:
            return []

        results = await self._fetch_l1_filtered_events(
            event_ids=event_ids,
            conditions=conditions,
            time_range=time_range,
            session_id=session_id,
            user_id=user_id,
            l1_retrieval_scopes=l1_retrieval_scopes,
        )
        result_ids = [str(item.get("event_id") or "") for item in results]
        dropped_ids = _dropped_event_ids(event_ids=event_ids, result_ids=result_ids)
        dropped_rows = await self._hydrate_dropped_l1_rows(
            dropped_ids=dropped_ids,
            user_id=user_id,
            l1_retrieval_scopes=l1_retrieval_scopes,
        )
        dropped_by_id = {str(row.get("event_id") or ""): row for row in dropped_rows}
        filters = _fetch_filter_trace(
            conditions=conditions,
            time_range=time_range,
            session_id=session_id,
            user_id=user_id,
            l1_retrieval_scopes=l1_retrieval_scopes,
        )
        _log_l1_fetch_filter_trace(
            conditions=conditions,
            event_ids=event_ids,
            results=results,
            result_ids=result_ids,
            dropped_ids=dropped_ids,
            dropped_by_id=dropped_by_id,
            filters=filters,
        )
        return results

    async def _fetch_l1_filtered_events(
        self,
        *,
        event_ids: List[str],
        conditions: L1Conditions,
        time_range: Optional[TimeRange],
        session_id: Optional[str],
        user_id: Optional[str],
        l1_retrieval_scopes: Optional[List[str]],
    ) -> List[Dict[str, Any]]:
        return await self._store.fetch_events(
            event_ids,
            session_id=session_id,
            user_id=user_id,
            event_types=conditions.event_types or None,
            source_filters=conditions.source_filters or None,
            domain_filters=conditions.domain_filters or None,
            exclude_domain=_runtime_telemetry_exclusion(conditions),
            time_start=time_range.start if time_range else None,
            time_end=time_range.end if time_range else None,
            l1_retrieval_scopes=l1_retrieval_scopes,
        )

    async def _hydrate_dropped_l1_rows(
        self,
        *,
        dropped_ids: List[str],
        user_id: Optional[str],
        l1_retrieval_scopes: Optional[List[str]],
    ) -> List[Dict[str, Any]]:
        if not dropped_ids:
            return []
        try:
            return await self._store.fetch_events(
                dropped_ids[:DETAIL_LIMIT],
                user_id=user_id,
                l1_retrieval_scopes=l1_retrieval_scopes,
            )
        except Exception:
            logger.debug("Failed to hydrate dropped L1 rows for debug log", exc_info=True)
            return []

    async def _log_l1_path_detail(
        self,
        *,
        content_query: str,
        user_id: Optional[str],
        time_range: Optional[TimeRange],
        l1_retrieval_scopes: Optional[List[str]],
        paths: Dict[str, List[str]],
        path_details: Dict[str, Dict[str, Dict[str, Any]]],
    ) -> None:
        """Log rich L1 path candidates at INFO level for temporary diagnosis."""
        try:
            selected_ids: list[str] = []
            for ids in paths.values():
                selected_ids.extend(ids[:DETAIL_LIMIT])
            selected_ids = list(dict.fromkeys(selected_ids))
            rows = await self._store.fetch_events(
                selected_ids,
                user_id=user_id,
                l1_retrieval_scopes=l1_retrieval_scopes,
            )
            by_id = {str(row.get("event_id") or ""): row for row in rows}
            log_detail(
                logger,
                "L1 PATH DETAIL",
                {
                    "content_query": content_query,
                    "user_id": user_id,
                    "time_range": (
                        {"start": time_range.start, "end": time_range.end}
                        if time_range is not None
                        else None
                    ),
                    "l1_retrieval_scopes": l1_retrieval_scopes,
                    "paths": {
                        name: {
                            "total_count": len(ids),
                            "logged_count": min(len(ids), DETAIL_LIMIT),
                            "candidates": [
                                event_record(
                                    by_id.get(event_id),
                                    rank=rank,
                                    path=name,
                                    path_rank=path_details.get(name, {})
                                    .get(event_id, {})
                                    .get("rank"),
                                    path_score=(
                                        path_details.get(name, {}).get(event_id, {}).get("score")
                                        if "score" in path_details.get(name, {}).get(event_id, {})
                                        else path_details.get(name, {})
                                        .get(event_id, {})
                                        .get("best_distance")
                                    ),
                                )
                                | {
                                    "path_detail": path_details.get(name, {}).get(event_id, {}),
                                    "event_id": event_id,
                                }
                                for rank, event_id in enumerate(ids[:DETAIL_LIMIT], start=1)
                            ],
                        }
                        for name, ids in paths.items()
                    },
                },
            )
        except Exception:
            logger.warning("Failed to log L1 path detail", exc_info=True)


def _runtime_telemetry_exclusion(conditions: L1Conditions) -> str | None:
    from ..event_contracts import MemoryDomain

    if conditions.domain_filters:
        return None
    return MemoryDomain.RUNTIME_TELEMETRY.label


def _dropped_event_ids(
    *,
    event_ids: List[str],
    result_ids: List[str],
) -> List[str]:
    result_id_set = set(result_ids)
    return [event_id for event_id in event_ids if event_id not in result_id_set]


def _fetch_filter_trace(
    *,
    conditions: L1Conditions,
    time_range: Optional[TimeRange],
    session_id: Optional[str],
    user_id: Optional[str],
    l1_retrieval_scopes: Optional[List[str]],
) -> Dict[str, Any]:
    return {
        "session_id": session_id,
        "user_id": user_id,
        "event_types": conditions.event_types or None,
        "source_filters": conditions.source_filters or None,
        "domain_filters": conditions.domain_filters or None,
        "exclude_domain": _runtime_telemetry_exclusion(conditions),
        "time_range": (
            {"start": time_range.start, "end": time_range.end} if time_range is not None else None
        ),
        "l1_retrieval_scopes": l1_retrieval_scopes,
    }


def _log_l1_fetch_filter_trace(
    *,
    conditions: L1Conditions,
    event_ids: List[str],
    results: List[Dict[str, Any]],
    result_ids: List[str],
    dropped_ids: List[str],
    dropped_by_id: Dict[str, Dict[str, Any]],
    filters: Dict[str, Any],
) -> None:
    query_log = (
        conditions.content_query
        if full_content_logging_enabled()
        else f"[content omitted; {len(conditions.content_query)} chars]"
    )
    logger.info(
        "L1 fetch filters applied | content_query=%r input_count=%d "
        "output_count=%d dropped_count=%d dropped_ids_sample=%s "
        "result_ids_sample=%s filters=%s",
        query_log,
        len(event_ids),
        len(results),
        len(dropped_ids),
        dropped_ids[:10],
        result_ids[:10],
        filters,
    )
    log_detail(
        logger,
        "L1 FETCH FILTER DETAIL",
        {
            "content_query": conditions.content_query,
            "input_count": len(event_ids),
            "output_count": len(results),
            "dropped_count": len(dropped_ids),
            "filters": filters,
            "result_events": [
                event_record(event, rank=rank)
                for rank, event in enumerate(results[:DETAIL_LIMIT], start=1)
            ],
            "dropped_events": [
                event_record(dropped_by_id.get(event_id), rank=rank) | {"event_id": event_id}
                for rank, event_id in enumerate(dropped_ids[:DETAIL_LIMIT], start=1)
            ],
        },
    )


__all__ = ["L1SearchPathMixin"]
