"""Builder for trend-shift driven L3 insights."""

from __future__ import annotations

from .models import L3Candidate, TrendShiftPacket


class TrendShiftService:
    """Converts long-span reconcile outcomes into trend-shift insights."""

    async def build_candidate(
        self,
        packet: TrendShiftPacket,
    ) -> L3Candidate | None:
        source_event_ids: list[str] = []
        normalized_outcomes: list[dict[str, object]] = []

        for raw_outcome in packet.outcomes:
            trait_name = str(raw_outcome.get("trait_name") or "").strip()
            winning_value = str(raw_outcome.get("winning_value") or "").strip()
            status = str(raw_outcome.get("status") or "").strip()
            stability_kind = str(raw_outcome.get("stability_kind") or "").strip()
            time_span_hours = float(raw_outcome.get("time_span_hours") or 0.0)
            evidence_event_ids = [
                str(event_id).strip()
                for event_id in raw_outcome.get("evidence_event_ids", [])
                if str(event_id).strip()
            ]
            if not trait_name or not winning_value or not status or not evidence_event_ids:
                continue
            if time_span_hours < 24.0:
                continue
            normalized_outcomes.append(
                {
                    "trait_name": trait_name,
                    "winning_value": winning_value,
                    "status": status,
                    "stability_kind": stability_kind,
                    "time_span_hours": round(time_span_hours, 2),
                }
            )
            for event_id in evidence_event_ids:
                if event_id not in source_event_ids:
                    source_event_ids.append(event_id)

        if not normalized_outcomes or not source_event_ids:
            return None

        fragments = [self._render_outcome_fragment(item) for item in normalized_outcomes[:3]]
        content = (
            f"Longer-span evidence for {packet.entity_id} suggests a trend shift where "
            + "; ".join(fragment for fragment in fragments if fragment)
            + "."
        ).strip()
        return L3Candidate(
            summary_type="insight",
            summary_category="trend_shift",
            content=content,
            source_event_ids=source_event_ids,
            subtypes=["change_over_time"],
        )

    def _render_outcome_fragment(self, outcome: dict[str, object]) -> str:
        trait_name = str(outcome["trait_name"])
        winning_value = str(outcome["winning_value"])
        time_span_hours = float(outcome["time_span_hours"])
        stability_kind = str(outcome["stability_kind"] or "pattern")
        return (
            f"{trait_name} stayed aligned with {winning_value} across {time_span_hours:.1f} hours "
            f"as a {stability_kind}"
        )
