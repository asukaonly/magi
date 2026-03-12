# LLM Onboarding Step Split Implementation Plan

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Split onboarding LLM setup into provider configuration and model selection, add custom-provider model management and discovery, and fix the onboarding shell so the right side has a scrollable content region with a fixed footer.

**Architecture:** Extend provider config so custom providers persist their own model lists and default model, add a dedicated discovery API, and move quick-mode model assignment into explicit default-selection helpers. Refactor onboarding so `LLM` is no longer one long mixed step: provider configuration becomes the shared first step, model selection becomes an expert-only second step, and the shared onboarding frame owns scrolling and footer positioning.

**Tech Stack:** Python 3.10+, FastAPI, Pydantic v2, React 18, TypeScript, Vite, Vitest, Testing Library

---

## File Structure

### Backend config and API

- Modify: `backend/src/magi/config/models.py`
  Add custom-provider model fields to persisted config.
- Modify: `backend/src/magi/api/routers/config.py`
  Accept and return the new custom-provider fields and expose a discovery action endpoint.
- Modify: `backend/src/magi/config/llm_registry.py`
  Reuse registry defaults for built-in provider auto-selection.
- Test: `backend/tests/test_config_api.py`
  Cover serialization, validation, and discovery API behavior.

### Frontend config types and LLM form logic

- Modify: `frontend/src/api/modules/config.ts`
  Add custom-provider model fields and discovery request/response types.
- Modify: `frontend/src/components/config-forms/LLMForm.tsx`
  Centralize provider validation, default-selection helpers, and discovery wiring.
- Modify: `frontend/src/components/config-forms/LLMProviderConfigurationSection.tsx`
  Add custom-model editing and explicit fetch-model action.
- Modify: `frontend/src/components/config-forms/LLMModelSelectionSection.tsx`
  Consume provider-backed model lists, including custom-provider models.
- Test: `frontend/src/__tests__/configForms.test.tsx`
  Cover new provider model behavior and quick-mode auto selection.

### Onboarding flow and layout

- Modify: `frontend/src/components/onboarding/OnboardingFlow.tsx`
  Split `LLM` into two steps in expert mode and one step in quick mode.
- Modify: `frontend/src/components/config-forms/GuidedConfigFrame.tsx`
  Lock the right-side shell into scrollable content plus fixed footer.
- Modify: `frontend/src/pages/Onboarding.tsx`
  Keep the centered viewport shell working with the new frame behavior.
- Test: `frontend/src/__tests__/onboardingFlow.test.tsx`
  Validate quick/expert step sequences.
- Test: `frontend/src/__tests__/guidedConfigFrame.test.tsx`
  Validate scrollable content and fixed footer classes.
- Test: `frontend/src/__tests__/onboardingPage.test.tsx`
  Validate the centered page shell remains intact.

### Settings alignment

- Modify: `frontend/src/pages/Settings.tsx`
  Keep settings save flow compatible with the expanded provider config.
- Test: `frontend/src/__tests__/settingsPage.test.tsx`
  Ensure the settings draft/save path still works with custom-provider model fields.

## Chunk 1: Backend Provider Model Metadata

### Task 1: Persist custom-provider models in config

**Files:**
- Modify: `backend/src/magi/config/models.py`
- Test: `backend/tests/test_config_api.py`

- [ ] **Step 1: Write the failing config-model test**

```python
def test_llm_provider_settings_support_custom_model_fields():
    provider = LLMProviderSettings(
        provider_type="custom",
        display_name="Proxy",
        custom_models=["foo-1", "foo-2"],
        custom_default_model="foo-1",
    )

    assert provider.custom_models == ["foo-1", "foo-2"]
    assert provider.custom_default_model == "foo-1"
```

- [ ] **Step 2: Run the focused test to verify it fails**

Run: `cd /Users/asuka/code/magi/backend && pytest tests/test_config_api.py::test_llm_provider_settings_support_custom_model_fields -v`
Expected: FAIL because `LLMProviderSettings` does not yet define those fields.

- [ ] **Step 3: Add the persisted fields to `LLMProviderSettings`**

```python
class LLMProviderSettings(BaseModel):
    ...
    custom_models: List[str] = Field(default_factory=list)
    custom_default_model: Optional[str] = Field(default=None)
```

- [ ] **Step 4: Add validation for custom-provider defaults**

```python
@model_validator(mode="after")
def validate_custom_provider_models(self) -> "LLMProviderSettings":
    if self.provider_type == LLMProvider.CUSTOM:
        if self.custom_default_model and self.custom_default_model not in self.custom_models:
            raise ValueError("Custom default model must exist in custom_models")
    return self
```

- [ ] **Step 5: Re-run the focused test**

Run: `cd /Users/asuka/code/magi/backend && pytest tests/test_config_api.py::test_llm_provider_settings_support_custom_model_fields -v`
Expected: PASS

- [ ] **Step 6: Add one validation regression test**

```python
def test_custom_provider_default_model_must_be_in_model_list():
    with pytest.raises(ValueError):
        LLMProviderSettings(
            provider_type="custom",
            display_name="Proxy",
            custom_models=["foo-1"],
            custom_default_model="foo-2",
        )
```

- [ ] **Step 7: Run the backend config test file**

Run: `cd /Users/asuka/code/magi/backend && pytest tests/test_config_api.py -v`
Expected: PASS

- [ ] **Step 8: Commit**

```bash
git add backend/src/magi/config/models.py backend/tests/test_config_api.py
git commit -m "feat: persist custom provider model metadata"
```

### Task 2: Add explicit model-discovery API

**Files:**
- Modify: `backend/src/magi/api/routers/config.py`
- Test: `backend/tests/test_config_api.py`

- [ ] **Step 1: Write the failing API test**

```python
def test_discover_llm_models_returns_models_from_provider_endpoint(client):
    response = client.post(
        "/config/llm/providers/discover-models",
        json={
            "provider_type": "custom",
            "base_url": "https://proxy.example.com/v1",
            "api_key": "sk-test",
            "api_format": "openai",
        },
    )

    assert response.status_code == 200
    assert response.json()["models"] == ["foo-1", "foo-2"]
```

- [ ] **Step 2: Run the focused API test to verify it fails**

Run: `cd /Users/asuka/code/magi/backend && pytest tests/test_config_api.py::test_discover_llm_models_returns_models_from_provider_endpoint -v`
Expected: FAIL because the route does not exist yet.

- [ ] **Step 3: Add request/response models and the route**

```python
class DiscoverLLMModelsRequest(BaseModel):
    provider_type: str
    base_url: str
    api_key: Optional[str] = None
    api_format: Optional[str] = None


@router.post("/llm/providers/discover-models")
async def discover_llm_models(payload: DiscoverLLMModelsRequest) -> dict[str, Any]:
    models = await _discover_remote_models(payload)
    return {"models": models, "default_model": models[0] if models else None}
```

- [ ] **Step 4: Stub or reuse provider-specific discovery helpers**

```python
async def _discover_remote_models(payload: DiscoverLLMModelsRequest) -> list[str]:
    if payload.api_format == "openai":
        ...
    raise HTTPException(status_code=400, detail="Unsupported model discovery format")
```

- [ ] **Step 5: Add a failure-path regression test**

```python
def test_discover_llm_models_preserves_clear_error_for_invalid_endpoint(client):
    response = client.post("/config/llm/providers/discover-models", json={...})
    assert response.status_code in {400, 502}
```

- [ ] **Step 6: Run the backend API test file**

Run: `cd /Users/asuka/code/magi/backend && pytest tests/test_config_api.py -v`
Expected: PASS

- [ ] **Step 7: Commit**

```bash
git add backend/src/magi/api/routers/config.py backend/tests/test_config_api.py
git commit -m "feat: add llm model discovery api"
```

## Chunk 2: Frontend LLM Provider Data Flow

### Task 3: Extend frontend config types and API client

**Files:**
- Modify: `frontend/src/api/modules/config.ts`
- Test: `frontend/src/__tests__/configForms.test.tsx`

- [ ] **Step 1: Write the failing frontend type-driven test**

```tsx
it('supports custom provider model metadata in llm form value', () => {
  expectTypeOf(llmValue.providers.custom_proxy.custom_models).toEqualTypeOf<string[] | undefined>()
})
```

- [ ] **Step 2: Run the focused test file to verify the current shape fails**

Run: `cd /Users/asuka/code/magi/frontend && npm run test -- --run src/__tests__/configForms.test.tsx`
Expected: FAIL or type-check failure because the provider type does not include custom model metadata.

- [ ] **Step 3: Add the new provider fields and discovery payload types**

```ts
export interface LLMProviderConfig {
  ...
  custom_models?: string[];
  custom_default_model?: string;
}

export interface DiscoverLLMModelsRequest {
  provider_type: LLMProvider;
  base_url: string;
  api_key?: string;
  api_format?: ApiFormat;
}
```

- [ ] **Step 4: Add the client method**

```ts
discoverLLMProviderModels(payload: DiscoverLLMModelsRequest) {
  return api.post('/config/llm/providers/discover-models', payload);
}
```

- [ ] **Step 5: Run `configForms` tests and type-check**

Run: `cd /Users/asuka/code/magi/frontend && npm run test -- --run src/__tests__/configForms.test.tsx`
Expected: PASS or reach the next intentional failure.

Run: `cd /Users/asuka/code/magi/frontend && npm run type-check`
Expected: PASS or expose the next missing callsite.

- [ ] **Step 6: Commit**

```bash
git add frontend/src/api/modules/config.ts frontend/src/__tests__/configForms.test.tsx
git commit -m "feat: add frontend llm discovery types"
```

### Task 4: Add custom model editing and fetch-model action to provider configuration

**Files:**
- Modify: `frontend/src/components/config-forms/LLMForm.tsx`
- Modify: `frontend/src/components/config-forms/LLMProviderConfigurationSection.tsx`
- Test: `frontend/src/__tests__/configForms.test.tsx`

- [ ] **Step 1: Write the failing interaction tests**

```tsx
it('lets users add a custom provider model manually', async () => {
  ...
  expect(screen.getByText('foo-1')).toBeInTheDocument()
})

it('fetches custom provider models on demand', async () => {
  ...
  expect(await screen.findByText('fetched-model-1')).toBeInTheDocument()
})
```

- [ ] **Step 2: Run the focused test file to verify failure**

Run: `cd /Users/asuka/code/magi/frontend && npm run test -- --run src/__tests__/configForms.test.tsx`
Expected: FAIL because the custom-provider editor and button do not exist yet.

- [ ] **Step 3: Extend cloning helpers and normalization in `LLMForm.tsx`**

```ts
const cloneProvider = (value?: Partial<LLMProviderConfig>): LLMProviderConfig => ({
  ...
  custom_models: [...(value?.custom_models || [])],
  custom_default_model: value?.custom_default_model || '',
})
```

- [ ] **Step 4: Add manual model editing controls to the custom-provider detail pane**

```tsx
<div>
  <label>{t('llm.providerConfiguration.availableModels')}</label>
  <TagInput ... />
</div>
<label>
  <span>{t('llm.fields.defaultModel')}</span>
  <select ... />
</label>
```

- [ ] **Step 5: Add an explicit `Fetch Models` button and loading/error state**

```tsx
<button type="button" onClick={() => onFetchProviderModels(activeProviderId)}>
  {t('llm.actions.fetchModels')}
</button>
```

- [ ] **Step 6: Wire the button through `LLMForm.tsx`**

```ts
const handleDiscoverProviderModels = async (providerId: string) => {
  const response = await configApi.discoverLLMProviderModels(...)
  updateValue(...)
}
```

- [ ] **Step 7: Re-run the focused frontend tests**

Run: `cd /Users/asuka/code/magi/frontend && npm run test -- --run src/__tests__/configForms.test.tsx`
Expected: PASS

- [ ] **Step 8: Commit**

```bash
git add frontend/src/components/config-forms/LLMForm.tsx frontend/src/components/config-forms/LLMProviderConfigurationSection.tsx frontend/src/__tests__/configForms.test.tsx
git commit -m "feat: add custom provider model controls"
```

## Chunk 3: Default Model Selection Logic

### Task 5: Generate scenario defaults from provider metadata

**Files:**
- Modify: `frontend/src/components/config-forms/LLMForm.tsx`
- Test: `frontend/src/__tests__/configForms.test.tsx`

- [ ] **Step 1: Write failing tests for quick-mode defaults**

```tsx
it('uses registry default_model for built-in provider auto selection', async () => {
  ...
})

it('uses custom_default_model for custom provider auto selection', async () => {
  ...
})
```

- [ ] **Step 2: Run the focused test file to verify failure**

Run: `cd /Users/asuka/code/magi/frontend && npm run test -- --run src/__tests__/configForms.test.tsx`
Expected: FAIL because auto-selection still depends on the current mixed-step logic.

- [ ] **Step 3: Extract a shared default-model resolver**

```ts
const resolveProviderDefaultModel = (
  registry: LLMProviderRegistry,
  provider: LLMProviderConfig | undefined,
): string => {
  if (!provider) return ''
  if (provider.provider_type === 'custom') return provider.custom_default_model || ''
  return getProviderMeta(registry, provider.provider_type)?.default_model || ''
}
```

- [ ] **Step 4: Use that helper when pre-filling selections**

```ts
selection.model = resolveProviderDefaultModel(registry, provider)
```

- [ ] **Step 5: Add one provider-step validator for quick mode**

```ts
const validateProviderStep = (...) => {
  if (provider.provider_type === 'custom' && !provider.custom_default_model) {
    return t('llm.validation.customDefaultModelRequired')
  }
}
```

- [ ] **Step 6: Re-run `configForms` tests and type-check**

Run: `cd /Users/asuka/code/magi/frontend && npm run test -- --run src/__tests__/configForms.test.tsx`
Expected: PASS

Run: `cd /Users/asuka/code/magi/frontend && npm run type-check`
Expected: PASS

- [ ] **Step 7: Commit**

```bash
git add frontend/src/components/config-forms/LLMForm.tsx frontend/src/__tests__/configForms.test.tsx
git commit -m "feat: auto select llm defaults by provider"
```

## Chunk 4: Onboarding Step Split and Layout

### Task 6: Split the onboarding flow into provider and model steps

**Files:**
- Modify: `frontend/src/components/onboarding/OnboardingFlow.tsx`
- Test: `frontend/src/__tests__/onboardingFlow.test.tsx`

- [ ] **Step 1: Write the failing onboarding-step tests**

```tsx
it('quick mode includes provider configuration but skips model selection', () => {
  ...
})

it('expert mode includes provider configuration followed by model selection', () => {
  ...
})
```

- [ ] **Step 2: Run the focused onboarding-flow test**

Run: `cd /Users/asuka/code/magi/frontend && npm run test -- --run src/__tests__/onboardingFlow.test.tsx`
Expected: FAIL because onboarding still has one `LLM` step.

- [ ] **Step 3: Add explicit step ids for `llmProviders` and `llmModels`**

```ts
const shared = [t('steps.language'), t('steps.mode')]
const llmSteps = mode === 'expert'
  ? [t('steps.llmProviders'), t('steps.llmModels')]
  : [t('steps.llmProviders')]
```

- [ ] **Step 4: Render the correct form per step**

```tsx
if (quickMode && current === quickSteps[0]) return <LLMForm quickMode step="providers" />
if (!quickMode && current === expertSteps[0]) return <LLMForm step="providers" />
if (!quickMode && current === expertSteps[1]) return <LLMForm step="models" />
```

- [ ] **Step 5: Re-run the onboarding-flow tests**

Run: `cd /Users/asuka/code/magi/frontend && npm run test -- --run src/__tests__/onboardingFlow.test.tsx`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add frontend/src/components/onboarding/OnboardingFlow.tsx frontend/src/__tests__/onboardingFlow.test.tsx
git commit -m "feat: split llm onboarding into two steps"
```

### Task 7: Lock the onboarding shell to scrollable content plus fixed footer

**Files:**
- Modify: `frontend/src/components/config-forms/GuidedConfigFrame.tsx`
- Modify: `frontend/src/pages/Onboarding.tsx`
- Test: `frontend/src/__tests__/guidedConfigFrame.test.tsx`
- Test: `frontend/src/__tests__/onboardingPage.test.tsx`

- [ ] **Step 1: Write the failing layout tests**

```tsx
it('keeps the content pane scrollable while footer stays fixed', () => {
  ...
})
```

- [ ] **Step 2: Run the focused layout tests**

Run: `cd /Users/asuka/code/magi/frontend && npm run test -- --run src/__tests__/guidedConfigFrame.test.tsx src/__tests__/onboardingPage.test.tsx`
Expected: FAIL because the frame does not yet enforce the new two-zone shell.

- [ ] **Step 3: Refine `GuidedConfigFrame` layout classes**

```tsx
<div className="flex min-h-0 flex-1 flex-col">
  <div className="min-h-0 flex-1 overflow-y-auto">...</div>
  <div className="shrink-0 border-t ...">...</div>
</div>
```

- [ ] **Step 4: Keep `Onboarding.tsx` centered while allowing the card to fill available height**

```tsx
<div className="flex min-h-screen items-center justify-center overflow-y-auto ...">
```

- [ ] **Step 5: Re-run the layout tests**

Run: `cd /Users/asuka/code/magi/frontend && npm run test -- --run src/__tests__/guidedConfigFrame.test.tsx src/__tests__/onboardingPage.test.tsx`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add frontend/src/components/config-forms/GuidedConfigFrame.tsx frontend/src/pages/Onboarding.tsx frontend/src/__tests__/guidedConfigFrame.test.tsx frontend/src/__tests__/onboardingPage.test.tsx
git commit -m "fix: stabilize onboarding shell layout"
```

### Task 8: Keep settings compatible with the expanded provider config

**Files:**
- Modify: `frontend/src/pages/Settings.tsx`
- Test: `frontend/src/__tests__/settingsPage.test.tsx`

- [ ] **Step 1: Write the failing settings test**

```tsx
it('saves llm settings with custom provider models', async () => {
  ...
})
```

- [ ] **Step 2: Run the focused settings test**

Run: `cd /Users/asuka/code/magi/frontend && npm run test -- --run src/__tests__/settingsPage.test.tsx`
Expected: FAIL because the new provider fields are not part of the save payload yet.

- [ ] **Step 3: Update the settings draft/save plumbing**

```tsx
const llmDraft = {
  ...values.llm,
  providers: normalizeProviders(values.llm.providers),
}
```

- [ ] **Step 4: Re-run the settings test**

Run: `cd /Users/asuka/code/magi/frontend && npm run test -- --run src/__tests__/settingsPage.test.tsx`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add frontend/src/pages/Settings.tsx frontend/src/__tests__/settingsPage.test.tsx
git commit -m "fix: keep settings aligned with llm provider models"
```

## Chunk 5: Final Verification

### Task 9: Run the end-to-end verification set

**Files:**
- No code changes expected unless a regression appears

- [ ] **Step 1: Run backend verification**

Run: `cd /Users/asuka/code/magi/backend && pytest tests/test_config_api.py -v`
Expected: PASS

- [ ] **Step 2: Run frontend focused verification**

Run: `cd /Users/asuka/code/magi/frontend && npm run test -- --run src/__tests__/configForms.test.tsx src/__tests__/guidedConfigFrame.test.tsx src/__tests__/onboardingFlow.test.tsx src/__tests__/onboardingPage.test.tsx src/__tests__/settingsPage.test.tsx`
Expected: PASS

- [ ] **Step 3: Run frontend type-check**

Run: `cd /Users/asuka/code/magi/frontend && npm run type-check`
Expected: PASS

- [ ] **Step 4: Commit any verification-driven fixes**

```bash
git add <files>
git commit -m "fix: resolve llm onboarding verification regressions"
```

