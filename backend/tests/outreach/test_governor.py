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
async def test_quiet_hours_defer():
    v, release = await _gov(_Log(), hour=23).evaluate(_intent(), external_target=object())
    assert v is GovernorVerdict.DEFER and release is not None


@pytest.mark.asyncio
async def test_over_budget_defers_normal():
    v, _ = await _gov(_Log(count=DAILY_EXTERNAL_BUDGET), hour=12).evaluate(_intent(), external_target=object())
    assert v is GovernorVerdict.DEFER


@pytest.mark.asyncio
async def test_high_urgency_bypasses_budget_not_quiet_hours():
    v, _ = await _gov(_Log(count=DAILY_EXTERNAL_BUDGET), hour=12).evaluate(
        _intent(urgency=Urgency.HIGH), external_target=object())
    assert v is GovernorVerdict.PUSH_NOW
    v2, _ = await _gov(_Log(count=DAILY_EXTERNAL_BUDGET), hour=2).evaluate(
        _intent(urgency=Urgency.HIGH), external_target=object())
    assert v2 is GovernorVerdict.DEFER


@pytest.mark.asyncio
async def test_normal_push_now():
    v, _ = await _gov(_Log(count=0), hour=12).evaluate(_intent(), external_target=object())
    assert v is GovernorVerdict.PUSH_NOW


@pytest.mark.asyncio
async def test_none_target_drops():
    # No external surface to reach -> DROP, before any delivery-log IO.
    v, release = await _gov(_Log(), hour=12).evaluate(_intent(), external_target=None)
    assert v is GovernorVerdict.DROP
    assert release is None
