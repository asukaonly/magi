# Memory Settings Subpages Implementation Plan

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Split the settings memory section into grouped subpages with dedicated layouts while keeping the existing draft/save configuration flow intact.

**Architecture:** Extend the settings navigation model so `memory` becomes a grouped family, then replace the single stacked memory section with six dedicated child sections backed by the existing `draftConfig.memory.l0-l4` structure. Keep state and save behavior in `useSettings`, but move per-page rendering into focused helpers/components so each memory subpage can own its own layout.

**Tech Stack:** React 18, TypeScript, Zustand theme store, Vitest, Testing Library, TailwindCSS.

---

## File Map

- Modify: `frontend/src/constants/settings.ts`
  - Add the six memory child nav items under the `memory` group.
- Modify: `frontend/src/types/settings.ts`
  - Narrow memory child section ids and keep nav typing aligned.
- Modify: `frontend/src/hooks/useSettings.ts`
  - Teach grouped navigation about the memory family and default landing on `memoryGeneral`.
- Modify: `frontend/src/pages/Settings.tsx`
  - Replace the old stacked memory cards with per-subpage rendering.
- Create: `frontend/src/components/settings/memory/MemoryGeneralSettingsSection.tsx`
  - Memory-wide settings surface.
- Create: `frontend/src/components/settings/memory/MemoryWorkbenchSettingsSection.tsx`
  - Workbench memory page.
- Create: `frontend/src/components/settings/memory/MemoryEventsSettingsSection.tsx`
  - Event memory page.
- Create: `frontend/src/components/settings/memory/MemoryKnowledgeSettingsSection.tsx`
  - Knowledge memory page.
- Create: `frontend/src/components/settings/memory/MemoryReflectionSettingsSection.tsx`
  - Reflection memory page.
- Create: `frontend/src/components/settings/memory/MemorySkillsSettingsSection.tsx`
  - Tool skill memory page.
- Modify: `frontend/src/components/settings/index.ts`
  - Export new memory settings sections if needed.
- Modify: `frontend/src/__tests__/settingsPage.test.tsx`
  - Cover grouped nav, memory child routing, and save behavior.

## Chunk 1: Navigation And Failing Tests

### Task 1: Add failing tests for grouped memory navigation

**Files:**
- Modify: `frontend/src/__tests__/settingsPage.test.tsx`

- [ ] **Step 1: Write the failing test**

Add tests that assert:
- clicking `settings.tabs.memory` expands memory child items
- first expand lands on `settings.tabs.memoryGeneral`
- clicking `settings.tabs.memoryKnowledge` updates the heading

- [ ] **Step 2: Run test to verify it fails**

Run: `cd frontend && npm run test -- src/__tests__/settingsPage.test.tsx`

Expected: FAIL because memory is still a leaf page.

- [ ] **Step 3: Write minimal navigation implementation**

Update:
- `frontend/src/constants/settings.ts`
- `frontend/src/types/settings.ts`
- `frontend/src/hooks/useSettings.ts`

So `memory` becomes a group with six child pages and defaults to `memoryGeneral` when expanded.

- [ ] **Step 4: Run test to verify it passes**

Run: `cd frontend && npm run test -- src/__tests__/settingsPage.test.tsx`

Expected: PASS for new grouped nav assertions.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/constants/settings.ts frontend/src/types/settings.ts frontend/src/hooks/useSettings.ts frontend/src/__tests__/settingsPage.test.tsx
git commit -m "feat: group memory settings navigation"
```

## Chunk 2: Split Memory Settings Pages

### Task 2: Extract dedicated memory subpage sections

**Files:**
- Create: `frontend/src/components/settings/memory/MemoryGeneralSettingsSection.tsx`
- Create: `frontend/src/components/settings/memory/MemoryWorkbenchSettingsSection.tsx`
- Create: `frontend/src/components/settings/memory/MemoryEventsSettingsSection.tsx`
- Create: `frontend/src/components/settings/memory/MemoryKnowledgeSettingsSection.tsx`
- Create: `frontend/src/components/settings/memory/MemoryReflectionSettingsSection.tsx`
- Create: `frontend/src/components/settings/memory/MemorySkillsSettingsSection.tsx`
- Modify: `frontend/src/pages/Settings.tsx`
- Modify: `frontend/src/components/settings/index.ts`

- [ ] **Step 1: Write the failing test**

Extend `frontend/src/__tests__/settingsPage.test.tsx` to assert:
- `memoryGeneral` renders general memory controls
- `memoryWorkbench` renders L0-only controls
- `memoryKnowledge` renders L2-only controls
- old single-page stack is no longer rendered

- [ ] **Step 2: Run test to verify it fails**

Run: `cd frontend && npm run test -- src/__tests__/settingsPage.test.tsx`

Expected: FAIL because `Settings.tsx` still renders the old combined memory page.

- [ ] **Step 3: Write minimal implementation**

Create small focused section components that receive only the draft config slices and callbacks they need. In `Settings.tsx`, switch on:
- `memoryGeneral`
- `memoryWorkbench`
- `memoryEvents`
- `memoryKnowledge`
- `memoryReflection`
- `memorySkills`

Use the product-facing labels from the main memory workspace, not `L0-L4` in the right-pane headings.

- [ ] **Step 4: Run test to verify it passes**

Run: `cd frontend && npm run test -- src/__tests__/settingsPage.test.tsx`

Expected: PASS for new section rendering assertions.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/components/settings/memory frontend/src/pages/Settings.tsx frontend/src/components/settings/index.ts frontend/src/__tests__/settingsPage.test.tsx
git commit -m "feat: split memory settings into subpages"
```

## Chunk 3: Save Flow And Regression Coverage

### Task 3: Re-anchor save tests on the new subpages

**Files:**
- Modify: `frontend/src/__tests__/settingsPage.test.tsx`

- [ ] **Step 1: Write the failing test**

Add or update save coverage so edits performed across:
- `memoryWorkbench`
- `memoryKnowledge`
- `memoryGeneral`

are still persisted through the same `configApi.update` call.

- [ ] **Step 2: Run test to verify it fails**

Run: `cd frontend && npm run test -- src/__tests__/settingsPage.test.tsx`

Expected: FAIL until the new pages wire draft mutations correctly.

- [ ] **Step 3: Write minimal implementation**

Ensure all new section components mutate the existing nested memory draft fields without introducing parallel state.

- [ ] **Step 4: Run test to verify it passes**

Run: `cd frontend && npm run test -- src/__tests__/settingsPage.test.tsx src/__tests__/sidebarNavigation.test.tsx`

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/__tests__/settingsPage.test.tsx frontend/src/pages/Settings.tsx frontend/src/components/settings/memory
git commit -m "test: cover split memory settings save flow"
```

## Chunk 4: Final Verification

### Task 4: Run focused verification for settings shell integrity

**Files:**
- No new files required

- [ ] **Step 1: Run focused settings and layout tests**

Run:

```bash
cd frontend && npm run test -- src/__tests__/settingsPage.test.tsx src/__tests__/sidebarNavigation.test.tsx
```

Expected: PASS.

- [ ] **Step 2: Run broader memory and trace regression**

Run:

```bash
cd frontend && npm run test -- src/__tests__/memoryPageDesign.test.tsx src/__tests__/toolchainDrawer.test.tsx
```

Expected: PASS.

- [ ] **Step 3: Run type-check and note unrelated failures if they persist**

Run:

```bash
cd frontend && npm run type-check
```

Expected: either PASS or only pre-existing unrelated failures documented in the task summary.

- [ ] **Step 4: Commit any final test/documentation-only adjustments**

```bash
git add frontend/src/__tests__/settingsPage.test.tsx
git commit -m "chore: verify memory settings split rollout"
```

Plan complete and saved to `docs/superpowers/plans/2026-03-23-memory-settings-subpages.md`. Ready to execute.
