# Memory Page Shell Redesign

## Context

The current memory pages share a heavy presentation-first frame:

- a large hero banner at the top of every page
- oversized page titles
- decorative gradients and soft ornaments
- repeated page sections that make different memory surfaces feel too similar

This creates two problems:

1. The pages look visually overdesigned in a way that reads as generic AI-generated UI rather than a deliberate product surface.
2. The shared structure suppresses the fact that overview, workbench, events, knowledge, reflection, and skills have different information priorities and should not be forced into the same reading order.

## Goals

1. Remove the large top hero from all memory pages.
2. Replace the current shared memory frame with a much thinner page base.
3. Preserve a unified product feel through restrained component styling rather than a repeated hero template.
4. Give each memory page independent first-screen structure based on its own domain.
5. Keep the redesign compatible with the existing route split:
   - overview
   - workbench
   - events
   - knowledge
   - reflection
   - skills

## Approved Design Direction

The approved overall direction is the "quiet workbench" approach:

- practical and product-like rather than showcase-like
- compact title treatment
- filters and primary data surfaced early
- restrained card styling
- no decorative hero banner

## Visual Rules

### Remove AI-looking presentation patterns

The redesign should explicitly avoid:

- oversized headline typography used mainly for visual drama
- large gradient hero backgrounds
- ornamental glow or floating accent shapes
- repeated summary-card walls that delay access to real content

### Preferred UI qualities

- calm and readable
- tidy spacing and alignment
- clear hierarchy through layout, not spectacle
- soft but restrained surfaces
- enough warmth to avoid looking cold, without looking ornamental

## Shared Base Versus Page Ownership

### Shared base responsibilities

The shared layer should only provide:

- page width and scrolling behavior
- consistent outer spacing
- a lightweight title row
- common action placement
- base card/input/select/button language
- responsive behavior for narrow layouts

### Things the shared base must not force

The shared layer must no longer impose:

- a top hero
- eyebrow labels
- hero stats
- hero aside content
- a fixed "filters then summary then content" composition
- repeated metric-card strips across every page

## Page-Level First-Screen Structures

### Overview

Overview acts as the section entry point.

First screen should emphasize:

- cross-layer search
- a compact set of useful summary signals
- layer entry points
- recent changes or recent signals

### Workbench

Workbench is an operational surface.

First screen should emphasize:

- filters
- session list
- currently selected session detail

### Events

Events is a feed-oriented surface.

First screen should emphasize:

- source/time/query filters
- event stream
- selected-event detail or inline detail affordance

### Knowledge

Knowledge is a structured cognition surface.

First screen should emphasize:

- entity or type filters
- the most important knowledge structure first
- supporting relation/assertion modules after the core focus

### Reflection

Reflection is a reading and synthesis surface.

First screen should emphasize:

- time/topic filters
- summary cards or reflection stream

### Skills

Skills is a capability inventory surface.

First screen should emphasize:

- status/category filters
- skill list
- operational state details

## Architecture Direction

`MemoryPageFrame` should be reduced into a layout primitive instead of a page template.

Likely responsibilities after refactor:

- outer container
- title row component or slot
- optional actions area
- base surface utilities

Each page component should own its own summary blocks and first-screen composition.

## Testing Expectations

Validation should cover:

- memory pages no longer rendering the shared hero test marker
- overview and at least one layer page using the new compact shell
- routes still rendering the correct pages
- existing memory navigation tests staying green

## Non-Goals

- fully redesigning the internal content of every memory submodule
- changing the memory route map
- redesigning the left sidebar again in this task
