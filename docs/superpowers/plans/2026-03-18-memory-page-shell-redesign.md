# Memory Page Shell Redesign Implementation Plan

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Remove the shared memory-page hero design and replace it with a restrained, page-owned shell across overview, workbench, events, knowledge, reflection, and skills.

**Architecture:** Reduce `MemoryPageFrame` to a thin page base that only handles outer layout and optional actions. Move first-screen composition responsibility into each memory page so every route can surface its own priorities without inheriting the same hero structure.

**Tech Stack:** React 18, TypeScript, React Router 6, TailwindCSS, i18next, Vitest, Testing Library

---

## Chunk 1: Lock The New Shell Expectations

### Task 1: Update design tests for the hero removal

**Files:**
- Modify: `frontend/src/__tests__/memoryPageDesign.test.tsx`

- [ ] **Step 1: Write the failing test**

Add assertions that memory pages no longer render the shared hero marker and instead expose a compact title row or page header area.

- [ ] **Step 2: Run the focused test to verify red**

Run: `cd frontend && npm run test -- src/__tests__/memoryPageDesign.test.tsx`
Expected: FAIL because the current pages still render `data-testid="memory-page-hero"`.

- [ ] **Step 3: Commit**

```bash
git add frontend/src/__tests__/memoryPageDesign.test.tsx
git commit -m "test: codify memory shell redesign"
```

## Chunk 2: Replace The Shared Hero Template

### Task 2: Refactor the shared frame into a thin base

**Files:**
- Modify: `frontend/src/pages/memory-pages/MemoryPageFrame.tsx`

- [ ] **Step 1: Implement the minimal shared base**

Remove hero-specific props and markup, keeping only:
- outer layout
- compact page title row
- actions slot
- optional filters region
- reusable panel and field styling

- [ ] **Step 2: Run the focused test**

Run: `cd frontend && npm run test -- src/__tests__/memoryPageDesign.test.tsx`
Expected: still FAIL because page components have not been adapted yet.

## Chunk 3: Give Each Memory Page Its Own First Screen

### Task 3: Adapt overview and layer pages to the new shell

**Files:**
- Modify: `frontend/src/pages/memory-pages/MemoryOverviewPage.tsx`
- Modify: `frontend/src/pages/memory-pages/MemoryWorkbenchPage.tsx`
- Modify: `frontend/src/pages/memory-pages/MemoryEventsPage.tsx`
- Modify: `frontend/src/pages/memory-pages/MemoryKnowledgePage.tsx`
- Modify: `frontend/src/pages/memory-pages/MemoryReflectionPage.tsx`
- Modify: `frontend/src/pages/memory-pages/MemorySkillsPage.tsx`

- [ ] **Step 1: Give overview its own entry-page structure**

Make overview emphasize:
- search
- compact summary signals
- layer entry points
- recent changes

- [ ] **Step 2: Give each layer page its own first-screen layout**

Ensure:
- workbench emphasizes sessions and selected-session detail
- events emphasizes filters and event flow
- knowledge emphasizes structured knowledge modules
- reflection emphasizes reading-oriented summary flow
- skills emphasizes capability inventory

- [ ] **Step 3: Run the focused test to verify green**

Run: `cd frontend && npm run test -- src/__tests__/memoryPageDesign.test.tsx`
Expected: PASS

## Chunk 4: Regression Verification

### Task 4: Verify routing, typing, and full frontend tests

**Files:**
- Test: `frontend/src/__tests__/memoryRoutes.test.tsx`
- Test: `frontend/src/__tests__/sidebarNavigation.test.tsx`

- [ ] **Step 1: Run route and shell regressions**

Run: `cd frontend && npm run test -- src/__tests__/memoryPageDesign.test.tsx src/__tests__/memoryRoutes.test.tsx src/__tests__/sidebarNavigation.test.tsx src/__tests__/appShellRouting.test.tsx`
Expected: PASS

- [ ] **Step 2: Run type-check**

Run: `cd frontend && npm run type-check`
Expected: PASS

- [ ] **Step 3: Run full frontend tests**

Run: `cd frontend && npm run test`
Expected: PASS with only pre-existing warnings.

- [ ] **Step 4: Commit**

```bash
git add frontend/src/pages/memory-pages frontend/src/__tests__/memoryPageDesign.test.tsx
git commit -m "feat: redesign memory page shells"
```
