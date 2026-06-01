"""WiFi scheduler backoff behavior."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from magi.location.scheduler_contrib import (
    INTERVAL_SECONDS_WIFI_POLL_BACKOFF,
    WIFI_BACKOFF_FAILURE_THRESHOLD,
    WiFiPollSchedulerContrib,
)
from magi.scheduler.contracts import ScheduledExecutionContext


class _StubWiFiSource:
    """Toggleable WiFi source for backoff tests."""

    source_name = "wifi"
    priority = 50
    validity_seconds = 7200

    def __init__(self, sample_to_return) -> None:
        self.sample = sample_to_return
        self.calls = 0

    async def query_samples(self, *, time_start, time_end):
        return []

    async def poll_and_persist(self):
        self.calls += 1
        return self.sample


def _ctx(triggered_at: float) -> ScheduledExecutionContext:
    return ScheduledExecutionContext(
        schedule=MagicMock(),
        target_state=MagicMock(),
        runtime_dir=None,
        triggered_at=triggered_at,
        manual=False,
    )


@pytest.mark.asyncio
async def test_backoff_engages_after_threshold_failures():
    """After N consecutive empty scans, handler short-circuits with a skip
    message instead of running poll_and_persist."""
    source = _StubWiFiSource(sample_to_return=None)
    contrib = WiFiPollSchedulerContrib(wifi_source=source)

    # First N-1 failures: scheduler still calls poll, returns failure
    for i in range(WIFI_BACKOFF_FAILURE_THRESHOLD - 1):
        result = await contrib._handle_poll(_ctx(triggered_at=100.0 + i * 600))
        assert result.success is False
        assert "consecutive_failures" in result.stats

    # Nth failure: tips into backoff
    result = await contrib._handle_poll(_ctx(triggered_at=100.0 + WIFI_BACKOFF_FAILURE_THRESHOLD * 600))
    assert result.success is False
    assert source.calls == WIFI_BACKOFF_FAILURE_THRESHOLD

    # Next tick within backoff window: short-circuits, doesn't call poll
    calls_before = source.calls
    next_trigger = 100.0 + WIFI_BACKOFF_FAILURE_THRESHOLD * 600 + 60  # 1 min later
    result = await contrib._handle_poll(_ctx(triggered_at=next_trigger))
    assert result.success is True  # skip is "success" in the sense of "no work"
    assert "skipped" in result.stats
    assert source.calls == calls_before  # poll NOT called


@pytest.mark.asyncio
async def test_backoff_resets_on_success():
    """A successful scan clears the failure counter and re-engages active interval."""
    sample = MagicMock()
    sample.city = "杭州"
    sample.accuracy_m = 80.0
    sample.metadata = {"ap_count": 5}
    source = _StubWiFiSource(sample_to_return=sample)
    contrib = WiFiPollSchedulerContrib(wifi_source=source)

    # Simulate prior failures by manually setting state
    contrib._consecutive_failures = WIFI_BACKOFF_FAILURE_THRESHOLD
    contrib._skip_until = 0.0  # not in backoff yet

    result = await contrib._handle_poll(_ctx(triggered_at=1000.0))
    assert result.success is True
    assert contrib._consecutive_failures == 0
    assert contrib._skip_until == 0.0


@pytest.mark.asyncio
async def test_backoff_skip_until_passes():
    """After the backoff interval elapses, the handler runs poll again."""
    source = _StubWiFiSource(sample_to_return=None)
    contrib = WiFiPollSchedulerContrib(wifi_source=source)

    # Fast-forward to "post-backoff" by manually setting skip_until
    contrib._consecutive_failures = WIFI_BACKOFF_FAILURE_THRESHOLD
    contrib._skip_until = 500.0
    # Tick at 1000 (well past skip_until)
    result = await contrib._handle_poll(_ctx(triggered_at=1000.0))
    # Still no sample, so failure again — but poll was called
    assert source.calls == 1
    assert result.success is False
