"""EnumerateReducer — for cross_session mode.

Lists grouped evidence items with dedup.
"""

from __future__ import annotations

from typing import Any

from ..evidence.base import EvidenceBundle, GroupedListEvidence


class EnumerateReducer:
    """Enumerate grouped evidence with counts."""

    def reduce(self, evidence: EvidenceBundle) -> dict[str, Any]:
        if not isinstance(evidence, GroupedListEvidence):
            return {"status": "not_found", "findings": []}

        if not evidence.groups:
            return {"status": "not_found", "findings": [], "insufficient_evidence": True}

        findings = []
        for grp in evidence.groups:
            entity = grp.get("entity", "")
            items = grp.get("items", [])
            count = grp.get("count", 0)
            findings.append({
                "statement": f"{entity}: {count} mention(s)",
                "source_layer": "multi",
                "source_type": "group",
                "group_entity": entity,
                "group_size": count,
                "items": items[:5],
            })

        # Summary line
        group_names = [g.get("entity", "") for g in evidence.groups[:5]]
        summary = f"Found {evidence.total_matches} item(s) across groups: {', '.join(group_names)}"
        status = "found" if evidence.total_matches > 0 else "not_found"

        return {
            "status": status,
            "summary": summary,
            "findings": findings,
            "insufficient_evidence": evidence.total_matches == 0,
            "answering_hints": {
                "total_matches": evidence.total_matches,
                "group_count": len(evidence.groups),
            },
        }
