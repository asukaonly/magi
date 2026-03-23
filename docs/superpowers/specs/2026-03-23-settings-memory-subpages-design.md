# Settings Memory Subpages Design

## Context

The current settings page renders all memory lifecycle configuration inside one large `memory` section with stacked expandable cards for `L0` through `L4`. This creates three UX problems:

- the settings navigation implies memory is a single page, while the product now treats memory as a family of distinct workspaces
- lifecycle controls for different layers are visually mixed together, making it harder to understand ownership and dependencies
- the page structure no longer matches the information architecture already used by the main memory workspace and the grouped `LLM` settings navigation

The goal of this redesign is to align settings IA with the memory product model while preserving the saved/draft workflow that already exists in `useSettings`.

## Goals

- turn `memory` into a grouped settings navigation item
- expose six dedicated memory subpages:
  - general memory settings
  - workbench memory
  - event memory
  - knowledge memory
  - reflection memory
  - tool skill memory
- reuse the product-facing labels from the main memory workspace instead of surfacing `L0-L4` terminology in navigation
- let each subpage own its own layout and control density
- keep all memory edits inside the existing settings draft/save flow

## Navigation Design

The left settings navigation should treat `memory` the same way `llm` is handled today:

- top-level item: `memory`
- expandable children:
  - `memoryGeneral`
  - `memoryWorkbench`
  - `memoryEvents`
  - `memoryKnowledge`
  - `memoryReflection`
  - `memorySkills`

Behavior:

- clicking the `memory` group expands or collapses it
- first expanding the group routes the right pane to `memoryGeneral`
- clicking a child item switches the right pane title directly to that child label
- no combined “all memory layers on one page” fallback remains

## Page Responsibilities

### General Memory Settings

This page holds memory-wide controls that do not belong to one lifecycle layer only.

Initial scope:

- global vectorization/asynchronous embedding behavior
- lifecycle overview copy
- dependency hints:
  - `knowledge / reflection / tool skills` depend on `event memory`
- any future cross-layer pipeline toggles

This page should read as a control surface for the whole memory pipeline, not a layer-specific editor.

### Workbench Memory

This page owns short-lived working-context behavior:

- enable/disable workbench memory
- checkpoint interval
- whether `L0-only` runtime replay events are included

The layout should be more operational and lightweight than the other layers.

### Event Memory

This page owns long-term event memory:

- enable/disable event memory
- retention window
- importance scoring
- event vectorization

This page should frame `event memory` as the durable base for downstream layers.

### Knowledge Memory

This page owns structured cognition settings:

- enable/disable knowledge memory
- LLM extraction
- batch flush interval
- conflict arbitration
- arbitration confidence threshold

The page should communicate the dependency on event memory clearly.

### Reflection Memory

This page owns summary and reflection generation:

- enable/disable reflection memory
- LLM summary / reflection generation
- reflection vectorization

The layout can prioritize cadence and generation behavior over low-level storage language.

### Tool Skill Memory

This page owns procedural skill extraction:

- enable/disable tool skill memory
- skill extraction
- related dependency hints

The page should communicate that this layer is built from observed execution and retained event context.

## UI Structure

The right pane should stop reusing one repeated expandable-card stack for all memory controls.

Instead:

- each memory subpage renders as its own settings page body
- the page header uses the child label directly
- each subpage can choose its own grouping, intro copy, and control order
- the visual language should stay within the warm settings theme shell already introduced in the settings dialog

This means memory configuration becomes a small settings subsystem instead of one oversized section.

## Data Model And State

The underlying config model does not need a schema change for this IA refactor.

The implementation should continue using:

- `draftConfig.memory.l0`
- `draftConfig.memory.l1`
- `draftConfig.memory.l2`
- `draftConfig.memory.l3`
- `draftConfig.memory.l4`

The refactor is a UI decomposition, not a config format migration.

Additional frontend state needed:

- memory nav group expansion in the same grouped-nav state as `llm`
- new `activeSection` ids for the six memory child pages

## Testing Strategy

Required regression coverage:

- grouped navigation:
  - memory group expands and collapses
  - memory child routes render
  - first group expansion lands on `memoryGeneral`
- draft/save behavior:
  - editing controls in at least two memory child pages persists through the existing settings save flow
- settings shell:
  - right pane heading matches the active memory child page

## Non-Goals

- no backend config schema changes
- no memory behavior changes
- no compatibility path for the old single-page memory settings UI
- no redesign of unrelated settings families in this task
