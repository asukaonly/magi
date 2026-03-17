# L2 Unified Extraction Implementation Plan

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Implement the first production version of unified L2 extraction so one LLM pass can emit `mentions`, `graph_candidates`, and `assertion_candidates`, while deterministic ontology/profile validators continue to control what actually enters the graph and assertion stores.

**Architecture:** Keep `EvidenceClassifier` and `PolicyResolver` unchanged as the front gate, then add a new ontology registry, extraction-profile resolver, and unified extraction prompt/service behind that gate. The pipeline will validate and normalize the LLM output before persistence, reject unsupported predicates or type combinations, and keep contradiction/reconcile/snapshot stages intact.

**Tech Stack:** Python 3.10+, asyncio, existing `UnifiedMemoryStore`, `L2Pipeline`, `L2LLMService`, `L2EntityCatalog`, `L2CognitionStore`, `ScenarioLLMPool`, pytest, aiosqlite.

---

## Scope Guardrails

- Keep current evidence governance behavior unchanged.
- Do not widen frontend scope in this implementation plan; backend only.
- Keep the current contradiction/reconcile/snapshot stages, but allow them to consume the new candidate shapes.
- Do not delete the old rule path until unified extraction has a fully passing fallback-safe implementation.
- Introduce `food` as the canonical coarse type and normalize `dish` into it.
- Represent “no entities extracted” as diagnostics, not as an entity type.
- Keep plugin/sensor intervention limited to extraction profiles and structured hints, not a full plugin management redesign.

## Source Documents To Re-read Before Implementation

- `docs/project-overview.md`
- `docs/task-agent-runtime-architecture.md`
- `docs/memory-system-design.md`
- `docs/superpowers/plans/2026-03-17-l2-evidence-governance.md`
- `docs/superpowers/plans/2026-03-17-l2-extraction-ontology.md`

## File Map

### New backend files

- `backend/src/magi/memory/l2_ontology.py`
  Canonical entity types, predicates, normalization aliases, compatibility matrix, and validation helpers.
- `backend/src/magi/memory/l2_extraction_profiles.py`
  Extraction profile DTOs, registry helpers, default source profiles, and merge logic for event/profile overrides.
- `backend/tests/memory/test_l2_ontology.py`
- `backend/tests/memory/test_l2_extraction_profiles.py`

### Modified backend files

- `backend/src/magi/memory/l2_prompt_templates.py`
  Replace split mention/assertion prompt generation with a single unified extraction prompt builder that takes ontology/profile constraints.
- `backend/src/magi/memory/l2_llm_service.py`
  Add unified extraction method and response validation/parsing.
- `backend/src/magi/memory/l2_pipeline.py`
  Replace separate `extract_entity_mentions()` and `extract_tom_assertions()` calls with a single unified extraction path, profile resolution, candidate normalization, and validator application.
- `backend/src/magi/memory/l2_entity_catalog.py`
  Normalize entity types during catalog writes and accept canonicalized mention payloads.
- `backend/src/magi/memory/l2_cognition_store.py`
  Accept unified graph candidates with validated predicate/type combinations and assertion candidates with duplicate-leaf suppression.
- `backend/src/magi/memory/l2_models.py`
  Add contracts for unified extraction output, extraction diagnostics, and structured hint payloads if needed.
- `backend/src/magi/memory/event_contracts.py`
  Add extraction profile metadata and optional structured hint fields.
- `backend/src/magi/memory/__init__.py`
  Wire ontology/profile dependencies into the memory store and pipeline.
- `backend/tests/memory/test_l2_llm_service.py`
  Extend with unified extraction JSON parsing tests.
- `backend/tests/memory/test_l2_pipeline.py`
  Extend with end-to-end coverage for unified extraction, type normalization, profile restrictions, and graph/assertion boundary rules.

---

## Chunk 1: Add Ontology Registry And Deterministic Validators

### Task 1: Introduce the canonical entity-type and predicate registry

**Files:**
- Create: `backend/src/magi/memory/l2_ontology.py`
- Test: `backend/tests/memory/test_l2_ontology.py`

- [ ] **Step 1: Write failing ontology tests**

Cover these cases:
- `dish` normalizes to `food`
- unknown entity type normalizes to `other`
- `none` is rejected as an entity type but allowed as diagnostics status elsewhere
- `DISLIKES` with object type `food` is valid
- `DISLIKES` with object type `health_metric` is invalid
- `HAS_METRIC` with object type `health_metric` is valid
- `LIVES_IN` only accepts `place`

- [ ] **Step 2: Run the focused ontology tests**

Run: `cd backend && pytest tests/memory/test_l2_ontology.py -v`
Expected: FAIL because the ontology module does not exist.

- [ ] **Step 3: Implement `l2_ontology.py`**

Add:
- `ENTITY_TYPE_REGISTRY`
- `PREDICATE_REGISTRY`
- `ENTITY_TYPE_ALIASES`
- `AssertionFamily` allowlist
- `normalize_entity_type(raw_type: str | None) -> str | None`
- `is_valid_entity_type(entity_type: str) -> bool`
- `is_valid_predicate(predicate: str) -> bool`
- `is_predicate_compatible(predicate: str, object_type: str) -> bool`
- `coerce_unknown_entity_type(raw_type: str | None) -> str`

Implementation notes:
- canonicalize to lowercase entity types and uppercase predicates
- `other` is the only runtime fallback entity type
- do not let this module reach into DB or pipeline code

- [ ] **Step 4: Re-run ontology tests**

Run: `cd backend && pytest tests/memory/test_l2_ontology.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/src/magi/memory/l2_ontology.py backend/tests/memory/test_l2_ontology.py
git commit -m "feat: add l2 ontology registry"
```

### Task 2: Add unified candidate validators that consume the registry

**Files:**
- Modify: `backend/src/magi/memory/l2_ontology.py`
- Modify: `backend/tests/memory/test_l2_ontology.py`

- [ ] **Step 1: Write failing validator tests**

Cover these cases:
- graph candidate with invalid predicate is rejected
- graph candidate with illegal object-type combination is rejected
- assertion candidate with unsupported family is rejected
- assertion candidate with leaf-level duplication marker can be identified for suppression

- [ ] **Step 2: Run focused validator tests**

Run: `cd backend && pytest tests/memory/test_l2_ontology.py -k validator -v`
Expected: FAIL because validator helpers do not exist.

- [ ] **Step 3: Implement validator helpers**

Add helpers such as:
- `validate_graph_candidate(candidate: dict[str, Any]) -> tuple[bool, str | None]`
- `validate_assertion_candidate(candidate: dict[str, Any]) -> tuple[bool, str | None]`
- `is_leaf_fact_duplicate(graph_candidates, assertion_candidate) -> bool`

Implementation notes:
- keep error reasons stable strings for logging and test assertions
- support canonicalization before validation

- [ ] **Step 4: Re-run validator tests**

Run: `cd backend && pytest tests/memory/test_l2_ontology.py -k validator -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/src/magi/memory/l2_ontology.py backend/tests/memory/test_l2_ontology.py
git commit -m "feat: add l2 candidate validators"
```

---

## Chunk 2: Add Extraction Profiles For Plugins, Sensors, And Source Overrides

### Task 3: Create the extraction-profile model and default source profiles

**Files:**
- Create: `backend/src/magi/memory/l2_extraction_profiles.py`
- Test: `backend/tests/memory/test_l2_extraction_profiles.py`

- [ ] **Step 1: Write failing profile tests**

Cover these cases:
- default chat profile exposes the full entity/predicate allowlist
- chrome-history profile narrows to `product` + `VISITED`
- a profile may disable assertions entirely
- profile alias mappings override global aliases when supplied

- [ ] **Step 2: Run focused profile tests**

Run: `cd backend && pytest tests/memory/test_l2_extraction_profiles.py -v`
Expected: FAIL because the profile module does not exist.

- [ ] **Step 3: Implement `l2_extraction_profiles.py`**

Required pieces:
- `ExtractionProfile` dataclass / model
- `DefaultSubjectPolicy`
- `DEFAULT_EXTRACTION_PROFILES`
- `resolve_extraction_profile(event, profile_registry=None) -> ExtractionProfile`
- merge logic for event metadata overrides

Implementation notes:
- ship at least `chat.user_message`, `timeline.chrome_history`, and `timeline.calendar` profiles
- support `allowed_entity_types`, `allowed_predicates`, `allowed_assertion_families`, `entity_type_aliases`, `predicate_aliases`, `allow_graph`, and `allow_assertion`

- [ ] **Step 4: Re-run profile tests**

Run: `cd backend && pytest tests/memory/test_l2_extraction_profiles.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/src/magi/memory/l2_extraction_profiles.py backend/tests/memory/test_l2_extraction_profiles.py
git commit -m "feat: add l2 extraction profiles"
```

### Task 4: Add event-contract support for profile ids and structured hints

**Files:**
- Modify: `backend/src/magi/memory/event_contracts.py`
- Modify: `backend/src/magi/memory/l2_models.py`
- Test: `backend/tests/memory/test_l2_pipeline.py`

- [ ] **Step 1: Write failing event-contract tests**

Cover these cases:
- event metadata can carry `extraction_profile_id`
- event metadata can carry `structured_entity_hints`
- event metadata can carry `structured_graph_hints`
- normalization preserves these fields through L1 round-trip

- [ ] **Step 2: Run focused event-contract tests**

Run: `cd backend && pytest tests/memory/test_l2_pipeline.py -k profile_metadata -v`
Expected: FAIL because the new metadata fields are not normalized yet.

- [ ] **Step 3: Extend contracts**

Add optional fields to `MemoryEvent` and the relevant DTOs for:
- `extraction_profile_id`
- `structured_entity_hints`
- `structured_graph_hints`

Implementation notes:
- keep metadata JSON-safe
- do not force every producer to provide these fields
- default to absent/empty values cleanly

- [ ] **Step 4: Re-run focused tests**

Run: `cd backend && pytest tests/memory/test_l2_pipeline.py -k profile_metadata -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/src/magi/memory/event_contracts.py backend/src/magi/memory/l2_models.py backend/tests/memory/test_l2_pipeline.py
git commit -m "feat: add l2 extraction profile metadata"
```

---

## Chunk 3: Replace Split LLM Calls With Unified Extraction

### Task 5: Add unified extraction prompt generation

**Files:**
- Modify: `backend/src/magi/memory/l2_prompt_templates.py`
- Test: `backend/tests/memory/test_l2_llm_service.py`

- [ ] **Step 1: Write failing prompt-render tests**

Cover these cases:
- prompt includes only profile-allowed entity types
- prompt includes only profile-allowed predicates
- prompt explicitly says dishes/drinks/snacks map to `food`
- prompt includes assertion-family allowlist
- prompt explains `entity_status=none`

- [ ] **Step 2: Run prompt tests**

Run: `cd backend && pytest tests/memory/test_l2_llm_service.py -k unified_prompt -v`
Expected: FAIL because the unified prompt builder does not exist.

- [ ] **Step 3: Implement unified prompt rendering**

Add:
- `UNIFIED_EXTRACTION_SYSTEM_PROMPT`
- `render_unified_extraction_prompt(...)`

Implementation notes:
- generate prompt sections from the resolved extraction profile
- include canonical enums in the prompt, not free-form type strings
- keep prompt deterministic for tests

- [ ] **Step 4: Re-run prompt tests**

Run: `cd backend && pytest tests/memory/test_l2_llm_service.py -k unified_prompt -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/src/magi/memory/l2_prompt_templates.py backend/tests/memory/test_l2_llm_service.py
git commit -m "feat: add unified l2 extraction prompt"
```

### Task 6: Add unified extraction parsing to `L2LLMService`

**Files:**
- Modify: `backend/src/magi/memory/l2_llm_service.py`
- Modify: `backend/tests/memory/test_l2_llm_service.py`

- [ ] **Step 1: Write failing LLM service tests**

Cover these cases:
- unified extraction parses mentions, graph candidates, assertions, and diagnostics
- invalid JSON fails closed to empty outputs
- single-event assertion confidence is still capped
- unknown entity types are not normalized here yet; that happens later in pipeline validation

- [ ] **Step 2: Run focused service tests**

Run: `cd backend && pytest tests/memory/test_l2_llm_service.py -k unified_extraction -v`
Expected: FAIL because the unified extraction service method does not exist.

- [ ] **Step 3: Implement unified extraction method**

Add a method such as:
- `extract_unified_candidates(event_window, profile, focal_subject) -> dict[str, Any]`

Implementation notes:
- return raw candidate lists plus diagnostics
- keep it JSON-safe and fail closed
- leave canonical normalization to the pipeline

- [ ] **Step 4: Re-run focused tests**

Run: `cd backend && pytest tests/memory/test_l2_llm_service.py -k unified_extraction -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/src/magi/memory/l2_llm_service.py backend/tests/memory/test_l2_llm_service.py
git commit -m "feat: add unified l2 extraction service"
```

---

## Chunk 4: Refactor The Pipeline To Use Unified Extraction And Validators

### Task 7: Resolve profiles and validate unified candidates inside `L2Pipeline`

**Files:**
- Modify: `backend/src/magi/memory/l2_pipeline.py`
- Modify: `backend/src/magi/memory/__init__.py`
- Test: `backend/tests/memory/test_l2_pipeline.py`

- [ ] **Step 1: Write failing pipeline tests for unified extraction**

Cover these cases:
- user message with `西湖醋鱼` yields a `food` mention after normalization
- a `DISLIKES` graph candidate for `food` is accepted and persisted
- duplicate leaf-level assertion for the same dislike fact is suppressed
- chrome-history profile allows `VISITED` and rejects unrelated predicates/assertions
- invalid predicate/object combinations are dropped before persistence

- [ ] **Step 2: Run the focused pipeline tests**

Run: `cd backend && pytest tests/memory/test_l2_pipeline.py -k unified_extraction -v`
Expected: FAIL because the pipeline still calls split mention/assertion methods.

- [ ] **Step 3: Refactor pipeline extraction flow**

Replace the current sequence:
- mention extraction
- graph rule build
- assertion extraction

with:
- resolve extraction profile
- merge structured hints from event metadata
- call unified extraction once
- normalize entity types and predicates
- validate graph/assertion candidates
- resolve entity IDs through the entity catalog
- persist only validated candidates

Implementation notes:
- keep the current graph-rule path as a fallback only while unified extraction is being proven
- preserve pipeline stats and skip reasons
- preserve contradiction detection as a separate step after candidate validation

- [ ] **Step 4: Re-run the focused pipeline tests**

Run: `cd backend && pytest tests/memory/test_l2_pipeline.py -k unified_extraction -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/src/magi/memory/l2_pipeline.py backend/src/magi/memory/__init__.py backend/tests/memory/test_l2_pipeline.py
git commit -m "refactor: use unified l2 extraction"
```

### Task 8: Normalize entity types in the entity catalog and persistence layer

**Files:**
- Modify: `backend/src/magi/memory/l2_entity_catalog.py`
- Modify: `backend/src/magi/memory/l2_cognition_store.py`
- Test: `backend/tests/memory/test_l2_entity_catalog.py`
- Test: `backend/tests/memory/test_l2_pipeline.py`

- [ ] **Step 1: Write failing normalization tests**

Cover these cases:
- `dish` is normalized to `food` before catalog persistence
- `unknown_type` is normalized to `other`
- persisted graph edges use normalized object types
- assertions use normalized entity types where applicable

- [ ] **Step 2: Run focused normalization tests**

Run: `cd backend && pytest tests/memory/test_l2_entity_catalog.py tests/memory/test_l2_pipeline.py -k normalization -v`
Expected: FAIL because the catalog/store still accept raw types.

- [ ] **Step 3: Implement normalization at persistence boundaries**

Apply normalization in:
- entity mention recording
- entity upsert
- graph upsert candidate preparation
- assertion candidate preparation

Implementation notes:
- normalize before dedup keys are computed
- do not mutate already persisted historical rows retroactively in this task

- [ ] **Step 4: Re-run focused tests**

Run: `cd backend && pytest tests/memory/test_l2_entity_catalog.py tests/memory/test_l2_pipeline.py -k normalization -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/src/magi/memory/l2_entity_catalog.py backend/src/magi/memory/l2_cognition_store.py backend/tests/memory/test_l2_entity_catalog.py backend/tests/memory/test_l2_pipeline.py
git commit -m "fix: normalize l2 entity types"
```

---

## Chunk 5: Tighten Boundary Rules Between Graph And Assertion Outputs

### Task 9: Suppress leaf-level assertion duplicates for explicit graph facts

**Files:**
- Modify: `backend/src/magi/memory/l2_pipeline.py`
- Modify: `backend/src/magi/memory/l2_ontology.py`
- Test: `backend/tests/memory/test_l2_pipeline.py`

- [ ] **Step 1: Write failing duplicate-boundary tests**

Cover these cases:
- `DISLIKES food:西湖醋鱼` graph fact suppresses `taste_preference = dislikes_food:...`
- higher-order assertion such as `taste_profile = avoids_vinegar_heavy_dishes` is still allowed alongside the graph fact

- [ ] **Step 2: Run focused boundary tests**

Run: `cd backend && pytest tests/memory/test_l2_pipeline.py -k duplicate_boundary -v`
Expected: FAIL because duplicate suppression is not implemented.

- [ ] **Step 3: Implement boundary suppression**

Add logic that:
- detects graph/assertion leaf duplication during candidate validation
- suppresses the assertion when it restates a concrete graph preference edge
- allows higher-order abstraction assertions to pass through

- [ ] **Step 4: Re-run focused tests**

Run: `cd backend && pytest tests/memory/test_l2_pipeline.py -k duplicate_boundary -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/src/magi/memory/l2_pipeline.py backend/src/magi/memory/l2_ontology.py backend/tests/memory/test_l2_pipeline.py
git commit -m "fix: suppress duplicate l2 assertions"
```

### Task 10: Preserve plugin/sensor structured hints with validator enforcement

**Files:**
- Modify: `backend/src/magi/memory/l2_pipeline.py`
- Modify: `backend/tests/memory/test_l2_pipeline.py`

- [ ] **Step 1: Write failing structured-hint tests**

Cover these cases:
- structured entity hints bypass LLM mention extraction when supplied
- structured graph hints are validated before persistence
- illegal structured graph hints are rejected just like LLM-produced candidates

- [ ] **Step 2: Run focused structured-hint tests**

Run: `cd backend && pytest tests/memory/test_l2_pipeline.py -k structured_hints -v`
Expected: FAIL because hints are not consumed yet.

- [ ] **Step 3: Implement structured-hint merge logic**

Implementation notes:
- structured hints should be merged before or instead of unified extraction depending on profile settings
- use the same validators as LLM output
- keep logging explicit when hints are used instead of LLM output

- [ ] **Step 4: Re-run focused tests**

Run: `cd backend && pytest tests/memory/test_l2_pipeline.py -k structured_hints -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/src/magi/memory/l2_pipeline.py backend/tests/memory/test_l2_pipeline.py
git commit -m "feat: support l2 structured hints"
```

---

## Chunk 6: Regression, Diagnostics, And Cleanup

### Task 11: Expand L2 logging and regressions for the new flow

**Files:**
- Modify: `backend/src/magi/memory/l2_pipeline.py`
- Modify: `backend/src/magi/memory/l2_llm_service.py`
- Modify: `backend/tests/memory/test_l2_pipeline.py`

- [ ] **Step 1: Write failing diagnostic tests**

Cover these cases:
- unified extraction logs profile id, mention count, graph candidate count, and assertion candidate count
- L2 LLM call timing is logged per unified extraction request
- rejected candidates log stable rejection reasons

- [ ] **Step 2: Run focused diagnostics tests**

Run: `cd backend && pytest tests/memory/test_l2_pipeline.py -k diagnostics -v`
Expected: FAIL because the new diagnostics do not exist yet.

- [ ] **Step 3: Implement diagnostics**

Add:
- unified extraction timing logs
- profile id in extract logs
- rejection-reason counters or logs

Keep info-level summaries readable and debug-level details deep.

- [ ] **Step 4: Re-run focused diagnostics tests**

Run: `cd backend && pytest tests/memory/test_l2_pipeline.py -k diagnostics -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/src/magi/memory/l2_pipeline.py backend/src/magi/memory/l2_llm_service.py backend/tests/memory/test_l2_pipeline.py
git commit -m "feat: add unified l2 diagnostics"
```

### Task 12: Run final backend regression suite for L2

**Files:**
- No new files expected

- [ ] **Step 1: Run full focused regression suite**

Run:

```bash
cd backend && pytest \
  tests/memory/test_l2_ontology.py \
  tests/memory/test_l2_extraction_profiles.py \
  tests/memory/test_l2_llm_service.py \
  tests/memory/test_l2_entity_catalog.py \
  tests/memory/test_l2_cognition_store.py \
  tests/memory/test_l2_pipeline.py \
  tests/api/test_memory_api.py -v
```

Expected: PASS.

- [ ] **Step 2: If failures appear, fix them in the smallest possible follow-up commit**

Do not batch unrelated cleanups.

- [ ] **Step 3: Commit any final regression-only fixes**

Example:

```bash
git add <files>
git commit -m "test: stabilize unified l2 regression coverage"
```

---

## Suggested Commit Sequence

1. `feat: add l2 ontology registry`
2. `feat: add l2 candidate validators`
3. `feat: add l2 extraction profiles`
4. `feat: add l2 extraction profile metadata`
5. `feat: add unified l2 extraction prompt`
6. `feat: add unified l2 extraction service`
7. `refactor: use unified l2 extraction`
8. `fix: normalize l2 entity types`
9. `fix: suppress duplicate l2 assertions`
10. `feat: support l2 structured hints`
11. `feat: add unified l2 diagnostics`
12. `test: stabilize unified l2 regression coverage`

---

## Exit Criteria

The implementation is complete when:

- one LLM call produces mentions, graph candidates, and assertion candidates for allowed evidence classes
- entity types are constrained and normalized through the ontology registry
- predicates are constrained and validated through the whitelist + compatibility matrix
- plugin/sensor extraction profiles can restrict what a source may emit
- `food` is the canonical output for dish-like items such as `西湖醋鱼`
- explicit graph facts no longer produce duplicate leaf-level assertions
- the backend regression suite for the new L2 path passes cleanly

