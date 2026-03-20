# Sidebar Polish Design

## Context

The desktop shell sidebar is already functionally complete:

- top-level navigation is stable
- conversation history can be searched and managed
- memory destinations are available as second-level entries
- settings remains a distinct primary action

The remaining issue is presentation quality rather than structure. The sidebar currently applies a very similar surface treatment to:

- top-level navigation buttons
- inline search tools
- conversation rows
- memory rows
- footer settings

That visual sameness makes hierarchy feel flatter than intended. The left rail works, but it does not yet read as a polished, professional shell.

## Goals

1. Refine the sidebar toward a quieter, more professional desktop-workbench feel.
2. Preserve the current information architecture and interaction model.
3. Make first-level navigation feel distinct from second-level rows without adding visual noise.
4. Reduce competition between utility controls and primary navigation.
5. Improve hover, focus, active, and overflow affordances so the sidebar feels deliberate in daily use.

## Approved Direction

The approved direction is the `B. Editorial Rail` concept from the design comparison.

This direction keeps the current warm desktop tone, but introduces clearer hierarchy through restraint:

- lighter top-level button surfaces
- a subtle left-side visual rail for expanded groups
- secondary rows that feel nested instead of button-equivalent
- lower visual weight for search and utility controls
- more intentional spacing rhythm between primary sections, nested content, and the footer

## UX Decisions

### Information architecture

No structural changes are in scope:

- keep the same top-level items
- keep the same expand/collapse behavior
- keep the same search and new-session actions
- keep the same session overflow menu behavior
- keep the same memory destination list

This is a polish task, not a navigation redesign.

### Primary navigation styling

Primary navigation should remain full-width and easily scannable, but its styling should become more restrained:

- active primary items should use a soft tinted background and cleaner border treatment
- inactive primary items should read more like anchored labels than large cards
- icon containers should stay present, but they should support hierarchy rather than dominate it
- chevrons should remain visible while becoming less visually loud

### Expanded group styling

Expanded conversation and memory content should read as nested content within the active section:

- introduce a subtle vertical rail or guide on the left side of the expanded area
- secondary rows should become lighter and flatter than the primary rows
- active secondary rows should be expressed through the rail, tint, and text emphasis rather than a large filled pill
- group spacing should create a clear parent-child relationship

### Tool row styling

The conversation search field and icon-only tool buttons should be visually quieter than the main navigation:

- search input should feel embedded rather than card-like
- icon tool buttons should share a common compact treatment
- hover and focus states should remain accessible without drawing more attention than the section title

### Session row behavior

Conversation session rows should feel cleaner and more legible during frequent use:

- current session state should remain obvious even with a lighter visual language
- unread counts should stay discoverable without becoming the strongest accent in the row
- timestamps should be visually subordinate
- overflow actions should feel attached to the row and appear more intentionally on hover/focus
- long labels should remain stable under truncation

### Footer settings treatment

The footer settings action should stay aligned with the primary navigation language, but be separated from the main working areas through spacing and a subtle divider cue.

## Implementation Direction

The implementation should stay local to the existing sidebar component and use existing design tokens:

- prefer tuning class composition and spacing rather than introducing new component abstractions
- keep colors token-based and consistent with the existing warm light theme and dark theme support
- preserve accessibility states, including visible keyboard focus and reduced-motion-safe transitions

If repeated class strings become unwieldy during implementation, extracting small local class helpers inside `Sidebar.tsx` is preferred over introducing a broader styling system.

## Testing Expectations

The task changes presentation, but it still needs regression coverage for the shell behavior that the styling touches:

- primary navigation buttons still render and stay accessible
- conversation tools still render when the section is expanded
- conversation and memory second-level rows still appear in the correct states
- active navigation behavior continues to work for conversation, timeline, memory, and settings

Tests may assert a small number of meaningful class markers where necessary, but should avoid overfitting to every utility class.

## Non-Goals

- changing route structure
- adding or removing navigation entries
- redesigning the memory information architecture
- changing settings behavior
- introducing a collapsible shell model
- adding new animations beyond subtle state transitions

## Risks And Mitigations

### Risk: style polish accidentally weakens active-state clarity

Mitigation:

- keep active text contrast and selection tint clearly stronger than inactive rows
- retain `aria-current` behavior and focused keyboard states in tests

### Risk: utility controls still compete with navigation

Mitigation:

- reduce tool button weight relative to primary items
- unify tool sizing and surface treatment so they read as support actions

### Risk: class-level refinements become brittle in tests

Mitigation:

- only assert a few stable class indicators tied to hierarchy or accessibility
- keep the rest of validation focused on rendered behavior and navigation outcomes
