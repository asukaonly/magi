# Scenario LLM Pool Design

## Goal

Replace the current single active LLM configuration with a scenario-based model selection system backed by a reusable provider pool.

The first product scope covers:

- a reusable LLM provider pool under `LLM`
- two scenario model selections:
  - `context_decider`
  - `core`
- a global runtime `ScenarioLLMPool` that resolves adapters by scenario
- onboarding and settings updates that separate model selection from provider configuration

This design intentionally does not preserve backward compatibility with the current `llm.provider + llm.model + llm.api_key` shape. The project is still in active development, so the old structure should be replaced rather than carried forward with compatibility code.

## Product Context

The current implementation binds provider credentials and active model selection together:

- one global provider
- one global model
- one API key
- one base URL

That structure blocks several product needs:

- fast and slow model splits
- routing-specific model choices
- future multimodal or planner-specific slots
- multiple enabled providers at once

The product configuration guide already expects LLM configuration to support multiple providers and model metadata from a backend registry. This design aligns the implementation with that product direction while keeping the first version intentionally small.

## User-Facing Outcome

Under the `LLM` settings category, users see two distinct sections:

1. `Model Selection`
   Users choose which enabled provider instance and model power each scenario.

2. `Provider Configuration`
   Users manage reusable provider connections, credentials, and endpoints.

The first version exposes two scenario slots:

- `Context Decider`
- `Core LLM`

Multimodal is not a separate slot yet. Image input continues to use the `Core LLM` selection. If the selected core model does not support vision, the UI shows a clear warning and runtime image requests fail with a clear configuration message.

## Configuration Model

## Top-Level Shape

The current `llm` config should be replaced with this shape:

```yaml
llm:
  providers:
    openai:
      enabled: true
      provider_type: openai
      display_name: OpenAI
      api_key: sk-...
      base_url: https://api.openai.com/v1

    anthropic:
      enabled: true
      provider_type: anthropic
      display_name: Anthropic
      api_key: sk-ant-...
      base_url: https://api.anthropic.com/v1

    custom_proxy_01:
      enabled: true
      provider_type: custom
      display_name: My OpenAI Proxy
      api_format: openai
      api_key: sk-...
      base_url: https://proxy.example.com/v1

  selections:
    context_decider:
      provider_id: openai
      model: gpt-5-mini
      capability_override_enabled: false
      capabilities:
        vision: false
        image_output: false
        tool_calling: true
        reasoning: true
        embedding: false
      limits:
        context_window: 200000
        max_output_tokens: 100000
      provider_options: {}

    core:
      provider_id: anthropic
      model: claude-sonnet-4-6
      capability_override_enabled: false
      capabilities:
        vision: true
        image_output: false
        tool_calling: true
        reasoning: true
        embedding: false
      limits:
        context_window: 200000
        max_output_tokens: 64000
      provider_options: {}
```

## Provider Pool Rules

Provider pool entries represent reusable connections.

Each provider entry owns:

- `enabled`
- `provider_type`
- `display_name`
- `api_key`
- `base_url`
- `api_format` for custom providers when needed
- optional provider-specific metadata needed to build adapters later

Rules:

- built-in providers are globally unique by provider type
- custom providers use independent generated ids
- custom providers are not deduplicated against built-in provider types
- a disabled provider cannot be referenced by any scenario selection
- credentials are stored once at the provider level, never duplicated into scenario slots

## Scenario Selection Rules

Scenario selections represent model choices for runtime responsibilities.

The first version includes:

- `context_decider`
- `core`

Each selection owns:

- `provider_id`
- `model`
- `capability_override_enabled`
- `capabilities`
- `limits`
- `provider_options`

Rules:

- every required scenario must be configured
- each selection must point to an enabled provider
- each selected model must belong to the referenced provider's model registry
- capability overrides stay attached to the scenario selection, not the provider

This keeps connection concerns and model-behavior concerns separate.

## Registry Semantics

The provider registry remains the source of truth for built-in metadata:

- provider display metadata
- model lists
- default models
- default base URLs
- capability profiles
- provider options examples

Registry-driven metadata should continue to power both onboarding and settings rather than hardcoded frontend lists.

For built-in providers, the settings list should preview available models directly in the left column so users can understand a provider's range before opening details.

For custom providers, the first version may keep model handling simple:

- users can enter a model name manually, or
- the backend can optionally surface endpoint-discovered models later

The first version does not require endpoint discovery.

## Runtime Architecture

## Scenario Enum

Introduce a central runtime enum for scenario-based LLM resolution.

Initial scenarios:

- `CONTEXT_DECIDER`
- `CORE`

Expected future scenarios:

- `MULTIMODAL`
- `PLANNER`
- `TITLE_GENERATION`
- `MEMORY_SUMMARY`

The enum becomes the shared contract across configuration, runtime wiring, and internal services.

## ScenarioLLMPool

Introduce a global `ScenarioLLMPool` service.

Responsibilities:

- resolve scenario selections to provider entries
- validate that a scenario points to an enabled provider
- validate that a selected model belongs to the provider
- build adapters from provider credentials plus scenario model selection
- cache adapters for reuse within the process
- invalidate and rebuild adapters after config changes
- expose scenario profile metadata for runtime logging and API consumers if needed

This pool becomes the only runtime entry point for obtaining an LLM adapter by business scenario.

Expected usage:

```python
llm_pool.get(LLMScenario.CONTEXT_DECIDER)
llm_pool.get(LLMScenario.CORE)
```

## Why A Pool Instead Of Per-Service Adapters

A global pool avoids scattering configuration resolution across unrelated services.

Benefits:

- services no longer know how provider config is stored
- adapter creation logic is centralized
- future scenario additions only need enum + selection config + usage site
- cache invalidation happens in one place
- product terminology and runtime terminology stay aligned

## Runtime Wiring

The runtime should no longer treat one adapter as the global active LLM.

Instead:

- bootstrap creates one shared `ScenarioLLMPool`
- task agents and related services receive the pool or scenario-resolved adapter accessor
- services request adapters by scenario

Initial usage mapping:

- `ContextDecider` uses `CONTEXT_DECIDER`
- `ChatPromptService` uses `CORE`
- `DirectLLMHandler` uses `CORE`
- `FunctionCallingExecutor` uses `CORE`
- chat and explore planning or aggregation services that currently depend on the same global LLM also use `CORE` in the first version

This keeps the first rollout small while establishing the extension point for later scenario splits.

## Adapter Factory Changes

The adapter factory should move from:

- create adapter from one global `app_config.llm`

to:

- create adapter from `provider config + scenario selection`

That means the factory boundary must accept:

- provider type
- API key
- base URL
- model
- provider options or scenario overrides where required

The factory should not read scenario or provider config directly from global state. Resolution belongs to `ScenarioLLMPool`.

## API Model Changes

## Config API

`/api/config` should expose and persist the new `llm` structure directly.

Required updates:

- replace the old single `LLMConfigModel`
- introduce provider pool response models
- introduce scenario selection response models
- update template and onboarding-template generation to build the new shape
- update validation to ensure all required selections are valid

The API should not dual-write or support the old format.

## Validation Rules

Saving config should fail when:

- `context_decider` or `core` is missing
- a selection references a provider that does not exist
- a selection references a provider that is disabled
- a built-in provider type is duplicated
- a built-in selection uses a model outside that provider's registry

Saving config should succeed with warnings when:

- the `core` model does not support `vision`

That warning is product-facing, not a persistence blocker.

## Settings UX

## Section Structure

The `LLM` settings page should be split into two stacked sections:

1. `Model Selection`
2. `Provider Configuration`

This order is intentional.

Users first see the active business choices, then the reusable connection details underneath.

## Model Selection UX

The `Model Selection` section uses one card per scenario.

Initial cards:

- `Context Decider`
- `Core LLM`

Each card shows:

- scenario title and short description
- selected provider
- selected model
- capability chips
- warning state if relevant
- a `Change` action

Interaction model:

- clicking `Change` expands the card inline
- expanded mode shows:
  - provider select, restricted to enabled providers
  - model select, populated from the chosen provider
- the card collapses back into summary mode after selection or explicit close

Inline editing is preferred over a separate drawer because there are only two first-version scenario slots and the page should feel direct and scannable.

## Provider Configuration UX

The provider section uses a left list plus right detail panel.

Left column:

- searchable provider list
- built-in providers shown as one entry per provider type
- custom providers shown as separate entries by id
- active/inactive state
- scenario usage references such as `Used by Context Decider`
- built-in provider model chips directly under each entry

Right detail panel:

- enable toggle
- API key
- base URL
- custom-only fields such as `api_format`
- usage references
- guardrail copy explaining uniqueness rules where helpful
- optional read-only model preview

The actual model choice still belongs in the scenario cards, not in provider details.

## Save-Time Interaction

If a user disables a provider that is still referenced:

- save is blocked
- the provider detail panel shows the referencing scenarios
- each affected scenario card shows an error state

If the selected `core` model lacks vision:

- the scenario card shows a warning before save
- save remains allowed

## Onboarding UX

Onboarding should adopt the same information architecture as settings to avoid forcing users to relearn the structure after first run.

Quick mode:

- keep one LLM step
- within that step show:
  - provider configuration
  - model selection
- reduce advanced text and hide scenario override controls

Expert mode:

- same structure
- expose advanced capability overrides and provider options per scenario

The quick-mode and settings experiences should differ in density, not in mental model.

## Error Handling

## Product-Level Errors

User-facing errors should be clear and scenario-specific.

Examples:

- `Core LLM is not configured`
- `Context Decider references a disabled provider`
- `OpenAI provider is enabled but API key is missing`
- `Current Core LLM does not support image input`

The product should not silently fall back to another provider or model.

## Runtime Errors

`ScenarioLLMPool.get(scenario)` should raise a clear configuration error when:

- the scenario is missing
- the provider is missing
- the provider is disabled
- the provider credentials are incomplete
- the model is invalid for that provider

Business services should not reimplement that validation logic. They should either:

- allow the error to surface through a typed configuration failure path, or
- convert it into a user-facing message where appropriate

## Image Input Behavior

First-version multimodal behavior:

- image requests continue to use `CORE`
- if `CORE` does not have `vision`, image handling fails clearly

There is no automatic fallback to another provider and no hidden scenario remapping in version one.

## Testing Strategy

## Backend

Add coverage for:

- provider pool config models
- built-in provider uniqueness validation
- scenario selection validation
- config router serialization and persistence for the new shape
- `ScenarioLLMPool` resolution and cache invalidation
- adapter factory behavior when different scenarios point to different providers

Key regression targets:

- `ContextDecider` resolves the scenario pool instead of a global adapter
- core chat execution uses the `CORE` scenario
- invalid references fail early and clearly

## Frontend

Add coverage for:

- provider list rendering with built-in model chips
- inline scenario card editing
- provider list filtered to enabled providers during scenario selection
- model dropdown updates when provider changes
- `Core LLM` warning when selected model lacks vision
- save blocked when disabling a referenced provider
- onboarding quick and expert LLM step rendering with the new two-section structure

## Manual Verification

Manual verification should include:

1. enable two built-in providers with distinct credentials
2. assign `context_decider` and `core` to different providers
3. save config and confirm backend reloads correctly
4. send a normal chat message and confirm the core scenario is used
5. send an image message with a non-vision core model and confirm the user gets a clear warning
6. disable a referenced provider and confirm save is blocked until the scenario is repointed

## Out Of Scope

The following are intentionally excluded from this first design:

- backward compatibility with the old single-LLM config
- automatic provider fallback
- automatic multimodal rerouting
- dynamic custom endpoint model discovery as a required feature
- adding more scenario slots beyond `context_decider` and `core`

Those can build naturally on top of the scenario-based structure later.

## Implementation Notes

The safest rollout order is:

1. define new config models and config API payloads
2. add `ScenarioLLMPool` and adapter factory changes
3. rewire runtime consumers to use scenario lookups
4. update frontend API types and LLM settings/onboarding UI
5. add validation and regression tests across backend and frontend

This sequence establishes the new source of truth before UI and runtime are fully switched over.
