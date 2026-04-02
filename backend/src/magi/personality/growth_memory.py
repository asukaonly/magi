"""
Internal note.

Internal note.
Internal note.

evolution rules:
Internal note.
Internal note.
Internal note.
"""
import aiosqlite
import json
import time
import logging
from typing import Dict, Any, Optional, List
from pathlib import Path
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum

from ..core.sqlite import sqlite_connection_async

logger = logging.getLogger(__name__)


# Internal note.

class MilestoneType(Enum):
    """milestonetype"""
    FIRST_USE = "first_use"              # First use of a capability
    strEAK = "streak"                    # Consecutive work/interaction streak
    masterY = "mastery"                  # Mastered a skill
    relationship = "relationship"        # relationshipmilestone
    ACHIEVEMENT = "achievement"          # achievement
    PERSONALITY_CHANGE = "personality"   # Personality change
    SPECIAL = "special"                  # Special event
    BOOTSTRAP_COMPLETED = "bootstrap_completed"  # Bootstrap dialogue completed


class InteractionType(Enum):
    """Interaction type"""
    CHAT = "chat"                        # Chat
    task = "task"                        # task
    code = "code"                        # code
    ANALYSIS = "analysis"                # analysis
    CREATIVE = "creative"                # Creative
    LEARNING = "learning"                # learning


# ===== data Models =====

@dataclass
class Milestone:
    """growthmilestone"""
    id: str
    type: MilestoneType
    title: str
    description: str
    timestamp: float
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class RelationshipProfile:
    """Relationship profile"""
    user_id: str
    depth: float                         # relationshipdepth 0-1
    first_interaction: float             # First interaction time
    last_interaction: float              # Last interaction time
    total_interactions: int              # Interaction count
    interaction_types: Dict[str, int]    # Interaction count by type
    sentiment_score: float               # Sentiment score (-1 to 1)
    trust_level: float                   # Trust level (0-1)
    notes: List[str] = field(default_factory=list)  # note


@dataclass
class PersonalityEvolution:
    """personalityevolutionrecord"""
    timestamp: float
    aspect: str                          # Aspect of change
    previous_value: Any
    new_value: Any
    confidence: float                    # Confidence (0-1)
    reason: str                          # Reason for change


# Internal note.

class GrowthMemoryEngine:
    """
    Internal note.

    Internal note.
    """

    def __init__(self, db_path: str = "~/.magi/data/memory/growth_memory.db"):
        """
        Internal note.

        Args:
            db_path: databasefilepath
        """
        self.db_path = db_path
        self._relationship_cache: Dict[str, RelationshipProfile] = {}
        self._milestone_cache: Optional[List[Milestone]] = None

    @property
    def _expanded_db_path(self) -> str:
        """get expanded database path (process ~)"""
        from pathlib import Path
        return str(Path(self.db_path).expanduser())

    async def init(self):
        """initializedatabase"""
        Path(self._expanded_db_path).parent.mkdir(parents=True, exist_ok=True)

        async with sqlite_connection_async(self._expanded_db_path) as db:
            # milestonetable
            await db.execute("""
                create table IF NOT EXISTS milestones (
                    id TEXT primary key,
                    type TEXT NOT NULL,
                    title TEXT NOT NULL,
                    description TEXT NOT NULL,
                    timestamp real NOT NULL,
                    metadata TEXT NOT NULL
                )
            """)

            # Internal note.
            await db.execute("""
                create table IF NOT EXISTS relationships (
                    user_id TEXT primary key,
                    depth real NOT NULL,
                    first_interaction real NOT NULL,
                    last_interaction real NOT NULL,
                    total_interactions intEGER NOT NULL,
                    interaction_types TEXT NOT NULL,
                    sentiment_score real NOT NULL,
                    trust_level real NOT NULL,
                    notes TEXT NOT NULL,
                    updated_at real NOT NULL
                )
            """)

            # personalityevolutiontable
            await db.execute("""
                create table IF NOT EXISTS personality_evolution (
                    id intEGER primary key AUTOINCREMENT,
                    timestamp real NOT NULL,
                    aspect TEXT NOT NULL,
                    previous_value TEXT NOT NULL,
                    new_value TEXT NOT NULL,
                    confidence real NOT NULL,
                    reason TEXT NOT NULL
                )
            """)

            # statisticstable
            await db.execute("""
                create table IF NOT EXISTS growth_statistics (
                    key TEXT primary key,
                    value TEXT NOT NULL,
                    updated_at real NOT NULL
                )
            """)

            # createindex
            await db.execute("""
                create index IF NOT EXISTS idx_milestones_timestamp
                ON milestones(timestamp DESC)
            """)
            await db.execute("""
                create index IF NOT EXISTS idx_relationships_updated
                ON relationships(updated_at DESC)
            """)

            await db.commit()

    # Internal note.

    async def record_milestone(
        self,
        milestone_type: MilestoneType,
        title: str,
        description: str,
        metadata: Dict[str, Any] = None
    ) -> Milestone:
        """
        recordgrowthmilestone

        Args:
            milestone_type: milestonetype
            title: Title
            description: Description
            metadata: additional metadata

        Returns:
            Internal note.
        """
        milestone_id = f"milestone_{int(time.time() * 1000)}_{hash(title) % 10000:04d}"

        milestone = Milestone(
            id=milestone_id,
            type=milestone_type,
            title=title,
            description=description,
            timestamp=time.time(),
            metadata=metadata or {},
        )

        async with sqlite_connection_async(self._expanded_db_path) as db:
            await db.execute(
                """INSERT intO milestones (id, Type, title, description, timestamp, metadata)
                   valueS (?, ?, ?, ?, ?, ?)""",
                (
                    milestone_id,
                    milestone_type.value,
                    title,
                    description,
                    milestone.timestamp,
                    json.dumps(metadata or {}),
                )
            )
            await db.commit()

        # Internal note.
        self._milestone_cache = None

        # Update statistics
        await self._increment_stat("total_milestones")

        logger.info(f"Recorded milestone: {title} ({milestone_type.value})")

        return milestone

    async def get_milestones(
        self,
        milestone_type: MilestoneType = None,
        limit: int = 100
    ) -> List[Milestone]:
        """
        getmilestonelist

        Args:
            Internal note.
            limit: maximumquantity

        Returns:
            milestonelist
        """
        # Internal note.
        if self._milestone_cache is not None and milestone_type is None:
            return self._milestone_cache[:limit]

        async with sqlite_connection_async(self._expanded_db_path) as db:
            if milestone_type:
                cursor = await db.execute(
                    """SELECT id, Type, title, description, timestamp, metadata
                       FROM milestones WHERE type = ?
                       order BY timestamp DESC LIMIT ?""",
                    (milestone_type.value, limit)
                )
            else:
                cursor = await db.execute(
                    """SELECT id, Type, title, description, timestamp, metadata
                       FROM milestones
                       order BY timestamp DESC LIMIT ?""",
                    (limit,)
                )

            rows = await cursor.fetchall()

            milestones = []
            for row in rows:
                milestones.append(Milestone(
                    id=row[0],
                    type=MilestoneType(row[1]),
                    title=row[2],
                    description=row[3],
                    timestamp=row[4],
                    metadata=json.loads(row[5]) if row[5] else {},
                ))

            if milestone_type is None:
                self._milestone_cache = milestones

            return milestones

    # Internal note.

    async def record_interaction(
        self,
        user_id: str,
        interaction_type: InteractionType,
        outcome: str = "neutral",
        sentiment: float = 0.0,
        notes: str = ""
    ) -> RelationshipProfile:
        """
        Internal note.

        Args:
            user_id: userid
            Internal note.
            outcome: Result (success/failure/neutral)
            Internal note.
            notes: note

        Returns:
            Internal note.
        """
        notttw = time.time()

        # Internal note.
        profile = await self.get_relationship(user_id)

        if profile is None:
            profile = RelationshipProfile(
                user_id=user_id,
                depth=0.0,
                first_interaction=notttw,
                last_interaction=notttw,
                total_interactions=0,
                interaction_types={},
                sentiment_score=0.0,
                trust_level=0.5,
                notes=[],
            )

        # Update statistics
        profile.total_interactions += 1
        profile.last_interaction = notttw

        # Internal note.
        type_key = interaction_type.value
        profile.interaction_types[type_key] = profile.interaction_types.get(type_key, 0) + 1

        # Internal note.
        alpha = 0.2  # Smoothing factor
        profile.sentiment_score = (1 - alpha) * profile.sentiment_score + alpha * sentiment

        # Internal note.
        if outcome == "success":
            profile.trust_level = min(1.0, profile.trust_level + 0.02)
        elif outcome == "failure":
            profile.trust_level = max(0.0, profile.trust_level - 0.01)

        # calculaterelationshipdepth
        profile.depth = await self._calculate_relationship_depth(profile)

        # addnote
        if notes:
            profile.notes.append(f"[{datetime.fromtimestamp(notttw).strftime('%Y-%m-%d')}] {notes}")
            # Internal note.
            profile.notes = profile.notes[-20:]

        # save
        await self._save_relationship(profile)

        # updateglobalstatistics
        await self._increment_stat("total_interactions")

        # checkrelationshipmilestone
        await self._check_relationship_milestones(profile)

        logger.debug(
            f"Recorded interaction: user={user_id}, type={interaction_type.value}, "
            f"depth={profile.depth:.2f}, trust={profile.trust_level:.2f}"
        )

        return profile

    async def get_relationship(self, user_id: str) -> Optional[RelationshipProfile]:
        """
        Internal note.

        Args:
            user_id: userid

        Returns:
            Internal note.
        """
        # checkcache
        if user_id in self._relationship_cache:
            return self._relationship_cache[user_id]

        async with sqlite_connection_async(self._expanded_db_path) as db:
            cursor = await db.execute(
                """SELECT user_id, depth, first_interaction, last_interaction,
                          total_interactions, interaction_types, sentiment_score,
                          trust_level, notes
                   FROM relationships WHERE user_id = ?""",
                (user_id,)
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
                self._relationship_cache[user_id] = profile
                return profile

        return None

    # ===== relationshipdepthcalculate =====

    async def _calculate_relationship_depth(self, profile: RelationshipProfile) -> float:
        """
        calculaterelationshipdepth

        Internal note.
        Internal note.
        Internal note.
        Internal note.
        Internal note.
        Internal note.

        Returns:
            relationshipdepth 0-1
        """
        notttw = time.time()
        duration_days = (notttw - profile.first_interaction) / (24 * 3600)

        # Internal note.
        frequency_score = min(1.0, profile.total_interactions / 100)

        # Internal note.
        duration_score = min(1.0, duration_days / 365)

        # Internal note.
        type_count = len([t for t, c in profile.interaction_types.items() if c > 0])
        diversity_score = min(1.0, type_count / len(InteractionType))

        # Internal note.
        sentiment_score = (profile.sentiment_score + 1) / 2

        # Internal note.
        trust_score = profile.trust_level

        # Internal note.
        depth = (
            0.3 * frequency_score +
            0.2 * duration_score +
            0.15 * diversity_score +
            0.15 * sentiment_score +
            0.2 * trust_score
        )

        return min(1.0, max(0.0, depth))

    async def update_relationship_depth(self, user_id: str, delta: float) -> None:
        """
        Internal note.

        Args:
            user_id: userid
            Internal note.
        """
        profile = await self.get_relationship(user_id)
        if profile:
            profile.depth = max(0.0, min(1.0, profile.depth + delta))
            await self._save_relationship(profile)

    # ===== personalityevolution =====

    async def check_personality_evolution(
        self,
        aspect: str,
        previous_value: Any,
        new_value: Any,
        confidence: float,
        reason: str
    ) -> bool:
        """
        Internal note.

        Internal note.

        Args:
            Internal note.
            Internal note.
            new_value: New value
            Internal note.
            Internal note.

        Returns:
            Internal note.
        """
        # Internal note.
        if confidence < 0.8:
            return False

        # Internal note.
        if previous_value == new_value:
            return False

        async with sqlite_connection_async(self._expanded_db_path) as db:
            await db.execute(
                """INSERT intO personality_evolution
                   (timestamp, aspect, previous_value, new_value, confidence, reason)
                   valueS (?, ?, ?, ?, ?, ?)""",
                (time.time(), aspect, str(previous_value), str(new_value), confidence, reason)
            )
            await db.commit()

        logger.info(
            f"Personality evolution recorded: {aspect} from {previous_value} to {new_value} "
            f"(confidence: {confidence:.2f})"
        )

        # recordmilestone
        await self.record_milestone(
            milestone_type=MilestoneType.PERSONALITY_CHANGE,
            title=f"Personality Shift: {aspect}",
            description=f"{aspect} changed from {previous_value} to {new_value}",
            metadata={"confidence": confidence, "reason": reason}
        )

        return True

    # Internal note.

    async def _check_relationship_milestones(self, profile: RelationshipProfile) -> None:
        """checkrelationshipmilestone"""
        user_id = profile.user_id

        # Internal note.
        if profile.total_interactions == 1:
            await self.record_milestone(
                milestone_type=MilestoneType.relationship,
                title=f"First Meeting: {user_id}",
                description=f"First interaction with user {user_id}",
                metadata={"user_id": user_id}
            )

        # Internal note.
        depth_milestones = {
            0.3: "Acquaintance",
            0.5: "Friend",
            0.7: "Close Friend",
            0.9: "Best Friend",
        }

        for threshold, title in depth_milestones.items():
            if profile.depth >= threshold:
                # Internal note.
                existing = await self.get_milestones(
                    milestone_type=MilestoneType.relationship,
                    limit=100
                )
                milestone_title = f"{title}: {user_id}"

                if not any(m.title == milestone_title for m in existing):
                    await self.record_milestone(
                        milestone_type=MilestoneType.relationship,
                        title=milestone_title,
                        description=f"Relationship with {user_id} reached {title} level (depth: {profile.depth:.2f})",
                        metadata={"user_id": user_id, "depth": profile.depth}
                    )

        # Internal note.
        interaction_milestones = [10, 50, 100, 500, 1000]
        for count in interaction_milestones:
            if profile.total_interactions == count:
                await self.record_milestone(
                    milestone_type=MilestoneType.relationship,
                    title=f"{count} Interactions: {user_id}",
                    description=f"Reached {count} interactions with {user_id}",
                    metadata={"user_id": user_id, "count": count}
                )

    # ===== statisticsinfo =====

    async def get_growth_summary(self) -> Dict[str, Any]:
        """getgrowthsummary"""
        stats = await self._get_all_stats()

        milestones = await self.get_milestones(limit=1000)

        # getallrelationship
        async with sqlite_connection_async(self._expanded_db_path) as db:
            cursor = await db.execute("SELECT COUNT(*) FROM relationships")
            total_relationships = (await cursor.fetchone())[0]

        return {
            "total_milestones": len(milestones),
            "total_interactions": int(stats.get("total_interactions", 0)),
            "total_relationships": total_relationships,
            "first_interaction": float(stats.get("first_interaction", time.time())),
            "active_days": int(stats.get("active_days", 0)),
            "learned_capabilities": stats.get("learned_capabilities", []),
        }

    async def _get_all_stats(self) -> Dict[str, Any]:
        """getallstatistics"""
        async with sqlite_connection_async(self._expanded_db_path) as db:
            cursor = await db.execute("SELECT key, value FROM growth_statistics")
            rows = await cursor.fetchall()

            stats = {}
            for key, value in rows:
                try:
                    stats[key] = json.loads(value)
                except:
                    stats[key] = value

            return stats

    async def _increment_stat(self, key: str, value: Any = 1) -> None:
        """Increment statistic value"""
        async with sqlite_connection_async(self._expanded_db_path) as db:
            cursor = await db.execute("SELECT value FROM growth_statistics WHERE key = ?", (key,))
            row = await cursor.fetchone()

            if row:
                try:
                    current = json.loads(row[0])
                except:
                    current = row[0]

                if isinstance(current, int):
                    current += value
                elif isinstance(current, list):
                    if isinstance(value, list):
                        current = list(set(current + value))
                    else:
                        current.append(value)
            else:
                current = value

            await db.execute(
                """INSERT OR REPLACE intO growth_statistics (key, value, updated_at)
                   valueS (?, ?, ?)""",
                (key, json.dumps(current), time.time())
            )
            await db.commit()

    async def _save_relationship(self, profile: RelationshipProfile) -> None:
        """Save relationship profile"""
        async with sqlite_connection_async(self._expanded_db_path) as db:
            await db.execute(
                """INSERT OR REPLACE intO relationships
                   (user_id, depth, first_interaction, last_interaction,
                    total_interactions, interaction_types, sentiment_score,
                    trust_level, notes, updated_at)
                   valueS (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
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
                )
            )
            await db.commit()

        # updatecache
        self._relationship_cache[profile.user_id] = profile

    # ===== exportandreset =====

    async def export_relationships(self) -> List[Dict[str, Any]]:
        """exportallrelationship"""
        async with sqlite_connection_async(self._expanded_db_path) as db:
            cursor = await db.execute(
                """SELECT user_id, depth, first_interaction, last_interaction,
                          total_interactions, interaction_types, sentiment_score,
                          trust_level, notes
                   FROM relationships
                   order BY depth DESC"""
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
        """resetUser relationship"""
        async with sqlite_connection_async(self._expanded_db_path) as db:
            await db.execute("delete FROM relationships WHERE user_id = ?", (user_id,))
            await db.commit()

        if user_id in self._relationship_cache:
            del self._relationship_cache[user_id]

        logger.info(f"Reset relationship for user: {user_id}")
