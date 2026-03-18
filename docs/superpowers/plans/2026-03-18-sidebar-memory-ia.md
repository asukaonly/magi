# Sidebar And Memory IA Implementation Plan

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Rebuild the desktop shell sidebar around conversation, timeline, memory, and settings, then split memory into an overview page plus five independent layer pages.

**Architecture:** Refactor the shell sidebar into expandable primary sections for conversation and memory, keep settings as an overlay route, and replace the current tabbed memory page with dedicated memory routes and page components. Reuse existing memory data hooks for the first pass so the information architecture can change now without blocking future page-specific design work.

**Tech Stack:** React 18, TypeScript, React Router 6, Zustand, i18next, Vitest, Testing Library

---

## File Map

### Existing files likely to modify

- `frontend/src/components/layout/Sidebar.tsx`
  Rebuild primary nav structure, expansion behavior, memory secondary items, and conversation header button row.
- `frontend/src/stores/chat-shell.ts`
  Simplify top-level panel types and add expansion state if needed.
- `frontend/src/pages/chat-route-helpers.ts`
  Update pathname-to-panel mapping and helpers for memory route family.
- `frontend/src/router/index.tsx`
  Add dedicated memory routes and remove reliance on the old single memory route.
- `frontend/src/i18n/locales/zh-CN/app.json`
  Add new sidebar and memory navigation labels.
- `frontend/src/i18n/locales/en/app.json`
  Keep i18n keys aligned with the Chinese locale.
- `frontend/src/__tests__/sidebarNavigation.test.tsx`
  Update shell navigation coverage for new structure.

### Existing files that may be repurposed or trimmed

- `frontend/src/pages/Memory.tsx`
  Convert from tab host into memory section container or redirect helper.
- `frontend/src/pages/Events.tsx`
  Split current content into reusable pieces or retire once layer pages exist.

### New files to create

- `frontend/src/pages/memory/MemoryOverviewPage.tsx`
  Overview skeleton with search and stats panels.
- `frontend/src/pages/memory/MemoryWorkbenchPage.tsx`
  L0-focused page scaffold with layer-specific filter area.
- `frontend/src/pages/memory/MemoryEventsPage.tsx`
  L1-focused page scaffold with layer-specific filter area.
- `frontend/src/pages/memory/MemoryKnowledgePage.tsx`
  L2-focused page scaffold with layer-specific filter area.
- `frontend/src/pages/memory/MemoryReflectionPage.tsx`
  L3-focused page scaffold with layer-specific filter area.
- `frontend/src/pages/memory/MemorySkillsPage.tsx`
  L4-focused page scaffold with layer-specific filter area.
- `frontend/src/pages/memory/MemoryPageFrame.tsx`
  Shared lightweight shell for per-page heading, filters, and content slot.
- `frontend/src/pages/memory/index.ts`
  Consolidated exports for the new memory route components.
- `frontend/src/__tests__/memoryRoutes.test.tsx`
  Route-level tests for each memory destination.

## Chunk 1: Document And Prepare Navigation Model

### Task 1: Align shell panel state with the approved IA

**Files:**
- Modify: `frontend/src/stores/chat-shell.ts`
- Modify: `frontend/src/pages/chat-route-helpers.ts`
- Test: `frontend/src/__tests__/sidebarNavigation.test.tsx`

- [ ] **Step 1: Write or update failing tests for top-level shell sections**

Add assertions that the shell recognizes `conversation`, `timeline`, `memory`, and `settings`, and that memory subroutes still map to the `memory` primary section.

- [ ] **Step 2: Run the focused sidebar test to verify failure**

Run: `cd frontend && npm run test -- sidebarNavigation.test.tsx`
Expected: failing assertions around old panel names or missing routes.

- [ ] **Step 3: Update shell state and route helpers**

Implement the minimal state changes:

- remove standalone personality panel handling
- ensure memory subroutes resolve to the `memory` section
- keep settings overlay behavior intact

- [ ] **Step 4: Re-run the focused sidebar test**

Run: `cd frontend && npm run test -- sidebarNavigation.test.tsx`
Expected: the updated shell state assertions pass or only fail on not-yet-implemented UI changes.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/stores/chat-shell.ts frontend/src/pages/chat-route-helpers.ts frontend/src/__tests__/sidebarNavigation.test.tsx
git commit -m "refactor: align shell panel model"
```

## Chunk 2: Rebuild The Sidebar

### Task 2: Implement expandable conversation and memory navigation

**Files:**
- Modify: `frontend/src/components/layout/Sidebar.tsx`
- Modify: `frontend/src/i18n/locales/zh-CN/app.json`
- Modify: `frontend/src/i18n/locales/en/app.json`
- Test: `frontend/src/__tests__/sidebarNavigation.test.tsx`

- [ ] **Step 1: Extend tests for the new sidebar structure**

Add tests that cover:

- primary buttons `对话 / 时间线 / 记忆 / 设置`
- `+` button beside conversation
- conversation expansion showing session history only
- memory expansion showing overview plus five layer entries
- settings still opening via the same action

- [ ] **Step 2: Run the focused sidebar test to verify failure**

Run: `cd frontend && npm run test -- sidebarNavigation.test.tsx`
Expected: failures because the old flat utility layout still renders.

- [ ] **Step 3: Rebuild `Sidebar.tsx` with the new IA**

Implement:

- unified primary button styling
- expandable conversation group with inline history list
- expandable memory group with six secondary items
- route-aware active highlighting for both primary and secondary entries
- preserved new-chat `+` action

- [ ] **Step 4: Add aligned i18n labels**

Add only the keys needed for:

- new conversation label text if renamed from the old nav key
- memory overview and memory layer labels
- optional expand/collapse accessibility labels if introduced

- [ ] **Step 5: Re-run sidebar tests**

Run: `cd frontend && npm run test -- sidebarNavigation.test.tsx`
Expected: sidebar tests pass.

- [ ] **Step 6: Commit**

```bash
git add frontend/src/components/layout/Sidebar.tsx frontend/src/i18n/locales/zh-CN/app.json frontend/src/i18n/locales/en/app.json frontend/src/__tests__/sidebarNavigation.test.tsx
git commit -m "feat: redesign shell sidebar navigation"
```

## Chunk 3: Split Memory Into Dedicated Routes

### Task 3: Add memory route family and page scaffolds

**Files:**
- Modify: `frontend/src/router/index.tsx`
- Modify: `frontend/src/pages/Memory.tsx`
- Create: `frontend/src/pages/memory/MemoryPageFrame.tsx`
- Create: `frontend/src/pages/memory/MemoryOverviewPage.tsx`
- Create: `frontend/src/pages/memory/MemoryWorkbenchPage.tsx`
- Create: `frontend/src/pages/memory/MemoryEventsPage.tsx`
- Create: `frontend/src/pages/memory/MemoryKnowledgePage.tsx`
- Create: `frontend/src/pages/memory/MemoryReflectionPage.tsx`
- Create: `frontend/src/pages/memory/MemorySkillsPage.tsx`
- Create: `frontend/src/pages/memory/index.ts`
- Test: `frontend/src/__tests__/memoryRoutes.test.tsx`

- [ ] **Step 1: Write failing route tests**

Cover:

- `/memory/overview`
- `/memory/workbench`
- `/memory/events`
- `/memory/knowledge`
- `/memory/reflection`
- `/memory/skills`

Assert that each route renders the expected page heading or marker.

- [ ] **Step 2: Run the focused route test to verify failure**

Run: `cd frontend && npm run test -- memoryRoutes.test.tsx`
Expected: route lookup failures because these paths do not exist yet.

- [ ] **Step 3: Add route family and page exports**

Implement the route map and export helpers. Keep `Memory.tsx` as a compatibility redirect only if the router still needs a shell entry point; otherwise remove its old tab-host responsibility.

- [ ] **Step 4: Create scaffold pages**

Build a lightweight shared frame and six pages with:

- route-specific titles
- placeholder filter section per page
- overview search and stats placeholders
- space for future richer content

- [ ] **Step 5: Re-run the focused route test**

Run: `cd frontend && npm run test -- memoryRoutes.test.tsx`
Expected: route tests pass.

- [ ] **Step 6: Commit**

```bash
git add frontend/src/router/index.tsx frontend/src/pages/Memory.tsx frontend/src/pages/memory frontend/src/__tests__/memoryRoutes.test.tsx
git commit -m "feat: split memory into route pages"
```

## Chunk 4: Migrate Existing Memory Content Into First-Pass Layer Pages

### Task 4: Wire current memory data into the new page set

**Files:**
- Modify: `frontend/src/hooks/useMemory.ts`
- Modify: `frontend/src/pages/memory/MemoryOverviewPage.tsx`
- Modify: `frontend/src/pages/memory/MemoryWorkbenchPage.tsx`
- Modify: `frontend/src/pages/memory/MemoryEventsPage.tsx`
- Modify: `frontend/src/pages/memory/MemoryKnowledgePage.tsx`
- Modify: `frontend/src/pages/memory/MemoryReflectionPage.tsx`
- Modify: `frontend/src/pages/memory/MemorySkillsPage.tsx`
- Test: `frontend/src/__tests__/memoryRoutes.test.tsx`

- [ ] **Step 1: Add or update failing tests for first-pass content wiring**

Cover at least:

- overview renders search/stat placeholders
- each layer page renders its own filter area
- existing layer-specific content appears on the matching page

- [ ] **Step 2: Run focused tests to verify failure**

Run: `cd frontend && npm run test -- memoryRoutes.test.tsx`
Expected: missing content or filter assertions fail.

- [ ] **Step 3: Move current tab content into dedicated pages**

Reuse the existing memory hook and extracted components where practical:

- L0 content into the workbench page
- L1 content into the events page
- L2 content into the knowledge page
- L3 content into the reflection page
- L4 content into the skills page

Do not keep the old shared tabs container.

- [ ] **Step 4: Re-run focused tests**

Run: `cd frontend && npm run test -- memoryRoutes.test.tsx`
Expected: page wiring tests pass.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/hooks/useMemory.ts frontend/src/pages/memory frontend/src/__tests__/memoryRoutes.test.tsx
git commit -m "refactor: move memory layers to dedicated pages"
```

## Chunk 5: Full Frontend Verification

### Task 5: Verify the end-to-end shell and memory changes

**Files:**
- Modify only if verification reveals regressions

- [ ] **Step 1: Run sidebar and memory tests together**

Run: `cd frontend && npm run test -- sidebarNavigation.test.tsx memoryRoutes.test.tsx`
Expected: targeted navigation tests pass.

- [ ] **Step 2: Run full frontend type check**

Run: `cd frontend && npm run type-check`
Expected: exit code 0.

- [ ] **Step 3: Run full frontend test suite if feasible**

Run: `cd frontend && npm run test`
Expected: exit code 0. If unrelated failures appear, record them clearly.

- [ ] **Step 4: Commit any final verification-driven fixes**

```bash
git add .
git commit -m "test: verify sidebar and memory navigation"
```

Plan complete and saved to `docs/superpowers/plans/2026-03-18-sidebar-memory-ia.md`. Ready to execute?
