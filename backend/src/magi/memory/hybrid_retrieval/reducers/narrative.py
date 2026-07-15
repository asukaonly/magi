"""NarrativeReducer — for episode_recall mode.

Composes a chronological narrative from episode evidence.
"""

from __future__ import annotations

from typing import Any

from ..evidence.base import EpisodeBundleEvidence, EvidenceBundle


class NarrativeReducer:
    """Build a chronological narrative summary from episodes."""

    def reduce(self, evidence: EvidenceBundle) -> dict[str, Any]:
        if not isinstance(evidence, EpisodeBundleEvidence):
            return {"status": "not_found", "findings": []}

        if not evidence.episodes and not evidence.key_events:
            return {"status": "not_found", "findings": [], "insufficient_evidence": True}

        findings = []

        # Episode-level findings
        for ep in evidence.episodes:
            findings.append({
                "statement": ep.get("summary", ep.get("label", "")),
                "source_layer": "L2",
                "source_type": "episode",
                "episode_id": ep.get("episode_id", ""),
                "time_start": ep.get("time_start"),
                "time_end": ep.get("time_end"),
            })

        # Key event findings
        for evt in evidence.key_events:
            findings.append({
                "statement": evt.get("summary", ""),
                "source_layer": "L1",
                "source_type": "key_event",
                "event_id": evt.get("event_id", ""),
                "timestamp": evt.get("timestamp"),
                "episode_id": evt.get("episode_id", ""),
                "evidence_semantics": evt.get(
                    "evidence_semantics", "historical_record"
                ),
                "correction_status": evt.get("correction_status"),
            })

        # Build narrative summary
        summary_parts = []
        for ep in evidence.episodes:
            label = ep.get("label") or ep.get("summary", "")
            if label:
                summary_parts.append(label)
        if not summary_parts:
            for evt in evidence.key_events[:3]:
                s = evt.get("summary", "")
                if s:
                    summary_parts.append(s)

        summary = "; ".join(summary_parts) if summary_parts else ""
        status = "found" if findings else "not_found"

        result: dict[str, Any] = {
            "status": status,
            "summary": summary,
            "findings": findings,
            "insufficient_evidence": len(findings) == 0,
            "answering_hints": {
                "episode_count": len(evidence.episodes),
                "event_count": len(evidence.key_events),
                "event_semantics": "historical_record",
            },
        }

        if evidence.state_overlays:
            result["answering_hints"]["state_overlays"] = evidence.state_overlays

        return result
