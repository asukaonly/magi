"""Scale-aware timeline viewport assembly."""

from __future__ import annotations

import json
from collections import Counter, defaultdict
from typing import Any

from ..i18n import is_zh_language
from .cluster_builder import TimelineClusterBuilder
from .context_bundle_builder import TimelineContextBundleBuilder
from .query_interpreter import TimelineQueryInterpretation, TimelineQueryInterpreter
from .state_band_builder import TimelineStateBandBuilder, derive_state_from_tone


_SOURCE_LABELS_ZH = {
    "chrome_history": "Chrome 历史",
    "manual_journal": "手动记录",
    "chat": "对话",
    "photo_library": "照片库",
    "screen_time": "应用使用情况",
    "system_media": "听歌/视频记录",
    "terminal_history": "终端历史",
    "git_activity": "Git 活动",
    "calendar": "日历",
    "netease_music": "网易云音乐",
}

_MOOD_LABELS_ZH = {
    "positive": "积极",
    "warm": "温和",
    "steady": "平稳",
    "neutral": "中性",
    "cool": "冷静",
    "low": "低落",
    "tense": "紧张",
    "anxious": "焦虑",
    "negative": "消极",
    "focused": "专注",
}


class TimelineViewportBuilder:
    """Assemble scale-aware viewport payloads from memory layers."""

    def __init__(self, *, l1_store: Any, l2_store: Any | None = None, l3_store: Any | None = None, l4_store: Any | None = None) -> None:
        self._l1 = l1_store
        self._l2 = l2_store
        self._l3 = l3_store
        self._l4 = l4_store
        self._state_band_builder = TimelineStateBandBuilder()
        self._cluster_builder = TimelineClusterBuilder()
        self._query_interpreter = TimelineQueryInterpreter()
        self._context_bundle_builder = TimelineContextBundleBuilder(
            l1_store=l1_store,
            l2_store=l2_store,
            l3_store=l3_store,
            l4_store=l4_store,
        )

    async def build_viewport(
        self,
        *,
        scale: str,
        start: float,
        end: float,
        query: str | None = None,
        timezone: str | None = None,
        focus: str = "self",
        locale: str = "en",
    ) -> dict[str, Any]:
        locale = self._normalize_locale(locale)
        interpreted_query = self._query_interpreter.interpret(query=query, start=start, end=end)
        events = await self._load_events(start=interpreted_query.start, end=interpreted_query.end)
        summaries = await self._load_summaries()
        assertions = await self._load_assertions()
        snapshots = await self._load_snapshots()
        episodes = await self._load_episodes(
            start=interpreted_query.start,
            end=interpreted_query.end,
        ) if scale in ("day", "week") else []

        events = self._filter_events(events, interpreted_query)
        summaries = self._filter_summaries(summaries, interpreted_query)

        state_bands, state_markers = self._state_band_builder.build(
            start=interpreted_query.start,
            end=interpreted_query.end,
            summaries=summaries,
            assertions=assertions,
            snapshots=snapshots,
            locale=locale,
        )
        state_transitions = self._build_state_transitions(assertions)
        reflections = self._build_reflections(
            summaries=summaries,
            start=interpreted_query.start,
            end=interpreted_query.end,
        )
        clusters = (
            self._cluster_builder.build(events, scale=scale, episodes=episodes)
            if scale != "hour"
            else []
        )
        if clusters:
            self._localize_cluster_labels(clusters, locale=locale)
            self._enrich_cluster_states(clusters, summaries, start=interpreted_query.start, end=interpreted_query.end)
        raw_events = [self._to_raw_event(event) for event in events] if scale == "hour" else []
        source_mix = self._build_source_mix(events=events, clusters=clusters, locale=locale)
        theme_cards = self._build_theme_cards(reflections=reflections, clusters=clusters)
        overview = self._build_overview(
            scale=scale,
            events=events,
            clusters=clusters,
            reflections=reflections,
            raw_events=raw_events,
            state_markers=state_markers,
            source_mix=source_mix,
            locale=locale,
        )
        state_summary = self._build_state_summary(
            state_bands=state_bands,
            state_markers=state_markers,
            state_transitions=state_transitions,
            locale=locale,
        )

        return {
            "viewport": {
                "scale": scale,
                "start": float(interpreted_query.start),
                "end": float(interpreted_query.end),
                "focus": focus,
                "query": query,
                "timezone": timezone,
                "locale": locale,
            },
            "summary": {
                "cluster_count": len(clusters),
                "event_count": len(events),
                "dominant_modes": [cluster["dominant_mode"] for cluster in clusters[:3]],
            },
            "overview": overview,
            "state_summary": state_summary,
            "state_bands": state_bands,
            "state_markers": state_markers,
            "state_transitions": state_transitions,
            "source_mix": source_mix,
            "theme_cards": theme_cards,
            "clusters": clusters,
            "episodes": episodes if scale in ("day", "week") else [],
            "reflections": reflections if scale == "month" else [],
            "raw_events": raw_events,
        }

    async def build_context_bundle(self, *, anchor: dict[str, Any]) -> dict[str, Any]:
        return await self._context_bundle_builder.build(anchor=anchor)

    def _enrich_cluster_states(
        self,
        clusters: list[dict[str, Any]],
        summaries: list[dict[str, Any]],
        *,
        start: float,
        end: float,
    ) -> None:
        """Populate each cluster's state_snapshot from overlapping L3 summaries."""
        relevant = [
            s for s in summaries
            if float(s.get("period_end") or 0) >= start
            and float(s.get("period_start") or 0) <= end
        ]
        for cluster in clusters:
            cs = cluster["time_start"]
            ce = cluster["time_end"]
            for s in relevant:
                ps = float(s.get("period_start") or 0)
                pe = float(s.get("period_end") or ps)
                if pe >= cs and ps <= ce:
                    sentiment = s.get("sentiment_summary")
                    if isinstance(sentiment, dict):
                        tone = str(sentiment.get("tone") or "").strip()
                        if tone:
                            cluster["state_snapshot"] = derive_state_from_tone(tone)
                    break

    async def _load_events(self, *, start: float, end: float) -> list[dict[str, Any]]:
        if self._l1 is None:
            return []
        return await self._l1.query_events(start_time=start, end_time=end, limit=500)

    async def _load_summaries(self) -> list[dict[str, Any]]:
        if self._l3 is None:
            return []
        return await self._l3.list_summaries(limit=200)

    async def _load_assertions(self) -> list[dict[str, Any]]:
        if self._l2 is None or not hasattr(self._l2, "list_tom_assertions"):
            return []
        return await self._l2.list_tom_assertions(entity_id="user:self", limit=200)

    async def _load_snapshots(self) -> list[dict[str, Any]]:
        if self._l2 is None or not hasattr(self._l2, "list_tom_snapshots"):
            return []
        return await self._l2.list_tom_snapshots(entity_id="user:self", limit=50)

    async def _load_episodes(self, *, start: float, end: float) -> list[dict[str, Any]]:
        """Load durable L2 episodes that overlap the viewport window."""
        if self._l2 is None or not hasattr(self._l2, "list_episodes"):
            return []
        return await self._l2.list_episodes(
            statuses=["active", "user_pinned"],
            time_start=start,
            time_end=end,
            limit=200,
        )

    def _build_state_transitions(self, assertions: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """Extract state transitions from superseded assertion chains."""
        transitions: list[dict[str, Any]] = []
        superseded = [
            a for a in assertions
            if str(a.get("status") or "") == "superseded" and a.get("superseded_by")
        ]
        active_by_id = {
            str(a.get("assertion_id")): a for a in assertions
            if str(a.get("status") or "") not in ("superseded", "archived", "expired")
        }
        for old in superseded:
            new_id = str(old.get("superseded_by") or "")
            new = active_by_id.get(new_id)
            transitions.append({
                "trait_name": str(old.get("trait_name") or ""),
                "old_value": str(old.get("trait_value") or ""),
                "new_value": str(new.get("trait_value") or "") if new else "",
                "changed_at": float(old.get("superseded_at") or old.get("updated_at") or 0),
                "old_assertion_id": str(old.get("assertion_id") or ""),
                "new_assertion_id": new_id,
            })
        transitions.sort(key=lambda t: t["changed_at"])
        return transitions

    def _build_overview(
        self,
        *,
        scale: str,
        events: list[dict[str, Any]],
        clusters: list[dict[str, Any]],
        reflections: list[dict[str, Any]],
        raw_events: list[dict[str, Any]],
        state_markers: list[dict[str, Any]],
        source_mix: list[dict[str, Any]],
        locale: str,
    ) -> dict[str, Any]:
        zh = self._is_zh_locale(locale)
        title_by_scale = (
            {
                "month": "窗口概览",
                "week": "本周概览",
                "day": "当日概览",
                "hour": "证据概览",
            }
            if zh
            else {
                "month": "Window overview",
                "week": "Week overview",
                "day": "Day overview",
                "hour": "Evidence overview",
            }
        )
        top_reflection = reflections[0] if reflections else None
        top_cluster = max(clusters, key=lambda item: int(item.get("event_count") or 0), default=None)
        top_event = raw_events[0] if raw_events else None
        summary = str(
            (top_reflection or {}).get("summary")
            or (top_cluster or {}).get("summary")
            or (top_event or {}).get("summary")
            or (
                "这个时间窗口里已有活动记录，但还没有足够的摘要上下文。"
                if zh
                else "Magi has activity in this window, but there is not enough summarized context yet."
            )
        )
        takeaways: list[str] = []
        if source_mix:
            primary_source = source_mix[0]
            source_label = primary_source.get("label") or self._source_label(primary_source.get("source_type"), locale)
            takeaways.append(f"主要来源：{source_label}" if zh else f"Main source: {source_label}")
        if state_markers:
            takeaways.append(str(state_markers[0].get("summary") or state_markers[0].get("label") or ("状态发生变化" if zh else "State changed")))
        if events:
            takeaways.append(f"捕获 {len(events)} 条事件" if zh else f"{len(events)} events captured")
        confidence = 0.35
        if top_reflection is not None:
            confidence += 0.25
        if top_cluster is not None or top_event is not None:
            confidence += 0.2
        if state_markers:
            confidence += 0.1
        return {
            "title": title_by_scale.get(scale, "窗口概览" if zh else "Window overview"),
            "summary": summary,
            "key_takeaways": takeaways[:3],
            "confidence": min(0.95, confidence),
        }

    def _build_state_summary(
        self,
        *,
        state_bands: list[dict[str, Any]],
        state_markers: list[dict[str, Any]],
        state_transitions: list[dict[str, Any]],
        locale: str,
    ) -> dict[str, Any]:
        mood_value = self._average_state_value(state_bands, "valence")
        stress_value = self._average_state_value(state_bands, "stress_level")
        engagement_value = self._average_state_value(state_bands, "engagement")
        mood_label = self._dominant_state_label(state_bands, locale=locale)
        notable_changes: list[dict[str, Any]] = []
        for marker in state_markers[:3]:
            timestamp = float(marker.get("timestamp") or 0.0)
            notable_changes.append(
                {
                    "label": self._localized_marker_label(marker.get("label"), locale),
                    "summary": str(marker.get("summary") or ("状态发生变化。" if self._is_zh_locale(locale) else "State changed.")),
                    "timestamp": timestamp,
                    "anchor": {
                        "anchor_type": "state_marker",
                        "anchor_id": str(marker.get("marker_id") or ""),
                        "time_start": timestamp,
                        "time_end": timestamp,
                    },
                }
            )
        for transition in state_transitions:
            if len(notable_changes) >= 3:
                break
            trait = self._humanize_label(transition.get("trait_name"), locale=locale)
            old_value = str(transition.get("old_value") or "unknown")
            new_value = str(transition.get("new_value") or "unknown")
            timestamp = float(transition.get("changed_at") or 0.0)
            notable_changes.append(
                {
                    "label": f"{trait}变化" if self._is_zh_locale(locale) else f"{trait} changed",
                    "summary": (
                        f"{trait}从 {old_value} 变化为 {new_value}。"
                        if self._is_zh_locale(locale)
                        else f"{trait} changed from {old_value} to {new_value}."
                    ),
                    "timestamp": timestamp,
                    "anchor": {
                        "anchor_type": "state_transition",
                        "anchor_id": str(transition.get("new_assertion_id") or transition.get("old_assertion_id") or ""),
                        "time_start": timestamp,
                        "time_end": timestamp,
                    },
                }
            )
        return {
            "mood_label": mood_label,
            "stress_label": self._stress_label(stress_value, locale=locale),
            "engagement_label": self._engagement_label(engagement_value, locale=locale),
            "mood_value": mood_value,
            "stress_value": stress_value,
            "engagement_value": engagement_value,
            "notable_changes": notable_changes,
        }

    @staticmethod
    def _average_state_value(state_bands: list[dict[str, Any]], key: str) -> float | None:
        values = [float(band[key]) for band in state_bands if isinstance(band.get(key), (int, float))]
        if not values:
            return None
        return sum(values) / len(values)

    def _dominant_state_label(self, state_bands: list[dict[str, Any]], *, locale: str = "en") -> str:
        labels = [str(band.get("label") or "").strip() for band in state_bands if str(band.get("label") or "").strip()]
        if not labels:
            return "Unknown"
        return self._humanize_label(Counter(labels).most_common(1)[0][0], locale=locale)

    def _localize_cluster_labels(self, clusters: list[dict[str, Any]], *, locale: str) -> None:
        if not self._is_zh_locale(locale):
            return
        for cluster in clusters:
            label = str(cluster.get("label") or "").strip()
            if not label:
                continue
            source_candidates = [str(cluster.get("dominant_mode") or "")]
            source_candidates.extend(str(source) for source in cluster.get("source_types") or [])
            for source in source_candidates:
                if self._is_generated_source_label(label, source):
                    cluster["label"] = self._source_label(source, locale)
                    break

    @staticmethod
    def _is_generated_source_label(label: str, source_type: str) -> bool:
        normalized_label = TimelineViewportBuilder._normalize_display_text(label)
        normalized_source = TimelineViewportBuilder._normalize_display_text(source_type)
        return bool(normalized_label and normalized_label == normalized_source)

    @staticmethod
    def _normalize_display_text(value: Any) -> str:
        return " ".join(str(value or "").replace("_", " ").replace("-", " ").split()).lower()

    @staticmethod
    def _stress_label(value: float | None, *, locale: str = "en") -> str:
        zh = TimelineViewportBuilder._is_zh_locale(locale)
        if value is None:
            return "未知" if zh else "Unknown"
        if value >= 0.67:
            return "高压力" if zh else "High stress"
        if value >= 0.4:
            return "中等压力" if zh else "Moderate stress"
        return "低压力" if zh else "Low stress"

    @staticmethod
    def _engagement_label(value: float | None, *, locale: str = "en") -> str:
        zh = TimelineViewportBuilder._is_zh_locale(locale)
        if value is None:
            return "未知" if zh else "Unknown"
        if value >= 0.67:
            return "高参与度" if zh else "High engagement"
        if value >= 0.4:
            return "稳定参与" if zh else "Steady engagement"
        return "低参与度" if zh else "Low engagement"

    @staticmethod
    def _humanize_label(value: Any, *, locale: str = "en") -> str:
        text = str(value or "").replace("_", " ").replace("-", " ").strip()
        if not text:
            return "未知" if TimelineViewportBuilder._is_zh_locale(locale) else "Unknown"
        if TimelineViewportBuilder._is_zh_locale(locale):
            return _MOOD_LABELS_ZH.get(text.lower(), text)
        return text.title()

    @staticmethod
    def _localized_marker_label(value: Any, locale: str) -> str:
        text = str(value or "").strip()
        if TimelineViewportBuilder._is_zh_locale(locale) and text.lower() in {"state shift", "state changed"}:
            return "状态变化"
        return text or ("状态变化" if TimelineViewportBuilder._is_zh_locale(locale) else "State shift")

    @staticmethod
    def _normalize_locale(locale: str | None) -> str:
        return "zh-CN" if is_zh_language(locale, default="en") else "en"

    @staticmethod
    def _is_zh_locale(locale: str | None) -> bool:
        return is_zh_language(locale, default="en")

    @staticmethod
    def _source_label(source_type: Any, locale: str) -> str:
        source = str(source_type or "memory")
        if TimelineViewportBuilder._is_zh_locale(locale):
            return _SOURCE_LABELS_ZH.get(source, source.replace("_", " "))
        return source.replace("_", " ").title()

    def _build_theme_cards(
        self,
        *,
        reflections: list[dict[str, Any]],
        clusters: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        cards: list[dict[str, Any]] = []
        seen: set[tuple[str, str]] = set()
        for reflection in reflections:
            title = str(reflection.get("title") or "Reflection window")
            summary = str(reflection.get("summary") or "")
            key = (title, summary)
            if key in seen:
                continue
            seen.add(key)
            event_ids = [str(event_id) for event_id in reflection.get("source_event_ids") or [] if str(event_id).strip()]
            time_start = float(reflection.get("time_start") or 0.0)
            time_end = float(reflection.get("time_end") or time_start)
            cards.append(
                {
                    "theme_id": f"reflection:{reflection.get('reflection_id')}",
                    "title": title,
                    "summary": summary,
                    "source_types": self._source_types_for_event_ids(event_ids, clusters),
                    "event_count": len(event_ids),
                    "anchor": {
                        "anchor_type": "event" if event_ids else "reflection",
                        "anchor_id": event_ids[0] if event_ids else "",
                        "representative_event_ids": event_ids[:5],
                        "time_start": time_start,
                        "time_end": time_end,
                    },
                }
            )
            if len(cards) >= 6:
                return cards

        for cluster in sorted(clusters, key=lambda item: int(item.get("event_count") or 0), reverse=True):
            if len(cards) >= 6:
                break
            title = str(cluster.get("label") or "Activity")
            summary = str(cluster.get("summary") or "")
            key = (title, summary)
            if key in seen:
                continue
            seen.add(key)
            cards.append(
                {
                    "theme_id": str(cluster.get("block_id") or f"cluster:{len(cards)}"),
                    "title": title,
                    "summary": summary,
                    "source_types": [str(source) for source in cluster.get("source_types") or [] if str(source).strip()],
                    "event_count": int(cluster.get("event_count") or 0),
                    "anchor": self._cluster_anchor(cluster),
                }
            )
        return cards

    def _source_types_for_event_ids(self, event_ids: list[str], clusters: list[dict[str, Any]]) -> list[str]:
        event_id_set = set(event_ids)
        source_types: list[str] = []
        if not event_id_set:
            return source_types
        for cluster in clusters:
            representative_ids = {str(event_id) for event_id in cluster.get("representative_event_ids") or []}
            if not (representative_ids & event_id_set):
                continue
            source_types.extend(str(source) for source in cluster.get("source_types") or [] if str(source).strip())
        return list(dict.fromkeys(source_types))

    @staticmethod
    def _cluster_anchor(cluster: dict[str, Any]) -> dict[str, Any]:
        episode_id = str(cluster.get("episode_id") or "")
        representative_ids = [str(event_id) for event_id in cluster.get("representative_event_ids") or [] if str(event_id).strip()]
        if episode_id:
            anchor_type = "episode"
            anchor_id = f"episode:{episode_id}"
        elif representative_ids:
            anchor_type = "event"
            anchor_id = representative_ids[0]
        else:
            anchor_type = "cluster"
            anchor_id = ""
        return {
            "anchor_type": anchor_type,
            "anchor_id": anchor_id,
            "representative_event_ids": representative_ids[:5],
            "episode_id": episode_id or None,
            "time_start": float(cluster.get("time_start") or 0.0),
            "time_end": float(cluster.get("time_end") or cluster.get("time_start") or 0.0),
        }

    def _build_source_mix(
        self,
        *,
        events: list[dict[str, Any]],
        clusters: list[dict[str, Any]],
        locale: str = "en",
    ) -> list[dict[str, Any]]:
        event_counts: Counter[str] = Counter(self._event_source_type(event) for event in events)
        duration_seconds: defaultdict[str, float] = defaultdict(float)
        for cluster in clusters:
            sources = [str(source) for source in cluster.get("source_types") or [] if str(source).strip()]
            if not sources:
                continue
            share = float(cluster.get("duration_seconds") or 0.0) / max(1, len(sources))
            for source in sources:
                duration_seconds[source] += share

        source_types = set(event_counts) | set(duration_seconds)
        return [
            {
                "source_type": source_type,
                "label": self._source_label(source_type, locale),
                "event_count": int(event_counts.get(source_type, 0)),
                "duration_seconds": float(duration_seconds.get(source_type, 0.0)),
            }
            for source_type in sorted(
                source_types,
                key=lambda item: (-event_counts.get(item, 0), -duration_seconds.get(item, 0.0), item),
            )
        ]

    def _build_reflections(self, *, summaries: list[dict[str, Any]], start: float, end: float) -> list[dict[str, Any]]:
        reflections: list[dict[str, Any]] = []
        for summary in summaries:
            period_start = float(summary.get("period_start") or 0.0)
            period_end = float(summary.get("period_end") or period_start)
            if period_end < start or period_start > end:
                continue
            reflections.append(
                {
                    "reflection_id": str(summary.get("summary_id")),
                    "time_start": period_start,
                    "time_end": period_end,
                    "title": self._reflection_title(summary),
                    "summary": str(summary.get("content") or ""),
                    "key_topics": list(summary.get("key_topics") or []),
                    "key_entities": list(summary.get("key_entities") or []),
                    "sentiment_summary": summary.get("sentiment_summary"),
                    "change_and_pattern": summary.get("change_and_pattern"),
                    "source_summary_ids": [str(summary.get("summary_id"))],
                    "source_event_ids": list(summary.get("source_event_ids") or []),
                }
            )
        return reflections

    def _reflection_title(self, summary: dict[str, Any]) -> str:
        topics = summary.get("key_topics") or []
        if topics:
            return ", ".join(str(t) for t in topics[:3]).title()
        content = str(summary.get("content") or "")
        if content:
            first_sentence = content.split(".")[0].strip()
            if first_sentence and len(first_sentence) <= 60:
                return first_sentence
        category = str(summary.get("summary_category") or "window")
        return f"{category.title()} Reflection"

    def _to_raw_event(self, event: dict[str, Any]) -> dict[str, Any]:
        metadata = self._event_metadata(event)
        timeline = metadata.get("timeline") if isinstance(metadata.get("timeline"), dict) else {}
        return {
            "event_id": str(event.get("event_id")),
            "timestamp": float(event.get("timestamp") or 0.0),
            "title": str(timeline.get("title") or event.get("event_type") or event.get("event_id") or "Event"),
            "summary": str(timeline.get("summary") or event.get("content") or ""),
            "source_type": str(timeline.get("source_type") or event.get("source") or "memory"),
            "source_item_id": str(
                timeline.get("source_item_id")
                or event.get("source_item_id")
                or event.get("idempotency_key")
                or ""
            ),
        }

    def _event_source_type(self, event: dict[str, Any]) -> str:
        metadata = self._event_metadata(event)
        timeline = metadata.get("timeline") if isinstance(metadata.get("timeline"), dict) else {}
        return str(timeline.get("source_type") or event.get("source") or "memory")

    def _filter_events(
        self,
        events: list[dict[str, Any]],
        interpretation: TimelineQueryInterpretation,
    ) -> list[dict[str, Any]]:
        if not interpretation.has_filters:
            return events
        return [event for event in events if self._matches_text(self._event_search_text(event), interpretation)]

    def _filter_summaries(
        self,
        summaries: list[dict[str, Any]],
        interpretation: TimelineQueryInterpretation,
    ) -> list[dict[str, Any]]:
        if not interpretation.has_filters:
            return summaries
        return [summary for summary in summaries if self._matches_text(self._summary_search_text(summary), interpretation)]

    def _matches_text(self, text: str, interpretation: TimelineQueryInterpretation) -> bool:
        haystack = text.lower()

        for hint in interpretation.mood_hints:
            if not any(alias in haystack for alias in self._query_interpreter.expand_hint(hint)):
                return False

        for hint in interpretation.activity_hints:
            if not any(alias in haystack for alias in self._query_interpreter.expand_hint(hint)):
                return False

        for term in interpretation.residual_terms:
            if term not in haystack:
                return False

        return True

    @staticmethod
    def _event_search_text(event: dict[str, Any]) -> str:
        metadata = TimelineViewportBuilder._event_metadata(event)
        timeline = metadata.get("timeline") if isinstance(metadata.get("timeline"), dict) else {}
        parts: list[str] = [
            str(event.get("source") or ""),
            str(event.get("content") or ""),
            str(timeline.get("title") or ""),
            str(timeline.get("summary") or ""),
            " ".join(str(tag) for tag in timeline.get("tags", []) if str(tag).strip()),
        ]
        for entity in timeline.get("entities", []):
            if isinstance(entity, dict):
                parts.extend([str(entity.get("label") or ""), str(entity.get("id") or "")])
        return " ".join(part for part in parts if part).lower()

    @staticmethod
    def _event_metadata(event: dict[str, Any]) -> dict[str, Any]:
        metadata = event.get("metadata")
        if isinstance(metadata, dict):
            return metadata
        metadata_json = event.get("metadata_json")
        if isinstance(metadata_json, dict):
            return metadata_json
        return {}

    @staticmethod
    def _summary_search_text(summary: dict[str, Any]) -> str:
        parts: list[str] = [
            str(summary.get("content") or ""),
            " ".join(str(topic) for topic in summary.get("key_topics", []) if str(topic).strip()),
            json.dumps(summary.get("sentiment_summary") or {}, ensure_ascii=False),
            json.dumps(summary.get("change_and_pattern") or {}, ensure_ascii=False),
        ]
        for entity in summary.get("key_entities", []):
            if isinstance(entity, dict):
                parts.extend([str(entity.get("entity_id") or ""), str(entity.get("label") or "")])
            else:
                parts.append(str(entity))
        return " ".join(part for part in parts if part).lower()
