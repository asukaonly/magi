"""State summary assembly for timeline viewports."""

from __future__ import annotations

from collections import Counter
from typing import Any

from .viewport_i18n import humanize_label, is_zh_locale, timeline_t


class TimelineStateSummaryBuilder:
    """Build the compact state summary block for a viewport response."""

    def build(
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
        notable_changes = self._notable_changes(
            state_markers=state_markers,
            state_transitions=state_transitions,
            locale=locale,
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

    def _notable_changes(
        self,
        *,
        state_markers: list[dict[str, Any]],
        state_transitions: list[dict[str, Any]],
        locale: str,
    ) -> list[dict[str, Any]]:
        changes = [self._marker_change(marker, locale=locale) for marker in state_markers[:3]]
        for transition in state_transitions:
            if len(changes) >= 3:
                break
            changes.append(self._transition_change(transition, locale=locale))
        return changes

    def _marker_change(
        self,
        marker: dict[str, Any],
        *,
        locale: str,
    ) -> dict[str, Any]:
        timestamp = float(marker.get("timestamp") or 0.0)
        return {
            "label": self._localized_marker_label(marker.get("label"), locale),
            "summary": str(
                marker.get("summary")
                or timeline_t(
                    "state.marker.default_summary",
                    locale,
                    fallback="状态发生变化。" if is_zh_locale(locale) else "State changed.",
                )
            ),
            "timestamp": timestamp,
            "anchor": {
                "anchor_type": "state_marker",
                "anchor_id": str(marker.get("marker_id") or ""),
                "time_start": timestamp,
                "time_end": timestamp,
            },
        }

    def _transition_change(
        self,
        transition: dict[str, Any],
        *,
        locale: str,
    ) -> dict[str, Any]:
        trait = humanize_label(transition.get("trait_name"), locale=locale)
        old_value = str(transition.get("old_value") or "unknown")
        new_value = str(transition.get("new_value") or "unknown")
        timestamp = float(transition.get("changed_at") or 0.0)
        return {
            "label": self._transition_label(trait, locale=locale),
            "summary": self._transition_summary(
                trait=trait,
                old_value=old_value,
                new_value=new_value,
                locale=locale,
            ),
            "timestamp": timestamp,
            "anchor": {
                "anchor_type": "state_transition",
                "anchor_id": str(
                    transition.get("new_assertion_id") or transition.get("old_assertion_id") or ""
                ),
                "time_start": timestamp,
                "time_end": timestamp,
            },
        }

    @staticmethod
    def _transition_label(trait: str, *, locale: str) -> str:
        return timeline_t(
            "state.transition.label",
            locale,
            fallback="{trait}变化" if is_zh_locale(locale) else "{trait} changed",
            trait=trait,
        )

    @staticmethod
    def _transition_summary(
        *,
        trait: str,
        old_value: str,
        new_value: str,
        locale: str,
    ) -> str:
        return timeline_t(
            "state.transition.summary",
            locale,
            fallback=(
                "{trait}从 {old_value} 变化为 {new_value}。"
                if is_zh_locale(locale)
                else "{trait} changed from {old_value} to {new_value}."
            ),
            trait=trait,
            old_value=old_value,
            new_value=new_value,
        )

    @staticmethod
    def _average_state_value(state_bands: list[dict[str, Any]], key: str) -> float | None:
        values = [
            float(band[key]) for band in state_bands if isinstance(band.get(key), (int, float))
        ]
        if not values:
            return None
        return sum(values) / len(values)

    @staticmethod
    def _dominant_state_label(state_bands: list[dict[str, Any]], *, locale: str = "en") -> str:
        labels = [
            str(band.get("label") or "").strip()
            for band in state_bands
            if str(band.get("label") or "").strip()
        ]
        if not labels:
            return timeline_t(
                "state.unknown",
                locale,
                fallback="未知" if is_zh_locale(locale) else "Unknown",
            )
        return humanize_label(Counter(labels).most_common(1)[0][0], locale=locale)

    @staticmethod
    def _stress_label(value: float | None, *, locale: str = "en") -> str:
        zh = is_zh_locale(locale)
        if value is None:
            return timeline_t("state.stress.unknown", locale, fallback="未知" if zh else "Unknown")
        if value >= 0.67:
            return timeline_t(
                "state.stress.high", locale, fallback="高压力" if zh else "High stress"
            )
        if value >= 0.4:
            return timeline_t(
                "state.stress.moderate", locale, fallback="中等压力" if zh else "Moderate stress"
            )
        return timeline_t("state.stress.low", locale, fallback="低压力" if zh else "Low stress")

    @staticmethod
    def _engagement_label(value: float | None, *, locale: str = "en") -> str:
        zh = is_zh_locale(locale)
        if value is None:
            return timeline_t(
                "state.engagement.unknown", locale, fallback="未知" if zh else "Unknown"
            )
        if value >= 0.67:
            return timeline_t(
                "state.engagement.high", locale, fallback="高参与度" if zh else "High engagement"
            )
        if value >= 0.4:
            return timeline_t(
                "state.engagement.steady",
                locale,
                fallback="稳定参与" if zh else "Steady engagement",
            )
        return timeline_t(
            "state.engagement.low", locale, fallback="低参与度" if zh else "Low engagement"
        )

    @staticmethod
    def _localized_marker_label(value: Any, locale: str) -> str:
        text = str(value or "").strip()
        if is_zh_locale(locale) and text.lower() in {"state shift", "state changed"}:
            return timeline_t("state.shift", locale, fallback="状态变化")
        return text or timeline_t(
            "state.shift",
            locale,
            fallback="状态变化" if is_zh_locale(locale) else "State shift",
        )
