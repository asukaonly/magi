# Sidebar Memory IA Implementation Plan

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Restore the approved desktop sidebar information architecture on `main`, with expandable conversation and memory navigation plus settings-owned personality configuration.

**Architecture:** Keep the current shell structure and memory route family, but simplify shell state to the approved top-level sections. Update route helpers, sidebar, header, and settings in one focused frontend slice so navigation behavior, active highlighting, and overlay behavior stay consistent.

**Tech Stack:** React 18, TypeScript, React Router 6, Zustand, i18next, Vitest, Testing Library

---

## Chunk 1: Navigation State And Sidebar Behavior

### Task 1: Lock the approved shell behavior with tests

**Files:**
- Modify: `frontend/src/__tests__/chatShell.test.tsx`
- Modify: `frontend/src/__tests__/sidebarNavigation.test.tsx`
- Modify: `frontend/src/__tests__/headerNavigation.test.tsx`

- [ ] **Step 1: Write the failing tests**

Add expectations for:
- `conversation` as the active chat section
- no standalone `personality` shell action
- expandable memory navigation with six second-level entries

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd frontend && npm run test -- src/__tests__/chatShell.test.tsx src/__tests__/sidebarNavigation.test.tsx src/__tests__/headerNavigation.test.tsx`
Expected: FAIL because the current shell still renders the old personality action and legacy memory navigation.

- [ ] **Step 3: Commit**

```bash
git add frontend/src/__tests__/chatShell.test.tsx frontend/src/__tests__/sidebarNavigation.test.tsx frontend/src/__tests__/headerNavigation.test.tsx
git commit -m "test: codify sidebar memory navigation"
```

### Task 2: Implement the new shell navigation model

**Files:**
- Modify: `frontend/src/stores/chat-shell.ts`
- Modify: `frontend/src/pages/chat-route-helpers.ts`
- Modify: `frontend/src/components/layout/Sidebar.tsx`
- Modify: `frontend/src/components/layout/Header.tsx`
- Modify: `frontend/src/pages/Settings.tsx`

- [ ] **Step 1: Write the minimal state and route updates**

Update the shell panel model to use:
- `conversation`
- `timeline`
- `memory`
- `settings`
- `none`

Map `/chat` and `/` to `conversation`, map `/memory/*` and `/events` to `memory`, and stop treating `/personality` as a sidebar shell panel.

- [ ] **Step 2: Implement the sidebar and header changes**

Make `对话` a first-level expandable button with the existing new-session icon. Remove the standalone personality action. Make `记忆` expand into:
- `总览`
- `工作台记忆`
- `事件记忆`
- `知识记忆`
- `摘要反思记忆`
- `工具技能记忆`

Keep `设置` opening the current settings route and keep personality configuration inside settings.

- [ ] **Step 3: Run focused tests to verify green**

Run: `cd frontend && npm run test -- src/__tests__/chatShell.test.tsx src/__tests__/sidebarNavigation.test.tsx src/__tests__/headerNavigation.test.tsx`
Expected: PASS

- [ ] **Step 4: Commit**

```bash
git add frontend/src/stores/chat-shell.ts frontend/src/pages/chat-route-helpers.ts frontend/src/components/layout/Sidebar.tsx frontend/src/components/layout/Header.tsx frontend/src/pages/Settings.tsx
git commit -m "feat: restore sidebar memory navigation"
```

## Chunk 2: Regression Verification

### Task 3: Verify routing and typing still hold

**Files:**
- Test: `frontend/src/__tests__/memoryRoutes.test.tsx`
- Test: `frontend/src/__tests__/appShellRouting.test.tsx`

- [ ] **Step 1: Run targeted regression tests**

Run: `cd frontend && npm run test -- src/__tests__/memoryRoutes.test.tsx src/__tests__/appShellRouting.test.tsx`
Expected: PASS

- [ ] **Step 2: Run type-check**

Run: `cd frontend && npm run type-check`
Expected: PASS

- [ ] **Step 3: Run full frontend tests**

Run: `cd frontend && npm run test`
Expected: PASS with only pre-existing warnings.

- [ ] **Step 4: Commit**

```bash
git add frontend/src
git commit -m "test: verify sidebar routing regressions"
```
