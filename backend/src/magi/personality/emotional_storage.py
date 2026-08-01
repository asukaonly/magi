"""SQLite persistence for the personality emotional state engine."""

from __future__ import annotations

import json
import logging
import time
from dataclasses import asdict
from pathlib import Path
from typing import List, Optional

from ..core.sqlite import sqlite_connection_async
from .emotional_contracts import EmotionalEvent
from .models import EmotionalState

logger = logging.getLogger(__name__)


class EmotionalStateStorageMixin:
    """Persists current emotional state and event history."""

    db_path: str
    persona_id: str
    _current_state: Optional[EmotionalState]

    @property
    def _expanded_db_path(self) -> str:
        """Get expanded database path."""
        return str(Path(self.db_path).expanduser())

    async def init(self) -> None:
        """Initialize the emotional state database (alembic-managed schema)."""
        Path(self._expanded_db_path).parent.mkdir(parents=True, exist_ok=True)
        await self._load_current_state()

    async def get_current_state(self) -> EmotionalState:
        """Get current emotional state."""
        if self._current_state is None:
            await self._load_current_state()
        assert self._current_state is not None
        return self._current_state

    async def _load_current_state(self) -> None:
        """Load current state from database."""
        state_key = f"current:{self.persona_id}" if self.persona_id else "current"
        async with sqlite_connection_async(self._expanded_db_path) as db:
            cursor = await db.execute(
                "SELECT value FROM emotional_state WHERE key = ?",
                (state_key,)
            )
            row = await cursor.fetchone()

            if row:
                self._current_state = EmotionalState(**json.loads(row[0]))
            else:
                self._current_state = EmotionalState()
                await self._save_current_state()

    async def _save_current_state(self) -> None:
        """Save current emotional state."""
        assert self._current_state is not None
        state_key = f"current:{self.persona_id}" if self.persona_id else "current"
        async with sqlite_connection_async(self._expanded_db_path) as db:
            await db.execute(
                """INSERT OR REPLACE INTO emotional_state (key, value, updated_at)
                   VALUES (?, ?, ?)""",
                (state_key, json.dumps(asdict(self._current_state)), time.time())
            )
            await db.commit()

    async def _record_event(
        self,
        event_type: str,
        previous_mood: str,
        new_mood: str,
        mood_delta: float,
        energy_delta: float,
        stress_delta: float,
        cause: str
    ) -> None:
        """Record emotional event."""
        async with sqlite_connection_async(self._expanded_db_path) as db:
            await db.execute(
                """INSERT INTO emotional_events
                   (timestamp, event_type, previous_mood, new_mood,
                    mood_delta, energy_delta, stress_delta, cause, persona_id)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (time.time(), event_type, previous_mood, new_mood,
                 mood_delta, energy_delta, stress_delta, cause, self.persona_id)
            )
            await db.commit()

    async def get_recent_events(self, limit: int = 50) -> List[EmotionalEvent]:
        """Get recent emotional events."""
        async with sqlite_connection_async(self._expanded_db_path) as db:
            cursor = await db.execute(
                """SELECT timestamp, event_type, previous_mood, new_mood,
                          mood_delta, energy_delta, stress_delta, cause
                   FROM emotional_events
                   WHERE persona_id = ?
                   ORDER BY timestamp DESC
                   LIMIT ?""",
                (self.persona_id, limit)
            )
            rows = await cursor.fetchall()

            events = []
            for row in rows:
                events.append(EmotionalEvent(
                    timestamp=row[0],
                    event_type=row[1],
                    previous_mood=row[2],
                    new_mood=row[3],
                    mood_delta=row[4],
                    energy_delta=row[5],
                    stress_delta=row[6],
                    cause=row[7],
                ))

            return events

    async def reset(self) -> None:
        """Reset emotional state to initial values."""
        self._current_state = EmotionalState()
        await self._save_current_state()

        async with sqlite_connection_async(self._expanded_db_path) as db:
            await db.execute("DELETE FROM emotional_events WHERE persona_id = ?", (self.persona_id,))
            await db.commit()

        logger.info("Emotional state reset to initial values")

    async def clear_all(self) -> int:
        """Delete every learned emotional state and reset the active cache."""
        deleted = 0
        async with sqlite_connection_async(self._expanded_db_path) as db:
            for table_name in ("emotional_events", "emotional_state"):
                cursor = await db.execute(f"DELETE FROM {table_name}")
                deleted += max(0, int(cursor.rowcount or 0))
            await db.commit()

        self._current_state = EmotionalState()
        event_history = getattr(self, "_event_history", None)
        if isinstance(event_history, list):
            event_history.clear()
        logger.info("Cleared all learned emotional state")
        return deleted


__all__ = ["EmotionalStateStorageMixin"]
