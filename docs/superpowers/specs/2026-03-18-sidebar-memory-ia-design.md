# Sidebar And Memory IA Redesign

## Context

The desktop shell currently uses a split sidebar model:

- a top chat history section with its own heading
- a bottom utility section with flat buttons for personality, timeline, memory, and settings

This no longer matches the desired product information architecture. The left rail should emphasize three core working areas:

- conversation
- timeline
- memory

Personality configuration should remain available from Settings, while the standalone personality button should be removed from the shell navigation.

## Goals

1. Redesign the left sidebar so `对话`, `时间线`, `记忆`, and `设置` are the only primary navigation items.
2. Make `对话` a first-class button matching the other primary actions while still expanding to show chat history.
3. Make `记忆` an expandable navigation group with a summary entry plus five dedicated memory layer destinations.
4. Preserve the current Settings dialog behavior.
5. Lay the groundwork for a future memory redesign by splitting memory into independent pages instead of one tabbed page.

## Approved UX Decisions

### Primary navigation

The sidebar will expose these top-level items in order:

1. `对话`
2. `时间线`
3. `记忆`
4. `设置`

### Conversation behavior

`对话` becomes a primary button with the same visual language as the other main items.

Approved interaction:

- clicking the `对话` button toggles an inline expansion area
- the `+` new-session icon remains on the right side of the `对话` row
- the expansion area contains only conversation history items
- switching personality is not shown inside the conversation area in order to preserve focus and immersion

### Personality placement

The standalone sidebar personality entry is removed.

Personality remains available only through Settings:

- no personality primary nav item in the sidebar
- personality configuration stays in the Settings surface

### Memory behavior

`记忆` becomes a primary button that expands into second-level destinations.

Approved secondary entries:

1. `总览`
2. `工作台记忆`
3. `事件记忆`
4. `知识记忆`
5. `摘要反思记忆`
6. `工具技能记忆`

Each secondary entry navigates the main content area to its own dedicated page.

### Memory page architecture

The current single tabbed memory page will be replaced with a small memory section made of separate routes and separate page components:

- one overview page
- five layer-specific pages

The overview page will initially provide reserved structure for:

- top search area
- statistics panel area
- placeholder body area for future detail design

Each memory layer page should expose its own filter area so the UI can diverge by layer over time without being constrained by a shared tab container.

### Timeline and settings behavior

- `时间线` remains a direct primary navigation item
- `设置` continues to open the existing centered settings dialog

## Architecture Direction

### Sidebar

The sidebar should move from a two-zone layout to a single stacked navigation system with two item types:

- direct nav items
- expandable nav groups

This keeps the hierarchy visible while making conversation and memory behave consistently as structured sections.

### Routing

The shell router should support dedicated memory routes instead of one shared `/events` page. A nested or namespaced route family under a memory prefix is preferred so active-state logic stays readable.

Example route shape:

- `/chat`
- `/timeline`
- `/memory/overview`
- `/memory/l0`
- `/memory/l1`
- `/memory/l2`
- `/memory/l3`
- `/memory/l4`
- `/settings`

Exact path names may be adjusted during implementation, but the final route map should preserve one page per memory destination.

### State model

The shell active panel state should be simplified around the new top-level sections:

- `conversation`
- `timeline`
- `memory`
- `settings`
- `none`

Expanded state for `对话` and `记忆` should be tracked separately from route selection so the UI can keep sections open while navigating within them.

## Testing Expectations

The implementation should include validation for:

- sidebar rendering of the new primary items
- expanding and collapsing `对话`
- expanding and collapsing `记忆`
- navigation to timeline
- opening settings without regression
- navigation to each memory destination
- direct routing into each memory page with correct active highlighting

## Non-Goals

- fully designing the final memory overview content in this task
- fully redesigning each memory layer page beyond scaffold, filters, and route separation
- changing the centered settings dialog interaction model

## Risks And Mitigations

### Risk: active state confusion between route and expansion

Mitigation:

- keep route-based active state separate from expansion state
- highlight the active primary section and the active secondary memory item independently

### Risk: large memory-page refactor breaks existing functionality

Mitigation:

- reuse existing memory data hooks where practical
- migrate layer content incrementally into dedicated page components
- keep overview intentionally lightweight for this iteration

### Risk: route regressions in shell overlays

Mitigation:

- preserve existing settings overlay path handling
- update pathname-to-panel helpers and sidebar tests together
