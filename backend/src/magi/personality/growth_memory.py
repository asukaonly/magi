"""Growth memory engine: milestones, relationships, and personality evolution events."""
import hashlib
import json
import time
import logging
from typing import Dict, Any, Optional, List
from pathlib import Path

from ..core.sqlite import sqlite_connection_async
from .growth_models import (
    InteractionType,  # noqa: F401 - compatibility re-export
    Milestone,
    MilestoneType,
    RelationshipProfile,
)
from .growth_relationships import GrowthRelationshipMixin

logger = logging.getLogger(__name__)



class GrowthMemoryEngine(GrowthRelationshipMixin):
    """Persona-scoped milestone log, relationship profiles, and evolution tracking."""

    def __init__(self, db_path: str = "~/.magi/data/memory/growth_memory.db", *, persona_id: str = ""):
        self.db_path = db_path
        self.persona_id = persona_id
        self._relationship_cache: Dict[str, RelationshipProfile] = {}
        self._milestone_cache: Optional[List[Milestone]] = None

    @property
    def _expanded_db_path(self) -> str:
        """Return ``db_path`` with ``~`` expanded to the user's home directory."""
        from pathlib import Path
        return str(Path(self.db_path).expanduser())

    async def init(self):
        """Create the database's parent directory; schema is applied lazily by stores."""
        Path(self._expanded_db_path).parent.mkdir(parents=True, exist_ok=True)

    async def clear_all(self) -> int:
        """Delete learned growth state for every persona and invalidate caches."""
        deleted = 0
        async with sqlite_connection_async(self._expanded_db_path) as db:
            for table_name in (
                "milestones",
                "relationships",
                "personality_evolution",
                "growth_statistics",
            ):
                cursor = await db.execute(f"DELETE FROM {table_name}")
                deleted += max(0, int(cursor.rowcount or 0))
            await db.commit()

        self._relationship_cache.clear()
        self._milestone_cache = None
        logger.info("Cleared all learned growth state")
        return deleted


    async def record_milestone(
        self,
        milestone_type: MilestoneType,
        title: str,
        description: str,
        metadata: Dict[str, Any] = None,
        *,
        idempotency_key: str | None = None,
    ) -> Milestone:
        """Persist a growth milestone (relationship/personality/special) and invalidate cache."""
        normalized_idempotency_key = str(idempotency_key or "").strip()
        if normalized_idempotency_key:
            digest = hashlib.sha256(normalized_idempotency_key.encode("utf-8")).hexdigest()
            milestone_id = f"milestone_once_{digest[:32]}"
        else:
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
            insert_clause = "INSERT OR IGNORE" if normalized_idempotency_key else "INSERT"
            cursor = await db.execute(
                f"""{insert_clause} INTO milestones
                   (id, Type, title, description, timestamp, metadata, persona_id)
                   VALUES (?, ?, ?, ?, ?, ?, ?)""",
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

            if normalized_idempotency_key and int(cursor.rowcount or 0) == 0:
                existing_cursor = await db.execute(
                    """
                    SELECT id, Type, title, description, timestamp, metadata
                    FROM milestones
                    WHERE id = ?
                    """,
                    (milestone_id,),
                )
                existing = await existing_cursor.fetchone()
                if existing is None:
                    raise RuntimeError("Idempotent milestone disappeared after insert")
                return Milestone(
                    id=str(existing[0]),
                    type=MilestoneType(str(existing[1])),
                    title=str(existing[2]),
                    description=str(existing[3]),
                    timestamp=float(existing[4]),
                    metadata=json.loads(existing[5]) if existing[5] else {},
                )

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
        """Return recent milestones, optionally filtered by ``milestone_type``."""
        if self._milestone_cache is not None and milestone_type is None:
            return self._milestone_cache[:limit]

        async with sqlite_connection_async(self._expanded_db_path) as db:
            if milestone_type:
                cursor = await db.execute(
                    """SELECT id, Type, title, description, timestamp, metadata
                       FROM milestones WHERE type = ? AND persona_id = ?
                       ORDER BY timestamp DESC LIMIT ?""",
                    (milestone_type.value, self.persona_id, limit)
                )
            else:
                cursor = await db.execute(
                    """SELECT id, Type, title, description, timestamp, metadata
                       FROM milestones WHERE persona_id = ?
                       ORDER BY timestamp DESC LIMIT ?""",
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
        """Record a personality-aspect change if confidence is high and the value actually changed."""
        if confidence < 0.8:
            return False

        if previous_value == new_value:
            return False

        async with sqlite_connection_async(self._expanded_db_path) as db:
            await db.execute(
                """INSERT INTO personality_evolution
                   (timestamp, aspect, previous_value, new_value, confidence, reason)
                   VALUES (?, ?, ?, ?, ?, ?)""",
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
        """Return aggregate growth statistics (milestone count, interactions, relationships)."""
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
        """Return all rows from ``growth_statistics`` as a dict, JSON-decoded where possible."""
        async with sqlite_connection_async(self._expanded_db_path) as db:
            cursor = await db.execute("SELECT key, value FROM growth_statistics")
            rows = await cursor.fetchall()

            stats = {}
            for key, value in rows:
                try:
                    stats[key] = json.loads(value)
                except (TypeError, ValueError):
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
                except (TypeError, ValueError):
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
                """INSERT OR REPLACE INTO growth_statistics (key, value, updated_at)
                   VALUES (?, ?, ?)""",
                (key, json.dumps(current), time.time())
            )
            await db.commit()
