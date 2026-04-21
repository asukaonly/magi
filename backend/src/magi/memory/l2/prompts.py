"""Prompt templates for L2 two-phase extraction and reconcile helpers."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any

from .models import (
    L2BatchEntityResolutionItem,
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

# ---------------------------------------------------------------------------
# Phase 1 — Extract & Resolve
# ---------------------------------------------------------------------------

PHASE1_EXTRACT_SYSTEM_PROMPT = """You are a memory extraction engine for a personal AI assistant.

Your task: identify entities, resolve references, and extract factual claims from user messages.

## Allowed Entity Types
person, place, organization, group, product, food, software, technology, hardware, virtual_object, project, activity, event, animal, pet, health_metric, concept, skill, media, topic, weather_state, other

### Entity Type Aliases (map to canonical type)
dish/drink/snack/ingredient → food | app/application/service/platform/os/database → software | language/framework/algorithm/model → technology | device/console/phone → hardware | idea/principle/theory → concept

## Predicates
Core predicates (preferred): LIKES, DISLIKES, INTERESTED_IN, VISITED, LIVES_IN, PLANS_TO, ATTENDED, WORKS_AT, MEMBER_OF, INTERACTED_WITH, KNOWS, FAMILY_OF, USES, OWNS, CREATES, PROFICIENT_IN, HAS_METRIC

If none of the core predicates accurately describes the relationship, you MAY use a custom predicate in UPPER_SNAKE_CASE format (e.g., LEARNING, ALLERGIC_TO, TEACHING, STUDYING). Custom predicates receive lower confidence.

## Rules
1. Only extract facts from messages marked **[USER]**. Messages marked [ASSISTANT] are dialogue context only — never treat assistant responses as user beliefs, preferences, or facts.
2. Do NOT extract preferences from questions, recall requests, or hypothetical statements (e.g., "你记得我喜欢什么吗？", "What if I liked X?").
3. Do NOT create preference facts for generic/category-level objects (e.g., "天气", "food", "music", "地方"). Only create preference facts when a specific liked/disliked value is explicitly stated.
4. If a pronoun or vague reference appears (e.g., "那个", "它", "这种", "the one", "there"), resolve it using the Existing Entities or Recent Context sections. If unresolvable, mark as unresolved.
5. If a mentioned entity matches an Existing Entity by name, alias, or clear semantic equivalence, use its canonical ID. Otherwise mark as new.
6. Each entity must include a specificity rating: "concrete" for specific items, "underspecified" for vague/category-level references.

## Output Format
Return JSON only:
```json
{
  "entities": [
    {
      "surface": "original text span",
      "normalized_name": "canonical name",
      "entity_type": "enum from allowed types",
      "specificity": "concrete|underspecified",
      "resolved_id": "existing entity ID or null if new",
      "is_new": true,
      "alias_signals": ["optional alternative names"],
      "confidence": 0.0
    }
  ],
  "fact_claims": [
    {
      "subject_ref": "entity ID or user:self",
      "subject_type": "user|person|...",
      "predicate": "enum from allowed predicates",
      "object_ref": "entity surface or ID",
      "object_type": "enum from allowed types",
      "fact_kind": "explicit_fact|stable_preference|public_topology|future_intent",
      "polarity": "positive|negative",
      "specificity": "concrete|underspecified",
      "evidence_text": "supporting quote",
      "confidence": 0.0,
      "supporting_event_ids": ["event IDs"]
    }
  ],
  "resolved_refs": [
    {
      "surface": "pronoun or vague reference",
      "resolved_ref": "entity ID or null",
      "resolved_kind": "entity type or null",
      "reference_type": "self_actor|existing_entity|context_entity|unresolved",
      "confidence": 0.0
    }
  ],
  "diagnostics": {
    "entity_status": "found|none"
  }
}
```

### Example — correct extraction:
Input: [USER] 我特别喜欢吃螺蛳粉
Output entities: [{"surface": "螺蛳粉", "entity_type": "food", "specificity": "concrete", ...}]
Output fact_claims: [{"subject_ref": "user:self", "predicate": "LIKES", "object_ref": "螺蛳粉", "object_type": "food", "specificity": "concrete", ...}]

### Example — do NOT extract:
Input: [USER] 你还记得我喜欢什么天气吗？
Output: {"entities": [], "fact_claims": [], "diagnostics": {"entity_status": "none"}}
Reason: This is a recall question, not a preference statement.
"""


PHASE2_INTEGRATE_SYSTEM_PROMPT = """You are a memory integration engine for a personal AI assistant.

Given Phase 1 extracted facts and the user's existing knowledge graph, produce final graph edges, ToM (Theory of Mind) assertions, and identify contradictions or refinements.

## Allowed Assertion Families
stress, mood, engagement, trigger, relationship_shift, group_atmosphere, public_sentiment, preference_profile, taste_profile

## Rules
1. Compare each new fact claim against the Existing Graph. Determine the relationship:
   - **new**: No related existing edge. Produce a new graph edge.
   - **corroborates**: Matches an existing edge. Note for confidence boost.
   - **refines**: A new concrete fact clarifies an existing underspecified one (e.g., "rainy weather" refines "杭州天气"). Produce the new edge AND a refinement link.
   - **contradicts**: Directly conflicts with an existing edge (e.g., LIKES vs DISLIKES same object). Produce a contradiction hint.
   - **evolves**: A temporal state change (e.g., moved from city A to city B). Produce the new edge and mark the old one as evolved.
2. Only generate ToM assertions when psychological state evidence is clear and directly from user's own words. Do not infer mood or stress from assistant responses.
3. For single-event evidence, cap assertion confidence at 0.3.
4. Respect evidence accumulation: if an existing edge has high observation_count and the new evidence is a single event, do not override.
5. When the user explicitly states how they want to be addressed, prefer a `preference_profile` assertion instead of a graph edge.
    - Preferred form of address -> `trait_name = "preference.address.preferred"`
    - Disallowed form of address -> `trait_name = "preference.address.disallowed"`
    - Explicit real name -> `trait_name = "preference.address.real_name"`
    - If multiple forms are listed, encode `trait_value` as a JSON array string.

## Output Format
Return JSON only:
```json
{
  "graph_edges": [
    {
      "subject_ref": "entity ID",
      "subject_type": "user|person|...",
      "predicate": "enum",
      "object_ref": "entity ID",
      "object_type": "enum",
      "fact_kind": "explicit_fact|stable_preference|public_topology|future_intent",
      "polarity": "positive|negative",
      "confidence": 0.0,
      "evidence_text": "supporting quote",
      "supporting_event_ids": ["event IDs"],
      "relationship_to_existing": "new|corroborates|refines|contradicts|evolves",
      "related_existing_triple_id": "triple ID or null"
    }
  ],
  "refinements": [
    {
      "existing_triple_id": "triple ID being refined",
      "refined_by_object": "new concrete entity ID",
      "explanation": "why this refines the existing edge"
    }
  ],
  "assertion_candidates": [
    {
      "entity_ref": "entity ID",
      "entity_type": "enum",
      "trait_family": "enum from allowed families",
      "trait_name": "string",
      "trait_value": "string",
      "inference_depth": "topology_only|defensive_psychology",
      "volatility_index": 0.0,
      "confidence": 0.0,
      "evidence_texts": ["string"],
      "supporting_event_ids": ["event IDs"]
    }
  ],
  "contradiction_hints": [
    {
      "target_record_id": "triple or assertion ID",
      "target_record_type": "knowledge_graph|tom_trait_assertion",
      "contradiction_kind": "direct_negation|state_reversal|temporal_expiration|exclusive_role_conflict|preference_reversal|weak_tension",
      "confidence": 0.0,
      "evidence_text": "string",
      "recommended_action": "downgrade_confidence|mark_conflicted|mark_deprecated|revalidate_only"
    }
  ]
}
```
"""

# Legacy prompts kept for entity resolution, reconcile, and conflict arbitration
# which remain as separate LLM calls.

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

CONFLICT_ARBITRATION_SYSTEM_PROMPT = """You are a conflict arbitration assistant for a memory system.

Your task is to review new evidence, conflicting existing memory records, and supporting source events.
Return exactly one final arbitration decision: keep_new, keep_existing, or mark_evolution.
Do not hedge, and do not return multiple competing outcomes.
"""

# ---------------------------------------------------------------------------
# Helper: format timestamp for prompts
# ---------------------------------------------------------------------------

def _format_ts(ts: float) -> str:
    if ts <= 0:
        return "unknown"
    try:
        return datetime.fromtimestamp(ts, tz=timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
    except (OSError, ValueError):
        return "unknown"


# ---------------------------------------------------------------------------
# Phase 1 prompt renderer
# ---------------------------------------------------------------------------

def render_phase1_extract_prompt(
    *,
    event_window: L2EventWindow,
    focal_subject: dict[str, Any],
    existing_entities: list[dict[str, Any]] | None = None,
    context_messages: list[dict[str, Any]] | None = None,
    extraction_instructions: str | None = None,
) -> str:
    """Render a Markdown-formatted Phase 1 extraction prompt."""
    parts: list[str] = []

    if extraction_instructions:
        parts.append("## Source-Specific Instructions")
        parts.append(extraction_instructions.strip())
        parts.append("")

    # Messages to analyze
    parts.append("## Messages to Analyze")
    for event in event_window.events:
        role = str(event.author_type or "user").upper()
        ts = _format_ts(event.timestamp)
        parts.append(f"### [{role}] (event: {event.event_id}, {ts})")
        parts.append(str(event.content).strip())
        parts.append("")

    # Focal subject
    focal_ref = focal_subject.get("entity_ref") or "user:self"
    focal_type = focal_subject.get("entity_type") or "user"
    parts.append(f"## Focal Subject\n- entity_ref: {focal_ref}\n- entity_type: {focal_type}")
    parts.append("")

    # Existing entities from catalog
    if existing_entities:
        parts.append("## Existing Entities (from catalog)")
        for entity in existing_entities[:30]:
            eid = entity.get("entity_id", "")
            etype = entity.get("entity_type", "")
            cname = entity.get("canonical_name", "")
            aliases_list = entity.get("aliases", [])
            alias_str = f" (aliases: {', '.join(aliases_list)})" if aliases_list else ""
            parts.append(f"- {eid} [{etype}] {cname}{alias_str}")
        parts.append("")

    # Context messages (same session, with role annotation)
    if context_messages:
        parts.append("## Recent Context (same session)")
        for msg in context_messages:
            role = str(msg.get("role", "user")).upper()
            content = str(msg.get("content", "")).strip()
            if content:
                parts.append(f"- [{role}] {content}")
        parts.append("")

    # History contexts (cross-session)
    if event_window.history_contexts:
        parts.append("## History Context (cross-session)")
        for ctx in event_window.history_contexts:
            ts = _format_ts(ctx.timestamp)
            matched = f", matched_entity: {ctx.canonical_name}" if ctx.canonical_name else ""
            session_label = f"session: {ctx.session_id}" if ctx.session_id else "unknown session"
            parts.append(f"### ({session_label}{matched}, {ts})")
            parts.append(str(ctx.content).strip())
            parts.append("")

    return "\n".join(parts)


# ---------------------------------------------------------------------------
# Phase 2 prompt renderer
# ---------------------------------------------------------------------------

def render_phase2_integrate_prompt(
    *,
    phase1_result: dict[str, Any],
    existing_graph_edges: list[dict[str, Any]] | None = None,
    existing_assertions: list[dict[str, Any]] | None = None,
    event_window: L2EventWindow,
    focal_subject: dict[str, Any],
) -> str:
    """Render a Markdown-formatted Phase 2 integration prompt."""
    parts: list[str] = []

    # Phase 1 results
    parts.append("## Phase 1 Extracted Results")

    entities = phase1_result.get("entities", [])
    if entities:
        parts.append("### Entities Found")
        for entity in entities:
            surface = entity.get("surface", "")
            etype = entity.get("entity_type", "")
            specificity = entity.get("specificity", "concrete")
            resolved_id = entity.get("resolved_id")
            status = f"resolved={resolved_id}" if resolved_id else "new"
            parts.append(f"- **{surface}** [{etype}, {specificity}] ({status})")
        parts.append("")

    fact_claims = phase1_result.get("fact_claims", [])
    if fact_claims:
        parts.append("### Fact Claims")
        for i, claim in enumerate(fact_claims, 1):
            subj = claim.get("subject_ref", "?")
            pred = claim.get("predicate", "?")
            obj = claim.get("object_ref", "?")
            obj_type = claim.get("object_type", "?")
            specificity = claim.get("specificity", "concrete")
            conf = claim.get("confidence", 0.0)
            evidence = claim.get("evidence_text", "")
            parts.append(
                f"{i}. {subj} → {pred} → {obj} [{obj_type}, {specificity}] "
                f"(confidence: {conf})"
            )
            if evidence:
                parts.append(f'   Evidence: "{evidence}"')
            event_ids = claim.get("supporting_event_ids", [])
            if event_ids:
                parts.append(f"   Events: {', '.join(event_ids)}")
        parts.append("")

    resolved_refs = phase1_result.get("resolved_refs", [])
    if resolved_refs:
        parts.append("### Resolved References")
        for ref in resolved_refs:
            surface = ref.get("surface", "")
            resolved = ref.get("resolved_ref") or "unresolved"
            parts.append(f"- \"{surface}\" → {resolved}")
        parts.append("")

    # Existing graph edges for the focal subject
    if existing_graph_edges:
        parts.append("## Existing Knowledge Graph (relevant subgraph)")
        for edge in existing_graph_edges[:30]:
            subj = edge.get("subject_id", "?")
            pred = edge.get("predicate", "?")
            obj = edge.get("object_id", "?")
            obj_type = edge.get("object_type", "?")
            status = edge.get("status", "active")
            conf = edge.get("confidence", 0.0)
            obs_count = edge.get("observation_count", 1)
            triple_id = edge.get("triple_id", "")
            first_obs = _format_ts(float(edge.get("first_observed_at", 0)))
            parts.append(
                f"- [{triple_id}] {subj} {pred} {obj} [{obj_type}] "
                f"(status={status}, confidence={conf}, observed={obs_count}x, since={first_obs})"
            )
        parts.append("")

    # Existing ToM assertions
    if existing_assertions:
        parts.append("## Existing Assertions")
        for assertion in existing_assertions[:20]:
            trait = assertion.get("trait_name", "?")
            value = assertion.get("trait_value", "?")
            family = assertion.get("trait_family", "?")
            state = assertion.get("validation_state", "?")
            conf = assertion.get("confidence_score", 0.0)
            aid = assertion.get("assertion_id", "")
            parts.append(
                f"- [{aid}] {family}/{trait} = {value} "
                f"(state={state}, confidence={conf})"
            )
        parts.append("")

    # Focal subject
    focal_ref = focal_subject.get("entity_ref") or "user:self"
    parts.append(f"## Focal Subject: {focal_ref}")
    parts.append("")

    # Original messages for evidence verification
    parts.append("## Original Messages (for evidence verification)")
    for event in event_window.events:
        role = str(event.author_type or "user").upper()
        parts.append(f"- [{role}] (event: {event.event_id}) {str(event.content).strip()}")
    parts.append("")

    return "\n".join(parts)


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


BATCH_ENTITY_RESOLUTION_SYSTEM_PROMPT = """You are an entity resolution engine for a memory graph.

Your job is to determine, for EACH mention in the batch, whether it refers to one of its provided candidate entities.
Be conservative:
- Prefer unresolved over guessing.
- Use local context, aliases, semantics, and common nicknames.
- Do not create a new fact beyond identity resolution.
- Return JSON only.
"""


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
    "PHASE1_EXTRACT_SYSTEM_PROMPT",
    "PHASE2_INTEGRATE_SYSTEM_PROMPT",
    "ENTITY_RECONCILE_SYSTEM_PROMPT",
    "ENTITY_RESOLUTION_SYSTEM_PROMPT",
    "CONFLICT_ARBITRATION_SYSTEM_PROMPT",
    "render_phase1_extract_prompt",
    "render_phase2_integrate_prompt",
    "render_conflict_arbitration_prompt",
    "render_entity_reconcile_prompt",
    "render_entity_resolution_prompt",
    "BATCH_ENTITY_RESOLUTION_SYSTEM_PROMPT",
    "render_batch_entity_resolution_prompt",
]
