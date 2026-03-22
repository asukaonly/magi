# L2 Microbatch Extraction Design

## Goal

Reduce L2 extraction cost and improve concurrency stability by replacing single-event L2 extraction with session-aware microbatch extraction, without changing the guarantee that L1 is the source-of-truth event layer and must succeed independently from any L2 work.

## Problem

The current L2 pipeline extracts from one `MemoryEvent` at a time. Even though it attaches a few nearby context texts, the runtime shape is still:

1. store one L1 event
2. enqueue one L2 extraction job
3. call the LLM once for that event

This creates four practical problems:

1. bursty chat sessions generate many small L2 calls
2. cost scales poorly because adjacent events are processed separately
3. queue pressure rises quickly during high-volume periods
4. single-event extraction cannot benefit from naturally grouped session context

For the first iteration, cost and concurrency stability are the priority. Accuracy improvements from richer history recall and deep conflict arbitration are explicitly deferred.

## Design

### Boundary

- Keep `L1` synchronous persistence unchanged.
- Keep `L2` asynchronous and failure-isolated from `L1`.
- Change only the L2 extraction entrypoint from single-event jobs to microbatch jobs.
- Do not add cross-session historical retrieval in this first version.
- Do not add deep-model conflict arbitration in this first version.

### Triggering Model

L2 extraction should move from direct single-event enqueueing to a staged microbatch buffer.

Each incoming `MemoryEvent` that is eligible for L2 is first added to a staging bucket. A bucket is keyed by:

1. `session_id` when present
2. otherwise `user_id`
3. otherwise the event falls back to direct single-event extraction

Each bucket flushes when any of the following conditions is met:

1. the oldest pending event has waited at least `l2_batch_flush_interval_seconds`
2. the bucket reaches the internal event-count limit
3. the bucket reaches the internal estimated-token limit
4. the system is shutting down and pending work must be flushed best-effort

The user-facing setting controls only the time-based flush threshold.

### Configuration

Add a new memory setting:

- `l2_batch_flush_interval_seconds`
  - default: `60`
  - minimum: `30`

This setting belongs alongside other L2 memory controls and should flow through:

- backend config models
- config API models
- frontend settings data contract
- settings UI
- localized copy for `en` and `zh-CN`

The following limits remain internal constants in the first version:

- `max_events_per_batch`
- `max_prompt_tokens_per_batch`

These are intentionally not user-configurable yet, to keep the first release simple and stable.

### Pipeline Structure

`L2Pipeline` should become a two-stage pipeline:

1. **staging**
   - receive eligible events
   - place them into in-memory buckets
   - periodically inspect buckets for flush eligibility
2. **batch extraction**
   - convert a flushed bucket into one `L2BatchJob`
   - run unified extraction once for the batch
   - validate, persist, reconcile, and refresh snapshots using the existing downstream stages

This keeps the current post-extraction behavior largely intact while changing only how extraction work is grouped.

### Batch Job Shape

Introduce a dedicated batch job contract so the extraction worker no longer consumes raw events.

The batch job should include:

- `job_id`
- `bucket_key`
- `session_id`
- `user_id`
- `events`
- `flush_reason`
- `estimated_tokens`
- `oldest_event_timestamp`
- `newest_event_timestamp`

The staging bucket should separately track:

- pending events
- token estimate
- first-seen timestamp
- last-seen timestamp
- whether the bucket is currently flushing

### Prompt Shape

The current unified extraction prompt uses a nominal `event_window` but is still populated with a single event. The new batch prompt should make `event_window` a real batch payload.

It should include:

- ordered batch events with `event_id`, `timestamp`, `author_type`, `source`, and `content`
- `event_ids` covering the whole batch
- a compact deterministic batch summary
- a small number of batch-external context texts
- the current `context_bundle`

The prompt should explicitly encourage:

- evidence grounding through `supporting_event_ids`
- cross-event co-reference within the batch
- conservative ToM confidence despite richer batch context

The existing rule that single-source or weak ToM assertions remain low-confidence should continue to hold.

### Context Strategy

The first version should stay conservative:

- use the batch itself as the primary context source
- keep a small amount of adjacent session context outside the batch
- do not yet perform cross-session search or L1 keyword recall

This is a deliberate scope cut to keep the first iteration focused on throughput and queue behavior.

### Failure Handling

- `L1` success must never depend on L2 batch success.
- Staging buckets may remain in memory only for the first version.
- On process restart, unflushed staging events may be lost from memory, but they remain recoverable from `L1`.
- Failed batches should be retried a limited number of times.
- Repeatedly failing batches may be split into smaller batches before the final failure path.
- Shutdown should attempt a best-effort flush with a timeout, but must not block process termination indefinitely.

### Observability

The pipeline should expose batch-oriented stats in addition to current extraction stats:

- total batch flush count
- flush count by reason
- average events per batch
- average estimated tokens per batch
- active bucket count
- pending staged event count

This observability is part of the feature, because the first release is primarily about operational improvement.

## Non-Goals

- No persistent batch queue in the first version
- No cross-session historical retrieval augmentation
- No deep-model conflict arbitration
- No redesign of contradiction detection or reconcile semantics
- No expansion of user-facing expert controls beyond batch flush interval

## Migration Path

The first release should preserve the current downstream L2 write pipeline so that future iterations can build on a stable microbatch entrypoint.

Planned follow-on work after this version:

1. history-aware retrieval for batch grounding
2. stronger contradiction escalation and arbitration
3. optional persistent staging queue and crash recovery

## Validation

Success for the first version should be measured by:

1. fewer L2 LLM calls under bursty event streams
2. higher average events per L2 call
3. stable queue behavior under load
4. unchanged L1 durability guarantees
5. unchanged L2 downstream persistence semantics for graph and assertion writes
