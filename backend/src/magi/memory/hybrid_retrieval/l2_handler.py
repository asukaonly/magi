"""L2 knowledge graph handler for hybrid memory retrieval.

Extracted from handlers.py for maintainability — L2Handler contains
complex semantic relationship planning that warrants its own module.
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

from .models import (
    L2Conditions,
    L2SemanticFrame,
    SemanticConstraint,
    TimeRange,
)
from .protocols import (
    EmbeddingServiceProtocol,
    EntityCatalogProtocol,
    L2StoreProtocol,
)
from .l2_semantic_relationships import L2SemanticRelationshipMixin
from .l2_handler_utils import (
    allows_object_id_filter,
    allows_object_type_filter,
    build_l2_trace,
    build_query_frame,
    collect_candidate_object_ids,
    collect_candidate_subject_ids,
    dedupe_relationships,
    filter_items_by_time_range,
    filter_target_entities_for_family,
    find_constraint,
    has_global_query_constraints,
    infer_assertion_states,
    infer_relation_direction,
    infer_status_filters,
    infer_target_entity_id,
    infer_trait_families,
    is_generic_entity_ref,
    make_self_entity,
    predicates_for_semantic_frame,
    select_exact_target_entity_id,
    select_semantic_target_entity_id,
    select_target_entity_types,
)

logger = logging.getLogger(__name__)


class L2Handler(L2SemanticRelationshipMixin):
    """Execute L2 knowledge graph queries from structured conditions."""

    def __init__(
        self,
        l2_store: L2StoreProtocol,
        entity_catalog: EntityCatalogProtocol | None = None,
        embedding_service: EmbeddingServiceProtocol | None = None,
        edge_vector_index: Any | None = None,
    ) -> None:
        self._store = l2_store
        self._entity_catalog = entity_catalog
        self._embedding_service = embedding_service
        self._edge_vector_index = edge_vector_index

    @property
    def store(self) -> L2StoreProtocol:
        """Read-only access to the underlying L2 store instance."""
        return self._store

    @staticmethod
    def _filter_by_time_range(
        items: List[Dict[str, Any]],
        time_range: "TimeRange",
        *,
        timestamp_keys: tuple[str, ...] = ("observed_at", "first_observed_at"),
    ) -> List[Dict[str, Any]]:
        """Keep items whose timestamp falls within *time_range*.

        Items without any recognizable timestamp are always kept so
        that un-dated knowledge-graph facts are not silently discarded.
        """
        return filter_items_by_time_range(items, time_range, timestamp_keys=timestamp_keys)

    async def execute(
        self,
        conditions: L2Conditions,
        time_range: Optional[TimeRange] = None,
        *,
        user_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Query L2 for entity cards and relationships."""
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
        allow_global_scan = self._has_global_query_constraints(
            conditions=conditions,
            resolved_entities=resolved_entities,
            semantic_frame=semantic_frame,
            predicate_family=predicate_family,
            query_frame=query_frame,
            time_range=time_range,
            user_id=user_id,
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
            elif allow_global_scan:
                results["assertions"] = await self._store.list_tom_assertions(
                    trait_families=trait_families,
                    validation_states=self._infer_assertion_states(status_filters),
                    include_expired=False,
                    target_entity_id=target_entity_id,
                    limit=conditions.limit,
                )
            elif user_id and not resolved_entities and not conditions.entities and semantic_frame is None:
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
                elif allow_global_scan:
                    rels = await self._store.get_relationships(
                        predicates=predicates,
                        status_filters=status_filters,
                        limit=conditions.limit,
                    )
                    results["relationships"] = rels

        # Post-retrieval time_range filtering for assertions/relationships
        if time_range and (time_range.start or time_range.end):
            results["assertions"] = self._filter_by_time_range(
                results["assertions"], time_range,
                timestamp_keys=("observed_at", "first_observed_at"),
            )
            results["relationships"] = self._filter_by_time_range(
                results["relationships"], time_range,
                timestamp_keys=("last_observed_at", "first_observed_at"),
            )

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

        results["trace"] = build_l2_trace(
            conditions=conditions,
            resolved_entities=resolved_entities,
            query_frame=query_frame,
            predicate_family=predicate_family,
            predicates=predicates,
            status_filters=status_filters,
            relation_direction=relation_direction,
            semantic_frame=semantic_frame,
            target_entity_id=target_entity_id,
            allow_global_scan=allow_global_scan,
            entity_card_count=len(results["entity_cards"]),
            relationship_count=len(results["relationships"]),
            assertion_count=len(results["assertions"]),
            edge_vector_supplement_count=edge_vector_supplement_count,
        )
        logger.info("L2 retrieval executed | %s", results["trace"])
        return results

    @staticmethod
    def _has_global_query_constraints(
        *,
        conditions: L2Conditions,
        resolved_entities: list[dict[str, str]],
        semantic_frame: L2SemanticFrame | None,
        predicate_family: str,
        query_frame: dict[str, Any],
        time_range: TimeRange | None,
        user_id: Optional[str],
    ) -> bool:
        return has_global_query_constraints(
            conditions=conditions,
            resolved_entities=resolved_entities,
            semantic_frame=semantic_frame,
            predicate_family=predicate_family,
            query_frame=query_frame,
            time_range=time_range,
            user_id=user_id,
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
        return predicates_for_semantic_frame(semantic_frame)

    @staticmethod
    def _infer_status_filters(query: str) -> list[str]:
        return infer_status_filters(query)

    @staticmethod
    def _infer_relation_direction(query: str) -> str:
        return infer_relation_direction(query)

    @staticmethod
    def _infer_assertion_states(status_filters: list[str] | None) -> list[str] | None:
        return infer_assertion_states(status_filters)

    @staticmethod
    def _infer_trait_families(predicate_family: str) -> list[str] | None:
        return infer_trait_families(predicate_family)

    def _infer_target_entity_id(
        self,
        *,
        query_frame: dict[str, Any],
        predicate_family: str,
    ) -> str | None:
        return infer_target_entity_id(query_frame=query_frame, predicate_family=predicate_family)

    @staticmethod
    def _make_self_entity(user_id: str) -> dict[str, str]:
        return make_self_entity(user_id)

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
        return build_query_frame(
            conditions=conditions,
            resolved_entities=resolved_entities,
            predicates=predicates,
            predicate_family=predicate_family,
            user_id=user_id,
            relation_direction=relation_direction,
        )

    def _filter_target_entities_for_family(
        self,
        *,
        entities: list[dict[str, str]],
        predicate_family: str,
    ) -> list[dict[str, str]]:
        return filter_target_entities_for_family(
            entities=entities,
            predicate_family=predicate_family,
        )

    def _select_exact_target_entity_id(
        self,
        *,
        conditions: L2Conditions,
        predicate_family: str,
        target_entities: list[dict[str, str]],
    ) -> str | None:
        return select_exact_target_entity_id(
            conditions=conditions,
            predicate_family=predicate_family,
            target_entities=target_entities,
        )

    def _select_target_entity_types(
        self,
        *,
        conditions: L2Conditions,
        predicate_family: str,
        target_entities: list[dict[str, str]],
    ) -> list[str] | None:
        return select_target_entity_types(
            conditions=conditions,
            predicate_family=predicate_family,
            target_entities=target_entities,
        )

    @staticmethod
    def _is_generic_entity_ref(entity: dict[str, str]) -> bool:
        return is_generic_entity_ref(entity)

    @staticmethod
    def _allows_object_id_filter(*, entity_type: str, direction: str) -> bool:
        return allows_object_id_filter(entity_type=entity_type, direction=direction)

    @staticmethod
    def _allows_object_type_filter(*, entity_type: str, direction: str) -> bool:
        return allows_object_type_filter(entity_type=entity_type, direction=direction)

    @staticmethod
    def _find_constraint(
        constraints: list[SemanticConstraint],
        *,
        scope: str,
        facet: str,
    ) -> SemanticConstraint | None:
        return find_constraint(constraints, scope=scope, facet=facet)

    @staticmethod
    def _collect_candidate_subject_ids(relationships: list[dict[str, Any]]) -> list[str]:
        return collect_candidate_subject_ids(relationships)

    @staticmethod
    def _collect_candidate_object_ids(relationships: list[dict[str, Any]]) -> list[str]:
        return collect_candidate_object_ids(relationships)

    @staticmethod
    def _dedupe_relationships(relationships: list[dict[str, Any]]) -> list[dict[str, Any]]:
        return dedupe_relationships(relationships)

    @staticmethod
    def _select_semantic_target_entity_id(
        *,
        semantic_frame: L2SemanticFrame,
        resolved_entities: list[dict[str, str]],
    ) -> str | None:
        return select_semantic_target_entity_id(
            semantic_frame=semantic_frame,
            resolved_entities=resolved_entities,
        )
