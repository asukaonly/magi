# LLM Provider Panel Refresh Implementation Plan

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Refresh the LLM provider configuration panel so it keeps the two-column layout but reads like a flatter settings surface with less decorative styling and less verbose connection-test copy.

**Architecture:** Keep the existing `LLMProviderConfigurationSection` data flow intact and limit changes to presentation structure, class names, and a small amount of copy cleanup. Update tests only where visible UI text or DOM structure expectations change.

**Tech Stack:** React 18, TypeScript, TailwindCSS, Vitest, Testing Library, i18next

---

## Chunk 1: Flatten The Provider Workbench Surface

### Task 1: Update the provider workbench container styling

**Files:**
- Modify: `/Users/asuka/code/magi/frontend/src/components/config-forms/LLMProviderConfigurationSection.tsx`
- Test: `/Users/asuka/code/magi/frontend/src/__tests__/configForms.test.tsx`

- [ ] **Step 1: Write the failing test**

Add or adjust a component assertion that still verifies the section renders after the structure is flattened.

- [ ] **Step 2: Run test to verify it fails**

Run: `cd frontend && npm run test -- --run src/__tests__/configForms.test.tsx`

- [ ] **Step 3: Write minimal implementation**

Remove the gradient-heavy outer workbench styling and replace it with flatter pane backgrounds and separators.

- [ ] **Step 4: Run test to verify it passes**

Run: `cd frontend && npm run test -- --run src/__tests__/configForms.test.tsx`

- [ ] **Step 5: Commit**

```bash
git add frontend/src/components/config-forms/LLMProviderConfigurationSection.tsx frontend/src/__tests__/configForms.test.tsx
git commit -m "refactor: flatten llm provider workbench"
```

## Chunk 2: Simplify The Detail Pane Hierarchy

### Task 2: Replace the verbose connection test block with a compact action row

**Files:**
- Modify: `/Users/asuka/code/magi/frontend/src/components/config-forms/LLMProviderConfigurationSection.tsx`
- Modify: `/Users/asuka/code/magi/frontend/src/i18n/locales/zh-CN/onboarding.json`
- Modify: `/Users/asuka/code/magi/frontend/src/i18n/locales/en/onboarding.json`
- Test: `/Users/asuka/code/magi/frontend/src/__tests__/configForms.test.tsx`

- [ ] **Step 1: Write the failing test**

Update a test to assert the compact `Test` action remains visible and old descriptive copy is no longer required.

- [ ] **Step 2: Run test to verify it fails**

Run: `cd frontend && npm run test -- --run src/__tests__/configForms.test.tsx`

- [ ] **Step 3: Write minimal implementation**

Remove the test title/description block from the UI, keep a single action button, and present success/error feedback in compact inline rows.

- [ ] **Step 4: Run test to verify it passes**

Run: `cd frontend && npm run test -- --run src/__tests__/configForms.test.tsx`

- [ ] **Step 5: Commit**

```bash
git add frontend/src/components/config-forms/LLMProviderConfigurationSection.tsx frontend/src/i18n/locales/zh-CN/onboarding.json frontend/src/i18n/locales/en/onboarding.json frontend/src/__tests__/configForms.test.tsx
git commit -m "refactor: simplify llm provider detail actions"
```

## Chunk 3: Tighten Spacing For Inputs And Model References

### Task 3: Make the right pane read like a settings form instead of stacked cards

**Files:**
- Modify: `/Users/asuka/code/magi/frontend/src/components/config-forms/LLMProviderConfigurationSection.tsx`
- Test: `/Users/asuka/code/magi/frontend/src/__tests__/configForms.test.tsx`

- [ ] **Step 1: Write the failing test**

Add or update a rendering test that still verifies the built-in provider fields and available-model labels remain visible after the layout simplification.

- [ ] **Step 2: Run test to verify it fails**

Run: `cd frontend && npm run test -- --run src/__tests__/configForms.test.tsx`

- [ ] **Step 3: Write minimal implementation**

Remove emphasized field containers where unnecessary, keep clear spacing between sections, and flatten the available-model list presentation.

- [ ] **Step 4: Run test to verify it passes**

Run: `cd frontend && npm run test -- --run src/__tests__/configForms.test.tsx`

- [ ] **Step 5: Commit**

```bash
git add frontend/src/components/config-forms/LLMProviderConfigurationSection.tsx frontend/src/__tests__/configForms.test.tsx
git commit -m "refactor: tighten llm provider form layout"
```

## Chunk 4: Final Validation

### Task 4: Run regression checks

**Files:**
- Verify only

- [ ] **Step 1: Run focused component tests**

Run: `cd frontend && npm run test -- --run src/__tests__/configForms.test.tsx src/__tests__/settingsPage.test.tsx`

- [ ] **Step 2: Run type-check**

Run: `cd frontend && npm run type-check`

- [ ] **Step 3: Commit final polish if needed**

```bash
git add frontend/src/components/config-forms/LLMProviderConfigurationSection.tsx frontend/src/i18n/locales/zh-CN/onboarding.json frontend/src/i18n/locales/en/onboarding.json frontend/src/__tests__/configForms.test.tsx
git commit -m "fix: polish llm provider settings panel"
```
