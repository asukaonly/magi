"""Models for the daily_mood_aggregate projection."""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(slots=True)
class DailyMoodAggregate:
    """One row per local date — the sidebar mood calendar reads this directly."""

    day_local_date: str  # YYYY-MM-DD
    dominant_valence: str = "neutral"  # warm | bright | neutral | cool | tense
    volatility_score: float = 0.0  # 0.0 flat – 1.0 high swings
    state_curve_compact: list[float] = field(default_factory=list)
    event_count: int = 0
    source_event_ids: list[str] = field(default_factory=list)
    computed_at: float = 0.0

    def __post_init__(self) -> None:
        date = (self.day_local_date or "").strip()
        if not date:
            raise ValueError("day_local_date must not be blank")
        self.day_local_date = date
        self.dominant_valence = (self.dominant_valence or "neutral").strip() or "neutral"
        self.volatility_score = max(0.0, min(1.0, float(self.volatility_score or 0.0)))
        self.state_curve_compact = [float(x) for x in (self.state_curve_compact or [])]
        self.event_count = int(self.event_count or 0)
        self.source_event_ids = list(
            dict.fromkeys(
                str(event_id).strip()
                for event_id in (self.source_event_ids or [])
                if str(event_id).strip()
            )
        )
        self.computed_at = float(self.computed_at or 0.0)
