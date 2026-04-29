"""L2 knowledge graph handler for hybrid memory retrieval.

Extracted from handlers.py for maintainability — L2Handler contains
complex semantic relationship planning that warrants its own module.
"""

from __future__ import annotations

import logging
from dataclasses import asdict
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
from ...runtime_defaults import DEFAULT_USER_ID

logger = logging.getLogger(__name__)


class L2Handler:
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
        result: List[Dict[str, Any]] = []
        for item in items:
            ts: float | None = None
            for key in timestamp_keys:
                raw = item.get(key)
                if raw is not None:
                    try:
                        ts = float(raw)
                    except (TypeError, ValueError):
                        continue
                    break
            if ts is None:
                result.append(item)
                continue
            if time_range.start and ts < time_range.start:
                continue
            if time_range.end and ts > time_range.end:
                continue
            result.append(item)
        return result

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
            "allow_global_scan": allow_global_scan,
            "entity_card_count": len(results["entity_cards"]),
            "relationship_count": len(results["relationships"]),
            "assertion_count": len(results["assertions"]),
            "edge_vector_supplement_count": edge_vector_supplement_count,
        }
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
        if resolved_entities or conditions.entities:
            return True
        if conditions.predicates or conditions.trait_families or conditions.entity_types:
            return True
        if predicate_family and predicate_family != "unknown":
            return True
        if conditions.subject_hint == "self" and user_id and predicate_family != "unknown":
            return True
        if semantic_frame is not None:
            if semantic_frame.subject_scope != "none":
                return True
            if semantic_frame.query_family != "lookup":
                return True
            if semantic_frame.entity_mentions or semantic_frame.constraints:
                return True
        if query_frame.get("relationship_object_id") or query_frame.get("relationship_object_types"):
            return True
        if time_range is not None and (time_range.start is not None or time_range.end is not None):
            return True
        return False

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

    @staticmethod
    def _make_self_entities(user_id: str) -> list[dict[str, str]]:
        primary = L2Handler._make_self_entity(user_id)
        entities = [primary]
        if user_id == DEFAULT_USER_ID and primary["entity_id"] != "user:self":
            entities.append({
                "entity_id": "user:self",
                "entity_type": "user",
                "match_source": "self_alias",
            })
        return entities

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
            subject_entities = self._make_self_entities(user_id)
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
            subject_entities = self._make_self_entities(user_id)
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
        for entity in target_entities:
            # Vector-only resolution is unreliable for exact target filtering.
            if str(entity.get("match_source") or "") == "vector":
                continue
            if predicate_family == "preference" and self._is_generic_entity_ref(entity):
                continue
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
