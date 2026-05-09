"""L2 subdomain retrievers: assertion, snapshot, and episode retrieval.

Each retriever takes an L2GroundingPlan and an L2 store reference, queries the
relevant subdomain, and returns normalized candidate dicts ready for fusion.
"""

from __future__ import annotations

import json
import logging
import time
from typing import Any

from .grounding import L2GroundingPlan
from .temporal import (
    build_assertion_temporal_clause,
    compute_temporal_score,
)

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Assertion retriever (Work Item 6)
# ---------------------------------------------------------------------------


async def retrieve_assertions(
    plan: L2GroundingPlan,
    store: Any,
    *,
    limit: int = 20,
) -> list[dict[str, Any]]:
    """Retrieve ToM assertions matching the grounding plan."""
    tc = plan.temporal_context
    temporal_clause = build_assertion_temporal_clause(tc)
    tc_sql, tc_params = temporal_clause
    clause_arg = (tc_sql, tc_params) if tc_sql else None

    trait_families = _infer_assertion_trait_families(plan)
    validation_states = _infer_assertion_states(tc)

    entity_ids = plan.subject_entity_ids
    target_entity_id = plan.object_entity_ids[0] if plan.object_entity_ids else None

    if entity_ids:
        batch_result = await store.batch_list_tom_assertions(
            entity_ids=entity_ids,
            trait_families=trait_families,
            validation_states=validation_states,
            include_expired=False,
            target_entity_id=target_entity_id,
            limit_per_entity=limit,
            temporal_clause=clause_arg,
        )
        assertions: list[dict[str, Any]] = []
        for entity_assertions in batch_result.values():
            assertions.extend(entity_assertions)
    else:
        assertions = await store.list_tom_assertions(
            trait_families=trait_families,
            validation_states=validation_states,
            include_expired=False,
            target_entity_id=target_entity_id,
            limit=limit,
            temporal_clause=clause_arg,
        )

    for assertion in assertions:
        assertion["_temporal_score"] = compute_temporal_score(
            tc,
            first_observed=assertion.get("first_inferred_at"),
            last_observed=assertion.get("last_validated_at"),
        )
        assertion["_candidate_kind"] = "assertion"

    return assertions


def _infer_assertion_trait_families(plan: L2GroundingPlan) -> list[str] | None:
    """Map grounding plan to relevant trait families."""
    kind = plan.query_kind
    if kind == "current_state":
        return ["mood", "stress", "engagement"]
    if kind == "preference":
        return ["preference_profile", "taste_profile"]
    if kind == "historical_state":
        return ["mood", "stress", "engagement", "preference_profile"]
    return None


def _infer_assertion_states(tc: Any) -> list[str] | None:
    """Determine which validation states to include based on temporal mode."""
    if tc is None or tc.mode in ("none", "current"):
        return ["active", "corroborated", "tentative", "stable-compatible"]
    return ["active", "corroborated", "tentative", "stable-compatible", "superseded"]


# ---------------------------------------------------------------------------
# Snapshot retriever (Work Item 7)
# ---------------------------------------------------------------------------


async def retrieve_snapshots(
    plan: L2GroundingPlan,
    store: Any,
) -> list[dict[str, Any]]:
    """Retrieve ToM snapshots, splitting current vs historical evidence."""
    entities = _snapshot_query_entities(plan)
    if not entities:
        return []

    snapshots = await store.batch_get_tom_snapshots(entities=entities)
    if not snapshots:
        return []

    tc = plan.temporal_context
    results: list[dict[str, Any]] = []

    for snapshot in snapshots:
        if tc.mode in ("none", "current"):
            snapshot["_temporal_score"] = 1.0
            snapshot["_candidate_kind"] = "snapshot"
            results.append(snapshot)
        else:
            current_entry = dict(snapshot)
            current_entry["_temporal_score"] = 0.2
            current_entry["_candidate_kind"] = "snapshot"
            results.append(current_entry)

            history_entries = _extract_snapshot_history(snapshot, tc)
            for entry in history_entries:
                entry["_candidate_kind"] = "snapshot_history"
                entry["_source_entity_id"] = snapshot.get("entity_id")
                entry["_source_entity_type"] = snapshot.get("entity_type")
                results.append(entry)

    return results


def _snapshot_query_entities(plan: L2GroundingPlan) -> list[dict[str, str]]:
    """Determine which entities to fetch snapshots for."""
    entities: list[dict[str, str]] = []
    for candidate in plan.subject_candidates:
        entities.append({
            "entity_id": candidate.entity_id,
            "entity_type": candidate.entity_type,
        })
    for candidate in plan.object_candidates:
        if candidate.entity_type not in ("place",):
            entities.append({
                "entity_id": candidate.entity_id,
                "entity_type": candidate.entity_type,
            })
    return entities


def _extract_snapshot_history(
    snapshot: dict[str, Any],
    tc: Any,
) -> list[dict[str, Any]]:
    """Extract timestamped history entries from snapshot that match the temporal context."""
    results: list[dict[str, Any]] = []

    for field_name in ("core_traits_history", "preferences_history", "relationship_history"):
        raw = snapshot.get(field_name)
        entries = _parse_json_field(raw)
        for entry in entries:
            ts = entry.get("evolved_at")
            if ts is not None and _timestamp_in_window(ts, tc):
                entry["_temporal_score"] = compute_temporal_score(
                    tc, first_observed=ts, last_observed=ts,
                )
                entry["_history_field"] = field_name
                results.append(entry)

    raw_mood = snapshot.get("mood_trajectory")
    mood_entries = _parse_json_field(raw_mood)
    for entry in mood_entries:
        ts = entry.get("at")
        if ts is not None and _timestamp_in_window(ts, tc):
            entry["_temporal_score"] = compute_temporal_score(
                tc, first_observed=ts, last_observed=ts,
            )
            entry["_history_field"] = "mood_trajectory"
            results.append(entry)

    return results


def _parse_json_field(raw: Any) -> list[dict[str, Any]]:
    """Parse a JSON field that may be a string, list, or None."""
    if raw is None:
        return []
    if isinstance(raw, str):
        try:
            parsed = json.loads(raw)
            return parsed if isinstance(parsed, list) else []
        except (json.JSONDecodeError, TypeError):
            return []
    if isinstance(raw, list):
        return raw
    return []


def _timestamp_in_window(ts: float, tc: Any) -> bool:
    """Check if a timestamp falls within the temporal context window."""
    if tc is None or tc.mode == "none":
        return True
    if tc.mode == "current":
        return True
    if tc.mode == "as_of" and tc.anchor is not None:
        return ts <= tc.anchor
    if tc.mode == "during" and tc.start is not None and tc.end is not None:
        return tc.start <= ts <= tc.end
    if tc.mode == "since" and tc.start is not None:
        return ts >= tc.start
    if tc.mode == "before" and tc.end is not None:
        return ts <= tc.end
    if tc.mode == "after" and tc.start is not None:
        return ts >= tc.start
    return True


# ---------------------------------------------------------------------------
# Episode retriever (Work Item 8)
# ---------------------------------------------------------------------------


async def retrieve_episodes(
    plan: L2GroundingPlan,
    store: Any,
    *,
    limit: int = 10,
) -> list[dict[str, Any]]:
    """Retrieve episodes matching the grounding plan via time overlap + FTS."""
    tc = plan.temporal_context
    episodes: list[dict[str, Any]] = []
    seen_ids: set[str] = set()

    time_episodes = await _query_episodes_by_time(store, tc, limit=limit)
    for ep in time_episodes:
        eid = ep.get("episode_id", "")
        if eid and eid not in seen_ids:
            seen_ids.add(eid)
            episodes.append(ep)

    if plan.predicate_family or plan.query_kind != "unknown":
        content = _build_episode_fts_query(plan)
        if content:
            fts_episodes = await store.search_episodes_fts(query=content, limit=limit)
            for ep in fts_episodes:
                eid = ep.get("episode_id", "")
                if eid and eid not in seen_ids:
                    seen_ids.add(eid)
                    episodes.append(ep)

    for ep in episodes:
        ep["_temporal_score"] = _compute_episode_temporal_score(ep, tc)
        ep["_entity_overlap_score"] = _compute_entity_overlap(ep, plan)
        ep["_candidate_kind"] = "episode"

    episodes.sort(
        key=lambda e: (
            e.get("_temporal_score", 0) * 0.5
            + e.get("_entity_overlap_score", 0) * 0.3
            + (0.2 if e.get("user_pinned") else 0.0)
        ),
        reverse=True,
    )

    return episodes[:limit]


async def _query_episodes_by_time(
    store: Any,
    tc: Any,
    *,
    limit: int = 10,
) -> list[dict[str, Any]]:
    """Query episodes using temporal window."""
    kwargs: dict[str, Any] = {"limit": limit}

    if tc is not None and tc.mode != "none":
        if tc.mode == "current":
            kwargs["time_start"] = time.time() - 86400 * 7
        elif tc.mode == "as_of" and tc.anchor is not None:
            kwargs["time_start"] = tc.anchor - 86400
            kwargs["time_end"] = tc.anchor + 86400
        elif tc.mode == "during" and tc.start is not None and tc.end is not None:
            kwargs["time_start"] = tc.start
            kwargs["time_end"] = tc.end
        elif tc.mode == "since" and tc.start is not None:
            kwargs["time_start"] = tc.start
        elif tc.mode == "before" and tc.end is not None:
            kwargs["time_end"] = tc.end
        elif tc.mode == "after" and tc.start is not None:
            kwargs["time_start"] = tc.start

    kwargs["statuses"] = ["active", "candidate"]
    return await store.list_episodes(**kwargs)


def _build_episode_fts_query(plan: L2GroundingPlan) -> str | None:
    """Build FTS query string from grounding plan entities."""
    terms: list[str] = []
    for c in plan.subject_candidates:
        if c.surface and c.surface != "self":
            terms.append(c.surface)
    for c in plan.object_candidates:
        if c.surface:
            terms.append(c.surface)
    if not terms:
        return None
    return " ".join(terms)


def _compute_episode_temporal_score(ep: dict[str, Any], tc: Any) -> float:
    """Score episode temporal fit."""
    return compute_temporal_score(
        tc,
        first_observed=ep.get("time_start"),
        last_observed=ep.get("time_end"),
    )


def _compute_entity_overlap(ep: dict[str, Any], plan: L2GroundingPlan) -> float:
    """Score entity overlap between episode and grounding plan."""
    ep_entities = set(ep.get("primary_entity_ids") or [])
    ep_places = set(ep.get("primary_place_ids") or [])
    ep_topics = set(ep.get("primary_topic_keys") or [])

    plan_entities = set(plan.subject_entity_ids + plan.object_entity_ids)
    if not plan_entities:
        return 0.0

    all_ep = ep_entities | ep_places | ep_topics
    overlap = all_ep & plan_entities
    if not overlap:
        return 0.0
    return min(1.0, len(overlap) / len(plan_entities))


__all__ = [
    "retrieve_assertions",
    "retrieve_episodes",
    "retrieve_snapshots",
]
