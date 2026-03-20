# Sidebar Polish Implementation Plan

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Refine the desktop sidebar into the approved quieter, more professional `Editorial Rail` direction without changing navigation structure or behavior.

**Architecture:** Keep the current shell layout and sidebar logic intact, but rebalance hierarchy inside `Sidebar.tsx` through lighter primary surfaces, nested secondary rows, and quieter support controls. Protect the existing navigation behavior with focused sidebar tests and finish with targeted frontend verification.

**Tech Stack:** React 18, TypeScript, React Router 6, Zustand, i18next, TailwindCSS, Vitest, Testing Library

---

## Chunk 1: Lock the polish contract with tests

### Task 1: Add focused sidebar styling and accessibility assertions

**Files:**
- Modify: `frontend/src/__tests__/sidebarNavigation.test.tsx`

- [ ] **Step 1: Write the failing test**

Add focused assertions that cover the approved polish contract without snapshotting the whole component:
- the sidebar `<aside>` keeps the shell container role and new rail-friendly surface classes
- the active conversation button keeps its primary treatment while expanded secondary rows remain separately addressable
- the search tools still render as compact controls inside the expanded conversation section
- active memory rows remain independently selectable from the top-level memory button

- [ ] **Step 2: Run the focused test to verify it fails**

Run: `cd frontend && npm run test -- src/__tests__/sidebarNavigation.test.tsx`
Expected: FAIL because the current sidebar classes and hierarchy markers do not yet match the approved polish direction.

- [ ] **Step 3: Commit**

```bash
git add frontend/src/__tests__/sidebarNavigation.test.tsx
git commit -m "test: codify sidebar polish states"
```

## Chunk 2: Implement the sidebar polish

### Task 2: Refine sidebar hierarchy and interaction styling

**Files:**
- Modify: `frontend/src/components/layout/Sidebar.tsx`

- [ ] **Step 1: Apply the approved primary navigation refinements**

Update the primary button and icon wrapper class helpers so:
- primary buttons use lighter borders and calmer inactive states
- active buttons use a restrained tinted surface
- icon containers support hierarchy without overpowering labels
- chevrons and label spacing feel cleaner and more consistent

- [ ] **Step 2: Add nested rail treatment for expanded sections**

Restyle the expanded conversation and memory areas so:
- expanded content sits inside a subtle left-side rail
- conversation rows and memory rows read as nested entries instead of peer buttons
- active secondary rows use a lighter tint plus rail emphasis
- spacing rhythm between section header, tool row, list content, and footer becomes more intentional

- [ ] **Step 3: Quiet the search and utility controls**

Refine the search input and icon-only controls so:
- the input feels embedded and less card-like
- tool buttons share a consistent compact surface
- hover/focus states stay visible and accessible
- session overflow controls feel attached to their rows

- [ ] **Step 4: Run the focused sidebar test**

Run: `cd frontend && npm run test -- src/__tests__/sidebarNavigation.test.tsx`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add frontend/src/components/layout/Sidebar.tsx frontend/src/__tests__/sidebarNavigation.test.tsx
git commit -m "feat: polish sidebar hierarchy"
```

## Chunk 3: Verify regressions

### Task 3: Run targeted frontend verification

**Files:**
- Verify: `frontend/src/components/layout/Sidebar.tsx`
- Verify: `frontend/src/__tests__/sidebarNavigation.test.tsx`
- Verify: `frontend/src/__tests__/mainLayout.test.tsx`

- [ ] **Step 1: Run related layout and sidebar tests**

Run: `cd frontend && npm run test -- src/__tests__/sidebarNavigation.test.tsx src/__tests__/mainLayout.test.tsx`
Expected: PASS

- [ ] **Step 2: Run frontend type-check**

Run: `cd frontend && npm run type-check`
Expected: PASS

- [ ] **Step 3: Commit**

```bash
git add frontend/src/components/layout/Sidebar.tsx frontend/src/__tests__/sidebarNavigation.test.tsx
git commit -m "test: verify sidebar polish"
```
