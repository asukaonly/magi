# LLM Draft Actions Implementation Plan

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add draft-aware LLM provider testing and onboarding personality generation so users can validate and use unsaved provider settings.

**Architecture:** The backend will expose one temporary-provider test endpoint and one shared helper for resolving draft LLM overrides into runtime adapters. The frontend will wire the provider workbench to that endpoint and pass onboarding LLM drafts into personality generation requests.

**Tech Stack:** FastAPI, Pydantic v2, React 18, TypeScript, Zustand/simple-form state, Vitest, pytest

---

## Chunk 1: Backend Draft LLM Resolution

### Task 1: Add backend failing tests for draft LLM actions

**Files:**
- Modify: `/Users/asuka/code/magi/backend/tests/test_config_api.py`
- Modify: `/Users/asuka/code/magi/backend/tests/test_personality_config_router.py`

- [ ] **Step 1: Write the failing tests**

```python
def test_llm_provider_test_uses_request_provider_payload(...):
    ...

async def test_ai_generate_personality_prefers_llm_override(...):
    ...
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest backend/tests/test_config_api.py backend/tests/test_personality_config_router.py -q`
Expected: FAIL because the provider test endpoint and override-aware generation path do not exist yet.

- [ ] **Step 3: Write minimal implementation**

Implement:
- request/response models for provider test
- shared helper that resolves effective LLM config from optional override
- draft-aware adapter creation for provider test and personality generation

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest backend/tests/test_config_api.py backend/tests/test_personality_config_router.py -q`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add backend/tests/test_config_api.py backend/tests/test_personality_config_router.py backend/src/magi/api/routers/config.py backend/src/magi/api/routers/personality_config.py
git commit -m "feat: support draft llm actions"
```

## Chunk 2: Frontend Provider Test UI

### Task 2: Add provider test client API and UI feedback

**Files:**
- Modify: `/Users/asuka/code/magi/frontend/src/api/modules/config.ts`
- Modify: `/Users/asuka/code/magi/frontend/src/components/config-forms/LLMForm.tsx`
- Modify: `/Users/asuka/code/magi/frontend/src/components/config-forms/LLMProviderConfigurationSection.tsx`
- Modify: `/Users/asuka/code/magi/frontend/src/i18n/locales/zh-CN/onboarding.json`
- Modify: `/Users/asuka/code/magi/frontend/src/i18n/locales/en/onboarding.json`
- Test: `/Users/asuka/code/magi/frontend/src/__tests__/configForms.test.tsx`

- [ ] **Step 1: Write the failing frontend tests**

```tsx
it('tests the active provider with current draft credentials', async () => {
  ...
})
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd frontend && npm run test -- --run src/__tests__/configForms.test.tsx`
Expected: FAIL because no test action exists yet.

- [ ] **Step 3: Write minimal implementation**

Implement:
- config API helper for provider connection testing
- active-provider test button and inline result state
- draft model resolution for the probe request

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd frontend && npm run test -- --run src/__tests__/configForms.test.tsx`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add frontend/src/api/modules/config.ts frontend/src/components/config-forms/LLMForm.tsx frontend/src/components/config-forms/LLMProviderConfigurationSection.tsx frontend/src/i18n/locales/zh-CN/onboarding.json frontend/src/i18n/locales/en/onboarding.json frontend/src/__tests__/configForms.test.tsx
git commit -m "feat: add llm provider connection test"
```

## Chunk 3: Onboarding Personality Draft Override

### Task 3: Pass onboarding LLM drafts into personality generation

**Files:**
- Modify: `/Users/asuka/code/magi/frontend/src/api/modules/personality.ts`
- Modify: `/Users/asuka/code/magi/frontend/src/components/config-forms/PersonalityForm.tsx`
- Test: `/Users/asuka/code/magi/frontend/src/__tests__/onboardingFlow.test.tsx`

- [ ] **Step 1: Write the failing test**

```tsx
it('passes llm draft override when generating personality during onboarding', async () => {
  ...
})
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd frontend && npm run test -- --run src/__tests__/onboardingFlow.test.tsx`
Expected: FAIL because personality generation request does not include LLM draft data.

- [ ] **Step 3: Write minimal implementation**

Implement:
- optional `llm_override` field on personality generate request typing
- onboarding personality form reads current `llm` value from form context and includes it in generate requests

- [ ] **Step 4: Run tests to verify it passes**

Run: `cd frontend && npm run test -- --run src/__tests__/onboardingFlow.test.tsx`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add frontend/src/api/modules/personality.ts frontend/src/components/config-forms/PersonalityForm.tsx frontend/src/__tests__/onboardingFlow.test.tsx
git commit -m "feat: use draft llm config for onboarding personality"
```

## Chunk 4: Final Verification

### Task 4: Run full targeted verification

**Files:**
- No code changes expected

- [ ] **Step 1: Run backend verification**

Run: `pytest backend/tests/test_config_api.py backend/tests/test_personality_config_router.py backend/tests/test_personality_presets_router.py -q`
Expected: PASS

- [ ] **Step 2: Run frontend verification**

Run: `cd frontend && npm run type-check && npm run test -- --run src/__tests__/configForms.test.tsx src/__tests__/onboardingFlow.test.tsx src/__tests__/personalitiesApi.test.ts`
Expected: PASS

- [ ] **Step 3: Commit if verification required code/doc touchups**

```bash
git add <files-if-needed>
git commit -m "test: verify llm draft actions"
```

If no code changes are needed after verification, skip this commit.
