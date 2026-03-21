# Memory Answerability And Timeline Implementation Plan

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Improve formal memory retrieval so product queries return answer-bearing evidence and timeline-compressed context instead of only semantically related raw turns.

**Architecture:** Keep the existing `HybridRetrievalService -> L1Handler -> ResultFusion -> answer synthesis` shape, but add two product-grade capabilities: answerability-aware ranking and deterministic timeline condensation. Do not add benchmark-specific branches. Do not require a small model in the first implementation pass; add any model-assisted rerank or condensation only as an optional, flag-gated stage after deterministic improvements land.

**Tech Stack:** Python 3.12, FastAPI, aiosqlite, existing hybrid retrieval stack, pytest.

---

## File Map

**Create**
- `backend/src/magi/memory/hybrid_retrieval/answerability.py`
  Utility helpers for query phrase extraction, quoted-span detection, eventness scoring, and generic-guidance penalties.
- `backend/src/magi/memory/hybrid_retrieval/timeline_condense.py`
  Deterministic bundle-to-timeline condensation for L1 evidence bundles.
- `backend/tests/memory/test_timeline_condense.py`
  Focused unit coverage for timeline condensation behavior.

**Modify**
- `backend/src/magi/memory/hybrid_retrieval/handlers.py`
  Replace ad-hoc rerank heuristics with richer answerability features while preserving the current L1 triple-path architecture.
- `backend/src/magi/memory/hybrid_retrieval/result_fusion.py`
  Preserve comparative and session-local evidence instead of truncating L1 as a flat list only.
- `backend/src/magi/memory/hybrid_retrieval/models.py`
  Add typed payload fields for timeline outputs.
- `backend/src/magi/memory/hybrid_retrieval/service.py`
  Build timeline summaries after grouped evidence bundles are available.
- `backend/src/magi/api/routers/memory.py`
  Feed timeline summaries to answer synthesis before raw evidence.
- `backend/tests/memory/test_layer_handlers.py`
  Add ranking behavior tests.
- `backend/tests/memory/test_result_fusion.py`
  Add session-aware fusion coverage.
- `backend/tests/memory/test_hybrid_retrieval_service.py`
  Verify timeline generation is attached to retrieval payloads.
- `backend/tests/api/test_memory_api.py`
  Verify answer synthesis prompt uses timeline summaries.

---

## Chunk 1: Answerability-Aware L1 Ranking

### Task 1: Extract answerability features into a dedicated helper module

**Files:**
- Create: `backend/src/magi/memory/hybrid_retrieval/answerability.py`
- Modify: `backend/tests/memory/test_layer_handlers.py`

- [ ] **Step 1: Write the failing tests**

Add tests to `backend/tests/memory/test_layer_handlers.py` covering:

```python
async def test_prefers_exact_quoted_event_title_over_generic_topical_guidance():
    ...

async def test_prefers_event_statement_over_follow_up_chitchat_when_both_share_topic_terms():
    ...
```

- [ ] **Step 2: Run the tests to verify they fail**

Run:

```bash
cd /Users/asuka/code/magi/backend
/Users/asuka/lib/miniconda3/bin/python -m pytest tests/memory/test_layer_handlers.py -q -k "quoted_event_title or event_statement"
```

Expected: FAIL because the current ranking logic does not distinguish quoted titles, event statements, and guidance-heavy replies strongly enough.

- [ ] **Step 3: Write minimal feature helpers**

Create `backend/src/magi/memory/hybrid_retrieval/answerability.py` with focused helpers such as:

```python
def extract_query_tokens(text: str) -> list[str]: ...
def extract_query_phrases(tokens: Sequence[str]) -> list[str]: ...
def extract_quoted_spans(text: str) -> list[str]: ...
def score_eventness(content: str, *, author_type: str) -> float: ...
def score_temporal_anchor(content: str) -> float: ...
def score_generic_guidance_penalty(content: str, *, author_type: str) -> float: ...
```

Rules should stay general-purpose:
- reward quoted-span matches
- reward concrete event verbs and attendance/action statements
- reward date/time anchors
- penalize list-like assistant guidance and long generic tutorials

- [ ] **Step 4: Integrate helpers into `L1Handler`**

Update `backend/src/magi/memory/hybrid_retrieval/handlers.py` so `_score_event()` uses helper-derived features such as:
- `quoted_phrase_hits`
- `eventness_score`
- `temporal_anchor_score`
- `generic_guidance_penalty`
- `list_like_penalty`

Extend `retrieval_trace` accordingly.

- [ ] **Step 5: Run the tests to verify they pass**

Run:

```bash
cd /Users/asuka/code/magi/backend
/Users/asuka/lib/miniconda3/bin/python -m pytest tests/memory/test_layer_handlers.py -q
```

Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add backend/src/magi/memory/hybrid_retrieval/answerability.py backend/src/magi/memory/hybrid_retrieval/handlers.py backend/tests/memory/test_layer_handlers.py
git commit -m "feat: improve l1 answerability ranking"
```

### Task 2: Preserve comparative coverage across sessions

**Files:**
- Modify: `backend/src/magi/memory/hybrid_retrieval/result_fusion.py`
- Modify: `backend/tests/memory/test_result_fusion.py`

- [ ] **Step 1: Write the failing tests**

Add tests to `backend/tests/memory/test_result_fusion.py` covering:

```python
def test_l1_budget_keeps_multiple_sessions_for_comparison_questions():
    ...

def test_l1_budget_keeps_user_event_anchor_before_verbose_assistant_guidance():
    ...
```

- [ ] **Step 2: Run the tests to verify they fail**

Run:

```bash
cd /Users/asuka/code/magi/backend
/Users/asuka/lib/miniconda3/bin/python -m pytest tests/memory/test_result_fusion.py -q -k "multiple_sessions or user_event_anchor"
```

Expected: FAIL because flat truncation currently drops useful comparative coverage.

- [ ] **Step 3: Implement session-aware L1 truncation**

Update `backend/src/magi/memory/hybrid_retrieval/result_fusion.py` so L1 budget application:
- preserves at least one high-value event per top-ranked session when possible
- prefers user-authored event anchors over assistant guidance
- keeps comparative coverage for questions that mention multiple quoted candidates or `first/earlier/before/after`

Do not alter non-L1 layer budgeting.

- [ ] **Step 4: Run the tests to verify they pass**

Run:

```bash
cd /Users/asuka/code/magi/backend
/Users/asuka/lib/miniconda3/bin/python -m pytest tests/memory/test_result_fusion.py -q
```

Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add backend/src/magi/memory/hybrid_retrieval/result_fusion.py backend/tests/memory/test_result_fusion.py
git commit -m "feat: preserve comparative l1 evidence"
```

---

## Chunk 2: Deterministic Timeline Condensation

### Task 3: Add a dedicated timeline condensation module

**Files:**
- Create: `backend/src/magi/memory/hybrid_retrieval/timeline_condense.py`
- Create: `backend/tests/memory/test_timeline_condense.py`

- [ ] **Step 1: Write the failing tests**

Create `backend/tests/memory/test_timeline_condense.py` with coverage such as:

```python
def test_condenses_bundles_into_time_sorted_event_lines():
    ...

def test_skips_generic_guidance_when_fact_event_exists_in_same_bundle():
    ...

def test_preserves_two_competing_events_for_before_after_questions():
    ...
```

- [ ] **Step 2: Run the tests to verify they fail**

Run:

```bash
cd /Users/asuka/code/magi/backend
/Users/asuka/lib/miniconda3/bin/python -m pytest tests/memory/test_timeline_condense.py -q
```

Expected: FAIL because the module does not exist yet.

- [ ] **Step 3: Implement deterministic condensation**

Create `backend/src/magi/memory/hybrid_retrieval/timeline_condense.py` with APIs like:

```python
def build_timeline_summary(
    *,
    question: str,
    evidence_bundles: list[dict[str, Any]],
    max_items: int = 8,
) -> list[dict[str, Any]]:
    ...
```

Each output item should include:
- `timestamp`
- `session_id`
- `turn_id`
- `author_type`
- `summary`
- `supporting_event_ids`
- `reason_codes`

Condensation rules:
- prefer user-authored fact statements
- preserve event titles and quoted spans
- preserve time anchors
- collapse long assistant guidance into at most one short support line, or drop it when a user fact line already covers the same event
- keep both sides of comparison questions whenever evidence exists

- [ ] **Step 4: Run the tests to verify they pass**

Run:

```bash
cd /Users/asuka/code/magi/backend
/Users/asuka/lib/miniconda3/bin/python -m pytest tests/memory/test_timeline_condense.py -q
```

Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add backend/src/magi/memory/hybrid_retrieval/timeline_condense.py backend/tests/memory/test_timeline_condense.py
git commit -m "feat: add timeline evidence condensation"
```

### Task 4: Attach timeline summaries to retrieval payloads

**Files:**
- Modify: `backend/src/magi/memory/hybrid_retrieval/models.py`
- Modify: `backend/src/magi/memory/hybrid_retrieval/service.py`
- Modify: `backend/tests/memory/test_hybrid_retrieval_service.py`

- [ ] **Step 1: Write the failing tests**

Add service tests covering:

```python
async def test_query_builds_timeline_summary_from_l1_evidence_bundles():
    ...

async def test_query_keeps_timeline_summary_sorted_by_timestamp():
    ...
```

- [ ] **Step 2: Run the tests to verify they fail**

Run:

```bash
cd /Users/asuka/code/magi/backend
/Users/asuka/lib/miniconda3/bin/python -m pytest tests/memory/test_hybrid_retrieval_service.py -q -k "timeline_summary"
```

Expected: FAIL because `RetrievalPayload` does not yet expose timeline summaries.

- [ ] **Step 3: Implement payload support**

Modify:
- `backend/src/magi/memory/hybrid_retrieval/models.py`
- `backend/src/magi/memory/hybrid_retrieval/service.py`

Add a new payload field such as:

```python
l1_timeline_summary: List[Dict[str, Any]] = field(default_factory=list)
```

Build it after `l1_evidence_bundles` are ready and add trace fields such as:
- `l1_timeline_summary_count`

- [ ] **Step 4: Run the tests to verify they pass**

Run:

```bash
cd /Users/asuka/code/magi/backend
/Users/asuka/lib/miniconda3/bin/python -m pytest tests/memory/test_hybrid_retrieval_service.py -q
```

Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add backend/src/magi/memory/hybrid_retrieval/models.py backend/src/magi/memory/hybrid_retrieval/service.py backend/tests/memory/test_hybrid_retrieval_service.py
git commit -m "feat: attach timeline summaries to retrieval payloads"
```

---

## Chunk 3: Answer Synthesis Uses Timeline First

### Task 5: Change eval answer synthesis to prioritize timeline summaries

**Files:**
- Modify: `backend/src/magi/api/routers/memory.py`
- Modify: `backend/tests/api/test_memory_api.py`

- [ ] **Step 1: Write the failing tests**

Add API tests covering:

```python
async def test_eval_answer_prompt_includes_timeline_summary_before_raw_evidence():
    ...

async def test_eval_answer_prompt_uses_timeline_summary_when_bundles_are_noisy():
    ...
```

- [ ] **Step 2: Run the tests to verify they fail**

Run:

```bash
cd /Users/asuka/code/magi/backend
/Users/asuka/lib/miniconda3/bin/python -m pytest tests/api/test_memory_api.py -q -k "timeline_summary_before_raw_evidence or noisy"
```

Expected: FAIL because `_synthesize_eval_answer()` currently only formats raw bundles and flat hits.

- [ ] **Step 3: Implement minimal answer prompt upgrade**

Update `backend/src/magi/api/routers/memory.py` so `_synthesize_eval_answer()` accepts `timeline_summary` and formats:

```text
Timeline Summary:
- 2023-03-15 | session=s1 | user | First service completed
- 2023-03-22 | session=s2 | user | GPS system issue reported

Session Evidence Bundles:
...

Retrieved Evidence:
...
```

Keep the existing conservative `unknown` policy.

- [ ] **Step 4: Run the tests to verify they pass**

Run:

```bash
cd /Users/asuka/code/magi/backend
/Users/asuka/lib/miniconda3/bin/python -m pytest tests/api/test_memory_api.py -q -k "eval_query_api_can_answer_with_llm or timeline_summary_before_raw_evidence or uses_evidence_bundles_for_answer_synthesis"
```

Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add backend/src/magi/api/routers/memory.py backend/tests/api/test_memory_api.py
git commit -m "feat: use timeline summaries in eval answers"
```

---

## Chunk 4: Optional Model-Assisted Post-Processing

### Task 6: Add a flag-gated small-model rerank or condensation stage only if deterministic results are still insufficient

**Files:**
- Modify: `backend/src/magi/memory/hybrid_retrieval/models.py`
- Modify: `backend/src/magi/memory/hybrid_retrieval/service.py`
- Modify: `backend/src/magi/api/routers/memory.py`
- Modify: `backend/tests/memory/test_hybrid_retrieval_service.py`

- [ ] **Step 1: Confirm deterministic pipeline is still insufficient**

Run the LongMemEval spot checks that previously failed and record which cases remain wrong after Chunks 1-3.

- [ ] **Step 2: Add a failing test for flag-gated post-processing**

Add coverage that ensures:
- disabled flag means no extra model call
- enabled flag only processes top-N evidence rows

- [ ] **Step 3: Implement the smallest possible model-assisted stage**

Only if needed, add a flag such as:

```python
answerability_rerank_llm_enabled: bool = False
answerability_rerank_top_n: int = 8
```

The model-assisted stage must:
- operate on already-retrieved top-N candidates only
- never replace recall
- return structured outputs such as `keep`, `drop`, `summary`, `confidence`

- [ ] **Step 4: Run tests and representative benchmark spot checks**

Run:

```bash
cd /Users/asuka/code/magi/backend
/Users/asuka/lib/miniconda3/bin/python -m pytest tests/memory/test_hybrid_retrieval_service.py -q
```

And rerun targeted queries with `query_one.py`.

- [ ] **Step 5: Commit**

```bash
git add backend/src/magi/memory/hybrid_retrieval/models.py backend/src/magi/memory/hybrid_retrieval/service.py backend/src/magi/api/routers/memory.py backend/tests/memory/test_hybrid_retrieval_service.py
git commit -m "feat: add optional llm answerability post-processing"
```

---

## Recommended Execution Order

1. Chunk 1 first
2. Chunk 2 second
3. Chunk 3 third
4. Chunk 4 only if needed

## Recommended Product Decision

- Do **not** introduce `bge-m3` or another retrieval model as the first fix.
- Do **not** add benchmark-specific question-type branches.
- Do **not** add a mandatory small-model rerank stage yet.
- First ship deterministic answerability ranking plus timeline condensation.
- Re-evaluate only after targeted query cases still fail.

Plan complete and saved to `docs/superpowers/plans/2026-03-21-memory-answerability-and-timeline-plan.md`. Ready to execute?
