"""Prompt templates for L2 two-phase extraction and reconcile helpers."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any
from zoneinfo import ZoneInfo

from magi.events.first_context import first_context_from_metadata

from magi.utils.calendar_timezone import calendar_timezone_id_from_metadata
from ...models import L2EventWindow
from .workflows import (
    BATCH_ENTITY_RESOLUTION_SYSTEM_PROMPT,
    ENTITY_RESOLUTION_SYSTEM_PROMPT,
    render_batch_entity_resolution_prompt,
    render_entity_resolution_prompt,
)

# ---------------------------------------------------------------------------
# Phase 1 — Extract & Resolve
# ---------------------------------------------------------------------------

PHASE1_EXTRACT_SYSTEM_PROMPT = """You are a memory extraction engine for a personal AI assistant.

Your task: identify entities, resolve references, and extract factual claims from user messages and trusted external observations.

## Allowed Entity Types
- `person` — an individual human.
- `place` — a named physical or geographic location.
- `organization` — a formal company, institution, or organization.
- `group` — a named band, team, community, or other collective.
- `product` — a named non-software commercial product.
- `food` — a specific dish, drink, snack, or ingredient.
- `software` — an app, service, platform, operating system, or database.
- `technology` — a language, framework, algorithm, model, standard, or protocol.
- `hardware` — a physical device or computing component.
- `virtual_object` — a specific digital asset, account, document, or virtual item.
- `project` — a named, reusable body of work, not a one-time action sentence.
- `activity` — a reusable practice or activity, not a complete plan or action clause.
- `event` — a named or clearly bounded occurrence.
- `animal` — an animal species or non-personal animal.
- `pet` — a specific companion animal.
- `health_metric` — a named measurable health quantity.
- `concept` — an abstract idea, quality, style, or preference.
- `skill` — a learnable and reusable capability.
- `media` — a named song, album, film, book, podcast, or creative work.
- `topic` — a reusable subject area, not a sentence about that subject.
- `weather_state` — a specific weather condition.
- `location_state` — a structured location or movement state.
- `time_point` — a specific named temporal point or anchor.
- `session_topic` — the bounded subject of a conversation session.
- `presence` — a structured presence or availability state.
- `other` — a concrete reusable entity that fits no more specific type.

### Entity Type Aliases (map to canonical type)
dish/drink/snack/ingredient → food | app/application/service/platform/os/database → software | language/framework/algorithm/model → technology | device/console/phone → hardware | idea/principle/theory → concept

### Entity Type Selection
Prefer the most specific allowed entity type supported by the current evidence.
- Use `group` for named bands, teams, communities, and collectives.
- Use `media` for named songs, albums, films, books, podcasts, and creative works.
- Use `concept` for abstract qualities, styles, and preferences.
- Use `other` only when no other allowed type fits; never use it merely because the entity is unfamiliar.

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
5. If a pronoun, short answer, or vague reference appears (e.g., "那个", "它", "这种", "the one", "there"), use only the bounded Recent Context frame to interpret it. Recent Context is interpretation context, not standalone evidence. History Context may help identify an already known entity, but it must never supply a new claim.
6. If a mentioned entity matches an Existing Entity by name, alias, or clear semantic equivalence, use its canonical ID. Otherwise mark as new.
7. Each entity must include a specificity rating: "concrete" for specific items, "underspecified" for vague/category-level references.
8. Preserve the evidence language and script for every entity type, including activity, concept, topic, event, and other abstract entities. `surface` must be an exact current-evidence span. `normalized_name` may normalize spelling, spacing, or punctuation only while retaining every letter script used by `surface`; never translate, romanize, transliterate, summarize, or slugify it. This applies to common nouns and phrases as well as proper nouns. The protocol rules and JSON schema are instructions, not evidence: never emit an entity surface or claim value copied from them. Add an item to `alias_signals` only when that exact alternate name appears in a current evidence message. Existing catalog aliases may be used for matching but must not be copied into output unless current evidence also contains them.
9. Extract only concrete, named, reusable entities. Pronouns and vague placeholders such as "他", "她", "它", "这个", "那个", "this one", "that one", "the file", "the image", generic "app", or generic "PDF" may appear only in `resolved_refs`; do not emit them as `entities` unless they are confidently resolved to a specific existing entity or asset with a concrete canonical name.
   New entity names must be reusable noun-like catalog labels. Do not emit complete sentences, long action clauses, or plans containing multiple actions as entities. Keep complete planned action text only in the Claim `object_ref`; independently reusable nested places, projects, skills, activities, or named objects may still be entities.
10. For web pages and external-source metadata, never use a URL domain/path slug as the canonical entity name when the title or source text contains a readable subject name. Treat domains and platforms as provenance or separate platform entities, not as replacements for the content entity.
11. Addressing instructions such as "叫我子涵" or "call me Zihan" are communication-profile signals. Emit one fact claim with `predicate = "PREFERRED_FORM_OF_ADDRESS"`, `object_ref` set to the requested name, and `object_type = "concept"`. Do NOT turn the requested name into a LIKES, DISLIKES, INTERESTED_IN, KNOWS, or other graph relationship.
12. Explicit self-profile facts such as real name, birthday, birth year, age, preferred language, or preferred communication style should use the matching profile-signal predicate, not graph predicates.
13. A concrete object_ref should also appear in entities when it names a reusable catalog object. Assertion-only literal values and complete `PLANS_TO` action text do not require an entity. For a goal, keep the complete planned action in `object_ref`; extract only independently reusable nested places, software, projects, skills, or other named objects as entities. A context-only entity may be used only by its Existing Entity ID; do not create a new entity from Recent Context or History Context.
14. Every fact claim must include `evidence_text` as an exact quote copied from a current message under Messages to Analyze. `supporting_event_ids` must contain only the current message IDs that contain that exact quote. Every claim must also declare one `evidence_mode`:
    - `direct`: the current quote states the complete claim. `antecedent_event_ids` must be empty.
    - `confirmation`: the current user quote is an explicit, unambiguous yes/no confirmation of the immediately preceding assistant proposition. Cite exactly that assistant event in `antecedent_event_ids`. Weak acknowledgements such as "嗯", "maybe", or "可能吧" are not confirmation.
    - `clarification`: the current short reply adds a concrete detail to the immediately preceding user statement, optionally through the immediately following assistant question. Cite the nearest user event and the immediately preceding assistant event, in chronological order, in `antecedent_event_ids`.
   Recent Context is interpretation context, not standalone evidence. Never use older context, History Context, or assistant wording without explicit current user confirmation. If the current message does not authorize the claim under one of these modes, omit it.
15. Every fact claim must include `temporal_cue`, grounded in explicit wording only: `one_off` for explicitly single-use wording, `recent` for wording such as recently/currently/these days, `recurring` for often/every week/repeatedly, `stable` for always/for years/long-term, and `unspecified` when no linguistic time cue is present. Do not infer a stable cue from the predicate or fact kind. Do not use temporal_cue to choose retention, expiry, or lifecycle; the host owns that policy.
16. Every fact claim must include `raw_time_expression`. Copy only the exact time phrase from `evidence_text` (for example `明天`, `2026-08-15`, or `next month`), preserving its original text. Use an empty string when the evidence has no explicit time phrase. Never calculate dates, add a year, or rewrite a relative expression; the host owns deterministic resolution.

## Output Format
Return JSON only:
```json
{
  "entities": [
    {
      "surface": "original text span",
      "normalized_name": "source-language normalized name",
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
      "fact_kind": "explicit_fact|stable_preference|public_topology|future_intent|interaction_evidence",
      "temporal_cue": "one_off|recent|recurring|stable|unspecified",
      "raw_time_expression": "exact evidence substring or empty string",
      "polarity": "positive|negative",
      "specificity": "concrete|underspecified",
      "evidence_text": "supporting quote",
      "confidence": 0.0,
      "supporting_event_ids": ["current event IDs"],
      "evidence_mode": "direct|clarification|confirmation",
      "antecedent_event_ids": ["bounded Recent Context event IDs"]
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


PHASE2_INTEGRATE_SYSTEM_PROMPT = """You write optional natural-language summaries for a personal memory system.

Phase 1 has already extracted and grounded the facts. The host deterministically owns every semantic decision, including routes, graph edges, assertion families, trait codes, slots, values, confidence, promotion, conflicts, time horizons, and lifecycle. Your output can improve wording only. It can never create, suppress, merge, or alter a memory.

## Rules
1. Every output item must cite one or more `claim_id` values shown in Phase 1. Never cite raw event IDs or invent a claim ID.
2. Claims in one item must describe the same subject, target, value, and time window. When uncertain, emit separate summaries or omit them.
3. Preserve the evidence language and script. Do not translate, romanize, transliterate, slugify, or expose internal identifiers.
4. Keep each summary factual and concise. Do not infer causes, personality, stability, currentness, or intent beyond the cited Claims.
5. Do not return entities, record IDs, families, traits, slots, routes, targets, values, confidence, lifecycle, conflict actions, or any undeclared fields.
6. It is valid to return an empty `summaries` list. The host supplies deterministic fallback wording.

## Output Format
Return JSON only:
```json
{
  "summaries": [
    {
      "claim_ids": ["exact Phase 1 claim IDs"],
      "text": "concise grounded summary, max 500 chars"
    }
  ]
}
```
"""


def build_phase2_integrate_system_prompt(user_language: str | None = None) -> str:
    """Return the Phase 2 system prompt with an explicit language directive.

    When ``user_language`` is supplied (e.g. "zh-CN", "en", "ja"), the prompt
    is suffixed with a binding instruction for every summary.

    When ``user_language`` is None, returns the baseline prompt unchanged so
    the LLM falls back to inferring language from evidence text.
    """
    if not user_language:
        return PHASE2_INTEGRATE_SYSTEM_PROMPT
    return PHASE2_INTEGRATE_SYSTEM_PROMPT + (
        "\n\n## Language directive\n"
        f"The user's primary language is `{user_language}`. Write every "
        "summary in that language unless the cited evidence explicitly uses a "
        "foreign term that should be preserved."
    )


# ---------------------------------------------------------------------------
# Helper: format timestamp for prompts
# ---------------------------------------------------------------------------


def _format_ts(ts: float, *, metadata: dict[str, Any] | None = None) -> str:
    if ts <= 0:
        return "unknown"
    try:
        timezone_id = calendar_timezone_id_from_metadata(metadata)
        event_timezone = ZoneInfo(timezone_id) if timezone_id is not None else timezone.utc
        return datetime.fromtimestamp(ts, tz=event_timezone).isoformat(
            sep=" ",
            timespec="seconds",
        )
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
    user_language: str | None = None,
    evidence_scripts: tuple[str, ...] = (),
) -> str:
    """Render a Markdown-formatted Phase 1 extraction prompt."""
    parts: list[str] = []

    if extraction_instructions:
        parts.append("## Source-Specific Instructions")
        parts.append(extraction_instructions.strip())
        parts.append("")

    parts.append("## Language and Script Contract")
    parts.append(
        f"- Configured user language: `{user_language or 'unknown'}`. This is context "
        "for interpreting the user, not permission to translate evidence-derived fields."
    )
    script_label = ", ".join(evidence_scripts) if evidence_scripts else "unknown"
    parts.append(f"- Letter scripts detected in current evidence: {script_label}.")
    parts.append(
        "- Keep JSON keys, enum values, and protocol identifiers in English. Keep "
        "`surface`, `normalized_name`, `object_ref`, `evidence_text`, and "
        "`raw_time_expression` in the current evidence language and script."
    )
    parts.append(
        "- The host verifies entity surfaces and aliases against current evidence and "
        "restores translated normalized names to their source surface."
    )
    parts.append("")

    # Messages to analyze
    parts.append("## Messages to Analyze")
    for event in event_window.events:
        role = str(event.author_type or "user").upper()
        ts = _format_ts(event.timestamp, metadata=event.metadata_json)
        parts.append(f"### [{role}] [#{event.event_id}] {ts}")
        parts.append(str(event.content).strip())
        parts.append("")

    first_context_questions: list[tuple[str, dict[str, str]]] = []
    for event in event_window.events:
        context = first_context_from_metadata(event.metadata_json)
        if context is not None:
            first_context_questions.append((event.event_id, context))
    if first_context_questions:
        parts.append("## Conversation Question Context (not evidence)")
        parts.append(
            "Use this only to interpret a short or elliptical answer. The question is not a user claim and must never be extracted as evidence."
        )
        for event_id, context in first_context_questions:
            parts.append(
                f"- [#{event_id}] question_id={context['question_id']}: {context['question_text']}"
            )
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
            event_id = str(msg.get("event_id", "")).strip()
            sequence = msg.get("session_seq")
            if content:
                event_label = f" [#{event_id}]" if event_id else ""
                sequence_label = f" [seq={sequence}]" if sequence is not None else ""
                parts.append(f"- [{role}]{event_label}{sequence_label} {content}")
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
    summary_instructions: str | None = None,
) -> str:
    """Render the optional Phase 2 summary prompt."""
    parts: list[str] = []

    _append_summary_instructions(parts, summary_instructions)
    _append_phase1_results(parts, phase1_result)
    _append_phase2_focal_subject(parts, focal_subject)

    return "\n".join(parts)


def _append_summary_instructions(
    parts: list[str],
    summary_instructions: str | None,
) -> None:
    if not summary_instructions:
        return
    instructions = str(summary_instructions).strip()
    if not instructions:
        return
    parts.append("## Source-Specific Summary Instructions")
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
        fact_kind = claim.get("fact_kind", "?")
        temporal_cue = claim.get("temporal_cue", "unspecified")
        evidence_mode = claim.get("evidence_mode", "direct")
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
            f"[{obj_type}, {specificity}, fact_kind={fact_kind}, "
            f"temporal_cue={temporal_cue}, evidence_mode={evidence_mode}{hint_text}] "
            f"(confidence: {conf})"
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
    antecedent_event_ids = claim.get("antecedent_event_ids", [])
    if antecedent_event_ids:
        parts.append(f"   Antecedents: {', '.join(antecedent_event_ids)}")


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
    "ENTITY_RESOLUTION_SYSTEM_PROMPT",
    "render_phase1_extract_prompt",
    "render_phase2_integrate_prompt",
    "render_entity_resolution_prompt",
    "BATCH_ENTITY_RESOLUTION_SYSTEM_PROMPT",
    "render_batch_entity_resolution_prompt",
]
