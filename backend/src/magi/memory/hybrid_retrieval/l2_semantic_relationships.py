"""Semantic relationship plans for L2 hybrid retrieval."""

from __future__ import annotations

from typing import Any, Optional, TYPE_CHECKING

from .models import L2Conditions, L2SemanticFrame
from .protocols import L2StoreProtocol

if TYPE_CHECKING:
    from .grounding import L2GroundingPlan


def _plan_from_conditions(
    *,
    conditions: L2Conditions,
    user_id: str,
    answer_kind: str,
) -> "L2GroundingPlan":
    """Synthesize a minimal ``L2GroundingPlan`` for ``_execute_topology``.

    Affinity handlers only need ``subject_entity_ids`` + ``allowed_evidence_classes``.
    """
    from .grounding import GroundedEntityCandidate, L2GroundingPlan

    plan = L2GroundingPlan(answer_kind=answer_kind, subject_scope="self")
    plan.subject_candidates = [
        GroundedEntityCandidate(
            entity_id=f"user:{user_id}",
            entity_type="person",
            surface="self",
            score=1.0,
            source="rule",
        )
    ]
    plan.allowed_evidence_classes = conditions.allowed_evidence_classes
    return plan


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
        from .topology_registry import ANSWER_KIND_TOPOLOGIES, _execute_topology

        # Constraint preprocessing: platform filter narrows candidate creators.
        platform_constraint = self._find_constraint(
            semantic_frame.constraints, scope="target", facet="platform"
        )
        if platform_constraint is None:
            platform_constraint = self._find_constraint(
                semantic_frame.constraints, scope="interaction", facet="platform"
            )
        platform_entity_id = (
            platform_constraint.resolved_entity_id if platform_constraint else None
        )

        candidate_object_ids: list[str] | None = None
        if platform_entity_id:
            topology_edges = await self._store.get_relationships(
                predicates=["ON_PLATFORM"],
                object_id=platform_entity_id,
                status_filters=status_filters,
                limit=max(conditions.limit * 5, 20),
            )
            candidate_object_ids = self._collect_candidate_subject_ids(topology_edges)
            if not candidate_object_ids:
                return []

        plan = _plan_from_conditions(
            conditions=conditions, user_id=user_id, answer_kind="creator"
        )
        return await _execute_topology(
            spec=ANSWER_KIND_TOPOLOGIES["creator"],
            plan=plan,
            store=self._store,
            limit=conditions.limit,
            candidate_object_ids=candidate_object_ids,
        )

    async def _execute_place_affinity_relationship_plan(
        self,
        *,
        conditions: L2Conditions,
        semantic_frame: L2SemanticFrame,
        status_filters: list[str] | None,
        user_id: str,
    ) -> list[dict[str, Any]] | None:
        from .topology_registry import ANSWER_KIND_TOPOLOGIES, _execute_topology

        # Constraint preprocessing: target/interaction location + category filter.
        target_location_constraint = self._find_constraint(
            semantic_frame.constraints, scope="target", facet="located_in"
        )
        interaction_location_constraint = self._find_constraint(
            semantic_frame.constraints, scope="interaction", facet="located_in"
        )
        target_location_entity_id = (
            target_location_constraint.resolved_entity_id
            if target_location_constraint
            else None
        )
        interaction_location_entity_id = (
            interaction_location_constraint.resolved_entity_id
            if interaction_location_constraint
            else None
        )
        category_constraint = self._find_constraint(
            semantic_frame.constraints, scope="target", facet="category"
        )
        category_value = (
            category_constraint.resolved_facet_value if category_constraint else None
        )

        # Interaction-location branch: intersect places the user already has
        # evidence on with those LOCATED_IN the interaction place (optionally
        # narrowed by category). The intersection shape doesn't fit the
        # executor's two-mode contract; keep this branch inline.
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
            candidate_ids = [cid for cid in candidate_ids if cid in location_ids]
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
                    rel
                    for rel in evidence_relationships
                    if str(rel.get("object_id") or "").strip() in set(candidate_ids)
                ]
            )

        # No location constraint: plain user→place fetch via executor.
        if not target_location_entity_id:
            plan = _plan_from_conditions(
                conditions=conditions, user_id=user_id, answer_kind="place"
            )
            return await _execute_topology(
                spec=ANSWER_KIND_TOPOLOGIES["place"],
                plan=plan,
                store=self._store,
                limit=conditions.limit,
            )

        # Target-location: prefetch candidate places via LOCATED_IN (optionally
        # narrowed by category) then delegate user→candidate fetch to executor.
        topology_edges = await self._store.get_relationships(
            predicates=["LOCATED_IN"],
            object_id=target_location_entity_id,
            status_filters=status_filters,
            limit=max(conditions.limit * 5, 20),
        )
        candidate_ids = self._collect_candidate_subject_ids(topology_edges)
        if candidate_ids and category_value:
            candidate_ids = await self._store.filter_entity_ids_by_facet(
                entity_ids=candidate_ids,
                facet_name="category",
                facet_values=[category_value],
            )
        if not candidate_ids:
            return []

        plan = _plan_from_conditions(
            conditions=conditions, user_id=user_id, answer_kind="place"
        )
        return await _execute_topology(
            spec=ANSWER_KIND_TOPOLOGIES["place"],
            plan=plan,
            store=self._store,
            limit=conditions.limit,
            candidate_object_ids=candidate_ids,
        )

    async def _execute_software_affinity_relationship_plan(
        self,
        *,
        conditions: L2Conditions,
        semantic_frame: L2SemanticFrame,
        status_filters: list[str] | None,
        user_id: str,
        resolved_entities: list[dict[str, str]],
    ) -> list[dict[str, Any]] | None:
        from .topology_registry import ANSWER_KIND_TOPOLOGIES, _execute_topology

        # A resolved software entity narrows to a single candidate.
        target_entity_id = self._select_semantic_target_entity_id(
            semantic_frame=semantic_frame,
            resolved_entities=resolved_entities,
        )
        candidate_object_ids: list[str] | None = (
            [target_entity_id] if target_entity_id else None
        )

        plan = _plan_from_conditions(
            conditions=conditions, user_id=user_id, answer_kind="software"
        )
        return await _execute_topology(
            spec=ANSWER_KIND_TOPOLOGIES["software"],
            plan=plan,
            store=self._store,
            limit=conditions.limit,
            candidate_object_ids=candidate_object_ids,
        )

    async def _execute_topic_affinity_relationship_plan(
        self,
        *,
        conditions: L2Conditions,
        semantic_frame: L2SemanticFrame,
        status_filters: list[str] | None,
        user_id: str,
    ) -> list[dict[str, Any]] | None:
        from .topology_registry import ANSWER_KIND_TOPOLOGIES, _execute_topology

        plan = _plan_from_conditions(
            conditions=conditions, user_id=user_id, answer_kind="topic"
        )
        return await _execute_topology(
            spec=ANSWER_KIND_TOPOLOGIES["topic"],
            plan=plan,
            store=self._store,
            limit=conditions.limit,
        )


__all__ = ["L2SemanticRelationshipMixin"]
