"""Seed persistence helpers for L2 experience discovery."""

from __future__ import annotations

from typing import Any, Sequence

from .seed_anchors import (
    _episode_concrete_entity_ids,
    _episode_concrete_place_ids,
    _episode_concrete_topic_keys,
    _episode_title,
    _seed_id,
)
from .seed_features import _candidate_episode_ids, _time_bounds
from .seed_models import _EpisodeSeedFeatures


async def _create_seed_if_missing(
    store: Any,
    *,
    seed_id: str,
    seed_type: str,
    status: str,
    title: str,
    description: str | None = None,
    anchor_entity_ids: list[str] | None = None,
    anchor_place_ids: list[str] | None = None,
    anchor_topic_keys: list[str] | None = None,
    time_start: float | None = None,
    time_end: float | None = None,
    confidence: float = 0.0,
    created_by: str = "system",
    source_ref_type: str | None = None,
    source_ref_id: str | None = None,
    evidence_episode_ids: list[str] | None = None,
) -> tuple[bool, str]:
    if await store.get_experience_seed(seed_id=seed_id):
        return False, seed_id
    await store.create_experience_seed(
        seed_id=seed_id,
        seed_type=seed_type,
        status=status,
        title=title,
        description=description,
        anchor_entity_ids=anchor_entity_ids or [],
        anchor_place_ids=anchor_place_ids or [],
        anchor_topic_keys=anchor_topic_keys or [],
        time_start=time_start,
        time_end=time_end,
        confidence=confidence,
        created_by=created_by,
        source_ref_type=source_ref_type,
        source_ref_id=source_ref_id,
    )
    if evidence_episode_ids:
        await store.add_experience_seed_evidence(
            seed_id=seed_id,
            evidence=[
                {
                    "ref_type": "episode",
                    "ref_id": episode_id,
                    "role": "trigger" if index == 0 else "support",
                    "confidence": confidence,
                }
                for index, episode_id in enumerate(evidence_episode_ids)
            ],
        )
    return True, seed_id


async def _create_repeated_seed_from_features(
    store: Any,
    *,
    seed_id: str,
    title: str,
    description: str,
    features: Sequence[_EpisodeSeedFeatures],
    anchor_entity_ids: list[str] | None = None,
    anchor_place_ids: list[str] | None = None,
    anchor_topic_keys: list[str] | None = None,
    confidence: float,
) -> tuple[bool, str]:
    start, end = _time_bounds(features)
    return await _create_seed_if_missing(
        store,
        seed_id=seed_id,
        seed_type="repeated_goal",
        status="candidate",
        title=title,
        description=description,
        anchor_entity_ids=anchor_entity_ids or [],
        anchor_place_ids=anchor_place_ids or [],
        anchor_topic_keys=anchor_topic_keys or [],
        time_start=start,
        time_end=end,
        confidence=confidence,
        source_ref_type="episode_group",
        source_ref_id=",".join(_candidate_episode_ids(features)),
        evidence_episode_ids=_candidate_episode_ids(features),
    )


async def discover_manual_experience_seed(
    store: Any,
    *,
    episode_id: str,
    title: str | None = None,
    created_by: str = "user",
) -> str:
    """Create an accepted seed from a user-selected episode."""
    episode = await store.get_episode(episode_id=episode_id)
    if episode is None or str(episode.get("status") or "") != "active":
        raise ValueError(f"Episode is not active for experience seed: {episode_id}")
    seed_id = _seed_id("manual", episode_id)
    created, _ = await _create_seed_if_missing(
        store,
        seed_id=seed_id,
        seed_type="manual",
        status="accepted",
        title=title or _episode_title(episode),
        description=str(episode.get("summary") or "") or None,
        anchor_entity_ids=_episode_concrete_entity_ids(episode),
        anchor_place_ids=_episode_concrete_place_ids(episode),
        anchor_topic_keys=_episode_concrete_topic_keys(episode),
        time_start=float(episode["time_start"]),
        time_end=float(episode["time_end"]),
        confidence=0.9,
        created_by=created_by,
        source_ref_type="episode",
        source_ref_id=episode_id,
        evidence_episode_ids=[episode_id],
    )
    if not created:
        await store.add_experience_seed_evidence(
            seed_id=seed_id,
            evidence=[{"ref_type": "episode", "ref_id": episode_id, "role": "trigger"}],
        )
    return seed_id
