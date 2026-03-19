# LongMemEval Memory Eval Integration Plan

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Integrate LongMemEval as a memory-subsystem benchmark for Magi by adding benchmark-agnostic memory evaluation support under `backend/src/magi/memory/eval_support/` and a LongMemEval-specific runner under `benchmark/longmemeval/`.

**Architecture:** Keep all benchmark-specific parsing, replay policy, and report generation outside the product runtime in `benchmark/`. Add a thin, stable memory-eval harness inside `backend/src/magi/memory/eval_support/` that can write replayed history into isolated namespaces, query memory without chat/personality layers, and return normalized retrieval traces. Phase 1 evaluates only memory read/write and retrieval quality; chat-integrated evaluation is explicitly out of scope.

**Tech Stack:** Python 3.10+, existing Magi memory pipeline and retrieval services, dataclasses/Pydantic-style contracts where already used in the repo, pytest, json/jsonl, LongMemEval official datasets and evaluation scripts.

---

## Scope Guardrails

- Only build memory-subsystem evaluation in this plan. Do not route through `ChatTaskAgent`, persona prompts, or user-facing response rendering.
- Do not place LongMemEval-specific parsing or dataset assumptions inside `backend/src/magi/`.
- Do not write directly to SQLite tables from benchmark code; always use the memory write path exposed by `eval_support`.
- Keep evaluation data isolated by namespace so benchmark runs cannot pollute normal runtime memory.
- Phase 1 must support LongMemEval `oracle` first. `s_cleaned` support comes after the minimal loop is stable.
- Retrieval trace export is required in Phase 1. Official answer judging integration is Phase 2 within this same plan.
- Do not add frontend scope.

## Source Documents To Re-read Before Implementation

- `docs/project-overview.md`
- `docs/task-agent-runtime-architecture.md`
- `docs/memory-system-design.md`
- `docs/hybrid-retrieval-design.md`
- `docs/superpowers/plans/2026-03-18-chat-trace-observability.md`
- `https://github.com/xiaowu0162/LongMemEval`

## File Map

### New backend files

- `backend/src/magi/memory/eval_support/__init__.py`
  Public exports for the benchmark-agnostic memory evaluation harness.
- `backend/src/magi/memory/eval_support/contracts.py`
  Stable contracts for benchmark replay writes, memory queries, retrieval hits, and trace payloads.
- `backend/src/magi/memory/eval_support/namespace.py`
  Namespace helpers for creating, resetting, and isolating benchmark runs.
- `backend/src/magi/memory/eval_support/writer.py`
  Benchmark-facing memory write adapter that turns replay records into memory-ingestible events.
- `backend/src/magi/memory/eval_support/reader.py`
  Benchmark-facing memory query adapter that bypasses chat rendering and returns normalized retrieval results.
- `backend/src/magi/memory/eval_support/trace.py`
  Retrieval trace normalization helpers for session ids, turn ids, event ids, and raw retrieval diagnostics.
- `backend/src/magi/memory/eval_support/service.py`
  Thin orchestration layer combining namespace, writer, reader, and trace helpers.
- `backend/tests/memory/test_eval_support_contracts.py`
- `backend/tests/memory/test_eval_support_namespace.py`
- `backend/tests/memory/test_eval_support_writer.py`
- `backend/tests/memory/test_eval_support_reader.py`
- `backend/tests/memory/test_eval_support_service.py`

### New benchmark files

- `benchmark/README.md`
  Explains benchmark directory conventions and how it differs from runtime code.
- `benchmark/common/io.py`
  Shared json/jsonl helpers for benchmark runners.
- `benchmark/common/paths.py`
  Output directory and dataset path helpers.
- `benchmark/longmemeval/README.md`
  LongMemEval-specific instructions, dataset preparation, and run examples.
- `benchmark/longmemeval/adapter.py`
  Converts LongMemEval dataset rows into replay sessions plus final query payloads.
- `benchmark/longmemeval/runner.py`
  Runs replay + query against Magi eval support and emits predictions and traces.
- `benchmark/longmemeval/report.py`
  Produces local summary metrics and prepares outputs for official LongMemEval evaluation.
- `benchmark/longmemeval/configs/oracle.sample.json`
  Minimal runner config example for `oracle`.
- `benchmark/tests/test_longmemeval_adapter.py`
- `benchmark/tests/test_longmemeval_runner.py`
- `benchmark/tests/test_longmemeval_report.py`

### Likely modified backend files

- `backend/src/magi/memory/__init__.py`
  Export or wire eval-support dependencies if the current memory package pattern expects it.
- `backend/src/magi/memory/hybrid_retrieval/service.py`
  Only if a small extension is needed to expose stable trace metadata without chat-specific wrappers.
- `backend/src/magi/core/runtime_bindings.py`
  Only if eval support needs safe access to the initialized unified memory store through an existing runtime binding.

### Files that should not be modified in this plan unless proven necessary

- `backend/src/magi/agent/`
- `frontend/src/`
- `backend/src/magi/personality/`
- `backend/src/magi/api/routers/messages.py`

---

## Chunk 1: Add Benchmark-Agnostic Eval Support Contracts

### Task 1: Define stable write/query/result contracts for memory evaluation

**Files:**
- Create: `backend/src/magi/memory/eval_support/contracts.py`
- Create: `backend/tests/memory/test_eval_support_contracts.py`

- [ ] **Step 1: Write failing contract tests**

Cover these cases:
- `EvalMemoryWriteRecord` requires `namespace`, `session_id`, `timestamp`, `role`, and `content`
- `EvalMemoryQuery` defaults `top_k` and `mode`
- `EvalMemoryQueryResult` de-duplicates `retrieved_session_ids` and `retrieved_turn_ids`
- `EvalMemoryHit` preserves `event_id`, `session_id`, `turn_id`, and `score`

- [ ] **Step 2: Run the focused contract tests**

Run: `cd backend && pytest tests/memory/test_eval_support_contracts.py -v`
Expected: FAIL because the module does not exist.

- [ ] **Step 3: Implement `contracts.py`**

Add contracts for:
- `EvalMemoryWriteRecord`
- `EvalMemoryQuery`
- `EvalMemoryHit`
- `EvalMemoryQueryResult`

Implementation notes:
- Keep these contracts benchmark-agnostic.
- Use simple dataclasses unless an existing local pattern clearly favors Pydantic.
- Include optional `turn_id` and `metadata`.
- Include a `trace: dict[str, Any]` field in query results for later retrieval diagnostics.

- [ ] **Step 4: Re-run the focused contract tests**

Run: `cd backend && pytest tests/memory/test_eval_support_contracts.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/src/magi/memory/eval_support/contracts.py backend/tests/memory/test_eval_support_contracts.py
git commit -m "feat: add memory eval support contracts"
```

### Task 2: Add namespace isolation helpers for benchmark runs

**Files:**
- Create: `backend/src/magi/memory/eval_support/namespace.py`
- Create: `backend/tests/memory/test_eval_support_namespace.py`

- [ ] **Step 1: Write failing namespace tests**

Cover these cases:
- benchmark namespace ids are deterministic from benchmark name, run id, and question id
- namespace reset can target a single namespace without deleting others
- namespace labels are safe for filesystem/logging usage

- [ ] **Step 2: Run the focused namespace tests**

Run: `cd backend && pytest tests/memory/test_eval_support_namespace.py -v`
Expected: FAIL because the namespace module does not exist.

- [ ] **Step 3: Implement `namespace.py`**

Add:
- namespace id builder
- namespace validation/sanitization
- isolated reset helper API

Implementation notes:
- Start with an in-memory or service-level reset contract if full deletion is not yet supported.
- Keep destructive behavior explicit; do not default to wiping all eval namespaces.

- [ ] **Step 4: Re-run the focused namespace tests**

Run: `cd backend && pytest tests/memory/test_eval_support_namespace.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/src/magi/memory/eval_support/namespace.py backend/tests/memory/test_eval_support_namespace.py
git commit -m "feat: add eval namespace helpers"
```

---

## Chunk 2: Build The Memory Eval Harness

### Task 3: Implement the replay writer that uses the memory ingest path

**Files:**
- Create: `backend/src/magi/memory/eval_support/writer.py`
- Create: `backend/tests/memory/test_eval_support_writer.py`

- [ ] **Step 1: Write failing writer tests**

Cover these cases:
- replay writes turn records in timestamp order
- user and assistant roles map into memory events correctly
- namespace and session metadata are preserved
- writes go through the ingest path, not direct storage internals

- [ ] **Step 2: Run the focused writer tests**

Run: `cd backend && pytest tests/memory/test_eval_support_writer.py -v`
Expected: FAIL because the writer module does not exist.

- [ ] **Step 3: Implement `writer.py`**

Add a writer class that:
- accepts `EvalMemoryWriteRecord`
- turns it into a normalized runtime/memory event
- sends it through the supported memory ingest path

Implementation notes:
- Reuse existing event normalization rules where possible.
- Preserve timestamp, role, namespace, session id, and optional turn id in metadata.
- Keep this layer free of LongMemEval naming.

- [ ] **Step 4: Re-run the focused writer tests**

Run: `cd backend && pytest tests/memory/test_eval_support_writer.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/src/magi/memory/eval_support/writer.py backend/tests/memory/test_eval_support_writer.py
git commit -m "feat: add eval memory writer"
```

### Task 4: Implement the memory-only reader and retrieval trace normalizer

**Files:**
- Create: `backend/src/magi/memory/eval_support/reader.py`
- Create: `backend/src/magi/memory/eval_support/trace.py`
- Create: `backend/tests/memory/test_eval_support_reader.py`

- [ ] **Step 1: Write failing reader tests**

Cover these cases:
- a query returns normalized hits without chat rendering
- session ids, turn ids, and event ids are exposed in the result
- duplicate ids are collapsed in `retrieved_session_ids`
- trace contains raw retrieval metadata useful for later analysis

- [ ] **Step 2: Run the focused reader tests**

Run: `cd backend && pytest tests/memory/test_eval_support_reader.py -v`
Expected: FAIL because the reader and trace modules do not exist.

- [ ] **Step 3: Implement `reader.py` and `trace.py`**

Add a reader class that:
- accepts `EvalMemoryQuery`
- calls the memory retrieval layer directly
- converts raw retrieval payloads into `EvalMemoryQueryResult`

Add trace helpers that:
- extract session ids
- extract turn ids
- extract event ids
- preserve retrieval scores and layer diagnostics where available

Implementation notes:
- Do not invoke personality or final answer synthesis.
- If current retrieval payloads do not expose enough ids, add the smallest safe extension to the retrieval service.

- [ ] **Step 4: Re-run the focused reader tests**

Run: `cd backend && pytest tests/memory/test_eval_support_reader.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/src/magi/memory/eval_support/reader.py backend/src/magi/memory/eval_support/trace.py backend/tests/memory/test_eval_support_reader.py
git commit -m "feat: add eval memory reader"
```

### Task 5: Add a thin eval-support service that combines namespace, writer, and reader

**Files:**
- Create: `backend/src/magi/memory/eval_support/service.py`
- Create: `backend/src/magi/memory/eval_support/__init__.py`
- Create: `backend/tests/memory/test_eval_support_service.py`
- Modify: `backend/src/magi/memory/__init__.py`

- [ ] **Step 1: Write failing service tests**

Cover these cases:
- one call can replay a full session into an isolated namespace
- one call can query the same namespace and return a normalized result
- resetting a namespace only removes eval data for that namespace

- [ ] **Step 2: Run the focused service tests**

Run: `cd backend && pytest tests/memory/test_eval_support_service.py -v`
Expected: FAIL because the service module does not exist.

- [ ] **Step 3: Implement the eval-support service**

Add a thin service that exposes:
- `reset_namespace(...)`
- `write_records(...)`
- `query_memory(...)`

Implementation notes:
- Keep service methods small and compositional.
- Export the stable entry points from `__init__.py`.
- Only touch `backend/src/magi/memory/__init__.py` if the package export pattern requires it.

- [ ] **Step 4: Re-run the focused service tests**

Run: `cd backend && pytest tests/memory/test_eval_support_service.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/src/magi/memory/eval_support/__init__.py backend/src/magi/memory/eval_support/service.py backend/src/magi/memory/__init__.py backend/tests/memory/test_eval_support_service.py
git commit -m "feat: add memory eval support service"
```

---

## Chunk 3: Add The Benchmark Workspace And LongMemEval Adapter

### Task 6: Create the benchmark workspace scaffolding

**Files:**
- Create: `benchmark/README.md`
- Create: `benchmark/common/io.py`
- Create: `benchmark/common/paths.py`

- [ ] **Step 1: Write a small failing smoke test for benchmark path helpers**

Create a focused test inline in `benchmark/tests/test_longmemeval_runner.py` or a tiny new test file to assert:
- output directories are created under a predictable run path
- jsonl writes are append-safe and deterministic

- [ ] **Step 2: Run the focused benchmark helper tests**

Run: `pytest benchmark/tests/test_longmemeval_runner.py -k helper -v`
Expected: FAIL because the helper modules do not exist.

- [ ] **Step 3: Implement benchmark scaffolding**

Add:
- shared json/jsonl readers and writers
- output path helper for run directories
- top-level README documenting the separation from `backend/src/magi/`

- [ ] **Step 4: Re-run the focused helper tests**

Run: `pytest benchmark/tests/test_longmemeval_runner.py -k helper -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add benchmark/README.md benchmark/common/io.py benchmark/common/paths.py benchmark/tests/test_longmemeval_runner.py
git commit -m "chore: add benchmark workspace scaffolding"
```

### Task 7: Implement the LongMemEval dataset adapter

**Files:**
- Create: `benchmark/longmemeval/README.md`
- Create: `benchmark/longmemeval/adapter.py`
- Create: `benchmark/tests/test_longmemeval_adapter.py`

- [ ] **Step 1: Write failing adapter tests**

Cover these cases:
- a LongMemEval row is converted into ordered replay records
- replay records preserve session ids and timestamps
- the final question becomes a single `EvalMemoryQuery`
- abstention questions are marked in adapter output metadata

- [ ] **Step 2: Run the focused adapter tests**

Run: `pytest benchmark/tests/test_longmemeval_adapter.py -v`
Expected: FAIL because the adapter module does not exist.

- [ ] **Step 3: Implement `adapter.py`**

Add:
- dataset row loader
- row-to-replay-record conversion
- row-to-query conversion

Implementation notes:
- Keep the adapter pure; it should not import Magi runtime modules outside the eval-support contracts.
- Support `oracle` first.
- Preserve `question_type`, `question_date`, `answer_session_ids`, and abstention metadata for later reporting.

- [ ] **Step 4: Re-run the focused adapter tests**

Run: `pytest benchmark/tests/test_longmemeval_adapter.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add benchmark/longmemeval/README.md benchmark/longmemeval/adapter.py benchmark/tests/test_longmemeval_adapter.py
git commit -m "feat: add longmemeval adapter"
```

---

## Chunk 4: Run LongMemEval Against The Memory Harness

### Task 8: Implement the LongMemEval runner for replay + retrieval

**Files:**
- Create: `benchmark/longmemeval/runner.py`
- Create: `benchmark/longmemeval/configs/oracle.sample.json`
- Create: `benchmark/tests/test_longmemeval_runner.py`

- [ ] **Step 1: Write failing runner tests**

Cover these cases:
- one sample is replayed into its own namespace
- query results are written to `predictions_with_trace.jsonl`
- a plain `predictions.jsonl` with `question_id` and `hypothesis` can also be emitted
- rerunning the same question id under a new run id does not reuse stale memory data

- [ ] **Step 2: Run the focused runner tests**

Run: `pytest benchmark/tests/test_longmemeval_runner.py -v`
Expected: FAIL because the runner module does not exist.

- [ ] **Step 3: Implement `runner.py`**

Add a CLI or script entry that:
- loads dataset rows
- builds per-question namespaces
- replays history sessions
- executes the memory query
- writes:
  - `predictions_with_trace.jsonl`
  - `predictions.jsonl`

Implementation notes:
- In Phase 1, `hypothesis` may be a deterministic synthesis from top hits or a configurable lightweight reader stage, but document which option is being used.
- Keep answer synthesis outside `eval_support`.
- Default to a small sample mode for quick local verification.

- [ ] **Step 4: Re-run the focused runner tests**

Run: `pytest benchmark/tests/test_longmemeval_runner.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add benchmark/longmemeval/runner.py benchmark/longmemeval/configs/oracle.sample.json benchmark/tests/test_longmemeval_runner.py
git commit -m "feat: add longmemeval replay runner"
```

### Task 9: Add local reporting for retrieval quality and official QA handoff

**Files:**
- Create: `benchmark/longmemeval/report.py`
- Create: `benchmark/tests/test_longmemeval_report.py`

- [ ] **Step 1: Write failing report tests**

Cover these cases:
- report code computes session-level recall@k from `answer_session_ids`
- report code exports a LongMemEval-compatible `predictions.jsonl`
- abstention items are summarized separately

- [ ] **Step 2: Run the focused report tests**

Run: `pytest benchmark/tests/test_longmemeval_report.py -v`
Expected: FAIL because the report module does not exist.

- [ ] **Step 3: Implement `report.py`**

Add:
- local session-recall summary
- optional turn-recall summary when trace includes turn ids
- exporter for official LongMemEval QA eval input

Implementation notes:
- Keep local retrieval metrics deterministic.
- Treat official `evaluate_qa.py` as an external follow-up command, not a backend dependency.

- [ ] **Step 4: Re-run the focused report tests**

Run: `pytest benchmark/tests/test_longmemeval_report.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add benchmark/longmemeval/report.py benchmark/tests/test_longmemeval_report.py
git commit -m "feat: add longmemeval reporting"
```

---

## Chunk 5: Verification And Documentation

### Task 10: Verify the end-to-end `oracle` loop and document the commands

**Files:**
- Modify: `benchmark/longmemeval/README.md`
- Modify: `benchmark/README.md`

- [ ] **Step 1: Run backend eval-support tests**

Run: `cd backend && pytest tests/memory/test_eval_support_contracts.py tests/memory/test_eval_support_namespace.py tests/memory/test_eval_support_writer.py tests/memory/test_eval_support_reader.py tests/memory/test_eval_support_service.py -q`
Expected: PASS.

- [ ] **Step 2: Run benchmark tests**

Run: `pytest benchmark/tests/test_longmemeval_adapter.py benchmark/tests/test_longmemeval_runner.py benchmark/tests/test_longmemeval_report.py -q`
Expected: PASS.

- [ ] **Step 3: Run a small `oracle` sample manually**

Run something equivalent to:

```bash
python benchmark/longmemeval/runner.py --dataset data/longmemeval_oracle.json --limit 5 --run-id smoke-oracle
```

Expected:
- run directory created
- `predictions.jsonl` created
- `predictions_with_trace.jsonl` created
- local retrieval summary generated

- [ ] **Step 4: Document official LongMemEval QA handoff**

Add README examples for:
- dataset download
- runner invocation
- official `evaluate_qa.py` invocation
- expected output files

- [ ] **Step 5: Commit**

```bash
git add benchmark/README.md benchmark/longmemeval/README.md
git commit -m "docs: document longmemeval benchmark flow"
```

---

## Acceptance Checklist

- `backend/src/magi/memory/eval_support/` contains no LongMemEval-specific parsing logic.
- `benchmark/longmemeval/` contains all LongMemEval-specific dataset and runner logic.
- Replay writes use the memory ingest path, not direct database writes.
- Queries bypass chat/personality layers and return normalized retrieval traces.
- `oracle` can run end-to-end through the benchmark runner.
- The system produces both:
  - LongMemEval-compatible `predictions.jsonl`
  - Magi-specific `predictions_with_trace.jsonl`
- Local retrieval metrics can be computed from exported traces.

## Deferred Work

- Chat-integrated evaluation through `ChatTaskAgent`
- `s_cleaned` and `m_cleaned` large-scale performance tuning
- Full turn-level recall metrics if current retrieval traces do not expose stable turn ids
- Cross-benchmark abstractions beyond what `benchmark/common/` needs today
- Dashboarding or persistent benchmark result storage

Plan complete and saved to `docs/superpowers/plans/2026-03-19-longmemeval-memory-eval-integration.md`. Ready to execute?
