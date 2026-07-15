"""L1 retrieval execution orchestration."""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Sequence, Tuple

from .handler_base import rrf_fuse
from .debug_detail import DETAIL_LIMIT, event_record, event_records, log_detail
from .models import L1Conditions, TimeRange

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class _L1BasePathResults:
    bm25_ids: List[str]
    vector_ids: List[str]
    keyword_ids: List[str]
    temporal_bm25_ids: List[str]
    bm25_details: Dict[str, Dict[str, Any]]
    vector_details: Dict[str, Dict[str, Any]]
    temporal_bm25_details: Dict[str, Dict[str, Any]]

    @property
    def paths(self) -> Dict[str, List[str]]:
        return {
            "bm25": self.bm25_ids,
            "vector": self.vector_ids,
            "keyword": self.keyword_ids,
            "temporal_bm25": self.temporal_bm25_ids,
        }

    @property
    def details(self) -> Dict[str, Dict[str, Dict[str, Any]]]:
        return {
            "bm25": self.bm25_details,
            "vector": self.vector_details,
            "keyword": {},
            "temporal_bm25": self.temporal_bm25_details,
        }

    def seed_ids(self) -> List[str]:
        return list(
            dict.fromkeys(
                self.bm25_ids[:10]
                + self.vector_ids[:10]
                + self.keyword_ids[:10]
                + self.temporal_bm25_ids[:10]
            )
        )


@dataclass(frozen=True)
class _L1ExpansionPathResults:
    entity_ids: List[str]
    graph_ids: List[str]


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
            top_ids,
            fused,
            conditions,
            time_range,
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
        self._reset_l1_path_details()
        base_paths = await self._run_base_l1_paths(
            conditions,
            time_range,
            fetch_k,
            session_id=session_id,
            user_id=user_id,
            l1_retrieval_scopes=l1_retrieval_scopes,
        )
        await self._log_base_l1_path_results(
            conditions=conditions,
            time_range=time_range,
            fetch_k=fetch_k,
            base_paths=base_paths,
            user_id=user_id,
            l1_retrieval_scopes=l1_retrieval_scopes,
        )

        expansion_paths = await self._expand_l1_candidate_paths(
            seed_ids=base_paths.seed_ids(),
            fetch_k=fetch_k,
            user_id=user_id,
            l1_retrieval_scopes=l1_retrieval_scopes,
            time_range=time_range,
            context_scope=conditions.context_scope,
        )
        ranked_lists, weights, path_names = self._build_l1_ranked_lists(
            base_paths,
            expansion_paths,
        )
        return (
            ranked_lists,
            weights,
            self._build_l1_path_debug(
                base_paths=base_paths,
                expansion_paths=expansion_paths,
                path_names=path_names,
                weights=weights,
            ),
        )

    def _reset_l1_path_details(self) -> None:
        self._last_bm25_path_details = {}
        self._last_vector_path_details = {}
        self._last_temporal_bm25_path_details = {}

    async def _run_base_l1_paths(
        self,
        conditions: L1Conditions,
        time_range: Optional[TimeRange],
        fetch_k: int,
        *,
        session_id: Optional[str],
        user_id: Optional[str],
        l1_retrieval_scopes: Optional[List[str]],
    ) -> _L1BasePathResults:
        has_temporal = self._has_temporal_range(time_range)
        retrieval_coros = self._base_l1_path_coroutines(
            conditions,
            time_range,
            fetch_k,
            has_temporal=has_temporal,
            session_id=session_id,
            user_id=user_id,
            l1_retrieval_scopes=l1_retrieval_scopes,
        )
        results_or_errors = await asyncio.gather(*retrieval_coros, return_exceptions=True)
        self._log_l1_path_errors(results_or_errors)
        return self._base_l1_results_from_gather(
            results_or_errors,
            has_temporal=has_temporal,
        )

    @staticmethod
    def _has_temporal_range(time_range: Optional[TimeRange]) -> bool:
        return time_range is not None and (
            time_range.start is not None or time_range.end is not None
        )

    def _base_l1_path_coroutines(
        self,
        conditions: L1Conditions,
        time_range: Optional[TimeRange],
        fetch_k: int,
        *,
        has_temporal: bool,
        session_id: Optional[str],
        user_id: Optional[str],
        l1_retrieval_scopes: Optional[List[str]],
    ) -> List[Any]:
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
        return retrieval_coros

    def _base_l1_results_from_gather(
        self,
        results_or_errors: List[Any],
        *,
        has_temporal: bool,
    ) -> _L1BasePathResults:
        temporal_bm25_ids: List[str] = []
        temporal_bm25_details: Dict[str, Dict[str, Any]] = {}
        if has_temporal:
            temporal_bm25_ids = self._ids_from_path_result(results_or_errors[3])
            temporal_bm25_details = self._last_path_details("_last_temporal_bm25_path_details")

        return _L1BasePathResults(
            bm25_ids=self._ids_from_path_result(results_or_errors[0]),
            vector_ids=self._ids_from_path_result(results_or_errors[1]),
            keyword_ids=self._ids_from_path_result(results_or_errors[2]),
            temporal_bm25_ids=temporal_bm25_ids,
            bm25_details=self._last_path_details("_last_bm25_path_details"),
            vector_details=self._last_path_details("_last_vector_path_details"),
            temporal_bm25_details=temporal_bm25_details,
        )

    @staticmethod
    def _ids_from_path_result(result: Any) -> List[str]:
        return result if isinstance(result, list) else []

    def _last_path_details(self, attr_name: str) -> Dict[str, Dict[str, Any]]:
        details = getattr(self, attr_name, {})
        return details if isinstance(details, dict) else {}

    @staticmethod
    def _log_l1_path_errors(results_or_errors: List[Any]) -> None:
        for i, res in enumerate(results_or_errors):
            if isinstance(res, BaseException):
                logger.warning("L1 search path %d failed: %s", i, res)

    async def _log_base_l1_path_results(
        self,
        *,
        conditions: L1Conditions,
        time_range: Optional[TimeRange],
        fetch_k: int,
        base_paths: _L1BasePathResults,
        user_id: Optional[str],
        l1_retrieval_scopes: Optional[List[str]],
    ) -> None:
        logger.info(
            "L1 retrieval paths completed | content_query=%r user_id=%s "
            "bm25_count=%d vec_count=%d kw_count=%d temporal_bm25_count=%d fetch_k=%d",
            conditions.content_query,
            user_id,
            len(base_paths.bm25_ids),
            len(base_paths.vector_ids),
            len(base_paths.keyword_ids),
            len(base_paths.temporal_bm25_ids),
            fetch_k,
        )
        logger.debug(
            "L1 retrieval path samples | content_query=%r user_id=%s "
            "bm25_ids_sample=%s vec_ids_sample=%s kw_ids_sample=%s "
            "temporal_bm25_ids_sample=%s l1_retrieval_scopes=%s time_range=%s",
            conditions.content_query,
            user_id,
            base_paths.bm25_ids[:10],
            base_paths.vector_ids[:10],
            base_paths.keyword_ids[:10],
            base_paths.temporal_bm25_ids[:10],
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
            paths=base_paths.paths,
            path_details=base_paths.details,
        )

    async def _expand_l1_candidate_paths(
        self,
        *,
        seed_ids: List[str],
        fetch_k: int,
        user_id: Optional[str],
        l1_retrieval_scopes: Optional[List[str]],
        time_range: Optional[TimeRange],
        context_scope: Dict[str, Any],
    ) -> _L1ExpansionPathResults:
        entity_ids = await self._entity_expansion_path(
            seed_ids=seed_ids,
            fetch_k=fetch_k,
            user_id=user_id,
            l1_retrieval_scopes=l1_retrieval_scopes,
        )
        graph_ids = await self._graph_expansion_path(
            seed_ids=seed_ids,
            fetch_k=fetch_k,
            user_id=user_id,
            l1_retrieval_scopes=l1_retrieval_scopes,
            time_range=time_range,
            context_scope=context_scope,
        )
        return _L1ExpansionPathResults(entity_ids=entity_ids, graph_ids=graph_ids)

    async def _entity_expansion_path(
        self,
        *,
        seed_ids: List[str],
        fetch_k: int,
        user_id: Optional[str],
        l1_retrieval_scopes: Optional[List[str]],
    ) -> List[str]:
        if not seed_ids:
            return []
        try:
            entity_ids = await self._store.expand_by_entities(seed_ids, limit=fetch_k)
            return await self._filter_ids_by_l1_retrieval_scope(
                entity_ids,
                l1_retrieval_scopes,
                user_id=user_id,
            )
        except Exception as exc:
            logger.warning("L1 entity expansion failed: %s", exc)
            return []

    async def _graph_expansion_path(
        self,
        *,
        seed_ids: List[str],
        fetch_k: int,
        user_id: Optional[str],
        l1_retrieval_scopes: Optional[List[str]],
        time_range: Optional[TimeRange],
        context_scope: Dict[str, Any],
    ) -> List[str]:
        cfg = self._config
        if not cfg.graph_spreading_enabled or self._l2_store is None or not seed_ids:
            return []
        try:
            graph_ids = await self._graph_spreading_path(
                seed_ids,
                fetch_k,
                time_range=time_range,
                context_scope=context_scope,
            )
            return await self._filter_ids_by_l1_retrieval_scope(
                graph_ids,
                l1_retrieval_scopes,
                user_id=user_id,
            )
        except Exception as exc:
            logger.warning("L1 graph spreading failed: %s", exc)
            return []

    def _build_l1_ranked_lists(
        self,
        base_paths: _L1BasePathResults,
        expansion_paths: _L1ExpansionPathResults,
    ) -> Tuple[List[Sequence[str]], List[float], List[str]]:
        cfg = self._config
        ranked_lists: List[Sequence[str]] = [
            base_paths.bm25_ids,
            base_paths.vector_ids,
            base_paths.keyword_ids,
        ]
        weights = [
            cfg.rrf_weight_bm25,
            cfg.rrf_weight_vector,
            cfg.rrf_weight_keyword,
        ]
        path_names = ["bm25", "vector", "keyword"]

        if expansion_paths.entity_ids:
            ranked_lists.append(expansion_paths.entity_ids)
            weights.append(cfg.rrf_weight_entity)
            path_names.append("entity")
        if expansion_paths.graph_ids:
            ranked_lists.append(expansion_paths.graph_ids)
            weights.append(cfg.rrf_weight_graph)
            path_names.append("graph")
        if base_paths.temporal_bm25_ids:
            ranked_lists.append(base_paths.temporal_bm25_ids)
            weights.append(cfg.rrf_weight_temporal_bm25)
            path_names.append("temporal_bm25")
        return ranked_lists, weights, path_names

    @staticmethod
    def _build_l1_path_debug(
        *,
        base_paths: _L1BasePathResults,
        expansion_paths: _L1ExpansionPathResults,
        path_names: List[str],
        weights: List[float],
    ) -> Dict[str, Any]:
        return {
            "path_names": path_names,
            "paths": {
                "bm25": base_paths.bm25_ids,
                "vector": base_paths.vector_ids,
                "keyword": base_paths.keyword_ids,
                "entity": expansion_paths.entity_ids,
                "graph": expansion_paths.graph_ids,
                "temporal_bm25": base_paths.temporal_bm25_ids,
            },
            "details": {
                "bm25": base_paths.bm25_details,
                "vector": base_paths.vector_details,
                "keyword": {},
                "entity": {},
                "graph": {},
                "temporal_bm25": base_paths.temporal_bm25_details,
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
            event_ids=top_ids,
            conditions=conditions,
            time_range=time_range,
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
        final = reranked[: conditions.limit]
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
