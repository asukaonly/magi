# L2 Microbatch Extraction Implementation Plan

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace single-event L2 extraction with session-aware microbatch extraction so L2 makes fewer, larger, more stable LLM calls while preserving L1-first durability and existing downstream L2 persistence behavior.

**Architecture:** Keep `UnifiedMemoryStore` and `L1EventStore` behavior unchanged at the truth layer, then refactor `L2Pipeline` into a staging-plus-batch-extraction pipeline. Buckets group eligible events by `session_id` or fallback `user_id`, flush on time or size limits, and feed one unified extraction pass per batch into the existing validation, contradiction, reconcile, and snapshot stages.

**Tech Stack:** Python 3.10+, asyncio, existing `UnifiedMemoryStore`, `L2Pipeline`, `L2LLMService`, `L1EventStore`, Pydantic config models, React settings UI, TypeScript config contracts, pytest, Vitest.

---

## Scope Guardrails

- Keep `L1` persistence semantics unchanged.
- Do not implement cross-session history recall in this plan.
- Do not implement deep-model conflict arbitration in this plan.
- Do not add a persistent disk-backed staging queue in this plan.
- Expose only one new user-facing setting: `l2_batch_flush_interval_seconds`.
- Keep internal batch-size and token-cap thresholds as backend constants.

## Source Documents To Re-read Before Implementation

- `docs/project-overview.md`
- `docs/product-configuration-guide.md`
- `docs/task-agent-runtime-architecture.md`
- `docs/memory-system-design.md`
- `docs/superpowers/specs/2026-03-22-l2-microbatch-extraction-design.md`

## File Map

### Modified backend files

- `backend/src/magi/config/models.py`
  Add the new memory setting and validation boundary.
- `backend/src/magi/api/routers/config.py`
  Expose the new setting through the config API model and save/load paths.
- `backend/src/magi/memory/__init__.py`
  Pass the batch flush interval into `L2Pipeline`.
- `backend/src/magi/memory/l2/models.py`
  Add batch bucket and batch job contracts.
- `backend/src/magi/memory/l2/pipeline.py`
  Replace direct single-event extraction enqueueing with staged microbatch buffering and batch extraction workers.
- `backend/src/magi/memory/l2/llm_service.py`
  Accept real batch event windows and pass richer batch metadata to the prompt/logging layer.
- `backend/src/magi/memory/l2/prompts.py`
  Render a true batch-oriented unified extraction prompt payload.
- `backend/tests/memory/test_l2_pipeline.py`
  Add coverage for staging, flushing, batch extraction, and shutdown behavior.
- `backend/tests/api/test_config_router.py`
  Add config API coverage if this suite already owns memory config fields.

### Modified frontend files

- `frontend/src/api/modules/config.ts`
  Extend the memory config contract with the new batch interval field.
- `frontend/src/pages/Settings.tsx`
  Add an L2 batch interval control to expert memory settings.
- `frontend/src/i18n/locales/en/app.json`
  Add English label and description.
- `frontend/src/i18n/locales/zh-CN/app.json`
  Add Chinese label and description.
- `frontend/src/__tests__/configForms.test.tsx`
  Extend config-form coverage if this suite already owns memory settings shape.
- `frontend/src/__tests__/settingsPage.test.tsx`
  Add UI-level validation for the new setting if this suite already covers memory controls.

---

## Chunk 1: Add Configuration And Batch Contracts

### Task 1: Add the backend memory setting for L2 batch flush interval

**Files:**
- Modify: `backend/src/magi/config/models.py`
- Modify: `backend/src/magi/api/routers/config.py`
- Test: `backend/tests/api/test_config_router.py`

- [ ] **Step 1: Write the failing config tests**

Cover these cases:
- default `l2_batch_flush_interval_seconds` is `60`
- the field rejects values below `30`
- the config API model round-trips the field through serialization

- [ ] **Step 2: Run the focused backend config tests**

Run: `cd backend && pytest tests/api/test_config_router.py -k l2_batch_flush_interval -v`
Expected: FAIL because the new field does not exist yet.

- [ ] **Step 3: Implement the config field**

Add `l2_batch_flush_interval_seconds: int = Field(default=60, ge=30)` to the backend memory settings and the config router memory model.

Implementation notes:
- keep naming aligned between persisted config and API payloads
- do not expose internal event-count or token-cap limits yet

- [ ] **Step 4: Re-run the focused config tests**

Run: `cd backend && pytest tests/api/test_config_router.py -k l2_batch_flush_interval -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/src/magi/config/models.py backend/src/magi/api/routers/config.py backend/tests/api/test_config_router.py
git commit -m "feat: add l2 batch flush interval config"
```

### Task 2: Add L2 batch bucket and batch job models

**Files:**
- Modify: `backend/src/magi/memory/l2/models.py`
- Test: `backend/tests/memory/test_l2_pipeline.py`

- [ ] **Step 1: Write the failing model tests**

Cover these cases:
- a bucket tracks pending events and token estimates
- a batch job captures flush reason and event ordering
- session-based and user-based bucket keys are normalized consistently

- [ ] **Step 2: Run the focused L2 model tests**

Run: `cd backend && pytest tests/memory/test_l2_pipeline.py -k microbatch_models -v`
Expected: FAIL because the batch contracts do not exist yet.

- [ ] **Step 3: Implement the batch contracts**

Add focused contracts for:
- `L2PendingBatchBucket`
- `L2BatchJob`

Implementation notes:
- keep contracts lightweight and JSON/log friendly
- store enough metadata for flush stats and debugging
- do not move persistence logic into the models

- [ ] **Step 4: Re-run the focused model tests**

Run: `cd backend && pytest tests/memory/test_l2_pipeline.py -k microbatch_models -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/src/magi/memory/l2/models.py backend/tests/memory/test_l2_pipeline.py
git commit -m "feat: add l2 microbatch job models"
```

---

## Chunk 2: Refactor The L2 Pipeline To Stage And Flush Microbatches

### Task 3: Pass the new setting into the L2 pipeline

**Files:**
- Modify: `backend/src/magi/memory/__init__.py`
- Test: `backend/tests/memory/test_l2_pipeline.py`

- [ ] **Step 1: Write the failing wiring test**

Cover this case:
- `UnifiedMemoryStore` constructs `L2Pipeline` with the configured batch flush interval

- [ ] **Step 2: Run the focused wiring test**

Run: `cd backend && pytest tests/memory/test_l2_pipeline.py -k flush_interval_wiring -v`
Expected: FAIL because the pipeline constructor does not accept the new setting yet.

- [ ] **Step 3: Implement the wiring**

Extend `UnifiedMemoryStore` construction so the configured interval is passed into `L2Pipeline`.

- [ ] **Step 4: Re-run the focused wiring test**

Run: `cd backend && pytest tests/memory/test_l2_pipeline.py -k flush_interval_wiring -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/src/magi/memory/__init__.py backend/tests/memory/test_l2_pipeline.py
git commit -m "refactor: wire l2 batch flush interval"
```

### Task 4: Replace direct event extraction enqueueing with staged buckets

**Files:**
- Modify: `backend/src/magi/memory/l2/pipeline.py`
- Test: `backend/tests/memory/test_l2_pipeline.py`

- [ ] **Step 1: Write the failing staging tests**

Cover these cases:
- `enqueue_event()` stages an eligible event instead of immediately sending it to extraction
- events with the same `session_id` share a bucket
- events without `session_id` but with the same `user_id` share a bucket
- events with neither identifier fall back to direct single-event handling

- [ ] **Step 2: Run the focused staging tests**

Run: `cd backend && pytest tests/memory/test_l2_pipeline.py -k staging_bucket -v`
Expected: FAIL because the pipeline still enqueues single events directly.

- [ ] **Step 3: Implement in-memory staging buckets**

Refactor `L2Pipeline` to:
- maintain bucket state keyed by normalized session/user identifiers
- keep per-bucket event lists, timestamps, and estimated tokens
- separate staged work from extraction work

Implementation notes:
- preserve existing evidence-gating behavior
- keep the single-event fallback path isolated and explicit
- do not yet add persistence for staged buckets

- [ ] **Step 4: Re-run the focused staging tests**

Run: `cd backend && pytest tests/memory/test_l2_pipeline.py -k staging_bucket -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/src/magi/memory/l2/pipeline.py backend/tests/memory/test_l2_pipeline.py
git commit -m "refactor: stage l2 events into microbatches"
```

### Task 5: Add mixed flush triggers and batch extraction jobs

**Files:**
- Modify: `backend/src/magi/memory/l2/pipeline.py`
- Test: `backend/tests/memory/test_l2_pipeline.py`

- [ ] **Step 1: Write the failing flush tests**

Cover these cases:
- a bucket flushes after the configured interval
- a bucket flushes early when it reaches the event-count cap
- a bucket flushes early when it reaches the estimated-token cap
- a flush produces one `L2BatchJob` with ordered events and a flush reason

- [ ] **Step 2: Run the focused flush tests**

Run: `cd backend && pytest tests/memory/test_l2_pipeline.py -k batch_flush -v`
Expected: FAIL because time/size/token-based flushing is not implemented yet.

- [ ] **Step 3: Implement flush scheduling and batch job creation**

Add:
- a periodic flush worker
- bucket eligibility checks
- batch job creation and queueing
- internal constants for max events and max estimated tokens

Implementation notes:
- use deterministic ordering by event timestamp
- mark buckets as flushing so new events land in the next window
- keep shutdown flush best-effort and timeout-bounded

- [ ] **Step 4: Re-run the focused flush tests**

Run: `cd backend && pytest tests/memory/test_l2_pipeline.py -k batch_flush -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/src/magi/memory/l2/pipeline.py backend/tests/memory/test_l2_pipeline.py
git commit -m "feat: add l2 microbatch flush scheduling"
```

### Task 6: Preserve extraction, retry, and shutdown safety with batch jobs

**Files:**
- Modify: `backend/src/magi/memory/l2/pipeline.py`
- Test: `backend/tests/memory/test_l2_pipeline.py`

- [ ] **Step 1: Write the failing resilience tests**

Cover these cases:
- batch extraction failure increments failure stats without blocking later batches
- repeatedly failing batches are retried with bounded attempts
- oversized or repeatedly failing batches can be split before final failure
- shutdown flushes pending buckets best-effort without hanging forever

- [ ] **Step 2: Run the focused resilience tests**

Run: `cd backend && pytest tests/memory/test_l2_pipeline.py -k microbatch_resilience -v`
Expected: FAIL because the current pipeline does not manage batch retries or shutdown flush semantics.

- [ ] **Step 3: Implement resilience behavior**

Add:
- bounded retry policy for batch jobs
- split-and-retry behavior for stubborn batches
- shutdown drain behavior with clear timeout boundaries

Implementation notes:
- never compromise `L1` durability to satisfy L2 flushing
- keep retry metadata out of persistent memory tables

- [ ] **Step 4: Re-run the focused resilience tests**

Run: `cd backend && pytest tests/memory/test_l2_pipeline.py -k microbatch_resilience -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/src/magi/memory/l2/pipeline.py backend/tests/memory/test_l2_pipeline.py
git commit -m "fix: harden l2 microbatch retries"
```

---

## Chunk 3: Make Unified Extraction Truly Batch-Aware

### Task 7: Render a true batch extraction prompt payload

**Files:**
- Modify: `backend/src/magi/memory/l2/prompts.py`
- Test: `backend/tests/memory/test_l2_pipeline.py`

- [ ] **Step 1: Write the failing prompt tests**

Cover these cases:
- the prompt includes multiple ordered events in `event_window`
- the prompt contains batch summary metadata
- the prompt retains a small amount of external context text
- the prompt still includes `context_bundle`

- [ ] **Step 2: Run the focused prompt tests**

Run: `cd backend && pytest tests/memory/test_l2_pipeline.py -k batch_prompt -v`
Expected: FAIL because the prompt still assumes one event in practice.

- [ ] **Step 3: Implement the batch prompt payload**

Update the prompt renderer so `event_window` contains:
- `event_ids`
- `events`
- `summary`
- `context_texts`

Implementation notes:
- keep output schema stable where possible
- add prompt rules that prefer `supporting_event_ids` and cross-event grounding

- [ ] **Step 4: Re-run the focused prompt tests**

Run: `cd backend && pytest tests/memory/test_l2_pipeline.py -k batch_prompt -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/src/magi/memory/l2/prompts.py backend/tests/memory/test_l2_pipeline.py
git commit -m "refactor: render l2 batch extraction prompts"
```

### Task 8: Update the LLM service and extraction path to consume batch windows

**Files:**
- Modify: `backend/src/magi/memory/l2/llm_service.py`
- Modify: `backend/src/magi/memory/l2/pipeline.py`
- Test: `backend/tests/memory/test_l2_pipeline.py`

- [ ] **Step 1: Write the failing extraction tests**

Cover these cases:
- one flushed batch produces one unified extraction LLM call
- the batch call logs all batch event ids
- the existing candidate validation and persistence path still runs after batch extraction
- ToM confidence clamping remains conservative for weak evidence

- [ ] **Step 2: Run the focused extraction tests**

Run: `cd backend && pytest tests/memory/test_l2_pipeline.py -k batch_extraction -v`
Expected: FAIL because the extraction worker still expects single events.

- [ ] **Step 3: Implement batch-aware extraction**

Refactor the extraction worker to:
- consume `L2BatchJob`
- build a batch `event_window`
- collect batch-external context texts conservatively
- pass batch metadata into logging and LLM invocation

Implementation notes:
- downstream graph/assertion persistence should still attach concrete evidence event ids
- keep existing contradiction, reconcile, and snapshot queueing behavior compatible with batch output

- [ ] **Step 4: Re-run the focused extraction tests**

Run: `cd backend && pytest tests/memory/test_l2_pipeline.py -k batch_extraction -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/src/magi/memory/l2/llm_service.py backend/src/magi/memory/l2/pipeline.py backend/tests/memory/test_l2_pipeline.py
git commit -m "feat: run l2 extraction as microbatches"
```

### Task 9: Add batch-oriented pipeline stats and reporting

**Files:**
- Modify: `backend/src/magi/memory/l2/pipeline.py`
- Modify: `backend/src/magi/memory/integration.py`
- Test: `backend/tests/memory/test_l2_pipeline.py`

- [ ] **Step 1: Write the failing stats tests**

Cover these cases:
- pipeline stats include batch flush count
- stats include flush counts by reason
- stats expose pending staged event count and active bucket count
- integration reporting surfaces the new L2 batch stats cleanly

- [ ] **Step 2: Run the focused stats tests**

Run: `cd backend && pytest tests/memory/test_l2_pipeline.py -k microbatch_stats -v`
Expected: FAIL because the new counters do not exist yet.

- [ ] **Step 3: Implement batch stats**

Add and surface:
- `batch_flush_count`
- `batch_flush_by_reason`
- `avg_batch_event_count`
- `avg_batch_estimated_tokens`
- `pending_staged_event_count`
- `active_bucket_count`

- [ ] **Step 4: Re-run the focused stats tests**

Run: `cd backend && pytest tests/memory/test_l2_pipeline.py -k microbatch_stats -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/src/magi/memory/l2/pipeline.py backend/src/magi/memory/integration.py backend/tests/memory/test_l2_pipeline.py
git commit -m "feat: add l2 microbatch pipeline stats"
```

---

## Chunk 4: Expose The Setting In The Frontend And Verify End-To-End Behavior

### Task 10: Extend frontend config types and settings UI

**Files:**
- Modify: `frontend/src/api/modules/config.ts`
- Modify: `frontend/src/pages/Settings.tsx`
- Modify: `frontend/src/i18n/locales/en/app.json`
- Modify: `frontend/src/i18n/locales/zh-CN/app.json`
- Test: `frontend/src/__tests__/configForms.test.tsx`
- Test: `frontend/src/__tests__/settingsPage.test.tsx`

- [ ] **Step 1: Write the failing frontend tests**

Cover these cases:
- memory config type includes `l2_batch_flush_interval_seconds`
- settings page renders the new L2 interval control
- the UI enforces the minimum visible boundary of `30`
- both locales contain matching translation keys

- [ ] **Step 2: Run the focused frontend tests**

Run: `cd frontend && npm run test -- --runInBand configForms settingsPage`
Expected: FAIL because the new field and UI do not exist yet.

- [ ] **Step 3: Implement the UI and locale strings**

Add one expert-facing control near existing L2 settings.

Implementation notes:
- keep the control simple and numeric
- reuse existing settings page interaction patterns
- keep `zh-CN` and `en` keys aligned

- [ ] **Step 4: Re-run the focused frontend tests**

Run: `cd frontend && npm run test -- --runInBand configForms settingsPage`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/api/modules/config.ts frontend/src/pages/Settings.tsx frontend/src/i18n/locales/en/app.json frontend/src/i18n/locales/zh-CN/app.json frontend/src/__tests__/configForms.test.tsx frontend/src/__tests__/settingsPage.test.tsx
git commit -m "feat: expose l2 batch flush interval setting"
```

### Task 11: Run backend and frontend verification for the whole feature

**Files:**
- Modify: `backend/tests/memory/test_l2_pipeline.py`
- Modify: `backend/tests/api/test_config_router.py`
- Modify: `frontend/src/__tests__/configForms.test.tsx`
- Modify: `frontend/src/__tests__/settingsPage.test.tsx`

- [ ] **Step 1: Run the targeted backend test suite**

Run: `cd backend && pytest tests/memory/test_l2_pipeline.py tests/api/test_config_router.py -v`
Expected: PASS.

- [ ] **Step 2: Run the targeted frontend test suite**

Run: `cd frontend && npm run test -- --runInBand configForms settingsPage`
Expected: PASS.

- [ ] **Step 3: Run the relevant frontend type checks**

Run: `cd frontend && npm run type-check`
Expected: PASS.

- [ ] **Step 4: Sanity-check the batch stats manually if an app environment is available**

Suggested manual verification:
- produce a burst of eligible chat events in one session
- confirm `L1` stores each event immediately
- confirm `L2` emits fewer extraction calls than event count
- confirm stats show the correct flush reasons

- [ ] **Step 5: Commit**

```bash
git add backend/tests/memory/test_l2_pipeline.py backend/tests/api/test_config_router.py frontend/src/__tests__/configForms.test.tsx frontend/src/__tests__/settingsPage.test.tsx
git commit -m "test: verify l2 microbatch extraction flow"
```

Plan complete and saved to `docs/superpowers/plans/2026-03-22-l2-microbatch-extraction.md`. Ready to execute?
