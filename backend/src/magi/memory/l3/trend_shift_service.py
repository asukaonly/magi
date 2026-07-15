"""Builder for trend-shift driven L3 insights."""

from __future__ import annotations

import hashlib
import json

from ... import i18n as core_i18n
from ..l2.models import ReconciledTraitOutcome
from .insight_renderer import render_insight_content
from .insight_utils import (
    decode_value,
    locale_for_zh,
    trait_group,
    wants_zh,
)
from .models import L3Candidate, TrendShiftPacket

_MIN_TREND_EVIDENCE = 3
_MIN_TREND_HOURS = 24.0
_VOLATILE_STABILITY_KINDS = {"volatile_pattern", "volatile_state", "temporary_state"}
_INTEREST_TREND_GROUP = "interest_profile"
_TREND_POLICY = "trend_shift_gate_v4"


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

        content = self._render_trend_content(normalized_outcomes, user_lang_zh=wants_zh())
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
                "policy": _TREND_POLICY,
                "trend_groups": sorted({self._trend_group(outcome) for outcome in normalized_outcomes}),
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
            "trend_groups": sorted({self._trend_group(outcome) for outcome in outcomes}),
        }
        digest = hashlib.sha256(
            json.dumps(key_material, ensure_ascii=False, sort_keys=True).encode("utf-8")
        ).hexdigest()[:16]
        return f"trend_shift:{packet.entity_id}:{digest}"

    def _render_trend_content(
        self,
        outcomes: list[ReconciledTraitOutcome],
        *,
        user_lang_zh: bool,
    ) -> str | None:
        if outcomes and all(self._is_interest_outcome(outcome) for outcome in outcomes):
            return self._render_interest_trend_content(outcomes, zh=user_lang_zh)
        return render_insight_content(
            insight_kind="trend_shift",
            outcomes=outcomes,
            user_lang_zh=user_lang_zh,
        )

    def _render_interest_trend_content(
        self,
        outcomes: list[ReconciledTraitOutcome],
        *,
        zh: bool,
    ) -> str | None:
        values: list[str] = []
        for outcome in sorted(
            outcomes,
            key=lambda item: (-len(item.evidence_event_ids), str(item.winning_value).casefold()),
        ):
            value = str(decode_value(str(outcome.winning_value)) or "").strip()
            if not value or value.casefold() in {item.casefold() for item in values}:
                continue
            values.append(value)
            if len(values) >= 6:
                break
        if not values:
            return None
        joined = "、".join(values) if zh else ", ".join(values)
        if zh:
            fallback = f"最近持续关注：{joined}。"
        else:
            fallback = f"Sustained interest: {joined}."
        return core_i18n.t(
            "memory.l3.insight.trend.interest",
            language=locale_for_zh(zh),
            fallback=fallback,
            values=joined,
        )

    def _trend_group(self, outcome: ReconciledTraitOutcome) -> str:
        if self._is_interest_outcome(outcome):
            return _INTEREST_TREND_GROUP
        return trait_group(str(outcome.trait_name))

    def _is_interest_outcome(self, outcome: ReconciledTraitOutcome) -> bool:
        trait_name = str(outcome.trait_name or "").strip().lower()
        trait_family = str(outcome.trait_family or "").strip().lower()
        return trait_family == "preference_profile" and trait_name.startswith("interest.")

    def _outcome_metadata(self, outcome: ReconciledTraitOutcome) -> dict[str, object]:
        return {
            "trait_name": str(outcome.trait_name),
            "winning_value": decode_value(str(outcome.winning_value)),
            "status": str(outcome.status),
            "confidence": float(outcome.confidence),
            "evidence_count": len(outcome.evidence_event_ids),
            "time_span_hours": float(outcome.time_span_hours),
            "stability_kind": str(outcome.stability_kind),
            "entity_id": str(outcome.entity_id or ""),
            "source_assertion_id": str(outcome.source_assertion_id or ""),
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
