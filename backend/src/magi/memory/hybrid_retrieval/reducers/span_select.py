"""SpanSelectReducer — for exact_fact mode.

Selects the best fact span from FactCardEvidence.
"""

from __future__ import annotations

from typing import Any

from ..evidence.base import EvidenceBundle, FactCardEvidence


class SpanSelectReducer:
    """Select the most relevant fact spans from evidence."""

    def reduce(self, evidence: EvidenceBundle) -> dict[str, Any]:
        if not isinstance(evidence, FactCardEvidence):
            return {"status": "not_found", "findings": []}

        if not evidence.facts:
            return {"status": "not_found", "findings": []}

        findings = []
        for f in evidence.facts:
            findings.append({
                "statement": f.get("statement", ""),
                "confidence": f.get("confidence", 0),
                "source_layer": f.get("source_layer", ""),
                "source_type": f.get("source_type", ""),
                "updated_at": f.get("updated_at"),
            })

        best = evidence.facts[0]
        status = "found" if best.get("confidence", 0) >= 0.3 else "ambiguous"

        result: dict[str, Any] = {
            "status": status,
            "summary": best.get("statement", ""),
            "findings": findings,
            "insufficient_evidence": len(evidence.facts) == 0,
        }

        if evidence.entity_context:
            result["answering_hints"] = {
                "entity": evidence.entity_context.get("name", ""),
                "entity_type": evidence.entity_context.get("entity_type", ""),
            }

        return result
