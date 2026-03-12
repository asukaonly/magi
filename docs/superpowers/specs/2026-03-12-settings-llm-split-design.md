# Settings LLM Split Design

## Context

The current settings page exposes all LLM controls under a single `LLM` navigation item and renders provider configuration plus model selection together in one content surface. This creates two problems:

- the information architecture is too dense for a long-term settings page
- the LLM sections still feel visually similar to onboarding, with oversized cards, decorative surfaces, and spacing that does not match the calmer settings shell

## Goals

- Rename the `LLM` settings area to `大模型配置` / `Model Configuration`
- Keep it as a grouped section in the left settings navigation
- Expand that group into two child entries:
  - `供应商配置` / `Provider Configuration`
  - `模型选择` / `Model Selection`
- Add a clearer top content header area with visible spacing before the section title
- Simplify both pages so they read like system settings, not onboarding cards

## Navigation Design

### Left navigation

The left settings navigation should keep the existing top-level structure, but the old `LLM` item becomes an expandable group.

- Parent label: `大模型配置`
- Child items:
  - `供应商配置`
  - `模型选择`

The parent group should stay visually aligned with the other settings items, but the active child should determine the content pane title and body.

## Content Header

The right content area should add a dedicated header strip with larger top spacing and a simpler title treatment, similar to the existing `偏好` page reference:

- more breathing room above the title
- no heavy hero card styling
- clear divider between header and body

## Provider Configuration Page

Keep the existing two-column structure:

- left: provider list
- right: provider detail

But simplify the visual language:

- tighter typography
- smaller vertical gaps
- no oversized decorative backgrounds
- no card-like gradients
- right pane should sit below the page header with enough top margin to feel anchored

## Model Selection Page

Model selection becomes its own settings page instead of sharing the provider page.

It should:

- use the same calmer settings layout as the provider page
- present each scenario in a flatter row or compact section
- avoid onboarding-like emphasis and decorative badges
- preserve the current capability warning behavior, but render it in a restrained settings style

## Behavioral Constraints

- No API changes
- No change to onboarding flow structure
- Existing LLM data model and save behavior remain intact
- The settings page still edits the same `draftConfig.llm` object

## Validation

- Settings navigation tests should cover the new grouped LLM section
- Existing LLM form tests should still cover provider test actions and model selection interactions
- Type-check and focused frontend tests must pass
