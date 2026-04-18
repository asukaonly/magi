"""AnchorCompareReducer — for temporal_compare mode.

Generates a comparison result between two temporal anchors.
"""

from __future__ import annotations

from typing import Any

from ..evidence.base import ComparisonFrameEvidence, EvidenceBundle


class AnchorCompareReducer:
    """Compare two temporal anchors and produce a delta summary."""

    def reduce(self, evidence: EvidenceBundle) -> dict[str, Any]:
        if not isinstance(evidence, ComparisonFrameEvidence):
            return {"status": "not_found", "findings": []}

        if not evidence.anchor_a and not evidence.anchor_b:
            return {"status": "not_found", "findings": [], "insufficient_evidence": True}

        findings = []

        if evidence.anchor_a:
            findings.append({
                "statement": _snapshot_label(evidence.anchor_a, "before"),
                "source_layer": "L2",
                "source_type": "anchor_a",
                **evidence.anchor_a,
            })

        if evidence.anchor_b:
            findings.append({
                "statement": _snapshot_label(evidence.anchor_b, "after"),
                "source_layer": "L2",
                "source_type": "anchor_b",
                **evidence.anchor_b,
            })

        for step in evidence.state_trajectory:
            findings.append({
                "statement": f"→ {step.get('trait_value', '')} (confidence {step.get('confidence', 0):.2f})",
                "source_layer": "L2",
                "source_type": "trajectory_step",
                "timestamp": step.get("timestamp"),
            })

        changed = evidence.delta.get("changed", False)
        if changed:
            from_v = evidence.delta.get("from") or evidence.delta.get("from_summary", "")
            to_v = evidence.delta.get("to") or evidence.delta.get("to_summary", "")
            summary = f"Changed from '{from_v}' to '{to_v}'"
        else:
            summary = "No change detected between the two points"

        status = "found" if findings else "not_found"

        return {
            "status": status,
            "summary": summary,
            "findings": findings,
            "insufficient_evidence": len(findings) == 0,
            "answering_hints": {
                "changed": changed,
                "trajectory_length": len(evidence.state_trajectory),
            },
        }


def _snapshot_label(snapshot: dict[str, Any], label: str) -> str:
    if "trait_value" in snapshot:
        return f"{label}: {snapshot.get('trait_name', '')} = {snapshot.get('trait_value', '')}"
    if "summary" in snapshot:
        return f"{label}: {snapshot.get('summary', '')}"
    return f"{label}: (no data)"
