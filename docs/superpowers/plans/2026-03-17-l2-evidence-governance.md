# L2 Evidence Governance Implementation Plan

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a deterministic evidence-classification and policy-resolution layer between `L1` and `L2` so assistant replies, tool-grounded summaries, external observations, and runtime events cannot pollute long-term cognition.

**Architecture:** Keep `L1` as the durable full-fidelity event log, then insert a rule-driven `EvidenceClassifier` and `L2EvidencePolicyResolver` ahead of all `L2` extraction work. The classifier decides what kind of evidence an event represents, and the policy resolver maps that class to allowed writes, evidence weight, and dedup/backlink behavior before any graph or ToM candidate extraction runs.

**Tech Stack:** Python 3.10+, FastAPI, asyncio, existing `UnifiedMemoryStore`, `L2Pipeline`, `L2CognitionStore`, Pydantic v2, pytest.

---

## Scope Guardrails

- Keep `L1` storage behavior unchanged: user, assistant, external, and runtime events may still be archived in `L1` for traceability.
- Do not let `assistant_freeform` or `assistant_quote` create new `L2` evidence by default.
- Do not let `assistant_tool_grounded` create new `L2` evidence in phase 1; keep it archived in `L1` only unless a future whitelist is added.
- Preserve backlinks from any derived or quoted `L2` artifact to the original `L1 event_id` set.
- Keep phase 1 fully rule-based; do not add an LLM-based classifier yet.
- Avoid widening unrelated memory APIs or changing existing `L2` prompt templates unless the policy layer requires new fields.

## Source Documents To Re-read Before Implementation

- `docs/project-overview.md`
- `docs/product-configuration-guide.md`
- `docs/task-agent-runtime-architecture.md`
- `docs/memory-system-design.md`
- `docs/superpowers/plans/2026-03-17-l2-cognition-write-pipeline.md`

## Problem Statement

Today `L2` work is triggered by `L1` events, but `L1` also contains assistant replies. Without evidence governance, assistant text can be mistaken for new user or world evidence. This creates three concrete risks:

1. assistant freeform replies can pollute user preferences and ToM assertions
2. assistant summaries can inflate evidence counts by re-stating earlier user messages
3. assistant tool-grounded replies can be mistaken for durable memory evidence even though the tool remains the better source of truth

The fix is to separate:

- event archival (`L1`)
- evidence identity classification
- write authorization and weighting
- downstream extraction

## Target Runtime Flow

```text
Bus / ingest_event
  -> normalize_runtime_event()
  -> L0 write
  -> L1 write
  -> enqueue L2 extraction

L2 extraction worker
  -> classify_event_evidence(event)
  -> resolve_l2_policy(classification)
  -> if policy denies all writes: mark skipped and stop
  -> allowed entity extraction
  -> allowed graph extraction
  -> allowed assertion extraction
  -> candidate persistence with evidence metadata
  -> reconcile / snapshot fan-out
```

## Semantic Model

### Core event metadata additions

Add or normalize these `MemoryEvent` fields:

- `speaker_role`
  Allowed values: `user | assistant | system | timeline | sensor | external`
- `grounding_type`
  Allowed values: `self_reported | observed | tool_grounded | quoted_from_history | model_inferred | freeform_generated`
- `derived_from_event_ids`
  List of `L1 event_id` values when an event is quoting, summarizing, or derived from earlier material
- `semantic_owner_hint`
  Allowed values: `user | assistant | world | third_party | mixed`
- `originality_type`
  Allowed values: `primary | derived | quoted | summarized`

These fields do not have to be manually supplied for every producer in phase 1; the classifier may synthesize defaults from source and metadata.

### Evidence classes

Implement these classes in code:

- `user_self_report`
- `user_report_about_others`
- `assistant_quote`
- `assistant_tool_grounded`
- `assistant_freeform`
- `external_observation`
- `system_runtime`

### Policy outputs

A policy decision must at minimum include:

- `allow_entity_extraction: bool`
- `allow_graph_write: bool`
- `allow_assertion_write: bool`
- `allow_snapshot_impact: bool`
- `graph_scope: none | world_only | full`
- `assertion_scope: none | topology_only | defensive_psychology | full`
- `evidence_weight: float`
- `count_as_new_evidence: bool`
- `require_source_backlink: bool`
- `skip_reason: str | None`

## Classifier Rules (Phase 1)

Use deterministic rules only.

### Rule order

1. runtime/system events
2. trusted external observations
3. assistant tool-grounded events
4. assistant quote/summarization events
5. remaining assistant replies
6. user-authored events

### Concrete rule table

- If `memory_domain == runtime_telemetry` or `speaker_role == system`:
  - classify as `system_runtime`
- If `source` or metadata indicates `timeline`, `sensor`, `calendar`, `location`, or `external_feed`:
  - classify as `external_observation`
- If `speaker_role == assistant` and metadata contains `tool_name`, `tool_call_id`, or `tool_result_ref`:
  - classify as `assistant_tool_grounded`
- If `speaker_role == assistant` and `derived_from_event_ids` is non-empty, or `grounding_type == quoted_from_history`:
  - classify as `assistant_quote`
- If `speaker_role == assistant` and none of the above matched:
  - classify as `assistant_freeform`
- If `speaker_role == user` and `semantic_owner_hint in {third_party, world}`:
  - classify as `user_report_about_others`
- Else if `speaker_role == user`:
  - classify as `user_self_report`

## Policy Mapping (Phase 1)

- `user_self_report`
  - graph: yes
  - assertion: yes
  - snapshot: yes
  - evidence weight: `1.0`
  - count as new evidence: yes
- `user_report_about_others`
  - graph: yes
  - assertion: limited
  - snapshot: limited
  - evidence weight: `0.8`
- `assistant_quote`
  - graph: no new writes
  - assertion: no
  - snapshot: no
  - evidence weight: `0.0`
  - count as new evidence: no
  - require backlink: yes
- `assistant_tool_grounded`
  - skip all writes in phase 1
  - evidence weight: `0.0`
  - keep the event in `L1` for traceability only
- `assistant_freeform`
  - skip all writes
  - evidence weight: `0.0`
- `external_observation`
  - graph: yes
  - assertion scope: `topology_only`
  - snapshot: limited
  - evidence weight: `0.7`
- `system_runtime`
  - skip all writes

## File Map

### New backend files

- `backend/src/magi/memory/l2_evidence_classifier.py`
  - `EvidenceClass` enum
  - `EvidenceClassification` DTO
  - default metadata derivation helpers
  - `classify_event_evidence(event)`
- `backend/src/magi/memory/l2_evidence_policy.py`
  - `PolicyDecision` DTO
  - `resolve_l2_policy(classification)`
- `backend/tests/memory/test_l2_evidence_classifier.py`
- `backend/tests/memory/test_l2_evidence_policy.py`

### Modified backend files

- `backend/src/magi/memory/event_contracts.py`
  - add the new optional evidence metadata fields
- `backend/src/magi/memory/l2_models.py`
  - add DTOs if shared contracts are needed by pipeline/store
- `backend/src/magi/memory/l2_pipeline.py`
  - classify before extraction
  - apply policy gates and scopes
  - surface skip reasons in pipeline stats/logs
- `backend/src/magi/memory/l2_cognition_store.py`
  - accept evidence metadata on graph/assertion writes
  - store `source_event_ids`, `evidence_class`, `evidence_weight`, and `is_derived_evidence` if schema changes are included in this phase
- `backend/src/magi/memory/__init__.py`
  - wire classifier/policy dependencies into `L2Pipeline`
- `backend/tests/memory/test_l2_pipeline.py`
  - integration coverage for assistant/user/external event classes
- `backend/tests/memory/test_memory_layers.py`
  - regression coverage that `L1` still stores all events while `L2` respects policy gates

### Optional later files (not phase 1)

- `backend/src/magi/memory/l2_evidence_policy_config.py`
- `backend/src/magi/api/routers/memory.py`
  - only if policy diagnostics need exposure to the frontend lab later

---

## Chunk 1: Add Evidence Metadata And Rule-Driven Classification

### Task 1: Extend event contracts with evidence-governance metadata

**Files:**
- Modify: `backend/src/magi/memory/event_contracts.py`
- Test: `backend/tests/memory/test_l2_evidence_classifier.py`

- [ ] **Step 1: Write failing tests for normalized event metadata defaults**

Cover these cases:
- user message defaults `speaker_role=user`
- assistant message defaults `speaker_role=assistant`
- timeline/sensor source defaults `speaker_role=external` or `timeline`
- `derived_from_event_ids` normalizes to an empty list when absent

- [ ] **Step 2: Run the focused metadata tests**

Run: `cd backend && pytest tests/memory/test_l2_evidence_classifier.py -k metadata -v`
Expected: FAIL because the new event fields do not exist yet.

- [ ] **Step 3: Add optional evidence metadata fields to `MemoryEvent` and normalization helpers**

Implementation notes:
- keep fields optional for existing callers
- normalize list fields to `[]`
- infer `speaker_role` from existing event source/type when metadata is absent

- [ ] **Step 4: Re-run the focused metadata tests**

Run: `cd backend && pytest tests/memory/test_l2_evidence_classifier.py -k metadata -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/src/magi/memory/event_contracts.py backend/tests/memory/test_l2_evidence_classifier.py
git commit -m "feat: add l2 evidence metadata"
```

### Task 2: Implement the evidence classifier

**Files:**
- Create: `backend/src/magi/memory/l2_evidence_classifier.py`
- Test: `backend/tests/memory/test_l2_evidence_classifier.py`

- [ ] **Step 1: Write failing classifier tests**

Cover these cases:
- user self-report becomes `user_self_report`
- user report with `semantic_owner_hint=third_party` becomes `user_report_about_others`
- assistant event with `tool_call_id` becomes `assistant_tool_grounded`
- assistant event with `derived_from_event_ids` becomes `assistant_quote`
- assistant event without grounding becomes `assistant_freeform`
- runtime event becomes `system_runtime`
- timeline event becomes `external_observation`

- [ ] **Step 2: Run the focused classifier tests**

Run: `cd backend && pytest tests/memory/test_l2_evidence_classifier.py -k classify -v`
Expected: FAIL because `l2_evidence_classifier.py` does not exist.

- [ ] **Step 3: Implement `EvidenceClass`, `EvidenceClassification`, and `classify_event_evidence()`**

Implementation notes:
- rule order must be deterministic and explicit
- include `source_event_ids` in the classification result
- include a machine-readable `reason_code` such as `assistant_tool_metadata` or `runtime_domain`

- [ ] **Step 4: Re-run the focused classifier tests**

Run: `cd backend && pytest tests/memory/test_l2_evidence_classifier.py -k classify -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/src/magi/memory/l2_evidence_classifier.py backend/tests/memory/test_l2_evidence_classifier.py
git commit -m "feat: classify l2 evidence"
```

---

## Chunk 2: Resolve Write Policy Before Any L2 Extraction

### Task 3: Implement the evidence policy resolver

**Files:**
- Create: `backend/src/magi/memory/l2_evidence_policy.py`
- Test: `backend/tests/memory/test_l2_evidence_policy.py`

- [ ] **Step 1: Write failing policy tests**

Cover these cases:
- `user_self_report` allows graph/assertion/snapshot impact with weight `1.0`
- `assistant_freeform` denies all writes
- `assistant_tool_grounded` is skipped by the resolver in phase 1
- `assistant_quote` denies new evidence and requires backlinks
- `external_observation` allows graph and `topology_only` assertion scope

- [ ] **Step 2: Run the focused policy tests**

Run: `cd backend && pytest tests/memory/test_l2_evidence_policy.py -v`
Expected: FAIL because the resolver module does not exist.

- [ ] **Step 3: Implement `PolicyDecision` and `resolve_l2_policy()`**

Implementation notes:
- make all defaults explicit
- include `skip_reason`
- keep policy mapping in one table or one small pure function rather than scattered if/else branches

- [ ] **Step 4: Re-run the focused policy tests**

Run: `cd backend && pytest tests/memory/test_l2_evidence_policy.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/src/magi/memory/l2_evidence_policy.py backend/tests/memory/test_l2_evidence_policy.py
git commit -m "feat: add l2 evidence policy"
```

### Task 4: Gate L2 extraction through classifier and policy

**Files:**
- Modify: `backend/src/magi/memory/l2_pipeline.py`
- Modify: `backend/src/magi/memory/__init__.py`
- Test: `backend/tests/memory/test_l2_pipeline.py`

- [ ] **Step 1: Write failing integration tests for policy-gated extraction**

Cover these cases:
- assistant freeform event is stored in `L1` but produces no graph/assertion writes
- assistant tool-grounded event is archived in `L1` but skipped by `L2` extraction
- assistant quote event does not add new evidence counts
- user self-report still behaves as before

- [ ] **Step 2: Run the focused pipeline tests**

Run: `cd backend && pytest tests/memory/test_l2_pipeline.py -k evidence_policy -v`
Expected: FAIL because `L2Pipeline` does not yet classify or gate events.

- [ ] **Step 3: Inject classifier and policy resolver into the pipeline**

Implementation notes:
- classify immediately after loading the `L1` event
- stop early when policy denies all writes
- pass `graph_scope` and `assertion_scope` into downstream extraction helpers
- preserve queue stats for skipped events, with reasons such as `assistant_freeform` or `system_runtime`

- [ ] **Step 4: Re-run the focused pipeline tests**

Run: `cd backend && pytest tests/memory/test_l2_pipeline.py -k evidence_policy -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/src/magi/memory/l2_pipeline.py backend/src/magi/memory/__init__.py backend/tests/memory/test_l2_pipeline.py
git commit -m "feat: gate l2 writes by evidence policy"
```

---

## Chunk 3: Preserve Evidence Backlinks And Prevent Derived-Evidence Inflation

### Task 5: Persist evidence metadata for graph/assertion records

**Files:**
- Modify: `backend/src/magi/memory/l2_cognition_store.py`
- Test: `backend/tests/memory/test_l2_cognition_store.py`

- [ ] **Step 1: Write failing store tests for evidence metadata persistence**

Cover these cases:
- graph edges can store `evidence_class` and `evidence_weight`
- assertion rows can store `is_derived_evidence`
- assistant-quoted artifacts preserve `source_event_ids`

- [ ] **Step 2: Run the focused store tests**

Run: `cd backend && pytest tests/memory/test_l2_cognition_store.py -k evidence_metadata -v`
Expected: FAIL because the schema and persistence methods do not accept the new fields.

- [ ] **Step 3: Extend the schema and write methods**

Implementation notes:
- prefer additive schema changes only
- do not break existing rows; backfill defaults for old data
- keep JSON-safe storage for `source_event_ids`

- [ ] **Step 4: Re-run the focused store tests**

Run: `cd backend && pytest tests/memory/test_l2_cognition_store.py -k evidence_metadata -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/src/magi/memory/l2_cognition_store.py backend/tests/memory/test_l2_cognition_store.py
git commit -m "feat: store l2 evidence metadata"
```

### Task 6: Deduplicate quoted or summarized evidence during reconcile

**Files:**
- Modify: `backend/src/magi/memory/l2_cognition_store.py`
- Modify: `backend/src/magi/memory/l2_pipeline.py`
- Test: `backend/tests/memory/test_l2_pipeline.py`
- Test: `backend/tests/memory/test_l2_cognition_store.py`

- [ ] **Step 1: Write failing tests for deduplicated evidence counting**

Cover these cases:
- one user event plus one assistant quote still counts as one primary evidence item
- repeated assistant summaries do not push an assertion from tentative to stable
- direct user evidence still promotes stability normally

- [ ] **Step 2: Run the focused dedup tests**

Run: `cd backend && pytest tests/memory/test_l2_pipeline.py -k dedup && pytest tests/memory/test_l2_cognition_store.py -k dedup -v`
Expected: FAIL because reconcile still counts derived evidence as independent support.

- [ ] **Step 3: Implement evidence-count deduplication**

Implementation notes:
- compute support counts using the canonical source event ids
- fall back to local `event_id` when no source backlink exists
- keep evidence weight available for future weighted reconcile but do not overcomplicate phase 1

- [ ] **Step 4: Re-run the focused dedup tests**

Run: `cd backend && pytest tests/memory/test_l2_pipeline.py -k dedup && pytest tests/memory/test_l2_cognition_store.py -k dedup -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/src/magi/memory/l2_cognition_store.py backend/src/magi/memory/l2_pipeline.py backend/tests/memory/test_l2_pipeline.py backend/tests/memory/test_l2_cognition_store.py
git commit -m "fix: deduplicate derived l2 evidence"
```

---

## Chunk 4: Regression Coverage And Operational Safety

### Task 7: Add full-path regression tests and observability

**Files:**
- Modify: `backend/tests/memory/test_memory_layers.py`
- Modify: `backend/tests/memory/test_l2_pipeline.py`
- Optional Modify: `backend/src/magi/memory/integration.py`

- [ ] **Step 1: Write failing end-to-end tests for mixed-source memory flows**

Cover these cases:
- `L1` still archives assistant replies even when `L2` skips them
- user self-report followed by assistant freeform does not inflate `L2`
- assistant tool-grounded weather reply is retained in `L1` but does not create any `L2` evidence

- [ ] **Step 2: Run the end-to-end regression tests**

Run: `cd backend && pytest tests/memory/test_memory_layers.py tests/memory/test_l2_pipeline.py -k mixed_source -v`
Expected: FAIL until pipeline stats and write gates are wired through the full flow.

- [ ] **Step 3: Add logging and stats for skipped-policy events**

Implementation notes:
- record counts by `evidence_class`
- record skip reasons such as `assistant_freeform` and `system_runtime`
- do not expose noisy debug payloads in public APIs unless explicitly needed

- [ ] **Step 4: Re-run the end-to-end regression tests**

Run: `cd backend && pytest tests/memory/test_memory_layers.py tests/memory/test_l2_pipeline.py -k mixed_source -v`
Expected: PASS.

- [ ] **Step 5: Run the broader backend regression suite**

Run:
```bash
cd backend
pytest tests/memory/test_l2_evidence_classifier.py \
       tests/memory/test_l2_evidence_policy.py \
       tests/memory/test_l2_cognition_store.py \
       tests/memory/test_l2_pipeline.py \
       tests/memory/test_memory_layers.py \
       tests/api/test_memory_api.py -v
```
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add backend/src/magi/memory/integration.py backend/tests/memory/test_memory_layers.py backend/tests/memory/test_l2_pipeline.py
git commit -m "test: cover l2 evidence governance"
```

---

## Open Questions To Resolve During Execution

- Whether `speaker_role` should be inferred in `normalize_runtime_event()` or only attached by event producers
- Whether a future whitelist should allow selected `assistant_tool_grounded` events into `L2` under explicit product rules
- Whether `external_observation` should allow any assertion writes in phase 1, or only graph writes
- Whether `user_report_about_others` should write third-party ToM assertions immediately or only after stricter validation

## Non-Goals For This Plan

- No LLM-based evidence classifier fallback yet
- No frontend evidence-policy controls yet
- No separate evidence-governance admin UI
- No attempt to solve semantic-owner NLP perfectly in phase 1

## Success Criteria

The plan is complete when the codebase can demonstrate all of the following:

- assistant freeform replies remain searchable in `L1` but do not write new `L2` cognition
- assistant quotes do not increase effective evidence counts
- assistant tool-grounded outputs stay outside `L2` by default; if product needs change later, reintroduce them behind an explicit whitelist and dedicated tests
- user self-reports continue to drive the existing `L2` pipeline as before
- mixed-source evidence handling is deterministic, test-covered, and explainable from logs and policy outputs
