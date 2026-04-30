"""L2 query execution flow for hybrid retrieval."""

from __future__ import annotations

import logging
from typing import Any, Optional, cast

from .l2_handler_utils import build_l2_trace
from .models import L2Conditions, L2SemanticFrame, TimeRange

logger = logging.getLogger(__name__)


class L2QueryExecutionMixin:
    """Execute L2 graph retrieval and assemble entity/assertion/relationship results."""

    async def execute(
        self,
        conditions: L2Conditions,
        time_range: Optional[TimeRange] = None,
        *,
        user_id: Optional[str] = None,
    ) -> dict[str, Any]:
        """Query L2 for entity cards and relationships."""
        host = cast(Any, self)
        results: dict[str, Any] = {
            "entity_cards": [],
            "relationships": [],
            "assertions": [],
            "trace": {},
        }
        resolved_entities = await host._resolve_entities(conditions, user_id=user_id)
        predicate_family = conditions.predicate_family or "unknown"
        predicates = conditions.predicates or host._predicates_for_family(predicate_family)
        status_filters = conditions.status_filter or host._infer_status_filters(conditions.content_query)
        relation_direction = conditions.relation_direction or host._infer_relation_direction(
            conditions.content_query
        )
        semantic_frame = conditions.semantic_frame
        query_frame = host._build_query_frame(
            conditions=conditions,
            resolved_entities=resolved_entities,
            predicates=predicates,
            predicate_family=predicate_family,
            user_id=user_id,
            relation_direction=relation_direction,
        )
        target_entity_id = host._infer_target_entity_id(
            query_frame=query_frame,
            predicate_family=predicate_family,
        )
        allow_global_scan = host._has_global_query_constraints(
            conditions=conditions,
            resolved_entities=resolved_entities,
            semantic_frame=semantic_frame,
            predicate_family=predicate_family,
            query_frame=query_frame,
            time_range=time_range,
            user_id=user_id,
        )

        if conditions.include_tom_snapshot:
            results["entity_cards"] = await self._query_entity_cards(
                conditions=conditions,
                resolved_entities=resolved_entities,
                query_frame=query_frame,
            )

        if conditions.include_assertions:
            results["assertions"] = await self._query_assertions(
                conditions=conditions,
                resolved_entities=resolved_entities,
                query_frame=query_frame,
                predicate_family=predicate_family,
                status_filters=status_filters,
                target_entity_id=target_entity_id,
                allow_global_scan=allow_global_scan,
                user_id=user_id,
                semantic_frame=semantic_frame,
            )

        if conditions.include_relationships:
            relationships, predicates = await self._query_relationships(
                conditions=conditions,
                resolved_entities=resolved_entities,
                query_frame=query_frame,
                predicates=predicates,
                status_filters=status_filters,
                relation_direction=relation_direction,
                semantic_frame=semantic_frame,
                allow_global_scan=allow_global_scan,
                user_id=user_id,
            )
            results["relationships"] = relationships

        if time_range and (time_range.start or time_range.end):
            results["assertions"] = host._filter_by_time_range(
                results["assertions"],
                time_range,
                timestamp_keys=("observed_at", "first_observed_at"),
            )
            results["relationships"] = host._filter_by_time_range(
                results["relationships"],
                time_range,
                timestamp_keys=("last_observed_at", "first_observed_at"),
            )

        edge_vector_supplement_count = 0
        if conditions.include_relationships and conditions.content_query:
            vector_edges = await host._supplement_edge_vector_search(
                content_query=conditions.content_query,
                existing_relationships=results["relationships"],
                status_filters=status_filters,
                predicates=None,
                predicate_boost_groups=host._collect_boost_groups(predicates),
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

    async def _query_entity_cards(
        self,
        *,
        conditions: L2Conditions,
        resolved_entities: list[dict[str, str]],
        query_frame: dict[str, Any],
    ) -> list[dict[str, Any]]:
        host = cast(Any, self)
        snapshot_entities = query_frame["snapshot_entities"] or resolved_entities
        if not snapshot_entities:
            return []
        return await host._store.batch_get_tom_snapshots(entities=snapshot_entities)

    async def _query_assertions(
        self,
        *,
        conditions: L2Conditions,
        resolved_entities: list[dict[str, str]],
        query_frame: dict[str, Any],
        predicate_family: str,
        status_filters: list[str] | None,
        target_entity_id: str | None,
        allow_global_scan: bool,
        user_id: str | None,
        semantic_frame: L2SemanticFrame | None,
    ) -> list[dict[str, Any]]:
        host = cast(Any, self)
        assertion_entities = query_frame["assertion_entities"] or resolved_entities
        trait_families = conditions.trait_families or host._infer_trait_families(predicate_family)
        validation_states = host._infer_assertion_states(status_filters)
        if assertion_entities:
            batch_assertions = await host._store.batch_list_tom_assertions(
                entity_ids=[e["entity_id"] for e in assertion_entities],
                trait_families=trait_families,
                validation_states=validation_states,
                include_expired=False,
                target_entity_id=target_entity_id,
                limit_per_entity=conditions.limit,
            )
            assertions: list[dict[str, Any]] = []
            for entity_assertions in batch_assertions.values():
                assertions.extend(entity_assertions)
            return assertions
        if allow_global_scan or (
            user_id and not resolved_entities and not conditions.entities and semantic_frame is None
        ):
            return await host._store.list_tom_assertions(
                trait_families=trait_families,
                validation_states=validation_states,
                include_expired=False,
                target_entity_id=target_entity_id,
                limit=conditions.limit,
            )
        return []

    async def _query_relationships(
        self,
        *,
        conditions: L2Conditions,
        resolved_entities: list[dict[str, str]],
        query_frame: dict[str, Any],
        predicates: list[str] | None,
        status_filters: list[str] | None,
        relation_direction: str,
        semantic_frame: L2SemanticFrame | None,
        allow_global_scan: bool,
        user_id: str | None,
    ) -> tuple[list[dict[str, Any]], list[str] | None]:
        host = cast(Any, self)
        semantic_relationships = await host._execute_semantic_relationship_plan(
            conditions=conditions,
            semantic_frame=semantic_frame,
            status_filters=status_filters,
            user_id=user_id,
            resolved_entities=resolved_entities,
        )
        if semantic_relationships is not None:
            if semantic_frame is not None:
                predicates = host._predicates_for_semantic_frame(semantic_frame)
            return semantic_relationships, predicates

        relationship_entities = query_frame["relationship_entities"] or resolved_entities
        if relationship_entities:
            return await self._query_entity_relationships(
                conditions=conditions,
                query_frame=query_frame,
                relationship_entities=relationship_entities,
                predicates=predicates,
                status_filters=status_filters,
                relation_direction=relation_direction,
            ), predicates
        if allow_global_scan:
            return await host._store.get_relationships(
                predicates=predicates,
                status_filters=status_filters,
                limit=conditions.limit,
            ), predicates
        return [], predicates

    async def _query_entity_relationships(
        self,
        *,
        conditions: L2Conditions,
        query_frame: dict[str, Any],
        relationship_entities: list[dict[str, str]],
        predicates: list[str] | None,
        status_filters: list[str] | None,
        relation_direction: str,
    ) -> list[dict[str, Any]]:
        host = cast(Any, self)
        entity_ids = [e["entity_id"] for e in relationship_entities]
        all_user = all(e.get("entity_type") == "user" for e in relationship_entities)
        apply_object_filter = all_user and relation_direction == "outgoing"
        batch_rels = await host._store.batch_get_relationships(
            entity_ids=entity_ids,
            direction=relation_direction,
            status_filters=status_filters,
            predicates=predicates,
            target_object_id=query_frame["relationship_object_id"] if apply_object_filter else None,
            object_types=query_frame["relationship_object_types"] if apply_object_filter else None,
            limit_per_entity=conditions.limit,
        )
        seen: set[str] = set()
        relationships: list[dict[str, Any]] = []
        for rels in batch_rels.values():
            for rel in rels:
                triple_id = str(rel.get("triple_id") or "")
                if triple_id and triple_id in seen:
                    continue
                if triple_id:
                    seen.add(triple_id)
                relationships.append(rel)
        return relationships


__all__ = ["L2QueryExecutionMixin"]
