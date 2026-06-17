"""Prompt templates for L2 two-phase extraction and reconcile helpers."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from ...models import L2EventWindow
from .workflows import (
    BATCH_ENTITY_RESOLUTION_SYSTEM_PROMPT,
    CONFLICT_ARBITRATION_SYSTEM_PROMPT,
    ENTITY_RECONCILE_SYSTEM_PROMPT,
    ENTITY_RESOLUTION_SYSTEM_PROMPT,
    render_batch_entity_resolution_prompt,
    render_conflict_arbitration_prompt,
    render_entity_reconcile_prompt,
    render_entity_resolution_prompt,
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

If none of the core predicates accurately describes a durable relationship, you MAY use a custom predicate in UPPER_SNAKE_CASE format (e.g., LEARNING, ALLERGIC_TO, TEACHING, STUDYING). Custom predicates receive lower confidence and must describe stable, reusable knowledge.
Do NOT use graph predicates for dialogue/query activity such as ASKED_ABOUT, QUESTIONED_ABOUT, MENTIONED, TALKED_ABOUT, REFERRED_TO, LOOKED_AT, WANTS_TO_KNOW, or NEEDS_HELP_WITH. Questions can explain short-lived attention or knowledge gaps, but they are not knowledge graph relations by themselves.

Profile-signal predicates (Phase 1 only, never graph relations): REAL_NAME, BIRTH_DATE, BIRTH_YEAR, STATED_AGE, PREFERRED_FORM_OF_ADDRESS, DISALLOWED_FORM_OF_ADDRESS, PREFERRED_COMMUNICATION_STYLE. Use these when the user states personal profile facts; preserve the exact value in `object_ref` and set `object_type` to `concept`.

## Rules
1. Only extract facts from messages marked **[USER]**. Messages marked [ASSISTANT] are dialogue context only — never treat assistant responses as user beliefs, preferences, or facts.
2. Do NOT extract preferences from questions, recall requests, or hypothetical statements (e.g., "你记得我喜欢什么吗？", "What if I liked X?").
3. Do NOT create preference facts for generic/category-level objects (e.g., "天气", "food", "music", "地方"). Only create preference facts when a specific liked/disliked value is explicitly stated.
4. If a pronoun or vague reference appears (e.g., "那个", "它", "这种", "the one", "there"), resolve it using the Existing Entities or Recent Context sections. If unresolvable, mark as unresolved.
5. If a mentioned entity matches an Existing Entity by name, alias, or clear semantic equivalence, use its canonical ID. Otherwise mark as new.
6. Each entity must include a specificity rating: "concrete" for specific items, "underspecified" for vague/category-level references.
7. Preserve entity language and script. `surface` must be the original text span, and `normalized_name` must keep the source language/script unless the source itself uses a translated name. Do NOT translate Chinese, Japanese, Korean, Cyrillic, or other non-Latin proper nouns into English; do NOT romanize or slugify them. Put known translations, romanizations, or alternate spellings in `alias_signals` only.
8. Extract only concrete, named, reusable entities. Pronouns and vague placeholders such as "他", "她", "它", "这个", "那个", "this one", "that one", "the file", "the image", generic "app", or generic "PDF" may appear only in `resolved_refs`; do not emit them as `entities` unless they are confidently resolved to a specific existing entity or asset with a concrete canonical name.
9. For web pages and external-source metadata, never use a URL domain/path slug as the canonical entity name when the title or source text contains a readable subject name. Treat domains and platforms as provenance or separate platform entities, not as replacements for the content entity.
10. Addressing instructions such as "叫我子涵" or "call me Zihan" are communication-profile signals. Emit one fact claim with `predicate = "PREFERRED_FORM_OF_ADDRESS"`, `object_ref` set to the requested name, and `object_type = "concept"`. Do NOT turn the requested name into a LIKES, DISLIKES, INTERESTED_IN, KNOWS, or other graph relationship.
11. Explicit self-profile facts such as real name, birthday, birth year, age, preferred language, or preferred communication style should use the matching profile-signal predicate, not graph predicates.

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
stress, mood, engagement, trigger, relationship_shift, group_atmosphere, public_sentiment, identity_profile, communication_profile, preference_profile, state_profile, taste_profile

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
5. When the user explicitly states profile facts, prefer `identity_profile` or `communication_profile` assertions instead of graph edges.
  - Phase 1 `REAL_NAME` -> `trait_family = "identity_profile"`, `trait_name = "identity.real_name"`
  - Phase 1 `BIRTH_DATE` -> `trait_family = "identity_profile"`, `trait_name = "identity.birth_date"`
  - Phase 1 `BIRTH_YEAR` -> `trait_family = "identity_profile"`, `trait_name = "identity.birth_year"`
  - Phase 1 `STATED_AGE` -> `trait_family = "identity_profile"`, `trait_name = "identity.age.stated"`
  - Phase 1 `PREFERRED_FORM_OF_ADDRESS` -> `trait_family = "communication_profile"`, `trait_name = "communication.address.preferred"`
  - Phase 1 `DISALLOWED_FORM_OF_ADDRESS` -> `trait_family = "communication_profile"`, `trait_name = "communication.address.disallowed"`
  - Phase 1 `PREFERRED_COMMUNICATION_STYLE` -> `trait_family = "communication_profile"`, `trait_name = "communication.response_style.preferred"`
    - If multiple forms are listed, encode `trait_value` as a JSON array string.
    - For profile assertions, `trait_value` is user-facing data. Preserve the
      original language/script and wording from Phase 1 `object_ref` or evidence.
      Do NOT translate, romanize, slugify, or convert it to snake_case IDs
      (for example, keep `哈基米或者子涵`, never `haji_mi_or_zi_han`).
    - These internal trait names may appear ONLY in `assertion_candidates.trait_name`.
      Never use assertion families, trait names, output field names, or schema keys as
      `graph_edges.predicate` or `graph_edges.object_ref`.
    - Do not emit any `graph_edges` item whose object is the requested form of address.
    - Emit these profile assertions only when Phase 1 contains the matching
      profile-signal fact claim grounded in current [USER] text. Do not infer
      identity or communication profile values from assistant/persona text,
      history context, or a one-off task request.
6. Custom graph predicates are allowed only for stable, reusable facts not covered by the core predicate list. Do NOT emit dialogue/query predicates such as ASKED_ABOUT, QUESTIONED_ABOUT, MENTIONED, TALKED_ABOUT, REFERRED_TO, LOOKED_AT, WANTS_TO_KNOW, or NEEDS_HELP_WITH.
7. Do NOT emit graph edges whose object is an unresolved pronoun or vague placeholder such as "他", "她", "它", "这个", "那个", generic "app", generic "PDF", "file", "document", or "image". Resolve them to a concrete existing entity/asset first, or omit the graph edge.
8. For `graph_edges.object_ref`, use ONLY concrete entity IDs shown in `### Entities Found` or `## Existing Knowledge Graph`. If Phase 1 gives a surface text plus an entity_id hint, copy the entity_id exactly. Do NOT invent entity IDs.
9. Preserve original language/script in evidence and user-facing values. Do NOT translate, romanize, transliterate, slugify, or combine non-Latin names into ASCII IDs such as pinyin or romaji.

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
      "trait_value": "profile assertions: original user-facing text; state assertions: short controlled value, max 40 chars",
      "natural_summary": "free-form description in user's language, max 500 chars",
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

def build_phase2_integrate_system_prompt(user_language: str | None = None) -> str:
    """Return the Phase 2 system prompt with an explicit language directive.

    When ``user_language`` is supplied (e.g. "zh-CN", "en", "ja"), the prompt
    is suffixed with a binding instruction: every ``natural_summary`` and every
    user-facing ``trait_value`` for state assertions must be written in that
    language. Profile-fact ``trait_value`` (real_name, address preference, etc.)
    still follows rule 5/9 and preserves the original script.

    When ``user_language`` is None, returns the baseline prompt unchanged so
    the LLM falls back to inferring language from evidence text.
    """
    if not user_language:
        return PHASE2_INTEGRATE_SYSTEM_PROMPT
    return PHASE2_INTEGRATE_SYSTEM_PROMPT + (
        "\n\n## Language directive\n"
        f"The user's primary language is `{user_language}`. Write every "
        "`natural_summary` in that language. For state-class assertion "
        "`trait_value` (mood, stress, engagement, sleep, energy, focus), also "
        "use that language unless the evidence text supplies an explicit foreign "
        "term the user chose. Profile-fact `trait_value` (real_name, addressing "
        "preference, etc.) still preserves the source script per rule 5/9."
    )


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
        parts.append(f"### [{role}] [#{event.event_id}] {ts}")
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
    source_integration_instructions: str | None = None,
) -> str:
    """Render a Markdown-formatted Phase 2 integration prompt."""
    parts: list[str] = []

    if source_integration_instructions:
        instructions = str(source_integration_instructions).strip()
        if instructions:
            parts.append("## Source-Specific Integration Instructions")
            parts.append(instructions)
            parts.append("")

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
        entity_status = "new" if entity.get("is_new", True) else "existing"
        status = (
          f"entity_id={resolved_id}, status={entity_status}"
          if resolved_id
          else "unresolved_new_surface"
        )
        parts.append(f"- **{surface}** -> {resolved_id or 'NO_ENTITY_ID'} [{etype}, {specificity}] ({status})")
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
            object_id_hint = _find_phase1_entity_id_for_claim(
              object_ref=obj,
              object_type=obj_type,
              entities=entities,
            )
            hint_text = f", entity_id: {object_id_hint}" if object_id_hint else ""
            parts.append(
              f"{i}. {subj} → {pred} → {obj} [{obj_type}, {specificity}{hint_text}] (confidence: {conf})"
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
            parts.append(f'- "{surface}" → {resolved}')
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
            parts.append(f"- [{aid}] {family}/{trait} = {value} (state={state}, confidence={conf})")
        parts.append("")

    # Focal subject
    focal_ref = focal_subject.get("entity_ref") or "user:self"
    parts.append(f"## Focal Subject: {focal_ref}")
    parts.append("")

    # Original messages for evidence verification
    parts.append("## Original Messages (for evidence verification)")
    for event in event_window.events:
        role = str(event.author_type or "user").upper()
        parts.append(f"- [{role}] [#{event.event_id}] {str(event.content).strip()}")
    parts.append("")

    return "\n".join(parts)


def _find_phase1_entity_id_for_claim(
    *,
    object_ref: Any,
    object_type: Any,
    entities: list[dict[str, Any]],
) -> str | None:
    object_text = str(object_ref or "").strip().casefold()
    object_type_text = str(object_type or "").strip().casefold()
    if not object_text:
        return None
    for entity in entities:
        resolved_id = str(entity.get("resolved_id") or "").strip()
        if not resolved_id:
            continue
        entity_type = str(entity.get("entity_type") or "").strip().casefold()
        if object_type_text and entity_type and entity_type != object_type_text:
            continue
        surfaces = {
            str(entity.get("surface") or "").strip().casefold(),
            str(entity.get("normalized_name") or "").strip().casefold(),
            resolved_id.casefold(),
        }
        if object_text in surfaces:
            return resolved_id
    return None


__all__ = [
    "PHASE1_EXTRACT_SYSTEM_PROMPT",
    "PHASE2_INTEGRATE_SYSTEM_PROMPT",
    "build_phase2_integrate_system_prompt",
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
