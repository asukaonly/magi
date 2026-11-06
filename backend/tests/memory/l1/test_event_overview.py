"""Real repository coverage for bounded overview reads and visibility."""
from dataclasses import replace

import pytest

from magi.memory.evidence import L1RetrievalScope
from magi.memory.l1.overview_contracts import EventOverviewQuery
from .test_event_repository import command, repository  # noqa: F401
from .test_mysql_event_repository import mysql_environment  # noqa: F401


@pytest.fixture(params=['sqlite', 'mysql'])
def overview_repository(request):
    if request.param == 'sqlite':
        return request.getfixturevalue('repository')[0]
    return request.getfixturevalue('mysql_environment')[0]


async def test_bounded_previews_exact_counts_and_visibility(overview_repository):
    repo = overview_repository
    for index in range(24):
        item = command(f'overview-{index}')
        item.event.timestamp = float(index)
        item.event.content = 'needle ' + 'raw payload ' * 1000
        item = replace(item, metadata={'activity_snapshot': {'title': 'Review project', 'summary': 'Short preview'}, 'large': 'x' * 5000})
        if index == 4:
            item = replace(item, evidence=replace(item.evidence, retrieval_scope=L1RetrievalScope.AUDIT_ONLY))
        await repo.append(item)
    await repo.soft_delete_events(['overview-3'], deleted_at=50)
    query = EventOverviewQuery(boundaries=(0, 10, 20), retrieval_scopes=('fact_authoritative',))
    result = await repo.read_event_overview(query)
    assert [(row.bucket, row.count) for row in result.counts] == [(0, 8), (1, 10)]
    assert len(result.previews) == 6
    assert all(row.title == 'Review project' and row.summary == 'Short preview' for row in result.previews)
    assert all(row.timestamp < 20 and row.event_id not in {'overview-3', 'overview-4'} for row in result.previews)
    assert not (await repo.read_event_overview(replace(query, term_groups=(('not found',),)))).counts
    assert sum(row.count for row in (await repo.read_event_overview(replace(query, term_groups=(('needle',),)))).counts) == 18
    assert not (await repo.read_event_overview(replace(query, retrieval_scopes=()))).counts


def test_overview_rejects_unbounded_or_invalid_queries():
    for boundaries in [(1, 1), (2, 1), (0, float('inf')), tuple(range(35))]:
        with pytest.raises(ValueError):
            EventOverviewQuery(boundaries=boundaries, retrieval_scopes=())
