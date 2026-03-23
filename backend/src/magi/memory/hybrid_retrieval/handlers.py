"""Layer handlers for hybrid memory retrieval.

Each handler wraps the corresponding memory store and executes
queries based on structured LayerQueryPlan conditions.
"""

from __future__ import annotations

import asyncio
import logging
import re
from typing import Any, Dict, List, Optional, Sequence, Tuple

from ...core.sqlite import sqlite_connection_async
from .answerability import (
    extract_query_phrases,
    extract_query_tokens,
    extract_quoted_spans,
    score_eventness,
    score_generic_guidance_penalty,
    score_temporal_anchor,
)
from .models import (
    L1Conditions,
    L2Conditions,
    L3Conditions,
    L4Conditions,
    LayerQueryPlan,
    RetrievalConfig,
    TimeRange,
)

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


class L1Handler:
    """Execute L1 event store queries with triple-path RRF fusion."""

    def __init__(self, l1_store: Any, config: Optional[RetrievalConfig] = None) -> None:
        self._store = l1_store
        self._config = config or RetrievalConfig()

    async def execute(
        self,
        conditions: L1Conditions,
        time_range: Optional[TimeRange] = None,
        *,
        session_id: Optional[str] = None,
        user_id: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        """Query L1 using BM25 + vector + keyword, fused via RRF."""
        if not conditions.content_query:
            return []

        fetch_k = max(conditions.limit * 5, 20)

        # Three concurrent search paths
        bm25_task = asyncio.ensure_future(self._bm25_path(conditions.content_query, fetch_k))
        vec_task = asyncio.ensure_future(self._vector_path(conditions.content_query, fetch_k))
        kw_task = asyncio.ensure_future(self._keyword_path(conditions, fetch_k, session_id=session_id, user_id=user_id))

        results_or_errors = await asyncio.gather(bm25_task, vec_task, kw_task, return_exceptions=True)

        bm25_ids: List[str] = results_or_errors[0] if isinstance(results_or_errors[0], list) else []
        vec_ids: List[str] = results_or_errors[1] if isinstance(results_or_errors[1], list) else []
        kw_ids: List[str] = results_or_errors[2] if isinstance(results_or_errors[2], list) else []

        for i, res in enumerate(results_or_errors):
            if isinstance(res, BaseException):
                logger.warning("L1 search path %d failed: %s", i, res)

        if not bm25_ids and not vec_ids and not kw_ids:
            return []

        # RRF fusion
        cfg = self._config
        fused = rrf_fuse(
            [bm25_ids, vec_ids, kw_ids],
            [cfg.rrf_weight_bm25, cfg.rrf_weight_vector, cfg.rrf_weight_keyword],
            k=cfg.rrf_k,
        )

        # Take top IDs up to fetch_k for hydration
        top_ids = [doc_id for doc_id, _ in fused[:fetch_k]]
        if not top_ids:
            return []

        # Hydrate full events and apply filters
        results = await self._fetch_and_filter(
            event_ids=top_ids,
            conditions=conditions,
            time_range=time_range,
            session_id=session_id,
            user_id=user_id,
        )

        reranked = self._rerank_results(
            results=results,
            query=conditions.content_query,
            fused_scores=dict(fused),
        )
        return reranked[:conditions.limit]

    async def _bm25_path(self, query: str, limit: int) -> List[str]:
        """BM25 search via FTS5."""
        try:
            hits = await self._store.bm25_search(query, limit=limit)
            return [event_id for event_id, _score in hits]
        except Exception as exc:
            logger.warning("BM25 path failed: %s", exc)
            return []

    async def _vector_path(self, query: str, limit: int) -> List[str]:
        """Vector similarity search via sqlite-vec."""
        try:
            hits = await self._store._semantic_search_event_hits(query=query, limit=limit)
            return [hit.entity_id for hit in hits]
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

    @staticmethod
    def _filter_by_time(
        results: List[Dict[str, Any]],
        time_range: TimeRange,
    ) -> List[Dict[str, Any]]:
        """Post-filter results by time range."""
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

    def _rerank_results(
        self,
        *,
        results: List[Dict[str, Any]],
        query: str,
        fused_scores: Dict[str, float],
    ) -> List[Dict[str, Any]]:
        """Apply answerability-aware reranking to hydrated L1 events."""
        if not results:
            return []

        query_tokens = extract_query_tokens(query)
        query_phrases = extract_query_phrases(query_tokens)
        quoted_phrases = extract_quoted_spans(query)

        scored: List[tuple[float, Dict[str, Any]]] = []
        for event in results:
            score, trace = self._score_event(
                event=event,
                query_tokens=query_tokens,
                query_phrases=query_phrases,
                quoted_phrases=quoted_phrases,
                base_rrf_score=float(fused_scores.get(str(event.get("event_id") or ""), 0.0)),
            )
            enriched = dict(event)
            enriched["retrieval_score"] = score
            enriched["retrieval_trace"] = trace
            scored.append((score, enriched))

        scored.sort(
            key=lambda item: (
                item[0],
                float(item[1].get("timestamp") or 0.0),
            ),
            reverse=True,
        )
        return [item for _, item in scored]

    def _score_event(
        self,
        *,
        event: Dict[str, Any],
        query_tokens: List[str],
        query_phrases: List[str],
        quoted_phrases: List[str],
        base_rrf_score: float,
    ) -> tuple[float, Dict[str, Any]]:
        """Score a single hydrated event for answerability-oriented ranking."""
        content = str(event.get("content") or "")
        lowered = content.lower()
        content_tokens = set(extract_query_tokens(content))
        matched_tokens = [token for token in query_tokens if token in content_tokens]
        phrase_hits = [phrase for phrase in query_phrases if phrase and phrase in lowered]
        quoted_phrase_hits = [phrase for phrase in quoted_phrases if phrase and phrase in lowered]

        author_type = str(event.get("author_type") or "").strip().lower()
        role_bias = 0.0
        if author_type == "user":
            role_bias = 0.35
        elif author_type == "assistant":
            role_bias = -0.1

        token_overlap = (len(matched_tokens) / len(query_tokens)) if query_tokens else 0.0
        phrase_score = min(len(phrase_hits), 3) * 0.25
        quoted_phrase_weight = 0.45 if author_type == "user" else 0.15
        quoted_phrase_score = min(len(quoted_phrase_hits), 2) * quoted_phrase_weight
        fact_density = 0.0
        if re.search(r"\b\d{1,2}[/-]\d{1,2}\b", content) or re.search(r"\b\d{1,2}:\d{2}\b", content):
            fact_density += 0.15
        if re.search(r"\bgps\b", lowered):
            fact_density += 0.1
        eventness_score = score_eventness(content, author_type=author_type)
        temporal_anchor_score = score_temporal_anchor(content)

        verbosity_penalty = 0.0
        if author_type == "assistant" and len(content) > 240:
            verbosity_penalty = min((len(content) - 240) / 600.0, 0.25)
        guidance_penalty = score_generic_guidance_penalty(content, author_type=author_type)

        final_score = (
            base_rrf_score
            + role_bias
            + token_overlap
            + phrase_score
            + quoted_phrase_score
            + fact_density
            + eventness_score
            + temporal_anchor_score
            - verbosity_penalty
            - guidance_penalty
        )
        trace = {
            "base_rrf_score": round(base_rrf_score, 6),
            "role_bias": role_bias,
            "token_overlap": round(token_overlap, 6),
            "phrase_hits": phrase_hits,
            "quoted_phrase_hits": quoted_phrase_hits,
            "fact_density": fact_density,
            "eventness_score": eventness_score,
            "temporal_anchor_score": temporal_anchor_score,
            "verbosity_penalty": round(verbosity_penalty, 6),
            "generic_guidance_penalty": round(guidance_penalty, 6),
            "matched_tokens": matched_tokens,
        }
        return final_score, trace


class L2Handler:
    """Execute L2 knowledge graph queries from structured conditions."""

    def __init__(self, l2_store: Any, entity_catalog: Any | None = None) -> None:
        self._store = l2_store
        self._entity_catalog = entity_catalog

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
        predicates = conditions.predicates or self._infer_predicates(conditions.content_query)
        status_filters = conditions.status_filter or self._infer_status_filters(conditions.content_query)
        relation_direction = conditions.relation_direction or self._infer_relation_direction(conditions.content_query)
        target_entity_id = self._infer_target_entity_id(
            resolved_entities=resolved_entities,
            predicates=predicates,
        )

        if conditions.include_tom_snapshot and resolved_entities:
            for entity in resolved_entities:
                snapshot = await self._store.get_tom_snapshot(
                    entity_id=entity["entity_id"],
                    entity_type=entity["entity_type"],
                )
                if snapshot:
                    results["entity_cards"].append(snapshot)

        if conditions.include_assertions:
            if resolved_entities:
                for entity in resolved_entities:
                    assertions = await self._store.list_tom_assertions(
                        entity_id=entity["entity_id"],
                        entity_type=entity["entity_type"],
                        trait_families=conditions.trait_families,
                        validation_states=self._infer_assertion_states(status_filters),
                        include_expired=False,
                        target_entity_id=target_entity_id,
                        limit=conditions.limit,
                    )
                    results["assertions"].extend(assertions)
            else:
                results["assertions"] = await self._store.list_tom_assertions(
                    trait_families=conditions.trait_families,
                    validation_states=self._infer_assertion_states(status_filters),
                    include_expired=False,
                    target_entity_id=target_entity_id,
                    limit=conditions.limit,
                )

        if conditions.include_relationships:
            if resolved_entities:
                for entity in resolved_entities:
                    results["relationships"].extend(
                        await self._query_relationships_for_entity(
                            entity_id=entity["entity_id"],
                            direction=relation_direction,
                            predicates=predicates,
                            status_filters=status_filters,
                            limit=conditions.limit,
                        )
                    )
            else:
                rels = await self._store.get_relationships(
                    predicates=predicates,
                    status_filters=status_filters,
                    limit=conditions.limit,
                )
                results["relationships"] = rels

        results["trace"] = {
            "resolved_entities": resolved_entities,
            "predicates": predicates or [],
            "status_filters": status_filters or [],
            "relation_direction": relation_direction,
            "target_entity_id": target_entity_id,
        }
        return results

    async def _query_relationships_for_entity(
        self,
        *,
        entity_id: str,
        direction: str,
        predicates: list[str] | None,
        status_filters: list[str] | None,
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
            limit=limit,
        )

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
                    resolved.append({"entity_id": normalized, "entity_type": entity_type or "entity"})
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
                resolved.append({"entity_id": entity_id, "entity_type": str(match["entity_type"])})
                seen.add(entity_id)

        if resolved or self._entity_catalog is None or not conditions.content_query:
            return resolved or self._infer_self_entities(conditions.content_query, user_id=user_id)

        query_matches = await self._entity_catalog.resolve_query_entities(
            conditions.content_query,
            limit=max(conditions.limit, 5),
            entity_types=conditions.entity_types,
        )
        for match in query_matches:
            entity_id = str(match["entity_id"])
            if entity_id in seen:
                continue
            resolved.append({"entity_id": entity_id, "entity_type": str(match["entity_type"])})
            seen.add(entity_id)
        return resolved or self._infer_self_entities(conditions.content_query, user_id=user_id)

    def _infer_predicates(self, query: str) -> list[str] | None:
        query_lower = query.lower()
        predicates: list[str] = []
        if any(token in query_lower for token in ("讨厌", "dislike", "dislikes", "不喜欢")):
            predicates.append("DISLIKES")
        if any(token in query_lower for token in ("喜欢", "like", "likes")):
            predicates.append("LIKES")
        if "偏好" in query_lower or "preference" in query_lower:
            predicates.extend(["LIKES", "DISLIKES", "INTERESTED_IN"])
        if "关系" in query_lower or "relationship" in query_lower:
            predicates.extend(["KNOWS", "FAMILY_OF", "INTERACTED_WITH", "MEMBER_OF"])
        unique = []
        seen: set[str] = set()
        for predicate in predicates:
            if predicate in seen:
                continue
            seen.add(predicate)
            unique.append(predicate)
        return unique or None

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

    def _infer_target_entity_id(
        self,
        *,
        resolved_entities: list[dict[str, str]],
        predicates: list[str] | None,
    ) -> str | None:
        if not resolved_entities or not predicates:
            return None
        if not any(predicate in {"LIKES", "DISLIKES", "INTERESTED_IN"} for predicate in predicates):
            return None
        first = resolved_entities[0]
        return str(first["entity_id"])

    def _infer_self_entities(self, query: str, *, user_id: Optional[str] = None) -> list[dict[str, str]]:
        if "我" not in query and " me " not in f" {query.lower()} ":
            return []
        if user_id:
            return [{"entity_id": f"user:{user_id}", "entity_type": "user"}]
        return []


class L3Handler:
    """Execute L3 summary store queries with triple-path RRF fusion."""

    def __init__(self, l3_store: Any, config: Optional[RetrievalConfig] = None) -> None:
        self._store = l3_store
        self._config = config or RetrievalConfig()

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

        bm25_task = asyncio.ensure_future(
            self._bm25_path(conditions.content_query, summary_type, summary_category, fetch_k)
        )
        vec_task = asyncio.ensure_future(
            self._vector_path(conditions.content_query, summary_type, summary_category, fetch_k)
        )
        kw_task = asyncio.ensure_future(
            self._keyword_path(conditions.content_query, summary_type, summary_category, fetch_k)
        )

        results_or_errors = await asyncio.gather(bm25_task, vec_task, kw_task, return_exceptions=True)

        bm25_ids: List[str] = results_or_errors[0] if isinstance(results_or_errors[0], list) else []
        vec_ids: List[str] = results_or_errors[1] if isinstance(results_or_errors[1], list) else []
        kw_ids: List[str] = results_or_errors[2] if isinstance(results_or_errors[2], list) else []

        for i, res in enumerate(results_or_errors):
            if isinstance(res, BaseException):
                logger.warning("L3 search path %d failed: %s", i, res)

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

        results = await self._fetch_by_ids(top_ids, summary_type, summary_category)
        if time_range and results:
            results = self._filter_by_time(results, time_range)
        return results[:conditions.limit]

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


class L4Handler:
    """Execute L4 procedural memory queries with triple-path RRF fusion."""

    def __init__(self, l4_store: Any, config: Optional[RetrievalConfig] = None) -> None:
        self._store = l4_store
        self._config = config or RetrievalConfig()

    async def execute(
        self,
        conditions: L4Conditions,
        time_range: Optional[TimeRange] = None,
    ) -> List[Dict[str, Any]]:
        """Query L4 using BM25 + vector + keyword, fused via RRF."""
        if not conditions.content_query:
            return []

        fetch_k = max(conditions.limit * 5, 20)

        bm25_task = asyncio.ensure_future(self._bm25_path(conditions.content_query, fetch_k))
        vec_task = asyncio.ensure_future(self._vector_path(conditions.content_query, fetch_k))
        kw_task = asyncio.ensure_future(self._keyword_path(conditions.content_query, fetch_k))

        results_or_errors = await asyncio.gather(bm25_task, vec_task, kw_task, return_exceptions=True)

        bm25_ids: List[str] = results_or_errors[0] if isinstance(results_or_errors[0], list) else []
        vec_ids: List[str] = results_or_errors[1] if isinstance(results_or_errors[1], list) else []
        kw_ids: List[str] = results_or_errors[2] if isinstance(results_or_errors[2], list) else []

        for i, res in enumerate(results_or_errors):
            if isinstance(res, BaseException):
                logger.warning("L4 search path %d failed: %s", i, res)

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

        results = await self._fetch_by_ids(top_ids)
        return results[:conditions.limit]

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
