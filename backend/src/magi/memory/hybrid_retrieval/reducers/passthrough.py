"""PassthroughReducer — for summary/strategy modes.

Passes the raw payload through without transformation.
"""

from __future__ import annotations

from typing import Any

from ..evidence.base import EvidenceBundle, PassthroughEvidence


class PassthroughReducer:
    """No reduction; return the wrapped payload as findings."""

    def reduce(self, evidence: EvidenceBundle) -> dict[str, Any]:
        if not isinstance(evidence, PassthroughEvidence):
            return {"status": "not_found", "findings": []}

        return {
            "status": "found",
            "summary": "",
            "findings": [],
            "insufficient_evidence": False,
            "raw_payload": evidence.payload,
        }
