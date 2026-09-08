"""Prompt templates for L2 extraction and reconcile helpers."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any
from zoneinfo import ZoneInfo

from magi.events.first_context import first_context_from_metadata

from magi.utils.calendar_timezone import calendar_timezone_id_from_metadata
from ...models import L2EventWindow
from ...entity_types import render_entity_type_instructions
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

{entity_type_instructions}

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
6. A shared name, alias, or category is only a candidate signal, never identity proof. Reuse an Existing Entity ID only when current context and its identity evidence identify the same referent. Same-named companies, brands, bands, works and people can be distinct. If identity is ambiguous, leave resolved_id null and is_new false; do not choose arbitrarily. If the referent is clearly distinct from all candidates, mark is_new true. Do not change an existing entity type merely to make a match.
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

17. Every fact claim must include `assertion_mode`. Interpret the complete source message and local context, not isolated keywords. Use `asserted` only when the speaker actually asserts the proposition. Use `quoted` for another speaker's statement, `hypothetical` for an imagined example, `conditional` when an unrepresented condition limits the proposition, `question` or `request` for a question/task without a self fact, and `uncertain` when the speaker does not commit. The host retains only asserted propositions; non-asserted source text remains in L1. Never remove a condition or negation to make a candidate asserted. A title containing first-person words (for example 《我的世界》) is an entity name, not a quoted self-report. A communication preference such as "请叫我小明" asserts a preferred address even though it is phrased as a request.
18. You own the linguistic interpretation of `fact_kind`, `temporal_cue`, `assertion_mode`, and contextual confirmation. The host validates source authorship, exact quotes, bounded antecedents, identifiers, and typed fields; it does not correct your interpretation with phrase lists. Preserve clause-local meaning: a time phrase about an adjacent activity must not change a general preference. Weak acknowledgements must remain `uncertain`, regardless of confidence.

19. Every entity candidate must include `referent_kind`: `entity` for a named object or reusable concept/activity, `proposition` for a whole assertion or plan, and `unknown` when unresolved. Only `entity` candidates can enter the catalog. Decide from context, not name length, alphabet, or an action verb: short names, numeric work titles, acronyms, and names with sentence-like wording can be valid entities. A plan without a separately named referent belongs in fact_claims. Alias signals must explicitly denote the same entity in the source, not its platform, publisher, or related object.

## Output Format
Return JSON only:
```json
{
  "entities": [
    {
      "surface": "original text span",
      "referent_kind": "entity|proposition|unknown",
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
      "object_ref": "entity surface or Existing Entity ID for an entity role; exact evidence value for a literal or goal role",
      "object_type": "enum from allowed types",
      "fact_kind": "explicit_fact|stable_preference|public_topology|future_intent|interaction_evidence",
      "temporal_cue": "one_off|recent|recurring|stable|unspecified",
      "raw_time_expression": "exact evidence substring or empty string",
      "polarity": "positive|negative",
      "specificity": "concrete|underspecified",
      "evidence_text": "supporting quote",
      "confidence": 0.0,
      "supporting_event_ids": ["current event IDs"],
      "assertion_mode": "asserted|quoted|hypothetical|conditional|question|request|uncertain",
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

### Mixed statements and questions
When a user states a fact and then asks a question, extract only the asserted clause.
"我喜欢爵士乐，你推荐什么？" supports "我喜欢爵士乐"; the question is not evidence.
Questions, hypotheses, and quoted statements from other speakers cannot establish a self fact.

### Preference scope
A favorable evaluation of one meal, visit, or attempt is not a durable preference.
"午饭吃了螺蛳粉，比上次好吃" is one-off evidence, not stable LIKES.
"我喜欢螺蛳粉" is a direct general preference without requiring words like always.
"最近喜欢螺蛳粉" is recent; "今天想吃螺蛳粉" is an intent, not a preference.

### Polarity
Polarity negates the predicate; it does not label negative sentiment.
"我讨厌鱼" = DISLIKES + positive; "我并不讨厌鱼" = DISLIKES + negative.
"我不住在杭州" = LIVES_IN + negative. Never invent an opposite predicate.
Preserve any temporal qualifier on a negative claim.

### Example — correct extraction:
Input: [USER] 我特别喜欢吃螺蛳粉
Output entities: [{"surface": "螺蛳粉", "entity_type": "food", "specificity": "concrete", ...}]
Output fact_claims: [{"subject_ref": "user:self", "predicate": "LIKES", "object_ref": "螺蛳粉", "object_type": "food", "specificity": "concrete", ...}]

### Example — do NOT extract:
Input: [USER] 你还记得我喜欢什么天气吗？
Output: {"entities": [], "fact_claims": [], "diagnostics": {"entity_status": "none"}}
Reason: This is a recall question, not a preference statement.
""".replace("{entity_type_instructions}", render_entity_type_instructions())


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
    event_ref_labels: dict[str, str] | None = None,
) -> str:
    """Render a Markdown-formatted Phase 1 extraction prompt."""
    parts: list[str] = []
    ref_labels = event_ref_labels or {}

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
        parts.append(f"### [{role}] [#{ref_labels.get(event.event_id, event.event_id)}] {ts}")
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
                f"- [#{ref_labels.get(event_id, event_id)}] question_id={context['question_id']}: {context['question_text']}"
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
            parts.append(f"- {eid} [stored_type={etype}] {cname}{alias_str}")
            for evidence in entity.get("identity_evidence", [])[:3]:
                parts.append(f"  Historical identity context (not new evidence): {evidence}")
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
                event_label = f" [#{ref_labels.get(event_id, event_id)}]" if event_id else ""
                sequence_label = f" [seq={sequence}]" if sequence is not None else ""
                parts.append(f"- [{role}]{event_label}{sequence_label} {content}")
        parts.append("")

    # History contexts (cross-session)
    if event_window.history_contexts:
        parts.append("## History Context (cross-session)")
        for ctx in event_window.history_contexts:
            ts = _format_ts(ctx.timestamp)
            matched = f", matched_entity: {ctx.canonical_name}" if ctx.canonical_name else ""
            session_label = "different session; interpretation context only"
            parts.append(f"### ({session_label}{matched}, {ts})")
            parts.append(str(ctx.content).strip())
            parts.append("")

    return "\n".join(parts)


__all__ = [
    "PHASE1_EXTRACT_SYSTEM_PROMPT",
    "ENTITY_RESOLUTION_SYSTEM_PROMPT",
    "render_phase1_extract_prompt",
    "render_entity_resolution_prompt",
    "BATCH_ENTITY_RESOLUTION_SYSTEM_PROMPT",
    "render_batch_entity_resolution_prompt",
]
