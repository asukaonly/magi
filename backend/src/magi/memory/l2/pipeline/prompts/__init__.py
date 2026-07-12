"""Prompt templates for L2 two-phase extraction and reconcile helpers."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from ...models import L2EventWindow
from ...assertion_family_policy import (
    render_assertion_family_list,
    render_assertion_family_semantics,
)
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

Your task: identify entities, resolve references, and extract factual claims from user messages and trusted external observations.

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
1. Only extract facts from messages marked **[USER]** or **[EXTERNAL]**. Messages marked [ASSISTANT] are dialogue context only — never treat assistant responses as user beliefs, preferences, or facts.
2. For [EXTERNAL] messages, never use user:self. Treat them as third-party observations. If the text says `Caroline said, "I ..."` or `Melanie said, "my ..."`, resolve first-person pronouns inside the quote to the named speaker, and use that person as the subject.
3. Do NOT extract preferences from questions, recall requests, or hypothetical statements (e.g., "你记得我喜欢什么吗？", "What if I liked X?").
4. Do NOT create preference facts for generic/category-level objects (e.g., "天气", "food", "music", "地方"). Only create preference facts when a specific liked/disliked value is explicitly stated.
5. If a pronoun or vague reference appears (e.g., "那个", "它", "这种", "the one", "there"), resolve it using the Existing Entities or Recent Context sections. If unresolvable, mark as unresolved.
6. If a mentioned entity matches an Existing Entity by name, alias, or clear semantic equivalence, use its canonical ID. Otherwise mark as new.
7. Each entity must include a specificity rating: "concrete" for specific items, "underspecified" for vague/category-level references.
8. Preserve entity language and script. `surface` must be the original text span, and `normalized_name` must keep the source language/script unless the source itself uses a translated name. Do NOT translate Chinese, Japanese, Korean, Cyrillic, or other non-Latin proper nouns into English; do NOT romanize or slugify them. Put known translations, romanizations, or alternate spellings in `alias_signals` only.
9. Extract only concrete, named, reusable entities. Pronouns and vague placeholders such as "他", "她", "它", "这个", "那个", "this one", "that one", "the file", "the image", generic "app", or generic "PDF" may appear only in `resolved_refs`; do not emit them as `entities` unless they are confidently resolved to a specific existing entity or asset with a concrete canonical name.
10. For web pages and external-source metadata, never use a URL domain/path slug as the canonical entity name when the title or source text contains a readable subject name. Treat domains and platforms as provenance or separate platform entities, not as replacements for the content entity.
11. Addressing instructions such as "叫我子涵" or "call me Zihan" are communication-profile signals. Emit one fact claim with `predicate = "PREFERRED_FORM_OF_ADDRESS"`, `object_ref` set to the requested name, and `object_type = "concept"`. Do NOT turn the requested name into a LIKES, DISLIKES, INTERESTED_IN, KNOWS, or other graph relationship.
12. Explicit self-profile facts such as real name, birthday, birth year, age, preferred language, or preferred communication style should use the matching profile-signal predicate, not graph predicates.
13. Every concrete object_ref used in fact_claims must also appear in entities with a matching surface or normalized_name and matching entity_type, unless object_ref is exactly an Existing Entity ID. This includes activities, events, plans, media, products, groups, and concepts. Do not emit orphan fact claims whose object cannot later be resolved to an entity.
14. Every fact claim must include `evidence_text` as an exact quote copied from a current message under Messages to Analyze. `supporting_event_ids` must contain only the current message IDs that contain that exact quote. Never cite Recent Context or History Context as new claim evidence. If no current message directly supports the claim, omit it.

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


PHASE2_INTEGRATE_SYSTEM_PROMPT = """You are the inference stage of a personal memory system.

Phase 1 has already extracted facts, resolved entities, and verified exact event evidence. Your task is limited to higher-order interpretation. Do not recreate graph edges, facts, entities, confidence scores, evidence quotes, event IDs, decay rules, or conflict actions.

## Allowed Assertion Families
@@ASSERTION_FAMILY_LIST@@

@@ASSERTION_FAMILY_SEMANTICS@@

## Rules
1. Every output item must cite one or more `claim_id` values shown in Phase 1. Never cite raw event IDs or invent a claim ID.
2. Emit a claim assessment only for a non-obvious relationship to a listed existing record: `refines`, `contradicts`, or `evolves`. Exact new facts and exact corroboration are handled deterministically by the host and must be omitted.
3. `related_record_id` must exactly match a listed triple ID or assertion ID. If no listed record applies, omit the assessment.
4. Generate an assertion only when the cited claims support a reusable higher-order understanding. A one-time task or passive observation is evidence, not automatically a stable preference, identity, routine, or psychological state.
5. When the user explicitly states profile facts, prefer `identity_profile` or `communication_profile` assertions.
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
    - Emit these profile assertions only when Phase 1 contains the matching
      profile-signal fact claim grounded in current [USER] text. Do not infer
      identity or communication profile values from assistant/persona text,
      history context, or a one-off task request.
6. Preserve original language and script in user-facing values. Do not translate, romanize, transliterate, slugify, or replace them with internal identifiers.
7. The host owns confidence, volatility, inference depth, lifecycle, and conflict actions. Do not return those fields.

## Output Format
Return JSON only:
```json
{
  "claim_assessments": [
    {
      "claim_id": "exact Phase 1 claim ID",
      "relationship": "refines|contradicts|evolves",
      "related_record_id": "exact listed triple or assertion ID"
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
      "supporting_claim_ids": ["exact Phase 1 claim IDs"]
    }
  ]
}
```
"""

PHASE2_INTEGRATE_SYSTEM_PROMPT = PHASE2_INTEGRATE_SYSTEM_PROMPT.replace(
    "@@ASSERTION_FAMILY_LIST@@", render_assertion_family_list()
).replace("@@ASSERTION_FAMILY_SEMANTICS@@", render_assertion_family_semantics())


def build_phase2_integrate_system_prompt(user_language: str | None = None) -> str:
    """Return the Phase 2 system prompt with an explicit language directive.

    When ``user_language`` is supplied (e.g. "zh-CN", "en", "ja"), the prompt
    is suffixed with a binding instruction: every ``natural_summary`` and every
    user-facing ``trait_value`` for state assertions must be written in that
    language. Profile-fact ``trait_value`` (real_name, address preference, etc.)
    still follows rule 5 and preserves the original script.

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
        "preference, etc.) still preserves the source script per rule 5."
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
    focal_subject: dict[str, Any],
    source_integration_instructions: str | None = None,
    evidence_packet: dict[str, Any] | None = None,
) -> str:
    """Render a Markdown-formatted Phase 2 integration prompt."""
    parts: list[str] = []

    _append_source_integration_instructions(parts, source_integration_instructions)
    _append_phase1_results(parts, phase1_result)
    _append_evidence_packet(parts, evidence_packet)
    _append_phase2_focal_subject(parts, focal_subject)

    return "\n".join(parts)


def _append_source_integration_instructions(
    parts: list[str],
    source_integration_instructions: str | None,
) -> None:
    if not source_integration_instructions:
        return
    instructions = str(source_integration_instructions).strip()
    if not instructions:
        return
    parts.append("## Source-Specific Integration Instructions")
    parts.append(instructions)
    parts.append("")


def _append_phase1_results(
    parts: list[str],
    phase1_result: dict[str, Any],
) -> None:
    parts.append("## Phase 1 Extracted Results")
    entities = phase1_result.get("entities", [])
    _append_phase1_entities(parts, entities)
    _append_phase1_fact_claims(parts, phase1_result.get("fact_claims", []), entities)
    _append_phase1_resolved_refs(parts, phase1_result.get("resolved_refs", []))


def _append_phase1_entities(parts: list[str], entities: list[dict[str, Any]]) -> None:
    if not entities:
        return
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
        parts.append(
            f"- **{surface}** -> {resolved_id or 'NO_ENTITY_ID'} "
            f"[{etype}, {specificity}] ({status})"
        )
    parts.append("")


def _append_phase1_fact_claims(
    parts: list[str],
    fact_claims: list[dict[str, Any]],
    entities: list[dict[str, Any]],
) -> None:
    if not fact_claims:
        return
    parts.append("### Fact Claims")
    for i, claim in enumerate(fact_claims, 1):
        claim_id = claim.get("claim_id", "")
        subj = claim.get("subject_ref", "?")
        pred = claim.get("predicate", "?")
        obj = claim.get("object_ref", "?")
        obj_type = claim.get("object_type", "?")
        specificity = claim.get("specificity", "concrete")
        conf = claim.get("confidence", 0.0)
        object_id_hint = _find_phase1_entity_id_for_claim(
            object_ref=obj,
            object_type=obj_type,
            entities=entities,
        )
        hint_text = f", entity_id: {object_id_hint}" if object_id_hint else ""
        claim_label = f" [{claim_id}]" if claim_id else ""
        parts.append(
            f"{i}.{claim_label} {subj} → {pred} → {obj} "
            f"[{obj_type}, {specificity}{hint_text}] (confidence: {conf})"
        )
        _append_fact_claim_evidence(parts, claim)
    parts.append("")


def _append_fact_claim_evidence(parts: list[str], claim: dict[str, Any]) -> None:
    evidence = claim.get("evidence_text", "")
    if evidence:
        parts.append(f'   Evidence: "{evidence}"')
    event_ids = claim.get("supporting_event_ids", [])
    if event_ids:
        parts.append(f"   Events: {', '.join(event_ids)}")


def _append_phase1_resolved_refs(
    parts: list[str],
    resolved_refs: list[dict[str, Any]],
) -> None:
    if not resolved_refs:
        return
    parts.append("### Resolved References")
    for ref in resolved_refs:
        surface = ref.get("surface", "")
        resolved = ref.get("resolved_ref") or "unresolved"
        parts.append(f'- "{surface}" → {resolved}')
    parts.append("")


def _append_evidence_packet(
    parts: list[str],
    evidence_packet: dict[str, Any] | None,
) -> None:
    if not evidence_packet:
        return
    parts.append("## Deterministic Evidence Packet")
    parts.append("No LLM was used to gather this packet; it is retrieval and statistics only.")
    _append_packet_candidate_refs(parts, evidence_packet.get("candidate_refs") or [])
    _append_packet_history_matches(parts, evidence_packet.get("history_contexts") or [])
    _append_packet_history_support(parts, evidence_packet.get("history_support") or [])
    _append_packet_related_edges(parts, evidence_packet.get("related_edges") or [])
    _append_packet_assertion_state(parts, evidence_packet.get("existing_assertions") or [])
    _append_packet_guardrails(parts, evidence_packet.get("promotion_guardrails") or [])


def _append_packet_candidate_refs(parts: list[str], refs: list[dict[str, Any]]) -> None:
    if not refs:
        return
    parts.append("### Current Candidate Anchors")
    for ref in refs[:12]:
        kind = ref.get("kind", "?")
        label = ref.get("label") or ref.get("id") or "?"
        ref_type = ref.get("type") or "unknown"
        predicate = ref.get("predicate")
        suffix = f", predicate={predicate}" if predicate else ""
        parts.append(f"- {kind}: {label} [{ref_type}{suffix}]")
    parts.append("")


def _append_packet_history_matches(
    parts: list[str],
    history_items: list[dict[str, Any]],
) -> None:
    if not history_items:
        return
    parts.append("### History Matches")
    for item in history_items[:3]:
        event_id = item.get("event_id", "?")
        name = item.get("canonical_name") or item.get("matched_text") or "matched item"
        content = item.get("content", "")
        parts.append(f"- [#{event_id}] {name}: {content}")
    parts.append("")


def _append_packet_history_support(
    parts: list[str],
    history_support: list[dict[str, Any]],
) -> None:
    if not history_support:
        return
    parts.append("### History Support Counts")
    for item in history_support[:12]:
        label = item.get("label") or item.get("id") or "matched item"
        ref_type = item.get("type") or "unknown"
        count = int(item.get("history_event_count", 0) or 0)
        latest = _format_ts(float(item.get("latest_timestamp", 0.0) or 0.0))
        parts.append(f"- {label} [{ref_type}] seen in {count} previous events, latest={latest}")
    parts.append("")


def _append_packet_related_edges(parts: list[str], related_edges: list[dict[str, Any]]) -> None:
    if not related_edges:
        return
    parts.append("### Related Graph Evidence")
    for edge in related_edges[:12]:
        triple_id = edge.get("triple_id", "?")
        predicate = edge.get("predicate", "?")
        object_id = edge.get("object_id", "?")
        object_type = edge.get("object_type", "?")
        source_type = edge.get("source_type") or "unknown_source"
        obs_count = int(edge.get("observation_count", 0) or 0)
        event_count = int(edge.get("evidence_event_count", 0) or 0)
        parts.append(
            f"- [{triple_id}] {predicate} {object_id} [{object_type}] "
            f"from {source_type}, observed={obs_count}x, events={event_count}"
        )
    parts.append("")


def _append_packet_assertion_state(
    parts: list[str],
    packet_assertions: list[dict[str, Any]],
) -> None:
    if not packet_assertions:
        return
    parts.append("### Existing Assertion State")
    for assertion in packet_assertions[:8]:
        assertion_id = assertion.get("assertion_id", "?")
        trait = assertion.get("trait_name", "?")
        value = assertion.get("trait_value", "?")
        family = assertion.get("trait_family", "?")
        state = assertion.get("validation_state", "?")
        source = assertion.get("source_domain", "?")
        parts.append(
            f"- [{assertion_id}] {family}/{trait} = {value} "
            f"(state={state}, source={source})"
        )
    parts.append("")


def _append_packet_guardrails(parts: list[str], guardrails: list[str]) -> None:
    if not guardrails:
        return
    parts.append("### Promotion Guardrails")
    for guardrail in guardrails:
        parts.append(f"- {guardrail}")
    parts.append("")


def _append_phase2_focal_subject(parts: list[str], focal_subject: dict[str, Any]) -> None:
    focal_ref = focal_subject.get("entity_ref") or "user:self"
    parts.append(f"## Focal Subject: {focal_ref}")
    parts.append("")


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
