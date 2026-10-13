"""Atomic, persona-scoped effects of accepted conversation outcomes."""

from __future__ import annotations

import hashlib
import json
import time
from datetime import datetime
from typing import Mapping

import aiosqlite

from ..core.sqlite import sqlite_connection_async
from .growth_models import InteractionType, MilestoneType, RelationshipProfile


def relationship_depth(profile: RelationshipProfile, now: float) -> float:
    """Calculate relationship depth without reading or modifying storage."""
    duration_days = (now - profile.first_interaction) / 86400
    value = (
        0.3 * min(1.0, profile.total_interactions / 100)
        + 0.2 * min(1.0, duration_days / 365)
        + 0.15 * len([count for count in profile.interaction_types.values() if count > 0]) / len(InteractionType)
        + 0.15 * (profile.sentiment_score + 1) / 2
        + 0.2 * profile.trust_level
    )
    return min(1.0, max(0.0, value))


async def _read_relationship(db: aiosqlite.Connection, persona_id: str, user_id: str) -> RelationshipProfile | None:
    async with db.execute(
        "SELECT user_id, depth, first_interaction, last_interaction, total_interactions, "
        "interaction_types, sentiment_score, trust_level, notes "
        "FROM relationships WHERE persona_id = ? AND user_id = ?",
        (persona_id, user_id),
    ) as cursor:
        row = await cursor.fetchone()
    if row is None:
        return None
    return RelationshipProfile(
        user_id=str(row[0]), depth=float(row[1]), first_interaction=float(row[2]),
        last_interaction=float(row[3]), total_interactions=int(row[4]),
        interaction_types=json.loads(row[5]), sentiment_score=float(row[6]),
        trust_level=float(row[7]), notes=json.loads(row[8]),
    )


async def _save_relationship(db: aiosqlite.Connection, persona_id: str, profile: RelationshipProfile, now: float) -> None:
    await db.execute(
        """INSERT INTO relationships (
            user_id, depth, first_interaction, last_interaction, total_interactions,
            interaction_types, sentiment_score, trust_level, notes, updated_at, persona_id
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(persona_id, user_id) DO UPDATE SET
            depth=excluded.depth, first_interaction=excluded.first_interaction,
            last_interaction=excluded.last_interaction, total_interactions=excluded.total_interactions,
            interaction_types=excluded.interaction_types, sentiment_score=excluded.sentiment_score,
            trust_level=excluded.trust_level, notes=excluded.notes, updated_at=excluded.updated_at""",
        (profile.user_id, profile.depth, profile.first_interaction, profile.last_interaction,
         profile.total_interactions, json.dumps(profile.interaction_types), profile.sentiment_score,
         profile.trust_level, json.dumps(profile.notes), now, persona_id),
    )


async def _milestone(db: aiosqlite.Connection, *, persona_id: str, kind: MilestoneType,
                     title: str, description: str, metadata: dict, now: float) -> None:
    identity = json.dumps([persona_id, kind.value, title], ensure_ascii=False)
    milestone_id = "milestone_once_" + hashlib.sha256(identity.encode()).hexdigest()[:32]
    cursor = await db.execute(
        """INSERT INTO milestones (id, type, title, description, timestamp, metadata, persona_id)
        SELECT ?, ?, ?, ?, ?, ?, ? WHERE NOT EXISTS (
            SELECT 1 FROM milestones WHERE persona_id = ? AND type = ? AND title = ?
        ) ON CONFLICT(id) DO NOTHING""",
        (milestone_id, kind.value, title, description, now, json.dumps(metadata), persona_id,
         persona_id, kind.value, title),
    )
    if cursor.rowcount == 1:
        await _increment_counter(db, "total_milestones", now)


async def _increment_counter(db: aiosqlite.Connection, key: str, now: float) -> None:
    await db.execute(
        """INSERT INTO growth_statistics (key, value, updated_at) VALUES (?, '1', ?)
        ON CONFLICT(key) DO UPDATE SET value = CAST(CAST(value AS INTEGER) + 1 AS TEXT),
            updated_at = excluded.updated_at""", (key, now),
    )


class GrowthOutcomePersistenceMixin:
    """Apply one accepted outcome atomically within the growth database."""

    persona_id: str
    _expanded_db_path: str
    _relationship_cache: dict[str, RelationshipProfile]
    _milestone_cache: list | None

    async def apply_turn_outcome(
        self, *, outcome_id: str, user_id: str, outcome: str,
        sentiment: float, notes: str, milestones: Mapping[str, str],
    ) -> bool:
        """Commit relationship, statistics, milestones and receipt together."""
        if not outcome_id.strip() or not user_id.strip():
            raise ValueError("Growth outcome and user identities are required")
        now = time.time()
        async with sqlite_connection_async(self._expanded_db_path) as db:
            await db.execute("BEGIN IMMEDIATE")
            if await self._has_outcome_receipt(db, outcome_id, "interaction"):
                self._relationship_cache.pop(user_id, None)
                self._milestone_cache = None
                return False
            profile = await _read_relationship(db, self.persona_id, user_id)
            if profile is None:
                profile = RelationshipProfile(user_id, 0, now, now, 0, {}, 0, 0.5, [])
            profile.total_interactions += 1
            profile.last_interaction = now
            profile.interaction_types["chat"] = profile.interaction_types.get("chat", 0) + 1
            profile.sentiment_score = 0.8 * profile.sentiment_score + 0.2 * sentiment
            if outcome == "success":
                profile.trust_level = min(1.0, profile.trust_level + 0.02)
            elif outcome == "failure":
                profile.trust_level = max(0.0, profile.trust_level - 0.01)
            profile.depth = relationship_depth(profile, now)
            if notes:
                profile.notes = (profile.notes + [f"[{datetime.fromtimestamp(now):%Y-%m-%d}] {notes}"])[-20:]
            await _save_relationship(db, self.persona_id, profile, now)
            await _increment_counter(db, "total_interactions", now)
            await self._record_relationship_milestones(db, profile, now)
            for key, description in milestones.items():
                await _milestone(db, persona_id=self.persona_id, kind=MilestoneType.SPECIAL,
                                 title=key, description=f"Persona milestone: {description}", metadata={}, now=now)
            await self._record_outcome_receipt(db, outcome_id, "interaction", user_id, now)
            await db.commit()
        self._relationship_cache.pop(user_id, None)
        self._milestone_cache = None
        return True

    async def apply_relationship_signal(
        self, *, outcome_id: str, effect_kind: str, user_id: str,
        trust_delta: float = 0, milestone_key: str = "", description: str = "",
    ) -> bool:
        """Commit one grounded observer signal and its receipt together."""
        if not outcome_id.strip() or not effect_kind.strip() or not user_id.strip():
            raise ValueError("Relationship signal identities are required")
        effect = f"observer:{effect_kind}"
        now = time.time()
        async with sqlite_connection_async(self._expanded_db_path) as db:
            await db.execute("BEGIN IMMEDIATE")
            if await self._has_outcome_receipt(db, outcome_id, effect):
                self._relationship_cache.pop(user_id, None)
                self._milestone_cache = None
                return False
            if trust_delta:
                profile = await _read_relationship(db, self.persona_id, user_id)
                if profile is not None:
                    profile.trust_level = max(0.0, min(1.0, profile.trust_level + trust_delta))
                    profile.depth = relationship_depth(profile, now)
                    await _save_relationship(db, self.persona_id, profile, now)
            if milestone_key:
                await _milestone(db, persona_id=self.persona_id, kind=MilestoneType.SPECIAL,
                                 title=milestone_key, description=f"Persona milestone: {description}", metadata={}, now=now)
            await self._record_outcome_receipt(db, outcome_id, effect, user_id, now)
            await db.commit()
        self._relationship_cache.pop(user_id, None)
        self._milestone_cache = None
        return True

    async def _has_outcome_receipt(self, db: aiosqlite.Connection, outcome_id: str, effect: str) -> bool:
        async with db.execute(
            "SELECT 1 FROM persona_outcome_receipts WHERE persona_id=? AND outcome_id=? AND effect_kind=?",
            (self.persona_id, outcome_id, effect),
        ) as cursor:
            return await cursor.fetchone() is not None

    async def _record_outcome_receipt(self, db: aiosqlite.Connection, outcome_id: str,
                                      effect: str, user_id: str, now: float) -> None:
        await db.execute("INSERT INTO persona_outcome_receipts VALUES (?, ?, ?, ?, ?)",
                         (self.persona_id, outcome_id, effect, user_id, now))

    async def _record_relationship_milestones(self, db: aiosqlite.Connection,
                                            profile: RelationshipProfile, now: float) -> None:
        user_id = profile.user_id
        entries: list[tuple[str, str, dict]] = []
        if profile.total_interactions == 1:
            entries.append((f"First Meeting: {user_id}", f"First interaction with user {user_id}", {"user_id": user_id}))
        for threshold, title in ((0.3, "Acquaintance"), (0.5, "Friend"), (0.7, "Close Friend"), (0.9, "Best Friend")):
            if profile.depth >= threshold:
                entries.append((f"{title}: {user_id}", f"Relationship with {user_id} reached {title} level (depth: {profile.depth:.2f})",
                                {"user_id": user_id, "depth": profile.depth}))
        if profile.total_interactions in {10, 50, 100, 500, 1000}:
            count = profile.total_interactions
            entries.append((f"{count} Interactions: {user_id}", f"Reached {count} interactions with {user_id}",
                            {"user_id": user_id, "count": count}))
        for title, description, metadata in entries:
            await _milestone(db, persona_id=self.persona_id, kind=MilestoneType.RELATIONSHIP,
                             title=title, description=description, metadata=metadata, now=now)
