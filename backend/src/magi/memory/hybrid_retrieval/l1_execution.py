"""L1 retrieval execution orchestration."""

from __future__ import annotations

import asyncio
import logging
from typing import Any, Dict, List, Optional, Sequence, Tuple

from .handler_base import rrf_fuse
from .debug_detail import DETAIL_LIMIT, event_record, event_records, log_detail
from .models import L1Conditions, TimeRange

logger = logging.getLogger(__name__)


class L1ExecutionMixin:
    """Coordinate L1 retrieval paths, RRF fusion, hydration, and reranking."""

    async def execute(
        self,
        conditions: L1Conditions,
        time_range: Optional[TimeRange] = None,
        *,
        session_id: Optional[str] = None,
        user_id: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        """Query L1 using BM25 + vector + keyword + entity expansion, fused via RRF."""
        if not conditions.content_query:
            return []
        cfg = self._config
        l1_retrieval_scopes = getattr(self, "_l1_retrieval_scopes", None)
        fetch_k = max(conditions.limit * cfg.rrf_over_fetch_multiplier, cfg.rrf_over_fetch_minimum)

        ranked_lists, weights, path_debug = await self._collect_candidate_lists(
            conditions,
            time_range,
            fetch_k,
            session_id=session_id,
            user_id=user_id,
            l1_retrieval_scopes=l1_retrieval_scopes,
        )
        if not any(ids for ids in ranked_lists):
            return []

        fused = rrf_fuse(ranked_lists, weights, k=cfg.rrf_k)
        top_ids = [doc_id for doc_id, _ in fused[:fetch_k]]
        if not top_ids:
            return []

        await self._log_l1_rrf_detail(
            conditions=conditions,
            time_range=time_range,
            fused=fused[:fetch_k],
            path_debug=path_debug,
            user_id=user_id,
            l1_retrieval_scopes=l1_retrieval_scopes,
        )

        return await self._hydrate_and_rerank(
            top_ids, fused, conditions, time_range,
            session_id=session_id,
            user_id=user_id,
            l1_retrieval_scopes=l1_retrieval_scopes,
            path_debug=path_debug,
        )

    async def _collect_candidate_lists(
        self,
        conditions: L1Conditions,
        time_range: Optional[TimeRange],
        fetch_k: int,
        *,
        session_id: Optional[str] = None,
        user_id: Optional[str] = None,
        l1_retrieval_scopes: Optional[List[str]] = None,
    ) -> Tuple[List[Sequence[str]], List[float], Dict[str, Any]]:
        """Run all retrieval paths and return (ranked_lists, weights) for RRF fusion."""
        cfg = self._config
        self._last_bm25_path_details = {}
        self._last_vector_path_details = {}
        self._last_temporal_bm25_path_details = {}

        retrieval_coros = [
            self._bm25_path(
                conditions.content_query,
                fetch_k,
                user_id=user_id,
                l1_retrieval_scopes=l1_retrieval_scopes,
            ),
            self._vector_path(
                conditions.content_query,
                fetch_k,
                user_id=user_id,
                l1_retrieval_scopes=l1_retrieval_scopes,
            ),
            self._keyword_path(
                conditions,
                fetch_k,
                session_id=session_id,
                user_id=user_id,
                l1_retrieval_scopes=l1_retrieval_scopes,
            ),
        ]
        has_temporal = time_range is not None and (time_range.start is not None or time_range.end is not None)
        if has_temporal:
            retrieval_coros.append(
                self._temporal_bm25_path(
                    conditions.content_query,
                    fetch_k,
                    time_range,
                    user_id=user_id,
                    l1_retrieval_scopes=l1_retrieval_scopes,
                ),
            )

        results_or_errors = await asyncio.gather(*retrieval_coros, return_exceptions=True)

        bm25_ids: List[str] = results_or_errors[0] if isinstance(results_or_errors[0], list) else []
        bm25_details = (
            getattr(self, "_last_bm25_path_details", {})
            if isinstance(getattr(self, "_last_bm25_path_details", {}), dict)
            else {}
        )
        vec_ids: List[str] = results_or_errors[1] if isinstance(results_or_errors[1], list) else []
        vec_details = (
            getattr(self, "_last_vector_path_details", {})
            if isinstance(getattr(self, "_last_vector_path_details", {}), dict)
            else {}
        )
        kw_ids: List[str] = results_or_errors[2] if isinstance(results_or_errors[2], list) else []
        temporal_bm25_ids: List[str] = []
        temporal_bm25_details: Dict[str, Dict[str, Any]] = {}
        if has_temporal:
            temporal_bm25_ids = results_or_errors[3] if isinstance(results_or_errors[3], list) else []
            temporal_bm25_details = (
                getattr(self, "_last_temporal_bm25_path_details", {})
                if isinstance(getattr(self, "_last_temporal_bm25_path_details", {}), dict)
                else {}
            )

        for i, res in enumerate(results_or_errors):
            if isinstance(res, BaseException):
                logger.warning("L1 search path %d failed: %s", i, res)

        logger.info(
            "L1 retrieval paths completed | content_query=%r user_id=%s "
            "bm25_count=%d vec_count=%d kw_count=%d temporal_bm25_count=%d fetch_k=%d",
            conditions.content_query, user_id,
            len(bm25_ids), len(vec_ids), len(kw_ids), len(temporal_bm25_ids), fetch_k,
        )
        logger.debug(
            "L1 retrieval path samples | content_query=%r user_id=%s "
            "bm25_ids_sample=%s vec_ids_sample=%s kw_ids_sample=%s "
            "temporal_bm25_ids_sample=%s l1_retrieval_scopes=%s time_range=%s",
            conditions.content_query,
            user_id,
            bm25_ids[:10],
            vec_ids[:10],
            kw_ids[:10],
            temporal_bm25_ids[:10],
            l1_retrieval_scopes,
            (
                {"start": time_range.start, "end": time_range.end}
                if time_range is not None
                else None
            ),
        )
        await self._log_l1_path_detail(
            content_query=conditions.content_query,
            user_id=user_id,
            time_range=time_range,
            l1_retrieval_scopes=l1_retrieval_scopes,
            paths={
                "bm25": bm25_ids,
                "vector": vec_ids,
                "keyword": kw_ids,
                "temporal_bm25": temporal_bm25_ids,
            },
            path_details={
                "bm25": bm25_details,
                "vector": vec_details,
                "keyword": {},
                "temporal_bm25": temporal_bm25_details,
            },
        )

        seed_ids: List[str] = list(dict.fromkeys(
            bm25_ids[:10] + vec_ids[:10] + kw_ids[:10] + temporal_bm25_ids[:10]
        ))
        entity_ids: List[str] = []
        if seed_ids:
            try:
                entity_ids = await self._store.expand_by_entities(seed_ids, limit=fetch_k)
                entity_ids = await self._filter_ids_by_l1_retrieval_scope(
                    entity_ids,
                    l1_retrieval_scopes,
                    user_id=user_id,
                )
            except Exception as exc:
                logger.warning("L1 entity expansion failed: %s", exc)

        graph_ids: List[str] = []
        if cfg.graph_spreading_enabled and self._l2_store is not None and seed_ids:
            try:
                graph_ids = await self._graph_spreading_path(seed_ids, fetch_k)
                graph_ids = await self._filter_ids_by_l1_retrieval_scope(
                    graph_ids,
                    l1_retrieval_scopes,
                    user_id=user_id,
                )
            except Exception as exc:
                logger.warning("L1 graph spreading failed: %s", exc)

        ranked_lists: List[Sequence[str]] = [bm25_ids, vec_ids, kw_ids]
        weights = [cfg.rrf_weight_bm25, cfg.rrf_weight_vector, cfg.rrf_weight_keyword]
        if entity_ids:
            ranked_lists.append(entity_ids)
            weights.append(cfg.rrf_weight_entity)
        if graph_ids:
            ranked_lists.append(graph_ids)
            weights.append(cfg.rrf_weight_graph)
        if temporal_bm25_ids:
            ranked_lists.append(temporal_bm25_ids)
            weights.append(cfg.rrf_weight_temporal_bm25)

        path_names = ["bm25", "vector", "keyword"]
        if entity_ids:
            path_names.append("entity")
        if graph_ids:
            path_names.append("graph")
        if temporal_bm25_ids:
            path_names.append("temporal_bm25")

        return ranked_lists, weights, {
            "path_names": path_names,
            "paths": {
                "bm25": bm25_ids,
                "vector": vec_ids,
                "keyword": kw_ids,
                "entity": entity_ids,
                "graph": graph_ids,
                "temporal_bm25": temporal_bm25_ids,
            },
            "details": {
                "bm25": bm25_details,
                "vector": vec_details,
                "keyword": {},
                "entity": {},
                "graph": {},
                "temporal_bm25": temporal_bm25_details,
            },
            "weights": dict(zip(path_names, weights)),
        }

    async def _hydrate_and_rerank(
        self,
        top_ids: List[str],
        fused: List[Tuple[str, float]],
        conditions: L1Conditions,
        time_range: Optional[TimeRange],
        *,
        session_id: Optional[str] = None,
        user_id: Optional[str] = None,
        l1_retrieval_scopes: Optional[List[str]] = None,
        path_debug: Optional[Dict[str, Any]] = None,
    ) -> List[Dict[str, Any]]:
        """Fetch full event rows, apply filters, and rerank."""
        results = await self._fetch_and_filter(
            event_ids=top_ids, conditions=conditions, time_range=time_range,
            session_id=session_id,
            user_id=user_id,
            l1_retrieval_scopes=l1_retrieval_scopes,
        )

        log_detail(
            logger,
            "L1 HYDRATED DETAIL",
            {
                "content_query": conditions.content_query,
                "input_count": len(top_ids),
                "output_count": len(results),
                "session_id": session_id,
                "user_id": user_id,
                "time_range": (
                    {"start": time_range.start, "end": time_range.end}
                    if time_range is not None
                    else None
                ),
                "source_filters": conditions.source_filters,
                "domain_filters": conditions.domain_filters,
                "l1_retrieval_scopes": l1_retrieval_scopes,
                "events": event_records(results, limit=DETAIL_LIMIT),
                "path_ranks": self._path_ranks_for_ids(
                    [str(item.get("event_id") or "") for item in results],
                    path_debug,
                ),
            },
        )

        reranked = await self._reranker.rerank(
            layer=self.layer_name,
            results=results,
            query=conditions.content_query,
            fused_scores=dict(fused),
        )
        final = reranked[:conditions.limit]
        log_detail(
            logger,
            "L1 RERANK DETAIL",
            {
                "content_query": conditions.content_query,
                "reranked_count": len(reranked),
                "limit": conditions.limit,
                "final_count": len(final),
                "reranked_events": event_records(reranked, limit=DETAIL_LIMIT),
                "final_events": event_records(final, limit=DETAIL_LIMIT),
            },
        )
        return final

    async def _log_l1_rrf_detail(
        self,
        *,
        conditions: L1Conditions,
        time_range: Optional[TimeRange],
        fused: List[Tuple[str, float]],
        path_debug: Dict[str, Any],
        user_id: Optional[str],
        l1_retrieval_scopes: Optional[List[str]],
    ) -> None:
        try:
            ids = [event_id for event_id, _score in fused[:DETAIL_LIMIT]]
            rows = await self._store.fetch_events(
                ids,
                user_id=user_id,
                l1_retrieval_scopes=l1_retrieval_scopes,
            )
            by_id = {str(row.get("event_id") or ""): row for row in rows}
            path_ranks = self._path_ranks_for_ids(ids, path_debug)
            log_detail(
                logger,
                "L1 RRF DETAIL",
                {
                    "content_query": conditions.content_query,
                    "time_range": (
                        {"start": time_range.start, "end": time_range.end}
                        if time_range is not None
                        else None
                    ),
                    "path_weights": path_debug.get("weights", {}),
                    "candidate_count": len(fused),
                    "logged_count": min(len(fused), DETAIL_LIMIT),
                    "candidates": [
                        event_record(
                            by_id.get(event_id),
                            rank=rank,
                            fused_score=score,
                        )
                        | {
                            "event_id": event_id,
                            "path_ranks": path_ranks.get(event_id, {}),
                        }
                        for rank, (event_id, score) in enumerate(fused[:DETAIL_LIMIT], start=1)
                    ],
                },
            )
        except Exception:
            logger.warning("Failed to log L1 RRF detail", exc_info=True)

    @staticmethod
    def _path_ranks_for_ids(
        event_ids: List[str],
        path_debug: Optional[Dict[str, Any]],
    ) -> Dict[str, Dict[str, Any]]:
        if not path_debug:
            return {}
        paths = path_debug.get("paths", {}) if isinstance(path_debug, dict) else {}
        details = path_debug.get("details", {}) if isinstance(path_debug, dict) else {}
        result: Dict[str, Dict[str, Any]] = {}
        for event_id in event_ids:
            per_path: Dict[str, Any] = {}
            for path_name, ids in paths.items():
                if not isinstance(ids, list):
                    continue
                try:
                    rank = ids.index(event_id) + 1
                except ValueError:
                    continue
                per_path[path_name] = {
                    "rank": rank,
                    "detail": (
                        details.get(path_name, {}).get(event_id, {})
                        if isinstance(details.get(path_name, {}), dict)
                        else {}
                    ),
                }
            if per_path:
                result[event_id] = per_path
        return result


__all__ = ["L1ExecutionMixin"]
