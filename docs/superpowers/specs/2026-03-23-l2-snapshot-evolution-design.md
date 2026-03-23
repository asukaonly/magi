# L2 Snapshot Evolution Design

## Goal

Extend L2 conflict arbitration so `mark_evolution` affects snapshot materialization, not just raw L2 record status, allowing snapshot consumers to read the current state directly while still preserving a lightweight evolution trail for recent changes.

## Problem

The current L2 arbitration path now supports `mark_evolution`, and old graph facts can be downgraded out of the active set. However, snapshot materialization still treats the world mostly as a flat “current valid records” view.

That creates three gaps:

1. snapshot readers cannot distinguish a stable current fact from a recently superseded fact unless they query raw L2 tables
2. current-state retrieval loses useful “what changed” context for recent reversals or updates
3. future L3 state-change and trend-shift work has no structured evolution payload to build on

For the next step, the priority is to improve the L2 snapshot read model. L3 enrichment remains a follow-on task.

## Design

### Boundary

- Keep the current `mark_evolution` arbitration decision in the L2 write path.
- Keep `knowledge_graph` and `tom_trait_assertions` as the canonical evidence tables.
- Extend snapshot materialization only; do not redesign the entire L3 insight pipeline in this iteration.
- Include `core_traits`, `preferences`, and `relationship_topology` in the evolution-aware snapshot design.
- Do not introduce a full historical timeline store inside snapshots. Snapshots remain a compact read model.

### Snapshot Semantics

The snapshot should expose two layers:

1. **current state**
   - existing fields such as `core_traits`, `preferences`, and `relationship_topology`
   - these fields should always represent the best current interpretation of active evidence
2. **recent evolution context**
   - a compact record of recent transitions that explains how the current state changed

This preserves snapshot ergonomics for retrieval while adding enough historical structure for explanation and downstream reasoning.

### Recommended Shape

Add lightweight evolution fields to the snapshot JSON payload:

- `core_traits_history`
- `preferences_history`
- `relationship_history`
- `last_evolution_at`
- `active_record_ids`
- `superseded_record_ids`

Each history entry should be a compact transition record:

- `field`
- `from`
- `to`
- `evolved_at`
- `superseded_record_ids`
- `supporting_record_ids`

The history lists should store only recent high-signal transitions, for example the most recent five entries per section.

### Materialization Rules

#### Current-State Fields

- `active` graph facts continue to drive `preferences` and `relationship_topology`
- `stable` or `corroborated` assertion outcomes continue to drive `core_traits`
- `deprecated` facts must not remain in the current-state fields
- `conflicted` facts must not become current-state winners

#### History Fields

- graph facts superseded by `mark_evolution` should generate history entries under `preferences_history` or `relationship_history`
- assertion outcomes superseded by future evolution-aware assertion handling should generate entries under `core_traits_history`
- the history entry should describe the transition rather than mirror the entire raw record

### Evolution Classification

History should only be written for meaningful current-state changes:

- preference reversals such as `LIKES -> DISLIKES`
- exclusive relationship replacements such as role or attachment changes
- trait changes that move the visible `core_traits` value to a new winner

The following should not create history entries in this iteration:

- routine corroboration that does not change the visible winner
- temporary confidence fluctuations
- low-confidence contradiction hints that do not produce `mark_evolution`

### Source of Truth

The raw truth remains in:

- `knowledge_graph`
- `tom_trait_assertions`

The snapshot history is derived, lossy, and intentionally small. Consumers that need full history should still query the underlying L2 tables.

### Refresh Flow

No new queue type is required.

The existing snapshot refresh worker should continue to call `refresh_entity_snapshot()`. The new behavior lives inside snapshot materialization:

1. load current active graph/assertion evidence
2. detect recently superseded records relevant to snapshot-backed fields
3. build current-state fields from current winners only
4. build compact evolution history from recent superseded transitions
5. write the new snapshot payload

### L3 Follow-On

This design is intentionally a precursor to deeper L3 work.

Once the snapshot contains structured evolution context, later work can:

- emit stronger `state_change` insights
- distinguish stabilization from true reversal
- support retrieval prompts that mention both current state and recent evolution

That follow-on should be a separate task.

## Non-Goals

- No full timeline system embedded inside snapshots
- No new persistent evolution table in this first iteration
- No immediate redesign of L3 candidate builders
- No broad retrieval prompt changes in the same task
- No attempt to backfill all historical snapshots retroactively

## Validation

Success for this iteration should be measured by:

1. snapshots reflect the current winner after `mark_evolution`
2. superseded records no longer appear in current-state snapshot fields
3. recent evolution metadata is available for `core_traits`, `preferences`, and `relationship_topology`
4. existing snapshot refresh flow remains asynchronous and failure-isolated
5. raw L2 truth tables remain unchanged as the canonical evidence source
