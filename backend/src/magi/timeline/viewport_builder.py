"""Scale-aware timeline viewport assembly."""

from __future__ import annotations

import json
from collections import Counter, defaultdict
from dataclasses import dataclass
from typing import Any

from magi.events.sensor_activity_snapshot import activity_snapshot_from_metadata
from magi.identity.defaults import CANONICAL_LOCAL_USER

from ..core.logger import get_logger
from ..memory.evidence import USER_VISIBLE_L1_RETRIEVAL_SCOPES
from .cluster_builder import TimelineClusterBuilder
from .context_bundle_builder import TimelineContextBundleBuilder
from .query_interpreter import TimelineQueryInterpretation, TimelineQueryInterpreter
from .state_band_builder import TimelineStateBandBuilder
from .viewport_clusters import TimelineClusterPresentationBuilder
from .viewport_experiences import TimelineExperienceLinker
from .viewport_i18n import is_zh_locale, normalize_locale, source_label, timeline_t
from .viewport_overview import TimelineOverviewBuilder
from .viewport_state_summary import TimelineStateSummaryBuilder
from .viewport_themes import ThemeCardBuilder

logger = get_logger("magi.timeline.viewport_builder")
_CANONICAL_SELF_ENTITY_ID = f"user:{CANONICAL_LOCAL_USER}"

# Upper bound on raw L1 events pulled per viewport window. Previously
# hardcoded at 500, which silently truncated power-user days (screen-time
# sensor at 1 event / 30s = 2880/day). 5000 covers the realistic worst
# case for a single day and is still cheap to pull from sqlite + send to
# the frontend. When we hit the cap we log a warning so it's visible in
# ops — the viewport itself doesn't surface this to the UI yet.
EVENT_QUERY_LIMIT = 5000


@dataclass(frozen=True)
class ViewportSourceData:
    events: list[dict[str, Any]]
    summaries: list[dict[str, Any]]
    assertions: list[dict[str, Any]]
    snapshots: list[dict[str, Any]]
    episodes: list[dict[str, Any]]


@dataclass(frozen=True)
class ViewportDerivedData:
    state_bands: list[dict[str, Any]]
    state_markers: list[dict[str, Any]]
    state_transitions: list[dict[str, Any]]
    reflections: list[dict[str, Any]]
    clusters: list[dict[str, Any]]
    raw_events: list[dict[str, Any]]
    source_mix: list[dict[str, Any]]
    theme_cards: list[dict[str, Any]]
    overview: dict[str, Any]
    state_summary: dict[str, Any]
    place_hints: list[str]


@dataclass(frozen=True)
class ViewportStateData:
    state_bands: list[dict[str, Any]]
    state_markers: list[dict[str, Any]]
    state_transitions: list[dict[str, Any]]
    state_summary: dict[str, Any]


@dataclass(frozen=True)
class ViewportActivityData:
    reflections: list[dict[str, Any]]
    clusters: list[dict[str, Any]]
    raw_events: list[dict[str, Any]]
    source_mix: list[dict[str, Any]]
    theme_cards: list[dict[str, Any]]
    overview: dict[str, Any]


class TimelineViewportBuilder:
    """Assemble scale-aware viewport payloads from memory layers."""

    def __init__(
        self,
        *,
        l1_store: Any,
        l2_store: Any | None = None,
        l3_store: Any | None = None,
        l4_store: Any | None = None,
        entity_catalog: Any | None = None,
        location_resolver: Any | None = None,
    ) -> None:
        self._l1 = l1_store
        self._l2 = l2_store
        self._l3 = l3_store
        self._l4 = l4_store
        # Optional entity catalog (L2EntityCatalog). When wired, themes are
        # derived from real entity canonical_names aggregated across the
        # window's episodes — concrete nouns the user actually touched,
        # rather than the L3 reflection insight_keys / cluster labels that
        # tend to leak internal machinery ("Day反思") or full summary
        # sentences into the chip slot.
        self._entity_catalog = entity_catalog
        # Optional LocationResolver. When wired, viewport responses include
        # ``place_hints`` (top labels for the period) which the Hero renders
        # as the "◦ 在 X" line. Without it we just omit the field.
        self._location_resolver = location_resolver
        self._state_band_builder = TimelineStateBandBuilder()
        self._state_summary_builder = TimelineStateSummaryBuilder()
        self._cluster_builder = TimelineClusterBuilder()
        self._cluster_presentation_builder = TimelineClusterPresentationBuilder()
        self._experience_linker = TimelineExperienceLinker(l2_store=l2_store)
        self._query_interpreter = TimelineQueryInterpreter()
        self._context_bundle_builder = TimelineContextBundleBuilder(
            l1_store=l1_store,
            l2_store=l2_store,
            l3_store=l3_store,
            l4_store=l4_store,
        )
        # Theme card assembly is split out to viewport_themes.py — see
        # that module for the priority order (entities → reflections →
        # cluster labels). Stateless across calls; constructed once with
        # the catalog reference.
        self._theme_card_builder = ThemeCardBuilder(entity_catalog=entity_catalog)
        self._overview_builder = TimelineOverviewBuilder(l3_store=l3_store)

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
        sources = await self._load_viewport_sources(scale=scale, query=interpreted_query)
        sources = self._filter_viewport_sources(sources, interpreted_query)
        derived = await self._derive_viewport_data(
            scale=scale,
            query=interpreted_query,
            sources=sources,
            locale=locale,
        )
        return self._build_viewport_response(
            scale=scale,
            query_text=query,
            timezone=timezone,
            focus=focus,
            locale=locale,
            query=interpreted_query,
            sources=sources,
            derived=derived,
        )

    async def _load_viewport_sources(
        self,
        *,
        scale: str,
        query: TimelineQueryInterpretation,
    ) -> ViewportSourceData:
        episodes = (
            await self._load_episodes(start=query.start, end=query.end)
            if scale in ("day", "week")
            else []
        )
        return ViewportSourceData(
            events=await self._load_events(start=query.start, end=query.end),
            summaries=await self._load_summaries(),
            assertions=await self._load_assertions(),
            snapshots=await self._load_snapshots(),
            episodes=episodes,
        )

    def _filter_viewport_sources(
        self,
        sources: ViewportSourceData,
        query: TimelineQueryInterpretation,
    ) -> ViewportSourceData:
        return ViewportSourceData(
            events=self._filter_events(sources.events, query),
            summaries=self._filter_summaries(sources.summaries, query),
            assertions=sources.assertions,
            snapshots=sources.snapshots,
            episodes=sources.episodes,
        )

    async def _derive_viewport_data(
        self,
        *,
        scale: str,
        query: TimelineQueryInterpretation,
        sources: ViewportSourceData,
        locale: str,
    ) -> ViewportDerivedData:
        state_data = self._derive_state_data(query=query, sources=sources, locale=locale)
        activity_data = await self._derive_activity_data(
            scale=scale,
            query=query,
            sources=sources,
            state_markers=state_data.state_markers,
            locale=locale,
        )
        return ViewportDerivedData(
            state_bands=state_data.state_bands,
            state_markers=state_data.state_markers,
            state_transitions=state_data.state_transitions,
            reflections=activity_data.reflections,
            clusters=activity_data.clusters,
            raw_events=activity_data.raw_events,
            source_mix=activity_data.source_mix,
            theme_cards=activity_data.theme_cards,
            overview=activity_data.overview,
            state_summary=state_data.state_summary,
            place_hints=await self._resolve_place_hints(start=query.start, end=query.end),
        )

    def _derive_state_data(
        self,
        *,
        query: TimelineQueryInterpretation,
        sources: ViewportSourceData,
        locale: str,
    ) -> ViewportStateData:
        state_bands, state_markers = self._state_band_builder.build(
            start=query.start,
            end=query.end,
            summaries=sources.summaries,
            assertions=sources.assertions,
            snapshots=sources.snapshots,
            locale=locale,
        )
        state_transitions = self._build_state_transitions(sources.assertions)
        state_summary = self._state_summary_builder.build(
            state_bands=state_bands,
            state_markers=state_markers,
            state_transitions=state_transitions,
            locale=locale,
        )
        return ViewportStateData(
            state_bands=state_bands,
            state_markers=state_markers,
            state_transitions=state_transitions,
            state_summary=state_summary,
        )

    async def _derive_activity_data(
        self,
        *,
        scale: str,
        query: TimelineQueryInterpretation,
        sources: ViewportSourceData,
        state_markers: list[dict[str, Any]],
        locale: str,
    ) -> ViewportActivityData:
        reflections = self._build_reflections(
            summaries=sources.summaries,
            start=query.start,
            end=query.end,
            locale=locale,
        )
        clusters = self._build_clusters_for_viewport(
            scale=scale,
            sources=sources,
            query=query,
            locale=locale,
        )
        if scale == "day":
            try:
                clusters = await self._experience_linker.decorate(
                    clusters,
                    start=query.start,
                    end=query.end,
                )
            except Exception as exc:
                logger.warning(
                    "Timeline experience decoration failed; rendering clusters without links",
                    error=str(exc),
                    scale=scale,
                    window_start=query.start,
                    window_end=query.end,
                )
        raw_events = self._build_raw_events_for_scale(scale, sources.events, locale=locale)
        source_mix = self._build_source_mix(
            events=sources.events,
            clusters=clusters,
            locale=locale,
        )
        theme_cards = await self._build_theme_cards(reflections, clusters, locale)
        overview = await self._build_activity_overview(
            scale=scale,
            query=query,
            sources=sources,
            reflections=reflections,
            clusters=clusters,
            raw_events=raw_events,
            state_markers=state_markers,
            source_mix=source_mix,
            locale=locale,
        )
        return ViewportActivityData(
            reflections=reflections,
            clusters=clusters,
            raw_events=raw_events,
            source_mix=source_mix,
            theme_cards=theme_cards,
            overview=overview,
        )

    async def _build_activity_overview(
        self,
        *,
        scale: str,
        query: TimelineQueryInterpretation,
        sources: ViewportSourceData,
        reflections: list[dict[str, Any]],
        clusters: list[dict[str, Any]],
        raw_events: list[dict[str, Any]],
        state_markers: list[dict[str, Any]],
        source_mix: list[dict[str, Any]],
        locale: str,
    ) -> dict[str, Any]:
        return await self._overview_builder.build(
            scale=scale,
            period_start=query.start,
            period_end=query.end,
            events=sources.events,
            clusters=clusters,
            reflections=reflections,
            raw_events=raw_events,
            state_markers=state_markers,
            source_mix=source_mix,
            locale=locale,
        )

    async def _build_theme_cards(
        self,
        reflections: list[dict[str, Any]],
        clusters: list[dict[str, Any]],
        locale: str,
    ) -> list[dict[str, Any]]:
        return await self._theme_card_builder.build(
            reflections=reflections,
            clusters=clusters,
            locale=locale,
        )

    def _build_clusters_for_viewport(
        self,
        *,
        scale: str,
        sources: ViewportSourceData,
        query: TimelineQueryInterpretation,
        locale: str,
    ) -> list[dict[str, Any]]:
        if scale == "hour":
            return []
        clusters = self._cluster_builder.build(
            sources.events,
            scale=scale,
            episodes=sources.episodes,
        )
        return self._cluster_presentation_builder.prepare(
            clusters,
            events=sources.events,
            summaries=sources.summaries,
            start=query.start,
            end=query.end,
            locale=locale,
        )

    def _build_raw_events_for_scale(
        self,
        scale: str,
        events: list[dict[str, Any]],
        *,
        locale: str,
    ) -> list[dict[str, Any]]:
        if scale != "hour":
            return []
        return [self._to_raw_event(event, locale=locale) for event in events]

    def _build_viewport_response(
        self,
        *,
        scale: str,
        query_text: str | None,
        timezone: str | None,
        focus: str,
        locale: str,
        query: TimelineQueryInterpretation,
        sources: ViewportSourceData,
        derived: ViewportDerivedData,
    ) -> dict[str, Any]:
        return {
            "viewport": {
                "scale": scale,
                "start": float(query.start),
                "end": float(query.end),
                "focus": focus,
                "query": query_text,
                "timezone": timezone,
                "locale": locale,
            },
            "summary": {
                "cluster_count": len(derived.clusters),
                "event_count": len(sources.events),
                "dominant_modes": [cluster["dominant_mode"] for cluster in derived.clusters[:3]],
            },
            "overview": derived.overview,
            "state_summary": derived.state_summary,
            "state_bands": derived.state_bands,
            "state_markers": derived.state_markers,
            "state_transitions": derived.state_transitions,
            "source_mix": derived.source_mix,
            "theme_cards": derived.theme_cards,
            "place_hints": derived.place_hints,
            "clusters": derived.clusters,
            "episodes": sources.episodes if scale in ("day", "week") else [],
            "reflections": derived.reflections if scale == "month" else [],
            "raw_events": derived.raw_events,
        }

    async def build_context_bundle(self, *, anchor: dict[str, Any]) -> dict[str, Any]:
        return await self._context_bundle_builder.build(anchor=anchor)

    async def _load_events(self, *, start: float, end: float) -> list[dict[str, Any]]:
        if self._l1 is None:
            return []
        events = await self._l1.query_events(
            start_time=start,
            end_time=end,
            limit=EVENT_QUERY_LIMIT,
            l1_retrieval_scopes=list(USER_VISIBLE_L1_RETRIEVAL_SCOPES),
        )
        # Surface truncation. When the result is exactly at the cap we
        # can't tell whether there's just barely enough or thousands more
        # past the limit; log loudly so it shows up in ops. A future
        # iteration could fold this into the viewport response (e.g.
        # `summary.events_truncated: true`) so the UI can flag it.
        if len(events) >= EVENT_QUERY_LIMIT:
            logger.warning(
                "Timeline viewport hit event-query limit; clusters and " "themes may be incomplete",
                limit=EVENT_QUERY_LIMIT,
                window_start=start,
                window_end=end,
                window_hours=round((end - start) / 3600, 1),
            )
        return events

    async def _resolve_place_hints(
        self,
        *,
        start: float,
        end: float,
    ) -> list[str]:
        """Ask LocationResolver for top labels covering the window.

        Returns an empty list when no resolver is wired (testing / partial
        bootstrap) or when no source produced a usable answer. Callers
        consume index 0 as the primary chip; the full list is available
        for secondary chip rendering.
        """
        if self._location_resolver is None:
            return []
        try:
            resolved = await self._location_resolver.resolve_dominant(
                time_start=start,
                time_end=end,
            )
        except Exception:  # pragma: no cover — defensive
            return []
        labels = [label for label in (resolved.labels or []) if label]
        if not labels and resolved.primary_label:
            labels = [resolved.primary_label]
        return labels

    async def _load_summaries(self) -> list[dict[str, Any]]:
        if self._l3 is None:
            return []
        return await self._l3.list_summaries(limit=200)

    async def _load_assertions(self) -> list[dict[str, Any]]:
        if self._l2 is None or not hasattr(self._l2, "list_tom_assertions"):
            return []
        return await self._l2.list_tom_assertions(entity_id=_CANONICAL_SELF_ENTITY_ID, limit=200)

    async def _load_snapshots(self) -> list[dict[str, Any]]:
        if self._l2 is None or not hasattr(self._l2, "list_tom_snapshots"):
            return []
        return await self._l2.list_tom_snapshots(entity_id=_CANONICAL_SELF_ENTITY_ID, limit=50)

    async def _load_episodes(self, *, start: float, end: float) -> list[dict[str, Any]]:
        """Load durable L2 episodes that overlap the viewport window.

        Includes ``candidate`` status so freshly-formed episodes show up
        before the promotion pipeline has run — without this, week-scale
        viewports fall back to transient single-event clustering and report
        "0s" duration chips for every day. Mirrors the orchestrator's
        ``statuses=["active", "candidate"]`` filter.
        """
        if self._l2 is None or not hasattr(self._l2, "list_episodes"):
            return []
        return await self._l2.list_episodes(
            statuses=["active", "candidate", "user_pinned"],
            time_start=start,
            time_end=end,
            limit=200,
        )

    def _build_state_transitions(self, assertions: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """Extract state transitions from superseded assertion chains."""
        transitions: list[dict[str, Any]] = []
        superseded = [
            a
            for a in assertions
            if str(a.get("status") or "") == "superseded" and a.get("superseded_by")
        ]
        active_by_id = {
            str(a.get("assertion_id")): a
            for a in assertions
            if str(a.get("status") or "") not in ("superseded", "archived", "expired")
        }
        for old in superseded:
            new_id = str(old.get("superseded_by") or "")
            new = active_by_id.get(new_id)
            transitions.append(
                {
                    "trait_name": str(old.get("trait_name") or ""),
                    "old_value": str(old.get("trait_value") or ""),
                    "new_value": str(new.get("trait_value") or "") if new else "",
                    "changed_at": float(old.get("superseded_at") or old.get("updated_at") or 0),
                    "old_assertion_id": str(old.get("assertion_id") or ""),
                    "new_assertion_id": new_id,
                }
            )
        transitions.sort(key=lambda t: t["changed_at"])
        return transitions

    @staticmethod
    def _normalize_locale(locale: str | None) -> str:
        return normalize_locale(locale)

    @staticmethod
    def _is_zh_locale(locale: str | None) -> bool:
        return is_zh_locale(locale)

    @staticmethod
    def _timeline_t(key: str, locale: str | None, *, fallback: str, **kwargs: Any) -> str:
        return timeline_t(key, locale, fallback=fallback, **kwargs)

    @staticmethod
    def _source_label(source_type: Any, locale: str) -> str:
        return source_label(source_type, locale)

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
            sources = [
                str(source) for source in cluster.get("source_types") or [] if str(source).strip()
            ]
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
                key=lambda item: (
                    -event_counts.get(item, 0),
                    -duration_seconds.get(item, 0.0),
                    item,
                ),
            )
        ]

    def _build_reflections(
        self, *, summaries: list[dict[str, Any]], start: float, end: float, locale: str
    ) -> list[dict[str, Any]]:
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
                    "title": self._reflection_title(summary, locale=locale),
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

    def _reflection_title(self, summary: dict[str, Any], *, locale: str) -> str:
        topics = summary.get("key_topics") or []
        if topics:
            return ", ".join(str(t) for t in topics[:3]).title()
        content = str(summary.get("content") or "")
        if content:
            first_sentence = content.split(".")[0].strip()
            if first_sentence and len(first_sentence) <= 60:
                return first_sentence
        category = str(summary.get("summary_category") or "window")
        return self._timeline_t(
            "theme.reflection_title",
            locale,
            fallback="{category} Reflection",
            category=category.title(),
        )

    def _to_raw_event(self, event: dict[str, Any], *, locale: str) -> dict[str, Any]:
        metadata = self._event_metadata(event)
        activity_snapshot = activity_snapshot_from_metadata(metadata)
        return {
            "event_id": str(event.get("event_id")),
            "timestamp": float(event.get("timestamp") or 0.0),
            "title": str(
                activity_snapshot.get("title")
                or event.get("event_type")
                or event.get("event_id")
                or self._timeline_t("raw_event.title", locale, fallback="Event")
            ),
            "summary": str(activity_snapshot.get("summary") or event.get("content") or ""),
            "source_type": str(
                activity_snapshot.get("source_type") or event.get("source") or "memory"
            ),
            "source_item_id": str(
                activity_snapshot.get("source_item_id")
                or event.get("source_item_id")
                or event.get("idempotency_key")
                or ""
            ),
        }

    def _event_source_type(self, event: dict[str, Any]) -> str:
        metadata = self._event_metadata(event)
        activity_snapshot = activity_snapshot_from_metadata(metadata)
        return str(activity_snapshot.get("source_type") or event.get("source") or "memory")

    def _filter_events(
        self,
        events: list[dict[str, Any]],
        interpretation: TimelineQueryInterpretation,
    ) -> list[dict[str, Any]]:
        if not interpretation.has_filters:
            return events
        return [
            event
            for event in events
            if self._matches_text(self._event_search_text(event), interpretation)
        ]

    def _filter_summaries(
        self,
        summaries: list[dict[str, Any]],
        interpretation: TimelineQueryInterpretation,
    ) -> list[dict[str, Any]]:
        if not interpretation.has_filters:
            return summaries
        return [
            summary
            for summary in summaries
            if self._matches_text(self._summary_search_text(summary), interpretation)
        ]

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
        activity_snapshot = activity_snapshot_from_metadata(metadata)
        parts: list[str] = [
            str(event.get("source") or ""),
            str(event.get("content") or ""),
            str(activity_snapshot.get("title") or ""),
            str(activity_snapshot.get("summary") or ""),
            " ".join(str(tag) for tag in activity_snapshot.get("tags", []) if str(tag).strip()),
        ]
        for entity in activity_snapshot.get("entities", []):
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
