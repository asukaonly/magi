# L3 Temporal Summary LLMization Implementation Plan

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the current rule-only temporal summary text assembly with an evidence-pack-based LLM summarization path that preserves traceability and safely falls back to the existing rule summary when the model path fails or produces low-quality output.

**Architecture:** Keep the existing temporal summary query and filtering rules, but split generation into three explicit stages: build a compact temporal evidence pack, ask the LLM for a structured temporal candidate, then validate and persist it through the existing L3 upsert path. Rule summaries remain the hard fallback so L3 writes never depend on LLM success.

**Tech Stack:** Python 3.12, asyncio, dataclasses, existing Magi `L3SummaryStore`, `UnifiedMemoryStore`, `MemoryEmbeddingService`, scenario LLM pool/adapters, pytest.

---

## Scope

This plan is intentionally narrower than the full L3 reflection pipeline:

- In scope:
  - temporal summaries only
  - hour/day/week/month/... time windows
  - evidence pack creation
  - LLM JSON extraction
  - validator + fallback
  - persistence through the current `summary_store` path

- Out of scope:
  - thematic summaries
  - insight summaries from L2 state changes
  - task reflection LLMization
  - retrieval ranking changes beyond reading new fields

## Design Summary

### Current problem

`generate_temporal_summary()` currently filters valid L1 events and concatenates raw content. This is stable, cheap, and traceable, but the summary text is weak:

- repeated content is not compressed well
- change-over-time is not surfaced clearly
- tone and pattern extraction are shallow
- outputs read like stitched evidence, not real reflection

### Target temporal flow

1. Collect eligible L1 events for the time window.
2. Build a compact `TemporalEvidencePack`.
3. Generate a rule fallback summary immediately.
4. If the pack meets threshold, call the LLM for a structured temporal output.
5. Validate the LLM output.
6. If accepted, persist the LLM candidate.
7. If the model fails, times out, or is rejected, persist the rule fallback summary instead.

### Hard rules

- Never let LLM failure block L3 writes.
- Never let the LLM invent evidence ids or entities.
- Temporal summaries may describe trends and explicit changes, but should not produce deep psychological diagnoses.
- The persisted summary must still link back to `source_event_ids` through `summary_event_links`.

## File Map

### New backend files

- Create: `backend/src/magi/memory/l3/temporal_llm_service.py`
  - Build prompt payloads, call the LLM, parse structured JSON, and return an L3 candidate or a fallback signal.
- Create: `backend/tests/memory/l3/test_temporal_llm_service.py`
  - Verify evidence-pack building, JSON parsing, timeout fallback, and validator handoff.

### Existing backend files to extend

- Modify: `backend/src/magi/memory/l3/models.py`
  - Add temporal evidence-pack and LLM-output contracts.
- Modify: `backend/src/magi/memory/l3/summary_store.py`
  - Route `generate_temporal_summary()` through the new temporal LLM service while preserving the rule fallback.
- Modify: `backend/src/magi/memory/__init__.py`
  - Ensure `generate_summary()` still exposes the same API while using the improved temporal generation path.
- Modify: `backend/src/magi/config/models.py`
  - Add config flags for enabling temporal LLM summaries, timeout, and minimum evidence thresholds if not already present elsewhere.
- Modify: `backend/src/magi/memory/lifecycle.py`
  - Wire new config into the L3 store/service if configuration is required at construction time.
- Modify: `backend/tests/memory/l3/test_summary_store.py`
  - Extend temporal summary coverage to include link persistence plus LLM fallback behavior.
- Modify: `backend/tests/memory/test_memory_layers.py`
  - Confirm the higher-level `generate_summary()` path remains stable.

## Chunk 1: Contracts And Evidence Packing

### Task 1: Add temporal evidence-pack contracts

**Files:**
- Modify: `backend/src/magi/memory/l3/models.py`
- Create: `backend/tests/memory/l3/test_temporal_llm_service.py`

- [ ] **Step 1: Write failing tests for temporal evidence-pack contracts**

```python
from magi.memory.l3.models import TemporalEvidenceItem, TemporalEvidencePack


def test_temporal_evidence_pack_keeps_window_and_event_ids():
    pack = TemporalEvidencePack(
        summary_category="day",
        period_start=100.0,
        period_end=200.0,
        source_event_count=2,
        source_event_ids=["evt-1", "evt-2"],
        events=[
            TemporalEvidenceItem(event_id="evt-1", event_type="UserMessage", content="growth matters"),
            TemporalEvidenceItem(event_id="evt-2", event_type="AIResponse", content="finish portfolio"),
        ],
    )

    assert pack.summary_category == "day"
    assert pack.source_event_ids == ["evt-1", "evt-2"]
```

- [ ] **Step 2: Run the failing tests**

Run: `PYTHONPATH=/Users/asuka/code/magi/backend/src pytest backend/tests/memory/l3/test_temporal_llm_service.py -k evidence_pack -v`
Expected: FAIL because the contracts do not exist.

- [ ] **Step 3: Add minimal temporal evidence-pack dataclasses**

Implementation notes:
- Keep them serialization-friendly.
- Include only fields the prompt needs.
- Do not prematurely add thematic/insight-only fields here.

- [ ] **Step 4: Re-run the focused tests**

Run: `PYTHONPATH=/Users/asuka/code/magi/backend/src pytest backend/tests/memory/l3/test_temporal_llm_service.py -k evidence_pack -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/src/magi/memory/l3/models.py backend/tests/memory/l3/test_temporal_llm_service.py
git commit -m "feat: add temporal evidence pack contracts"
```

### Task 2: Build the rule-side temporal evidence pack

**Files:**
- Create: `backend/src/magi/memory/l3/temporal_llm_service.py`
- Modify: `backend/tests/memory/l3/test_temporal_llm_service.py`

- [ ] **Step 1: Write failing tests for evidence-pack building**

```python
async def test_build_temporal_evidence_pack_filters_runtime_and_preserves_importance():
    pack = service.build_evidence_pack(events=[...], summary_category="day", period_start=100.0, period_end=200.0)

    assert pack.source_event_ids == ["evt-1", "evt-2"]
    assert pack.importance_aggregate > 0
```

- [ ] **Step 2: Run the failing tests**

Run: `PYTHONPATH=/Users/asuka/code/magi/backend/src pytest backend/tests/memory/l3/test_temporal_llm_service.py -k build_temporal_evidence_pack -v`
Expected: FAIL because the service does not exist.

- [ ] **Step 3: Implement rule-side evidence-pack construction**

Implementation notes:
- Preserve current L1 filtering rules.
- Keep only compact event fields for prompt input.
- Generate rule hints such as top topics/entities only if they can be built cheaply.

- [ ] **Step 4: Re-run the focused tests**

Run: `PYTHONPATH=/Users/asuka/code/magi/backend/src pytest backend/tests/memory/l3/test_temporal_llm_service.py -k build_temporal_evidence_pack -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/src/magi/memory/l3/temporal_llm_service.py backend/tests/memory/l3/test_temporal_llm_service.py
git commit -m "feat: add temporal evidence pack builder"
```

## Chunk 2: LLM Generation And Fallback

### Task 3: Add structured temporal LLM output parsing

**Files:**
- Modify: `backend/src/magi/memory/l3/models.py`
- Modify: `backend/src/magi/memory/l3/temporal_llm_service.py`
- Modify: `backend/tests/memory/l3/test_temporal_llm_service.py`

- [ ] **Step 1: Write failing tests for JSON parsing**

```python
def test_parse_temporal_llm_output_into_candidate():
    payload = {
        "content": "The day centered on clarifying job-switch priorities.",
        "key_topics": ["job_search"],
        "key_entities": [{"entity_id": "user:self", "entity_type": "user"}],
        "sentiment_summary": {"tone": "serious_but_constructive"},
        "change_and_pattern": {"changes": ["moved from exploration to planning"], "patterns": []},
        "importance_aggregate": 0.8,
    }

    candidate = service.parse_llm_output(payload, pack=pack)

    assert candidate.summary_type == "temporal"
    assert candidate.summary_category == "day"
```

- [ ] **Step 2: Run the failing tests**

Run: `PYTHONPATH=/Users/asuka/code/magi/backend/src pytest backend/tests/memory/l3/test_temporal_llm_service.py -k parse_temporal_llm_output -v`
Expected: FAIL because the parser does not exist.

- [ ] **Step 3: Implement minimal parsing**

Implementation notes:
- Fail closed on malformed JSON.
- Map the output to an `L3Candidate` plus metadata overrides.
- Do not accept missing `content`.

- [ ] **Step 4: Re-run the focused tests**

Run: `PYTHONPATH=/Users/asuka/code/magi/backend/src pytest backend/tests/memory/l3/test_temporal_llm_service.py -k parse_temporal_llm_output -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/src/magi/memory/l3/models.py backend/src/magi/memory/l3/temporal_llm_service.py backend/tests/memory/l3/test_temporal_llm_service.py
git commit -m "feat: parse temporal l3 llm output"
```

### Task 4: Add timeout-safe LLM fallback behavior

**Files:**
- Modify: `backend/src/magi/memory/l3/temporal_llm_service.py`
- Modify: `backend/tests/memory/l3/test_temporal_llm_service.py`

- [ ] **Step 1: Write failing tests for fallback on timeout and invalid output**

```python
@pytest.mark.asyncio
async def test_generate_candidate_falls_back_to_rule_summary_on_timeout():
    result = await service.generate_temporal_candidate(pack, fallback_summary="rule text")

    assert result.used_fallback is True
    assert result.candidate.content == "rule text"
```

- [ ] **Step 2: Run the failing tests**

Run: `PYTHONPATH=/Users/asuka/code/magi/backend/src pytest backend/tests/memory/l3/test_temporal_llm_service.py -k falls_back_to_rule_summary -v`
Expected: FAIL because fallback orchestration does not exist.

- [ ] **Step 3: Implement timeout-safe generation**

Implementation notes:
- Always compute the rule fallback first.
- Only call the model if the pack passes the minimum threshold.
- On timeout, JSON parse error, or validator rejection, return the rule fallback candidate.

- [ ] **Step 4: Re-run the focused tests**

Run: `PYTHONPATH=/Users/asuka/code/magi/backend/src pytest backend/tests/memory/l3/test_temporal_llm_service.py -k falls_back_to_rule_summary -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/src/magi/memory/l3/temporal_llm_service.py backend/tests/memory/l3/test_temporal_llm_service.py
git commit -m "feat: add temporal summary llm fallback"
```

## Chunk 3: Store Integration

### Task 5: Route `generate_temporal_summary()` through the temporal LLM service

**Files:**
- Modify: `backend/src/magi/memory/l3/summary_store.py`
- Modify: `backend/tests/memory/l3/test_summary_store.py`

- [ ] **Step 1: Write failing tests for LLM-backed temporal generation preserving links**

```python
async def test_generate_temporal_summary_uses_llm_candidate_when_available(tmp_path):
    summary = await l3_store.generate_temporal_summary(...)

    assert summary["content"] == "LLM rewritten temporal summary"
    assert await l3_store.list_summary_event_links(summary["summary_id"])
```

- [ ] **Step 2: Run the failing tests**

Run: `PYTHONPATH=/Users/asuka/code/magi/backend/src pytest backend/tests/memory/l3/test_summary_store.py -k llm_candidate_when_available -v`
Expected: FAIL because the LLM service is not wired in.

- [ ] **Step 3: Integrate the service into `summary_store`**

Implementation notes:
- Preserve the current public API of `generate_temporal_summary()`.
- Keep current traceability fields and link persistence.
- Reuse the existing validator and `upsert_candidate` path.

- [ ] **Step 4: Re-run the focused tests**

Run: `PYTHONPATH=/Users/asuka/code/magi/backend/src pytest backend/tests/memory/l3/test_summary_store.py -k llm_candidate_when_available -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/src/magi/memory/l3/summary_store.py backend/tests/memory/l3/test_summary_store.py
git commit -m "refactor: route temporal summaries through llm service"
```

### Task 6: Keep `UnifiedMemoryStore.generate_summary()` behavior stable

**Files:**
- Modify: `backend/src/magi/memory/__init__.py`
- Modify: `backend/tests/memory/test_memory_layers.py`

- [ ] **Step 1: Write failing tests for the high-level generate-summary path**

```python
async def test_generate_summary_still_returns_temporal_summary_after_llmization(store):
    summary = await store.generate_summary(period_type="day", ...)

    assert summary is not None
    assert summary["summary_type"] == "temporal"
```

- [ ] **Step 2: Run the failing tests**

Run: `PYTHONPATH=/Users/asuka/code/magi/backend/src pytest backend/tests/memory/test_memory_layers.py -k generate_summary_still_returns_temporal_summary -v`
Expected: FAIL if integration broke the public path.

- [ ] **Step 3: Adjust only the integration edge**

Implementation notes:
- Do not change the call signature.
- Keep fallback semantics entirely inside the L3 layer.

- [ ] **Step 4: Re-run the focused tests**

Run: `PYTHONPATH=/Users/asuka/code/magi/backend/src pytest backend/tests/memory/test_memory_layers.py -k generate_summary_still_returns_temporal_summary -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/src/magi/memory/__init__.py backend/tests/memory/test_memory_layers.py
git commit -m "test: protect temporal summary generate path"
```

## Chunk 4: Config And Verification

### Task 7: Add config gating for temporal LLM summaries

**Files:**
- Modify: `backend/src/magi/config/models.py`
- Modify: `backend/src/magi/memory/lifecycle.py`
- Modify: tests covering config or lifecycle wiring if they exist

- [ ] **Step 1: Write failing tests for config defaults**

```python
def test_memory_config_defaults_temporal_llm_summary_to_disabled():
    cfg = ...
    assert cfg.agent.memory.enable_l3_temporal_llm is False
```

- [ ] **Step 2: Run the failing tests**

Run: `PYTHONPATH=/Users/asuka/code/magi/backend/src pytest ... -k temporal_llm_summary_to_disabled -v`
Expected: FAIL because the config fields do not exist.

- [ ] **Step 3: Add minimal config wiring**

Implementation notes:
- Add enable flag.
- Add timeout seconds.
- Add minimum evidence threshold if needed.
- Default off unless product policy says otherwise.

- [ ] **Step 4: Re-run the focused tests**

Run: `PYTHONPATH=/Users/asuka/code/magi/backend/src pytest ... -k temporal_llm_summary_to_disabled -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/src/magi/config/models.py backend/src/magi/memory/lifecycle.py
git commit -m "feat: add temporal l3 llm config"
```

## Verification Pass

- [ ] Run the temporal L3 service suite:
  `PYTHONPATH=/Users/asuka/code/magi/backend/src pytest backend/tests/memory/l3/test_temporal_llm_service.py backend/tests/memory/l3/test_summary_store.py -v`
- [ ] Run the memory-layer regression slice:
  `PYTHONPATH=/Users/asuka/code/magi/backend/src pytest backend/tests/memory/test_memory_layers.py -k generate_summary -v`
- [ ] Run the chat-side regression slice if temporal summaries are consumed there indirectly.

## Notes For Execution

- Land the evidence-pack contracts before any LLM prompt code.
- Keep the fallback path working from the first commit; never leave `generate_temporal_summary()` dependent on successful model output.
- Treat the LLM output as untrusted input: parse, validate, and fall back.
- Keep this plan independent from future thematic/insight work so it can ship on its own.

Plan complete and saved to `docs/superpowers/plans/2026-03-18-l3-temporal-summary-llmization.md`. Ready to execute?
