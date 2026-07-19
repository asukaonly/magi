"""Gate the EXTERNAL push (quiet hours / budget). Desktop write is
ungated. v1 hardcodes thresholds as module constants — moving them to
user/system config is a follow-up (spec section 11.9)."""
from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any, Callable

from .contracts import GovernorVerdict, OutreachIntent, Urgency

# --- v1 HARDCODED THRESHOLDS (spec section 11.9 = move to config later) ---
QUIET_HOURS_LOCAL = (22, 8)        # [22:00, 08:00) local = quiet
DAILY_EXTERNAL_BUDGET = 20         # max external pushes per user per local day
# --------------------------------------------------------------------------


def _to_ms(dt: datetime) -> int:
    return int(dt.timestamp() * 1000)


class Governor:
    def __init__(self, *, delivery_log: Any, now_local: Callable[[], datetime] | None = None) -> None:
        self._log = delivery_log
        self._now_local = now_local or datetime.now

    def _in_quiet_hours(self, now: datetime) -> bool:
        start, end = QUIET_HOURS_LOCAL
        return now.hour >= start or now.hour < end

    def _next_quiet_end_ms(self, now: datetime) -> int:
        _, end = QUIET_HOURS_LOCAL
        candidate = now.replace(hour=end, minute=0, second=0, microsecond=0)
        if now.hour >= end:  # already past today's end hour -> tomorrow
            candidate = candidate + timedelta(days=1)
        return _to_ms(candidate)

    def _start_of_day_ms(self, now: datetime) -> int:
        return _to_ms(now.replace(hour=0, minute=0, second=0, microsecond=0))

    def _next_day_ms(self, now: datetime) -> int:
        return _to_ms(now.replace(hour=0, minute=0, second=0, microsecond=0) + timedelta(days=1))

    async def evaluate(
        self, intent: OutreachIntent, *, external_target: Any
    ) -> tuple[GovernorVerdict, int | None]:
        if external_target is None:
            return GovernorVerdict.DROP, None

        now = self._now_local()
        if self._in_quiet_hours(now):
            return GovernorVerdict.DEFER, self._next_quiet_end_ms(now)

        if intent.urgency is not Urgency.HIGH:
            count = await self._log.count_for_user_since(intent.user_id, self._start_of_day_ms(now))
            if count >= DAILY_EXTERNAL_BUDGET:
                return GovernorVerdict.DEFER, self._next_day_ms(now)

        return GovernorVerdict.PUSH_NOW, None
