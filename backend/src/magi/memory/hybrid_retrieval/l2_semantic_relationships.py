"""Semantic relationship plans for L2 hybrid retrieval."""

from __future__ import annotations

from typing import Any, Optional

from .models import L2Conditions, L2SemanticFrame
from .protocols import L2StoreProtocol


class L2SemanticRelationshipMixin:
    """Execute semantic affinity relationship plans for L2 queries."""

    _store: L2StoreProtocol

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


__all__ = ["L2SemanticRelationshipMixin"]