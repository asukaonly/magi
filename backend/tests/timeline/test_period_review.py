"""Scale-specific, bounded review payloads without eager evidence reads."""
from datetime import datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock
from zoneinfo import ZoneInfo
import json

import pytest

from magi.memory.l1.overview_contracts import EventOverview, EventOverviewCount, EventOverviewPreview
from magi.timeline.period_review import calendar_boundaries
from magi.timeline.viewport_builder import TimelineViewportBuilder


def stamp(value: str, zone: str = 'Asia/Shanghai') -> float:
    return datetime.fromisoformat(value).replace(tzinfo=ZoneInfo(zone)).timestamp()


@pytest.mark.parametrize('count', [5000, 50000])
async def test_month_payload_is_bounded_without_month_summary(count):
    start, end = stamp('2026-10-01'), stamp('2026-11-01')
    facts = EventOverview(
        counts=[EventOverviewCount(0, 'codex_agent_history', count)],
        previews=[EventOverviewPreview(0, 'event', start + 3600, 'codex_agent_history', 'Review reporting', 'Compare query results')],
    )
    l1 = SimpleNamespace(read_event_overview=AsyncMock(return_value=facts), query_events=AsyncMock(side_effect=AssertionError('Raw reads are forbidden')))
    l3 = SimpleNamespace(list_summaries_by_category=AsyncMock(return_value=[{
        'summary_id': 'day-1', 'summary_category': 'day', 'period_start': start, 'period_end': start + 86400,
        'content': 'Review reporting and compare query results.', 'key_topics': ['Reporting'], 'updated_at': end,
    }]))
    result = await TimelineViewportBuilder(l1_store=l1, l3_store=l3).build_viewport(scale='month', start=start, end=end, timezone='Asia/Shanghai')
    review = result['period_review']
    assert len(review['periods']) == 5
    assert review['periods'][0]['target_start'] == stamp('2026-09-28')
    assert review['periods'][0]['start'] == start
    assert review['periods'][-1]['end'] == end
    assert review['periods'][0]['summary'] == 'Review reporting and compare query results.'
    assert review['summary_status'] == 'partial'
    assert review['topics'][0]['title'] == 'Reporting'
    assert result['summary']['event_count'] == count
    assert all(not result[key] for key in ('clusters', 'episodes', 'reflections', 'raw_events'))
    assert len(json.dumps(result)) < 6000
    l1.query_events.assert_not_awaited()
    assert l3.list_summaries_by_category.call_args.kwargs['period_start'] == start


async def test_week_empty_days_and_filtered_reads_do_not_reuse_unrelated_summaries():
    start, end = stamp('2026-10-26'), stamp('2026-11-02')
    l1 = SimpleNamespace(read_event_overview=AsyncMock(return_value=EventOverview(
        counts=[EventOverviewCount(3, 'codex_agent_history', 1)],
        previews=[EventOverviewPreview(3, 'event', start + 3 * 86400, 'codex_agent_history', 'entity:52b5f111f', 'Codex conversed <environment_context>private')],
    )))
    l3 = SimpleNamespace(list_summaries_by_category=AsyncMock())
    result = await TimelineViewportBuilder(l1_store=l1, l3_store=l3).build_viewport(
        scale='week', start=start, end=end, timezone='Asia/Shanghai', query='coding',
    )
    assert len(result['period_review']['periods']) == 7
    assert result['period_review']['periods'][0]['event_count'] == 0
    assert result['period_review']['periods'][3]['summary'] == ''
    assert 'environment_context' not in json.dumps(result)
    l3.list_summaries_by_category.assert_not_awaited()
    assert l1.read_event_overview.call_args.args[0].term_groups


def test_calendar_buckets_follow_dst():
    boundaries = calendar_boundaries(stamp('2026-11-01', 'America/New_York'), stamp('2026-11-03', 'America/New_York'), 'America/New_York')
    assert [b - a for a, b in zip(boundaries, boundaries[1:])] == [25 * 3600, 24 * 3600]


async def test_empty_facts_do_not_resurface_stale_summary():
    start, end = stamp('2026-10-01'), stamp('2026-11-01')
    l1 = SimpleNamespace(read_event_overview=AsyncMock(return_value=EventOverview()))
    l3 = SimpleNamespace(list_summaries_by_category=AsyncMock(return_value=[{
        'summary_category': 'month', 'period_start': start, 'period_end': end,
        'content': 'Deleted evidence', 'key_topics': ['Deleted topic'],
    }]))
    result = await TimelineViewportBuilder(l1_store=l1, l3_store=l3).build_viewport(scale='month', start=start, end=end)
    assert result['overview']['summary'] == ''
    assert result['period_review']['topics'] == []
