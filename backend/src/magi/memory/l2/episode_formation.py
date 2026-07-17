"""Streaming episode candidate formation and periodic consolidation.

Streaming formation hooks into the L2 pipeline extract worker:
after each extraction, events are assigned to an existing candidate
episode or start a new one, based on time gap and entity/topic overlap.

Periodic consolidation promotes mature candidates, merges adjacent
episodes, and queues summaries/embeddings.
"""

from __future__ import annotations

import time
import uuid
from dataclasses import dataclass
from typing import Any, Dict, List, Optional

from ...core.logger import get_logger
from ...core.sqlite import sqlite_connection_async
from ..source_event_governance import (
    promote_source_event_entity_projection_candidates,
)
from .anchors import is_generic_experience_anchor
from .models import EpisodeCandidateJob, EpisodeConsolidationStats
from .store import L2CognitionStore
from .storage.utils import _l2_setting

logger = get_logger(__name__)

# ── Gap thresholds (seconds) per episode_type ────────────────────

EPISODE_MAX_GAP: Dict[str, float] = {
    "default": 30 * 60,  # 30 minutes
    "activity": 30 * 60,
    "visit": 2 * 60 * 60,  # 2 hours
    "session": 60 * 60,  # 1 hour
    "conversation": 10 * 60,  # 10 minutes
}

# Raw event_type (e.g. ``MemoryEvent.event_type`` like ``"UserMessage"``) →
# gap-table category. Without this the multi-type gap table is dead: a raw
# event_type is never a key in ``EPISODE_MAX_GAP`` and always falls to the
# 30-min ``default`` gap. Keep this small and explicit.
_EVENT_TYPE_TO_EPISODE_TYPE: Dict[str, str] = {
    # Chat / message exchanges → tight conversation gap
    "UserMessage": "conversation",
    "AIResponse": "conversation",
    "UserMessageReceived": "conversation",
    "AssistantResponseProduced": "conversation",
    # Location / visit events → loose visit gap
    "LocationVisit": "visit",
    "PlaceVisit": "visit",
}


def episode_type_for_event(event_type: str) -> str:
    """Map a raw ``event_type`` to a gap-table category in ``EPISODE_MAX_GAP``.

    Chat/message types cluster as ``"conversation"``; location/visit types as
    ``"visit"``; anything unrecognized falls back to the safe ``"activity"``
    default. The result is always a valid ``EPISODE_MAX_GAP`` key.
    """
    return _EVENT_TYPE_TO_EPISODE_TYPE.get(event_type, "activity")


# ── Consolidation thresholds ─────────────────────────────────────

MIN_EVENTS_TO_PROMOTE = 3
MIN_AGE_TO_PROMOTE = 30 * 60  # 30 minutes
MERGE_GAP_FACTOR = 1.5  # merge if gap < 1.5x normal threshold
MIN_ENTITY_OVERLAP_FOR_MERGE = 0.3

# Standout gate thresholds — episodes that pass become product-grade chapters
# surfaced in the 经历 page. V1.1 rule:
#   - at least 8 supporting events
#   - at least 45 minutes of duration OR at least 20 dense supporting events
#   - at least 2 distinct primary entities (not pure noise)
STANDOUT_MIN_EVENTS = 8
STANDOUT_MIN_DURATION_SECONDS = 45 * 60
STANDOUT_DENSE_EVENT_COUNT = 20
STANDOUT_MIN_DISTINCT_ENTITIES = 2


def _episode_int(attr: str, default: int) -> int:
    return int(_l2_setting("episode", attr, default))


def _episode_float(attr: str, default: float) -> float:
    return float(_l2_setting("episode", attr, default))


@dataclass(frozen=True)
class StandoutGate:
    """Thresholds for the product-grade (经历 page) standout gate.

    Defaults are the module constants so the gate stays deterministic when
    called without an explicit gate (e.g. in unit tests); ``from_config`` builds
    a config-driven gate, falling back to these defaults when no config is bound.
    """

    min_events: int = STANDOUT_MIN_EVENTS
    min_duration_seconds: float = STANDOUT_MIN_DURATION_SECONDS
    dense_event_count: int = STANDOUT_DENSE_EVENT_COUNT
    min_distinct_entities: int = STANDOUT_MIN_DISTINCT_ENTITIES

    @classmethod
    def from_config(cls) -> "StandoutGate":
        return cls(
            min_events=_episode_int("standout_min_events", STANDOUT_MIN_EVENTS),
            min_duration_seconds=_episode_float(
                "standout_min_duration_seconds", STANDOUT_MIN_DURATION_SECONDS
            ),
            dense_event_count=_episode_int(
                "standout_dense_event_count", STANDOUT_DENSE_EVENT_COUNT
            ),
            min_distinct_entities=_episode_int(
                "standout_min_distinct_entities", STANDOUT_MIN_DISTINCT_ENTITIES
            ),
        )


@dataclass(frozen=True)
class _EpisodeBatchContext:
    event_ids: list[str]
    entity_ids: list[str]
    place_ids: list[str]
    topic_keys: list[str]
    min_ts: float
    max_ts: float
    episode_type_hint: str


@dataclass(frozen=True)
class _EpisodeConsolidationPolicy:
    standout_gate: StandoutGate
    min_events_to_promote: int
    min_age_to_promote: float
    merge_gap_factor: float
    min_entity_overlap_for_merge: float

    @classmethod
    def from_config(cls) -> "_EpisodeConsolidationPolicy":
        return cls(
            standout_gate=StandoutGate.from_config(),
            min_events_to_promote=_episode_int("min_events_to_promote", MIN_EVENTS_TO_PROMOTE),
            min_age_to_promote=_episode_float("min_age_to_promote_seconds", MIN_AGE_TO_PROMOTE),
            merge_gap_factor=_episode_float("merge_gap_factor", MERGE_GAP_FACTOR),
            min_entity_overlap_for_merge=_episode_float(
                "min_entity_overlap_for_merge", MIN_ENTITY_OVERLAP_FOR_MERGE
            ),
        )


def _passes_standout_gate(episode: dict[str, Any], gate: StandoutGate | None = None) -> bool:
    """Decide whether a promoted episode is product-grade for the 经历 page.

    Pure rule: enough events, enough time span, enough entity diversity. The
    *gate* defaults to the module constants so direct callers stay deterministic.
    """
    gate = gate or StandoutGate()
    event_count = int(episode.get("source_event_count") or 0)
    if event_count < gate.min_events:
        return False

    time_start = float(episode.get("time_start") or 0)
    time_end = float(episode.get("time_end") or 0)
    duration = time_end - time_start
    if duration < gate.min_duration_seconds and event_count < gate.dense_event_count:
        return False

    entities = episode.get("primary_entity_ids") or []
    if not isinstance(entities, list):
        entities = []
    distinct_entities = len({str(e).strip() for e in entities if str(e).strip()})
    if distinct_entities < gate.min_distinct_entities:
        return False

    return True


def _shares_theme(
    entity_ids_a: List[str],
    entity_ids_b: List[str],
    topic_keys_a: Optional[List[str]] = None,
    topic_keys_b: Optional[List[str]] = None,
) -> bool:
    """Check whether two event/episode contexts share a theme.

    Adapted from ``TimelineClusterBuilder._shares_theme``.
    """
    concrete_entities_a = _concrete_anchors(entity_ids_a)
    concrete_entities_b = _concrete_anchors(entity_ids_b)
    concrete_topics_a = _concrete_anchors(topic_keys_a or [])
    concrete_topics_b = _concrete_anchors(topic_keys_b or [])
    if concrete_entities_a and concrete_entities_b:
        if set(concrete_entities_a) & set(concrete_entities_b):
            return True
    if concrete_topics_a and concrete_topics_b:
        if set(concrete_topics_a) & set(concrete_topics_b):
            return True
    return False


def _entity_overlap_ratio(a: List[str], b: List[str]) -> float:
    if not a or not b:
        return 0.0
    sa, sb = set(_concrete_anchors(a)), set(_concrete_anchors(b))
    if not sa or not sb:
        return 0.0
    intersection = len(sa & sb)
    return intersection / min(len(sa), len(sb))


def _concrete_anchors(values: List[str]) -> list[str]:
    return sorted(
        {
            text
            for value in values
            if (text := str(value or "").strip()) and not is_generic_experience_anchor(text)
        }
    )


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

    jobs = await _filter_blocked_episode_jobs(store, jobs)
    if not jobs:
        return None
    batch = _build_episode_batch_context(jobs)
    candidate = await _find_extendable_candidate(store, batch)
    if candidate is not None:
        return await _extend_episode_candidate(store, candidate, batch)
    return await _create_episode_candidate(store, batch)


async def _filter_blocked_episode_jobs(
    store: L2CognitionStore,
    jobs: List[EpisodeCandidateJob],
) -> List[EpisodeCandidateJob]:
    """Drop only old evidence governed by durable episode/entity barriers."""
    event_ids = sorted({str(job.event_id) for job in jobs if str(job.event_id).strip()})
    if not event_ids:
        return []
    placeholders = ", ".join("?" for _ in event_ids)
    async with sqlite_connection_async(store.db_path) as db:
        await db.execute("BEGIN IMMEDIATE")
        try:
            for job in jobs:
                await promote_source_event_entity_projection_candidates(
                    db,
                    [str(job.event_id)],
                    entity_ids=(str(entity_id) for entity_id in job.entity_ids),
                )
            async with db.execute(
                f"""
                SELECT block_kind, target_id, event_id
                FROM memory_projection_blocks
                WHERE event_id IN ({placeholders})
                """,
                tuple(event_ids),
            ) as cursor:
                rows = await cursor.fetchall()
            await db.commit()
        except BaseException:
            await db.rollback()
            raise
    episode_blocked = {str(row[2]) for row in rows if str(row[0]) == "episode_formation"}
    entity_blocks: dict[str, set[str]] = {}
    for block_kind, target_id, event_id in rows:
        if str(block_kind) not in {
            "entity_projection",
            "entity_projection_candidate",
        }:
            continue
        entity_blocks.setdefault(str(event_id), set()).add(str(target_id))
    return [
        job
        for job in jobs
        if str(job.event_id) not in episode_blocked
        and not entity_blocks.get(str(job.event_id), set()).intersection(
            str(entity_id) for entity_id in job.entity_ids
        )
    ]


def _build_episode_batch_context(jobs: List[EpisodeCandidateJob]) -> _EpisodeBatchContext:
    """Aggregate episode formation signals from one micro-batch."""
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

    return _EpisodeBatchContext(
        event_ids=event_ids,
        entity_ids=sorted(set(all_entity_ids)),
        place_ids=sorted(set(all_place_ids)),
        topic_keys=sorted(set(all_topic_keys)),
        min_ts=min_ts,
        max_ts=max_ts,
        episode_type_hint=episode_type_hint,
    )


async def _find_extendable_candidate(
    store: L2CognitionStore,
    batch: _EpisodeBatchContext,
) -> dict[str, Any] | None:
    max_gap = EPISODE_MAX_GAP.get(
        batch.episode_type_hint,
        EPISODE_MAX_GAP["default"],
    )
    candidate = await store.find_recent_candidate_episode(
        episode_type=batch.episode_type_hint,
        max_gap=max_gap,
        before_time=batch.max_ts + 1,
        entity_ids=_concrete_anchors(batch.entity_ids) or None,
    )

    if candidate is None:
        return None
    ep_entities = candidate.get("primary_entity_ids") or []
    ep_topics = candidate.get("primary_topic_keys") or []
    if not _shares_theme(ep_entities, batch.entity_ids, ep_topics, batch.topic_keys):
        return None
    return candidate


async def _extend_episode_candidate(
    store: L2CognitionStore,
    candidate: dict[str, Any],
    batch: _EpisodeBatchContext,
) -> str:
    episode_id = candidate["episode_id"]
    ep_entities = candidate.get("primary_entity_ids") or []
    ep_places = candidate.get("primary_place_ids") or []
    ep_topics = candidate.get("primary_topic_keys") or []

    await store.add_episode_events(
        episode_id=episode_id,
        event_ids=batch.event_ids,
    )
    # Derive the count from membership (not arithmetic): re-adding an
    # already-present event is an INSERT OR IGNORE no-op, so summing
    # len(event_ids) would drift the stored count above true membership.
    new_count = await store.count_episode_events(episode_id=episode_id)

    await store.update_episode(
        episode_id=episode_id,
        time_start=min(candidate["time_start"], batch.min_ts),
        time_end=max(candidate["time_end"], batch.max_ts),
        primary_entity_ids=_merge_sorted(ep_entities, batch.entity_ids),
        primary_place_ids=_merge_sorted(ep_places, batch.place_ids),
        primary_topic_keys=_merge_sorted(ep_topics, batch.topic_keys),
        source_event_count=new_count,
    )
    logger.debug(
        "Episode candidate extended",
        episode_id=episode_id,
        added_events=len(batch.event_ids),
        new_count=new_count,
    )
    return episode_id


async def _create_episode_candidate(
    store: L2CognitionStore,
    batch: _EpisodeBatchContext,
) -> str:
    episode_id = str(uuid.uuid4())
    await store.create_episode(
        episode_id=episode_id,
        episode_type=batch.episode_type_hint,
        status="candidate",
        time_start=batch.min_ts,
        time_end=batch.max_ts,
        primary_entity_ids=batch.entity_ids,
        primary_place_ids=batch.place_ids,
        primary_topic_keys=batch.topic_keys,
        formation_method="time_gap_cluster",
        source_event_count=len(batch.event_ids),
    )
    await store.add_episode_events(
        episode_id=episode_id,
        event_ids=batch.event_ids,
    )
    logger.debug(
        "Episode candidate created",
        episode_id=episode_id,
        event_count=len(batch.event_ids),
        episode_type=batch.episode_type_hint,
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
    policy = _EpisodeConsolidationPolicy.from_config()

    await _promote_mature_candidates(store, stats, now, policy)
    await _merge_adjacent_active_episodes(store, stats, policy)
    await _invalidate_sparse_episodes(store, stats)

    logger.info(
        "Episode consolidation completed",
        promoted=stats.promoted,
        standouts=stats.standouts,
        merged=stats.merged,
        invalidated=stats.invalidated,
    )
    return stats


async def _promote_mature_candidates(
    store: L2CognitionStore,
    stats: EpisodeConsolidationStats,
    now: float,
    policy: _EpisodeConsolidationPolicy,
) -> None:
    candidates = await store.list_episodes(status="candidate", limit=500)
    for episode in candidates:
        if not _should_promote_candidate(episode, now, policy):
            continue
        await _promote_candidate(store, stats, episode, now, policy)


def _should_promote_candidate(
    episode: dict[str, Any],
    now: float,
    policy: _EpisodeConsolidationPolicy,
) -> bool:
    age = now - episode["created_at"]
    return (
        episode["source_event_count"] >= policy.min_events_to_promote
        and age >= policy.min_age_to_promote
    )


async def _promote_candidate(
    store: L2CognitionStore,
    stats: EpisodeConsolidationStats,
    episode: dict[str, Any],
    now: float,
    policy: _EpisodeConsolidationPolicy,
) -> None:
    standout = _passes_standout_gate(episode, policy.standout_gate)
    update_fields: dict[str, Any] = {"status": "active"}
    if standout:
        update_fields["magi_standout"] = True
    await store.update_episode(episode_id=episode["episode_id"], **update_fields)

    stats.promoted += 1
    stats.promoted_episode_ids.append(episode["episode_id"])
    if standout:
        stats.standouts += 1

    age = now - episode["created_at"]
    logger.debug(
        "Episode promoted",
        episode_id=episode["episode_id"],
        event_count=episode["source_event_count"],
        age_minutes=round(age / 60, 1),
        magi_standout=standout,
    )


async def _merge_adjacent_active_episodes(
    store: L2CognitionStore,
    stats: EpisodeConsolidationStats,
    policy: _EpisodeConsolidationPolicy,
) -> None:
    active_episodes = await store.list_episodes(status="active", limit=500)
    if len(active_episodes) < 2:
        return

    sorted_episodes = sorted(active_episodes, key=lambda e: e["time_start"])
    merged_ids: set[str] = set()
    for current, next_episode in _iter_adjacent_episode_pairs(sorted_episodes):
        if not _can_merge_episodes(current, next_episode, merged_ids, policy):
            continue
        await _merge_episode_pair(store, stats, current, next_episode, merged_ids)


def _iter_adjacent_episode_pairs(
    episodes: list[dict[str, Any]],
) -> list[tuple[dict[str, Any], dict[str, Any]]]:
    return [(episodes[i], episodes[i + 1]) for i in range(len(episodes) - 1)]


def _can_merge_episodes(
    current: dict[str, Any],
    next_episode: dict[str, Any],
    merged_ids: set[str],
    policy: _EpisodeConsolidationPolicy,
) -> bool:
    if current["episode_id"] in merged_ids or next_episode["episode_id"] in merged_ids:
        return False
    if current["episode_type"] != next_episode["episode_type"]:
        return False

    gap = next_episode["time_start"] - current["time_end"]
    max_gap = EPISODE_MAX_GAP.get(
        current["episode_type"],
        EPISODE_MAX_GAP["default"],
    )
    if gap > max_gap * policy.merge_gap_factor:
        return False

    overlap = _entity_overlap_ratio(
        current.get("primary_entity_ids") or [],
        next_episode.get("primary_entity_ids") or [],
    )
    return overlap >= policy.min_entity_overlap_for_merge


async def _merge_episode_pair(
    store: L2CognitionStore,
    stats: EpisodeConsolidationStats,
    current: dict[str, Any],
    next_episode: dict[str, Any],
    merged_ids: set[str],
) -> None:
    # Move next_episode's events to current first, then derive the count from
    # membership: duplicate events shared by both episodes are INSERT OR IGNORE
    # no-ops, so arithmetic would drift above true membership.
    next_events = await store.list_episode_events(episode_id=next_episode["episode_id"])
    if next_events:
        await store.add_episode_events(
            episode_id=current["episode_id"],
            event_ids=[event["event_id"] for event in next_events],
        )
    new_count = await store.count_episode_events(episode_id=current["episode_id"])

    await store.update_episode(
        episode_id=current["episode_id"],
        time_end=max(current["time_end"], next_episode["time_end"]),
        primary_entity_ids=_merge_sorted(
            current.get("primary_entity_ids") or [],
            next_episode.get("primary_entity_ids") or [],
        ),
        primary_place_ids=_merge_sorted(
            current.get("primary_place_ids") or [],
            next_episode.get("primary_place_ids") or [],
        ),
        primary_topic_keys=_merge_sorted(
            current.get("primary_topic_keys") or [],
            next_episode.get("primary_topic_keys") or [],
        ),
        source_event_count=new_count,
    )
    await store.update_episode(episode_id=next_episode["episode_id"], status="merged")
    merged_ids.add(next_episode["episode_id"])
    stats.merged += 1

    overlap = _entity_overlap_ratio(
        current.get("primary_entity_ids") or [],
        next_episode.get("primary_entity_ids") or [],
    )
    logger.debug(
        "Episodes merged",
        survivor=current["episode_id"],
        absorbed=next_episode["episode_id"],
        entity_overlap=round(overlap, 2),
    )


async def _invalidate_sparse_episodes(
    store: L2CognitionStore,
    stats: EpisodeConsolidationStats,
) -> None:
    active_after = await store.list_episodes(statuses=["candidate", "active"], limit=500)
    for episode in active_after:
        if episode["source_event_count"] >= 2:
            continue
        events = await store.list_episode_events(episode_id=episode["episode_id"], limit=5)
        if len(events) >= 2:
            continue
        await store.update_episode(episode_id=episode["episode_id"], status="invalidated")
        stats.invalidated += 1
        logger.debug(
            "Episode invalidated",
            episode_id=episode["episode_id"],
            remaining_events=len(events),
        )


def _merge_sorted(left: list[str], right: list[str]) -> list[str]:
    return sorted(set(left) | set(right))
