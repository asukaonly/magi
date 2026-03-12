# LLM Onboarding Step Split Design

## Goal

Reshape the onboarding `LLM` experience into a clearer two-step flow that separates provider setup from model selection, while keeping quick mode lightweight and automatic.

The product scope for this change is:

- split onboarding `LLM` into `Provider Configuration` and `Model Selection`
- keep quick mode on provider setup only and auto-fill model selections
- add custom-provider model management and model discovery
- restructure the onboarding layout so the right side is a fixed two-zone surface:
  - scrollable content area
  - fixed footer actions

This design intentionally replaces the current behavior rather than preserving compatibility. The project is still in active development, so the old single-step `LLM` onboarding flow should be removed instead of retained behind compatibility branches.

## Product Context

The current onboarding step tries to show provider setup and model selection on one long page. That creates two product problems:

- the page grows too tall and the lower model-selection area becomes hard to reach or scroll predictably
- the visual hierarchy is weak because provider setup and model selection look like peers even though they serve different decisions

The product direction is now:

- users first make sure providers are available and correctly configured
- users only choose scenario models after providers are ready
- quick mode should not force model decisions when safe defaults already exist

## User-Facing Outcome

### Quick Mode

Quick mode keeps the onboarding sequence small:

- language
- mode selection
- provider configuration
- personality
- completion

Users only configure providers in the `LLM` area. They do not see a separate model-selection page.

When the user leaves the provider step, the system auto-fills:

- `context_decider`
- `core`

Rules:

- built-in providers use the selected provider's registry `default_model`
- custom providers use the custom provider's configured default model

If the chosen provider cannot produce a valid default model, onboarding blocks at the provider step with a clear inline error.

### Expert Mode

Expert mode expands the onboarding sequence:

- language
- mode selection
- provider configuration
- model selection
- personality
- memory
- tools
- completion

This preserves the existing expert-vs-quick split while making each LLM step focused and scannable.

## Onboarding Layout

The left-side progress rail remains visually unchanged.

The right side becomes a fixed shell with two vertical regions:

1. `Scrollable content region`
   Shows the current step form only

2. `Fixed footer region`
   Always shows `Previous` and `Next`

Behavior rules:

- the right content region owns the step scrolling
- the footer never scrolls out of view
- the overall onboarding shell remains centered in the viewport
- each onboarding step should fit this shared shell rather than redefining its own page structure

This structure applies to all onboarding steps, not just LLM, but the immediate driver is the new LLM flow.

## Provider Configuration Step

The provider step becomes the first and only LLM screen in quick mode, and the first LLM screen in expert mode.

### Visual Structure

The step is a single provider workbench:

- header with title, description, and `Add Custom Provider`
- left provider list
- right provider detail panel

The list and detail panel are displayed side by side on large screens and stacked on smaller screens.

Desktop behavior:

- left list scrolls independently if provider cards overflow
- right detail panel scrolls independently if the selected provider form is long

### Built-In Providers

Built-in providers remain registry-driven.

The list preview continues to show:

- provider name
- description
- enabled state
- available model chips

The detail panel continues to show connection fields such as:

- API key
- base URL
- available model summary

The available model list is still read-only for built-in providers.

## Custom Provider Model Handling

Custom providers now own their own model list instead of relying on manual free-text only.

### Config Shape

Each provider entry for `provider_type = custom` should support:

- `custom_models: string[]`
- `custom_default_model?: string`

These fields live in the persisted provider config so both onboarding and settings can share one source of truth.

### Custom Provider UI

The detail panel for a custom provider adds:

- editable available-model tag list
- editable default-model control
- `Fetch Models` action

Users can:

- add models manually
- remove models manually
- set which model is the default

### Model Discovery

Model discovery is an explicit button action, not an automatic fetch on URL change.

The discovery request uses the current provider draft values:

- `base_url`
- `api_key`
- `api_format`

The backend attempts to fetch model metadata from the remote endpoint.

Success behavior:

- discovered model ids replace or refresh `custom_models`
- if `custom_default_model` is empty and models are returned, set it to the first returned model

Failure behavior:

- keep the user's manually entered models
- surface a clear inline error message
- do not clear or silently mutate the existing provider draft

## Model Selection Step

The model-selection step exists only in expert mode.

It shows two scenario cards:

- `Context Decider`
- `Core LLM`

Each card allows:

- selecting one enabled provider
- selecting one model from that provider

Provider options:

- built-in provider: models come from the registry
- custom provider: models come from `custom_models`

The `core` card continues to show a warning when the selected model lacks vision support. This remains a warning only and does not block save.

## Automatic Selection Rules

Automatic model filling is needed in two places:

1. quick mode when the provider step completes
2. expert mode when entering the model-selection step for the first time

Rules:

- built-in provider -> use registry `default_model`
- custom provider -> use `custom_default_model`

For expert mode, the generated defaults act as a starting point that the user may edit on the next step.

For quick mode, the generated defaults are final unless the user changes them later in Settings.

## API Changes

The current registry API remains the source of truth for built-in provider metadata.

Add a new explicit discovery endpoint for custom-provider models:

`POST /config/llm/providers/discover-models`

Request payload:

- `provider_type`
- `base_url`
- `api_key`
- `api_format`

Response payload:

- `models: string[]`
- `default_model?: string`

The discovery API is an action endpoint and does not persist config on its own.

## Validation Rules

### Provider Step

The provider step must validate before allowing the user to continue:

- at least one provider is enabled
- built-in providers satisfy required credential rules from the registry field metadata
- custom providers have at least one available model
- custom providers have a valid default model

If quick mode is active, the step must also validate that both runtime scenarios can be auto-filled successfully before allowing navigation.

### Model Selection Step

Expert mode model selection must validate:

- each scenario points to an enabled provider
- each selected model exists in the chosen provider's available model list

## Settings Alignment

The settings page should stay aligned with the same data model:

- provider configuration uses the same provider fields
- custom providers expose the same model list and fetch button
- model selection remains a separate section from provider configuration

Unlike onboarding, settings may keep both sections on one page because it is not constrained by the same step-driven first-run flow. The important rule is that provider setup remains visually and structurally distinct from scenario model selection.

## Error Handling

The UI should produce clear product-facing errors for:

- no enabled provider
- missing custom-provider models
- missing custom-provider default model
- failed model discovery
- auto-selection failure in quick mode

Runtime image-input errors remain unchanged:

- if `core` lacks vision support and chat receives images, runtime returns a clear configuration message

## Testing Scope

Frontend coverage should include:

- quick/expert onboarding step counts and step labels
- quick mode hides model selection
- expert mode includes model selection
- fixed onboarding footer with scrollable content region
- provider workbench independent scrolling
- custom provider manual model editing
- custom provider fetch-model action
- quick-mode auto-selection using `default_model` and `custom_default_model`

Backend coverage should include:

- config serialization for `custom_models` and `custom_default_model`
- model-discovery endpoint success and failure behavior
- auto-selection helper logic for built-in and custom providers

## Non-Goals

This change does not introduce:

- automatic model fetching on every base URL edit
- backward compatibility for the old single-step onboarding flow
- new runtime scenarios beyond `context_decider` and `core`
- automatic capability inference for arbitrary custom endpoints beyond what discovery returns
