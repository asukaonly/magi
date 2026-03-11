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
- memory mode
- tool management
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
- tool settings
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

## Memory Mode

Magi uses a layered memory model.

The current conceptual model is:

- L1: raw events
- L2: relationship graph
- L3: semantic memory
- L4: summaries
- L5: capability memory

Product expectations:

- users can understand the layers at a high level
- dependencies between layers are visible
- advanced memory configuration is expert-oriented
- quick onboarding should not force users through detailed memory decisions

Important behavioral rule:

- L1 is foundational
- higher memory layers depend on it

## Tool Management

Tool management covers:

- builtin tools
- provider-backed tools
- external skills

Expected product behavior:

- users can enable or disable supported builtin tools
- tool-specific configuration is shown only when relevant
- external skills are discoverable from the backend rather than hardcoded
- expert mode exposes more of this surface than quick mode

The exact tool list may change over time, but the product should preserve these principles:

- clear enable/disable state
- explicit provider configuration where required
- separation between builtin tools and externally loaded skills

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

For a high-level repository and architecture introduction, read:

- [Project Overview](/Users/asuka/code/magi/docs/project-overview.md)
