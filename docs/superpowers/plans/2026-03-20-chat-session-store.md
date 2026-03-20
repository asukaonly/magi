# Chat Session Store Implementation Plan

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace L1/session-file aggregation with a canonical `chat_sessions` table, make the frontend own session selection, and require explicit `session_id` for session-scoped chat operations.

**Architecture:** Session metadata moves into a dedicated SQLite table in the chat/L1 database domain while chat messages remain in `fact_events` and traces remain in `runtime_trace.db`. The backend stops resolving "current session" implicitly; the frontend chooses and persists the selected session explicitly.

**Tech Stack:** Python, FastAPI, sqlite3, React, Zustand, WebSocket, Vitest, pytest

---

## Chunk 1: Backend Session Store

### Task 1: Add failing backend tests for canonical session storage

**Files:**
- Modify: `/Users/asuka/code/magi/backend/tests/api/test_messages_sessions.py`
- Modify: `/Users/asuka/code/magi/backend/tests/api/test_message_dispatch_service.py`

- [ ] **Step 1: Write failing tests for `chat_sessions`-backed list/create/rename/delete**

Add tests that assert:

- sessions are listed from explicit session rows rather than inferred-only fact rows
- create returns a persisted session row
- rename updates the row title
- delete removes or soft-deletes the row
- no `current_session_id` is returned from list responses

- [ ] **Step 2: Run the targeted backend tests to verify they fail**

Run:

```bash
cd /Users/asuka/code/magi/backend && PYTHONPATH=/Users/asuka/code/magi/backend/src pytest tests/api/test_messages_sessions.py tests/api/test_message_dispatch_service.py -v
```

Expected: failures around missing `chat_sessions` table behavior and missing explicit-session validation.

- [ ] **Step 3: Implement the minimal backend session-store changes**

Modify:

- `/Users/asuka/code/magi/backend/src/magi/api/services/chat_read_service.py`
- `/Users/asuka/code/magi/backend/src/magi/api/services/message_dispatch_service.py`
- `/Users/asuka/code/magi/backend/src/magi/api/routers/messages.py`
- `/Users/asuka/code/magi/backend/src/magi/websocket/handlers.py`

Implementation requirements:

- create and initialize a `chat_sessions` table
- read session list from the table
- create/rename/delete sessions against the table
- remove `current_session_by_user` and session metadata file reads/writes
- require explicit `session_id` for send/history/trace/clear and websocket send/history
- remove `/messages/session/current` and websocket `get_current_session`

- [ ] **Step 4: Run the same backend tests to verify they pass**

Run:

```bash
cd /Users/asuka/code/magi/backend && PYTHONPATH=/Users/asuka/code/magi/backend/src pytest tests/api/test_messages_sessions.py tests/api/test_message_dispatch_service.py -v
```

Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add /Users/asuka/code/magi/backend/tests/api/test_messages_sessions.py /Users/asuka/code/magi/backend/tests/api/test_message_dispatch_service.py /Users/asuka/code/magi/backend/src/magi/api/services/chat_read_service.py /Users/asuka/code/magi/backend/src/magi/api/services/message_dispatch_service.py /Users/asuka/code/magi/backend/src/magi/api/routers/messages.py /Users/asuka/code/magi/backend/src/magi/websocket/handlers.py
git commit -m "refactor: add canonical chat session store"
```

## Chunk 2: Runtime Session Service Cleanup

### Task 2: Make runtime session handling explicit and file-free

**Files:**
- Modify: `/Users/asuka/code/magi/backend/tests/agent/test_chat_task_agent_orchestration.py`
- Modify: `/Users/asuka/code/magi/backend/tests/agent/test_chat_handlers.py`
- Modify: `/Users/asuka/code/magi/backend/src/magi/agent/task_agents/chat/session_service.py`
- Modify: `/Users/asuka/code/magi/backend/src/magi/agent/task_agents/chat_task_agent.py`
- Modify: `/Users/asuka/code/magi/backend/src/magi/agent/task_agents/chat/postprocess_service.py`

- [ ] **Step 1: Write failing runtime tests for explicit session ownership**

Add tests that assert:

- runtime chat context requires `session_id` from the incoming fact
- `ChatSessionService` no longer loads or saves `chat_sessions.json`
- history cache continues to work for explicit `(user_id, session_id)` pairs

- [ ] **Step 2: Run the targeted runtime tests to verify they fail**

Run:

```bash
cd /Users/asuka/code/magi/backend && PYTHONPATH=/Users/asuka/code/magi/backend/src pytest tests/agent/test_chat_handlers.py tests/agent/test_chat_task_agent_orchestration.py -v
```

Expected: FAIL on old current-session assumptions.

- [ ] **Step 3: Implement the minimal runtime cleanup**

Implementation requirements:

- remove persistent current-session state from `ChatSessionService`
- keep only history/tool caches keyed by explicit `user_id` + `session_id`
- require `session_id` in chat runtime context construction
- drop `ChatTaskAgent` helpers that expose backend-style current-session creation/resolution

- [ ] **Step 4: Run the same runtime tests to verify they pass**

Run:

```bash
cd /Users/asuka/code/magi/backend && PYTHONPATH=/Users/asuka/code/magi/backend/src pytest tests/agent/test_chat_handlers.py tests/agent/test_chat_task_agent_orchestration.py -v
```

Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add /Users/asuka/code/magi/backend/tests/agent/test_chat_handlers.py /Users/asuka/code/magi/backend/tests/agent/test_chat_task_agent_orchestration.py /Users/asuka/code/magi/backend/src/magi/agent/task_agents/chat/session_service.py /Users/asuka/code/magi/backend/src/magi/agent/task_agents/chat_task_agent.py /Users/asuka/code/magi/backend/src/magi/agent/task_agents/chat/postprocess_service.py
git commit -m "refactor: remove backend current session state"
```

## Chunk 3: Session Metadata Projection

### Task 3: Keep `chat_sessions` metadata updated from chat facts

**Files:**
- Modify: `/Users/asuka/code/magi/backend/tests/memory/l1/test_event_store.py`
- Modify: `/Users/asuka/code/magi/backend/tests/api/test_messages_sessions.py`
- Modify: `/Users/asuka/code/magi/backend/src/magi/memory/l1/event_store.py`
- Modify: `/Users/asuka/code/magi/backend/src/magi/api/services/chat_read_service.py`

- [ ] **Step 1: Write failing tests for session metadata projection**

Add tests that assert:

- user messages update `last_user_message_preview`, `last_message_preview`, `last_user_message_at`, `last_message_at`, and `message_count`
- assistant messages update `last_message_preview`, `last_message_at`, and `message_count`
- empty or irrelevant events do not mutate `chat_sessions`

- [ ] **Step 2: Run the targeted projection tests to verify they fail**

Run:

```bash
cd /Users/asuka/code/magi/backend && PYTHONPATH=/Users/asuka/code/magi/backend/src pytest tests/memory/l1/test_event_store.py tests/api/test_messages_sessions.py -v
```

Expected: FAIL because session rows are not yet updated from persisted chat facts.

- [ ] **Step 3: Implement the minimal projection path**

Implementation requirements:

- update `chat_sessions` transactionally when chat facts are persisted
- preserve explicit title values already stored on the session row
- avoid rebuilding session list from L1 facts

- [ ] **Step 4: Run the same projection tests to verify they pass**

Run:

```bash
cd /Users/asuka/code/magi/backend && PYTHONPATH=/Users/asuka/code/magi/backend/src pytest tests/memory/l1/test_event_store.py tests/api/test_messages_sessions.py -v
```

Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add /Users/asuka/code/magi/backend/tests/memory/l1/test_event_store.py /Users/asuka/code/magi/backend/tests/api/test_messages_sessions.py /Users/asuka/code/magi/backend/src/magi/memory/l1/event_store.py /Users/asuka/code/magi/backend/src/magi/api/services/chat_read_service.py
git commit -m "feat: project chat facts into session rows"
```

## Chunk 4: Frontend Session Ownership

### Task 4: Make the frontend own selected session state

**Files:**
- Modify: `/Users/asuka/code/magi/frontend/src/api/modules/messages.ts`
- Modify: `/Users/asuka/code/magi/frontend/src/components/layout/Sidebar.tsx`
- Modify: `/Users/asuka/code/magi/frontend/src/pages/Chat.tsx`
- Modify: `/Users/asuka/code/magi/frontend/src/realtime/provider.tsx`
- Modify: `/Users/asuka/code/magi/frontend/src/stores/conversation-store.ts`
- Modify: `/Users/asuka/code/magi/frontend/src/__tests__/sidebarNavigation.test.tsx`
- Modify: `/Users/asuka/code/magi/frontend/src/__tests__/chatPage.test.tsx`
- Modify: `/Users/asuka/code/magi/frontend/src/__tests__/realtimeProvider.test.tsx`
- Modify: `/Users/asuka/code/magi/frontend/src/__tests__/conversationStore.test.ts`

- [ ] **Step 1: Write failing frontend tests for explicit session selection**

Add tests that assert:

- session list drives initial selection
- frontend persists last selected session locally
- missing-session chat sends are prevented client-side
- no code asks the backend for `current_session`

- [ ] **Step 2: Run the targeted frontend tests to verify they fail**

Run:

```bash
cd /Users/asuka/code/magi/frontend && npm test -- --run src/__tests__/sidebarNavigation.test.tsx src/__tests__/chatPage.test.tsx src/__tests__/realtimeProvider.test.tsx src/__tests__/conversationStore.test.ts
```

Expected: FAIL on old current-session message flow and API expectations.

- [ ] **Step 3: Implement the minimal frontend rewrite**

Implementation requirements:

- remove `getCurrentSession` usage and related websocket messaging
- initialize selected session from list results + local persistence
- require explicit session selection before requesting history or sending messages
- adapt API typing to the new backend contracts

- [ ] **Step 4: Run the same frontend tests to verify they pass**

Run:

```bash
cd /Users/asuka/code/magi/frontend && npm test -- --run src/__tests__/sidebarNavigation.test.tsx src/__tests__/chatPage.test.tsx src/__tests__/realtimeProvider.test.tsx src/__tests__/conversationStore.test.ts
```

Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add /Users/asuka/code/magi/frontend/src/api/modules/messages.ts /Users/asuka/code/magi/frontend/src/components/layout/Sidebar.tsx /Users/asuka/code/magi/frontend/src/pages/Chat.tsx /Users/asuka/code/magi/frontend/src/realtime/provider.tsx /Users/asuka/code/magi/frontend/src/stores/conversation-store.ts /Users/asuka/code/magi/frontend/src/__tests__/sidebarNavigation.test.tsx /Users/asuka/code/magi/frontend/src/__tests__/chatPage.test.tsx /Users/asuka/code/magi/frontend/src/__tests__/realtimeProvider.test.tsx /Users/asuka/code/magi/frontend/src/__tests__/conversationStore.test.ts
git commit -m "refactor: let frontend own chat session selection"
```

## Chunk 5: Verification And Documentation

### Task 5: Verify end-to-end behavior and update architecture docs

**Files:**
- Modify: `/Users/asuka/code/magi/docs/task-agent-runtime-architecture.md`
- Modify: `/Users/asuka/code/magi/docs/project-overview.md`

- [ ] **Step 1: Update docs to reflect canonical session storage**

Document:

- `chat_sessions` as a first-class entity
- frontend-owned current-session selection
- removal of backend session fallback and `chat_sessions.json`

- [ ] **Step 2: Run focused backend and frontend verification**

Run:

```bash
cd /Users/asuka/code/magi/backend && PYTHONPATH=/Users/asuka/code/magi/backend/src pytest tests/api/test_messages_sessions.py tests/api/test_message_dispatch_service.py tests/agent/test_chat_handlers.py tests/agent/test_chat_task_agent_orchestration.py tests/memory/l1/test_event_store.py -v
cd /Users/asuka/code/magi/frontend && npm test -- --run src/__tests__/sidebarNavigation.test.tsx src/__tests__/chatPage.test.tsx src/__tests__/realtimeProvider.test.tsx src/__tests__/conversationStore.test.ts
```

Expected: PASS

- [ ] **Step 3: Run broader regression verification**

Run:

```bash
cd /Users/asuka/code/magi/backend && PYTHONPATH=/Users/asuka/code/magi/backend/src pytest tests/api tests/agent -v
cd /Users/asuka/code/magi/frontend && npm test -- --run src/__tests__/chatTraceState.test.ts src/__tests__/toolchainDrawer.test.tsx src/__tests__/memoryRoutes.test.tsx
```

Expected: PASS

- [ ] **Step 4: Commit**

```bash
git add /Users/asuka/code/magi/docs/task-agent-runtime-architecture.md /Users/asuka/code/magi/docs/project-overview.md
git commit -m "docs: document canonical chat session storage"
```
