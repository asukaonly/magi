"""Pure update-state helpers for L4 procedural memory records."""
from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Mapping

from .procedural_memory_serialization import rolling_average


@dataclass(frozen=True)
class NewSkillRecordState:
    total_attempts: int
    success_count: int
    failure_count: int
    success_rate: float
    avg_duration_ms: float
    min_duration_ms: float
    max_duration_ms: float
    breaker_state: str
    breaker_opened_at: float | None
    failure_streak: int
    recovery_count: int


@dataclass(frozen=True)
class UpdatedSkillRecordState:
    total_attempts: int
    success_count: int
    failure_count: int
    success_rate: float
    avg_duration_ms: float
    min_duration_ms: float
    max_duration_ms: float
    source_event_ids: list[Any]
    breaker_state: str
    breaker_opened_at: float | None
    failure_streak: int
    recovery_count: int
    last_success_at: Any
    last_failure_at: Any
    pending_trace_count: int

    @property
    def breaker_just_opened(self) -> bool:
        return self.breaker_state == "open" and self.previous_breaker_state != "open"

    @property
    def previous_breaker_state(self) -> str:
        return self._previous_breaker_state

    _previous_breaker_state: str = "closed"


def build_new_skill_record_state(
    *,
    success: bool,
    duration_ms: float,
    event_timestamp: float,
    breaker_failure_threshold: int,
) -> NewSkillRecordState:
    total_attempts = 1
    success_count = 1 if success else 0
    failure_count = 0 if success else 1
    failure_streak = 0 if success else 1
    breaker_state = "closed"
    breaker_opened_at = None
    if failure_streak >= breaker_failure_threshold:
        breaker_state = "open"
        breaker_opened_at = event_timestamp
    return NewSkillRecordState(
        total_attempts=total_attempts,
        success_count=success_count,
        failure_count=failure_count,
        success_rate=float(success_count / total_attempts),
        avg_duration_ms=duration_ms,
        min_duration_ms=duration_ms,
        max_duration_ms=duration_ms,
        breaker_state=breaker_state,
        breaker_opened_at=breaker_opened_at,
        failure_streak=failure_streak,
        recovery_count=0,
    )


def build_updated_skill_record_state(
    *,
    existing: Mapping[str, Any],
    success: bool,
    duration_ms: float,
    event_id: str,
    event_timestamp: float,
    breaker_failure_threshold: int,
    breaker_recovery_successes: int,
) -> UpdatedSkillRecordState:
    total_attempts = int(existing["total_attempts"]) + 1
    success_count = int(existing["success_count"]) + (1 if success else 0)
    failure_count = int(existing["failure_count"]) + (0 if success else 1)
    source_event_ids = json.loads(existing["source_event_ids"] or "[]")
    source_event_ids.append(event_id)

    breaker_state = str(existing["circuit_breaker_state"])
    previous_breaker_state = breaker_state
    failure_streak = int(existing["circuit_breaker_failure_count"])
    recovery_count = int(existing["circuit_breaker_success_count"])
    breaker_opened_at = (
        float(existing["circuit_breaker_opened_at"])
        if existing["circuit_breaker_opened_at"]
        else None
    )

    if success:
        failure_streak = 0
        if breaker_state == "open":
            breaker_state = "half_open"
            recovery_count = 1
        elif breaker_state == "half_open":
            recovery_count += 1
            if recovery_count >= breaker_recovery_successes:
                breaker_state = "closed"
                recovery_count = 0
                breaker_opened_at = None
        else:
            recovery_count = 0
    else:
        recovery_count = 0
        failure_streak += 1
        if failure_streak >= breaker_failure_threshold:
            breaker_state = "open"
            breaker_opened_at = event_timestamp

    return UpdatedSkillRecordState(
        total_attempts=total_attempts,
        success_count=success_count,
        failure_count=failure_count,
        success_rate=float(success_count / total_attempts),
        avg_duration_ms=rolling_average(existing["avg_execution_time_ms"], total_attempts - 1, duration_ms),
        min_duration_ms=min(float(existing["min_execution_time_ms"] or duration_ms), duration_ms),
        max_duration_ms=max(float(existing["max_execution_time_ms"] or duration_ms), duration_ms),
        source_event_ids=source_event_ids,
        breaker_state=breaker_state,
        breaker_opened_at=breaker_opened_at,
        failure_streak=failure_streak,
        recovery_count=recovery_count,
        last_success_at=float(event_timestamp) if success else existing["last_success_at"],
        last_failure_at=float(event_timestamp) if not success else existing["last_failure_at"],
        pending_trace_count=(existing["pending_trace_count"] or 0) + 1,
        _previous_breaker_state=previous_breaker_state,
    )
