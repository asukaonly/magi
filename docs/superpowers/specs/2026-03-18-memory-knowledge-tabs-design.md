# Memory Knowledge In-Page Tabs Design

## Context

The current L2 knowledge page keeps a shared filter bar at the top, but almost all knowledge content is still rendered through one oversized `L2Tab` surface. This makes the page hard to scan because graph data, ToM assertions, snapshots, mentions, conflict rules, and lab controls all compete for the same vertical reading path.

The user wants to keep L2 as one route while splitting the page body into a row of in-page tabs. Each tab should feel like its own focused knowledge board instead of one long stack.

## Goals

1. Keep `/memory/knowledge` as a single route.
2. Add an in-page tab bar below the shared L2 filters.
3. Split the body into these eight tabs:
   - overview
   - knowledge graph
   - theory of mind
   - mind snapshots
   - lab
   - canonical entities
   - recent mentions
   - conflict rules
4. Let each tab surface only the modules that belong to that slice.
5. Keep the visual language calm and product-like instead of decorative.

## Approved Direction

The approved direction is a "single page, many focused boards" layout:

- keep the existing page title and filters
- use a horizontal tab row for the eight L2 slices
- give each tab its own layout and emphasis
- avoid building another heavy hero or oversized summary wall

## Information Architecture

### Shared layer

The page-level shell continues to own:

- title and description
- refresh action
- query and entity-type filters
- shared filtered datasets derived from the current query and entity type

### Tab-level ownership

Each tab owns its own presentation:

- `overview`
  - compact structural summary
  - identity mapping summary
  - evidence and skip reason breakdown
  - pointers to the densest predicates and active entities
- `knowledgeGraph`
  - relation status filter
  - relation list
  - dominant predicate context
- `theoryOfMind`
  - assertion list and validation state emphasis
- `mindSnapshots`
  - snapshot list and stable trait summaries
- `lab`
  - manual event injection
  - replay extraction
  - reconcile and snapshot actions
- `canonicalEntities`
  - canonical entity cards and aliases
- `recentMentions`
  - mention evidence cards
- `conflictRules`
  - existing rules list
  - rule editor

## Visual Rules

- Keep the tab bar compact and quiet.
- Do not use large hero typography, gradients, or decorative illustration.
- Prefer card grouping, spacing, and local summaries over giant all-page metric rows.
- Make each tab feel denser or lighter depending on its content rather than forcing one repeated structure.

## Component Direction

`MemoryKnowledgePage` should own the tab state because the tab row belongs to the page, not the lower-level L2 inspector.

`L2Tab` should be refactored into a tab-aware content renderer or a set of smaller L2 section components so the page can render one focused section at a time.

## Testing Expectations

Validation should cover:

- the knowledge page rendering an in-page tab list
- switching tabs revealing the correct section content
- non-active tab content not being shown at the same time
- existing memory route tests and type-check staying green

## Non-Goals

- splitting L2 into multiple routes
- redesigning other memory pages in the same task
- changing backend memory APIs
