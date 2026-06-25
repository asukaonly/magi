"""Relationship profile operations for growth memory."""

from __future__ import annotations

import json
import logging
import time
from datetime import datetime
from typing import Any, Dict, List, Optional, Protocol

from ..core.sqlite import sqlite_connection_async
from .growth_models import InteractionType, MilestoneType, RelationshipProfile

logger = logging.getLogger(__name__)


class _GrowthRelationshipHost(Protocol):
    persona_id: str
    _relationship_cache: Dict[str, RelationshipProfile]

    @property
    def _expanded_db_path(self) -> str: ...

    async def record_milestone(
        self,
        milestone_type: MilestoneType,
        title: str,
        description: str,
        metadata: Dict[str, Any] | None = None,
    ) -> Any: ...

    async def get_milestones(
        self,
        milestone_type: MilestoneType | None = None,
        limit: int = 100,
    ) -> list[Any]: ...

    async def _increment_stat(self, key: str, value: Any = 1) -> None: ...


class GrowthRelationshipMixin:
    """Relationship tracking, milestones, export, and reset operations."""

    async def record_interaction(
        self,
        user_id: str,
        interaction_type: InteractionType,
        outcome: str = "neutral",
        sentiment: float = 0.0,
        notes: str = ""
    ) -> RelationshipProfile:
        host = self._relationship_host
        now_ts = time.time()

        profile = await self.get_relationship(user_id)

        if profile is None:
            profile = RelationshipProfile(
                user_id=user_id,
                depth=0.0,
                first_interaction=now_ts,
                last_interaction=now_ts,
                total_interactions=0,
                interaction_types={},
                sentiment_score=0.0,
                trust_level=0.5,
                notes=[],
            )

        profile.total_interactions += 1
        profile.last_interaction = now_ts

        type_key = interaction_type.value
        profile.interaction_types[type_key] = profile.interaction_types.get(type_key, 0) + 1

        alpha = 0.2
        profile.sentiment_score = (1 - alpha) * profile.sentiment_score + alpha * sentiment

        if outcome == "success":
            profile.trust_level = min(1.0, profile.trust_level + 0.02)
        elif outcome == "failure":
            profile.trust_level = max(0.0, profile.trust_level - 0.01)

        profile.depth = await self._calculate_relationship_depth(profile)

        if notes:
            profile.notes.append(f"[{datetime.fromtimestamp(now_ts).strftime('%Y-%m-%d')}] {notes}")
            profile.notes = profile.notes[-20:]

        await self._save_relationship(profile)
        await host._increment_stat("total_interactions")
        await self._check_relationship_milestones(profile)

        logger.debug(
            f"Recorded interaction: user={user_id}, type={interaction_type.value}, "
            f"depth={profile.depth:.2f}, trust={profile.trust_level:.2f}"
        )

        return profile

    async def get_relationship(self, user_id: str) -> Optional[RelationshipProfile]:
        host = self._relationship_host
        if user_id in host._relationship_cache:
            return host._relationship_cache[user_id]

        async with sqlite_connection_async(host._expanded_db_path) as db:
            cursor = await db.execute(
                """SELECT user_id, depth, first_interaction, last_interaction,
                          total_interactions, interaction_types, sentiment_score,
                          trust_level, notes
                   FROM relationships WHERE user_id = ? AND persona_id = ?""",
                (user_id, host.persona_id)
            )
            row = await cursor.fetchone()

            if row:
                profile = RelationshipProfile(
                    user_id=row[0],
                    depth=row[1],
                    first_interaction=row[2],
                    last_interaction=row[3],
                    total_interactions=row[4],
                    interaction_types=json.loads(row[5]),
                    sentiment_score=row[6],
                    trust_level=row[7],
                    notes=json.loads(row[8]),
                )
                host._relationship_cache[user_id] = profile
                return profile

        return None

    async def _calculate_relationship_depth(self, profile: RelationshipProfile) -> float:
        now_ts = time.time()
        duration_days = (now_ts - profile.first_interaction) / (24 * 3600)
        frequency_score = min(1.0, profile.total_interactions / 100)
        duration_score = min(1.0, duration_days / 365)
        type_count = len([t for t, c in profile.interaction_types.items() if c > 0])
        diversity_score = min(1.0, type_count / len(InteractionType))
        sentiment_score = (profile.sentiment_score + 1) / 2
        trust_score = profile.trust_level

        depth = (
            0.3 * frequency_score +
            0.2 * duration_score +
            0.15 * diversity_score +
            0.15 * sentiment_score +
            0.2 * trust_score
        )

        return min(1.0, max(0.0, depth))

    async def update_relationship_depth(self, user_id: str, delta: float) -> None:
        profile = await self.get_relationship(user_id)
        if profile:
            profile.depth = max(0.0, min(1.0, profile.depth + delta))
            await self._save_relationship(profile)

    async def update_relationship_trust(self, user_id: str, delta: float) -> None:
        profile = await self.get_relationship(user_id)
        if profile:
            profile.trust_level = max(0.0, min(1.0, profile.trust_level + delta))
            profile.depth = await self._calculate_relationship_depth(profile)
            await self._save_relationship(profile)

    async def _check_relationship_milestones(self, profile: RelationshipProfile) -> None:
        host = self._relationship_host
        user_id = profile.user_id

        if profile.total_interactions == 1:
            await host.record_milestone(
                milestone_type=MilestoneType.RELATIONSHIP,
                title=f"First Meeting: {user_id}",
                description=f"First interaction with user {user_id}",
                metadata={"user_id": user_id}
            )

        depth_milestones = {
            0.3: "Acquaintance",
            0.5: "Friend",
            0.7: "Close Friend",
            0.9: "Best Friend",
        }

        for threshold, title in depth_milestones.items():
            if profile.depth >= threshold:
                existing = await host.get_milestones(
                    milestone_type=MilestoneType.RELATIONSHIP,
                    limit=100
                )
                milestone_title = f"{title}: {user_id}"

                if not any(m.title == milestone_title for m in existing):
                    await host.record_milestone(
                        milestone_type=MilestoneType.RELATIONSHIP,
                        title=milestone_title,
                        description=f"Relationship with {user_id} reached {title} level (depth: {profile.depth:.2f})",
                        metadata={"user_id": user_id, "depth": profile.depth}
                    )

        interaction_milestones = [10, 50, 100, 500, 1000]
        for count in interaction_milestones:
            if profile.total_interactions == count:
                await host.record_milestone(
                    milestone_type=MilestoneType.RELATIONSHIP,
                    title=f"{count} Interactions: {user_id}",
                    description=f"Reached {count} interactions with {user_id}",
                    metadata={"user_id": user_id, "count": count}
                )

    async def _save_relationship(self, profile: RelationshipProfile) -> None:
        host = self._relationship_host
        async with sqlite_connection_async(host._expanded_db_path) as db:
            await db.execute(
                """INSERT OR REPLACE INTO relationships
                   (user_id, depth, first_interaction, last_interaction,
                    total_interactions, interaction_types, sentiment_score,
                    trust_level, notes, updated_at, persona_id)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    profile.user_id,
                    profile.depth,
                    profile.first_interaction,
                    profile.last_interaction,
                    profile.total_interactions,
                    json.dumps(profile.interaction_types),
                    profile.sentiment_score,
                    profile.trust_level,
                    json.dumps(profile.notes),
                    time.time(),
                    host.persona_id,
                )
            )
            await db.commit()

        host._relationship_cache[profile.user_id] = profile

    async def export_relationships(self) -> List[Dict[str, Any]]:
        host = self._relationship_host
        async with sqlite_connection_async(host._expanded_db_path) as db:
            cursor = await db.execute(
                """SELECT user_id, depth, first_interaction, last_interaction,
                          total_interactions, interaction_types, sentiment_score,
                          trust_level, notes
                   FROM relationships
                   WHERE persona_id = ?
                   ORDER BY depth DESC""",
                (host.persona_id,)
            )
            rows = await cursor.fetchall()

            relationships = []
            for row in rows:
                relationships.append({
                    "user_id": row[0],
                    "depth": row[1],
                    "first_interaction": row[2],
                    "last_interaction": row[3],
                    "total_interactions": row[4],
                    "interaction_types": json.loads(row[5]),
                    "sentiment_score": row[6],
                    "trust_level": row[7],
                    "notes": json.loads(row[8]),
                })

            return relationships

    async def reset_user(self, user_id: str) -> None:
        host = self._relationship_host
        async with sqlite_connection_async(host._expanded_db_path) as db:
            await db.execute("DELETE FROM relationships WHERE user_id = ? AND persona_id = ?", (user_id, host.persona_id))
            await db.commit()

        if user_id in host._relationship_cache:
            del host._relationship_cache[user_id]

        logger.info(f"Reset relationship for user: {user_id}")

    @property
    def _relationship_host(self) -> _GrowthRelationshipHost:
        return self  # type: ignore[return-value]


__all__ = ["GrowthRelationshipMixin"]
