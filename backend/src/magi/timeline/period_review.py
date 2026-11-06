"""Bounded calendar review projections for week and month viewports."""
from __future__ import annotations

from collections import Counter
from dataclasses import asdict, dataclass, field
from datetime import datetime, time, timedelta
import re
from typing import Any, Literal
from zoneinfo import ZoneInfo

from magi.memory.evidence import USER_VISIBLE_L1_RETRIEVAL_SCOPES
from magi.memory.l1.overview_contracts import EventOverview, EventOverviewQuery

from .presentation_text import display_text, readable_label
from .query_interpreter import TimelineQueryInterpretation, TimelineQueryInterpreter
from .viewport_i18n import source_label


@dataclass
class ReviewPeriod:
    start: float
    end: float
    target_start: float
    scale: Literal['day', 'week']
    summary: str = ''
    event_count: int = 0
    source_types: list[str] = field(default_factory=list)
    has_summary: bool = False


@dataclass
class ReviewTopic:
    topic_id: str
    title: str
    summary: str
    source_types: list[str]
    period_starts: list[float]


@dataclass
class PeriodReview:
    periods: list[ReviewPeriod]
    topics: list[ReviewTopic]
    summary_status: Literal['ready', 'partial', 'pending']
    summary_updated_at: float | None
    active_days: int

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def calendar_boundaries(start: float, end: float, timezone: str | None) -> list[float]:
    """Keep local calendar days intact, including daylight-saving transitions."""
    zone = ZoneInfo(timezone or 'UTC')
    current = datetime.fromtimestamp(start, zone)
    boundaries = [start]
    while True:
        current = datetime.combine(current.date() + timedelta(days=1), time.min, zone)
        if current.timestamp() >= end:
            break
        boundaries.append(current.timestamp())
        if len(boundaries) > 32:
            raise ValueError('Period reviews support at most 32 calendar days')
    boundaries.append(end)
    return boundaries


def short_text(value: Any, limit: int = 180) -> str:
    text = readable_label(display_text(value))
    text = re.sub(r'\s+', ' ', text).strip()
    return text if len(text) <= limit else text[:limit].rstrip() + '…'


def summary_text(summary: dict[str, Any]) -> str:
    return short_text(summary.get('essence_prose') or summary.get('content'))


class TimelinePeriodReviewBuilder:
    """Project summaries and bounded L1 previews without transient clustering."""

    def __init__(self, *, l1_store: Any, l3_store: Any | None) -> None:
        self._l1 = l1_store
        self._l3 = l3_store

    async def build(
        self, *, scale: str, query: TimelineQueryInterpretation,
        timezone: str | None, locale: str, query_text: str | None, focus: str,
    ) -> dict[str, Any]:
        boundaries = calendar_boundaries(query.start, query.end, timezone)
        interpreter = TimelineQueryInterpreter()
        groups = [tuple(interpreter.expand_hint(hint)) for hint in (*query.mood_hints, *query.activity_hints)]
        groups.extend((term,) for term in query.residual_terms)
        facts = await self._l1.read_event_overview(EventOverviewQuery(
            boundaries=tuple(boundaries), retrieval_scopes=tuple(USER_VISIBLE_L1_RETRIEVAL_SCOPES),
            term_groups=tuple(groups),
        )) if self._l1 is not None else EventOverview()
        summaries = await self._load_summaries(query) if not query.has_filters else []
        days = self._days(boundaries, facts, summaries)
        periods = days if scale == 'week' else self._weeks(days, summaries, timezone)
        usable = [item for item in summaries if any(
            day.event_count and day.start < float(item.get('period_end') or 0)
            and day.end > float(item.get('period_start') or 0) for day in days
        )]
        top = self._matching_summary(usable, scale, query.start, query.end)
        topics = self._topics(usable, periods)
        status = 'ready' if top else 'partial' if any(period.has_summary for period in periods) else 'pending'
        overview = summary_text(top) if top else ''
        # Partial coverage gets an honest short overview from existing child summaries.
        if not overview:
            overview = short_text(' · '.join(topic.title for topic in topics))
        updated = [float(item.get('updated_at') or 0) for item in usable]
        review = PeriodReview(
            periods=periods, topics=topics, summary_status=status,
            summary_updated_at=max(updated) if updated and max(updated) else None,
            active_days=sum(day.event_count > 0 for day in days),
        )
        source_counts: Counter[str] = Counter()
        for count in facts.counts:
            source_counts[count.source] += count.count
        return {
            'viewport': {'scale': scale, 'start': query.start, 'end': query.end,
                         'focus': focus, 'query': query_text, 'timezone': timezone, 'locale': locale},
            'summary': {'cluster_count': 0, 'event_count': sum(source_counts.values()), 'dominant_modes': []},
            'overview': {'title': '', 'summary': overview, 'essence_prose': overview,
                         'key_takeaways': [], 'confidence': 0.0},
            'period_review': review.to_dict(),
            'source_mix': [{'source_type': source, 'label': source_label(source, locale), 'event_count': count}
                           for source, count in source_counts.most_common()],
            'state_summary': {'mood_label': '', 'stress_label': '', 'engagement_label': '', 'notable_changes': []},
            'state_bands': [], 'state_markers': [], 'state_transitions': [], 'theme_cards': [],
            'place_hints': [], 'clusters': [], 'episodes': [], 'reflections': [], 'raw_events': [],
        }

    async def _load_summaries(self, query: TimelineQueryInterpretation) -> list[dict[str, Any]]:
        if self._l3 is None:
            return []
        rows = await self._l3.list_summaries_by_category(
            summary_categories=['day', 'week', 'month'], period_start=query.start,
            period_end=query.end, limit=128,
        )
        # A neighboring month's/week's summary must not describe this window.
        return [row for row in rows if float(row.get('period_start') or 0) >= query.start
                and float(row.get('period_end') or 0) <= query.end
                and float(row.get('period_start') or 0) < query.end
                and float(row.get('period_end') or 0) > query.start]

    @staticmethod
    def _matching_summary(rows: list[dict[str, Any]], category: str, start: float, end: float) -> dict[str, Any] | None:
        matches = [row for row in rows if row.get('summary_category') == category
                   and abs(float(row.get('period_start') or 0) - start) < 1
                   and abs(float(row.get('period_end') or 0) - end) <= 1]
        return max(matches, key=lambda row: float(row.get('updated_at') or 0), default=None)

    def _days(self, boundaries: list[float], facts: EventOverview, summaries: list[dict[str, Any]]) -> list[ReviewPeriod]:
        days: list[ReviewPeriod] = []
        for bucket, (start, end) in enumerate(zip(boundaries, boundaries[1:])):
            counts = sorted((item for item in facts.counts if item.bucket == bucket), key=lambda item: (-item.count, item.source))
            summary = self._matching_summary(summaries, 'day', start, end) if counts else None
            previews = list(dict.fromkeys(
                short_text(readable_label(display_text(item.title, item.source)) or display_text(item.summary, item.source), 90)
                for item in facts.previews if item.bucket == bucket
            ))
            days.append(ReviewPeriod(
                start=start, end=end, target_start=start, scale='day',
                summary=summary_text(summary) if summary else short_text(' · '.join(value for value in previews[:2] if value)),
                event_count=sum(item.count for item in counts), source_types=[item.source for item in counts],
                has_summary=bool(summary and summary_text(summary)),
            ))
        return days

    def _weeks(self, days: list[ReviewPeriod], summaries: list[dict[str, Any]], timezone: str | None) -> list[ReviewPeriod]:
        zone = ZoneInfo(timezone or 'UTC')
        grouped: dict[float, list[ReviewPeriod]] = {}
        for day in days:
            date = datetime.fromtimestamp(day.start, zone)
            monday = datetime.combine(date.date() - timedelta(days=date.weekday()), time.min, zone).timestamp()
            grouped.setdefault(monday, []).append(day)
        weeks: list[ReviewPeriod] = []
        for monday, children in grouped.items():
            start, end = children[0].start, children[-1].end
            summary = self._matching_summary(summaries, 'week', start, end) if any(day.event_count for day in children) else None
            child_text = list(dict.fromkeys(day.summary for day in children if day.summary))
            weeks.append(ReviewPeriod(
                start=start, end=end, target_start=monday, scale='week',
                summary=summary_text(summary) if summary else short_text(' · '.join(child_text[:2])),
                event_count=sum(day.event_count for day in children),
                source_types=list(dict.fromkeys(source for day in children for source in day.source_types)),
                has_summary=bool(summary) or any(day.has_summary for day in children),
            ))
        return weeks

    @staticmethod
    def _topics(summaries: list[dict[str, Any]], periods: list[ReviewPeriod]) -> list[ReviewTopic]:
        candidates: dict[str, tuple[str, list[dict[str, Any]]]] = {}
        for summary in summaries:
            for value in summary.get('key_topics') or []:
                title = short_text(value, 56)
                if title:
                    candidates.setdefault(title.casefold(), (title, []))[1].append(summary)
        topics: list[ReviewTopic] = []
        for key, (title, evidence) in sorted(candidates.items(), key=lambda item: -len(item[1][1]))[:3]:
            related = [period for period in periods if period.event_count and any(
                float(row.get('period_start') or 0) < period.end and float(row.get('period_end') or 0) > period.start
                for row in evidence
            )]
            if not related:
                continue
            # Prefer a sentence that names the topic over copying a whole period summary.
            sentences = [sentence.strip() for row in evidence for sentence in re.split(r'(?<=[。.!?！？])\s*', summary_text(row)) if key in sentence.casefold()]
            topics.append(ReviewTopic(
                topic_id=key, title=title, summary=short_text(sentences[0], 100) if sentences else '',
                source_types=list(dict.fromkeys(source for period in related for source in period.source_types))[:3],
                period_starts=[period.start for period in related],
            ))
        return topics
