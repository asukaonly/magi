# L2 Snapshot Evolution Implementation Plan

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make `mark_evolution` visible in L2 snapshots so current-state snapshot fields exclude superseded facts while recent transitions remain available as compact history metadata.

**Architecture:** Keep `knowledge_graph` and `tom_trait_assertions` as the canonical evidence layer, then extend `refresh_entity_snapshot()` to derive both current-state fields and compact evolution-history fields from the existing record status model. Reuse the existing snapshot refresh queue and worker so this change stays inside the current L2 reconciliation/materialization pipeline.

**Tech Stack:** Python 3.12, aiosqlite, pytest, existing L2 pipeline/store models

---

## File Map

- Modify: `backend/src/magi/memory/l2/store.py`
  - extend snapshot materialization and snapshot JSON shape
- Modify: `backend/src/magi/memory/l2/pipeline.py`
  - ensure snapshot refresh is queued for the right evolved entities if current tests reveal gaps
- Modify: `backend/tests/memory/l2/test_pipeline.py`
  - add end-to-end regression coverage for arbitration -> snapshot refresh
- Modify: `backend/tests/memory/l2/test_store.py`
  - add focused snapshot materialization tests for current-state and history behavior
- Modify: `docs/superpowers/specs/2026-03-23-l2-snapshot-evolution-design.md`
  - only if implementation reveals a necessary design correction

## Chunk 1: Snapshot Shape And Store Semantics

### Task 1: Add failing snapshot store tests

**Files:**
- Modify: `backend/tests/memory/l2/test_store.py`
- Modify: `backend/src/magi/memory/l2/store.py`

- [ ] **Step 1: Write the failing test for superseded preference facts**

```python
async def test_refresh_entity_snapshot_excludes_deprecated_preference_and_keeps_history():
    ...
```

- [ ] **Step 2: Run the focused test to verify it fails**

Run: `PYTHONPATH=backend/src pytest backend/tests/memory/l2/test_store.py -q -k deprecated_preference`
Expected: FAIL because the snapshot has no evolution history and/or still treats superseded facts as current.

- [ ] **Step 3: Write the failing test for core trait evolution history**

```python
async def test_refresh_entity_snapshot_tracks_core_trait_evolution_history():
    ...
```

- [ ] **Step 4: Run the focused test to verify it fails**

Run: `PYTHONPATH=backend/src pytest backend/tests/memory/l2/test_store.py -q -k core_trait_evolution`
Expected: FAIL because the snapshot payload lacks `core_traits_history`.

- [ ] **Step 5: Implement minimal snapshot-history support**

Add minimal helpers in `backend/src/magi/memory/l2/store.py` to:

- collect active winners for snapshot-backed fields
- collect recent superseded records relevant to `core_traits`, `preferences`, and `relationship_topology`
- write compact history entries and metadata fields into the snapshot payload

- [ ] **Step 6: Run the focused store tests to verify they pass**

Run: `PYTHONPATH=backend/src pytest backend/tests/memory/l2/test_store.py -q -k "deprecated_preference or core_trait_evolution"`
Expected: PASS

- [ ] **Step 7: Commit**

```bash
git add backend/src/magi/memory/l2/store.py backend/tests/memory/l2/test_store.py
git commit -m "feat: track l2 snapshot evolution"
```

## Chunk 2: Pipeline Regression Coverage

### Task 2: Verify arbitration results propagate into refreshed snapshots

**Files:**
- Modify: `backend/tests/memory/l2/test_pipeline.py`
- Modify: `backend/src/magi/memory/l2/pipeline.py`

- [ ] **Step 1: Write the failing pipeline test**

Add an end-to-end test that:

- writes an old active fact
- triggers `mark_evolution`
- waits for snapshot refresh
- asserts the snapshot current field reflects the new winner
- asserts the snapshot history records the superseded winner

- [ ] **Step 2: Run the focused pipeline test to verify it fails**

Run: `PYTHONPATH=backend/src pytest backend/tests/memory/l2/test_pipeline.py -q -k snapshot_evolution`
Expected: FAIL because the refreshed snapshot does not yet carry the new history payload or current-state semantics.

- [ ] **Step 3: Adjust pipeline behavior only if needed**

Only if the test shows a queueing gap:

- enqueue snapshot refresh for entities touched by evolved records
- keep the change narrowly scoped to snapshot refresh propagation

- [ ] **Step 4: Run the focused pipeline test to verify it passes**

Run: `PYTHONPATH=backend/src pytest backend/tests/memory/l2/test_pipeline.py -q -k snapshot_evolution`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add backend/src/magi/memory/l2/pipeline.py backend/tests/memory/l2/test_pipeline.py
git commit -m "feat: surface evolution in l2 snapshots"
```

## Chunk 3: Final Verification

### Task 3: Re-run the affected suites

**Files:**
- Modify: none unless a regression is uncovered

- [ ] **Step 1: Run the store and pipeline suites**

Run: `PYTHONPATH=backend/src pytest backend/tests/memory/l2/test_store.py backend/tests/memory/l2/test_pipeline.py -q`
Expected: PASS

- [ ] **Step 2: Run the config and lifecycle suites as a regression check**

Run: `PYTHONPATH=backend/src pytest backend/tests/api/test_config_api.py backend/tests/memory/l2/test_llm_service.py backend/tests/memory/test_lifecycle.py -q`
Expected: PASS

- [ ] **Step 3: Check git status**

Run: `git status --short`
Expected: clean working tree

- [ ] **Step 4: If any verification fix was needed, commit it immediately**

```bash
git add <files>
git commit -m "fix: stabilize l2 snapshot evolution"
```
