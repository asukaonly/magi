"""Builder for L2 reconcile-driven L3 state-change insights."""

from __future__ import annotations

import hashlib
import json

from ..l2.models import ReconciledTraitOutcome
from .insight_utils import (
    compact_values,
    decode_value,
    normalized_value_for_key,
    state_change_phrase,
    trait_group,
    trait_group_label,
    trait_label,
    wants_zh,
)
from .models import L3Candidate, StateChangePacket

_TRANSITION_STATUSES = {"corroborated", "stable", "contradicted", "superseded", "user_rejected"}
_MIN_EMERGING_EVIDENCE = 3


class StateChangeService:
    """Converts reconcile outcomes into user-facing L3 insight candidates."""

    async def build_candidate(
        self,
        packet: StateChangePacket,
    ) -> L3Candidate | None:
        normalized_outcomes: list[ReconciledTraitOutcome] = []
        source_event_ids: list[str] = []

        for outcome in packet.outcomes:
            trait_name = str(outcome.trait_name or "").strip()
            winning_value = str(outcome.winning_value or "").strip()
            status = str(outcome.status or "").strip().lower()
            evidence_event_ids = [str(event_id).strip() for event_id in outcome.evidence_event_ids if str(event_id).strip()]
            if not trait_name or not winning_value or not status:
                continue
            if not evidence_event_ids:
                continue
            if not self._passes_generation_gate(outcome, evidence_event_ids):
                continue
            normalized_outcomes.append(outcome)
            for event_id in evidence_event_ids:
                if event_id not in source_event_ids:
                    source_event_ids.append(event_id)

        if not normalized_outcomes or not source_event_ids:
            return None

        content = self._render_content(packet, normalized_outcomes)

        # If every outcome carries an `expires_at`, the insight inherits the
        # latest expiry as its salience window. If any outcome has no expiry
        # (e.g. evidence_only or none decay policy), the insight stays salient
        # indefinitely — represented as None.
        expiries = [o.expires_at for o in normalized_outcomes]
        if expiries and all(e is not None for e in expiries):
            salience_until = max(float(e) for e in expiries if e is not None)
        else:
            salience_until = None

        return L3Candidate(
            summary_type="insight",
            summary_category="state_change",
            content=content,
            source_event_ids=source_event_ids,
            subtypes=["state_transition"],
            insight_key=self._build_insight_key(packet, normalized_outcomes),
            review_state="pending_confirmation",
            insight_metadata={
                "kind": "state_change",
                "policy": "state_change_gate_v3",
                "entity_id": packet.entity_id,
                "entity_type": packet.entity_type,
                "trigger_reason": packet.trigger_reason,
                "outcomes": [self._outcome_metadata(outcome) for outcome in normalized_outcomes],
                "salience_until": salience_until,
            },
        )

    def _passes_generation_gate(
        self,
        outcome: ReconciledTraitOutcome,
        evidence_event_ids: list[str],
    ) -> bool:
        status = str(outcome.status or "").strip().lower()
        evidence_count = len(evidence_event_ids)
        if status == "stable":
            return evidence_count >= 2 or float(outcome.time_span_hours or 0.0) >= 24.0
        if status in {"contradicted", "superseded", "user_rejected"}:
            return evidence_count >= 1
        if status in _TRANSITION_STATUSES:
            return evidence_count >= 1
        return evidence_count >= _MIN_EMERGING_EVIDENCE

    def _build_insight_key(
        self,
        packet: StateChangePacket,
        outcomes: list[ReconciledTraitOutcome],
    ) -> str:
        key_material = {
            "kind": "state_change",
            "entity_id": packet.entity_id,
            "trait_groups": sorted({trait_group(str(outcome.trait_name)) for outcome in outcomes}),
        }
        digest = hashlib.sha256(
            json.dumps(key_material, ensure_ascii=False, sort_keys=True).encode("utf-8")
        ).hexdigest()[:16]
        return f"state_change:{packet.entity_id}:{digest}"

    def _outcome_metadata(self, outcome: ReconciledTraitOutcome) -> dict[str, object]:
        return {
            "trait_name": str(outcome.trait_name),
            "winning_value": decode_value(str(outcome.winning_value)),
            "status": str(outcome.status),
            "confidence": float(outcome.confidence),
            "evidence_count": len(outcome.evidence_event_ids),
            "time_span_hours": float(outcome.time_span_hours),
            "stability_kind": str(outcome.stability_kind),
            "recommended_snapshot_field": str(outcome.recommended_snapshot_field),
        }

    def _render_content(
        self,
        packet: StateChangePacket,
        outcomes: list[ReconciledTraitOutcome],
    ) -> str:
        # Prefer the natural-language summaries that L2 already produced for
        # each underlying assertion. Each outcome carries `natural_summary`;
        # we keep up to three (matching the existing fragment cap below) and
        # join them with separators that read naturally in either language.
        zh = wants_zh()
        natural_fragments: list[str] = []
        for outcome in outcomes:
            summary = str(getattr(outcome, "natural_summary", "") or "").strip()
            if not summary:
                continue
            # Strip a trailing period so we can join cleanly; we'll add one back.
            summary = summary.rstrip("。.")
            if summary not in natural_fragments:
                natural_fragments.append(summary)

        if natural_fragments:
            joined = ("；" if zh else "; ").join(natural_fragments[:3])
            return f"{joined}。" if zh else f"{joined}."

        # Fallback: legacy deterministic template using trait labels.
        grouped: dict[str, list[ReconciledTraitOutcome]] = {}
        for outcome in outcomes:
            grouped.setdefault(str(outcome.trait_name), []).append(outcome)

        group_names = sorted({trait_group(str(outcome.trait_name)) for outcome in outcomes})
        group_subject = trait_group_label(group_names[0], zh=zh) if len(group_names) == 1 else None

        fragments: list[str] = []
        for trait_name, trait_outcomes in grouped.items():
            values = self._unique_values(trait_outcomes)
            statuses = sorted({str(outcome.status).lower() for outcome in trait_outcomes})
            readable_trait = trait_label(trait_name, zh=zh)
            readable_status = state_change_phrase(statuses, zh=zh)
            readable_values = compact_values(values, zh=zh)
            if zh:
                if group_subject == "音乐偏好" and readable_status in {"更明确", "比较稳定"}:
                    fragments.append(f"{readable_trait}包括 {readable_values}")
                else:
                    fragments.append(f"{readable_trait}{readable_status}：{readable_values}")
            else:
                fragments.append(f"{readable_trait} {readable_status}: {readable_values}")

        joined = "；".join(fragments[:3]) if zh else "; ".join(fragments[:3])
        if zh:
            if group_subject:
                return f"最近的记忆显示，用户的{group_subject}更清晰：{joined}。"
            return f"最近的记忆显示，用户状态有更新：{joined}。"
        return f"User state update for {packet.entity_id}: {joined}."

    def _unique_values(self, outcomes: list[ReconciledTraitOutcome]) -> list[object]:
        values: list[object] = []
        seen: set[str] = set()
        for outcome in outcomes:
            decoded = decode_value(str(outcome.winning_value))
            signature = normalized_value_for_key(str(outcome.winning_value))
            if signature in seen:
                continue
            seen.add(signature)
            values.append(decoded)
        return values
