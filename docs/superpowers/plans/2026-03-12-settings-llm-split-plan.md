# Settings LLM Split Implementation Plan

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Split settings LLM controls into two left-navigation child pages under a new `大模型配置` group and restyle both pages to match the calmer settings-shell aesthetic.

**Architecture:** Keep the existing settings page as the shell and continue using `draftConfig.llm` as the single source of truth. Refactor navigation to support grouped entries, then render `LLMForm` in provider-only or model-only mode for the two child pages, while simplifying both provider and model sections to fit the settings design language.

**Tech Stack:** React 18, TypeScript, TailwindCSS, Vitest, Testing Library, i18next

---

## Chunk 1: Settings Navigation Grouping

### Task 1: Add grouped LLM navigation entries

**Files:**
- Modify: `/Users/asuka/code/magi/frontend/src/pages/Settings.tsx`
- Modify: `/Users/asuka/code/magi/frontend/src/i18n/locales/zh-CN/app.json`
- Modify: `/Users/asuka/code/magi/frontend/src/i18n/locales/en/app.json`
- Test: `/Users/asuka/code/magi/frontend/src/__tests__/settingsPage.test.tsx`

- [ ] **Step 1: Write the failing test**
- [ ] **Step 2: Run test to verify it fails**
- [ ] **Step 3: Implement grouped `大模型配置` navigation with two child entries**
- [ ] **Step 4: Run the test to verify it passes**
- [ ] **Step 5: Commit**

## Chunk 2: Split LLM Content Into Two Settings Pages

### Task 2: Route provider and model pages through separate settings sections

**Files:**
- Modify: `/Users/asuka/code/magi/frontend/src/pages/Settings.tsx`
- Modify: `/Users/asuka/code/magi/frontend/src/components/config-forms/LLMForm.tsx`
- Test: `/Users/asuka/code/magi/frontend/src/__tests__/settingsPage.test.tsx`

- [ ] **Step 1: Write the failing test**
- [ ] **Step 2: Run test to verify it fails**
- [ ] **Step 3: Render provider-only and model-only settings sections from separate nav entries**
- [ ] **Step 4: Run the test to verify it passes**
- [ ] **Step 5: Commit**

## Chunk 3: Simplify Provider Configuration Styling

### Task 3: Make provider configuration match the settings shell aesthetic

**Files:**
- Modify: `/Users/asuka/code/magi/frontend/src/components/config-forms/LLMProviderConfigurationSection.tsx`
- Test: `/Users/asuka/code/magi/frontend/src/__tests__/configForms.test.tsx`

- [ ] **Step 1: Write the failing test**
- [ ] **Step 2: Run test to verify it fails**
- [ ] **Step 3: Tighten typography, spacing, and background treatment for the provider page**
- [ ] **Step 4: Run the test to verify it passes**
- [ ] **Step 5: Commit**

## Chunk 4: Simplify Model Selection Styling

### Task 4: Make model selection a flatter settings page

**Files:**
- Modify: `/Users/asuka/code/magi/frontend/src/components/config-forms/LLMModelSelectionSection.tsx`
- Test: `/Users/asuka/code/magi/frontend/src/__tests__/configForms.test.tsx`

- [ ] **Step 1: Write the failing test**
- [ ] **Step 2: Run test to verify it fails**
- [ ] **Step 3: Flatten the scenario cards into quieter settings sections**
- [ ] **Step 4: Run the test to verify it passes**
- [ ] **Step 5: Commit**

## Chunk 5: Final Validation

### Task 5: Run focused settings and config regressions

**Files:**
- Verify only

- [ ] **Step 1: Run focused frontend tests**

Run: `cd frontend && npm run test -- --run src/__tests__/settingsPage.test.tsx src/__tests__/configForms.test.tsx`

- [ ] **Step 2: Run type-check**

Run: `cd frontend && npm run type-check`

- [ ] **Step 3: Commit final polish if needed**

```bash
git add frontend/src/pages/Settings.tsx frontend/src/components/config-forms/LLMForm.tsx frontend/src/components/config-forms/LLMProviderConfigurationSection.tsx frontend/src/components/config-forms/LLMModelSelectionSection.tsx frontend/src/i18n/locales/zh-CN/app.json frontend/src/i18n/locales/en/app.json frontend/src/__tests__/settingsPage.test.tsx frontend/src/__tests__/configForms.test.tsx
git commit -m "refactor: split settings llm configuration"
```
