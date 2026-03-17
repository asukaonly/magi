# Product Configuration Guide

## Purpose

This document describes the main product-facing configuration surfaces in Magi.

It is intended for:

- new contributors working on onboarding, settings, or configuration UX
- open source users who want to understand what the product can configure today
- maintainers who need one place to review the expected behavior of language, model, memory, and tool settings

## Configuration Areas

Magi currently exposes these major configuration areas:

- language and localization
- onboarding flow
- LLM provider and model settings
- AI personality and tone
- memory system
- tool management
- plugin and extension management
- timeline source management
- outbound action management
- settings page structure

These areas are closely related. Onboarding determines the first-run experience, while the settings page is the long-term place where users revisit the same configuration families.

## Language And Localization

Magi currently supports:

- Simplified Chinese
- English

Expected behavior:

- users can switch language at any time
- language preference is persisted
- the application re-renders in the chosen language
- onboarding and settings must remain language-aware

Implementation notes:

- new user-facing UI copy should continue to use i18n keys rather than hardcoded text
- `zh-CN` and `en` resources should stay aligned
- language changes should keep local state, persisted preference, and document language in sync

## Onboarding Flow

The onboarding flow is the first-run configuration experience.

Current design expectations:

- if onboarding is incomplete, the application routes the user into onboarding
- if onboarding is already complete, the user enters the main application
- onboarding uses a dedicated layout rather than the main application shell
- partially completed onboarding progress should survive refreshes or temporary exits

The onboarding flow distinguishes two modes:

- quick mode
  Focus on essential setup only

- expert mode
  Expose the full configuration surface

### Quick Mode

Quick mode is intended to reduce friction for first-time users.

It should focus on:

- language
- LLM configuration
- AI personality

### Expert Mode

Expert mode exposes the full configuration path, including:

- language
- LLM configuration
- AI personality
- memory configuration
- tool configuration

## Settings Page

The settings page is the persistent configuration home after onboarding.

It should provide a stable place where users can revisit and update:

- preferences
- LLM settings
- personality settings
- memory settings
- timeline settings
- extension settings
- tool settings
- action settings
- relevant system/runtime settings

Expected behavior:

- settings are grouped by category
- changes are validated before save
- save success and validation errors are visible to the user
- language switching remains available from settings

## LLM Configuration

The LLM configuration layer defines how Magi talks to language models.

Current product expectations:

- multiple providers can be selected
- model name is configurable
- API credentials are stored safely
- custom base URLs are supported where applicable
- expert-facing configuration can expose more fields than quick mode
- provider/model metadata should come from the backend registry rather than hardcoded frontend lists
- each selected model can expose a capability profile such as vision, reasoning, tool calling, and embedding support
- users can review the active model capability profile during onboarding and later in settings
- advanced users can override capability flags, model limits, and provider-specific JSON options for the current model

At a minimum, the product should support:

- provider selection
- model selection
- API key input
- optional custom endpoint configuration
- model capability summary
- advanced capability override controls for the currently selected model

The exact provider list may evolve, but the product architecture should keep provider configuration extensible rather than hardcoding one vendor path.

## AI Personality

Magi supports configurable assistant personality behavior.

There are two main ways to express personality:

- preset personalities
- custom personality prompt input

The product should also support a configurable tone layer, such as:

- casual
- formal

Design expectations:

- presets should be loaded from the backend rather than hardcoded into the frontend
- personality content should remain language-aware
- quick mode should stay simpler than expert mode

## Memory System

Magi now exposes a lifecycle-based memory system instead of the older feature-stacked memory layer framing.

The current conceptual model is:

- `L0`: working context
  Short-lived runtime state kept in memory with checkpoint recovery

- `L1`: event memory
  Long-term normalized source events and the factual base for later recall

- `L2`: structured cognition
  Entities, relationships, and defensive ToM assertions derived from L1

- `L3`: reflection memory
  Summaries and distilled insights generated from retained event streams

- `L4`: procedural memory
  Reusable strategies, execution heuristics, and learned failure avoidance

Product expectations:

- users can understand the lifecycle of memory at a high level
- advanced memory configuration remains expert-oriented
- quick onboarding should not force detailed memory tuning
- settings should expose the main lifecycle toggles and key pipeline switches

The current settings surface should support at least:

- enable or disable `L0` through `L4`
- configure L0 checkpoint interval
- configure L1 retention window
- enable or disable T1 importance scoring
- enable or disable L2 LLM extraction
- enable or disable L3 LLM reflection
- enable or disable L4 procedural skill extraction
- expose whether short-lived L0-only runtime events participate in replay

Important behavioral rules:

- `L1` is the long-term foundation
- `L2`, `L3`, and `L4` depend on `L1`
- runtime telemetry should not be treated as equivalent to user-authored memory
- expert memory controls belong in Settings and expert onboarding, not quick onboarding

Current storage implementation notes:

- `message_queue.db` is reserved for message bus queue persistence, not long-term L1 memory.
- L1 is stored in `memories/l1_events.db`.
- L0/L2/L3/L4 are consolidated into `memories/memory.db` (multi-table layout).
- Layer vectors are stored per layer (`L1/L3/L4` vector tables) instead of a shared `embeddings.db`.
- `scenario_prompts.db` and `llm_usage.db` are runtime/system databases under `~/.magi/data/`, not memory-layer databases.

## Tool And Extension Management

Tool management covers:

- builtin tools
- provider-backed tools
- external skills
- plugin-contributed tools
- plugin package lifecycle

Expected product behavior:

- users can inspect discovered plugin packages in a dedicated Extensions area
- users can enable, disable, reload, and rescan plugin packages
- plugin-provided settings are rendered from backend field metadata rather than custom plugin frontend code
- tool surfaces should continue to reflect runtime-registered tools rather than hardcoded frontend lists

Tool-specific expectations:

- users can enable or disable supported builtin or plugin-provided tools
- tool-specific configuration is shown only when relevant
- external skills are discoverable from the backend rather than hardcoded
- expert mode exposes more of this surface than quick mode

The exact tool list may change over time, but the product should preserve these principles:

- clear enable/disable state
- explicit provider configuration where required
- separation between builtin tools and externally loaded skills

## Timeline Source Management

Timeline source management is now plugin-backed.

Expected product behavior:

- the Timeline settings surface should render sources from backend-registered timeline sensors
- the frontend should not assume a fixed source list when the backend can provide dynamic sensor contributions
- top-level timeline domain controls may remain in root config
- per-source behavior such as sync mode, retention, and source-specific fields should be persisted through plugin settings

This split is intentional:

- global timeline state belongs to the product domain
- source-specific runtime settings belong to the owning sensor contribution

Timeline sync behavior is now backed by the unified scheduler runtime.

Expected product behavior:

- manual sync should enqueue a one-shot scheduler job for the selected source
- interval sync should register a recurring schedule when the source is enabled
- watch mode may be offered as a source capability, but a source without native watch support may fall back to interval semantics
- timeline source status may expose scheduler-backed state such as last sync, next run, and last error

## Action Management

Magi now exposes outbound actions as a distinct product surface.

Expected product behavior:

- actions should appear as a dedicated settings category
- action settings should be rendered from backend metadata
- actions remain conceptually distinct from tools even when a tool adapter exists
- dangerous or permission-requiring actions should surface that metadata clearly to the user

Action execution may also be scheduled by the backend runtime for delayed or recurring delivery, even when the product does not yet expose a full task-center UI.

## Cross-Cutting Product Rules

These rules apply across onboarding and settings:

- quick mode should optimize for speed and low cognitive load
- expert mode should optimize for clarity and control
- configuration should be language-aware
- configuration changes should be persisted
- validation should happen before save
- advanced features should not be forced on new users too early

## Relationship To Runtime Docs

This document is product-facing.

For internal runtime implementation details, read:

- [Task-Agent Runtime Architecture](/Users/asuka/code/magi/docs/task-agent-runtime-architecture.md)

For unified extension loading, plugin-backed sensors, and action/tool registration, read:

- [Unified Plugin Extension Architecture](/Users/asuka/code/magi/docs/plugin-extension-architecture.md)
- [Plugin Development Guide](/Users/asuka/code/magi/docs/plugin-development-guide.md)

For a high-level repository and architecture introduction, read:

- [Project Overview](/Users/asuka/code/magi/docs/project-overview.md)
