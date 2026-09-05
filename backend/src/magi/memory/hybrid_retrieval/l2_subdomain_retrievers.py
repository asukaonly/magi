"""L2 subdomain retrievers: assertion, snapshot, and episode retrieval.

Each retriever takes an L2GroundingPlan and an L2 store reference, queries the
relevant subdomain, and returns normalized candidate dicts ready for fusion.
"""

from __future__ import annotations

import json
import logging
import re
import time
from typing import Any

from ..l2.assertions.state_machine import (
    ACTIVE_VALIDATION_STATES,
    HISTORICAL_VALIDATION_STATES,
)
from .grounding import L2GroundingPlan
from .temporal import (
    build_assertion_temporal_clause,
    compute_temporal_score,
)

logger = logging.getLogger(__name__)

_ACTIVE_EXPERIENCE_STATUSES = frozenset({"active", "candidate"})
_HIDDEN_EXPERIENCE_STATUSES = frozenset({"hidden", "merged", "invalidated", "deleted"})
_MAX_SOURCE_EPISODES_PER_EXPERIENCE = 5


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
    include_superseded = tc is not None and tc.mode not in ("none", "current")

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
            include_superseded=include_superseded,
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
            include_superseded=include_superseded,
            target_entity_id=target_entity_id,
            limit=limit,
            temporal_clause=clause_arg,
        )

    for assertion in assertions:
        first_observed = assertion.get("first_inferred_at")
        last_observed = assertion.get("last_validated_at")
        if (
            assertion.get("_governed_valid_at") is not None
            and tc is not None
            and tc.mode == "during"
        ):
            # Governed claim versions describe a validity interval. Observation
            # timestamps only describe when evidence arrived and would wrongly
            # discard an older version whose validity extends into the query
            # window (or a replacement that remains valid after its creation).
            first_observed = assertion.get("valid_from") or first_observed
            last_observed = assertion.get("valid_to") or tc.end or last_observed
        assertion["_temporal_score"] = compute_temporal_score(
            tc,
            first_observed=first_observed,
            last_observed=last_observed,
        )
        assertion["_candidate_kind"] = "assertion"

    return assertions


def _infer_assertion_trait_families(plan: L2GroundingPlan) -> list[str] | None:
    """Map grounding plan to relevant trait families."""
    kind = plan.query_kind
    if kind == "current_state":
        return ["mood", "stress", "engagement"]
    if kind == "preference":
        return ["preference_profile"]
    if kind == "historical_state":
        return ["mood", "stress", "engagement", "preference_profile"]
    return None


def _infer_assertion_states(tc: Any) -> list[str] | None:
    """Determine which validation states to include based on temporal mode.

    Must mirror the states `derive_validation_state` actually emits — including
    the graduated ``stable`` state — so the strongest ToM facts stay retrievable.
    """
    if tc is None or tc.mode in ("none", "current"):
        return list(ACTIVE_VALIDATION_STATES)
    return list(HISTORICAL_VALIDATION_STATES)


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
            # A snapshot is a current derived view. Letting it participate in
            # an historical answer can reintroduce a post-correction value next
            # to the governed as-of assertion or relationship. Only explicitly
            # timestamped snapshot history is eligible for historical recall.
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
        entities.append(
            {
                "entity_id": candidate.entity_id,
                "entity_type": candidate.entity_type,
            }
        )
    for candidate in plan.object_candidates:
        if candidate.entity_type not in ("place",):
            entities.append(
                {
                    "entity_id": candidate.entity_id,
                    "entity_type": candidate.entity_type,
                }
            )
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
                    tc,
                    first_observed=ts,
                    last_observed=ts,
                )
                entry["_history_field"] = field_name
                results.append(entry)

    raw_mood = snapshot.get("mood_trajectory")
    mood_entries = _parse_json_field(raw_mood)
    for entry in mood_entries:
        ts = entry.get("at")
        if ts is not None and _timestamp_in_window(ts, tc):
            entry["_temporal_score"] = compute_temporal_score(
                tc,
                first_observed=ts,
                last_observed=ts,
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
    """Retrieve episodes matching the grounding plan via time overlap.

    Episodes participate in recall as the time-anchored narrative substrate
    only. Content-based recall is deliberately delegated to L1 event search
    and experiences: episode summaries are folded source digests, so letting
    them match on content mostly spends token budget on noise.
    """
    tc = plan.temporal_context
    episodes = await _query_episodes_by_time(store, tc, limit=limit)

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

    kwargs["statuses"] = ["active"]
    return await store.list_episodes(**kwargs)


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


# ---------------------------------------------------------------------------
# Experience retriever
# ---------------------------------------------------------------------------


async def retrieve_experiences(
    plan: L2GroundingPlan,
    store: Any,
    *,
    limit: int = 10,
) -> list[dict[str, Any]]:
    """Retrieve user-facing experiences that match a recall query.

    Experiences sit above episodes. V1 deliberately reuses the L2 store and
    keeps matching conservative: a query with textual/entity signals must match
    experience text or anchors before it can surface.
    """
    if not callable(getattr(store, "list_experiences", None)):
        return []

    tc = plan.temporal_context
    experiences = await _query_experiences_by_time(store, tc, limit=max(limit * 4, 20))
    terms = _experience_search_terms(plan)
    has_query_signal = bool(terms or plan.subject_entity_ids or plan.object_entity_ids)

    candidates: list[dict[str, Any]] = []
    for experience in experiences:
        if not _experience_is_visible(experience):
            continue
        text_score = _compute_experience_text_score(experience, terms)
        entity_score = _compute_experience_entity_overlap(experience, plan)
        if has_query_signal and text_score <= 0.0 and entity_score <= 0.0:
            continue
        temporal_score = compute_temporal_score(
            tc,
            first_observed=experience.get("time_start"),
            last_observed=experience.get("time_end"),
        )
        quality_score = _compute_experience_quality_score(experience)
        retrieval_score = (
            text_score * 0.45 + entity_score * 0.25 + temporal_score * 0.15 + quality_score * 0.15
        )
        item = dict(experience)
        item["_candidate_kind"] = "experience"
        item["_retrieval_score"] = retrieval_score
        item["_experience_text_score"] = text_score
        item["_experience_entity_overlap_score"] = entity_score
        item["_temporal_score"] = temporal_score
        item["_quality_score"] = quality_score
        candidates.append(item)

    candidates.sort(key=lambda item: float(item.get("_retrieval_score") or 0.0), reverse=True)
    selected = candidates[:limit]
    for experience in selected:
        await _attach_experience_members(experience, store)
    return selected


async def _query_experiences_by_time(
    store: Any,
    tc: Any,
    *,
    limit: int = 20,
) -> list[dict[str, Any]]:
    kwargs: dict[str, Any] = {"limit": limit, "statuses": list(_ACTIVE_EXPERIENCE_STATUSES)}
    if tc is not None and tc.mode != "none":
        if tc.mode == "current":
            kwargs["time_start"] = time.time() - 86400 * 30
        elif tc.mode == "as_of" and tc.anchor is not None:
            kwargs["time_start"] = tc.anchor - 86400 * 7
            kwargs["time_end"] = tc.anchor + 86400 * 7
        elif tc.mode == "during" and tc.start is not None and tc.end is not None:
            kwargs["time_start"] = tc.start
            kwargs["time_end"] = tc.end
        elif tc.mode == "since" and tc.start is not None:
            kwargs["time_start"] = tc.start
        elif tc.mode == "before" and tc.end is not None:
            kwargs["time_end"] = tc.end
        elif tc.mode == "after" and tc.start is not None:
            kwargs["time_start"] = tc.start
    return await store.list_experiences(**kwargs)


def _experience_is_visible(experience: dict[str, Any]) -> bool:
    status = str(experience.get("status") or "").strip().lower()
    if status in _HIDDEN_EXPERIENCE_STATUSES:
        return False
    if status and status not in _ACTIVE_EXPERIENCE_STATUSES:
        return False
    if experience.get("merged_into_experience_id"):
        return False
    return True


def _experience_search_terms(plan: L2GroundingPlan) -> list[str]:
    terms: list[str] = []
    terms.extend(_text_terms(plan.content_query))
    for candidate in [*plan.subject_candidates, *plan.object_candidates]:
        if candidate.surface and candidate.surface != "self":
            terms.extend(_text_terms(candidate.surface))
        if candidate.entity_id:
            terms.extend(_entity_id_terms(candidate.entity_id))
    deduped: list[str] = []
    seen: set[str] = set()
    for term in terms:
        normalized = term.strip().lower()
        if len(normalized) < 2 or normalized in seen:
            continue
        seen.add(normalized)
        deduped.append(normalized)
    return deduped


def _text_terms(text: Any) -> list[str]:
    normalized = str(text or "").strip().lower()
    if not normalized:
        return []
    terms = re.findall(r"[a-z0-9][a-z0-9_\-]{1,}", normalized)
    for cjk_run in re.findall(r"[\u4e00-\u9fff]{2,}", normalized):
        terms.append(cjk_run)
        terms.extend(_cjk_ngrams(cjk_run))
    return terms


def _cjk_ngrams(text: str) -> list[str]:
    tokens: list[str] = []
    for size in (2, 3, 4):
        if len(text) < size:
            continue
        tokens.extend(text[index : index + size] for index in range(0, len(text) - size + 1))
    return tokens


def _entity_id_terms(entity_id: str) -> list[str]:
    raw = str(entity_id or "").strip().lower()
    if not raw:
        return []
    slug = raw.split(":", 1)[1] if ":" in raw else raw
    return [term for term in re.split(r"[-_:/\s]+", slug) if len(term) >= 2]


def _experience_text_blob(experience: dict[str, Any]) -> str:
    fields: list[str] = []
    for key in (
        "user_label",
        "title",
        "user_note",
        "magi_interpretation",
        "intent",
        "outcome",
        "experience_type",
    ):
        value = experience.get(key)
        if value:
            fields.append(str(value))
    for key in ("primary_entity_ids", "primary_place_ids", "primary_topic_keys"):
        value = experience.get(key) or []
        if isinstance(value, list):
            fields.extend(str(item) for item in value if item)
    return " ".join(fields).lower()


def _compute_experience_text_score(experience: dict[str, Any], terms: list[str]) -> float:
    if not terms:
        return 0.0
    text = _experience_text_blob(experience)
    if not text:
        return 0.0
    matched = [term for term in terms if term in text]
    if not matched:
        return 0.0
    coverage = len(set(matched)) / max(1, len(set(terms)))
    return min(1.0, 0.35 + coverage * 0.65)


def _compute_experience_entity_overlap(experience: dict[str, Any], plan: L2GroundingPlan) -> float:
    experience_entities = set(experience.get("primary_entity_ids") or [])
    experience_places = set(experience.get("primary_place_ids") or [])
    experience_topics = set(experience.get("primary_topic_keys") or [])
    plan_entities = set(plan.subject_entity_ids + plan.object_entity_ids)
    if not plan_entities:
        return 0.0
    overlap = (experience_entities | experience_places | experience_topics) & plan_entities
    if not overlap:
        return 0.0
    return min(1.0, len(overlap) / len(plan_entities))


def _compute_experience_quality_score(experience: dict[str, Any]) -> float:
    narrative = min(1.0, max(0.0, float(experience.get("narrative_score") or 0.0)))
    episode_count = min(1.0, float(experience.get("source_episode_count") or 0) / 3.0)
    event_count = min(1.0, float(experience.get("source_event_count") or 0) / 20.0)
    user_signal = 0.0
    if experience.get("user_pinned"):
        user_signal += 0.35
    if experience.get("user_label"):
        user_signal += 0.20
    if experience.get("user_note"):
        user_signal += 0.20
    return min(1.0, narrative * 0.35 + episode_count * 0.20 + event_count * 0.25 + user_signal)


async def _attach_experience_members(experience: dict[str, Any], store: Any) -> None:
    experience_id = str(experience.get("experience_id") or "").strip()
    if not experience_id or not callable(getattr(store, "list_experience_members", None)):
        experience["members"] = []
        experience["source_episode_ids"] = []
        experience["source_event_ids"] = []
        experience["source_episodes"] = []
        return
    members = [
        member
        for member in await store.list_experience_members(experience_id=experience_id, limit=500)
        if str(member.get("role") or "").strip() != "excluded"
    ]
    episode_ids = [
        str(member.get("member_id") or "")
        for member in members
        if str(member.get("member_type") or "") == "episode" and member.get("member_id")
    ]
    event_ids = [
        str(member.get("member_id") or "")
        for member in members
        if str(member.get("member_type") or "") == "event" and member.get("member_id")
    ]
    experience["members"] = members
    experience["source_episode_ids"] = episode_ids
    experience["source_event_ids"] = event_ids
    experience["source_episodes"] = await _load_member_episodes(store, episode_ids)


async def _load_member_episodes(store: Any, episode_ids: list[str]) -> list[dict[str, Any]]:
    if not episode_ids or not callable(getattr(store, "get_episode", None)):
        return []
    episodes: list[dict[str, Any]] = []
    for episode_id in episode_ids[:_MAX_SOURCE_EPISODES_PER_EXPERIENCE]:
        episode = await store.get_episode(episode_id=episode_id)
        if episode:
            episodes.append(episode)
    return episodes


__all__ = [
    "retrieve_assertions",
    "retrieve_episodes",
    "retrieve_experiences",
    "retrieve_snapshots",
]
