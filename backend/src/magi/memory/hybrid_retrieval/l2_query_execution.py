"""L2 query execution flow for hybrid retrieval."""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from typing import Any, Optional, cast

from ...utils.diagnostic_logging import full_content_logging_enabled
from .grounding import L2GroundingPlan, build_grounding_plan
from .governed_l2_recall import (
    GovernedL2RecallView,
    governed_temporal_bounds,
)
from .l2_fusion import fuse_l2_candidates, project_candidates
from .l2_knowledge_retriever import retrieve_knowledge
from .predicate_resolver import resolve_predicates
from .l2_subdomain_retrievers import (
    retrieve_assertions,
    retrieve_episodes,
    retrieve_experiences,
    retrieve_snapshots,
)
from .models import L2Conditions, TimeRange

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class _L2ChannelResults:
    knowledge_edges: list[dict[str, Any]]
    assertions: list[dict[str, Any]]
    snapshots: list[dict[str, Any]]
    episodes: list[dict[str, Any]]
    experiences: list[dict[str, Any]]


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

        plan = await _build_query_plan(
            host,
            conditions,
            user_id=user_id,
            time_range=time_range,
        )

        channels = await _retrieve_l2_channels(
            host,
            plan,
            conditions,
            time_range=time_range,
            user_id=user_id,
        )

        candidates = fuse_l2_candidates(
            plan,
            knowledge_edges=channels.knowledge_edges,
            assertions=channels.assertions,
            snapshots=channels.snapshots,
            episodes=channels.episodes,
            top_k=conditions.limit * 2,
        )

        projected = project_candidates(candidates)
        results = _build_query_results(projected, channels.experiences)
        results["trace"] = _build_execution_trace(plan, channels, candidates, results)

        if full_content_logging_enabled():
            logger.info("L2 retrieval executed | %s", results["trace"])
        else:
            logger.info(
                "L2 retrieval executed | entity_cards=%d relationships=%d "
                "assertions=%d episodes=%d experiences=%d",
                len(results.get("entity_cards", [])),
                len(results.get("relationships", [])),
                len(results.get("assertions", [])),
                len(results.get("episodes", [])),
                len(results.get("experiences", [])),
            )
        return results


async def _build_query_plan(
    host: Any,
    conditions: L2Conditions,
    *,
    time_range: Optional[TimeRange],
    user_id: Optional[str],
) -> L2GroundingPlan:
    resolved_entities = await host._resolve_entities(conditions, user_id=user_id)

    await resolve_predicates(
        conditions,
        embedding_service=getattr(host, "_embedding_service", None),
    )

    return build_grounding_plan(
        conditions,
        resolved_entities=resolved_entities,
        user_id=user_id,
        time_range=time_range,
    )


async def _retrieve_l2_channels(
    host: Any,
    plan: L2GroundingPlan,
    conditions: L2Conditions,
    *,
    time_range: Optional[TimeRange],
    user_id: Optional[str],
) -> _L2ChannelResults:
    temporal_bounds = governed_temporal_bounds(time_range)
    claim_store = GovernedL2RecallView(
        host._store,
        context_scope=plan.context_scope,
        effective_at=temporal_bounds.effective_at,
        effective_range=temporal_bounds.effective_range,
        include_relationship_history=temporal_bounds.include_history,
    )
    knowledge_task = (
        retrieve_knowledge(
            plan,
            claim_store,
            embedding_service=getattr(host, "_embedding_service", None),
            edge_vector_index=getattr(host, "_edge_vector_index", None),
            l1_store=getattr(host, "_l1_store", None),
            user_id=user_id,
            limit=conditions.limit,
        )
        if conditions.include_relationships
        else _empty_list()
    )

    assertion_task = (
        retrieve_assertions(
            plan,
            claim_store,
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

    episode_task = (
        retrieve_episodes(
            plan,
            host._store,
            limit=conditions.limit,
        )
        if conditions.include_episodes
        else _empty_list()
    )

    experience_task = (
        retrieve_experiences(
            plan,
            host._store,
            limit=conditions.limit,
        )
        if conditions.include_experiences
        else _empty_list()
    )

    knowledge_edges, assertions, snapshots, episodes, experiences = await asyncio.gather(
        knowledge_task,
        assertion_task,
        snapshot_task,
        episode_task,
        experience_task,
    )

    return _L2ChannelResults(
        knowledge_edges=knowledge_edges,
        assertions=assertions,
        snapshots=snapshots,
        episodes=(
            _merge_experience_source_episodes(episodes, experiences)
            if conditions.include_episodes
            else []
        ),
        experiences=experiences,
    )


async def _empty_list() -> list[dict[str, Any]]:
    return []


def _build_query_results(
    projected: dict[str, Any],
    experiences: list[dict[str, Any]],
) -> dict[str, Any]:
    return {
        "entity_cards": projected.get("entity_cards", []),
        "relationships": projected.get("relationships", []),
        "assertions": projected.get("assertions", []),
        "episodes": projected.get("episodes", []),
        "experiences": experiences,
        "state_facts": projected.get("state_facts", []),
        "state_history": projected.get("state_history", []),
    }


def _build_execution_trace(
    plan: L2GroundingPlan,
    channels: _L2ChannelResults,
    candidates: list[Any],
    results: dict[str, Any],
) -> dict[str, Any]:
    return {
        "grounding_plan": _build_grounding_plan_trace(plan),
        "channel_counts": {
            "knowledge_edges": len(channels.knowledge_edges),
            "assertions": len(channels.assertions),
            "snapshots": len(channels.snapshots),
            "episodes": len(channels.episodes),
            "experiences": len(channels.experiences),
        },
        "fusion_candidate_count": len(candidates),
        "output_counts": {
            "entity_cards": len(results["entity_cards"]),
            "relationships": len(results["relationships"]),
            "assertions": len(results["assertions"]),
            "episodes": len(results["episodes"]),
            "experiences": len(results["experiences"]),
            "state_history": len(results["state_history"]),
        },
    }


def _merge_experience_source_episodes(
    episodes: list[dict[str, Any]],
    experiences: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    merged = list(episodes)
    seen = {str(ep.get("episode_id") or "") for ep in merged}
    for experience in experiences:
        for source_episode in experience.get("source_episodes") or []:
            episode_id = str(source_episode.get("episode_id") or "")
            if not episode_id or episode_id in seen:
                continue
            episode = dict(source_episode)
            episode["_candidate_kind"] = "episode"
            episode["_from_experience_id"] = experience.get("experience_id")
            merged.append(episode)
            seen.add(episode_id)
    return merged


def _build_grounding_plan_trace(plan: L2GroundingPlan) -> dict[str, Any]:
    """Build the grounding-plan slice of the L2 retrieval trace dict.

    Kept as a small helper so the dict shape is easy to unit-test without
    spinning up a full retriever. The output must remain stable: external
    log consumers grep these keys.
    """
    return {
        "query_kind": plan.query_kind,
        "subject_scope": plan.subject_scope,
        "answer_kind": plan.answer_kind,
        "predicate_family": plan.predicate_family,
        "confidence": plan.confidence,
        "temporal_mode": plan.temporal_context.mode,
        "subject_count": len(plan.subject_candidates),
        "object_count": len(plan.object_candidates),
        "predicate_count": len(plan.predicate_candidates),
        "allowed_evidence_classes": (
            sorted(plan.allowed_evidence_classes) if plan.allowed_evidence_classes else None
        ),
        "evidence_focus_source": plan.evidence_focus_source,
        "predicate_source": plan.predicate_source,
        "subject_entity_ids": list(plan.subject_entity_ids),
        "object_entity_ids": list(plan.object_entity_ids),
    }


__all__ = ["L2QueryExecutionMixin"]
