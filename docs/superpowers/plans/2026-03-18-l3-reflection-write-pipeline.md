# L3 Reflection Write Pipeline Implementation Plan

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Upgrade L3 from a periodic temporal digest into a traceable reflection write pipeline that supports time-, topic-, insight-, and task-driven summaries with validation, evidence linking, and safe compression handoff.

**Architecture:** Introduce explicit L3 reflection contracts first, then add a validator/arbiter layer between candidate generation and persistence. Extend the summary store with link tables and upsert helpers, add a task-outcome driven write path alongside the existing temporal path, and only then wire background triggers and retention cleanup so each stage stays testable and reversible.

**Tech Stack:** Python 3.12, asyncio, aiosqlite, dataclasses, existing Magi `UnifiedMemoryStore`, `L1EventStore`, `L2CognitionStore`, `L3SummaryStore`, pytest.

---

## Design Summary

### Trigger families

1. `temporal`
   - Fixed windows: hour, day, week, month, quarter, year.
   - Uses L1 evidence plus lower-granularity L3 summaries as helpers, but never summary-of-summary only.

2. `thematic`
   - Triggered when a topic, entity, project, or relationship cluster crosses threshold.
   - Uses canonical topic/entity keys so repeated material upserts into one rolling summary instead of exploding the table.

3. `insight`
   - Triggered by L2 state changes, contradiction resolution, trend shifts, or milestone review.
   - Requires stronger evidence and novelty checks than temporal summaries.

4. `task_reflection`
   - Triggered when a user-goal task completes, partially completes, or fails.
   - Stores user-facing conclusions, not orchestration traces or tool-loop details.

### Non-goals

- Do not store worker progress spam or loop telemetry in L3.
- Do not use L3 as a replacement for L2 graph/assertion facts.
- Do not delete permanent L1 records after summary generation.
- Do not build a generic event-clustering framework before the first concrete trigger paths land.

### Invariants

- Every L3 record must remain traceable to `source_event_ids`.
- `task_reflection` records should default to `summary_type = "insight"` and `summary_category = "task_reflection"`.
- A source L1 event may map to multiple summaries; linkage must use dedicated link tables, not single-field backpatching.
- Retention cleanup must run only after summary persistence and link persistence have both succeeded.

## File Map

### New backend files

- Create: `backend/src/magi/memory/l3/models.py`
  - L3 summary enums, task outcome packet, L3 candidate, validation result contracts.
- Create: `backend/src/magi/memory/l3/validator.py`
  - Reject / merge / route / accept logic for L3 candidates.
- Create: `backend/src/magi/memory/l3/task_reflection_service.py`
  - Convert a completed task outcome packet plus evidence into an L3 candidate request.
- Create: `backend/tests/memory/l3/test_reflection_contracts.py`
  - Contract coverage for task outcome packets and candidate defaults.
- Create: `backend/tests/memory/l3/test_validator.py`
  - Validation and routing behavior.
- Create: `backend/tests/memory/l3/test_task_reflection_service.py`
  - Task-driven candidate generation and evidence shaping.

### Existing backend files to extend

- Modify: `backend/src/magi/memory/l3/summary_store.py`
  - Add summary/event and summary/task link tables, richer upsert helpers, and task-aware persistence metadata.
- Modify: `backend/src/magi/memory/__init__.py`
  - Add explicit L3 candidate persistence entrypoints and task reflection orchestration.
- Modify: `backend/src/magi/memory/integration.py`
  - Keep periodic summary loop, but route future summary generation through the validator/persistence layer.
- Modify: `backend/src/magi/memory/hybrid_retrieval/models.py`
  - Add optional L3 filters for summary categories and subtypes if needed by retrieval.
- Modify: `backend/src/magi/memory/hybrid_retrieval/handlers.py`
  - Respect new L3 filtering fields and linked metadata.
- Modify: `backend/src/magi/memory/l2/pipeline.py`
  - Emit explicit insight-trigger hints when state transitions or contradiction resolutions happen.
- Modify: `backend/tests/memory/l3/test_summary_store.py`
  - Cover link persistence and richer summary writes.
- Modify: `backend/tests/memory/test_hybrid_retrieval.py`
  - Verify task reflections are queryable from L3.

### Adjacent runtime files likely to touch

- Modify: task or orchestration completion path under `backend/src/magi/agent/`
  - Emit a `TaskOutcomePacket` after user-goal tasks finish.
- Modify: memory API under `backend/src/magi/api/routers/memory.py`
  - Expose linked task ids or summary metadata only after the store schema is stable.

## Chunk 1: Contracts And Arbitration

### Task 1: Add explicit L3 reflection contracts

**Files:**
- Create: `backend/src/magi/memory/l3/models.py`
- Create: `backend/tests/memory/l3/test_reflection_contracts.py`

- [ ] **Step 1: Write failing tests for task outcome and L3 candidate contracts**

```python
from dataclasses import asdict

from magi.memory.l3.models import L3Candidate, TaskOutcomePacket


def test_task_outcome_packet_keeps_user_goal_and_evidence():
    packet = TaskOutcomePacket(
        task_id="task-1",
        user_id="u1",
        task_title="Plan job switch",
        task_status="completed",
        user_goal="Decide whether to start applying this month",
        evidence_event_ids=["evt-1", "evt-2"],
    )

    data = asdict(packet)

    assert data["user_goal"] == "Decide whether to start applying this month"
    assert data["evidence_event_ids"] == ["evt-1", "evt-2"]


def test_l3_candidate_defaults_task_reflection_to_insight():
    candidate = L3Candidate(
        content="The user clarified that growth matters more than salary.",
        source_event_ids=["evt-1", "evt-2"],
        summary_category="task_reflection",
    )

    assert candidate.summary_type == "insight"
    assert candidate.subtypes == []
```

- [ ] **Step 2: Run the failing tests**

Run: `PYTHONPATH=/Users/asuka/code/magi/backend/src pytest backend/tests/memory/l3/test_reflection_contracts.py -v`
Expected: FAIL because the module does not exist.

- [ ] **Step 3: Implement the dataclasses and enums in `models.py`**

Implementation notes:
- Add stable literals or enums for `summary_type`, `summary_category`, and task-reflection subtypes.
- Keep the contracts small and serialization-friendly.
- Default `task_reflection` candidates to `summary_type="insight"`.

- [ ] **Step 4: Re-run the focused tests**

Run: `PYTHONPATH=/Users/asuka/code/magi/backend/src pytest backend/tests/memory/l3/test_reflection_contracts.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/src/magi/memory/l3/models.py backend/tests/memory/l3/test_reflection_contracts.py
git commit -m "feat: add l3 reflection contracts"
```

### Task 2: Add an L3 validator / arbiter

**Files:**
- Create: `backend/src/magi/memory/l3/validator.py`
- Create: `backend/tests/memory/l3/test_validator.py`
- Modify: `backend/src/magi/memory/l3/models.py`

- [ ] **Step 1: Write failing tests for reject, merge, and route decisions**

```python
from magi.memory.l3.models import L3Candidate, TaskOutcomePacket
from magi.memory.l3.validator import validate_candidate


def test_validator_routes_execution_trace_like_task_outcomes_to_l4():
    packet = TaskOutcomePacket(
        task_id="task-1",
        user_id="u1",
        task_title="Run repo explore",
        task_status="completed",
        result_summary="Called rg, retried twice, then worker finished.",
        evidence_event_ids=["evt-1", "evt-2"],
    )
    candidate = L3Candidate(
        summary_type="insight",
        summary_category="task_reflection",
        content="The task called rg, retried twice, and completed successfully.",
        source_event_ids=["evt-1", "evt-2"],
    )

    decision = validate_candidate(candidate, task_outcome=packet, evidence_events=[])

    assert decision.action == "route_to_l4"
```

- [ ] **Step 2: Run the failing tests**

Run: `PYTHONPATH=/Users/asuka/code/magi/backend/src pytest backend/tests/memory/l3/test_validator.py -v`
Expected: FAIL because the validator does not exist.

- [ ] **Step 3: Implement minimal validation rules**

Rules to land now:
- missing evidence -> reject
- disposable-only evidence -> reject
- execution-trace-like task reflection -> route to L4
- low-novelty duplicate -> merge_existing
- valid task reflection with user-facing conclusions -> accept

- [ ] **Step 4: Run the focused tests**

Run: `PYTHONPATH=/Users/asuka/code/magi/backend/src pytest backend/tests/memory/l3/test_validator.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/src/magi/memory/l3/models.py backend/src/magi/memory/l3/validator.py backend/tests/memory/l3/test_validator.py
git commit -m "feat: add l3 reflection validator"
```

## Chunk 2: Persistence And Linkage

### Task 3: Extend the summary store with link tables and upsert helpers

**Files:**
- Modify: `backend/src/magi/memory/l3/summary_store.py`
- Modify: `backend/tests/memory/l3/test_summary_store.py`

- [ ] **Step 1: Write failing tests for summary-event and summary-task links**

```python
async def test_store_summary_persists_event_and_task_links(l3_store):
    summary = await l3_store.upsert_candidate(
        candidate=...,
        source_task_ids=["task-1"],
    )

    links = await l3_store.list_summary_event_links(summary["summary_id"])
    task_links = await l3_store.list_summary_task_links(summary["summary_id"])

    assert {link["event_id"] for link in links} == {"evt-1", "evt-2"}
    assert task_links[0]["task_id"] == "task-1"
```

- [ ] **Step 2: Run the failing tests**

Run: `PYTHONPATH=/Users/asuka/code/magi/backend/src pytest backend/tests/memory/l3/test_summary_store.py -k links -v`
Expected: FAIL because the link schema and APIs do not exist.

- [ ] **Step 3: Add dedicated link tables and upsert APIs**

Implementation notes:
- Add `summary_event_links`.
- Add `summary_task_links`.
- Keep `summaries.source_event_ids` as the denormalized fast path, but do not rely on it as the only linkage.
- Introduce one upsert API that persists summary row first, then links, then queues embeddings.

- [ ] **Step 4: Run the focused tests**

Run: `PYTHONPATH=/Users/asuka/code/magi/backend/src pytest backend/tests/memory/l3/test_summary_store.py -k links -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/src/magi/memory/l3/summary_store.py backend/tests/memory/l3/test_summary_store.py
git commit -m "feat: add l3 summary link tables"
```

### Task 4: Add `UnifiedMemoryStore` entrypoints for validated L3 candidates

**Files:**
- Modify: `backend/src/magi/memory/__init__.py`
- Modify: `backend/tests/memory/test_memory_layers.py`

- [ ] **Step 1: Write failing tests for a validated L3 write path**

```python
async def test_unified_memory_store_persists_validated_task_reflection(store):
    summary = await store.persist_l3_candidate(candidate=..., task_outcome=...)

    assert summary is not None
    assert summary["summary_category"] == "task_reflection"
```

- [ ] **Step 2: Run the failing tests**

Run: `PYTHONPATH=/Users/asuka/code/magi/backend/src pytest backend/tests/memory/test_memory_layers.py -k validated_task_reflection -v`
Expected: FAIL because the entrypoint does not exist.

- [ ] **Step 3: Implement the minimal orchestration**

Implementation notes:
- Fetch L1 evidence from `source_event_ids`.
- Validate through the arbiter.
- Accept -> persist to L3.
- Merge -> upsert existing summary and refresh links.
- Route to L4 / Reject -> no L3 write.

- [ ] **Step 4: Run the focused tests**

Run: `PYTHONPATH=/Users/asuka/code/magi/backend/src pytest backend/tests/memory/test_memory_layers.py -k validated_task_reflection -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/src/magi/memory/__init__.py backend/tests/memory/test_memory_layers.py
git commit -m "feat: add validated l3 candidate writes"
```

## Chunk 3: Task And Trigger Integration

### Task 5: Add a task reflection service and task-outcome write path

**Files:**
- Create: `backend/src/magi/memory/l3/task_reflection_service.py`
- Create: `backend/tests/memory/l3/test_task_reflection_service.py`
- Modify: task completion path under `backend/src/magi/agent/`

- [ ] **Step 1: Write failing tests for task reflection extraction**

```python
async def test_task_reflection_service_builds_candidate_from_completed_user_goal_task():
    candidate = await service.build_candidate(packet)

    assert candidate.summary_category == "task_reflection"
    assert "growth" in candidate.content.lower()
```

- [ ] **Step 2: Run the failing tests**

Run: `PYTHONPATH=/Users/asuka/code/magi/backend/src pytest backend/tests/memory/l3/test_task_reflection_service.py -v`
Expected: FAIL because the service does not exist.

- [ ] **Step 3: Implement a rule-first task reflection builder**

Implementation notes:
- Start rule-first, not LLM-only.
- Only include user-goal tasks, not low-level orchestration tasks.
- Produce a compact evidence packet for future LLM expansion.

- [ ] **Step 4: Run the focused tests**

Run: `PYTHONPATH=/Users/asuka/code/magi/backend/src pytest backend/tests/memory/l3/test_task_reflection_service.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/src/magi/memory/l3/task_reflection_service.py backend/tests/memory/l3/test_task_reflection_service.py
git commit -m "feat: add task reflection candidate builder"
```

### Task 6: Route periodic and insight-triggered L3 generation through the new pipeline

**Files:**
- Modify: `backend/src/magi/memory/integration.py`
- Modify: `backend/src/magi/memory/l2/pipeline.py`
- Modify: `backend/tests/memory/test_memory_integration_worker_events.py`

- [ ] **Step 1: Write failing tests for periodic summaries using the validator path**

```python
async def test_periodic_summary_generation_uses_validated_l3_pipeline():
    await integration.generate_pending_summaries()

    assert integration.get_statistics()["l3_summaries_generated"] == 1
```

- [ ] **Step 2: Run the failing tests**

Run: `PYTHONPATH=/Users/asuka/code/magi/backend/src pytest backend/tests/memory/test_memory_integration_worker_events.py -k validated_l3_pipeline -v`
Expected: FAIL because the old direct path is still in place.

- [ ] **Step 3: Re-route summary generation**

Implementation notes:
- Temporal generation should emit a candidate then persist through the arbiter/store path.
- L2 contradiction/state-change hooks should enqueue `insight` candidates, not write summary rows directly.

- [ ] **Step 4: Run the focused tests**

Run: `PYTHONPATH=/Users/asuka/code/magi/backend/src pytest backend/tests/memory/test_memory_integration_worker_events.py -k validated_l3_pipeline -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/src/magi/memory/integration.py backend/src/magi/memory/l2/pipeline.py backend/tests/memory/test_memory_integration_worker_events.py
git commit -m "refactor: route l3 generation through validator"
```

## Chunk 4: Retrieval And Retention

### Task 7: Extend retrieval contracts and handlers for richer L3 filtering

**Files:**
- Modify: `backend/src/magi/memory/hybrid_retrieval/models.py`
- Modify: `backend/src/magi/memory/hybrid_retrieval/handlers.py`
- Modify: `backend/tests/memory/test_retrieval_contracts.py`
- Modify: `backend/tests/memory/test_hybrid_retrieval.py`

- [ ] **Step 1: Write failing tests for category and subtype filters**

```python
def test_l3_conditions_accept_summary_categories_and_subtypes():
    conditions = L3Conditions(
        content_query="job switch",
        summary_types=["insight"],
        summary_categories=["task_reflection"],
        subtypes=["constraint_summary"],
    )

    assert conditions.summary_categories == ["task_reflection"]
    assert conditions.subtypes == ["constraint_summary"]
```

- [ ] **Step 2: Run the failing tests**

Run: `PYTHONPATH=/Users/asuka/code/magi/backend/src pytest backend/tests/memory/test_retrieval_contracts.py backend/tests/memory/test_hybrid_retrieval.py -k l3 -v`
Expected: FAIL because the fields are missing.

- [ ] **Step 3: Implement the retrieval filter support**

Implementation notes:
- Preserve backward compatibility with existing `summary_types`.
- Make filters optional.
- Ensure the SQL path and vector path both respect them.

- [ ] **Step 4: Run the focused tests**

Run: `PYTHONPATH=/Users/asuka/code/magi/backend/src pytest backend/tests/memory/test_retrieval_contracts.py backend/tests/memory/test_hybrid_retrieval.py -k l3 -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/src/magi/memory/hybrid_retrieval/models.py backend/src/magi/memory/hybrid_retrieval/handlers.py backend/tests/memory/test_retrieval_contracts.py backend/tests/memory/test_hybrid_retrieval.py
git commit -m "feat: add richer l3 retrieval filters"
```

### Task 8: Add compression-safe garbage collection hooks

**Files:**
- Modify: `backend/src/magi/memory/l3/summary_store.py`
- Modify: `backend/src/magi/memory/__init__.py`
- Add or modify tests under `backend/tests/memory/`

- [ ] **Step 1: Write failing tests for compressible-only cleanup eligibility**

```python
async def test_only_compressible_events_become_cleanup_candidates_after_summary_linking(store):
    ...
    assert cleanup_candidates == ["evt-browser-1"]
```

- [ ] **Step 2: Run the failing tests**

Run: `PYTHONPATH=/Users/asuka/code/magi/backend/src pytest backend/tests/memory -k cleanup_candidates -v`
Expected: FAIL because cleanup hooks do not exist.

- [ ] **Step 3: Implement cleanup eligibility, not full destructive deletion**

Implementation notes:
- Phase one should only mark cleanup candidates.
- Require summary persistence + link persistence + retention window checks.
- Do not delete permanent or unresolved evidence rows.

- [ ] **Step 4: Run the focused tests**

Run: `PYTHONPATH=/Users/asuka/code/magi/backend/src pytest backend/tests/memory -k cleanup_candidates -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/src/magi/memory/l3/summary_store.py backend/src/magi/memory/__init__.py backend/tests/memory
git commit -m "feat: add l3 cleanup eligibility hooks"
```

## Verification Pass

- [ ] Run the focused L3 suite:
  `PYTHONPATH=/Users/asuka/code/magi/backend/src pytest backend/tests/memory/l3/test_reflection_contracts.py backend/tests/memory/l3/test_validator.py backend/tests/memory/l3/test_summary_store.py backend/tests/memory/l3/test_task_reflection_service.py -v`
- [ ] Run the broader memory regression slice:
  `PYTHONPATH=/Users/asuka/code/magi/backend/src pytest backend/tests/memory/test_memory_layers.py backend/tests/memory/test_hybrid_retrieval.py backend/tests/memory/test_retrieval_contracts.py -v`
- [ ] Update memory docs if execution materially changes the agreed contracts.

## Notes For Execution

- Land contracts and validator before touching periodic generation.
- Keep task reflection rule-first for the first pass; LLM-based extraction can be layered on after the contracts settle.
- Prefer additive schema changes over rewriting existing `summaries` rows in place.
- Follow AGENTS.md: each independently verified task must be committed immediately.

Plan complete and saved to `docs/superpowers/plans/2026-03-18-l3-reflection-write-pipeline.md`. Ready to execute?
