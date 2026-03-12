# LLM Draft Actions Design

## Context

The onboarding and settings flows both edit LLM provider configuration in frontend-local draft state before the user saves the full configuration. Today, two product gaps come from that boundary:

1. users cannot quickly verify whether the current provider draft can reach the upstream API
2. personality one-line generation cannot use the unsaved draft provider/model, so onboarding can fail even when the user already typed valid credentials

The active product guidance in `docs/product-configuration-guide.md` expects provider configuration and personality setup to stay connected across onboarding and settings, while keeping backend-driven provider metadata and avoiding duplicated frontend-only vendor logic.

## Goals

- add a provider connection test action that works from both onboarding and settings without persisting config first
- allow personality generation to use an optional unsaved LLM draft override
- keep existing persisted-config behavior unchanged when no override is provided
- reuse one backend resolution path for both features

## Non-Goals

- no agent runtime involvement for provider connection tests
- no implicit config save before testing or generating
- no new compatibility path for legacy avatar or provider APIs
- no UI redesign outside the small control/status additions needed for these actions

## Proposed Architecture

### Backend

Add a lightweight draft-aware LLM execution path:

- introduce a config router endpoint for provider testing, receiving one provider draft plus the model to probe
- build a temporary adapter from request payload and send a plain `hi` prompt through `LLMProviderBridge.chat(...)`
- extend personality generation request payload with optional `llm_override`
- centralize temporary LLM resolution in a shared helper so provider testing and personality generation both use the same validation and adapter construction logic

This keeps provider-specific branching inside backend LLM/config layers instead of duplicating it in the frontend.

### Frontend

- add a `Test Connection` button in the provider detail pane for the active provider
- send the current draft provider fields and a resolved probe model to the backend test endpoint
- surface loading, success, and error feedback inline in the provider pane
- when onboarding personality generation runs, include the current `llm` form draft as `llm_override`
- settings personality generation can keep existing behavior for now, because settings already has persisted config available

## Data Flow

### Provider Test

1. user edits provider fields in onboarding or settings
2. user clicks `Test Connection`
3. frontend sends current draft provider payload plus probe model
4. backend validates the provider payload, creates a temporary adapter, and calls provider bridge with a single user message `hi`
5. backend returns latency, selected model, and a short response preview
6. frontend shows inline result state

### Personality Generation With Draft Override

1. user configures provider/model in onboarding but has not saved yet
2. user goes to personality one-line generation
3. frontend includes current `llm` form value in the generate request
4. backend resolves the effective LLM config from request override first, falling back to persisted config
5. generation uses the resolved core scenario provider/model

## API Changes

### New config endpoint

`POST /api/config/llm-providers/test`

Request:

- `provider_id`
- `provider` draft config
- `model`

Response:

- `success`
- `message`
- `data.model`
- `data.latency_ms`
- `data.preview`

### Personality generation request extension

Existing `POST /api/personality/generate` request gains:

- optional `llm_override`

If omitted, backend uses current persisted config exactly as before.

## Error Handling

- missing API key or missing model should return explicit 400 errors
- upstream auth/network/provider errors should surface readable error messages back to the UI
- personality generation should fail fast when override exists but does not resolve to a valid enabled core provider/model

## Testing Strategy

### Backend

- test provider test endpoint with temporary provider payload and mocked bridge call
- test personality generation prefers `llm_override` over saved config
- test invalid draft payloads return 400-level failures

### Frontend

- test provider pane renders and triggers `Test Connection`
- test request payload uses current draft values rather than persisted config
- test onboarding personality generation sends `llm_override`

## Risks

- provider/model resolution logic can drift if duplicated; shared helper avoids this
- inline test feedback can become noisy if global toasts are overused; prefer local status in the provider pane
- anthropic/openai-compatible payload differences must remain backend-only
