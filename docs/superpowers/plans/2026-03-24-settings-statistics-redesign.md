# Settings Statistics Redesign Implementation Plan

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the current single settings usage page with a two-submenu statistics center that provides refined LLM analytics and a real runtime overview backed by actual runtime data.

**Architecture:** Keep the redesign inside the existing settings shell by converting the current `usage` leaf into a `statistics` nav group with two dedicated leaf sections. Reuse one lightweight analytics frame on the frontend, extend the existing LLM metrics endpoints for historical analysis, and add a new runtime overview aggregation endpoint for live health data. Avoid placeholder agent data and show explicit unavailable states when metrics are not yet available.

**Tech Stack:** React 18, TypeScript, Vite, Vitest, FastAPI, Pydantic, psutil, existing Magi metrics/router/runtime services.

---

## File Structure

### Frontend files

- Modify: `frontend/src/constants/settings.ts`
  - Replace the current `usage` leaf with a `statistics` nav group and two children.
- Modify: `frontend/src/pages/Settings.tsx`
  - Wire new settings sections into navigation and content rendering.
- Modify: `frontend/src/types/settings.ts`
  - Ensure nav item typing supports the new statistics group without special-casing.
- Modify: `frontend/src/i18n/locales/zh-CN/app.json`
  - Add statistics group/subpage labels and new copy.
- Modify: `frontend/src/i18n/locales/en/app.json`
  - Keep English copy aligned with the new statistics structure.
- Modify: `frontend/src/api/modules/metrics.ts`
  - Extend LLM metrics types and add runtime overview API types/methods.
- Create: `frontend/src/components/settings/StatisticsPageFrame.tsx`
  - Shared lightweight analytics page frame for both statistics pages.
- Create: `frontend/src/components/settings/LLMStatisticsSection.tsx`
  - New editorial-style LLM statistics page using the shared frame.
- Create: `frontend/src/components/settings/RuntimeStatisticsSection.tsx`
  - New runtime overview page using the shared frame.
- Modify: `frontend/src/components/settings/index.ts`
  - Export new statistics components.
- Modify: `frontend/src/__tests__/settingsPage.test.tsx`
  - Cover navigation and new section wiring.
- Create: `frontend/src/__tests__/llmStatisticsSection.test.tsx`
  - Cover LLM statistics interactions and empty states.
- Create: `frontend/src/__tests__/runtimeStatisticsSection.test.tsx`
  - Cover runtime overview rendering and unavailable-state handling.

### Backend files

- Modify: `backend/src/magi/api/routers/metrics.py`
  - Add runtime overview endpoint and extend LLM usage endpoints.
- Create: `backend/src/magi/api/services/metrics_overview_service.py`
  - Aggregate runtime-backed metrics in one place.
- Modify: `backend/src/magi/api/services/runtime_status_service.py`
  - Reuse existing runtime status helpers where appropriate.
- Modify: `backend/src/magi/llm/usage_store.py`
  - Extend summary/timeseries queries for cost/TTFT/success-related fields if available from stored usage data.
- Create: `backend/tests/api/test_metrics_api.py`
  - Cover runtime overview and extended LLM metrics payload behavior.

---

## Chunk 1: Settings Navigation And Frontend Wiring

### Task 1: Convert `usage` into a `statistics` nav group

**Files:**
- Modify: `frontend/src/constants/settings.ts`
- Modify: `frontend/src/i18n/locales/zh-CN/app.json`
- Modify: `frontend/src/i18n/locales/en/app.json`
- Test: `frontend/src/__tests__/settingsPage.test.tsx`

- [ ] **Step 1: Write the failing settings navigation test**

Add coverage that expects:
- `settings.tabs.statistics`
- `settings.tabs.statisticsLlm`
- `settings.tabs.statisticsRuntime`

and no direct `usage` leaf rendering in the settings nav.

- [ ] **Step 2: Run the test to verify it fails**

Run:

```bash
cd frontend && npm run test -- settingsPage.test.tsx
```

Expected: FAIL because the navigation still exposes `usage` as a leaf.

- [ ] **Step 3: Update settings navigation constants and translations**

Implement:
- new nav group in `frontend/src/constants/settings.ts`
- aligned `settings.tabs.*` translation keys in both locales
- updated statistics descriptions replacing the old single-page wording

- [ ] **Step 4: Run the test to verify it passes**

Run:

```bash
cd frontend && npm run test -- settingsPage.test.tsx
```

Expected: PASS for the new navigation assertions.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/constants/settings.ts frontend/src/i18n/locales/zh-CN/app.json frontend/src/i18n/locales/en/app.json frontend/src/__tests__/settingsPage.test.tsx
git commit -m "feat: add statistics settings navigation"
```

### Task 2: Wire new statistics leaf sections into `Settings.tsx`

**Files:**
- Modify: `frontend/src/pages/Settings.tsx`
- Modify: `frontend/src/components/settings/index.ts`
- Test: `frontend/src/__tests__/settingsPage.test.tsx`

- [ ] **Step 1: Extend the failing settings page test**

Add assertions that selecting:
- `statisticsLlm`
- `statisticsRuntime`

renders separate section components instead of the old `usage` section.

- [ ] **Step 2: Run the test to verify it fails**

Run:

```bash
cd frontend && npm run test -- settingsPage.test.tsx
```

Expected: FAIL because `Settings.tsx` still maps `usage` to `LLMUsageSection`.

- [ ] **Step 3: Update section routing in `Settings.tsx`**

Implement:
- imports for the two new statistics sections
- `switch` cases for `statisticsLlm` and `statisticsRuntime`
- removal of the direct `usage` case

- [ ] **Step 4: Run the test to verify it passes**

Run:

```bash
cd frontend && npm run test -- settingsPage.test.tsx
```

Expected: PASS for new statistics section rendering.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/pages/Settings.tsx frontend/src/components/settings/index.ts frontend/src/__tests__/settingsPage.test.tsx
git commit -m "refactor: route settings statistics sections"
```

---

## Chunk 2: Shared Statistics Frame And LLM Statistics Redesign

### Task 3: Build the shared lightweight statistics frame

**Files:**
- Create: `frontend/src/components/settings/StatisticsPageFrame.tsx`
- Test: `frontend/src/__tests__/llmStatisticsSection.test.tsx`

- [ ] **Step 1: Write the failing frame usage test**

Add a new frontend test that expects the statistics page to expose:
- toolbar region
- signal ribbon region
- main canvas region
- summary rail region

- [ ] **Step 2: Run the test to verify it fails**

Run:

```bash
cd frontend && npm run test -- llmStatisticsSection.test.tsx
```

Expected: FAIL because the shared frame component does not exist.

- [ ] **Step 3: Create the shared frame component**

Implement a reusable frame that:
- fits inside the current settings shell
- avoids a page hero inside the content body
- uses lighter separators instead of repeated boxed cards

- [ ] **Step 4: Run the test to verify it passes**

Run:

```bash
cd frontend && npm run test -- llmStatisticsSection.test.tsx
```

Expected: PASS for structural regions.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/components/settings/StatisticsPageFrame.tsx frontend/src/__tests__/llmStatisticsSection.test.tsx
git commit -m "feat: add shared statistics page frame"
```

### Task 4: Replace the old usage panel with the new LLM statistics page

**Files:**
- Create: `frontend/src/components/settings/LLMStatisticsSection.tsx`
- Modify: `frontend/src/api/modules/metrics.ts`
- Modify: `frontend/src/components/settings/index.ts`
- Test: `frontend/src/__tests__/llmStatisticsSection.test.tsx`

- [ ] **Step 1: Extend the failing LLM statistics test**

Add coverage for:
- 7/30 day switching
- absence of repeated local title/subtitle inside content body
- toolbar filters
- empty state
- health summary rail content

- [ ] **Step 2: Run the test to verify it fails**

Run:

```bash
cd frontend && npm run test -- llmStatisticsSection.test.tsx
```

Expected: FAIL because the new section has not been implemented.

- [ ] **Step 3: Implement the editorial-style LLM statistics section**

Implement:
- top utility bar
- signal ribbon
- dominant trend canvas
- restrained secondary analysis sections
- concise health summary rail

Use real API data and explicit unavailable states where metrics are missing.

- [ ] **Step 4: Run the test to verify it passes**

Run:

```bash
cd frontend && npm run test -- llmStatisticsSection.test.tsx
```

Expected: PASS for the new LLM statistics behavior.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/components/settings/LLMStatisticsSection.tsx frontend/src/api/modules/metrics.ts frontend/src/components/settings/index.ts frontend/src/__tests__/llmStatisticsSection.test.tsx
git commit -m "feat: redesign llm statistics settings page"
```

---

## Chunk 3: Backend Metrics Extensions

### Task 5: Extend LLM metrics payloads for the redesigned page

**Files:**
- Modify: `backend/src/magi/llm/usage_store.py`
- Modify: `backend/src/magi/api/routers/metrics.py`
- Create: `backend/tests/api/test_metrics_api.py`

- [ ] **Step 1: Write the failing backend LLM metrics test**

Add tests that expect the summary/timeseries payloads to expose the extra fields required by the redesigned page, with stable null/default handling when data is missing.

- [ ] **Step 2: Run the test to verify it fails**

Run:

```bash
cd backend && pytest backend/tests/api/test_metrics_api.py -k llm_usage -v
```

Expected: FAIL because the new fields are not returned yet.

- [ ] **Step 3: Extend usage store queries and metrics router output**

Implement:
- aggregated cost fields where available
- TTFT aggregates where available
- explicit success-rate inputs
- stable schema for missing values

- [ ] **Step 4: Run the test to verify it passes**

Run:

```bash
cd backend && pytest backend/tests/api/test_metrics_api.py -k llm_usage -v
```

Expected: PASS for extended LLM metrics responses.

- [ ] **Step 5: Commit**

```bash
git add backend/src/magi/llm/usage_store.py backend/src/magi/api/routers/metrics.py backend/tests/api/test_metrics_api.py
git commit -m "feat: extend llm metrics summaries"
```

### Task 6: Add the runtime overview aggregation service and endpoint

**Files:**
- Create: `backend/src/magi/api/services/metrics_overview_service.py`
- Modify: `backend/src/magi/api/routers/metrics.py`
- Modify: `backend/src/magi/api/services/runtime_status_service.py`
- Modify: `backend/tests/api/test_metrics_api.py`

- [ ] **Step 1: Write the failing runtime overview test**

Add tests that expect `/api/metrics/runtime/overview` to return:
- system resource usage
- runtime readiness/backlog
- memory queue stats
- scheduler summary
- explicit unavailable markers for absent metrics

- [ ] **Step 2: Run the test to verify it fails**

Run:

```bash
cd backend && pytest backend/tests/api/test_metrics_api.py -k runtime_overview -v
```

Expected: FAIL because the endpoint/service does not exist.

- [ ] **Step 3: Implement runtime overview aggregation**

Build a dedicated service that:
- reuses existing runtime status helpers
- collects CPU/memory via `psutil`
- loads runtime queue backlog
- reads L2 pipeline backlog
- summarizes scheduler state
- returns TTFT/intent/core-model metrics only when trustworthy

- [ ] **Step 4: Run the test to verify it passes**

Run:

```bash
cd backend && pytest backend/tests/api/test_metrics_api.py -k runtime_overview -v
```

Expected: PASS for runtime overview schema and fallback behavior.

- [ ] **Step 5: Commit**

```bash
git add backend/src/magi/api/services/metrics_overview_service.py backend/src/magi/api/routers/metrics.py backend/src/magi/api/services/runtime_status_service.py backend/tests/api/test_metrics_api.py
git commit -m "feat: add runtime overview metrics endpoint"
```

---

## Chunk 4: Runtime Statistics Frontend

### Task 7: Implement the runtime statistics section

**Files:**
- Create: `frontend/src/components/settings/RuntimeStatisticsSection.tsx`
- Modify: `frontend/src/api/modules/metrics.ts`
- Modify: `frontend/src/components/settings/index.ts`
- Create: `frontend/src/__tests__/runtimeStatisticsSection.test.tsx`

- [ ] **Step 1: Write the failing runtime statistics test**

Add coverage for:
- refresh toolbar
- signal ribbon values
- main runtime trend region
- summary rail
- unavailable-state rendering

- [ ] **Step 2: Run the test to verify it fails**

Run:

```bash
cd frontend && npm run test -- runtimeStatisticsSection.test.tsx
```

Expected: FAIL because the runtime statistics section does not exist.

- [ ] **Step 3: Implement the runtime statistics UI**

Use the shared statistics frame and render:
- system resource ribbon
- CPU/memory/TTFT trend canvas
- scheduler and queue summary blocks
- concise health summary rail

- [ ] **Step 4: Run the test to verify it passes**

Run:

```bash
cd frontend && npm run test -- runtimeStatisticsSection.test.tsx
```

Expected: PASS for the runtime statistics interactions and states.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/components/settings/RuntimeStatisticsSection.tsx frontend/src/api/modules/metrics.ts frontend/src/components/settings/index.ts frontend/src/__tests__/runtimeStatisticsSection.test.tsx
git commit -m "feat: add runtime statistics settings page"
```

---

## Chunk 5: Integration Verification And Cleanup

### Task 8: Run focused frontend and backend verification

**Files:**
- Modify: `frontend/src/__tests__/settingsPage.test.tsx`
- Modify: `frontend/src/__tests__/llmStatisticsSection.test.tsx`
- Modify: `frontend/src/__tests__/runtimeStatisticsSection.test.tsx`
- Modify: `backend/tests/api/test_metrics_api.py`

- [ ] **Step 1: Run focused frontend tests**

Run:

```bash
cd frontend && npm run test -- settingsPage.test.tsx llmStatisticsSection.test.tsx runtimeStatisticsSection.test.tsx
```

Expected: PASS

- [ ] **Step 2: Run focused backend tests**

Run:

```bash
cd backend && pytest backend/tests/api/test_metrics_api.py backend/tests/api/test_runtime_status_service.py -v
```

Expected: PASS

- [ ] **Step 3: Run a type check for the frontend**

Run:

```bash
cd frontend && npm run type-check
```

Expected: PASS

- [ ] **Step 4: Review copy parity and explicit empty states**

Confirm:
- `zh-CN` and `en` keys are aligned
- unavailable metrics are labeled clearly
- no repeated local statistics hero/title is rendered

- [ ] **Step 5: Commit**

```bash
git add frontend/src/__tests__/settingsPage.test.tsx frontend/src/__tests__/llmStatisticsSection.test.tsx frontend/src/__tests__/runtimeStatisticsSection.test.tsx backend/tests/api/test_metrics_api.py frontend/src/i18n/locales/zh-CN/app.json frontend/src/i18n/locales/en/app.json
git commit -m "test: verify statistics center redesign"
```

---

Plan complete and saved to `docs/superpowers/plans/2026-03-24-settings-statistics-redesign.md`. Ready to execute?
