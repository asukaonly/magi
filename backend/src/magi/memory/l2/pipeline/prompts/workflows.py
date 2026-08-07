"""Prompt templates for auxiliary L2 workflow LLM calls."""

from __future__ import annotations

import json

from ...models import (
    L2BatchEntityResolutionItem,
    L2EntityCandidate,
    L2EntityResolutionMention,
    L2ReconcileAssertion,
    L2ReconcileEntity,
    L2ReconcileGraphFact,
    L2SourceEvent,
)


ENTITY_RESOLUTION_SYSTEM_PROMPT = """You are an entity resolution engine for a memory graph.

Your job is to determine whether a mention refers to one of the provided candidate entities.
Be conservative:
- Prefer unresolved over guessing.
- Use local context, aliases, semantics, and common nicknames.
- Do not create a new fact beyond identity resolution.
- Return JSON only.
"""

ENTITY_RECONCILE_SYSTEM_PROMPT = """You are an entity-level reconciliation engine for a memory system.

Your job is to review multiple evidence-bound records for the same entity and estimate which candidate traits are currently supported, contradicted, unstable, or still uncertain.
Be conservative:
- Respect evidence count and time span.
- Do not overfit to a single recent statement if long-term evidence disagrees.
- Separate stable traits from temporary states.
- Return JSON only.
"""

BATCH_ENTITY_RESOLUTION_SYSTEM_PROMPT = """You are an entity resolution engine for a memory graph.

Your job is to determine, for EACH mention in the batch, whether it refers to one of its provided candidate entities.
Be conservative:
- Prefer unresolved over guessing.
- Use local context, aliases, semantics, and common nicknames.
- Do not create a new fact beyond identity resolution.
- Return JSON only.
"""


def render_entity_resolution_prompt(
    *,
    mention: L2EntityResolutionMention,
    candidate_entities: list[L2EntityCandidate],
) -> str:
    return (
        "Resolve the entity mention to one of the candidate canonical entities if possible.\n\n"
        f"Mention:\n{json.dumps(mention.to_dict(), ensure_ascii=False, indent=2)}\n\n"
        f"Candidate entities:\n{json.dumps([item.to_dict() for item in candidate_entities], ensure_ascii=False, indent=2)}\n\n"
        "Return JSON with this schema:\n"
        '{\n  "resolution": {\n    "decision": "match|unresolved|create_new_candidate",\n    "matched_entity_id": "string or null",\n'
        '    "matched_entity_name": "string or null",\n    "confidence": 0.0,\n    "reason_tags": ["string"],\n'
        '    "should_merge": true,\n    "canonical_name_suggestion": "string or null"\n  }\n}'
    )


def render_batch_entity_resolution_prompt(
    *,
    items: list[L2BatchEntityResolutionItem],
) -> str:
    items_payload = [item.to_dict() for item in items]
    return (
        "Resolve each entity mention to one of its candidate canonical entities if possible.\n\n"
        f"Mentions to resolve:\n{json.dumps(items_payload, ensure_ascii=False, indent=2)}\n\n"
        "Return JSON with this schema:\n"
        '{\n  "resolutions": [\n    {\n      "mention_key": "string (echo back the mention_key)",\n'
        '      "decision": "match|unresolved|create_new_candidate",\n      "matched_entity_id": "string or null",\n'
        '      "matched_entity_name": "string or null",\n      "confidence": 0.0,\n      "reason_tags": ["string"],\n'
        '      "should_merge": true,\n      "canonical_name_suggestion": "string or null"\n    }\n  ]\n}'
    )


def render_entity_reconcile_prompt(
    *,
    entity: L2ReconcileEntity,
    graph_facts: list[L2ReconcileGraphFact],
    assertions: list[L2ReconcileAssertion],
    recent_events: list[L2SourceEvent],
) -> str:
    return (
        "Reconcile the following evidence for one entity.\n\n"
        f"Entity:\n{json.dumps(entity.to_dict(), ensure_ascii=False, indent=2)}\n\n"
        f"Related graph facts:\n{json.dumps([item.to_dict() for item in graph_facts], ensure_ascii=False, indent=2)}\n\n"
        f"Related assertion candidates:\n{json.dumps([item.to_dict() for item in assertions], ensure_ascii=False, indent=2)}\n\n"
        f"Recent events:\n{json.dumps([item.to_dict() for item in recent_events], ensure_ascii=False, indent=2)}\n\n"
        "Return JSON with this schema. evidence_event_ids must contain bare ULIDs only "
        "— copy the value inside [#...] from the input verbatim, without any 'event:' or '#' prefix.\n"
        '{\n  "reconciled_traits": [\n    {\n      "trait_name": "string",\n      "winning_value": "string or JSON string",\n'
        '      "status": "stable|corroborated|tentative|contradicted|expired",\n      "confidence": 0.0,\n      "evidence_event_ids": ["string"],\n'
        '      "time_span_hours": 0.0,\n      "stability_kind": "stable_trait|temporary_state|volatile_pattern",\n'
        '      "recommended_snapshot_field": "core_traits|preferences|sensitive_triggers|public_sentiment_profile|relationship_topology|current_context|current_mood|current_stress_level|current_engagement|none"\n'
        "    }\n  ]\n}"
    )


__all__ = [
    "BATCH_ENTITY_RESOLUTION_SYSTEM_PROMPT",
    "ENTITY_RECONCILE_SYSTEM_PROMPT",
    "ENTITY_RESOLUTION_SYSTEM_PROMPT",
    "render_batch_entity_resolution_prompt",
    "render_entity_reconcile_prompt",
    "render_entity_resolution_prompt",
]
