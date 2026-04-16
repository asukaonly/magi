"""Streaming episode candidate formation and periodic consolidation.

Streaming formation hooks into the L2 pipeline extract worker:
after each extraction, events are assigned to an existing candidate
episode or start a new one, based on time gap and entity overlap.

Periodic consolidation promotes mature candidates, merges adjacent
episodes, and queues summaries/embeddings.
"""

from __future__ import annotations

import time
import uuid
from typing import Any, Dict, List, Optional

from ...core.logger import get_logger
from .models import EpisodeCandidateJob, EpisodeConsolidationStats
from .store import L2CognitionStore

logger = get_logger(__name__)

# ── Gap thresholds (seconds) per episode_type ────────────────────

EPISODE_MAX_GAP: Dict[str, float] = {
    "default": 30 * 60,       # 30 minutes
    "activity": 30 * 60,
    "visit": 2 * 60 * 60,     # 2 hours
    "session": 60 * 60,       # 1 hour
    "conversation": 10 * 60,  # 10 minutes
}

# ── Consolidation thresholds ─────────────────────────────────────

MIN_EVENTS_TO_PROMOTE = 3
MIN_AGE_TO_PROMOTE = 30 * 60  # 30 minutes
MERGE_GAP_FACTOR = 1.5        # merge if gap < 1.5x normal threshold
MIN_ENTITY_OVERLAP_FOR_MERGE = 0.3


def _shares_theme(
    entity_ids_a: List[str],
    entity_ids_b: List[str],
    topic_keys_a: Optional[List[str]] = None,
    topic_keys_b: Optional[List[str]] = None,
) -> bool:
    """Check whether two event/episode contexts share a theme.

    Adapted from ``TimelineClusterBuilder._shares_theme``.
    """
    if entity_ids_a and entity_ids_b:
        if set(entity_ids_a) & set(entity_ids_b):
            return True
    if topic_keys_a and topic_keys_b:
        if set(topic_keys_a) & set(topic_keys_b):
            return True
    return False


def _entity_overlap_ratio(a: List[str], b: List[str]) -> float:
    if not a or not b:
        return 0.0
    sa, sb = set(a), set(b)
    intersection = len(sa & sb)
    return intersection / min(len(sa), len(sb))


async def assign_events_to_episode(
    store: L2CognitionStore,
    jobs: List[EpisodeCandidateJob],
) -> Optional[str]:
    """Assign one or more event candidate jobs to an episode.

    Finds the most recent ``candidate`` episode that is within the gap
    threshold and shares a theme with the incoming events. If none is
    found, creates a new candidate episode.

    Returns the episode_id that the events were assigned to.
    """
    if not jobs:
        return None

    # Aggregate metadata across all jobs in this micro-batch
    all_entity_ids: list[str] = []
    all_place_ids: list[str] = []
    all_topic_keys: list[str] = []
    min_ts = float("inf")
    max_ts = 0.0
    event_ids: list[str] = []
    episode_type_hint = "activity"

    for job in jobs:
        event_ids.append(job.event_id)
        all_entity_ids.extend(job.entity_ids)
        all_place_ids.extend(job.place_ids)
        all_topic_keys.extend(job.topic_keys)
        if job.event_timestamp < min_ts:
            min_ts = job.event_timestamp
        if job.event_timestamp > max_ts:
            max_ts = job.event_timestamp
        if job.episode_type_hint != "activity":
            episode_type_hint = job.episode_type_hint

    # De-dup
    unique_entity_ids = sorted(set(all_entity_ids))
    unique_place_ids = sorted(set(all_place_ids))
    unique_topic_keys = sorted(set(all_topic_keys))

    max_gap = EPISODE_MAX_GAP.get(episode_type_hint, EPISODE_MAX_GAP["default"])

    # Try to find an existing candidate to extend
    candidate = await store.find_recent_candidate_episode(
        episode_type=episode_type_hint,
        max_gap=max_gap,
        before_time=max_ts + 1,
        entity_ids=unique_entity_ids or None,
    )

    if candidate is not None:
        ep_entities = candidate.get("primary_entity_ids") or []
        ep_topics = candidate.get("primary_topic_keys") or []
        if _shares_theme(ep_entities, unique_entity_ids, ep_topics, unique_topic_keys) or not unique_entity_ids:
            # Extend existing candidate
            episode_id = candidate["episode_id"]
            new_end = max(candidate["time_end"], max_ts)
            new_start = min(candidate["time_start"], min_ts)
            merged_entities = sorted(set(ep_entities) | set(unique_entity_ids))
            merged_places = sorted(set(candidate.get("primary_place_ids") or []) | set(unique_place_ids))
            merged_topics = sorted(set(ep_topics) | set(unique_topic_keys))
            new_count = candidate["source_event_count"] + len(event_ids)

            await store.update_episode(
                episode_id=episode_id,
                time_start=new_start,
                time_end=new_end,
                primary_entity_ids=merged_entities,
                primary_place_ids=merged_places,
                primary_topic_keys=merged_topics,
                source_event_count=new_count,
            )
            await store.add_episode_events(
                episode_id=episode_id,
                event_ids=event_ids,
            )
            logger.debug(
                "Episode candidate extended",
                episode_id=episode_id,
                added_events=len(event_ids),
                new_count=new_count,
            )
            return episode_id

    # No suitable candidate — create new episode
    episode_id = str(uuid.uuid4())
    await store.create_episode(
        episode_id=episode_id,
        episode_type=episode_type_hint,
        status="candidate",
        time_start=min_ts,
        time_end=max_ts,
        primary_entity_ids=unique_entity_ids,
        primary_place_ids=unique_place_ids,
        primary_topic_keys=unique_topic_keys,
        formation_method="time_gap_cluster",
        source_event_count=len(event_ids),
    )
    await store.add_episode_events(
        episode_id=episode_id,
        event_ids=event_ids,
    )
    logger.debug(
        "Episode candidate created",
        episode_id=episode_id,
        event_count=len(event_ids),
        episode_type=episode_type_hint,
    )
    return episode_id


async def consolidate_episodes(
    store: L2CognitionStore,
) -> EpisodeConsolidationStats:
    """Run periodic episode consolidation.

    1. Promote mature candidates to ``active``
    2. Merge adjacent active episodes with high entity overlap
    3. Invalidate episodes that lost too many events

    Returns consolidation statistics.
    """
    stats = EpisodeConsolidationStats()
    now = time.time()

    # ── 1. Promote mature candidates ─────────────────────────────
    candidates = await store.list_episodes(status="candidate", limit=500)
    for ep in candidates:
        age = now - ep["created_at"]
        if ep["source_event_count"] >= MIN_EVENTS_TO_PROMOTE and age >= MIN_AGE_TO_PROMOTE:
            await store.update_episode(episode_id=ep["episode_id"], status="active")
            stats.promoted += 1
            logger.debug(
                "Episode promoted",
                episode_id=ep["episode_id"],
                event_count=ep["source_event_count"],
                age_minutes=round(age / 60, 1),
            )

    # ── 2. Merge adjacent active episodes ────────────────────────
    active_episodes = await store.list_episodes(status="active", limit=500)
    if len(active_episodes) >= 2:
        # Sort by time_start ascending for merge scan
        sorted_eps = sorted(active_episodes, key=lambda e: e["time_start"])
        merged_ids: set[str] = set()

        for i in range(len(sorted_eps) - 1):
            if sorted_eps[i]["episode_id"] in merged_ids:
                continue
            curr = sorted_eps[i]
            nxt = sorted_eps[i + 1]
            if nxt["episode_id"] in merged_ids:
                continue
            if curr["episode_type"] != nxt["episode_type"]:
                continue

            gap = nxt["time_start"] - curr["time_end"]
            max_gap = EPISODE_MAX_GAP.get(curr["episode_type"], EPISODE_MAX_GAP["default"])
            if gap > max_gap * MERGE_GAP_FACTOR:
                continue

            overlap = _entity_overlap_ratio(
                curr.get("primary_entity_ids") or [],
                nxt.get("primary_entity_ids") or [],
            )
            if overlap < MIN_ENTITY_OVERLAP_FOR_MERGE:
                continue

            # Merge nxt into curr
            merged_entities = sorted(set(curr.get("primary_entity_ids") or []) | set(nxt.get("primary_entity_ids") or []))
            merged_places = sorted(set(curr.get("primary_place_ids") or []) | set(nxt.get("primary_place_ids") or []))
            merged_topics = sorted(set(curr.get("primary_topic_keys") or []) | set(nxt.get("primary_topic_keys") or []))
            new_count = curr["source_event_count"] + nxt["source_event_count"]

            await store.update_episode(
                episode_id=curr["episode_id"],
                time_end=max(curr["time_end"], nxt["time_end"]),
                primary_entity_ids=merged_entities,
                primary_place_ids=merged_places,
                primary_topic_keys=merged_topics,
                source_event_count=new_count,
            )
            # Move nxt's events to curr
            nxt_events = await store.list_episode_events(episode_id=nxt["episode_id"])
            if nxt_events:
                await store.add_episode_events(
                    episode_id=curr["episode_id"],
                    event_ids=[e["event_id"] for e in nxt_events],
                )
            await store.update_episode(episode_id=nxt["episode_id"], status="merged")
            merged_ids.add(nxt["episode_id"])
            stats.merged += 1
            logger.debug(
                "Episodes merged",
                survivor=curr["episode_id"],
                absorbed=nxt["episode_id"],
                entity_overlap=round(overlap, 2),
            )

    # ── 3. Invalidate episodes with too few remaining events ─────
    active_after = await store.list_episodes(
        statuses=["candidate", "active"], limit=500
    )
    for ep in active_after:
        if ep["source_event_count"] < 2:
            events = await store.list_episode_events(episode_id=ep["episode_id"], limit=5)
            if len(events) < 2:
                await store.update_episode(episode_id=ep["episode_id"], status="invalidated")
                stats.invalidated += 1
                logger.debug(
                    "Episode invalidated",
                    episode_id=ep["episode_id"],
                    remaining_events=len(events),
                )

    logger.info(
        "Episode consolidation completed",
        promoted=stats.promoted,
        merged=stats.merged,
        invalidated=stats.invalidated,
    )
    return stats
