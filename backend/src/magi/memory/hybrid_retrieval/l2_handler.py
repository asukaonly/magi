"""L2 knowledge graph handler for hybrid memory retrieval.

Extracted from handlers.py for maintainability — L2Handler contains
complex semantic relationship planning that warrants its own module.
"""

from __future__ import annotations

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
from .l2_edge_vectors import L2EdgeVectorSupplementMixin
from .l2_entity_resolution import L2EntityResolutionMixin
from .l2_relationship_queries import L2RelationshipQueryMixin
from .l2_query_execution import L2QueryExecutionMixin
from .l2_handler_utils import (
    allows_object_id_filter,
    allows_object_type_filter,
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
    make_self_entities,
    predicates_for_semantic_frame,
    select_exact_target_entity_id,
    select_semantic_target_entity_id,
    select_target_entity_types,
)

class L2Handler(
    L2EntityResolutionMixin,
    L2RelationshipQueryMixin,
    L2EdgeVectorSupplementMixin,
    L2QueryExecutionMixin,
):
    """Execute L2 knowledge graph queries from structured conditions."""

    def __init__(
        self,
        l2_store: L2StoreProtocol,
        entity_catalog: EntityCatalogProtocol | None = None,
        embedding_service: EmbeddingServiceProtocol | None = None,
        edge_vector_index: Any | None = None,
        l1_store: Any | None = None,
    ) -> None:
        self._store = l2_store
        self._entity_catalog = entity_catalog
        self._embedding_service = embedding_service
        self._edge_vector_index = edge_vector_index
        self._l1_store = l1_store

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

    @staticmethod
    def _make_self_entities(user_id: str) -> list[dict[str, str]]:
        return make_self_entities(user_id)

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
