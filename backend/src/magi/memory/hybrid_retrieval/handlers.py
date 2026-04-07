"""Layer handlers for hybrid memory retrieval.

Each handler wraps the corresponding memory store and executes
queries based on structured LayerQueryPlan conditions.
"""

from __future__ import annotations

import abc
import asyncio
import logging
from dataclasses import asdict
from typing import Any, Dict, List, Optional, Sequence, Tuple

from ...core.sqlite import sqlite_connection_async
from .answerability import (
    extract_query_tokens,
    extract_quoted_spans,
)
from .models import (
    L1Conditions,
    L2Conditions,
    L2SemanticFrame,
    L3Conditions,
    L4Conditions,
    LayerQueryPlan,
    RetrievalConfig,
    SemanticConstraint,
    TimeRange,
)
from .reranker import build_retrieval_reranker

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# RRF fusion utility
# ---------------------------------------------------------------------------


def rrf_fuse(
    ranked_lists: Sequence[Sequence[str]],
    weights: Sequence[float],
    k: int = 60,
) -> List[Tuple[str, float]]:
    """Reciprocal Rank Fusion over multiple ranked ID lists.

    score(d) = Σ w_r / (k + rank_r(d))

    where rank_r(d) is 1-based position in ranked list r.

    Returns (id, score) pairs sorted by descending score.
    """
    scores: Dict[str, float] = {}
    for ranked_ids, weight in zip(ranked_lists, weights):
        for rank_1based, doc_id in enumerate(ranked_ids, start=1):
            scores[doc_id] = scores.get(doc_id, 0.0) + weight / (k + rank_1based)
    return sorted(scores.items(), key=lambda x: x[1], reverse=True)


# ---------------------------------------------------------------------------
# Abstract base for BM25 + vector + keyword → RRF fusion handlers
# ---------------------------------------------------------------------------


class RRFSearchHandler(abc.ABC):
    """Template for handlers that fuse BM25, vector, and keyword paths via RRF.

    Subclasses override the three search paths and the hydration step.
    """

    layer_name: str = "?"

    def __init__(self, store: Any, config: Optional[RetrievalConfig] = None) -> None:
        self._store = store
        self._config = config or RetrievalConfig()
        self._reranker = build_retrieval_reranker(self._config)

    async def _rrf_execute(
        self,
        *,
        content_query: str,
        limit: int,
        bm25_coro,
        vector_coro,
        keyword_coro,
        hydrate_coro_fn,
        time_range: Optional[TimeRange] = None,
    ) -> List[Dict[str, Any]]:
        """Shared RRF fusion skeleton used by all subclasses."""
        if not content_query:
            return []

        fetch_k = max(limit * 5, 20)

        results_or_errors = await asyncio.gather(
            bm25_coro, vector_coro, keyword_coro, return_exceptions=True,
        )

        bm25_ids: List[str] = results_or_errors[0] if isinstance(results_or_errors[0], list) else []
        vec_ids: List[str] = results_or_errors[1] if isinstance(results_or_errors[1], list) else []
        kw_ids: List[str] = results_or_errors[2] if isinstance(results_or_errors[2], list) else []

        for i, res in enumerate(results_or_errors):
            if isinstance(res, BaseException):
                logger.warning("%s search path %d failed: %s", self.layer_name, i, res)

        if not bm25_ids and not vec_ids and not kw_ids:
            return []

        cfg = self._config
        fused = rrf_fuse(
            [bm25_ids, vec_ids, kw_ids],
            [cfg.rrf_weight_bm25, cfg.rrf_weight_vector, cfg.rrf_weight_keyword],
            k=cfg.rrf_k,
        )

        top_ids = [doc_id for doc_id, _ in fused[:fetch_k]]
        if not top_ids:
            return []

        results = await hydrate_coro_fn(top_ids)

        if time_range and results:
            results = self._filter_by_time(results, time_range)

        reranked = await self._reranker.rerank(
            layer=self.layer_name,
            results=results,
            query=content_query,
            fused_scores=dict(fused),
        )
        return reranked[:limit]

    @staticmethod
    def _filter_by_time(
        results: List[Dict[str, Any]],
        time_range: TimeRange,
    ) -> List[Dict[str, Any]]:
        """Default time-range filter using timestamp/created_at."""
        filtered = []
        for r in results:
            ts = r.get("timestamp") or r.get("created_at")
            if ts is None:
                filtered.append(r)
                continue
            if time_range.start and ts < time_range.start:
                continue
            if time_range.end and ts > time_range.end:
                continue
            filtered.append(r)
        return filtered

class L1Handler(RRFSearchHandler):
    """Execute L1 event store queries with triple-path RRF fusion."""

    layer_name = "L1"

    def __init__(
        self,
        l1_store: Any,
        config: Optional[RetrievalConfig] = None,
        *,
        l2_store: Any = None,
    ) -> None:
        super().__init__(l1_store, config)
        self._l2_store = l2_store

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
        fetch_k = max(conditions.limit * 5, 20)

        # Phase 1: Run 3 core retrieval paths in parallel
        retrieval_coros = [
            self._bm25_path(conditions.content_query, fetch_k, user_id=user_id),
            self._vector_path(conditions.content_query, fetch_k, user_id=user_id),
            self._keyword_path(conditions, fetch_k, session_id=session_id, user_id=user_id),
        ]
        has_temporal = time_range is not None and (time_range.start is not None or time_range.end is not None)
        if has_temporal:
            retrieval_coros.append(
                self._temporal_bm25_path(conditions.content_query, fetch_k, time_range, user_id=user_id),
            )

        results_or_errors = await asyncio.gather(*retrieval_coros, return_exceptions=True)

        bm25_ids: List[str] = results_or_errors[0] if isinstance(results_or_errors[0], list) else []
        vec_ids: List[str] = results_or_errors[1] if isinstance(results_or_errors[1], list) else []
        kw_ids: List[str] = results_or_errors[2] if isinstance(results_or_errors[2], list) else []
        temporal_bm25_ids: List[str] = []
        if has_temporal:
            temporal_bm25_ids = results_or_errors[3] if isinstance(results_or_errors[3], list) else []

        for i, res in enumerate(results_or_errors):
            if isinstance(res, BaseException):
                logger.warning("L1 search path %d failed: %s", i, res)

        logger.info(
            "L1 retrieval paths completed | content_query=%r user_id=%s "
            "bm25_count=%d vec_count=%d kw_count=%d temporal_bm25_count=%d fetch_k=%d",
            conditions.content_query, user_id,
            len(bm25_ids), len(vec_ids), len(kw_ids), len(temporal_bm25_ids), fetch_k,
        )

        # Phase 2: Entity co-occurrence expansion using top seed IDs
        seed_ids: List[str] = list(dict.fromkeys(
            bm25_ids[:10] + vec_ids[:10] + kw_ids[:10] + temporal_bm25_ids[:10]
        ))
        entity_ids: List[str] = []
        if seed_ids:
            try:
                entity_ids = await self._store.expand_by_entities(seed_ids, limit=fetch_k)
            except Exception as exc:
                logger.warning("L1 entity expansion failed: %s", exc)

        if not bm25_ids and not vec_ids and not kw_ids and not entity_ids and not temporal_bm25_ids:
            return []

        cfg = self._config

        # Phase 2b: Graph spreading activation (L2 knowledge graph BFS)
        graph_ids: List[str] = []
        if cfg.graph_spreading_enabled and self._l2_store is not None and seed_ids:
            try:
                graph_ids = await self._graph_spreading_path(seed_ids, fetch_k)
            except Exception as exc:
                logger.warning("L1 graph spreading failed: %s", exc)

        # Phase 3: N-way RRF fusion
        ranked_lists: list[Sequence[str]] = [bm25_ids, vec_ids, kw_ids]
        weights = [cfg.rrf_weight_bm25, cfg.rrf_weight_vector, cfg.rrf_weight_keyword]
        if entity_ids:
            ranked_lists.append(entity_ids)
            weights.append(cfg.rrf_weight_entity)
        if graph_ids:
            ranked_lists.append(graph_ids)
            weights.append(cfg.rrf_weight_graph)
        if temporal_bm25_ids:
            ranked_lists.append(temporal_bm25_ids)
            weights.append(cfg.rrf_weight_bm25)

        fused = rrf_fuse(ranked_lists, weights, k=cfg.rrf_k)
        top_ids = [doc_id for doc_id, _ in fused[:fetch_k]]
        if not top_ids:
            return []

        logger.debug(
            "L1 RRF fusion completed | top_ids_count=%d top_ids_sample=%s",
            len(top_ids), top_ids[:5],
        )

        # Phase 4: Hydrate, filter, rerank
        results = await self._fetch_and_filter(
            event_ids=top_ids, conditions=conditions, time_range=time_range,
            session_id=session_id, user_id=user_id,
        )

        logger.debug(
            "L1 fetch_and_filter completed | input_count=%d output_count=%d "
            "session_id=%s user_id=%s time_range=%s source_filters=%s domain_filters=%s",
            len(top_ids), len(results),
            session_id, user_id, time_range,
            conditions.source_filters, conditions.domain_filters,
        )

        if time_range and results:
            results = self._filter_by_time(results, time_range)

        reranked = await self._reranker.rerank(
            layer=self.layer_name,
            results=results,
            query=conditions.content_query,
            fused_scores=dict(fused),
        )
        final = reranked[:conditions.limit]
        logger.debug(
            "L1 execute returning | reranked_count=%d limit=%d final_count=%d "
            "final_event_ids=%s",
            len(reranked), conditions.limit, len(final),
            [e.get("event_id") for e in final[:5]],
        )
        return final

    async def _graph_spreading_path(self, seed_event_ids: List[str], limit: int) -> List[str]:
        """Graph spreading activation via L2 knowledge graph BFS."""
        from .graph_spreader import GraphSpreader

        cfg = self._config
        spreader = GraphSpreader(
            self._l2_store,
            max_hops=cfg.graph_spreading_max_hops,
            max_neighbors_per_node=cfg.graph_spreading_max_neighbors,
            max_total_entities=cfg.graph_spreading_max_entities,
            decay=cfg.graph_spreading_decay,
        )

        # Resolve seed event_ids → entity_ids via l1_event_entities
        seed_entity_ids: List[str] = []
        try:
            from ...core.sqlite import sqlite_connection_async

            ph = ", ".join("?" for _ in seed_event_ids)
            async with sqlite_connection_async(self._store.db_path) as db:
                async with db.execute(
                    f"SELECT DISTINCT entity_id FROM l1_event_entities WHERE event_id IN ({ph})",
                    tuple(seed_event_ids),
                ) as cursor:
                    seed_entity_ids = [row[0] for row in await cursor.fetchall()]
        except Exception as exc:
            logger.warning("Graph spreading seed resolution failed: %s", exc)
            return []

        if not seed_entity_ids:
            return []

        result = await spreader.spread(
            seed_entity_ids,
            exclude_event_ids=set(seed_event_ids),
        )

        if not result.scored_event_ids:
            # Fall back to discovered entities → l1_event_entities lookup
            if result.discovered_entities:
                try:
                    top_entities = sorted(
                        result.discovered_entities.items(),
                        key=lambda x: x[1],
                        reverse=True,
                    )[:20]
                    entity_ids_to_lookup = [eid for eid, _ in top_entities]
                    from ...core.sqlite import sqlite_connection_async

                    eph = ", ".join("?" for _ in entity_ids_to_lookup)
                    async with sqlite_connection_async(self._store.db_path) as db:
                        async with db.execute(
                            f"SELECT event_id, COUNT(DISTINCT entity_id) AS shared"
                            f" FROM l1_event_entities"
                            f" WHERE entity_id IN ({eph})"
                            f" GROUP BY event_id"
                            f" ORDER BY shared DESC"
                            f" LIMIT ?",
                            (*entity_ids_to_lookup, limit),
                        ) as cursor:
                            rows = await cursor.fetchall()
                    exclude = set(seed_event_ids)
                    return [r[0] for r in rows if r[0] not in exclude][:limit]
                except Exception as exc:
                    logger.warning("Graph spreading entity→event lookup failed: %s", exc)
            return []

        # Sort by activation score descending
        scored = sorted(result.scored_event_ids.items(), key=lambda x: x[1], reverse=True)
        return [eid for eid, _ in scored[:limit]]

    async def _bm25_path(self, query: str, limit: int, *, user_id: Optional[str] = None) -> List[str]:
        """BM25 search via FTS5, optionally scoped to *user_id*."""
        try:
            hits = await self._store.bm25_search(query, limit=limit, user_id=user_id)
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
    ) -> List[str]:
        """Time-constrained BM25 search to boost recall for temporal queries.

        Uses strict matching (exact tokens first, no OR fallback) to avoid
        noise from short prefix stems flooding RRF fusion.
        """
        try:
            hits = await self._store.bm25_search(
                query,
                limit=limit,
                user_id=user_id,
                start_time=time_range.start,
                end_time=time_range.end,
                strict=True,
            )
            return [event_id for event_id, _score in hits]
        except Exception as exc:
            logger.warning("Temporal BM25 path failed: %s", exc)
            return []

    async def _vector_path(self, query: str, limit: int, *, user_id: Optional[str] = None) -> List[str]:
        """Vector similarity search via sqlite-vec.

        Resolves chunk-level entity IDs returned by the vector index back to
        event IDs.  When *user_id* is provided, only events belonging to that
        user are returned (via a post-filter against ``fact_events``).
        """
        try:
            # Over-fetch when user_id filtering will discard cross-namespace hits
            vec_limit = limit * 10 if user_id else limit
            hits = await self._store._semantic_search_event_hits(query=query, limit=vec_limit)
            if not hits:
                return []

            # Resolve chunk_ids (e.g. "evt_xxx::chunk-0") → event_ids ("evt_xxx")
            seen: set[str] = set()
            event_ids: List[str] = []
            for hit in hits:
                eid = hit.entity_id.split("::")[0] if "::" in hit.entity_id else hit.entity_id
                if eid not in seen:
                    seen.add(eid)
                    event_ids.append(eid)

            if user_id and event_ids:
                event_ids = await self._filter_ids_by_user(event_ids, user_id)

            return event_ids
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
    ) -> List[str]:
        """SQL LIKE keyword search via query_events + in-memory token filtering."""
        try:
            events = await self._store.query_events(
                session_id=session_id,
                user_id=user_id,
                event_type=conditions.event_types[0] if conditions.event_types else None,
                source_filters=conditions.source_filters,
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

            query_tokens = [t for t in conditions.content_query.lower().split() if t]
            matched = [
                e["event_id"]
                for e in events
                if all(tok in e.get("content", "").lower() for tok in query_tokens)
            ]
            return matched
        except Exception as exc:
            logger.warning("Keyword path failed: %s", exc)
            return []

    async def _filter_ids_by_user(self, event_ids: List[str], user_id: str) -> List[str]:
        """Return the subset of *event_ids* that belong to *user_id*."""
        if not event_ids:
            return []
        placeholders = ", ".join("?" for _ in event_ids)
        query = (
            f"SELECT event_id FROM fact_events"
            f" WHERE event_id IN ({placeholders}) AND user_id = ? AND deleted_at IS NULL"
        )
        args = [*event_ids, user_id]
        async with sqlite_connection_async(self._store.db_path) as db:
            async with db.execute(query, tuple(args)) as cursor:
                rows = await cursor.fetchall()
        valid = {str(row[0]) for row in rows}
        return [eid for eid in event_ids if eid in valid]

    async def _fetch_and_filter(
        self,
        *,
        event_ids: List[str],
        conditions: L1Conditions,
        time_range: Optional[TimeRange],
        session_id: Optional[str],
        user_id: Optional[str],
    ) -> List[Dict[str, Any]]:
        """Fetch full event dicts for given IDs and apply post-filters."""
        from ..event_contracts import MemoryDomain

        if not event_ids:
            return []

        import aiosqlite

        query = "SELECT * FROM fact_events WHERE deleted_at IS NULL"
        args: list[Any] = []
        placeholders = ", ".join("?" for _ in event_ids)
        query += f" AND event_id IN ({placeholders})"
        args.extend(event_ids)

        if session_id:
            query += " AND session_id = ?"
            args.append(session_id)
        if user_id:
            query += " AND user_id = ?"
            args.append(user_id)
        if conditions.event_types:
            et_ph = ", ".join("?" for _ in conditions.event_types)
            query += f" AND event_type IN ({et_ph})"
            args.extend(conditions.event_types)
        if conditions.source_filters:
            sf_ph = ", ".join("?" for _ in conditions.source_filters)
            query += f" AND source IN ({sf_ph})"
            args.extend(conditions.source_filters)
        if conditions.domain_filters:
            domain_ints = []
            for df in conditions.domain_filters:
                try:
                    domain_ints.append(int(MemoryDomain.from_value(df)))
                except (ValueError, KeyError):
                    pass
            if domain_ints:
                df_ph = ", ".join("?" for _ in domain_ints)
                query += f" AND memory_domain IN ({df_ph})"
                args.extend(domain_ints)
        else:
            query += " AND memory_domain != ?"
            args.append(int(MemoryDomain.RUNTIME_TELEMETRY))

        # Temporal pre-filter: push time_range into SQL to avoid
        # wasting hydration slots on out-of-range events.
        if time_range:
            if time_range.start is not None:
                query += " AND timestamp >= ?"
                args.append(time_range.start)
            if time_range.end is not None:
                query += " AND timestamp <= ?"
                args.append(time_range.end)

        async with sqlite_connection_async(self._store.db_path) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute(query, tuple(args)) as cursor:
                rows = await cursor.fetchall()

        events_by_id = {str(row["event_id"]): self._store._row_to_dict(row) for row in rows}

        # Preserve RRF rank ordering
        results = [events_by_id[eid] for eid in event_ids if eid in events_by_id]

        # Time range post-filter
        if time_range and results:
            results = self._filter_by_time(results, time_range)

        return results

class L2Handler:
    """Execute L2 knowledge graph queries from structured conditions."""

    def __init__(
        self,
        l2_store: Any,
        entity_catalog: Any | None = None,
        embedding_service: Any | None = None,
        edge_vector_index: Any | None = None,
    ) -> None:
        self._store = l2_store
        self._entity_catalog = entity_catalog
        self._embedding_service = embedding_service
        self._edge_vector_index = edge_vector_index

    async def execute(
        self,
        conditions: L2Conditions,
        time_range: Optional[TimeRange] = None,
        *,
        user_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Query L2 for entity cards and relationships."""
        del time_range
        results: Dict[str, Any] = {"entity_cards": [], "relationships": [], "assertions": [], "trace": {}}
        resolved_entities = await self._resolve_entities(conditions, user_id=user_id)
        predicate_family = conditions.predicate_family or "unknown"
        predicates = conditions.predicates or self._predicates_for_family(predicate_family)
        status_filters = conditions.status_filter or self._infer_status_filters(conditions.content_query)
        relation_direction = conditions.relation_direction or self._infer_relation_direction(conditions.content_query)
        semantic_frame = conditions.semantic_frame
        query_frame = self._build_query_frame(
            conditions=conditions,
            resolved_entities=resolved_entities,
            predicates=predicates,
            predicate_family=predicate_family,
            user_id=user_id,
            relation_direction=relation_direction,
        )
        target_entity_id = self._infer_target_entity_id(
            query_frame=query_frame,
            predicate_family=predicate_family,
        )

        snapshot_entities = query_frame["snapshot_entities"] or resolved_entities
        if conditions.include_tom_snapshot and snapshot_entities:
            results["entity_cards"] = await self._store.batch_get_tom_snapshots(
                entities=snapshot_entities,
            )

        if conditions.include_assertions:
            assertion_entities = query_frame["assertion_entities"] or resolved_entities
            trait_families = conditions.trait_families or self._infer_trait_families(predicate_family)
            if assertion_entities:
                batch_assertions = await self._store.batch_list_tom_assertions(
                    entity_ids=[e["entity_id"] for e in assertion_entities],
                    trait_families=trait_families,
                    validation_states=self._infer_assertion_states(status_filters),
                    include_expired=False,
                    target_entity_id=target_entity_id,
                    limit_per_entity=conditions.limit,
                )
                for assertions in batch_assertions.values():
                    results["assertions"].extend(assertions)
            else:
                results["assertions"] = await self._store.list_tom_assertions(
                    trait_families=trait_families,
                    validation_states=self._infer_assertion_states(status_filters),
                    include_expired=False,
                    target_entity_id=target_entity_id,
                    limit=conditions.limit,
                )

        if conditions.include_relationships:
            semantic_relationships = await self._execute_semantic_relationship_plan(
                conditions=conditions,
                semantic_frame=semantic_frame,
                status_filters=status_filters,
                user_id=user_id,
                resolved_entities=resolved_entities,
            )
            if semantic_relationships is not None:
                results["relationships"] = semantic_relationships
                if semantic_frame is not None:
                    predicates = self._predicates_for_semantic_frame(semantic_frame)
            else:
                relationship_entities = query_frame["relationship_entities"] or resolved_entities
                if relationship_entities:
                    entity_ids = [e["entity_id"] for e in relationship_entities]
                    all_user = all(e.get("entity_type") == "user" for e in relationship_entities)
                    apply_object_filter = all_user and relation_direction == "outgoing"
                    batch_rels = await self._store.batch_get_relationships(
                        entity_ids=entity_ids,
                        direction=relation_direction,
                        status_filters=status_filters,
                        predicates=predicates,
                        target_object_id=query_frame["relationship_object_id"] if apply_object_filter else None,
                        object_types=query_frame["relationship_object_types"] if apply_object_filter else None,
                        limit_per_entity=conditions.limit,
                    )
                    seen: set[str] = set()
                    for rels in batch_rels.values():
                        for rel in rels:
                            triple_id = str(rel.get("triple_id") or "")
                            if triple_id and triple_id in seen:
                                continue
                            if triple_id:
                                seen.add(triple_id)
                            results["relationships"].append(rel)
                else:
                    rels = await self._store.get_relationships(
                        predicates=predicates,
                        status_filters=status_filters,
                        limit=conditions.limit,
                    )
                    results["relationships"] = rels

        edge_vector_supplement_count = 0
        if conditions.include_relationships and conditions.content_query:
            vector_edges = await self._supplement_edge_vector_search(
                content_query=conditions.content_query,
                existing_relationships=results["relationships"],
                status_filters=status_filters,
                predicates=None,
                predicate_boost_groups=self._collect_boost_groups(predicates),
                limit=conditions.limit,
            )
            if vector_edges:
                results["relationships"].extend(vector_edges)
                edge_vector_supplement_count = len(vector_edges)

        results["trace"] = {
            "content_query": conditions.content_query,
            "requested_entities": [
                entity["entity_id"] for entity in resolved_entities
            ] if resolved_entities else list(conditions.entities or []),
            "subject_hint": conditions.subject_hint or "none",
            "predicate_family": predicate_family,
            "requested_entity_types": list(conditions.entity_types or []),
            "trait_families": list(conditions.trait_families or []),
            "semantic_frame": asdict(semantic_frame) if semantic_frame is not None else None,
            "include_tom_snapshot": conditions.include_tom_snapshot,
            "include_relationships": conditions.include_relationships,
            "include_assertions": conditions.include_assertions,
            "limit": conditions.limit,
            "resolved_entities": resolved_entities,
            "query_frame": query_frame,
            "predicates": predicates or [],
            "status_filters": status_filters or [],
            "relation_direction": relation_direction,
            "target_entity_id": target_entity_id,
            "relationship_object_id": query_frame["relationship_object_id"],
            "relationship_object_types": query_frame["relationship_object_types"],
            "entity_card_count": len(results["entity_cards"]),
            "relationship_count": len(results["relationships"]),
            "assertion_count": len(results["assertions"]),
            "edge_vector_supplement_count": edge_vector_supplement_count,
        }
        logger.info(
            "L2 retrieval executed | content_query=%r requested_entities=%s resolved_entities=%s subject_hint=%s "
            "predicate_family=%s predicates=%s status_filters=%s relation_direction=%s target_entity_id=%s "
            "relationship_object_id=%s relationship_object_types=%s include_tom_snapshot=%s "
            "include_relationships=%s include_assertions=%s limit=%s entity_card_count=%s "
            "relationship_count=%s assertion_count=%s",
            conditions.content_query,
            results["trace"]["requested_entities"],
            resolved_entities,
            conditions.subject_hint or "none",
            predicate_family,
            predicates or [],
            status_filters or [],
            relation_direction,
            target_entity_id,
            query_frame["relationship_object_id"],
            query_frame["relationship_object_types"],
            conditions.include_tom_snapshot,
            conditions.include_relationships,
            conditions.include_assertions,
            conditions.limit,
            len(results["entity_cards"]),
            len(results["relationships"]),
            len(results["assertions"]),
        )
        return results

    async def _execute_semantic_relationship_plan(
        self,
        *,
        conditions: L2Conditions,
        semantic_frame: L2SemanticFrame | None,
        status_filters: list[str] | None,
        user_id: Optional[str],
        resolved_entities: list[dict[str, str]],
    ) -> list[dict[str, Any]] | None:
        if semantic_frame is None:
            return None
        if semantic_frame.query_family != "affinity":
            return None
        if semantic_frame.subject_scope != "self" or not user_id:
            return None

        if semantic_frame.answer_kind == "creator":
            return await self._execute_creator_affinity_relationship_plan(
                conditions=conditions,
                semantic_frame=semantic_frame,
                status_filters=status_filters,
                user_id=user_id,
            )
        if semantic_frame.answer_kind == "place":
            return await self._execute_place_affinity_relationship_plan(
                conditions=conditions,
                semantic_frame=semantic_frame,
                status_filters=status_filters,
                user_id=user_id,
            )
        if semantic_frame.answer_kind == "software":
            return await self._execute_software_affinity_relationship_plan(
                conditions=conditions,
                semantic_frame=semantic_frame,
                status_filters=status_filters,
                user_id=user_id,
                resolved_entities=resolved_entities,
            )
        if semantic_frame.answer_kind == "topic":
            return await self._execute_topic_affinity_relationship_plan(
                conditions=conditions,
                semantic_frame=semantic_frame,
                status_filters=status_filters,
                user_id=user_id,
            )
        return None

    async def _execute_creator_affinity_relationship_plan(
        self,
        *,
        conditions: L2Conditions,
        semantic_frame: L2SemanticFrame,
        status_filters: list[str] | None,
        user_id: str,
    ) -> list[dict[str, Any]] | None:
        platform_constraint = self._find_constraint(semantic_frame.constraints, scope="target", facet="platform")
        if platform_constraint is None:
            platform_constraint = self._find_constraint(semantic_frame.constraints, scope="interaction", facet="platform")
        platform_entity_id = platform_constraint.resolved_entity_id if platform_constraint else None
        if not platform_entity_id:
            return await self._store.get_relationships(
                subject_id=f"user:{user_id}",
                predicates=self._predicates_for_semantic_frame(semantic_frame),
                object_types=["presence", "person"],
                status_filters=status_filters,
                limit=conditions.limit,
            )

        topology_edges = await self._store.get_relationships(
            predicates=["ON_PLATFORM"],
            object_id=platform_entity_id,
            status_filters=status_filters,
            limit=max(conditions.limit * 5, 20),
        )
        candidate_ids = self._collect_candidate_subject_ids(topology_edges)
        if not candidate_ids:
            return []

        relationships: list[dict[str, Any]] = []
        predicates = self._predicates_for_semantic_frame(semantic_frame)
        for candidate_id in candidate_ids:
            relationships.extend(
                await self._store.get_relationships(
                    subject_id=f"user:{user_id}",
                    object_id=candidate_id,
                    predicates=predicates,
                    status_filters=status_filters,
                    limit=conditions.limit,
                )
            )
        deduped = self._dedupe_relationships(relationships)
        if semantic_frame.answer_unit == "identity":
            return await self._lift_creator_presence_relationships(deduped)
        return deduped

    async def _execute_place_affinity_relationship_plan(
        self,
        *,
        conditions: L2Conditions,
        semantic_frame: L2SemanticFrame,
        status_filters: list[str] | None,
        user_id: str,
    ) -> list[dict[str, Any]] | None:
        target_location_constraint = self._find_constraint(semantic_frame.constraints, scope="target", facet="located_in")
        interaction_location_constraint = self._find_constraint(
            semantic_frame.constraints,
            scope="interaction",
            facet="located_in",
        )
        target_location_entity_id = target_location_constraint.resolved_entity_id if target_location_constraint else None
        interaction_location_entity_id = (
            interaction_location_constraint.resolved_entity_id if interaction_location_constraint else None
        )

        if interaction_location_entity_id:
            evidence_relationships = await self._store.get_relationships(
                subject_id=f"user:{user_id}",
                predicates=self._predicates_for_semantic_frame(semantic_frame),
                object_types=["place"],
                status_filters=status_filters,
                limit=max(conditions.limit * 5, 20),
            )
            candidate_ids = self._collect_candidate_object_ids(evidence_relationships)
            topology_edges = await self._store.get_relationships(
                predicates=["LOCATED_IN"],
                object_id=interaction_location_entity_id,
                status_filters=status_filters,
                limit=max(conditions.limit * 5, 20),
            )
            location_ids = set(self._collect_candidate_subject_ids(topology_edges))
            candidate_ids = [candidate_id for candidate_id in candidate_ids if candidate_id in location_ids]
            category_constraint = self._find_constraint(semantic_frame.constraints, scope="target", facet="category")
            category_value = category_constraint.resolved_facet_value if category_constraint else None
            if candidate_ids and category_value:
                candidate_ids = await self._store.filter_entity_ids_by_facet(
                    entity_ids=candidate_ids,
                    facet_name="category",
                    facet_values=[category_value],
                )
            if not candidate_ids:
                return []
            return self._dedupe_relationships(
                [
                    relationship
                    for relationship in evidence_relationships
                    if str(relationship.get("object_id") or "").strip() in set(candidate_ids)
                ]
            )

        if not target_location_entity_id:
            return await self._store.get_relationships(
                subject_id=f"user:{user_id}",
                predicates=self._predicates_for_semantic_frame(semantic_frame),
                object_types=["place"],
                status_filters=status_filters,
                limit=conditions.limit,
            )

        topology_edges = await self._store.get_relationships(
            predicates=["LOCATED_IN"],
            object_id=target_location_entity_id,
            status_filters=status_filters,
            limit=max(conditions.limit * 5, 20),
        )
        candidate_ids = self._collect_candidate_subject_ids(topology_edges)
        category_constraint = self._find_constraint(semantic_frame.constraints, scope="target", facet="category")
        category_value = category_constraint.resolved_facet_value if category_constraint else None
        if candidate_ids and category_value:
            candidate_ids = await self._store.filter_entity_ids_by_facet(
                entity_ids=candidate_ids,
                facet_name="category",
                facet_values=[category_value],
            )
        if not candidate_ids:
            return []

        relationships: list[dict[str, Any]] = []
        predicates = self._predicates_for_semantic_frame(semantic_frame)
        for candidate_id in candidate_ids:
            relationships.extend(
                await self._store.get_relationships(
                    subject_id=f"user:{user_id}",
                    object_id=candidate_id,
                    predicates=predicates,
                    status_filters=status_filters,
                    limit=conditions.limit,
                )
            )
        return self._dedupe_relationships(relationships)

    async def _execute_software_affinity_relationship_plan(
        self,
        *,
        conditions: L2Conditions,
        semantic_frame: L2SemanticFrame,
        status_filters: list[str] | None,
        user_id: str,
        resolved_entities: list[dict[str, str]],
    ) -> list[dict[str, Any]] | None:
        target_entity_id = self._select_semantic_target_entity_id(
            semantic_frame=semantic_frame,
            resolved_entities=resolved_entities,
        )
        if not target_entity_id:
            return await self._store.get_relationships(
                subject_id=f"user:{user_id}",
                predicates=self._predicates_for_semantic_frame(semantic_frame),
                object_types=["software"],
                status_filters=status_filters,
                limit=conditions.limit,
            )
        return await self._store.get_relationships(
            subject_id=f"user:{user_id}",
            object_id=target_entity_id,
            predicates=self._predicates_for_semantic_frame(semantic_frame),
            status_filters=status_filters,
            limit=conditions.limit,
        )

    async def _execute_topic_affinity_relationship_plan(
        self,
        *,
        conditions: L2Conditions,
        semantic_frame: L2SemanticFrame,
        status_filters: list[str] | None,
        user_id: str,
    ) -> list[dict[str, Any]] | None:
        return await self._store.get_relationships(
            subject_id=f"user:{user_id}",
            predicates=self._predicates_for_semantic_frame(semantic_frame),
            object_types=["topic"],
            status_filters=status_filters,
            limit=conditions.limit,
        )

    async def _query_relationships_for_entity(
        self,
        *,
        entity_id: str,
        entity_type: str,
        direction: str,
        predicates: list[str] | None,
        status_filters: list[str] | None,
        object_id: str | None,
        object_types: list[str] | None,
        limit: int,
    ) -> list[dict[str, Any]]:
        if direction == "incoming":
            return await self._store.get_relationships(
                object_id=entity_id,
                predicates=predicates,
                status_filters=status_filters,
                limit=limit,
            )
        if direction == "both":
            outgoing = await self._store.get_relationships(
                subject_id=entity_id,
                predicates=predicates,
                status_filters=status_filters,
                object_id=object_id,
                object_types=object_types,
                limit=limit,
            )
            incoming = await self._store.get_relationships(
                object_id=entity_id,
                predicates=predicates,
                status_filters=status_filters,
                limit=limit,
            )
            seen: set[str] = set()
            merged: list[dict[str, Any]] = []
            for item in outgoing + incoming:
                triple_id = str(item.get("triple_id") or "")
                if triple_id and triple_id in seen:
                    continue
                if triple_id:
                    seen.add(triple_id)
                merged.append(item)
            return merged
        return await self._store.get_relationships(
            subject_id=entity_id,
            predicates=predicates,
            status_filters=status_filters,
            object_id=object_id if self._allows_object_id_filter(entity_type=entity_type, direction=direction) else None,
            object_types=object_types if self._allows_object_type_filter(entity_type=entity_type, direction=direction) else None,
            limit=limit,
        )

    @staticmethod
    def _collect_boost_groups(predicates: list[str] | None) -> set[str] | None:
        """Collect synonym groups from predicates for soft re-ranking."""
        if not predicates:
            return None
        from ...memory.l2.ontology import get_predicate_synonym_group

        groups: set[str] = set()
        for pred in predicates:
            group = get_predicate_synonym_group(pred)
            if group:
                groups.add(group)
        return groups or None

    async def _supplement_edge_vector_search(
        self,
        *,
        content_query: str,
        existing_relationships: list[dict[str, Any]],
        status_filters: list[str] | None,
        predicates: list[str] | None,
        predicate_boost_groups: set[str] | None = None,
        limit: int,
    ) -> list[dict[str, Any]]:
        """Return additional edges found via vector similarity that are not already present.

        Predicates are NOT used as hard filters.  Instead, edges whose
        predicate belongs to one of *predicate_boost_groups* receive a
        distance bonus so they rank higher.
        """
        if self._embedding_service is None or self._edge_vector_index is None:
            return []
        query_text = content_query.strip()
        if not query_text:
            return []
        try:
            embedding = await self._embedding_service.embed_text(query_text)
            if embedding is None:
                return []
            candidates = await self._store.search_edges_by_embedding(
                vector_index=self._edge_vector_index,
                embedding=embedding,
                limit=limit,
                status_filters=status_filters,
                predicates=predicates,
            )
        except Exception as exc:
            logger.debug("Edge vector supplement failed: %s", exc)
            return []
        if not candidates:
            return []

        if predicate_boost_groups:
            from ...memory.l2.ontology import get_predicate_synonym_group

            for edge in candidates:
                group = get_predicate_synonym_group(str(edge.get("predicate") or ""))
                if group and group in predicate_boost_groups:
                    dist = edge.get("vector_distance")
                    if dist is not None:
                        edge["vector_distance"] = dist * 0.7
            candidates.sort(key=lambda e: e.get("vector_distance") or float("inf"))

        existing_ids = {str(r.get("triple_id") or "") for r in existing_relationships}
        novel = [c for c in candidates if str(c.get("triple_id") or "") not in existing_ids]
        return novel

    async def _resolve_entities(
        self,
        conditions: L2Conditions,
        *,
        user_id: Optional[str] = None,
    ) -> list[dict[str, str]]:
        resolved: list[dict[str, str]] = []
        seen: set[str] = set()

        for entity in conditions.entities or []:
            normalized = str(entity).strip()
            if not normalized:
                continue
            if ":" in normalized:
                entity_type, _, _ = normalized.partition(":")
                if normalized not in seen:
                    resolved.append({"entity_id": normalized, "entity_type": entity_type or "entity", "match_source": "explicit"})
                    seen.add(normalized)
                continue
            if self._entity_catalog is None:
                continue
            matches = await self._entity_catalog.resolve_query_entities(
                normalized,
                limit=5,
                entity_types=conditions.entity_types,
            )
            for match in matches:
                entity_id = str(match["entity_id"])
                if entity_id in seen:
                    continue
                resolved.append({
                    "entity_id": entity_id,
                    "entity_type": str(match["entity_type"]),
                    "match_source": str(match.get("match_source") or "unknown"),
                })
                seen.add(entity_id)

        if resolved or self._entity_catalog is None or not conditions.content_query:
            return resolved

        # When subject_hint is "self" with an unknown predicate family, the
        # user entity is the subject and the answer (object) is completely
        # unknown.  Skip content_query vector search to avoid resolving
        # irrelevant entities that would wrongly filter outgoing edges.
        # For known families like "preference", target resolution is still
        # valuable (e.g. "Do I like sushi?" → resolve "sushi").
        if conditions.subject_hint == "self" and (
            not conditions.predicate_family
            or conditions.predicate_family == "unknown"
        ):
            return resolved

        query_matches = await self._entity_catalog.resolve_query_entities(
            conditions.content_query,
            limit=max(conditions.limit, 5),
            entity_types=conditions.entity_types,
        )
        for match in query_matches:
            entity_id = str(match["entity_id"])
            if entity_id in seen:
                continue
            resolved.append({
                "entity_id": entity_id,
                "entity_type": str(match["entity_type"]),
                "match_source": str(match.get("match_source") or "unknown"),
            })
            seen.add(entity_id)
        return resolved

    @staticmethod
    def _predicates_for_family(family: str) -> list[str] | None:
        """Derive predicate list from predicate_family via the canonical ontology."""
        from ...memory.l2.ontology import predicates_for_family

        return predicates_for_family(family)

    @staticmethod
    def _predicates_for_semantic_frame(semantic_frame: L2SemanticFrame) -> list[str]:
        if semantic_frame.query_family == "affinity" and semantic_frame.answer_kind == "creator":
            return ["FOLLOWS", "LIKES", "DISLIKES", "INTERESTED_IN"]
        if semantic_frame.query_family == "affinity" and semantic_frame.answer_kind == "place":
            return ["VISITED", "LIKES", "DISLIKES"]
        if semantic_frame.query_family == "affinity" and semantic_frame.answer_kind == "software":
            return ["USES", "LIKES", "DISLIKES"]
        if semantic_frame.query_family == "affinity" and semantic_frame.answer_kind == "topic":
            return ["INTERESTED_IN", "LIKES", "DISLIKES"]
        return []

    def _infer_status_filters(self, query: str) -> list[str]:
        query_lower = query.lower()
        if "冲突" in query_lower or "conflict" in query_lower:
            return ["conflicted"]
        return ["active", "conflicted"]

    def _infer_relation_direction(self, query: str) -> str:
        query_lower = query.lower()
        if "谁认识我" in query or "who knows me" in query_lower:
            return "incoming"
        if "关系" in query or "relationship" in query_lower:
            return "both"
        return "outgoing"

    def _infer_assertion_states(self, status_filters: list[str] | None) -> list[str] | None:
        if not status_filters:
            return ["stable", "corroborated", "tentative"]
        if status_filters == ["conflicted"]:
            return ["contradicted"]
        return ["stable", "corroborated", "tentative"]

    def _infer_trait_families(self, predicate_family: str) -> list[str] | None:
        if predicate_family == "preference":
            return ["preference_profile"]
        return None

    def _infer_target_entity_id(
        self,
        *,
        query_frame: dict[str, Any],
        predicate_family: str,
    ) -> str | None:
        if predicate_family != "preference":
            return None
        if query_frame["target_entity_id_exact"]:
            return str(query_frame["target_entity_id_exact"])
        return None

    @staticmethod
    def _make_self_entity(user_id: str) -> dict[str, str]:
        return {"entity_id": f"user:{user_id}", "entity_type": "user"}

    def _build_query_frame(
        self,
        *,
        conditions: L2Conditions,
        resolved_entities: list[dict[str, str]],
        predicates: list[str] | None,
        predicate_family: str,
        user_id: Optional[str],
        relation_direction: str,
    ) -> dict[str, Any]:
        explicit_entities = [dict(entity) for entity in resolved_entities]
        subject_entities: list[dict[str, str]] = []
        target_entities: list[dict[str, str]] = []
        subject_binding_source = "none"

        if conditions.subject_hint == "self" and user_id:
            subject_entities = [self._make_self_entity(user_id)]
            target_entities = self._filter_target_entities_for_family(
                entities=explicit_entities,
                predicate_family=predicate_family,
            )
            subject_binding_source = "self_anchor"
        elif conditions.subject_hint == "explicit" and explicit_entities:
            subject_entities = [dict(explicit_entities[0])]
            target_entities = self._filter_target_entities_for_family(
                entities=[dict(entity) for entity in explicit_entities[1:]],
                predicate_family=predicate_family,
            )
            subject_binding_source = "explicit_entity"
        elif explicit_entities:
            subject_entities = [dict(entity) for entity in explicit_entities]
            subject_binding_source = "resolved_entity"

        if relation_direction == "incoming" and user_id:
            subject_entities = [self._make_self_entity(user_id)]
            target_entities = explicit_entities
            subject_binding_source = "self_anchor"

        relationship_entities = subject_entities or explicit_entities
        snapshot_entities = subject_entities or explicit_entities
        assertion_entities = subject_entities or explicit_entities

        target_entity_id_exact = self._select_exact_target_entity_id(
            conditions=conditions,
            predicate_family=predicate_family,
            target_entities=target_entities,
        )
        relationship_object_types = self._select_target_entity_types(
            conditions=conditions,
            predicate_family=predicate_family,
            target_entities=target_entities,
        )
        relationship_object_id = target_entity_id_exact
        if relationship_object_id is not None and relationship_object_types:
            relationship_object_types = None

        chosen_subject_entity_id = subject_entities[0]["entity_id"] if subject_entities else None
        chosen_target_entity_id = target_entities[0]["entity_id"] if target_entities else None
        return {
            "subject_entities": subject_entities,
            "target_entities": target_entities,
            "relationship_entities": relationship_entities,
            "snapshot_entities": snapshot_entities,
            "assertion_entities": assertion_entities,
            "chosen_subject_entity_id": chosen_subject_entity_id,
            "chosen_target_entity_id": chosen_target_entity_id,
            "subject_binding_source": subject_binding_source,
            "target_entity_id_exact": target_entity_id_exact,
            "relationship_object_id": relationship_object_id,
            "relationship_object_types": relationship_object_types,
        }

    def _filter_target_entities_for_family(
        self,
        *,
        entities: list[dict[str, str]],
        predicate_family: str,
    ) -> list[dict[str, str]]:
        if predicate_family != "preference":
            return [dict(entity) for entity in entities]
        filtered = [
            dict(entity)
            for entity in entities
            if str(entity.get("entity_type") or "").strip() not in {"person", "user"}
        ]
        return filtered or [dict(entity) for entity in entities]

    def _select_exact_target_entity_id(
        self,
        *,
        conditions: L2Conditions,
        predicate_family: str,
        target_entities: list[dict[str, str]],
    ) -> str | None:
        if not target_entities:
            return None
        if predicate_family != "preference":
            return str(target_entities[0]["entity_id"])
        for entity in target_entities:
            # Vector-only resolution is unreliable for exact target filtering.
            if str(entity.get("match_source") or "") == "vector":
                continue
            if not self._is_generic_entity_ref(entity):
                return str(entity["entity_id"])
        return None

    def _select_target_entity_types(
        self,
        *,
        conditions: L2Conditions,
        predicate_family: str,
        target_entities: list[dict[str, str]],
    ) -> list[str] | None:
        if predicate_family != "preference" or not target_entities:
            return None
        # When all target entities came from vector-only resolution, skip
        # type filtering to avoid excluding valid results.
        if all(str(e.get("match_source") or "") == "vector" for e in target_entities):
            return None
        types: list[str] = []
        for entity in target_entities:
            entity_type = str(entity.get("entity_type") or "").strip()
            if entity_type and entity_type not in types:
                types.append(entity_type)
        return types or None

    @staticmethod
    def _is_generic_entity_ref(entity: dict[str, str]) -> bool:
        """Detect generic/category entities structurally.

        An entity is generic when its ID suffix is (a substring of) its type
        name or vice-versa, e.g. ``weather_state:weather``, ``food:food``.
        Specific instances like ``weather_state:rainy-hangzhou`` won't match.
        """
        entity_id = str(entity.get("entity_id") or "")
        entity_type = str(entity.get("entity_type") or "")
        if not entity_id or not entity_type:
            return False
        _, _, suffix = entity_id.partition(":")
        if not suffix:
            return False
        normalized_suffix = suffix.replace("_", "-").casefold()
        normalized_type = entity_type.replace("_", "-").casefold()
        return normalized_suffix in normalized_type or normalized_type in normalized_suffix

    @staticmethod
    def _allows_object_id_filter(*, entity_type: str, direction: str) -> bool:
        return direction == "outgoing" and entity_type == "user"

    @staticmethod
    def _allows_object_type_filter(*, entity_type: str, direction: str) -> bool:
        return direction == "outgoing" and entity_type == "user"

    @staticmethod
    def _find_constraint(
        constraints: list[SemanticConstraint],
        *,
        scope: str,
        facet: str,
    ) -> SemanticConstraint | None:
        for constraint in constraints:
            if constraint.scope == scope and constraint.facet == facet:
                return constraint
        return None

    @staticmethod
    def _collect_candidate_subject_ids(relationships: list[dict[str, Any]]) -> list[str]:
        seen: set[str] = set()
        candidates: list[str] = []
        for relationship in relationships:
            subject_id = str(relationship.get("subject_id") or "").strip()
            if subject_id and subject_id not in seen:
                seen.add(subject_id)
                candidates.append(subject_id)
        return candidates

    @staticmethod
    def _collect_candidate_object_ids(relationships: list[dict[str, Any]]) -> list[str]:
        seen: set[str] = set()
        candidates: list[str] = []
        for relationship in relationships:
            object_id = str(relationship.get("object_id") or "").strip()
            if object_id and object_id not in seen:
                seen.add(object_id)
                candidates.append(object_id)
        return candidates

    @staticmethod
    def _dedupe_relationships(relationships: list[dict[str, Any]]) -> list[dict[str, Any]]:
        seen: set[str] = set()
        deduped: list[dict[str, Any]] = []
        for relationship in relationships:
            triple_id = str(relationship.get("triple_id") or "").strip()
            key = triple_id or (
                f"{relationship.get('subject_id')}:"
                f"{relationship.get('predicate')}:"
                f"{relationship.get('object_id')}"
            )
            if key in seen:
                continue
            seen.add(key)
            deduped.append(relationship)
        return deduped

    async def _lift_creator_presence_relationships(
        self,
        relationships: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        lifted: list[dict[str, Any]] = []
        presence_cache: dict[str, dict[str, Any] | None] = {}

        for relationship in relationships:
            object_id = str(relationship.get("object_id") or "").strip()
            object_type = str(relationship.get("object_type") or "").strip()
            if object_type != "presence" or not object_id:
                lifted.append(relationship)
                continue

            if object_id not in presence_cache:
                presence_edges = await self._store.get_relationships(
                    subject_id=object_id,
                    predicates=["PRESENCE_OF"],
                    limit=1,
                )
                presence_cache[object_id] = presence_edges[0] if presence_edges else None

            presence_edge = presence_cache[object_id]
            if not presence_edge:
                lifted.append(relationship)
                continue

            lifted_relationship = dict(relationship)
            lifted_relationship["object_id"] = presence_edge.get("object_id")
            lifted_relationship["object_type"] = presence_edge.get("object_type")
            lifted_relationship["object"] = presence_edge.get("object_id")
            lifted.append(lifted_relationship)

        return lifted

    @staticmethod
    def _select_semantic_target_entity_id(
        *,
        semantic_frame: L2SemanticFrame,
        resolved_entities: list[dict[str, str]],
    ) -> str | None:
        expected_type = semantic_frame.answer_kind
        for entity in resolved_entities:
            entity_type = str(entity.get("entity_type") or "").strip()
            if entity_type != expected_type:
                continue
            if str(entity.get("match_source") or "") == "vector":
                continue
            entity_id = str(entity.get("entity_id") or "").strip()
            if entity_id:
                return entity_id
        return None


class L3Handler(RRFSearchHandler):
    """Execute L3 summary store queries with triple-path RRF fusion."""

    layer_name = "L3"

    def __init__(self, l3_store: Any, config: Optional[RetrievalConfig] = None) -> None:
        super().__init__(l3_store, config)

    async def execute(
        self,
        conditions: L3Conditions,
        time_range: Optional[TimeRange] = None,
    ) -> List[Dict[str, Any]]:
        """Query L3 using BM25 + vector + keyword, fused via RRF."""
        if not conditions.content_query:
            return []
        summary_type = conditions.summary_types[0] if conditions.summary_types else None
        summary_category = conditions.summary_categories[0] if conditions.summary_categories else None
        fetch_k = max(conditions.limit * 5, 20)
        return await self._rrf_execute(
            content_query=conditions.content_query,
            limit=conditions.limit,
            bm25_coro=self._bm25_path(conditions.content_query, summary_type, summary_category, fetch_k),
            vector_coro=self._vector_path(conditions.content_query, summary_type, summary_category, fetch_k),
            keyword_coro=self._keyword_path(conditions.content_query, summary_type, summary_category, fetch_k),
            hydrate_coro_fn=lambda ids: self._fetch_by_ids(ids, summary_type, summary_category),
            time_range=time_range,
        )

    async def _bm25_path(
        self,
        query: str,
        summary_type: Optional[str],
        summary_category: Optional[str],
        limit: int,
    ) -> List[str]:
        try:
            hits = await self._store.bm25_search(
                query,
                summary_type=summary_type,
                summary_category=summary_category,
                limit=limit,
            )
            return [sid for sid, _score in hits]
        except Exception as exc:
            logger.warning("L3 BM25 path failed: %s", exc)
            return []

    async def _vector_path(
        self,
        query: str,
        summary_type: Optional[str],
        summary_category: Optional[str],
        limit: int,
    ) -> List[str]:
        try:
            results = await self._store._semantic_search_summaries(
                query=query,
                summary_type=summary_type,
                summary_category=summary_category,
                limit=limit,
            )
            return [r["summary_id"] for r in results]
        except Exception as exc:
            logger.warning("L3 vector path failed: %s", exc)
            return []

    async def _keyword_path(
        self,
        query: str,
        summary_type: Optional[str],
        summary_category: Optional[str],
        limit: int,
    ) -> List[str]:
        try:
            import aiosqlite

            sql = "SELECT summary_id FROM summaries WHERE content LIKE ?"
            args: list[Any] = [f"%{query}%"]
            if summary_type:
                sql += " AND summary_type = ?"
                args.append(summary_type)
            if summary_category:
                sql += " AND summary_category = ?"
                args.append(summary_category)
            sql += " ORDER BY updated_at DESC LIMIT ?"
            args.append(limit)
            async with sqlite_connection_async(self._store.db_path) as db:
                async with db.execute(sql, tuple(args)) as cursor:
                    rows = await cursor.fetchall()
            return [str(row[0]) for row in rows]
        except Exception as exc:
            logger.warning("L3 keyword path failed: %s", exc)
            return []

    async def _fetch_by_ids(
        self,
        summary_ids: List[str],
        summary_type: Optional[str],
        summary_category: Optional[str],
    ) -> List[Dict[str, Any]]:
        if not summary_ids:
            return []
        import aiosqlite

        placeholders = ", ".join("?" for _ in summary_ids)
        sql = f"SELECT * FROM summaries WHERE summary_id IN ({placeholders})"
        args: list[Any] = list(summary_ids)
        if summary_type:
            sql += " AND summary_type = ?"
            args.append(summary_type)
        if summary_category:
            sql += " AND summary_category = ?"
            args.append(summary_category)
        async with sqlite_connection_async(self._store.db_path) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute(sql, tuple(args)) as cursor:
                rows = await cursor.fetchall()
        by_id = {str(row["summary_id"]): self._store._row_to_dict(row) for row in rows}
        return [by_id[sid] for sid in summary_ids if sid in by_id]

    @staticmethod
    def _filter_by_time(results: List[Dict[str, Any]], time_range: TimeRange) -> List[Dict[str, Any]]:
        filtered = []
        for r in results:
            if time_range.start and r.get("period_end", 0) < time_range.start:
                continue
            if time_range.end and r.get("period_start", float("inf")) > time_range.end:
                continue
            filtered.append(r)
        return filtered


class L4Handler(RRFSearchHandler):
    """Execute L4 procedural memory queries with triple-path RRF fusion."""

    layer_name = "L4"

    def __init__(self, l4_store: Any, config: Optional[RetrievalConfig] = None) -> None:
        super().__init__(l4_store, config)

    async def execute(
        self,
        conditions: L4Conditions,
        time_range: Optional[TimeRange] = None,
    ) -> List[Dict[str, Any]]:
        """Query L4 using BM25 + vector + keyword, fused via RRF."""
        if not conditions.content_query:
            return []
        fetch_k = max(conditions.limit * 5, 20)
        return await self._rrf_execute(
            content_query=conditions.content_query,
            limit=conditions.limit,
            bm25_coro=self._bm25_path(conditions.content_query, fetch_k),
            vector_coro=self._vector_path(conditions.content_query, fetch_k),
            keyword_coro=self._keyword_path(conditions.content_query, fetch_k),
            hydrate_coro_fn=self._fetch_by_ids,
        )

    async def _bm25_path(self, query: str, limit: int) -> List[str]:
        try:
            hits = await self._store.bm25_search(query, limit=limit)
            return [sid for sid, _score in hits]
        except Exception as exc:
            logger.warning("L4 BM25 path failed: %s", exc)
            return []

    async def _vector_path(self, query: str, limit: int) -> List[str]:
        try:
            results = await self._store._semantic_query_strategies(query=query, limit=limit)
            return [r["skill_id"] for r in results]
        except Exception as exc:
            logger.warning("L4 vector path failed: %s", exc)
            return []

    async def _keyword_path(self, query: str, limit: int) -> List[str]:
        try:
            import aiosqlite

            like_query = f"%{query}%"
            async with sqlite_connection_async(self._store.db_path) as db:
                async with db.execute(
                    """
                    SELECT skill_id FROM procedural_skills
                    WHERE skill_name LIKE ? OR COALESCE(optimized_prompt, '') LIKE ?
                    ORDER BY success_rate DESC, updated_at DESC
                    LIMIT ?
                    """,
                    (like_query, like_query, limit),
                ) as cursor:
                    rows = await cursor.fetchall()
            return [str(row[0]) for row in rows]
        except Exception as exc:
            logger.warning("L4 keyword path failed: %s", exc)
            return []

    async def _fetch_by_ids(self, skill_ids: List[str]) -> List[Dict[str, Any]]:
        if not skill_ids:
            return []
        import aiosqlite

        placeholders = ", ".join("?" for _ in skill_ids)
        async with sqlite_connection_async(self._store.db_path) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute(
                f"SELECT * FROM procedural_skills WHERE skill_id IN ({placeholders})",
                tuple(skill_ids),
            ) as cursor:
                rows = await cursor.fetchall()
        by_id = {str(row["skill_id"]): self._store._row_to_dict(row) for row in rows}
        return [by_id[sid] for sid in skill_ids if sid in by_id]


async def execute_plan(
    plan: LayerQueryPlan,
    *,
    l1: Optional[L1Handler] = None,
    l2: Optional[L2Handler] = None,
    l3: Optional[L3Handler] = None,
    l4: Optional[L4Handler] = None,
    session_id: Optional[str] = None,
    user_id: Optional[str] = None,
) -> Any:
    """Dispatch a single LayerQueryPlan to the appropriate handler."""
    time_range = plan.time_range

    if plan.layer == "L1" and l1 is not None:
        assert isinstance(plan.conditions, L1Conditions)
        return await l1.execute(plan.conditions, time_range, session_id=session_id, user_id=user_id)
    elif plan.layer == "L2" and l2 is not None:
        assert isinstance(plan.conditions, L2Conditions)
        return await l2.execute(plan.conditions, time_range, user_id=user_id)
    elif plan.layer == "L3" and l3 is not None:
        assert isinstance(plan.conditions, L3Conditions)
        return await l3.execute(plan.conditions, time_range)
    elif plan.layer == "L4" and l4 is not None:
        assert isinstance(plan.conditions, L4Conditions)
        return await l4.execute(plan.conditions, time_range)
    else:
        logger.warning("No handler available for layer %s", plan.layer)
        return [] if plan.layer != "L2" else {"entity_cards": [], "relationships": []}
