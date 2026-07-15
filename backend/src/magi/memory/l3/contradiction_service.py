"""Builder for contradiction-driven L3 conflict-resolution insights."""

from __future__ import annotations

import hashlib
import json

from .insight_renderer import render_insight_content
from .insight_utils import wants_zh
from .models import ContradictionPacket, L3Candidate


class ContradictionInsightService:
    """Converts contradicted outcomes into user-facing L3 insight candidates."""

    async def build_candidate(
        self,
        packet: ContradictionPacket,
    ) -> L3Candidate | None:
        source_event_ids = [
            str(event_id).strip()
            for event_id in packet.source_event_ids
            if str(event_id).strip()
        ]
        outcomes = [
            outcome for outcome in packet.outcomes
            if str(outcome.trait_name or "").strip()
            and str(outcome.winning_value or "").strip()
        ]
        if not source_event_ids or not outcomes:
            return None

        content = render_insight_content(
            insight_kind="conflict_resolution",
            outcomes=outcomes,
            user_lang_zh=wants_zh(),
        )
        if content is None:
            return None

        return L3Candidate(
            summary_type="insight",
            summary_category="conflict_resolution",
            content=content,
            source_event_ids=source_event_ids,
            subtypes=["contradiction_resolved"],
            insight_key=self._build_insight_key(outcomes),
            review_state="pending_confirmation",
            insight_metadata={
                "kind": "conflict_resolution",
                "policy": "conflict_resolution_gate_v2",
                "trigger_reason": packet.trigger_reason,
                "outcomes": [self._outcome_metadata(outcome) for outcome in outcomes],
            },
        )

    def _build_insight_key(self, outcomes: list) -> str:
        key_material = sorted(
            [
                {
                    "trait_name": str(outcome.trait_name or "").strip(),
                    "winning_value": self._normalize_value(str(outcome.winning_value or "")),
                }
                for outcome in outcomes
            ],
            key=lambda item: (str(item["trait_name"]), str(item["winning_value"])),
        )
        digest = hashlib.sha256(
            json.dumps(key_material, ensure_ascii=False, sort_keys=True).encode("utf-8")
        ).hexdigest()[:16]
        return f"conflict_resolution:{digest}"

    def _normalize_value(self, value: str) -> str:
        try:
            decoded = json.loads(value)
        except json.JSONDecodeError:
            decoded = value
        if isinstance(decoded, str):
            decoded = " ".join(decoded.casefold().split())
        return json.dumps(decoded, ensure_ascii=False, sort_keys=True, separators=(",", ":"))

    def _outcome_metadata(self, outcome) -> dict[str, object]:
        return {
            "trait_name": str(outcome.trait_name),
            "winning_value": str(outcome.winning_value),
            "status": str(outcome.status),
            "trait_family": str(outcome.trait_family or ""),
            "entity_id": str(outcome.entity_id or ""),
            "source_assertion_id": str(outcome.source_assertion_id or ""),
        }
