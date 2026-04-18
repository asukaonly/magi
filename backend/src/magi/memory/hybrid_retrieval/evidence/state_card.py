"""StateCardAssembler — evidence for current_state mode."""

from __future__ import annotations

from typing import Any

from ..models import RetrievalPayload, RetrievalQuery
from .base import StateCardEvidence


class StateCardAssembler:
    """Assemble current state value + history chain."""

    def assemble(
        self,
        payload: RetrievalPayload,
        request: RetrievalQuery,
    ) -> StateCardEvidence:
        current: dict[str, Any] | None = None
        supporting_events: list[dict[str, Any]] = []
        history: list[dict[str, Any]] = []

        # 1. Active state assertions → current value (pick highest confidence)
        active_facts = sorted(
            payload.l2_state_facts,
            key=lambda f: float(f.get("confidence_score", 0)),
            reverse=True,
        )
        if active_facts:
            best = active_facts[0]
            current = {
                "trait_name": best.get("trait_name", ""),
                "trait_value": best.get("trait_value", ""),
                "confidence": float(best.get("confidence_score", 0)),
                "last_confirmed_at": best.get("last_validated_at"),
                "status": best.get("status", "active"),
                "assertion_id": best.get("assertion_id", ""),
            }

        # Fallback: if no state facts, try assertions
        if current is None and payload.l2_assertions:
            sorted_assertions = sorted(
                payload.l2_assertions,
                key=lambda a: float(a.get("confidence_score", 0)),
                reverse=True,
            )
            best = sorted_assertions[0]
            current = {
                "trait_name": best.get("trait_name", ""),
                "trait_value": best.get("trait_value", ""),
                "confidence": float(best.get("confidence_score", 0)),
                "last_confirmed_at": best.get("last_validated_at"),
                "status": best.get("status", "active"),
                "assertion_id": best.get("assertion_id", ""),
            }

        # 2. Supporting events from evidence_event_ids
        supporting_events = [
            {
                "event_id": evt.get("event_id", ""),
                "summary": evt.get("summary") or evt.get("content", "")[:200],
                "timestamp": evt.get("timestamp"),
            }
            for evt in payload.l1_events[:5]
        ]

        # 3. State history (supersession chain)
        for h in payload.l2_state_history:
            history.append({
                "trait_value": h.get("trait_value", ""),
                "valid_from": h.get("first_inferred_at"),
                "valid_to": h.get("superseded_at"),
                "status": h.get("status", ""),
                "confidence": float(h.get("confidence_score", 0)),
            })

        return StateCardEvidence(
            current=current,
            supporting_events=supporting_events,
            history=history,
        )
