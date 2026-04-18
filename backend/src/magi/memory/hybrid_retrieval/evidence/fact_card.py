"""FactCardAssembler — evidence for exact_fact mode."""

from __future__ import annotations

from typing import Any

from ..models import RetrievalPayload, RetrievalQuery
from .base import FactCardEvidence


class FactCardAssembler:
    """Assemble high-precision fact cards from L2 semantic + L1 data."""

    def assemble(
        self,
        payload: RetrievalPayload,
        request: RetrievalQuery,
    ) -> FactCardEvidence:
        facts: list[dict[str, Any]] = []

        # 1. KG edges as facts
        for rel in payload.l2_relationships:
            facts.append({
                "statement": rel.get("natural_summary") or f"{rel.get('subject_id', '')} {rel.get('predicate', '')} {rel.get('object_id', '')}",
                "confidence": float(rel.get("confidence", 0)),
                "source_layer": "L2",
                "source_type": "kg_edge",
                "evidence_ref_ids": _parse_list(rel.get("evidence_event_ids")),
                "updated_at": rel.get("updated_at"),
            })

        # 2. Assertions as facts (semantic subdomain preferred)
        for assertion in payload.l2_assertions:
            facts.append({
                "statement": f"{assertion.get('trait_name', '')}: {assertion.get('trait_value', '')}",
                "confidence": float(assertion.get("confidence_score", 0)),
                "source_layer": "L2",
                "source_type": "assertion",
                "evidence_ref_ids": _parse_list(assertion.get("evidence_events")),
                "updated_at": assertion.get("updated_at"),
            })

        # 3. State facts if present
        for sf in payload.l2_state_facts:
            facts.append({
                "statement": f"{sf.get('trait_name', '')}: {sf.get('trait_value', '')}",
                "confidence": float(sf.get("confidence_score", 0)),
                "source_layer": "L2",
                "source_type": "state_fact",
                "evidence_ref_ids": _parse_list(sf.get("evidence_events")),
                "updated_at": sf.get("updated_at"),
            })

        # 4. L1 events as supporting facts
        for evt in payload.l1_events:
            facts.append({
                "statement": evt.get("summary") or evt.get("content", "")[:200],
                "confidence": float(evt.get("retrieval_score", 0)),
                "source_layer": "L1",
                "source_type": "event",
                "evidence_ref_ids": [evt.get("event_id", "")],
                "updated_at": evt.get("timestamp"),
            })

        # Rank by confidence × freshness, keep top items
        facts.sort(key=lambda f: f.get("confidence", 0), reverse=True)
        top_facts = facts[:10]

        # Entity context from entity cards
        entity_context = payload.l2_entity_cards[0] if payload.l2_entity_cards else None

        return FactCardEvidence(facts=top_facts, entity_context=entity_context)


def _parse_list(value: Any) -> list[str]:
    """Parse a JSON list or comma-separated string into a list of strings."""
    if isinstance(value, list):
        return [str(v) for v in value]
    if isinstance(value, str):
        import json

        try:
            parsed = json.loads(value)
            if isinstance(parsed, list):
                return [str(v) for v in parsed]
        except (json.JSONDecodeError, TypeError):
            pass
        return [v.strip() for v in value.split(",") if v.strip()]
    return []
