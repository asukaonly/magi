"""Build self-focused state bands and markers for timeline viewport reads."""

from __future__ import annotations

from typing import Any


_TONE_TO_VALENCE = {
    "positive": 0.75,
    "warm": 0.65,
    "steady": 0.35,
    "neutral": 0.0,
    "cool": -0.25,
    "low": -0.45,
    "tense": -0.5,
    "anxious": -0.6,
    "negative": -0.75,
}

_TONE_TO_STRESS: dict[str, float] = {
    "positive": 0.2,
    "warm": 0.25,
    "steady": 0.3,
    "neutral": 0.35,
    "cool": 0.45,
    "low": 0.55,
    "tense": 0.7,
    "anxious": 0.8,
    "negative": 0.65,
}

_TONE_TO_ENGAGEMENT: dict[str, float] = {
    "positive": 0.7,
    "warm": 0.65,
    "steady": 0.55,
    "neutral": 0.4,
    "cool": 0.35,
    "low": 0.25,
    "tense": 0.6,
    "anxious": 0.55,
    "negative": 0.3,
}


def derive_state_from_tone(tone: str) -> dict[str, Any]:
    """Derive valence/stress/engagement from a sentiment tone label."""
    key = tone.strip().lower()
    return {
        "valence": _TONE_TO_VALENCE.get(key, 0.0),
        "stress": _TONE_TO_STRESS.get(key, 0.5),
        "engagement": _TONE_TO_ENGAGEMENT.get(key, 0.5),
        "label": key or "steady",
    }


class TimelineStateBandBuilder:
    """Derive coarse self-state ranges from L2 and L3 artifacts."""

    def build(
        self,
        *,
        start: float,
        end: float,
        summaries: list[dict[str, Any]],
        assertions: list[dict[str, Any]],
        snapshots: list[dict[str, Any]],
        locale: str = "en",
    ) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
        zh = locale.lower().startswith("zh")
        relevant_summaries = [
            summary
            for summary in summaries
            if float(summary.get("period_end") or 0.0) >= float(start)
            and float(summary.get("period_start") or 0.0) <= float(end)
        ]
        relevant_summaries.sort(key=lambda item: float(item.get("period_start") or 0.0))

        bands: list[dict[str, Any]] = []
        markers: list[dict[str, Any]] = []
        previous_band: dict[str, Any] | None = None

        for summary in relevant_summaries:
            summary_id = str(summary.get("summary_id") or "summary")
            period_start = float(summary.get("period_start") or start)
            period_end = float(summary.get("period_end") or period_start)
            overlapping_assertions = self._assertions_for_period(assertions, period_start, period_end)
            nearest_snapshot = self._nearest_snapshot(snapshots, period_start, period_end)
            sentiment_summary = summary.get("sentiment_summary") if isinstance(summary.get("sentiment_summary"), dict) else {}

            stress_level = self._resolve_stress_level(sentiment_summary, overlapping_assertions, nearest_snapshot)
            engagement = self._resolve_engagement(sentiment_summary, overlapping_assertions, nearest_snapshot)
            label = self._resolve_label(overlapping_assertions, nearest_snapshot, sentiment_summary)
            band = {
                "band_id": f"state-band:{summary_id}",
                "time_start": period_start,
                "time_end": period_end,
                "valence": self._resolve_valence(sentiment_summary, label),
                "stress_level": stress_level,
                "engagement": engagement,
                "confidence": self._resolve_confidence(overlapping_assertions),
                "label": label,
                "source_summary_ids": [summary_id],
                "source_assertion_ids": [
                    str(assertion.get("assertion_id"))
                    for assertion in overlapping_assertions
                    if assertion.get("assertion_id")
                ],
            }
            bands.append(band)

            if previous_band is not None and abs(float(previous_band["stress_level"]) - float(stress_level)) >= 0.25:
                changes = []
                change_and_pattern = summary.get("change_and_pattern")
                if isinstance(change_and_pattern, dict):
                    changes = [str(item) for item in change_and_pattern.get("changes", []) if str(item).strip()]
                markers.append(
                    {
                        "marker_id": f"state-marker:{summary_id}",
                        "timestamp": period_start,
                        "kind": "shift",
                        "label": "状态变化" if zh else "State shift",
                        "summary": changes[0] if changes else (
                            f"压力变化为 {stress_level:.2f}。" if zh else f"Stress changed to {stress_level:.2f}."
                        ),
                        "source_band_ids": [str(previous_band["band_id"]), band["band_id"]],
                        "source_summary_ids": [summary_id],
                    }
                )

            previous_band = band

        return bands, markers

    def _assertions_for_period(
        self,
        assertions: list[dict[str, Any]],
        period_start: float,
        period_end: float,
    ) -> list[dict[str, Any]]:
        _excluded_statuses = {"superseded", "archived", "expired", "user_rejected"}
        matches: list[dict[str, Any]] = []
        for assertion in assertions:
            if str(assertion.get("entity_id") or "") != "user:self":
                continue
            status = str(assertion.get("status") or assertion.get("validation_state") or "")
            if status in _excluded_statuses:
                continue
            first_inferred_at = float(assertion.get("first_inferred_at") or period_start)
            last_validated_at = float(assertion.get("last_validated_at") or first_inferred_at)
            if last_validated_at < period_start or first_inferred_at > period_end:
                continue
            matches.append(assertion)
        return matches

    def _nearest_snapshot(
        self,
        snapshots: list[dict[str, Any]],
        period_start: float,
        period_end: float,
    ) -> dict[str, Any] | None:
        matches = [
            snapshot
            for snapshot in snapshots
            if str(snapshot.get("entity_id") or "") == "user:self"
            and float(snapshot.get("last_updated_at") or 0.0) >= period_start
            and float(snapshot.get("last_updated_at") or 0.0) <= period_end
        ]
        if not matches:
            return None
        matches.sort(key=lambda item: float(item.get("last_updated_at") or 0.0))
        return matches[-1]

    def _resolve_stress_level(
        self,
        sentiment_summary: dict[str, Any],
        assertions: list[dict[str, Any]],
        snapshot: dict[str, Any] | None,
    ) -> float:
        if isinstance(sentiment_summary.get("stress_level"), (int, float)):
            return float(sentiment_summary["stress_level"])
        tone = str(sentiment_summary.get("tone") or "").strip().lower()
        if tone in _TONE_TO_STRESS:
            return _TONE_TO_STRESS[tone]
        for assertion in assertions:
            if str(assertion.get("trait_name") or "") == "stress_level":
                return self._coerce_float(assertion.get("trait_value"), default=0.5)
        if snapshot is not None:
            return self._coerce_float(snapshot.get("current_stress_level"), default=0.5)
        return 0.5

    def _resolve_engagement(
        self,
        sentiment_summary: dict[str, Any],
        assertions: list[dict[str, Any]],
        snapshot: dict[str, Any] | None,
    ) -> float:
        if isinstance(sentiment_summary.get("engagement"), (int, float)):
            return float(sentiment_summary["engagement"])
        tone = str(sentiment_summary.get("tone") or "").strip().lower()
        if tone in _TONE_TO_ENGAGEMENT:
            return _TONE_TO_ENGAGEMENT[tone]
        for assertion in assertions:
            if str(assertion.get("trait_name") or "") == "engagement":
                return self._coerce_float(assertion.get("trait_value"), default=0.5)
        if snapshot is not None:
            return self._coerce_float(snapshot.get("current_engagement"), default=0.5)
        return 0.5

    def _resolve_label(
        self,
        assertions: list[dict[str, Any]],
        snapshot: dict[str, Any] | None,
        sentiment_summary: dict[str, Any],
    ) -> str:
        for assertion in assertions:
            if str(assertion.get("trait_name") or "") == "mood":
                return str(assertion.get("trait_value") or "steady")
        if snapshot is not None and snapshot.get("current_mood"):
            return str(snapshot["current_mood"])
        tone = str(sentiment_summary.get("tone") or "").strip()
        return tone or "steady"

    def _resolve_valence(self, sentiment_summary: dict[str, Any], label: str) -> float:
        tone = str(sentiment_summary.get("tone") or "").strip().lower()
        if tone in _TONE_TO_VALENCE:
            return _TONE_TO_VALENCE[tone]
        return _TONE_TO_VALENCE.get(label.lower(), 0.0)

    def _resolve_confidence(self, assertions: list[dict[str, Any]]) -> float:
        if not assertions:
            return 0.45
        return max(float(assertion.get("confidence_score") or 0.0) for assertion in assertions)

    @staticmethod
    def _coerce_float(value: Any, *, default: float) -> float:
        try:
            return float(value)
        except (TypeError, ValueError):
            return float(default)

