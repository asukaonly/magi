# LongMemEval Unknown Analysis For `0320-17-13-test`

## Scope

This report summarizes all `hypothesis = "unknown"` rows from:

- `/Users/asuka/code/LongMemEval/outputs/longmemeval/0320-17-13-test/predictions_with_trace.jsonl`
- `/Users/asuka/code/LongMemEval/outputs/longmemeval/0320-17-13-test/summary.json`

The goal is to separate expected abstentions from actionable failures, identify the dominant failure archetypes, and turn them into an implementation roadmap for the hybrid retrieval and answer synthesis stack.

## Dataset-Level Summary

- Total questions: `500`
- Questions with `hypothesis = "unknown"`: `261`
- Unknown rows that are benchmark abstentions: `23`
- Actionable unknown rows (non-abstention): `238`

### Unknown Rate By Question Type

Non-abstention only:

- `single-session-assistant`: `41 / 56 = 73.2%`
- `temporal-reasoning`: `80 / 127 = 63.0%`
- `single-session-preference`: `15 / 30 = 50.0%`
- `multi-session`: `60 / 121 = 49.6%`
- `single-session-user`: `22 / 64 = 34.4%`
- `knowledge-update`: `20 / 72 = 27.8%`

This makes the current weak spots clear:

1. Assistant-authored recall
2. Temporal reasoning that needs decomposition or arithmetic
3. Cross-session aggregation

## Failure Buckets

The `238` actionable unknown rows cluster into three buckets:

- `140` `no_evidence`
  - no hits, no bundles, no timeline summary
- `20` `thin_evidence`
  - one hit or one very thin bundle, not enough to answer
- `78` `abstained_with_evidence`
  - multiple hits and/or timeline entries exist, but the system still returns `unknown`

### Why This Split Matters

- `no_evidence` is primarily a retrieval planning and candidate generation problem.
- `thin_evidence` is usually a coverage or grouping problem.
- `abstained_with_evidence` means retrieval is already partially working, but we still rely on the answer LLM for tasks that should be handled programmatically.

## Primary Failure Archetypes

## 1. Temporal Distance And Anchor Decomposition

These questions require two event anchors and a programmatic comparison or date delta. They are not well served by a single semantic query.

Representative rows:

- `0bb5a684`
  - `How many days before the team meeting I was preparing for did I attend the workshop on 'Effective Communication in the Workplace'?`
  - bucket: `no_evidence`
- `a3045048`
  - `How many days before my best friend's birthday party did I order her gift?`
  - bucket: `no_evidence`
- `gpt4_0a05b494`
  - `Who did I meet first, the woman selling jam at the farmer's market or the tourist from Australia?`
  - bucket: `no_evidence`
- `gpt4_0b2f1d21`
  - `Which event happened first, the purchase of the coffee maker or the malfunction of the stand mixer?`
  - bucket: `abstained_with_evidence`
- `e4e14d04`
  - `How long had I been a member of 'Book Lovers Unite' when I attended the meetup?`
  - bucket: `abstained_with_evidence`
- `cc6d1ec1`
  - `How long had I been bird watching when I attended the bird watching workshop?`
  - bucket: `abstained_with_evidence`

Observed pattern:

- The question contains two events, but only one is a quoted title or explicit noun phrase.
- The other anchor is often a descriptive phrase such as `the team meeting I was preparing for`.
- Current backstops handle:
  - quoted coverage
  - simple `A or B` comparisons
- Current backstops do not reliably handle:
  - `how many days before/after`
  - `how long had I been X when Y happened`
  - descriptive anchor phrases tied to a later calculation

Recommended product change:

- Add a `temporal_distance` query class.
- Parse the question into:
  - anchor A
  - anchor B
  - relation (`before`, `after`, `first`, `later`)
  - unit (`days`, `weeks`, `months`, `years`)
- Run independent anchor retrieval plans.
- Normalize dates from each anchor.
- Compute the delta or ordering in code before answer synthesis.

## 2. Cross-Session Aggregation And Counting

These questions are not really asking for a single memory. They are asking for aggregation over multiple sessions with filtering, deduplication, and arithmetic.

Representative rows:

- `6d550036`
  - `How many projects have I led or am currently leading?`
  - bucket: `no_evidence`
- `gpt4_59c863d7`
  - `How many model kits have I worked on or bought?`
  - bucket: `no_evidence`
- `3a704032`
  - `How many plants did I acquire in the last month?`
  - bucket: `no_evidence`
- `gpt4_a56e767c`
  - `How many movie festivals that I attended?`
  - bucket: `no_evidence`
- `28dc39ac`
  - `How many hours have I spent playing games in total?`
  - bucket: `abstained_with_evidence`
- `46a3abf7`
  - `How many tanks do I currently have, including the one I set up for my friend's kid?`
  - bucket: `abstained_with_evidence`

Observed pattern:

- Current retrieval produces candidate memories, but there is no explicit reducer for:
  - `count`
  - `sum`
  - `distinct count`
  - `argmax`
  - `time-filtered aggregation`
- When retrieval does find some evidence, answer synthesis still has to infer:
  - which mentions refer to the same object
  - which mentions should be counted
  - whether the scope is `currently`, `this year`, `last month`, or `in total`

Recommended product change:

- Introduce aggregation-oriented question classes:
  - `count_entities`
  - `sum_duration`
  - `count_distinct`
  - `argmax_entity`
- Move counting and summation into deterministic reducers.
- Let the answer LLM surface only the final result and a short explanation.

## 3. Assistant-Authored And Recommendation Recall

This is currently the worst-performing category by rate.

Representative rows:

- `7161e7e2`
  - `... what was the rotation for Admon on a Sunday?`
- `89527b6b`
  - `... what color was the scaly body of the Plesiosaur in the image?`
- `e9327a54`
  - `... that unique dessert shop with the giant milkshakes ...`
- `4c36ccef`
  - `... the romantic Italian restaurant in Rome ...`
- `cc539528`
  - `... what back-end programming languages you recommended I learn?`
- `18dcd5a5`
  - `... how many mummies the party will face in the temple?`

Observed pattern:

- The answer lives in assistant text, recommendations, or even media-associated content.
- The current retrieval stack is biased toward user-authored factual event statements.
- Assistant replies are often long, generic, or compressed away, which lowers recall for exactly these tasks.

Recommended product change:

- Add an assistant-recall retrieval mode with higher assistant-turn weight.
- Detect when the question explicitly asks:
  - `you recommended`
  - `you said`
  - `our previous chat`
  - `in the image`
- Route these queries to a dedicated recall plan instead of generic L1 event search.
- For media/image cases, attach media/text extraction references to evidence instead of relying on generic turn text.

## 4. Evidence Exists But The System Still Abstains

This is the most important secondary bucket because it represents cases where retrieval is already partially good enough.

There are `49` actionable unknown rows where:

- `l1_hit_count >= 4`
- `l1_timeline_summary_count >= 2`

Representative rows:

- `2c63a862`
  - `How many days did it take for me to find a house I loved after starting to work with Rachel?`
- `982b5123`
  - `How many months ago did I book the Airbnb in San Francisco?`
- `gpt4_9a159967`
  - `Which airline did I fly with the most in March and April?`
- `d01c6aa8`
  - `How old was I when I moved to the United States?`
- `gpt4_4cd9eba1`
  - `How many weeks have I been accepted into the exchange program when I started attending the pre-departure orientation sessions?`
- `28dc39ac`
  - `How many hours have I spent playing games in total?`

Observed pattern:

- We already have the raw ingredients:
  - multiple hits
  - grouped bundles
  - usable timeline summaries
- But the answer still depends on the LLM to do:
  - arithmetic
  - ordering
  - grouping
  - max selection
  - age or duration computation

Recommended product change:

- Add deterministic reducers between retrieval and answer synthesis.
- Use structured intermediate values such as:
  - `start_date`
  - `end_date`
  - `delta_days`
  - `delta_months`
  - `entity_counts`
  - `entity_totals`
  - `top_entity`
- Feed both the structured result and the supporting evidence to the answer LLM.

## 5. Preference And Advice Follow-Ups

These are not pure fact retrieval questions. They ask the system to remember user context and then synthesize a recommendation.

Representative rows:

- `0edc2aef`
  - `Can you suggest a hotel for my upcoming trip to Miami?`
- `75832dbd`
  - `Can you recommend some recent publications or conferences that I might find interesting?`
- `afdc33df`
  - `My kitchen's becoming a bit of a mess again. Any tips for keeping it clean?`
- `caf03d32`
  - `I've been struggling with my slow cooker recipes. Any advice on getting better results?`

Observed pattern:

- Some of these have evidence, but there is no structured preference profile available to ground the recommendation.
- Others are not truly answerable through L1 event retrieval alone.

Recommended product change:

- Split recommendation tasks from recall tasks.
- Prefer L2/L3 preference and profile memory for these questions.
- Only use L1 as supporting detail, not as the primary source.

## Quantitative Takeaways

Among the `238` actionable unknown rows:

- `140` are still retrieval failures with zero evidence.
- `78` already have enough raw evidence to justify a deterministic reducer.
- `20` are coverage-thin cases where retrieval is close but not robust enough.

Most common non-abstention unknown combinations:

- `single-session-assistant + no_evidence`: `41`
- `temporal-reasoning + abstained_with_evidence`: `40`
- `multi-session + no_evidence`: `30`
- `temporal-reasoning + no_evidence`: `29`
- `multi-session + abstained_with_evidence`: `24`

This strongly suggests that the next engineering wins are not more prompt tuning. They are:

1. Better retrieval routing
2. Better query decomposition
3. Deterministic reducers for arithmetic and aggregation

## Recommended Execution Order

## P0. Temporal-Distance And Event-Comparison Decomposition

Target outcomes:

- `how many days before/after`
- `how long had I been X when Y`
- descriptive anchor comparisons

Why first:

- Temporal reasoning is the largest actionable failure group.
- It already has partial retrieval infrastructure and timeline support.

## P1. Deterministic Reducers For Date Math And Aggregation

Target outcomes:

- date deltas
- age and duration
- totals
- counts
- most/least selection

Why second:

- We already have at least `78` actionable unknown rows with enough evidence to support a reducer.
- This should convert many `abstained_with_evidence` cases without needing new retrieval work.

## P2. Assistant-Recall Retrieval Mode

Target outcomes:

- `you recommended`
- `you said`
- assistant-generated named entities
- media-backed recall

Why third:

- This is the single worst question type by unknown rate.
- The current retrieval bias is systematically wrong for these questions.

## P3. Preference/Profile Routing

Target outcomes:

- recommendation follow-ups
- preference-aware suggestions
- advice grounded in remembered context

Why fourth:

- These need a different source of truth than pure L1 event search.
- Better routing to L2/L3 should reduce both no-evidence and weak-answer cases.

## Practical Next Step

The most leverage comes from turning the current retrieval stack into a two-stage system for reasoning-heavy questions:

1. Retrieve evidence
2. Reduce evidence into structured intermediate facts
3. Ask the LLM to verbalize the already-computed result

The immediate implementation candidate is:

- add `temporal_distance` decomposition
- add programmatic date-delta reducers
- extend the existing timeline summary pathway to carry normalized anchor dates

That path directly addresses the highest-value unknown bucket without requiring a full redesign of the rest of the memory system.
