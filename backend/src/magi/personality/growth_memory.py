"""
Internal note.

Internal note.
Internal note.

evolution rules:
Internal note.
Internal note.
Internal note.
"""
import json
import time
import logging
from typing import Dict, Any, Optional, List
from pathlib import Path

from ..core.sqlite import sqlite_connection_async
from .growth_models import (
    InteractionType,
    Milestone,
    MilestoneType,
    PersonalityEvolution,
    RelationshipProfile,
)
from .growth_relationships import GrowthRelationshipMixin
from .growth_schema import ensure_growth_memory_schema

logger = logging.getLogger(__name__)


# Internal note.

class GrowthMemoryEngine(GrowthRelationshipMixin):
    """
    Internal note.

    Internal note.
    """

    def __init__(self, db_path: str = "~/.magi/data/memory/growth_memory.db", *, persona_id: str = ""):
        """
        Internal note.

        Args:
            db_path: databasefilepath
            persona_id: Stable persona identity for scoping data.
        """
        self.db_path = db_path
        self.persona_id = persona_id
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
            await ensure_growth_memory_schema(db)

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
                """INSERT intO milestones (id, Type, title, description, timestamp, metadata, persona_id)
                   valueS (?, ?, ?, ?, ?, ?, ?)""",
                (
                    milestone_id,
                    milestone_type.value,
                    title,
                    description,
                    milestone.timestamp,
                    json.dumps(metadata or {}),
                    self.persona_id,
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
                       FROM milestones WHERE type = ? AND persona_id = ?
                       order BY timestamp DESC LIMIT ?""",
                    (milestone_type.value, self.persona_id, limit)
                )
            else:
                cursor = await db.execute(
                    """SELECT id, Type, title, description, timestamp, metadata
                       FROM milestones WHERE persona_id = ?
                       order BY timestamp DESC LIMIT ?""",
                    (self.persona_id, limit)
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

    # ===== statisticsinfo =====

    async def get_growth_summary(self) -> Dict[str, Any]:
        """getgrowthsummary"""
        stats = await self._get_all_stats()

        milestones = await self.get_milestones(limit=1000)

        # getallrelationship
        async with sqlite_connection_async(self._expanded_db_path) as db:
            cursor = await db.execute("SELECT COUNT(*) FROM relationships WHERE persona_id = ?", (self.persona_id,))
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
