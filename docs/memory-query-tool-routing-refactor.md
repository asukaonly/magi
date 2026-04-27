# Memory Query Tool Routing Refactor

**Status**: Approved, in implementation
**Owner**: Memory team
**Last Updated**: 2026-04-26

## 1. Problem

The `memory_query` tool exposes a clean schema to the core chat LLM
(`query_mode`, `time_range`, `sources`, `summary_categories`, `limit`),
yet three separate decision layers compete to fill those parameters
before the actual retrieval runs:

1. `MemoryQueryHintResolver` (rule-based) inside `ContextDecider` —
   parses the user message with hardcoded patterns + dateparser and
   produces a `routing_memory_hint` dict.
2. The hint is serialized into a system-prompt block
   (`# Memory Query Guidance`) that the chat LLM sees alongside the tool
   schema, strongly biasing its parameter choice.
3. Inside the backend, `IntentDecider` runs a second LLM
   (`LLMIntentDecider`) that re-decides the layer routing on top of the
   already-fixed `query_mode`.

Result: the rule-based pre-decision is the weakest link and frequently
overrides what the chat LLM would have chosen on its own. Concrete
failure: "我最近在用 chrome 看什么" → rule resolver classifies as
`episode_recall` (because verb list misses "看" without aspect marker
and has no `chrome` keyword), the hint gets pushed into chat LLM's
prompt, the LLM defers to the hint, retrieval runs against L1 timeline
events instead of the L3 `browser_activity` summaries we just built.

## 2. Goal

Let the **core chat LLM be the single decision point** for
`memory_query` parameters. The backend trusts those parameters, runs
retrieval mechanically, and only uses LLM internally for
backend-private concerns (content-query rewriting, entity extraction,
predicate inference). Pre-call hint injection is removed entirely.

## 3. Non-Goals

- Cross-unit reranker training (tracked separately).
- Schema migration of L3 `summary_category` storage.
- Frontend / settings changes (none required).

## 4. Architecture Diff

### Before

```
user msg ─► ContextDecider
              ├─ LLM #1 (which tools)
              └─ MemoryQueryHintResolver (rule)
                  └─ routing_memory_hint = {query_mode, sources, time_range}
                      ▼
              ContextDecision.routing_memory_hint
                      ▼
            chat handlers ─► system prompt block
                      ▼
            core chat LLM #2 (fills tool params, biased by hint)
                      ▼
            memory_query tool
                      ▼
            HybridRetrievalService.query
                      ▼
            IntentDecider
              ├─ Rule (mode → layers)
              └─ LLMIntentDecider #3 (re-decides layers)
```

### After

```
user msg ─► ContextDecider
              └─ LLM #1 (which tools, including a should_recall boolean)
                      ▼
            ContextDecision (no routing_memory_hint)
                      ▼
            core chat LLM #2 (fills ALL memory_query params from schema)
                      ▼
            memory_query tool
                      ▼
            HybridRetrievalService.query  (trusts query_mode)
                      ▼
            IntentDecider
              ├─ Rule (mode → layers, no fallback to default mode)
              └─ LLMIntentDecider (only outputs content_query rewrite,
                                    entities, subject_hint, predicate_family,
                                    semantic_frame — NO layers, NO mode)
              └─ Time-range backfill via dateparser when LLM omitted it
```

Net change:
- **One** decision point for `query_mode` (the chat LLM).
- Backend LLM keeps existing value (query rewriting, entity tagging) but
  loses the redundant routing role.
- Rule-based `_route_layers` becomes a pure mode→layers translator.
- Existing `_run_backstops` and `_run_fallback_if_needed` mechanisms in
  `HybridRetrievalService` remain as the safety net when the chat LLM
  picks a wrong mode (result_count below threshold ⇒ rule-based
  backstop adds extra plans).

## 5. Code Changes

### 5.1 Files Deleted

| Path | Reason |
|------|--------|
| `backend/src/magi/tools/memory_query_hint_resolver.py` | Sole consumer is ContextDecider; replaced by chat LLM via tool schema |
| `backend/tests/tools/test_memory_query_hint_resolver.py` (if exists) | Tests of deleted module |

### 5.2 Files Modified

#### `backend/src/magi/tools/context_decider.py`

- Drop import of `MemoryQueryHintResolver`.
- Drop `self._memory_query_hint_resolver`.
- `evaluate_memory_need(user_message, context) -> bool`: keep only the
  boolean recommendation; no `MemoryGuidance.recommended_tools[*].suggested_params`.
- `_apply_memory_guidance`: keep "promote `memory_query` to tools[0]";
  remove the `routing_memory_hint=...` assignment.
- Delete `ContextDecision.routing_memory_hint` field and parameter.
- Delete `_infer_time_range`, `_infer_memory_types` (already deprecated
  per docstring).
- `MemoryGuidance`: remove `recommended_tools[*].suggested_params`;
  reduce `recommended_tools` to a list of names only (or keep dict with
  only `name` + `description`).

#### `backend/src/magi/agent/task_agents/chat/contracts.py`

- Remove `routing_memory_hint: dict[str, Any] | None = None` from the
  intent / decision dataclass.

#### `backend/src/magi/agent/task_agents/chat/coordinator.py`

- Remove `routing_memory_hint=getattr(decision, "routing_memory_hint", None)`.

#### `backend/src/magi/agent/task_agents/chat/handlers.py`

- Delete `_build_memory_query_guidance_block`.
- Delete its call site in the prompt-assembly path.

#### `backend/src/magi/memory/hybrid_retrieval/intent_decider.py`

- `RuleBasedIntentDecider._route_layers`: keep the existing soft
  default to `exact_fact` when `query_mode_hint` is `None` or unknown.
  The tool schema marks `query_mode` as required so production callers
  always supply it; the soft default exists to keep ~50 rule-engine
  unit tests stable and to make the rule engine usable as a
  standalone component (e.g. tests that exercise time-range parsing
  without going through the chat LLM). The mode registry guarantees
  L1 reachability under every mode, so `exact_fact` is a safe
  fallback. *(Deviation from the original plan, which proposed
  raising — keeping the soft default scoped the refactor down without
  losing safety, since invalid `query_mode` from production would
  surface in the validation backstops in `HybridRetrievalService`.)*
- `LLMIntentDecider`:
  - Update `_LLM_SYSTEM_PROMPT` to ask for `content_query`,
    `entities`, `subject_hint`, `predicate_family`, `semantic_frame`,
    `reasoning` only — drop the `layers` array from the JSON schema
    it requests, and tell the LLM that layer routing is decided
    elsewhere.
  - `_parse_response` returns a flat `LLMRefinement` dataclass (or
    `None` when nothing useful came back); it no longer constructs
    `LayerQueryPlan` instances.
  - `evaluate` returns `Optional[LLMRefinement]` (not
    `IntentDecision`).
  - New `apply(original_query, rule_decision, refinement)` method
    overlays the refinement onto the rule-routed plans: `content_query`
    is applied to every plan (with L1 over-broad-rewrite validation
    preserved); `entities` / `subject_hint` / `predicate_family` /
    `semantic_frame` are applied only to L2 plans, then
    `enrich_l2_conditions` runs.
- `IntentDecider.decide`: rule layer routing and time range are
  canonical. When `LLMIntentDecider.evaluate` returns a refinement, the
  decider calls `LLMIntentDecider.apply` to overlay it onto
  `rule_decision.plans`. When it returns `None`, the rule decision is
  used unchanged with `source="rule_fallback"`.
- `EvaluationRecord` / `compute_diff`: refactored to track whether a
  refinement was *applied* (and which fields were touched) instead of
  comparing layer sets between rule and LLM decisions. The
  `llm_decision` / `layers_match` fields are renamed to
  `llm_refinement` / `refinement_applied`. **Breaking change for any
  downstream shadow-eval consumer** — none found in the current
  repository, but external dashboards reading these fields will need
  to be updated.

#### `backend/src/magi/tools/builtin/memory_query_tool.py`

- Add few-shot examples in `query_mode` description (3-5 cases).
- Make `summary_categories` description dynamic: at schema-build time,
  call `plugin_manager.iter_merged_summary_profiles()` (when available)
  and inject the available category names.
- Strengthen `time_range` description: explicitly tell the LLM to fill
  it whenever the user message contains a temporal expression.

### 5.3 Tests

| File | Change |
|------|--------|
| `backend/tests/agent/test_context_decider_memory.py` | Remove all `routing_memory_hint == {...}` assertions; replace with `assert decision.tools[0] == "memory_query"` |
| `backend/tests/agent/test_chat_handlers.py` | Remove `routing_memory_hint=None` kwargs; remove guidance-block expectations |
| `backend/tests/agent/test_chat_execution_coordinator.py` | Same |
| `backend/tests/agent/test_chat_detach_handoff.py` | Same |
| `backend/tests/agent/test_chat_task_agent_runtime.py` | Same |
| `backend/tests/agent/test_interruptible_chat_session_integration.py` | Same |
| `backend/tests/memory/test_intent_decider*.py` (if exists) | Update LLM prompt fixtures; add unit test that mode is taken from request, not LLM |

## 6. Migration Strategy

Single PR per stage. Each stage compiles + passes tests on its own.

### PR-1: Remove pre-call hint injection (this PR)

- Delete `memory_query_hint_resolver.py`
- Strip `routing_memory_hint` from contracts / coordinator / handlers /
  ContextDecider / tests
- `evaluate_memory_need` returns bool; `_apply_memory_guidance`
  promotes `memory_query` without writing parameters
- Run Pylance + existing test suite

Expected impact: chat LLM now picks `query_mode` directly from tool
schema. LongMemEval expected delta: **+1~2%** (no more rule-mis-routing).

### PR-2: Tool schema strengthening

- `query_mode` few-shot examples
- `summary_categories` dynamic from PluginManager
- `time_range` stricter description

Expected impact: smaller models (7B-13B) pick mode correctly more
often. LongMemEval expected delta: **+1~3%**.

### PR-3: Narrow `LLMIntentDecider`

- Drop `layers` from LLM output schema
- Backend LLM only returns retrieval-refinement fields
- Rule engine becomes canonical for layer routing

Expected impact: cleaner separation; backend LLM prompts are shorter
and focused. LongMemEval expected delta: **0~+0.5%** (mostly latency
and clarity wins).

### PR-4 (optional): Telemetry

- Append-only audit log of `(user_query, chat_llm_mode, result_count,
  backstop_triggered, fallback_triggered)` for future fine-tuning data.

## 7. Risk & Rollback

| Risk | Mitigation |
|------|------------|
| Small chat LLM picks wrong `query_mode` | Existing rule + confidence backstops in `HybridRetrievalService` recover when result_count < threshold or top-K avg score < min_score. Safety net unchanged. |
| Tests churn is large | Each PR keeps itself self-contained and reversible. Field deletion (PR-1) is a one-shot clean removal — no deprecation period required because the field is internal and not user-visible. |
| LongMemEval regression | Run benchmark before merge of each PR; gate merge on no regression > 0.5%. |
| Plugin authors using `intent_verbs` for hint resolver | The `SummaryProfileSpec.intent_verbs` field is preserved (still used by future LLM-side prompt hints in PR-2). No plugin contract change. |

## 8. Forward Compatibility

This refactor unblocks two future workstreams:

1. **Cross-unit reranker** (separate doc): once routing is trustworthy,
   the next bottleneck is heterogeneous-unit ranking. PR-1..3 leave the
   ranking surface unchanged.
2. **`query_mode` audit-driven distillation**: data collected by PR-4
   feeds a distilled small-model classifier that can replace the chat
   LLM's mode choice for offline / low-latency paths.

## 9. Validation

- Pylance: all touched modules clean.
- Unit tests: full backend test suite green.
- Integration: replay LongMemEval oracle subset (run_all.py with
  `--limit 50`) before/after each PR; compare `summary.json` accuracy.
- Manual: query "我最近在用 chrome 看什么" against a backend with
  chrome-history plugin enabled and at least one settled
  `browser_activity` summary; verify L3 retrieval path is taken.
