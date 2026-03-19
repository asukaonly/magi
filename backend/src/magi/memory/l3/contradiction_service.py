"""Builder for contradiction-driven L3 conflict-resolution insights."""

from __future__ import annotations

from .models import ContradictionPacket, L3Candidate


class ContradictionInsightService:
    """Converts contradicted outcomes into user-facing L3 insight candidates."""

    async def build_candidate(
        self,
        packet: ContradictionPacket,
    ) -> L3Candidate | None:
        source_event_ids = [event_id for event_id in packet.source_event_ids if str(event_id).strip()]
        contradictions = [
            item
            for item in packet.contradictions
            if str(item.get("trait_name") or "").strip()
            and str(item.get("winning_value") or "").strip()
        ]
        if not source_event_ids or not contradictions:
            return None

        fragments = [self._render_contradiction_fragment(item) for item in contradictions[:3]]
        content = (
            "Contradiction resolution signals indicate that "
            + "; ".join(fragment for fragment in fragments if fragment)
            + "."
        ).strip()
        return L3Candidate(
            summary_type="insight",
            summary_category="conflict_resolution",
            content=content,
            source_event_ids=source_event_ids,
            subtypes=["contradiction_resolved"],
        )

    def _render_contradiction_fragment(self, contradiction: dict[str, object]) -> str:
        trait_name = str(contradiction["trait_name"])
        winning_value = str(contradiction["winning_value"])
        return f"{trait_name} now conflicts around {winning_value}"
