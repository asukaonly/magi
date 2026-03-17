# L2 Unified Extraction Ontology Plan

> **For agentic workers:** REQUIRED: Use superpowers:executing-plans or superpowers:subagent-driven-development before implementation. This document defines the ontology, extraction-profile, and validation boundaries for the next L2 extraction refactor.

**Goal:** Replace the current multi-step `mention LLM + graph rules + assertion LLM` path with a single extraction LLM pass that returns `mentions`, `graph_candidates`, and `assertion_candidates`, while preserving deterministic engineering controls for evidence governance, type normalization, profile-based source restrictions, and graph/assertion validation.

**Architecture:** Keep `EvidenceClassifier` and `PolicyResolver` as the hard gate ahead of L2. After a write is allowed, build a source-aware `ExtractionProfile`, call the unified extraction prompt once, normalize and validate all candidate outputs, then persist graph/assertion artifacts through the existing entity catalog, conflict matrix, reconcile, and snapshot pipeline.

**Tech Stack:** Python 3.10+, asyncio, existing `UnifiedMemoryStore`, `L2Pipeline`, `L2EntityCatalog`, `L2CognitionStore`, `ScenarioLLMPool`, pytest.

---

## Scope Guardrails

- Keep the current evidence-governance gate intact; assistant freeform, assistant quotes, and assistant tool-grounded events remain blocked before extraction.
- The unified extraction LLM may propose candidates, but it never writes directly to storage.
- All entity types and predicates must be validated against registry allowlists.
- Plugin and sensor producers must be able to narrow allowed entity types, predicates, and assertion families through extraction profiles.
- Unknown entity types normalize to `other`.
- Absence of extracted entities is represented as a top-level extraction diagnostic (`entity_status=none`), not as a per-mention entity type.
- Preserve existing contradiction, reconcile, and snapshot stages.

## Source Documents To Re-read Before Implementation

- `docs/project-overview.md`
- `docs/product-configuration-guide.md`
- `docs/task-agent-runtime-architecture.md`
- `docs/memory-system-design.md`
- `docs/superpowers/plans/2026-03-17-l2-cognition-write-pipeline.md`
- `docs/superpowers/plans/2026-03-17-l2-evidence-governance.md`

---

## Problem Statement

The current L2 extraction path has three problems:

1. graph facts rely too heavily on brittle keyword rules, so valid relations such as `DISLIKES 西湖醋鱼` can be missed even when entity extraction succeeds
2. entity types are not constrained tightly enough in prompts, so the LLM may emit values like `dish` while downstream code only recognizes `food`
3. multiple serial LLM calls increase latency for each eligible event

The refactor should solve these by:

- moving to a single LLM extraction pass per event window
- constraining entity and predicate vocabularies in the prompt
- normalizing outputs through a shared ontology registry
- allowing source-specific extraction profiles to narrow what a producer may emit

---

## Target Runtime Flow

```text
L1 stored event
  -> EvidenceClassifier
  -> PolicyResolver
  -> ExtractionProfileResolver
  -> UnifiedExtractionLLM
       -> mentions
       -> graph_candidates
       -> assertion_candidates
       -> diagnostics
  -> EntityTypeNormalizer / PredicateValidator
  -> Entity catalog / alias resolution
  -> Graph upsert
  -> Assertion upsert
  -> Contradiction hints
  -> Reconcile
  -> Snapshot refresh
```

---

## Unified Extraction Contract

The single extraction prompt should return JSON using this shape:

```json
{
  "mentions": [
    {
      "mention_text": "string",
      "normalized_surface": "string",
      "entity_type": "enum",
      "canonical_name_hint": "string or null",
      "alias_signals": ["string"],
      "evidence_text": "string",
      "confidence": 0.0
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
      "confidence": 0.0
    }
  ],
  "assertion_candidates": [
    {
      "entity_ref": "string",
      "entity_type": "enum",
      "trait_family": "enum",
      "trait_name": "string",
      "trait_value": "string or JSON string",
      "inference_depth": "topology_only|defensive_psychology",
      "volatility_index": 0.0,
      "confidence": 0.0,
      "validation_state": "tentative",
      "evidence_texts": ["string"],
      "supporting_event_ids": ["string"]
    }
  ],
  "diagnostics": {
    "entity_status": "found|none"
  }
}
```

### Contract Rules

- `mentions` may be empty.
- `entity_status=none` means the extractor found no usable entity mentions.
- `entity_type` must come from the allowed entity type enum; invalid values normalize to `other`.
- `predicate` must come from the allowed predicate enum; invalid values are rejected.
- `graph_candidates` and `assertion_candidates` are candidates only and remain subject to policy/profile validation.

---

## Entity Type Registry

### Canonical Entity Types

- `person`
- `place`
- `organization`
- `group`
- `product`
- `food`
- `software`
- `technology`
- `hardware`
- `virtual_object`
- `project`
- `activity`
- `event`
- `animal`
- `pet`
- `health_metric`
- `concept`
- `skill`
- `media`
- `topic`
- `other`

### Boundary Definitions

#### `person`
Human individuals. Use for named people, contacts, family members, doctors, coworkers, and public figures.

#### `place`
Physical locations, cities, venues, countries, landmarks, and geographical areas.

#### `organization`
Formal institutions, companies, schools, agencies, nonprofits, publishers, or teams functioning as organizations.

#### `group`
Informal or semi-formal collectives that are not best modeled as an organization. Example: a friend group, a game guild, a chat group.

#### `product`
Consumer-facing products, goods, brands, pages, or sites when the source profile treats them as visitable/product entities. This is especially useful for browser history sources.

#### `food`
A coarse food taxonomy for dishes, drinks, snacks, ingredients, cuisines-as-food-items, and named edible items. First implementation should map `dish`, `drink`, `snack`, and `ingredient` into `food`.

#### `software`
Applications, operating systems, databases, client software, hosted platforms, and user-facing services. Examples: `macOS`, `SQLite`, `微信`, `GitHub` when treated as a software platform.

#### `technology`
Programming languages, frameworks, protocols, algorithms, model families, architectural patterns, and technical abstractions. Examples: `Rust`, `React`, `大语言模型`.

#### `hardware`
Physical devices and peripherals. Examples: `Steam Deck`, `iPhone 16 Pro Max`, `显示器`.

#### `virtual_object`
Purely virtual game or online-world artifacts. Examples: in-game cards, mods, character skins, account identifiers, server personas.

#### `project`
A bounded engineering effort, initiative, or plan with persistence beyond a single session. Examples: `AI 日记应用开发`, `QQ 群消息分析工具`.

#### `activity`
Actor-centric actions or recurring practices. Examples: `面试`, `旅行`, `健身`.

#### `event`
Objective or public happenings best treated as standalone events, especially when multiple actors may attend or reference them.

#### `animal`
General animal entities not clearly modeled as an owned/related pet.

#### `pet`
A user- or person-associated companion animal. Keep separate because relation semantics such as owner, feeder, or veterinarian differ from `person`.

#### `health_metric`
A measurable physiological metric or status concept such as `体重`, `身高`, `血压`. This type often pairs with numeric values and needs metric-specific predicates.

#### `concept`
Non-technical abstract ideas, principles, philosophies, and conceptual constructs. Examples: `第一性原理`, `心智理论`.

#### `skill`
A learned capability or practical competence. Examples: `后端开发`, `预算管理`.

#### `media`
Books, films, songs, videos, podcasts, and named media works.

#### `topic`
Discussion topics, interest areas, domains, categories, or themes that are not better modeled as a concrete technology, concept, or media item.

#### `other`
Fallback type for valid mentions that cannot be mapped safely into the known taxonomy.

### Top-Level `none`

- `none` is not a valid `entity_type`.
- `none` only appears in diagnostics when no entity mention was extracted.

---

## Entity Type Normalization

### Normalization Rules

If the unified extraction LLM outputs an entity type outside the allowed registry:

1. apply source-profile aliases first
2. apply global normalization aliases second
3. if still unknown, coerce to `other`

### Recommended Global Type Aliases

```json
{
  "dish": "food",
  "drink": "food",
  "snack": "food",
  "ingredient": "food",
  "meal": "food",
  "cuisine_item": "food",

  "app": "software",
  "application": "software",
  "service": "software",
  "platform": "software",
  "os": "software",
  "database": "software",

  "framework": "technology",
  "language": "technology",
  "library": "technology",
  "algorithm": "technology",
  "model": "technology",
  "protocol": "technology",

  "device": "hardware",
  "console": "hardware",
  "phone": "hardware",
  "computer": "hardware",
  "monitor": "hardware",
  "peripheral": "hardware",

  "idea": "concept",
  "principle": "concept",
  "theory": "concept",

  "website": "product",
  "page": "product",

  "unknown": "other"
}
```

---

## Predicate Whitelist

### Canonical Predicates

#### Status and preference
- `LIKES`
- `DISLIKES`
- `INTERESTED_IN`

#### Action and trajectory
- `VISITED`
- `LIVES_IN`
- `PLANS_TO`
- `ATTENDED`

#### Social and organization
- `WORKS_AT`
- `MEMBER_OF`
- `INTERACTED_WITH`
- `KNOWS`
- `FAMILY_OF`

#### Capability and creation
- `USES`
- `OWNS`
- `CREATES`
- `PROFICIENT_IN`

#### Metric linkage
- `HAS_METRIC`

### Predicate Semantics

#### `LIKES` / `DISLIKES`
Stable or explicit object preference relations. Use when the user or entity clearly expresses like/dislike toward a concrete object.

#### `INTERESTED_IN`
Current attention, exploration, or learning intent. This is intentionally weaker and more time-local than `LIKES`.

#### `VISITED`
Past visit or access relation. For browser-history sources, this may represent visiting a product/page. For physical-world sources, it represents presence at a place.

#### `LIVES_IN`
Current residence relation, subject to exclusivity conflict rules.

#### `PLANS_TO`
Future intent toward an activity, event, place, or project. Use only for explicit plan/intent text.

#### `ATTENDED`
Past participation in an event or activity.

#### `WORKS_AT`
Current or recent work affiliation, subject to exclusivity rules when modeled as current employment.

#### `MEMBER_OF`
Membership relation for groups and organizations.

#### `INTERACTED_WITH`
Observable interaction relation that does not require the stronger semantic claim of `KNOWS`.

#### `KNOWS`
A stronger social familiarity relation than `INTERACTED_WITH`. Use conservatively.

#### `FAMILY_OF`
Kinship or family relation.

#### `USES`
Use of software, hardware, tools, or products.

#### `OWNS`
Ownership of assets, devices, pets, or accounts where ownership is explicit.

#### `CREATES`
Primary creation or authorship relation to a project, media item, software artifact, or virtual object.

#### `PROFICIENT_IN`
Capability relation between a person and a skill.

#### `HAS_METRIC`
Links a subject to a `health_metric` concept. Numeric values should live in metric payloads or companion attributes, not in the predicate itself.

---

## Predicate Compatibility Matrix

The validator should reject predicate/object-type combinations that fall outside the allowed matrix.

| Predicate | Allowed object types |
|---|---|
| `LIKES` | `food`, `product`, `place`, `media`, `topic`, `technology`, `activity`, `software`, `hardware`, `virtual_object`, `project` |
| `DISLIKES` | `food`, `product`, `place`, `media`, `topic`, `technology`, `activity`, `software`, `hardware`, `virtual_object`, `project` |
| `INTERESTED_IN` | `topic`, `technology`, `skill`, `project`, `activity`, `media`, `concept` |
| `VISITED` | `place`, `product`, `organization`, `event`, `activity` |
| `LIVES_IN` | `place` |
| `PLANS_TO` | `activity`, `event`, `project`, `place` |
| `ATTENDED` | `event`, `activity` |
| `WORKS_AT` | `organization`, `project` |
| `MEMBER_OF` | `group`, `organization` |
| `INTERACTED_WITH` | `person`, `group`, `organization`, `pet`, `animal`, `software`, `product` |
| `KNOWS` | `person` |
| `FAMILY_OF` | `person`, `pet` |
| `USES` | `software`, `hardware`, `product`, `technology` |
| `OWNS` | `hardware`, `product`, `pet`, `virtual_object`, `software` |
| `CREATES` | `project`, `media`, `software`, `virtual_object`, `product` |
| `PROFICIENT_IN` | `skill`, `technology` |
| `HAS_METRIC` | `health_metric` |

### Subject Compatibility Defaults

Unless a source profile narrows the allowed subject space further, the validator should allow these subject types:

- `person`
- `user`
- `organization` for a limited subset (`CREATES`, `OWNS`, `USES`, `MEMBER_OF` when nesting makes sense)
- `group` for limited social predicates where the source explicitly supports it

All other subject types should be treated as opt-in, not default.

---

## Graph vs Assertion Boundary

### Graph candidates represent

- explicit relation facts
- object-centric preferences
- public or observable topology
- future intent when stated directly
- durable, queryable triples that benefit from conflict resolution

### Assertion candidates represent

- internal state
- emotional state or stress
- engagement level
- group atmosphere
- relationship change interpretations
- triggers or sensitivities
- higher-order preference profiles derived from repeated facts

### Allowed assertion trait families

- `stress`
- `mood`
- `engagement`
- `trigger`
- `relationship_shift`
- `group_atmosphere`
- `public_sentiment`
- `preference_profile`
- `taste_profile`

### Dual-write rules

#### Allowed dual-write
A single event may produce both:

- a low-level graph fact, and
- a higher-order assertion

Example:
- `graph`: `user DISLIKES food:west_lake_vinegar_fish`
- `assertion`: `taste_profile = avoids_vinegar_heavy_dishes`

#### Disallowed dual-write
Do not emit an assertion that merely restates the same low-level graph fact.

Reject or collapse patterns such as:
- `graph`: `user DISLIKES food:west_lake_vinegar_fish`
- `assertion`: `taste_preference = dislikes_food:west_lake_vinegar_fish`

The assertion layer should hold an abstraction, not a duplicate leaf fact.

---

## Extraction Profiles

### Purpose

An `ExtractionProfile` lets a plugin or sensor restrict and shape unified extraction without changing the global ontology.

### Example Shape

```json
{
  "profile_id": "timeline.chrome_history",
  "allowed_entity_types": ["product"],
  "allowed_predicates": ["VISITED"],
  "allowed_assertion_families": [],
  "entity_type_aliases": {
    "website": "product",
    "page": "product"
  },
  "predicate_aliases": {},
  "default_subject_policy": {
    "subject_ref_template": "user:{user_id}",
    "subject_type": "user"
  },
  "allow_graph": true,
  "allow_assertion": false
}
```

### Resolution Order

1. evidence policy decides whether extraction is allowed at all
2. extraction profile narrows types/predicates/families
3. global ontology registry validates and normalizes outputs
4. invalid values are dropped or coerced to `other` according to rules

### Example profiles

#### Chrome history sensor
- allowed entity types: `product`
- allowed predicates: `VISITED`
- assertions disabled

#### Calendar sensor
- allowed entity types: `activity`, `event`, `place`, `organization`, `person`
- allowed predicates: `ATTENDED`, `PLANS_TO`, `VISITED`
- assertions disabled or topology-only depending on product choice

#### Chat user message
- allowed entity types: global default set
- allowed predicates: global default set
- allowed assertions: all allowed families subject to evidence policy

---

## Prompt Constraints

The unified extraction prompt must be generated dynamically from:

- allowed entity types
- allowed predicates
- allowed assertion families
- source/profile-specific guidance

### Required prompt instructions

- Only emit entity types from the provided enum.
- Specific dishes, drinks, snacks, and ingredients must be labeled as `food`.
- Only emit predicates from the provided enum.
- If a relation is not directly supported by the text, skip it.
- If an assertion only restates a graph fact without abstraction, skip it.
- If no entity is found, return `mentions=[]` and `diagnostics.entity_status="none"`.

---

## Validator Responsibilities

After the single LLM pass, the pipeline must still perform deterministic validation.

### Entity validation
- normalize entity type aliases
- coerce unknown types to `other`
- keep `mentions=[]` if `entity_status=none`
- resolve aliases and canonical IDs through `L2EntityCatalog`

### Graph validation
- reject unknown predicates
- reject illegal subject/object type combinations
- apply source profile restrictions
- require evidence text and confidence
- deduplicate by canonical `(subject, predicate, object)`

### Assertion validation
- reject unknown assertion families
- apply evidence-policy scope (`topology_only`, `full`, etc.)
- cap single-event confidence
- block leaf-fact duplication of graph candidates

---

## Immediate Implementation Notes

### Why `food` should replace `dish`
The current pipeline missed a graph preference relation for `西湖醋鱼` partly because `dish` is not included in `_GRAPH_ELIGIBLE_ENTITY_TYPES`, while `food` is. The unified ontology should avoid this class of mismatch by:

- constraining the prompt to use `food`
- normalizing `dish -> food` in code anyway

### Why one LLM pass should help latency
The current path can call:
- entity mention extraction
- ToM assertion extraction
- contradiction hint extraction

A unified extraction pass should replace the first two with one request, reducing serial LLM latency for the common path.

---

## Recommended Next Implementation Split

### Task A: Ontology registry and validators
- create the entity type enum
- create the predicate enum
- add normalization aliases
- add compatibility matrix validation

### Task B: Extraction profile system
- add `ExtractionProfile` contracts
- add source/profile resolution in `L2Pipeline`
- allow plugin/sensor registration of profiles

### Task C: Unified extraction prompt
- replace separate mention/assertion prompt calls with a single extraction call
- thread profile allowlists into prompt generation
- keep contradiction detection separate for now

### Task D: Remove brittle graph keyword dependence
- demote `_build_graph_candidates()` from primary extraction path to fallback/debug path
- rely on unified `graph_candidates` validated by engineering rules

---

## Validation Checklist

- user message `但我讨厌吃西湖醋鱼`
  - mention type normalizes to `food`
  - graph candidate emits `DISLIKES`
  - no duplicate leaf-level assertion is stored
- plugin profile `timeline.chrome_history`
  - only `product` mentions survive
  - only `VISITED` relations survive
  - assertions are rejected
- unknown type emitted by LLM
  - normalizes to `other`
- no entities in text
  - `mentions=[]`
  - diagnostics mark `entity_status=none`
- invalid predicate/object combination
  - candidate is rejected before persistence

