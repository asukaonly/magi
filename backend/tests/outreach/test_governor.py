import pytest
from datetime import datetime
from magi.outreach.contracts import OutreachIntent, OutreachKind, Urgency, GovernorVerdict
from magi.outreach.governor import Governor, DAILY_EXTERNAL_BUDGET


def _intent(urgency=Urgency.NORMAL, cid="c1"):
    return OutreachIntent(kind=OutreachKind.TASK_COMPLETED, user_id="u1",
                          origin_session_id="s1", title="t", facts="f",
                          correlation_id=cid, completed_at_ms=1, urgency=urgency)


class _Log:
    def __init__(self, delivered=(), count=0):
        self._delivered = set(delivered)
        self._count = count

    async def was_delivered(self, cid): return cid in self._delivered
    async def count_for_user_since(self, user_id, since_ms): return self._count


def _gov(log, hour):
    return Governor(delivery_log=log, now_local=lambda: datetime(2026, 6, 2, hour, 0, 0))


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("hour", "verdict", "release"),
    [
        (7, GovernorVerdict.DEFER, datetime(2026, 6, 2, 8)),
        (8, GovernorVerdict.PUSH_NOW, None),
        (21, GovernorVerdict.PUSH_NOW, None),
        (22, GovernorVerdict.DEFER, datetime(2026, 6, 3, 8)),
        (23, GovernorVerdict.DEFER, datetime(2026, 6, 3, 8)),
    ],
)
async def test_outreach_quiet_hour_boundaries_release_at_next_morning(hour, verdict, release):
    log = _Log()
    result = await _gov(log, hour).evaluate(_intent(), external_target=object())
    assert result == (verdict, int(release.timestamp() * 1000) if release else None)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("count", "verdict", "release"),
    [
        (DAILY_EXTERNAL_BUDGET - 1, GovernorVerdict.PUSH_NOW, None),
        (DAILY_EXTERNAL_BUDGET, GovernorVerdict.DEFER, datetime(2026, 6, 3)),
    ],
)
async def test_outreach_queries_user_local_day_and_defers_at_budget(count, verdict, release):
    from unittest.mock import AsyncMock

    log = _Log()
    log.count_for_user_since = AsyncMock(return_value=count)
    result = await _gov(log, 12).evaluate(_intent(), external_target=object())
    assert result == (verdict, int(release.timestamp() * 1000) if release else None)
    log.count_for_user_since.assert_awaited_once_with(
        "u1", int(datetime(2026, 6, 2).timestamp() * 1000)
    )


@pytest.mark.asyncio
async def test_high_urgency_bypasses_budget_not_quiet_hours():
    v, _ = await _gov(_Log(count=DAILY_EXTERNAL_BUDGET), hour=12).evaluate(
        _intent(urgency=Urgency.HIGH), external_target=object())
    assert v is GovernorVerdict.PUSH_NOW
    v2, _ = await _gov(_Log(count=DAILY_EXTERNAL_BUDGET), hour=2).evaluate(
        _intent(urgency=Urgency.HIGH), external_target=object())
    assert v2 is GovernorVerdict.DEFER


@pytest.mark.asyncio
async def test_none_target_drops():
    # No external surface to reach -> DROP, before any delivery-log IO.
    v, release = await _gov(_Log(), hour=12).evaluate(_intent(), external_target=None)
    assert v is GovernorVerdict.DROP
    assert release is None
