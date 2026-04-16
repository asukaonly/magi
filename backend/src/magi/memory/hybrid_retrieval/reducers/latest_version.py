"""LatestVersionReducer — for current_state mode.

Returns the current state value with history context.
"""

from __future__ import annotations

from typing import Any

from ..evidence.base import EvidenceBundle, StateCardEvidence


class LatestVersionReducer:
    """Extract the latest state value with change history."""

    def reduce(self, evidence: EvidenceBundle) -> dict[str, Any]:
        if not isinstance(evidence, StateCardEvidence):
            return {"status": "not_found", "findings": []}

        if evidence.current is None:
            return {"status": "not_found", "findings": [], "insufficient_evidence": True}

        findings = [{
            "statement": f"{evidence.current.get('trait_name', '')}: {evidence.current.get('trait_value', '')}",
            "confidence": evidence.current.get("confidence", 0),
            "source_layer": "L2",
            "source_type": "state_assertion",
            "last_confirmed_at": evidence.current.get("last_confirmed_at"),
        }]

        if evidence.history:
            for h in evidence.history:
                findings.append({
                    "statement": f"Previously: {h.get('trait_value', '')}",
                    "confidence": h.get("confidence", 0),
                    "source_layer": "L2",
                    "source_type": "state_history",
                    "valid_from": h.get("valid_from"),
                    "valid_to": h.get("valid_to"),
                })

        status = "found" if evidence.current.get("confidence", 0) >= 0.3 else "ambiguous"

        return {
            "status": status,
            "summary": f"{evidence.current.get('trait_name', '')} is currently {evidence.current.get('trait_value', '')}",
            "findings": findings,
            "insufficient_evidence": False,
            "answering_hints": {
                "has_history": len(evidence.history) > 0,
                "history_count": len(evidence.history),
                "supporting_events": len(evidence.supporting_events),
            },
        }
