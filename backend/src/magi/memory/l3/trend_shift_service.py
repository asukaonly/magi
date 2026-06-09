"""Builder for trend-shift driven L3 insights."""

from __future__ import annotations

import hashlib
import json

from ..l2.models import ReconciledTraitOutcome
from .insight_renderer import render_insight_content
from .insight_utils import (
    decode_value,
    trait_group,
    wants_zh,
)
from .models import L3Candidate, TrendShiftPacket

_MIN_TREND_EVIDENCE = 3
_MIN_TREND_HOURS = 24.0
_VOLATILE_STABILITY_KINDS = {"volatile_pattern", "volatile_state", "temporary_state"}


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
            if not self._passes_generation_gate(outcome, evidence_event_ids):
                continue
            normalized_outcomes.append(outcome)
            for event_id in evidence_event_ids:
                if event_id not in source_event_ids:
                    source_event_ids.append(event_id)

        if not normalized_outcomes or not source_event_ids:
            return None

        content = render_insight_content(
            insight_kind="trend_shift",
            outcomes=normalized_outcomes,
            user_lang_zh=wants_zh(),
        )
        if content is None:
            return None
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
                "policy": "trend_shift_gate_v3",
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
            "trait_groups": sorted({trait_group(str(outcome.trait_name)) for outcome in outcomes}),
        }
        digest = hashlib.sha256(
            json.dumps(key_material, ensure_ascii=False, sort_keys=True).encode("utf-8")
        ).hexdigest()[:16]
        return f"trend_shift:{packet.entity_id}:{digest}"

    def _outcome_metadata(self, outcome: ReconciledTraitOutcome) -> dict[str, object]:
        return {
            "trait_name": str(outcome.trait_name),
            "winning_value": decode_value(str(outcome.winning_value)),
            "status": str(outcome.status),
            "confidence": float(outcome.confidence),
            "evidence_count": len(outcome.evidence_event_ids),
            "time_span_hours": float(outcome.time_span_hours),
            "stability_kind": str(outcome.stability_kind),
        }

    def _passes_generation_gate(
        self,
        outcome: ReconciledTraitOutcome,
        evidence_event_ids: list[str],
    ) -> bool:
        time_span_hours = float(outcome.time_span_hours or 0.0)
        stability_kind = str(outcome.stability_kind or "").strip().lower()
        if time_span_hours < _MIN_TREND_HOURS:
            return False
        if len(evidence_event_ids) < _MIN_TREND_EVIDENCE:
            return False
        return stability_kind not in _VOLATILE_STABILITY_KINDS

