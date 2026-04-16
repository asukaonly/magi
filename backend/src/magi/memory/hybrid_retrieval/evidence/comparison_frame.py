"""ComparisonFrameAssembler — evidence for temporal_compare mode."""

from __future__ import annotations

from typing import Any

from ..models import RetrievalPayload, RetrievalQuery
from .base import ComparisonFrameEvidence


class ComparisonFrameAssembler:
    """Assemble a comparison frame between two temporal anchors."""

    def assemble(
        self,
        payload: RetrievalPayload,
        request: RetrievalQuery,
    ) -> ComparisonFrameEvidence:
        # Split state history into before/after anchors
        history = sorted(
            payload.l2_state_history,
            key=lambda h: float(h.get("first_inferred_at", 0) or 0),
        )

        if len(history) >= 2:
            anchor_a = _state_snapshot(history[0])
            anchor_b = _state_snapshot(history[-1])
        elif len(history) == 1:
            anchor_a = _state_snapshot(history[0])
            # Use current state as anchor_b
            active = payload.l2_state_facts
            anchor_b = _state_snapshot(active[0]) if active else {}
        else:
            # Fallback: use L1 events chronologically
            events = sorted(payload.l1_events, key=lambda e: float(e.get("timestamp", 0) or 0))
            anchor_a = _event_snapshot(events[0]) if len(events) > 0 else {}
            anchor_b = _event_snapshot(events[-1]) if len(events) > 1 else {}

        delta = _compute_delta(anchor_a, anchor_b)

        trajectory = [
            {
                "trait_value": h.get("trait_value", ""),
                "timestamp": h.get("first_inferred_at"),
                "confidence": float(h.get("confidence_score", 0)),
            }
            for h in history
        ]

        return ComparisonFrameEvidence(
            anchor_a=anchor_a,
            anchor_b=anchor_b,
            delta=delta,
            state_trajectory=trajectory,
        )


def _state_snapshot(record: dict[str, Any]) -> dict[str, Any]:
    return {
        "trait_name": record.get("trait_name", ""),
        "trait_value": record.get("trait_value", ""),
        "timestamp": record.get("first_inferred_at"),
        "confidence": float(record.get("confidence_score", 0)),
    }


def _event_snapshot(record: dict[str, Any]) -> dict[str, Any]:
    return {
        "summary": record.get("summary") or record.get("content", "")[:200],
        "timestamp": record.get("timestamp"),
        "event_id": record.get("event_id", ""),
    }


def _compute_delta(a: dict[str, Any], b: dict[str, Any]) -> dict[str, Any]:
    delta: dict[str, Any] = {}
    if a.get("trait_value") and b.get("trait_value"):
        delta["from"] = a.get("trait_value", "")
        delta["to"] = b.get("trait_value", "")
        delta["changed"] = a.get("trait_value") != b.get("trait_value")
    elif a.get("summary") and b.get("summary"):
        delta["from_summary"] = a.get("summary", "")
        delta["to_summary"] = b.get("summary", "")
        delta["changed"] = a.get("summary") != b.get("summary")
    return delta
