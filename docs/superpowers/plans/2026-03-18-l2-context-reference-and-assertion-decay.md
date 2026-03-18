# L2 Context Reference And Assertion Decay Implementation Plan

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add context-reference resolution, live context grounding, target-aware assertions, TTL/decay semantics, snapshot expiry handling, and runtime-action evidence gating so L2 can interpret phrases like "这种天气" precisely without letting assistant execution artifacts pollute user cognition.

**Architecture:** Keep the current `EvidenceClassifier -> PolicyResolver -> unified extraction -> validator -> graph/assertion persistence -> reconcile -> snapshot` shape, but extend it with a new `ContextBundle` and `Context Reference Resolver` stage. The resolver combines rule-collected context candidates with a single unified LLM pass that emits `resolved_context_refs` alongside `mentions`, `graph_candidates`, and `assertion_candidates`, while the assertion store evolves from global trait slots into target-aware, time-bounded cognition records.

**Tech Stack:** Python 3.10+, asyncio, existing `UnifiedMemoryStore`, `L2Pipeline`, `L2EntityCatalog`, `L2CognitionStore`, `L2LLMService`, `ScenarioLLMPool`, FastAPI, aiosqlite, pytest.

---

## Source Documents To Re-read Before Implementation

- `docs/project-overview.md`
- `docs/task-agent-runtime-architecture.md`
- `docs/memory-system-design.md`
- `docs/superpowers/plans/2026-03-17-l2-evidence-governance.md`
- `docs/superpowers/plans/2026-03-17-l2-extraction-ontology.md`
- `docs/superpowers/plans/2026-03-18-l2-unified-extraction-implementation.md`

## Problem Statement

Current L2 behavior still has four major semantic gaps:

1. **Context-free object grounding**
   - Phrases like `这种天气`, `这里`, `这道菜`, and `现在` are reduced to coarse concepts instead of being bound to the current conversational or observed context.
   - Example today: `我真的很烦这种天气耶` became `user:self DISLIKES concept:weather`, which loses the actual weather-state target.

2. **Target-free assertions**
   - Assertions such as `annoyance=high` currently attach only to the user, not to the thing causing the reaction.
   - This makes short-lived object-bound reactions look like global user state.

3. **Weak decay semantics**
   - `tom_trait_assertions` already has `volatility_index` and `expires_at`, but there is no consistent trait-family TTL/decay policy.
   - Snapshot materialization also does not clearly distinguish live temporary signals from expired records still kept for evidence history.

4. **Runtime action pollution**
   - `ActionExecuted(ChatResponseAction)` events can currently be classified as `external_observation`, enter L2, and even contradict user-authored facts.
   - Assistant-generated runtime artifacts must not be allowed to re-enter the cognition layer as new user evidence.

This plan addresses all four together because they affect the same L2 semantic boundary.

---

## Target Runtime Flow

```text
L1 stored event
  -> EvidenceClassifier
  -> PolicyResolver
  -> ContextBundleCollector
  -> ContextReferenceResolver (rules + context candidates)
  -> UnifiedExtractionLLM
       -> mentions
       -> resolved_context_refs
       -> graph_candidates
       -> assertion_candidates
       -> diagnostics
  -> Candidate normalizer / validator
       -> apply target/context binding
       -> reject invalid target refs
       -> assign TTL / decay metadata
  -> Graph upsert
  -> Assertion upsert
  -> Contradiction hints
  -> Reconcile
  -> Snapshot materialization (ignoring expired temporary assertions)
```

---

## Semantic Model

### Stable Entities vs Context Entities

Keep two separate concepts in L2:

1. **Stable canonical entities**
   - long-lived nodes in `entity_catalog`
   - examples: `place:shanghai`, `food:west_lake_vinegar_fish`, `person:alice`

2. **Context / live entities**
   - time-bounded semantic objects representing current state
   - examples:
     - `weather_state:hangzhou-rainy-11c-20260318-1358`
     - `location_state:hangzhou-20260318-1358`
     - `time_point:2026-03-18T13:58+08:00`
     - `session_topic:weather-discussion-<session>`

These are not aliases of stable entities. They represent current, contextualized state.

### Alias Resolution vs Context Reference Resolution

These must be kept separate:

- **Alias resolution**
  - same stable entity, different surface form
  - `魔都 -> 上海`
  - `西湖醋鱼 -> food:west_lake_vinegar_fish`

- **Context reference resolution**
  - deictic or conversational reference into current context
  - `这种天气 -> current weather_state`
  - `这里 -> current location_state`
  - `这道菜 -> most recent food mention`

Do not overload alias tables with contextual references.

---

## ContextBundle Design

Add a new transient bundle passed into unified extraction.

### `ContextBundle`

```python
@dataclass(slots=True)
class ContextBundle:
    recent_messages: list[dict[str, Any]]
    recent_entities: list[dict[str, Any]]
    live_context_entities: list[dict[str, Any]]
    pronoun_bindings: list[dict[str, Any]]
    source_event_ids: list[str]
```

### `live_context_entities` shape

```json
{
  "context_id": "weather_state:hangzhou-rainy-11c-20260318-1358",
  "kind": "weather_state",
  "summary": "杭州，阵雨，11度，体感6度，湿度91%",
  "payload": {
    "place_ref": "place:hangzhou",
    "condition": "rainy",
    "temperature_c": 11,
    "humidity": 91
  },
  "source_event_ids": ["evt-weather-tool-1"],
  "created_at": 1773813500.0,
  "expires_at": 1773817100.0
}
```

### Sources for the context bundle

The collector should build candidates from:

- recent session messages
- recent entity mentions already resolved in L2
- recent tool-grounded or observation events already persisted in L1
- L0 slots if available (`current_place`, `current_weather`, `current_time`, `active_topic`)
- source-specific structured hints

The collector must not trigger new tools. It only uses already-known context.

---

## Context Reference Resolver Design

### High-level strategy

Use a **hybrid approach**:

1. **Rules first** to collect candidate targets and bind trivial references
2. **The same unified extraction LLM call** chooses among candidate context references and emits `resolved_context_refs`
3. **Program validators** verify that every chosen reference is in the allowed candidate set and not expired

Do **not** add a second independent LLM call just for reference resolution.

### Rule-only direct bindings

These should resolve before LLM when unambiguous:

- `我` -> `user:self`
- `现在` -> current `time_point` if available
- `这里` -> current location context if a single candidate exists
- `这种天气` -> current weather context if a single live weather entity exists
- `这道菜` -> most recent single food mention in the active session window
- `他/她/他们` -> recent unique person/group mention only when unambiguous

When multiple plausible candidates exist, pass them to the LLM as a bounded choice set.

### Unified extraction extension

Extend the current unified extraction response schema with:

```json
{
  "resolved_context_refs": [
    {
      "surface": "这种天气",
      "reference_type": "context_entity|canonical_entity|self_actor|unresolved",
      "resolved_ref": "weather_state:hangzhou-rainy-11c-20260318-1358",
      "resolved_kind": "weather_state",
      "confidence": 0.0,
      "evidence_text": "我真的很烦这种天气耶"
    }
  ]
}
```

### Prompt constraints

The prompt must receive:

- candidate context references
- stable canonical entities already in scope
- explicit instruction: choose only from supplied candidates or return `unresolved`

The LLM must not invent a new context entity ID.

### Validator rules

After LLM response:

- reject any `resolved_ref` not present in `ContextBundle.live_context_entities` or explicit stable-entity candidates
- reject expired context refs
- reject mismatched kind/type combinations
- downgrade to broader stable concept only if a deterministic fallback rule exists
- otherwise drop the reference rather than hallucinating a target

---

## Assertion Model Upgrade

### Problem with current schema

Current assertion records model only:

- subject entity
- `trait_name`
- `trait_value`

This is insufficient for object-bound reactions.

### Proposed new fields

Add these columns to `tom_trait_assertions`:

- `trait_family TEXT NOT NULL`
- `target_entity_id TEXT`
- `target_entity_type TEXT`
- `target_scope TEXT NOT NULL DEFAULT 'global'`
- `temporal_scope TEXT NOT NULL DEFAULT 'session'`
- `decay_policy TEXT`
- `decay_anchor_at REAL`
- `context_ref_id TEXT`

### New semantics

- `target_entity_id / target_entity_type`
  - the object or context causing the state
  - example: `concept:weather` or `weather_state:...`

- `target_scope`
  - `global`
  - `entity_bound`
  - `context_bound`
  - `event_bound`

- `temporal_scope`
  - `momentary`
  - `session`
  - `daily`
  - `multi_day`
  - `stable`

- `decay_policy`
  - `fast_decay`
  - `session_decay`
  - `time_window`
  - `evidence_only`
  - `manual_revalidate`

- `decay_anchor_at`
  - when decay starts from

- `context_ref_id`
  - optional link to a live context entity used during extraction

### Uniqueness change

Replace the current uniqueness rule:

- `UNIQUE(entity_id, entity_type, trait_name)`

with a target-aware key, such as:

- `UNIQUE(entity_id, entity_type, trait_name, COALESCE(target_entity_id, ''), target_scope)`

This allows:
- `annoyance -> weather`
- `annoyance -> commute`
- `annoyance -> noisy_group`

to coexist without overwriting each other.

---

## Assertion Categories

Treat assertions as three categories with different persistence semantics.

### 1. `event_local_reaction`

Examples:
- annoyed at current weather
- upset by a specific message
- frustrated with a task failure

Properties:
- target required
- `temporal_scope=momentary`
- short TTL
- not a stable user trait

### 2. `contextual_state`

Examples:
- mood low today
- stress high this session
- engagement low this week

Properties:
- target optional
- medium TTL
- may influence `current_*` snapshot fields

### 3. `stable_pattern`

Examples:
- rainy weather tends to trigger irritability
- strongly avoids vinegar-heavy dishes
- prefers quiet environments

Properties:
- never single-event final output
- derived only after reconcile from repeated evidence
- may enter stable snapshot sections

---

## Trait Family TTL / Decay Rules

### Guiding principles

- TTL should be determined primarily by **trait family**, not by free-form LLM preference
- `volatility_index` should adjust TTL, not define it from scratch
- expired assertions remain in the pool as evidence history, but stop affecting current snapshot fields

### Default TTL table

| Trait family | Example | Target required | Temporal scope | Base TTL | Decay policy | Snapshot behavior |
|---|---|---:|---|---|---|---|
| `reaction.annoyance` | annoyed at weather | yes | `momentary` | 2h | `fast_decay` | never stable; may affect `current_context` only while live |
| `reaction.frustration` | frustrated by failure | yes | `momentary` | 2h | `fast_decay` | same as above |
| `reaction.relief` | relieved after resolution | optional | `momentary` | 2h | `fast_decay` | context-only |
| `state.mood` | current mood low | no | `session` | 12h | `session_decay` | may affect `current_mood` while live |
| `state.stress` | current stress high | no | `daily` | 24h | `time_window` | may affect `current_stress_level` while live |
| `state.engagement` | currently disengaged | no | `session` | 12h | `session_decay` | may affect `current_engagement` while live |
| `trigger.*` | rainy weather as trigger | yes | `multi_day` | none | `evidence_only` | only after reconcile |
| `preference.*` | prefers Japanese food | optional | `stable` | none | `evidence_only` | stable snapshot candidate |
| `relationship_shift` | relation cooling | yes | `multi_day` | 7d | `time_window` | current context first, stable only after repeats |
| `group_atmosphere` | chat tense | yes | `session` | 6h | `session_decay` | current context only |
| `public_sentiment` | positive public stance | yes | `multi_day` | 3d | `time_window` | summary/context only |

### Volatility adjustment

Suggested formula:

```text
effective_ttl = base_ttl * clamp(0.35, 1.25 - volatility_index, 1.2)
```

Meaning:
- high volatility shortens TTL
- low volatility keeps or slightly extends TTL
- stable patterns ignore automatic TTL and rely on evidence accumulation instead

### Required helper

Add a deterministic helper such as:

```python
def resolve_assertion_lifecycle(*, trait_family: str, volatility_index: float, now: float) -> AssertionLifecycle:
    ...
```

Returning:
- `temporal_scope`
- `decay_policy`
- `base_ttl_seconds`
- `effective_expires_at`
- `allow_snapshot_projection`

---

## Snapshot Expiry Rules

### Keep assertions in the pool, but filter by liveness

Expired assertions should not be hard-deleted immediately. They are still useful for:
- evidence history
- future pattern learning
- auditing why a past snapshot looked a certain way

### Snapshot read/materialization rules

When building `tom_snapshots`:

1. separate assertions into:
   - `live_assertions`
   - `expired_assertions`
   - `stable_assertions`
2. only project **live** temporary assertions into current-state snapshot fields
3. stable patterns may remain visible even if there is no TTL, provided they remain validated
4. expired temporary assertions contribute to historical counters only, not `current_mood/current_stress/current_context`

### Field-specific rules

- `current_mood`
  - use only live `state.mood` assertions
- `current_stress_level`
  - use only live `state.stress` assertions
- `current_engagement`
  - use only live `state.engagement` assertions
- `current_context`
  - may include live `event_local_reaction` assertions with target refs
- `core_traits`
  - only stable validated patterns
- `preferences`
  - only stable preference patterns or stable graph-derived preferences
- `sensitive_triggers`
  - only stable trigger patterns

### Example for current bug

For `我真的很烦这种天气耶`:

- graph should point to a weather-state context entity
- assertion should be:
  - `trait_family = reaction.annoyance`
  - `target = weather_state:...`
  - `temporal_scope = momentary`
  - `expires_at = now + ~2h`
- snapshot should only surface it in `current_context` while live
- it must not become a general `current_mood=annoyed` or a long-term `core_trait`

---

## Runtime Action Gating Fix

### Problem

`ActionExecuted(ChatResponseAction)` is currently able to enter L2 as `external_observation`, even though the payload is just the assistant response rendered through runtime infrastructure.

### Required new rule

Any runtime action event that represents assistant-authored content must be denied as L2 evidence.

### Detection rules

In `EvidenceClassifier`, add a new decision path before `external_observation`:

If all of the following are true:
- `event_type == 'ActionExecuted'`
- `source == 'runtime_action_emitter'` or equivalent runtime action namespace
- `structured_payload.action_type == 'ChatResponseAction'` or payload includes assistant response text

Then classify as:
- `assistant_runtime_derivation`

### Policy mapping

For `assistant_runtime_derivation`:
- `allow_entity_extraction = false`
- `allow_graph_write = false`
- `allow_assertion_write = false`
- `allow_snapshot_impact = false`
- `evidence_weight = 0.0`
- `count_as_new_evidence = false`
- `skip_reason = 'assistant_runtime_derivation'`

### Broader guardrail

Also treat these classes as non-evidence by default unless explicitly whitelisted later:
- `ActionExecuted(ChatResponseAction)`
- runtime events whose payload is a reserialized assistant answer
- agent orchestration observations carrying assistant text but no independent world observation

This fixes the current weather example where the assistant follow-up caused a contradiction hint to be applied against the user-authored dislike.

---

## Unified Extraction Contract Changes

Extend the existing single-pass extraction schema.

### New output fields

```json
{
  "resolved_context_refs": [
    {
      "surface": "这种天气",
      "reference_type": "context_entity|canonical_entity|self_actor|unresolved",
      "resolved_ref": "weather_state:hangzhou-rainy-11c-20260318-1358",
      "resolved_kind": "weather_state",
      "confidence": 0.92,
      "evidence_text": "我真的很烦这种天气耶"
    }
  ]
}
```

### Prompt additions

The prompt should receive:
- `candidate_context_refs`
- direct rule-bound self/pronoun bindings
- recent canonical entity candidates
- explicit instruction to choose only from supplied candidates or return `unresolved`

### Validator behavior

- validate every context reference
- project bound references into graph/assertion targets
- if a reference is invalid, remove it instead of widening automatically unless a deterministic fallback exists

---

## File Map

### New backend files

- `backend/src/magi/memory/l2/context_bundle.py`
  - DTOs for context entities and reference candidates
- `backend/src/magi/memory/l2/context_collector.py`
  - rules for building context bundles from session, L0, recent mentions, and recent observations
- `backend/src/magi/memory/l2/assertion_lifecycle.py`
  - TTL / decay / expiry helper tables and calculations
- `backend/tests/memory/l2/test_context_collector.py`
- `backend/tests/memory/l2/test_assertion_lifecycle.py`

### Modified backend files

- `backend/src/magi/memory/l2/prompts.py`
  - extend unified extraction prompt with candidate context refs and `resolved_context_refs` schema
- `backend/src/magi/memory/l2/llm_service.py`
  - parse `resolved_context_refs`
- `backend/src/magi/memory/l2/pipeline.py`
  - build context bundles
  - inject context candidates into unified extraction
  - apply reference bindings to graph/assertion candidates
  - skip assistant runtime derivation events
- `backend/src/magi/memory/l2/store.py`
  - add assertion target/lifecycle fields
  - change uniqueness logic
  - filter expired assertions during snapshot materialization
- `backend/src/magi/memory/l2/evidence_classifier.py`
  - add `assistant_runtime_derivation`
- `backend/src/magi/memory/l2/evidence_policy.py`
  - skip policy for the new evidence class
- `backend/src/magi/memory/l2/models.py`
  - add DTOs for resolved context refs and lifecycle metadata
- `backend/src/magi/memory/l2/ontology.py`
  - add context-entity kinds if needed
- `backend/tests/memory/l2/test_pipeline.py`
  - end-to-end coverage
- `backend/tests/memory/l2/test_evidence_classifier.py`
  - gating coverage for runtime action events
- `backend/tests/memory/l2/test_store.py`
  - snapshot expiry and target-aware assertion tests

---

## Chunk 1: Add Context Bundles And Reference Resolution Contracts

### Task 1: Add DTOs for context entities and resolved references

**Files:**
- Create: `backend/src/magi/memory/l2/context_bundle.py`
- Modify: `backend/src/magi/memory/l2/models.py`
- Test: `backend/tests/memory/l2/test_context_collector.py`

- [ ] **Step 1: Write failing tests for context bundle DTOs**
- [ ] **Step 2: Run focused test to confirm failure**
- [ ] **Step 3: Implement `ContextBundle`, `ContextEntity`, and `ResolvedContextRef` contracts**
- [ ] **Step 4: Re-run focused test**
- [ ] **Step 5: Commit**

### Task 2: Implement deterministic context bundle collection

**Files:**
- Create: `backend/src/magi/memory/l2/context_collector.py`
- Test: `backend/tests/memory/l2/test_context_collector.py`

- [ ] **Step 1: Write failing tests covering**
  - `我 -> user:self`
  - single current weather slot -> `这种天气`
  - most recent food mention -> `这道菜`
  - ambiguity returns multiple candidates instead of forced binding
- [ ] **Step 2: Run focused tests**
- [ ] **Step 3: Implement collector and trivial direct bindings**
- [ ] **Step 4: Re-run tests**
- [ ] **Step 5: Commit**

---

## Chunk 2: Extend Unified Extraction With Context References

### Task 3: Extend prompts and LLM service to emit `resolved_context_refs`

**Files:**
- Modify: `backend/src/magi/memory/l2/prompts.py`
- Modify: `backend/src/magi/memory/l2/llm_service.py`
- Test: `backend/tests/memory/l2/test_llm_service.py`

- [ ] **Step 1: Add failing tests for parsing valid/invalid context refs**
- [ ] **Step 2: Run focused tests**
- [ ] **Step 3: Extend unified prompt and parser**
- [ ] **Step 4: Re-run focused tests**
- [ ] **Step 5: Commit**

### Task 4: Bind validated context references into graph/assertion candidates

**Files:**
- Modify: `backend/src/magi/memory/l2/pipeline.py`
- Modify: `backend/src/magi/memory/l2/ontology.py`
- Test: `backend/tests/memory/l2/test_pipeline.py`

- [ ] **Step 1: Write failing pipeline tests for `这种天气` resolving to a weather-state context entity**
- [ ] **Step 2: Run focused tests**
- [ ] **Step 3: Implement candidate binding and validation**
- [ ] **Step 4: Re-run focused tests**
- [ ] **Step 5: Commit**

---

## Chunk 3: Upgrade Assertions With Targets And Lifecycle Rules

### Task 5: Add target-aware assertion fields and migrations

**Files:**
- Modify: `backend/src/magi/memory/l2/store.py`
- Modify: `backend/src/magi/memory/l2/models.py`
- Test: `backend/tests/memory/l2/test_store.py`

- [ ] **Step 1: Write failing tests for target-bearing assertions coexisting by target**
- [ ] **Step 2: Run focused tests**
- [ ] **Step 3: Add new columns and update normalization/upsert logic**
- [ ] **Step 4: Re-run focused tests**
- [ ] **Step 5: Commit**

### Task 6: Implement assertion lifecycle resolver and TTL table

**Files:**
- Create: `backend/src/magi/memory/l2/assertion_lifecycle.py`
- Modify: `backend/src/magi/memory/l2/pipeline.py`
- Test: `backend/tests/memory/l2/test_assertion_lifecycle.py`
- Test: `backend/tests/memory/l2/test_pipeline.py`

- [ ] **Step 1: Write failing tests for TTL/decay behavior across trait families**
- [ ] **Step 2: Run focused tests**
- [ ] **Step 3: Implement lifecycle resolver and pipeline assignment**
- [ ] **Step 4: Re-run focused tests**
- [ ] **Step 5: Commit**

---

## Chunk 4: Snapshot Expiry Handling

### Task 7: Exclude expired temporary assertions from current snapshot fields

**Files:**
- Modify: `backend/src/magi/memory/l2/store.py`
- Test: `backend/tests/memory/l2/test_store.py`

- [ ] **Step 1: Write failing snapshot tests**
  - expired annoyance does not affect `current_context`
  - expired mood does not affect `current_mood`
  - expired stress does not affect `current_stress_level`
  - stable preference remains visible
- [ ] **Step 2: Run focused tests**
- [ ] **Step 3: Implement live-vs-expired filtering during snapshot materialization**
- [ ] **Step 4: Re-run focused tests**
- [ ] **Step 5: Commit**

---

## Chunk 5: Block Assistant Runtime Derivations From L2

### Task 8: Classify and skip `ActionExecuted(ChatResponseAction)`

**Files:**
- Modify: `backend/src/magi/memory/l2/evidence_classifier.py`
- Modify: `backend/src/magi/memory/l2/evidence_policy.py`
- Modify: `backend/src/magi/memory/l2/pipeline.py`
- Test: `backend/tests/memory/l2/test_evidence_classifier.py`
- Test: `backend/tests/memory/l2/test_pipeline.py`

- [ ] **Step 1: Write failing tests showing runtime chat response actions are skipped**
- [ ] **Step 2: Run focused tests**
- [ ] **Step 3: Implement `assistant_runtime_derivation` classification and policy deny rule**
- [ ] **Step 4: Re-run focused tests**
- [ ] **Step 5: Commit**

### Task 9: Add regression coverage for the weather complaint scenario

**Files:**
- Modify: `backend/tests/memory/l2/test_pipeline.py`
- Modify: `backend/tests/memory/l2/test_store.py`

- [ ] **Step 1: Write a failing end-to-end test for**
  - user says `我真的很烦这种天气耶`
  - current weather-state context exists
  - graph binds to weather-state context instead of `concept:weather`
  - annoyance assertion targets the weather-state context
  - subsequent `ActionExecuted(ChatResponseAction)` does not mark the user graph edge `conflicted`
- [ ] **Step 2: Run the scenario test and confirm failure**
- [ ] **Step 3: Implement the minimal fixes across resolver, lifecycle, and evidence gating**
- [ ] **Step 4: Re-run focused scenario tests**
- [ ] **Step 5: Commit**

---

## Validation Matrix

Minimum regression suite after implementation:

```bash
cd backend
PYTHONPATH=src pytest \
  tests/memory/l2/test_context_collector.py \
  tests/memory/l2/test_assertion_lifecycle.py \
  tests/memory/l2/test_evidence_classifier.py \
  tests/memory/l2/test_llm_service.py \
  tests/memory/l2/test_pipeline.py \
  tests/memory/l2/test_store.py -v
```

Recommended broader regression after the final chunk:

```bash
cd backend
PYTHONPATH=src pytest \
  tests/memory/l2 \
  tests/memory/test_memory_layers.py \
  tests/memory/test_identity_resolver.py \
  tests/api/test_memory_api.py -v
```

---

## Success Criteria

This plan is complete when all of the following are true:

- `这种天气` and similar deictic references can bind to context entities rather than collapsing to generic concepts
- object-bound reactions become target-aware assertions rather than global user traits
- temporary reaction/state assertions have deterministic TTL/decay semantics
- snapshots ignore expired temporary assertions while retaining stable patterns
- `ActionExecuted(ChatResponseAction)` no longer enters L2 as new evidence
- the current weather complaint scenario no longer produces a self-contradicting graph edge

