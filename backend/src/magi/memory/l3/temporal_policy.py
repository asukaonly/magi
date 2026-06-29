"""Period-specific policy for L3 temporal summary generation."""

from __future__ import annotations

from .temporal_language import target_language_code

LEGACY_FLAT_TIMEOUT_SECONDS = 3.0

_PERIOD_TIMEOUT_SECONDS = {
    "hour": 180.0,
    "day": 300.0,
    "week": 600.0,
    "month": 600.0,
    "quarter": 600.0,
    "year": 600.0,
}
_PERIOD_DISABLE_THINKING = {
    "hour": True,
    "day": False,
    "week": False,
    "month": False,
    "quarter": False,
    "year": False,
}
_PERIOD_FOCUS_INSTRUCTIONS = {
    "hour": (
        "- Hour focus: capture the local sequence, immediate context, and short-lived shifts inside this hour.\n"
        "- Avoid turning one hour of activity into a durable preference or long-term trend."
    ),
    "day": (
        "- Day focus: identify the main blocks of the day, attention shifts, explicit decisions, and repeated constraints.\n"
        "- Preserve concrete anchors such as projects, tools, services, sites, people, media titles, and action items when evidence supports them.\n"
        "- Separate meaningful patterns from ordinary single-event noise."
    ),
    "week": (
        "- Week focus: synthesize durable themes, recurring interests, cross-source patterns, and notable changes across the week.\n"
        "- Keep representative anchors such as projects, tools, sites, media titles, source clusters, and decisions so future recall can recover specifics.\n"
        "- Avoid listing every event, but do not compress the week into a single generic theme."
    ),
    "month": (
        "- Month focus: synthesize cross-week themes, stage changes, sustained interests, project progress, and unusually frequent activities across the month.\n"
        "- Prefer a timeline-oriented month recap over listing weekly summaries one by one.\n"
        "- Keep representative anchors for ongoing projects, source-specific habits, decisions, purchases, and open threads."
    ),
    "quarter": (
        "- Long-window focus: synthesize durable themes, recurring interests, cross-source patterns, and notable changes across the window.\n"
        "- Keep representative anchors for durable projects, decisions, constraints, and source-specific habits without listing every event."
    ),
    "year": (
        "- Long-window focus: synthesize durable themes, recurring interests, cross-source patterns, and notable changes across the window.\n"
        "- Keep representative anchors for durable projects, decisions, constraints, and source-specific habits without listing every event."
    ),
}
_SECTION_LABELS = {
    "zh": {
        "headline": "## 要点",
        "subperiod": "## 子周期脉络",
        "timeline": "## 时间线",
        "decisions": "## 决策与行动",
        "open_threads": "## 未闭合",
        "vs_yesterday": "## 与昨日对比",
        "vs_last_week": "## 与上周对比",
        "vs_last_month": "## 与上月对比",
        "vs_last_quarter": "## 与上季度对比",
        "vs_last_year": "## 与去年对比",
    },
    "en": {
        "headline": "## Highlights",
        "subperiod": "## Subperiod arc",
        "timeline": "## Timeline",
        "decisions": "## Decisions and actions",
        "open_threads": "## Open threads",
        "vs_yesterday": "## vs yesterday",
        "vs_last_week": "## vs last week",
        "vs_last_month": "## vs last month",
        "vs_last_quarter": "## vs last quarter",
        "vs_last_year": "## vs last year",
    },
}


class TemporalSummaryPolicy:
    """Own the generation rules that vary by temporal summary period."""

    def __init__(self, *, timeout_override_seconds: float | None = None) -> None:
        self._timeout_override_seconds = timeout_override_seconds

    def timeout_seconds_for_category(self, category: str) -> float:
        if self._timeout_override_seconds is not None:
            return self._timeout_override_seconds
        return _PERIOD_TIMEOUT_SECONDS.get(str(category), _PERIOD_TIMEOUT_SECONDS["week"])

    def disable_thinking_for_category(self, category: str) -> bool:
        return _PERIOD_DISABLE_THINKING.get(str(category), False)

    def focus_instruction(self, category: str) -> str:
        return _PERIOD_FOCUS_INSTRUCTIONS.get(
            str(category),
            _PERIOD_FOCUS_INSTRUCTIONS["week"],
        )

    def structure_instruction(self, category: str) -> str:
        s = self._section_labels()
        templates = {
            "hour": (
                "- content (markdown): a single short paragraph (1-3 sentences). Section headings are optional for hour summaries; if used, only `{headline}` and `{timeline}`.\n"
                "- change_and_pattern.headline: one short sentence mirroring the content paragraph.\n"
                "- change_and_pattern.timeline: 1-3 ordered activity blocks when supported.\n"
                "- change_and_pattern.source_signals: 0-3 source-specific signals.\n"
                "- daily_breakdown / weekly_breakdown / trend_shifts / metrics: leave empty for hour windows.\n"
                "- Leave unsupported arrays empty rather than filling them with guesses."
            ),
            "day": (
                "- content (markdown): use sections `{headline}`, `{timeline}`, `{decisions}`, `{open_threads}`, and `{vs_yesterday}` when previous_period_summaries supports it. Each section body is a tight bullet list; total length 4-8 lines of bullets plus a one-line headline.\n"
                "- change_and_pattern.headline: one short sentence; same as the `{headline}` line.\n"
                "- change_and_pattern.timeline: 2-5 ordered blocks or phase shifts.\n"
                "- change_and_pattern.source_signals: 2-5 source-specific signals when multiple sources or repeated source behavior appear.\n"
                "- change_and_pattern.decisions_and_actions and open_threads: preserve concrete tasks, purchases, choices, or unresolved follow-ups.\n"
                "- change_and_pattern.trend_shifts: populate rising/falling/new/persisting only when previous_period_summaries supports the comparison; otherwise leave the arrays empty.\n"
                "- change_and_pattern.metrics: fill event_count, dominant_sources, and any other numeric signals you can ground in source_distribution and event_type_distribution; leave unknown numeric fields out.\n"
                "- daily_breakdown and weekly_breakdown: leave empty for day windows."
            ),
            "week": (
                "- content (markdown): use sections `{headline}`, `{subperiod}` (per-day bullets covering each day in the window, sourced from child_period_summaries headlines), `{timeline}` (3-6 phase-level bullets), `{decisions}`, `{open_threads}`, `{vs_last_week}`. Total length should remain compact - aim for 12-20 bullet lines.\n"
                "- change_and_pattern.headline: one short sentence capturing the week-level arc.\n"
                "- change_and_pattern.daily_breakdown: 5-8 entries, one per day in the window, each a `MM-DD: one-line` string sourced from child day headlines or your synthesis when child summaries are missing for some days.\n"
                "- change_and_pattern.timeline: 3-6 ordered phases, day clusters, or stage shifts.\n"
                "- change_and_pattern.source_signals: 3-6 source-specific signals covering dominant sources and unusual repeated behavior.\n"
                "- change_and_pattern.decisions_and_actions and open_threads: keep representative concrete anchors that future recall may query; for open_threads, include since-date when known.\n"
                "- change_and_pattern.trend_shifts: rising/falling reserved for sustained multi-week trajectories visible across previous_period_summaries; use `new` for themes appearing only this week and `persisting` for themes stable across the comparison series.\n"
                "- change_and_pattern.metrics: fill event_count, covered_children (number of distinct child days), deep_work_blocks, fragmentation_score, dominant_sources where evidence supports.\n"
                "- weekly_breakdown: leave empty for week windows."
            ),
            "month": (
                "- content (markdown): use sections `{headline}`, `{subperiod}` (per-week bullets sourced from child_period_summaries), `{timeline}`, `{decisions}`, `{open_threads}`, `{vs_last_month}`. Total length should remain compact - aim for 14-22 bullet lines.\n"
                "- change_and_pattern.headline: one short sentence capturing the month-level arc.\n"
                "- change_and_pattern.weekly_breakdown: 4-5 entries, one per ISO-week in the window, each `Week N (MM-DD~MM-DD): one-line`, sourced from child week headlines.\n"
                "- change_and_pattern.timeline: 3-7 ordered phases or week-to-week stage shifts.\n"
                "- change_and_pattern.source_signals: 3-7 source-specific signals covering dominant sources and unusual repeated behavior.\n"
                "- change_and_pattern.decisions_and_actions and open_threads: retain representative project, purchase, planning, and interest anchors; carry open_threads forward from child summaries when still unresolved.\n"
                "- change_and_pattern.trend_shifts: rising/falling reserved for sustained multi-month trajectories visible across previous_period_summaries.\n"
                "- change_and_pattern.metrics: fill event_count, covered_children (number of distinct child weeks), deep_work_blocks, fragmentation_score, dominant_sources where evidence supports.\n"
                "- daily_breakdown: leave empty for month windows."
            ),
            "quarter": (
                "- content (markdown): use sections `{headline}`, `{timeline}`, `{decisions}`, `{open_threads}`, `{vs_last_quarter}`. Aim for 12-20 bullet lines.\n"
                "- change_and_pattern.headline, timeline, source_signals, decisions_and_actions, open_threads, trend_shifts, metrics: populate as for month windows, scaled to quarter granularity.\n"
                "- Use structured arrays to retain representative anchors rather than exhaustive event lists."
            ),
            "year": (
                "- content (markdown): use sections `{headline}`, `{timeline}`, `{decisions}`, `{open_threads}`, `{vs_last_year}`. Aim for 14-22 bullet lines.\n"
                "- change_and_pattern.headline, timeline, source_signals, decisions_and_actions, open_threads, trend_shifts, metrics: populate at year granularity.\n"
                "- Use structured arrays to retain representative anchors rather than exhaustive event lists."
            ),
        }
        template = templates.get(str(category), templates["week"])
        return template.format(**s)

    def _section_labels(self) -> dict[str, str]:
        return _SECTION_LABELS["zh" if target_language_code() == "zh" else "en"]


__all__ = [
    "LEGACY_FLAT_TIMEOUT_SECONDS",
    "TemporalSummaryPolicy",
]
