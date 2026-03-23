"""Prompt templates for L2 extraction and reconcile helpers."""

from __future__ import annotations

import json
from typing import Any

from .context_bundle import ContextBundle
from .extraction_profiles import ExtractionProfile
from .models import (
    L2CandidateSet,
    L2EntityCandidate,
    L2EntityResolutionMention,
    L2ReconcileAssertion,
    L2ReconcileEntity,
    L2ReconcileGraphFact,
    L2EventWindow,
    L2ExistingRecord,
    L2SourceEvent,
)


UNIFIED_EXTRACTION_SYSTEM_PROMPT = """You are a structured extraction engine for a memory system.

Your task is to extract entity mentions, graph fact candidates, and assertion candidates from the supplied event window.
Be conservative:
- Return JSON only.
- Do not invent unsupported entity types or predicates.
- Use only the allowed entity types, predicates, and assertion families supplied in the prompt.
- Specific dishes, drinks, snacks, and ingredients must use `food`.
- If no entity can be extracted, set diagnostics.entity_status to `none`.
"""


ENTITY_RESOLUTION_SYSTEM_PROMPT = """You are an entity resolution engine for a memory graph.

Your job is to determine whether a mention refers to one of the provided candidate entities.
Be conservative:
- Prefer unresolved over guessing.
- Use local context, aliases, semantics, and common nicknames.
- Do not create a new fact beyond identity resolution.
- Return JSON only.
"""

CONTRADICTION_HINT_SYSTEM_PROMPT = """You are a contradiction detection assistant for a memory system.

Your task is to compare a new memory event with existing graph facts or ToM assertions and identify possible contradiction signals.
Do not make final database decisions.
Only emit contradiction hints with evidence and confidence.
Return JSON only.
"""

ENTITY_RECONCILE_SYSTEM_PROMPT = """You are an entity-level reconciliation engine for a memory system.

Your job is to review multiple evidence-bound records for the same entity and estimate which candidate traits are currently supported, contradicted, unstable, or still uncertain.
Be conservative:
- Respect evidence count and time span.
- Do not overfit to a single recent statement if long-term evidence disagrees.
- Separate stable traits from temporary states.
- Return JSON only.
"""

CONFLICT_ARBITRATION_SYSTEM_PROMPT = """You are a conflict arbitration assistant for a memory system.

Your task is to review new evidence, conflicting existing memory records, and supporting source events.
Return exactly one final arbitration decision: keep_new, keep_existing, or mark_evolution.
Do not hedge, and do not return multiple competing outcomes.
"""


def render_unified_extraction_prompt(
    *,
    event_window: L2EventWindow,
    profile: ExtractionProfile,
    focal_subject: dict[str, Any],
    context_bundle: ContextBundle | None = None,
) -> str:
    """Render the unified extraction prompt with ontology/profile constraints."""

    payload = {
        "event_window": event_window.to_dict(),
        "focal_subject": focal_subject,
        "context_bundle": context_bundle.to_dict() if context_bundle is not None else None,
        "allowed_entity_types": sorted(profile.allowed_entity_types),
        "allowed_predicates": sorted(profile.allowed_predicates),
        "allowed_assertion_families": sorted(profile.allowed_assertion_families),
        "allow_graph": profile.allow_graph,
        "allow_assertion": profile.allow_assertion,
        "entity_type_aliases": profile.entity_type_aliases,
        "predicate_aliases": profile.predicate_aliases,
        "rules": [
            "Use only the allowed entity types and predicates in this prompt.",
            "Specific dishes, drinks, snacks, and ingredients must use `food`.",
            "Use diagnostics.entity_status = `none` when no entity mention is extracted.",
            "Resolve context references only from the supplied context bundle candidates or return unresolved.",
            "Use batch-level context across the supplied event window, but only cite supporting_event_ids that are present in the event window.",
            "When multiple events support the same candidate, include every relevant supporting_event_ids entry that directly supports it.",
            "Return JSON with mentions, resolved_context_refs, graph_candidates, assertion_candidates, and diagnostics.",
        ],
        "output_schema": {
            "mentions": [
                {
                    "mention_text": "string",
                    "normalized_surface": "string",
                    "entity_type": "enum",
                    "canonical_name_hint": "string or null",
                    "alias_signals": ["string"],
                    "evidence_text": "string",
                    "confidence": 0.0,
                }
            ],
            "resolved_context_refs": [
                {
                    "surface": "string",
                    "reference_type": "context_entity|canonical_entity|self_actor|unresolved",
                    "resolved_ref": "string or null",
                    "resolved_kind": "string or null",
                    "confidence": 0.0,
                    "evidence_text": "string",
                }
            ],
            "graph_candidates": [
                {
                    "subject_ref": "string",
                    "subject_type": "enum",
                    "predicate": "enum",
                    "object_ref": "string",
                    "object_type": "enum",
                    "fact_kind": "explicit_fact|stable_preference|public_topology|future_intent",
                    "polarity": "positive|negative",
                    "evidence_text": "string",
                    "confidence": 0.0,
                }
            ],
            "assertion_candidates": [
                {
                    "entity_ref": "string",
                    "entity_type": "enum",
                    "trait_family": "enum",
                    "trait_name": "string",
                    "trait_value": "string or JSON string",
                    "target_ref": "string or null",
                    "target_entity_type": "enum or null",
                    "inference_depth": "topology_only|defensive_psychology",
                    "volatility_index": 0.0,
                    "confidence": 0.0,
                    "validation_state": "tentative",
                    "evidence_texts": ["string"],
                    "supporting_event_ids": ["string"],
                }
            ],
            "diagnostics": {
                "entity_status": "found|none",
            },
        },
    }
    return (
        "Extract unified L2 candidates from the following event window.\n\n"
        f"{json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True)}"
    )


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


def render_contradiction_hint_prompt(*, new_event: dict[str, Any], existing_records: list[L2ExistingRecord]) -> str:
    return (
        "Compare the new event against existing memory records and identify possible contradiction hints.\n\n"
        f"New event:\n{json.dumps(new_event, ensure_ascii=False, indent=2)}\n\n"
        f"Existing records:\n{json.dumps([item.to_dict() for item in existing_records], ensure_ascii=False, indent=2)}\n\n"
        "Return JSON with this schema:\n"
        '{\n  "contradiction_hints": [\n    {\n      "target_record_id": "string",\n      "target_record_type": "knowledge_graph|tom_trait_assertion",\n'
        '      "contradiction_kind": "direct_negation|state_reversal|temporal_expiration|exclusive_role_conflict|preference_reversal|weak_tension",\n'
        '      "confidence": 0.0,\n      "evidence_text": "string",\n      "recommended_action": "downgrade_confidence|mark_conflicted|mark_deprecated|revalidate_only"\n'
        "    }\n  ]\n}"
    )


def render_conflict_arbitration_prompt(
    *,
    new_event_window: L2EventWindow,
    new_candidates: L2CandidateSet,
    contradiction_hints: list[dict[str, Any]],
    existing_records: list[L2ExistingRecord],
    source_events: list[L2SourceEvent],
) -> str:
    return (
        "Arbitrate the conflict between new evidence and existing memory records.\n\n"
        f"New event window:\n{json.dumps(new_event_window.to_dict(), ensure_ascii=False, indent=2)}\n\n"
        f"New candidates:\n{json.dumps(new_candidates.to_dict(), ensure_ascii=False, indent=2)}\n\n"
        f"Contradiction hints:\n{json.dumps(contradiction_hints, ensure_ascii=False, indent=2)}\n\n"
        f"Existing records:\n{json.dumps([item.to_dict() for item in existing_records], ensure_ascii=False, indent=2)}\n\n"
        f"Supporting source events:\n{json.dumps([item.to_dict() for item in source_events], ensure_ascii=False, indent=2)}\n\n"
        "Return JSON with this schema:\n"
        '{\n  "decision": "keep_new|keep_existing|mark_evolution",\n'
        '  "winning_record_ids": ["string"],\n'
        '  "superseded_record_ids": ["string"],\n'
        '  "reason": "string"\n}'
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
        "Return JSON with this schema:\n"
        '{\n  "reconciled_traits": [\n    {\n      "trait_name": "string",\n      "winning_value": "string or JSON string",\n'
        '      "status": "stable|corroborated|tentative|contradicted|expired",\n      "confidence": 0.0,\n      "evidence_event_ids": ["string"],\n'
        '      "time_span_hours": 0.0,\n      "stability_kind": "stable_trait|temporary_state|volatile_pattern",\n'
        '      "recommended_snapshot_field": "core_traits|preferences|sensitive_triggers|public_sentiment_profile|relationship_topology|current_context|current_mood|current_stress_level|current_engagement|none"\n'
        "    }\n  ]\n}"
    )


__all__ = [
    "UNIFIED_EXTRACTION_SYSTEM_PROMPT",
    "ENTITY_RECONCILE_SYSTEM_PROMPT",
    "ENTITY_RESOLUTION_SYSTEM_PROMPT",
    "CONTRADICTION_HINT_SYSTEM_PROMPT",
    "CONFLICT_ARBITRATION_SYSTEM_PROMPT",
    "render_conflict_arbitration_prompt",
    "render_contradiction_hint_prompt",
    "render_entity_reconcile_prompt",
    "render_entity_resolution_prompt",
    "render_unified_extraction_prompt",
]
