# Settings Statistics Redesign Design

## Goal

Redesign the settings statistics experience into a lightweight, polished two-submenu analytics center that separates historical LLM usage analysis from live system runtime status, while staying aligned with Magi's existing settings shell and avoiding dense dashboard-style card grids.

## Context

The current settings surface exposes a single `usage` leaf that renders an older LLM usage panel. That panel already has working data sources for token usage trends, but it is structurally narrow and visually too close to a generic dashboard. The new design should fit the current settings navigation model, stay inside Settings instead of the main shell, and reflect the product/runtime split described in:

- `docs/project-overview.md`
- `docs/product-configuration-guide.md`
- `docs/task-agent-runtime-architecture.md`

This redesign should treat runtime observability as a dedicated product-facing surface backed by real runtime data, not placeholder agent metrics.

## User-Approved Decisions

### Placement

- The statistics entry lives under `Settings`.
- It must not appear as a top-level main workspace route in the shell.

### Navigation

- Replace the current single statistics leaf with a parent settings node:
  - `Statistics`
- The parent expands into two submenus:
  - `LLM Statistics`
  - `System Runtime`

### Interaction Depth

- The first version targets “overview + lightweight drill-down”.
- It should support time window switching, model/provider/request-kind slicing, and concise health summaries.
- It should not become a heavy operations console.

### Visual Direction

- Use the approved `A1` “editorial data page” direction.
- Avoid a screen full of boxed cards or repeated metric tiles.
- Reduce “AI dashboard” feel by relying more on:
  - information ribbons
  - section rhythm
  - dividing lines
  - selective emphasis
  - whitespace
- Remove repeated page titles and descriptive copy inside the content area when that information is already obvious from settings navigation context.

## Information Architecture

## Settings Navigation

- `Preferences`
- `LLM`
- `Personality`
- `Memory`
- `Extensions`
- `Timeline`
- `Actions`
- `Tools`
- `Statistics`
  - `LLM Statistics`
  - `System Runtime`

The active content header should remain consistent with the existing settings shell, but the body of the page should start directly with the toolbar and analytics content instead of a repeated local page hero.

## Page Framework

Both statistics pages share one lightweight analytics frame:

1. Top utility bar
2. Signal ribbon
3. Primary analytical canvas
4. Secondary analytical blocks
5. Right-side health summary rail

This shared frame keeps the two pages visually related while letting each one emphasize a different type of decision-making.

## Page Design

### LLM Statistics

#### Purpose

Help users inspect historical model usage and answer:

- how much usage happened recently
- where token and cost growth came from
- whether latency or TTFT worsened
- which models/providers/request kinds changed most

#### Layout

##### Top utility bar

Lightweight controls only:

- `7 days` / `30 days`
- provider filter
- model filter
- last updated timestamp

No repeated in-page title or introductory paragraph.

##### Signal ribbon

The first row is a horizontal information ribbon rather than stacked cards:

- total tokens
- total cost
- average latency
- average TTFT
- success rate

These values should feel like a summary strip, using subtle separators and emphasis rather than bordered metric tiles.

##### Primary canvas

Main visual:

- dual-axis trend for `tokens` and `cost`

This is the visual anchor of the page and should receive the largest area.

##### Secondary analysis blocks

Below the main canvas:

- input vs output composition
- model ranking
- provider ranking
- request-kind ranking

These blocks can use restrained containers or section dividers, but should avoid becoming a four-card dashboard.

##### Health summary rail

The right rail is short and opinionated:

- model with largest volatility
- request kind with highest failure rate
- provider with fastest cost growth
- one sentence summary

This rail exists to tell the user what matters now, not to duplicate every chart.

### System Runtime

#### Purpose

Help users inspect current runtime health and answer:

- whether the local system is under pressure
- whether first-token latency is degrading
- whether intent routing and core model execution are succeeding
- whether memory processing or scheduler work is backing up

#### Layout

##### Top utility bar

- auto-refresh status indicator
- manual refresh action
- last updated timestamp

No configurable refresh cadence in the first version.

##### Signal ribbon

- CPU usage
- memory usage
- average TTFT
- intent recognition success rate
- core model success rate
- memory processing queue length

##### Primary canvas

A recent trend area combining:

- CPU
- memory
- TTFT

This should be compact and easy to scan rather than a dense monitoring graph.

##### Secondary blocks

- scheduler task status summary
- recent runtime tasks list
- queue pressure summary
- critical anomaly reminders

##### Health summary rail

- overall runtime status
- most important current bottleneck
- backlog/failure risk status

This page should feel slightly more “live” than LLM Statistics, but still remain inside the same restrained settings visual language.

## Data Design

### LLM Statistics Data

Use existing metrics foundations and extend them:

- existing summary endpoint:
  - `/api/metrics/llm/usage/summary`
- existing timeseries endpoint:
  - `/api/metrics/llm/usage/timeseries`

Add or expose these fields where available:

- cost totals and per-day cost
- TTFT aggregates
- success rate fields
- provider/model/request-kind filtering support

If a metric is not yet available from runtime traces, return explicit null or “not available” fields rather than inferred placeholder values.

### System Runtime Data

Add a dedicated aggregation endpoint:

- `/api/metrics/runtime/overview`

This endpoint should combine only trustworthy live/runtime-backed data:

- `psutil` CPU and memory metrics
- runtime queue backlog
- runtime worker readiness and heartbeat
- L2 memory pipeline backlog
- scheduler status summary
- available TTFT aggregates
- available intent/core-model success metrics

Important rule:

- do not reuse placeholder `/metrics/agents` data for this page
- do not fabricate synthetic runtime health values just to fill UI

If some observability slices are not yet fully available, the endpoint should still return a stable schema with explicit missing-data markers.

## Visual Principles

### What to avoid

- repeated page title plus repeated subtitle inside content area
- dashboard-like “card farms”
- identical metric boxes across every section
- decorative analytics chrome without informational value

### What to emphasize

- clear hierarchy
- one dominant chart area
- restrained accent color use
- subtle section separation
- higher-quality typography rhythm
- concise summaries that help users decide where to look next

## Component Design

Introduce a shared settings statistics frame component that can be reused by both pages:

- toolbar slot
- signal ribbon slot
- main content slot
- summary rail slot

Then implement two page-specific sections:

- `LLMStatisticsSection`
- `RuntimeStatisticsSection`

This keeps page composition readable and prevents the existing settings page from absorbing too much analytics-specific layout logic.

## Non-Goals

This redesign does not include:

- log explorers
- failure detail tables
- full alert center
- user-configurable refresh intervals
- deep task operations tooling
- fake “agent metrics” based on current placeholder endpoints

## Verification Requirements

### Frontend

- settings navigation shows `Statistics` as an expandable group
- `LLM Statistics` and `System Runtime` render correctly inside the current settings shell
- no repeated page hero title/content inside statistics body
- `7/30 day` switching works
- empty states are explicit and graceful

### Backend

- new runtime overview endpoint has tests for shape and no-data behavior
- LLM usage payload extensions have tests
- responses use real runtime-backed values or explicit missing-data markers

## Risks

### Incomplete observability fields

TTFT, intent success, and core-model success may not yet exist in a complete aggregated form. The backend must aggregate conservatively and return explicit unavailable states where needed.

### Layout drift from existing settings shell

The redesign should feel more refined than the current usage page, but it still needs to belong inside Settings. Over-stylizing it into a standalone dashboard would violate the approved direction.

## Implementation Strategy

Implement in small reversible tasks:

1. navigation and settings wiring
2. shared statistics frame and LLM statistics redesign
3. runtime overview backend aggregation
4. system runtime page
5. i18n and tests

Each independent task should be validated and committed immediately.
