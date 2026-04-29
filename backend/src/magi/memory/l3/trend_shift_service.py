"""Builder for trend-shift driven L3 insights."""

from __future__ import annotations

import hashlib
import json

from ..l2.models import ReconciledTraitOutcome
from .models import L3Candidate, TrendShiftPacket


class TrendShiftService:
    """Converts long-span reconcile outcomes into trend-shift insights."""

    async def build_candidate(
        self,
        packet: TrendShiftPacket,
    ) -> L3Candidate | None:
        source_event_ids: list[str] = []
        normalized_outcomes: list[ReconciledTraitOutcome] = []

        for outcome in packet.outcomes:
            trait_name = str(outcome.trait_name or "").strip()
            winning_value = str(outcome.winning_value or "").strip()
            status = str(outcome.status or "").strip()
            time_span_hours = float(outcome.time_span_hours or 0.0)
            evidence_event_ids = [str(event_id).strip() for event_id in outcome.evidence_event_ids if str(event_id).strip()]
            if not trait_name or not winning_value or not status or not evidence_event_ids:
                continue
            if time_span_hours < 24.0:
                continue
            normalized_outcomes.append(outcome)
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
            insight_key=self._build_insight_key(packet, normalized_outcomes),
            review_state="pending_confirmation",
            insight_metadata={
                "kind": "trend_shift",
                "policy": "trend_shift_gate_v1",
                "entity_id": packet.entity_id,
                "entity_type": packet.entity_type,
                "trigger_reason": packet.trigger_reason,
                "outcomes": [self._outcome_metadata(outcome) for outcome in normalized_outcomes],
            },
        )

    def _build_insight_key(
        self,
        packet: TrendShiftPacket,
        outcomes: list[ReconciledTraitOutcome],
    ) -> str:
        key_material = {
            "kind": "trend_shift",
            "entity_id": packet.entity_id,
            "outcomes": sorted(
                [
                    {
                        "trait_name": str(outcome.trait_name).strip(),
                        "winning_value": self._normalize_value(str(outcome.winning_value)),
                    }
                    for outcome in outcomes
                ],
                key=lambda item: (str(item["trait_name"]), str(item["winning_value"])),
            ),
        }
        digest = hashlib.sha256(
            json.dumps(key_material, ensure_ascii=False, sort_keys=True).encode("utf-8")
        ).hexdigest()[:16]
        return f"trend_shift:{packet.entity_id}:{digest}"

    def _outcome_metadata(self, outcome: ReconciledTraitOutcome) -> dict[str, object]:
        return {
            "trait_name": str(outcome.trait_name),
            "winning_value": self._decode_value(str(outcome.winning_value)),
            "status": str(outcome.status),
            "confidence": float(outcome.confidence),
            "evidence_count": len(outcome.evidence_event_ids),
            "time_span_hours": float(outcome.time_span_hours),
            "stability_kind": str(outcome.stability_kind),
        }

    def _normalize_value(self, value: str) -> str:
        decoded = self._decode_value(value)
        return json.dumps(self._canonicalize(decoded), ensure_ascii=False, sort_keys=True, separators=(",", ":"))

    def _decode_value(self, value: str) -> object:
        try:
            return json.loads(value)
        except json.JSONDecodeError:
            return value

    def _canonicalize(self, value: object) -> object:
        if isinstance(value, str):
            return " ".join(value.casefold().split())
        if isinstance(value, list):
            return sorted(
                (self._canonicalize(item) for item in value),
                key=lambda item: json.dumps(item, ensure_ascii=False, sort_keys=True),
            )
        if isinstance(value, dict):
            return {str(key): self._canonicalize(item) for key, item in sorted(value.items())}
        return value

    def _render_outcome_fragment(self, outcome: ReconciledTraitOutcome) -> str:
        trait_name = str(outcome.trait_name)
        winning_value = str(outcome.winning_value)
        time_span_hours = float(outcome.time_span_hours)
        stability_kind = str(outcome.stability_kind or "pattern")
        return (
            f"{trait_name} stayed aligned with {winning_value} across {time_span_hours:.1f} hours "
            f"as a {stability_kind}"
        )
