"""Adaptive profile update scheduler with exponential backoff strategy."""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Any, Dict


@dataclass
class AdaptiveProfileUpdater:
    """Controls when a user profile should be refreshed."""

    # After the first 100 interactions, update frequency follows this ladder.
    backoff_schedule: tuple[int, ...] = (1, 5, 10, 50)
    schedule_index: int = 0
    interactions_since_update: int = 0
    last_update_at: float = 0.0

    def should_update(self, total_interactions: int, significant_change: bool = False) -> bool:
        """Returns True when profile update should be triggered."""
        if significant_change:
            self.reset()
            return True

        if total_interactions < 100:
            return True

        if self.schedule_index < len(self.backoff_schedule):
            threshold = self.backoff_schedule[self.schedule_index]
            return self.interactions_since_update >= threshold

        # Final stage: weekly updates.
        if self.last_update_at <= 0:
            return True
        return (time.time() - self.last_update_at) >= 7 * 86400

    def record_interaction(self) -> None:
        self.interactions_since_update += 1

    def record_update(self) -> None:
        self.last_update_at = time.time()
        self.interactions_since_update = 0
        if self.schedule_index < len(self.backoff_schedule):
            self.schedule_index += 1

    def reset(self) -> None:
        self.schedule_index = 0
        self.interactions_since_update = 0
        self.last_update_at = time.time()

    def to_dict(self) -> Dict[str, Any]:
        return {
            "schedule_index": self.schedule_index,
            "interactions_since_update": self.interactions_since_update,
            "last_update_at": self.last_update_at,
        }

    @classmethod
    def from_dict(cls, payload: Dict[str, Any]) -> "AdaptiveProfileUpdater":
        return cls(
            schedule_index=int(payload.get("schedule_index", 0)),
            interactions_since_update=int(payload.get("interactions_since_update", 0)),
            last_update_at=float(payload.get("last_update_at", 0.0)),
        )
