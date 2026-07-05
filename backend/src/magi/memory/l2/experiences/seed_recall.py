"""Recall candidate evidence around an experience seed."""

from __future__ import annotations

from typing import Any


def _ordered_unique(values: list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        text = str(value or "").strip()
        if text and text not in seen:
            seen.add(text)
            result.append(text)
    return result


def _round_robin_event_ids(event_groups: list[list[str]], *, limit: int) -> list[str]:
    if limit <= 0:
        return []

    selected: list[str] = []
    seen: set[str] = set()
    offset = 0
    while len(selected) < limit:
        added_at_offset = False
        for event_ids in event_groups:
            if offset >= len(event_ids):
                continue
            added_at_offset = True
            event_id = str(event_ids[offset] or "").strip()
            if not event_id or event_id in seen:
                continue
            seen.add(event_id)
            selected.append(event_id)
            if len(selected) >= limit:
                return selected
        if not added_at_offset:
            break
        offset += 1
    return selected


async def _seed_episode_ids(store: Any, *, seed_id: str) -> tuple[list[str], list[str]]:
    evidence = await store.list_experience_seed_evidence(seed_id=seed_id)
    trigger_episode_ids = [
        str(item["ref_id"])
        for item in evidence
        if item["ref_type"] == "episode" and item["role"] == "trigger"
    ]
    evidence_episode_ids = [
        str(item["ref_id"]) for item in evidence if item["ref_type"] == "episode"
    ]
    return _ordered_unique(trigger_episode_ids), _ordered_unique(evidence_episode_ids)


async def _candidate_episodes(
    store: Any,
    *,
    seed: dict[str, Any],
    evidence_episode_ids: list[str],
    window_seconds: float,
) -> list[dict[str, Any]]:
    episodes_by_id: dict[str, dict[str, Any]] = {}
    for episode_id in evidence_episode_ids:
        episode = await store.get_episode(episode_id=episode_id)
        if episode is not None:
            episodes_by_id[str(episode["episode_id"])] = episode

    time_start = seed.get("time_start")
    time_end = seed.get("time_end")
    if time_start is None and episodes_by_id:
        time_start = min(float(episode["time_start"]) for episode in episodes_by_id.values())
    if time_end is None and episodes_by_id:
        time_end = max(float(episode["time_end"]) for episode in episodes_by_id.values())

    if time_start is not None and time_end is not None:
        nearby = await store.list_episodes(
            status="active",
            time_start=float(time_start) - window_seconds,
            time_end=float(time_end) + window_seconds,
            limit=500,
        )
        for episode in nearby:
            episodes_by_id[str(episode["episode_id"])] = episode

    return sorted(episodes_by_id.values(), key=lambda item: float(item["time_start"]))


async def _candidate_event_ids(
    store: Any,
    *,
    episodes: list[dict[str, Any]],
    raw_event_limit: int,
) -> list[str]:
    event_groups: list[list[str]] = []
    for episode in episodes:
        rows = await store.list_episode_events(
            episode_id=str(episode["episode_id"]),
            limit=max(0, raw_event_limit),
        )
        event_groups.append(_ordered_unique([str(row["event_id"]) for row in rows]))
    return _round_robin_event_ids(event_groups, limit=raw_event_limit)


async def recall_candidate_evidence_for_seed(
    store: Any,
    *,
    seed_id: str,
    window_seconds: float = 4 * 60 * 60,
    raw_event_limit: int = 80,
) -> dict[str, Any]:
    """Build a compact candidate evidence pack for a seed."""
    seed = await store.get_experience_seed(seed_id=seed_id)
    if seed is None:
        raise ValueError(f"Experience seed not found: {seed_id}")
    evidence = await store.list_experience_seed_evidence(seed_id=seed_id)
    trigger_episode_ids, evidence_episode_ids = await _seed_episode_ids(store, seed_id=seed_id)
    episodes = await _candidate_episodes(
        store,
        seed=seed,
        evidence_episode_ids=evidence_episode_ids,
        window_seconds=window_seconds,
    )
    return {
        "seed": seed,
        "seed_evidence": evidence,
        "trigger_episode_ids": trigger_episode_ids,
        "candidate_episodes": episodes,
        "candidate_event_ids": await _candidate_event_ids(
            store,
            episodes=episodes,
            raw_event_limit=raw_event_limit,
        ),
    }


__all__ = ["recall_candidate_evidence_for_seed"]
