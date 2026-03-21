# Eval Answer Layer Classification

## Scope

This note classifies the answer-synthesis logic currently concentrated in:

- `/Users/asuka/code/magi/backend/src/magi/api/routers/memory.py`

The goal is to separate:

- generic retrieval and answer-quality improvements that should exist for normal memory queries
- reusable answer reducers that are currently wired only through the benchmark API path
- benchmark-only normalization or instrumentation that should stay isolated in the eval path

This classification is based on the current implementation around `_synthesize_eval_answer()` and its helper functions.

## Current Eval Answer Stack

The eval API currently does four jobs in one place:

1. It detects whether the question can be answered by a deterministic reducer.
2. It formats retrieved evidence into an answer prompt.
3. It runs an answer LLM with eval-specific safety constraints.
4. It normalizes the final answer toward benchmark-style short spans.

These jobs do not all belong to the same product layer.

## Classification

## 1. Public Retrieval Improvements Already Absorbed Elsewhere

These are not benchmark-specific even if benchmark failures motivated them. They improve evidence quality or retrieval coverage in a way that should benefit normal memory recall.

Primary locations:

- `/Users/asuka/code/magi/backend/src/magi/memory/hybrid_retrieval/service.py`
- `/Users/asuka/code/magi/backend/src/magi/memory/hybrid_retrieval/handlers.py`
- `/Users/asuka/code/magi/backend/src/magi/memory/hybrid_retrieval/result_fusion.py`
- `/Users/asuka/code/magi/backend/src/magi/memory/hybrid_retrieval/timeline_condense.py`
- `/Users/asuka/code/magi/backend/src/magi/memory/hybrid_retrieval/answerability.py`

Examples:

- quoted-span coverage backstops
- unquoted comparison candidate coverage
- temporal-distance anchor decomposition for retrieval
- timeline condensation that preserves anchor coverage
- answerability-aware reranking
- fusion rules that reduce noisy assistant guidance dominance

Why these belong in the public layer:

- they improve whether the system can find the right evidence at all
- they are useful outside benchmark evaluation
- they do not depend on benchmark gold-answer wording

## 2. Reusable Answer Reducers That Are Currently Eval-Wired

These are product-useful capabilities, but today they only run through the eval answer path.

Primary locations:

- `/Users/asuka/code/magi/backend/src/magi/api/routers/memory.py`

Relevant functions:

- `_should_prioritize_timeline(...)`
- `_resolve_temporal_distance_answer(...)`
- `_extract_anchor_calendar_date(...)`
- `_extract_explicit_calendar_date_candidates(...)`
- `_extract_relative_week_date_candidates(...)`

Current behavior:

- temporal or comparison questions can prefer `timeline_summary` over raw bundles
- explicit date anchors can be normalized into calendar dates
- `how many days/weeks before/after` can be answered deterministically
- some relative week expressions can be converted without relying on the answer LLM

Why these should move toward a shared product layer:

- they improve answer correctness for any memory question involving time comparison
- they reduce answer-model dependence for arithmetic and ordering
- they are not tied to benchmark answer wording

Recommended destination:

- a shared reducer module under the memory retrieval stack, for example:
  - `/Users/asuka/code/magi/backend/src/magi/memory/hybrid_retrieval/reducers.py`
  - or `/Users/asuka/code/magi/backend/src/magi/memory/answering/reducers.py`

Recommended contract:

- input:
  - original question
  - normalized evidence hits
  - timeline summary
  - query timestamp
- output:
  - optional structured answer result, for example:
    - `kind`
    - `value`
    - `supporting_turn_ids`
    - `confidence`

This keeps deterministic computation reusable for:

- benchmark eval
- normal chat memory answers
- future UI inspector tooling

## 3. Generic Answer-Formatting Logic That Should Be Shared

These parts are currently embedded inside `_synthesize_eval_answer()` but represent a generally useful answer-shaping policy.

Current behaviors:

- prefer the timeline summary first for temporal and comparison questions
- suppress noisy raw bundles when the timeline already captures the relevant chain
- ask the answer model for concise final spans instead of free-form narration
- disable reasoning-mode token burn for narrow answer synthesis

Primary location:

- `/Users/asuka/code/magi/backend/src/magi/api/routers/memory.py`

Why these should become shared:

- they improve robustness for real memory Q&A, not only eval
- they reduce the chance that the answer model is distracted by long raw evidence
- they are format decisions, not benchmark gold-answer hacks

Recommended destination:

- a reusable answer prompt builder or answer policy component, for example:
  - `/Users/asuka/code/magi/backend/src/magi/memory/answering/prompt_builder.py`

Recommended boundary:

- product answer policy decides:
  - evidence priority
  - whether timeline-first mode applies
  - whether short-span mode applies
  - whether model thinking should be disabled
- eval path may still wrap this policy with benchmark-specific options

## 4. Benchmark-Only Normalization And Instrumentation

These parts are clearly tied to benchmark scoring, not general memory quality.

Primary location:

- `/Users/asuka/code/magi/backend/src/magi/api/routers/memory.py`

Relevant functions and behaviors:

- `_normalize_eval_answer(...)`
  - first block / first line truncation
  - article stripping for very short answers
- `_canonicalize_issue_component_answer(...)`
  - converts component-only answers such as `GPS system` into benchmark-style malfunction text
- eval-only answer prompt phrasing:
  - `Return only the final answer span`
  - `If the evidence is insufficient, answer exactly: unknown`
- eval-only prompt logging:
  - full system message dump
  - full user message dump
  - raw answer logging

Why these should stay eval-specific:

- they optimize exact-match or near-exact-match scoring
- they can over-constrain normal conversational answers
- they risk rewriting a valid product answer into an unnatural benchmark phrase

Concrete risk if moved to product chat:

- a user asks a natural question and receives a clipped noun phrase instead of a helpful answer
- domain-specific canonicalization turns a broad issue description into a forced template
- article stripping changes the tone or grammaticality of a normal response

## 5. Things That Look Generic But Need Refactoring Before Reuse

Some logic is useful in spirit but currently too eval-shaped to reuse directly.

Examples:

- deterministic temporal reducers live inside an API router file
- prompt policy and answer normalization are interleaved in one function
- issue canonicalization mixes answer shaping with benchmark-specific scoring needs

Before reuse, these should be refactored into:

1. evidence reduction
2. answer policy selection
3. answer rendering
4. eval-only normalization

## Recommended Split

## A. Keep In Eval Path

- benchmark-specific answer span normalization
- benchmark-specific component issue canonicalization
- `unknown` exact-string fallback policy
- full prompt and raw-answer debug logging

## B. Move To Shared Memory Answering

- timeline-first answer policy for temporal and comparison questions
- deterministic temporal distance reducers
- structured date extraction from timeline summaries
- evidence suppression rules that hide noisy raw bundles when the timeline is sufficient
- answer-model settings for narrow answer synthesis such as `disable_thinking=True`

## C. Leave In Retrieval Layer

- all coverage backstops
- candidate decomposition
- reranking improvements
- timeline condensation and anchor preservation

## Proposed Refactor Sequence

1. Extract deterministic temporal reducers from `memory.py` into a shared reducer module.
2. Extract timeline-first and concise-answer prompt construction into a shared answer-policy builder.
3. Keep `_synthesize_eval_answer()` as a thin benchmark wrapper around shared reducers and prompt policy.
4. Leave benchmark normalization in the eval router only.

This preserves benchmark quality while making the useful parts available to normal memory chat.

## Practical Rule Of Thumb

When deciding whether a piece should leave `_synthesize_eval_answer()`:

- if it improves evidence interpretation, temporal arithmetic, or answer robustness for any memory question, it belongs in a shared layer
- if it mostly changes wording toward a benchmark gold answer, it should remain eval-only

## Bottom Line

The current `_synthesize_eval_answer()` contains both product-useful answering logic and benchmark-specific answer shaping.

The most important reusable pieces are:

- timeline-first answer policy
- deterministic temporal reducers
- concise answer prompt construction for narrow memory questions

The clearest eval-only pieces are:

- issue canonicalization toward benchmark wording
- article stripping and first-line clipping for exact-match scoring
- eval-specific prompt and raw-answer logging
