"""Builder for L2 reconcile-driven L3 state-change insights."""

from __future__ import annotations

from ..l2.models import ReconciledTraitOutcome
from .models import L3Candidate, StateChangePacket


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
            status = str(outcome.status or "").strip()
            evidence_event_ids = [str(event_id).strip() for event_id in outcome.evidence_event_ids if str(event_id).strip()]
            if not trait_name or not winning_value or not status:
                continue
            if not evidence_event_ids:
                continue
            normalized_outcomes.append(outcome)
            for event_id in evidence_event_ids:
                if event_id not in source_event_ids:
                    source_event_ids.append(event_id)

        if not normalized_outcomes or not source_event_ids:
            return None

        fragments = [
            self._render_outcome_fragment(outcome)
            for outcome in normalized_outcomes[:3]
        ]
        content = (
            f"Reconciled state changes for {packet.entity_id} indicate that "
            + "; ".join(fragment for fragment in fragments if fragment)
            + "."
        ).strip()
        return L3Candidate(
            summary_type="insight",
            summary_category="state_change",
            content=content,
            source_event_ids=source_event_ids,
            subtypes=["state_transition"],
        )

    def _render_outcome_fragment(self, outcome: ReconciledTraitOutcome) -> str:
        trait_name = str(outcome.trait_name)
        winning_value = str(outcome.winning_value)
        status = str(outcome.status)
        if status == "stable":
            return f"{trait_name} has stabilized around {winning_value}"
        if status == "corroborated":
            return f"{trait_name} is corroborated as {winning_value}"
        if status == "contradicted":
            return f"{trait_name} is now conflicted around {winning_value}"
        return f"{trait_name} currently points to {winning_value}"
