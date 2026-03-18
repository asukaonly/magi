# Memory Knowledge In-Page Tabs Implementation Plan

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Turn the L2 knowledge page into a single-route workspace with eight in-page tabs that each surface a focused knowledge module.

**Architecture:** Keep `MemoryKnowledgePage` responsible for shared filters and tab state, then refactor the current L2 surface so each tab renders only the content for one knowledge slice. Reuse the restrained memory page styling instead of introducing a new visual shell.

**Tech Stack:** React 18, TypeScript, TailwindCSS, Radix Tabs, i18next, Vitest, Testing Library

---

## Chunk 1: Lock The New Knowledge-Page Behavior

### Task 1: Add a failing knowledge-page tab test

**Files:**
- Create: `frontend/src/__tests__/memoryKnowledgePageTabs.test.tsx`

- [ ] **Step 1: Write the failing test**

Render `MemoryKnowledgePage` with mocked memory data and assert that:
- an in-page tab list is present
- the default tab shows overview content
- switching to another tab reveals that section and hides overview-only content

- [ ] **Step 2: Run the focused test to verify red**

Run: `cd frontend && npm run test -- src/__tests__/memoryKnowledgePageTabs.test.tsx`
Expected: FAIL because the current page has no in-page tab layout.

- [ ] **Step 3: Commit**

```bash
git add frontend/src/__tests__/memoryKnowledgePageTabs.test.tsx
git commit -m "test: codify knowledge page tabs"
```

## Chunk 2: Build The In-Page Tab Workspace

### Task 2: Refactor L2 into tab-owned sections

**Files:**
- Modify: `frontend/src/pages/memory-pages/MemoryKnowledgePage.tsx`
- Modify: `frontend/src/components/memory/L2Tab.tsx`
- Modify: `frontend/src/components/memory/index.ts`
- Modify: `frontend/src/i18n/locales/zh-CN/app.json`
- Modify: `frontend/src/i18n/locales/en/app.json`

- [ ] **Step 1: Add the tab row and tab state**

Use the page component to render the eight-tab navigation and keep the existing query/entity filters above it.

- [ ] **Step 2: Split the L2 content into focused sections**

Refactor `L2Tab` so it can render one section at a time for:
- overview
- knowledge graph
- theory of mind
- mind snapshots
- lab
- canonical entities
- recent mentions
- conflict rules

- [ ] **Step 3: Add i18n labels and any empty-state copy needed by the new tabs**

Keep `zh-CN` and `en` aligned.

- [ ] **Step 4: Run the focused test to verify green**

Run: `cd frontend && npm run test -- src/__tests__/memoryKnowledgePageTabs.test.tsx`
Expected: PASS

## Chunk 3: Regression Verification

### Task 3: Run memory-page regression checks

**Files:**
- Test: `frontend/src/__tests__/memoryPageDesign.test.tsx`
- Test: `frontend/src/__tests__/memoryRoutes.test.tsx`
- Test: `frontend/src/__tests__/sidebarNavigation.test.tsx`

- [ ] **Step 1: Run targeted regressions**

Run: `cd frontend && npm run test -- src/__tests__/memoryKnowledgePageTabs.test.tsx src/__tests__/memoryPageDesign.test.tsx src/__tests__/memoryRoutes.test.tsx src/__tests__/sidebarNavigation.test.tsx src/__tests__/appShellRouting.test.tsx`
Expected: PASS

- [ ] **Step 2: Run type-check**

Run: `cd frontend && npm run type-check`
Expected: PASS

- [ ] **Step 3: Run full frontend tests**

Run: `cd frontend && npm run test`
Expected: PASS with only pre-existing warnings.

- [ ] **Step 4: Commit**

```bash
git add frontend/src/pages/memory-pages/MemoryKnowledgePage.tsx frontend/src/components/memory/L2Tab.tsx frontend/src/i18n/locales/zh-CN/app.json frontend/src/i18n/locales/en/app.json frontend/src/__tests__/memoryKnowledgePageTabs.test.tsx
git commit -m "feat: tabify memory knowledge page"
```
