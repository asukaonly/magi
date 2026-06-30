"""Overview card assembly for timeline viewports."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from .viewport_i18n import is_zh_locale, source_label, timeline_t


class TimelineOverviewBuilder:
    """Build the viewport overview block from already-derived viewport data."""

    def __init__(self, *, l3_store: Any | None = None) -> None:
        self._l3 = l3_store

    async def build(
        self,
        *,
        scale: str,
        period_start: float,
        period_end: float,
        events: list[dict[str, Any]],
        clusters: list[dict[str, Any]],
        reflections: list[dict[str, Any]],
        raw_events: list[dict[str, Any]],
        state_markers: list[dict[str, Any]],
        source_mix: list[dict[str, Any]],
        locale: str,
    ) -> dict[str, Any]:
        title_by_scale = self._titles(locale)
        top_reflection = reflections[0] if reflections else None
        top_cluster = max(
            clusters, key=lambda item: int(item.get("event_count") or 0), default=None
        )
        top_event = raw_events[0] if raw_events else None
        summary = self._summary(
            top_reflection=top_reflection,
            top_cluster=top_cluster,
            top_event=top_event,
            locale=locale,
        )
        takeaways = self._takeaways(
            source_mix=source_mix,
            state_markers=state_markers,
            event_count=len(events),
            locale=locale,
        )
        confidence = self._confidence(
            top_reflection=top_reflection,
            top_cluster=top_cluster,
            top_event=top_event,
            state_markers=state_markers,
        )
        essence_prose = await self._lookup_essence_prose(
            scale=scale,
            period_start=period_start,
        )
        return {
            "title": title_by_scale.get(scale, title_by_scale["month"]),
            "summary": summary,
            "key_takeaways": takeaways[:3],
            "confidence": confidence,
            "essence_prose": essence_prose,
        }

    @staticmethod
    def _titles(locale: str) -> dict[str, str]:
        zh = is_zh_locale(locale)
        return {
            "month": timeline_t(
                "overview.month", locale, fallback="窗口概览" if zh else "Window overview"
            ),
            "week": timeline_t(
                "overview.week", locale, fallback="本周概览" if zh else "Week overview"
            ),
            "day": timeline_t(
                "overview.day", locale, fallback="当日概览" if zh else "Day overview"
            ),
            "hour": timeline_t(
                "overview.hour", locale, fallback="证据概览" if zh else "Evidence overview"
            ),
        }

    @staticmethod
    def _summary(
        *,
        top_reflection: dict[str, Any] | None,
        top_cluster: dict[str, Any] | None,
        top_event: dict[str, Any] | None,
        locale: str,
    ) -> str:
        zh = is_zh_locale(locale)
        return str(
            (top_reflection or {}).get("summary")
            or (top_cluster or {}).get("summary")
            or (top_event or {}).get("summary")
            or timeline_t(
                "overview.fallback_summary",
                locale,
                fallback=(
                    "这个时间窗口里已有活动记录，但还没有足够的摘要上下文。"
                    if zh
                    else "Magi has activity in this window, but there is not enough summarized context yet."
                ),
            )
        )

    def _takeaways(
        self,
        *,
        source_mix: list[dict[str, Any]],
        state_markers: list[dict[str, Any]],
        event_count: int,
        locale: str,
    ) -> list[str]:
        takeaways: list[str] = []
        takeaways.extend(self._source_takeaway(source_mix, locale=locale))
        takeaways.extend(self._state_takeaway(state_markers, locale=locale))
        if event_count:
            takeaways.append(self._event_count_takeaway(event_count, locale=locale))
        return takeaways[:3]

    @staticmethod
    def _source_takeaway(
        source_mix: list[dict[str, Any]],
        *,
        locale: str,
    ) -> list[str]:
        if not source_mix:
            return []
        zh = is_zh_locale(locale)
        primary_source = source_mix[0]
        label = primary_source.get("label") or source_label(
            primary_source.get("source_type"), locale
        )
        return [
            timeline_t(
                "takeaways.main_source",
                locale,
                fallback="主要来源：{source}" if zh else "Main source: {source}",
                source=label,
            )
        ]

    @staticmethod
    def _state_takeaway(
        state_markers: list[dict[str, Any]],
        *,
        locale: str,
    ) -> list[str]:
        if not state_markers:
            return []
        zh = is_zh_locale(locale)
        return [
            str(
                state_markers[0].get("summary")
                or state_markers[0].get("label")
                or timeline_t(
                    "takeaways.state_changed",
                    locale,
                    fallback="状态发生变化" if zh else "State changed",
                )
            )
        ]

    @staticmethod
    def _event_count_takeaway(event_count: int, *, locale: str) -> str:
        zh = is_zh_locale(locale)
        return timeline_t(
            "takeaways.event_count",
            locale,
            fallback="捕获 {count} 条事件" if zh else "{count} events captured",
            count=event_count,
        )

    @staticmethod
    def _confidence(
        *,
        top_reflection: dict[str, Any] | None,
        top_cluster: dict[str, Any] | None,
        top_event: dict[str, Any] | None,
        state_markers: list[dict[str, Any]],
    ) -> float:
        confidence = 0.35
        if top_reflection is not None:
            confidence += 0.25
        if top_cluster is not None or top_event is not None:
            confidence += 0.2
        if state_markers:
            confidence += 0.1
        return min(0.95, confidence)

    async def _lookup_essence_prose(self, *, scale: str, period_start: float) -> str:
        """Look up the L3 diary essence for this period, if Plan 2 has produced one."""
        if self._l3 is None:
            return ""

        period_date = datetime.fromtimestamp(period_start).date().isoformat()
        insight_key = f"diary-{scale}-{period_date}"

        try:
            summary = await self._l3._find_summary_by_insight_key(insight_key)
        except Exception:
            return ""

        if not summary:
            return ""
        if summary.get("narrative_style") != "diary_2p":
            return ""
        return str(summary.get("essence_prose") or "")
