"""L2 query execution flow for hybrid retrieval."""

from __future__ import annotations

import asyncio
import logging
from typing import Any, Optional, cast

from .grounding import build_grounding_plan
from .l2_fusion import fuse_l2_candidates, project_candidates
from .l2_knowledge_retriever import retrieve_knowledge
from .l2_subdomain_retrievers import (
    retrieve_assertions,
    retrieve_episodes,
    retrieve_snapshots,
)
from .models import L2Conditions, TimeRange

logger = logging.getLogger(__name__)


class L2QueryExecutionMixin:
    """Execute L2 graph retrieval using grounded hybrid retrieval pipeline."""

    async def execute(
        self,
        conditions: L2Conditions,
        time_range: Optional[TimeRange] = None,
        *,
        user_id: Optional[str] = None,
    ) -> dict[str, Any]:
        """Query L2 using the grounded hybrid retrieval pipeline.

        Flow:
        1. Resolve entities from query text
        2. Build L2GroundingPlan (deterministic, no LLM)
        3. Run subdomain retrievers concurrently
        4. Fuse and rank candidates
        5. Project back to typed output
        """
        host = cast(Any, self)

        resolved_entities = await host._resolve_entities(conditions, user_id=user_id)

        plan = build_grounding_plan(
            conditions,
            resolved_entities=resolved_entities,
            user_id=user_id,
            time_range=time_range,
        )

        knowledge_task = (
            retrieve_knowledge(
                plan,
                host._store,
                embedding_service=getattr(host, "_embedding_service", None),
                edge_vector_index=getattr(host, "_edge_vector_index", None),
                limit=conditions.limit,
            )
            if conditions.include_relationships
            else _empty_list()
        )

        assertion_task = (
            retrieve_assertions(
                plan,
                host._store,
                limit=conditions.limit,
            )
            if conditions.include_assertions
            else _empty_list()
        )

        snapshot_task = (
            retrieve_snapshots(
                plan,
                host._store,
            )
            if conditions.include_tom_snapshot
            else _empty_list()
        )

        episode_task = retrieve_episodes(
            plan,
            host._store,
            limit=conditions.limit,
        )

        knowledge_edges, assertions, snapshots, episodes = await asyncio.gather(
            knowledge_task,
            assertion_task,
            snapshot_task,
            episode_task,
        )

        candidates = fuse_l2_candidates(
            plan,
            knowledge_edges=knowledge_edges,
            assertions=assertions,
            snapshots=snapshots,
            episodes=episodes,
            top_k=conditions.limit * 2,
        )

        projected = project_candidates(candidates)

        results: dict[str, Any] = {
            "entity_cards": projected.get("entity_cards", []),
            "relationships": projected.get("relationships", []),
            "assertions": projected.get("assertions", []),
            "episodes": projected.get("episodes", []),
            "state_facts": projected.get("state_facts", []),
            "state_history": projected.get("state_history", []),
        }

        results["trace"] = {
            "grounding_plan": {
                "query_kind": plan.query_kind,
                "subject_scope": plan.subject_scope,
                "answer_kind": plan.answer_kind,
                "predicate_family": plan.predicate_family,
                "confidence": plan.confidence,
                "temporal_mode": plan.temporal_context.mode,
                "subject_count": len(plan.subject_candidates),
                "object_count": len(plan.object_candidates),
                "predicate_count": len(plan.predicate_candidates),
            },
            "channel_counts": {
                "knowledge_edges": len(knowledge_edges),
                "assertions": len(assertions),
                "snapshots": len(snapshots),
                "episodes": len(episodes),
            },
            "fusion_candidate_count": len(candidates),
            "output_counts": {
                "entity_cards": len(results["entity_cards"]),
                "relationships": len(results["relationships"]),
                "assertions": len(results["assertions"]),
                "episodes": len(results["episodes"]),
                "state_history": len(results["state_history"]),
            },
        }

        logger.info("L2 retrieval executed | %s", results["trace"])
        return results


async def _empty_list() -> list:
    return []


__all__ = ["L2QueryExecutionMixin"]
