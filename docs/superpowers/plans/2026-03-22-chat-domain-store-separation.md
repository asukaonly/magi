# Chat Domain Store Separation Implementation Plan

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Fully separate chat transcript and turn-state persistence from L1 memory and runtime notifications so chat becomes its own durable domain with a dedicated source of truth.

**Architecture:** Introduce a dedicated SQLite-backed chat store that owns `chat_sessions`, `chat_turns`, and `chat_messages`, make all user-visible chat writes commit there before notifications are emitted, and demote L1 to an asynchronous projection target for canonical user/final-assistant content only. Runtime trace remains in `runtime_trace.db` for execution observability, and WebSocket notifications become live fan-out of already-committed chat state rather than the source of truth.

**Tech Stack:** Python, FastAPI, sqlite3, aiosqlite, React, Zustand, Vitest, pytest, SQLite

---

## File Map

### Backend chat persistence

- Create: `/Users/asuka/code/magi/backend/src/magi/chat/__init__.py`
  Export chat-domain contracts and store helpers.

- Create: `/Users/asuka/code/magi/backend/src/magi/chat/contracts.py`
  Define typed chat session, turn, and message contracts plus enums for `message_kind`, `response_mode`, and `turn_status`.

- Create: `/Users/asuka/code/magi/backend/src/magi/chat/store.py`
  Own schema creation and all write/read operations for `chat_sessions`, `chat_turns`, and `chat_messages`.

- Create: `/Users/asuka/code/magi/backend/src/magi/chat/projector.py`
  Own asynchronous projection from committed chat messages into L1 fact events.

- Create: `/Users/asuka/code/magi/backend/src/magi/chat/migration.py`
  Backfill existing `chat_sessions` and transcript rows from L1 facts into the new chat store.

### Backend bootstrap and runtime integration

- Modify: `/Users/asuka/code/magi/backend/src/magi/utils/runtime.py`
  Add dedicated `chat_db_path`.

- Modify: `/Users/asuka/code/magi/backend/src/magi/core/database_initializer.py`
  Initialize the new chat database and its schema.

- Modify: `/Users/asuka/code/magi/backend/src/magi/bootstrap/context.py`
  Add a bootstrap slice for the chat store and projector.

- Modify: `/Users/asuka/code/magi/backend/src/magi/bootstrap/builder.py`
- Modify: `/Users/asuka/code/magi/backend/src/magi/bootstrap/api_builder.py`
- Modify: `/Users/asuka/code/magi/backend/src/magi/bootstrap/runtime_worker_builder.py`
- Modify: `/Users/asuka/code/magi/backend/src/magi/bootstrap/exports.py`
  Wire chat store ownership into both API and runtime roles.

- Create: `/Users/asuka/code/magi/backend/src/magi/chat/lifecycle.py`
  Initialize and shut down chat store and projector as lifecycle modules.

### Backend write side

- Modify: `/Users/asuka/code/magi/backend/src/magi/api/services/message_dispatch_service.py`
  Write user turns/messages to chat store before enqueueing runtime commands.

- Modify: `/Users/asuka/code/magi/backend/src/magi/agent/task_agents/chat/postprocess_service.py`
  Persist `TurnUXPlan`, interim/reaction/final messages, and turn completion into chat store before appending runtime notifications.

- Modify: `/Users/asuka/code/magi/backend/src/magi/agent/task_agents/chat/contracts.py`
  Carry stable chat-domain identifiers and turn-state payloads through execution results.

- Modify: `/Users/asuka/code/magi/backend/src/magi/agent/task_agents/common/contracts.py`
  Expose any new IDs needed at runtime boundaries.

- Modify: `/Users/asuka/code/magi/backend/src/magi/awareness/action_emitter.py`
  Stop treating `AI_RESPONSE` as transcript truth; keep only local integration semantics.

### Backend read side and transport

- Modify: `/Users/asuka/code/magi/backend/src/magi/api/services/chat_read_service.py`
  Read transcript from the new chat store instead of `fact_events`.

- Modify: `/Users/asuka/code/magi/backend/src/magi/api/services/chat_trace_read_service.py`
  Keep trace ownership, but stop assuming `fact_events` is the transcript source.

- Modify: `/Users/asuka/code/magi/backend/src/magi/api/routers/messages.py`
- Modify: `/Users/asuka/code/magi/backend/src/magi/websocket/handlers.py`
- Modify: `/Users/asuka/code/magi/backend/src/magi/websocket/bridge_lifecycle.py`
  Return chat-domain DTOs and notification payloads keyed to committed chat message state.

- Modify: `/Users/asuka/code/magi/backend/src/magi/agent/task_agents/chat/history_service.py`
  Load prompt history from chat store rather than directly from L1.

### Frontend

- Modify: `/Users/asuka/code/magi/frontend/src/api/modules/messages.ts`
- Modify: `/Users/asuka/code/magi/frontend/src/types/chat.ts`
- Modify: `/Users/asuka/code/magi/frontend/src/types/websocket.ts`
- Modify: `/Users/asuka/code/magi/frontend/src/pages/chat-state.ts`
- Modify: `/Users/asuka/code/magi/frontend/src/stores/conversation-store.ts`
- Modify: `/Users/asuka/code/magi/frontend/src/pages/Chat.tsx`
  Model chat around persisted `turn/message` records instead of notification-only transient state.

### Tests

- Create: `/Users/asuka/code/magi/backend/tests/chat/test_chat_store.py`
- Create: `/Users/asuka/code/magi/backend/tests/chat/test_chat_migration.py`
- Modify: `/Users/asuka/code/magi/backend/tests/api/test_message_dispatch_service.py`
- Modify: `/Users/asuka/code/magi/backend/tests/agent/test_chat_postprocess_service.py`
- Modify: `/Users/asuka/code/magi/backend/tests/api/test_messages_sessions.py`
- Modify: `/Users/asuka/code/magi/backend/tests/api/test_messages_router_bindings.py`
- Modify: `/Users/asuka/code/magi/backend/tests/websocket/test_bridge_lifecycle.py`
- Modify: `/Users/asuka/code/magi/backend/tests/runtime/test_process_role_bootstrap.py`
- Modify: `/Users/asuka/code/magi/frontend/src/__tests__/conversationStore.test.ts`
- Modify: `/Users/asuka/code/magi/frontend/src/__tests__/chatPage.test.tsx`
- Modify: `/Users/asuka/code/magi/frontend/src/__tests__/chatTraceState.test.ts`

## Chunk 1: Dedicated Chat Store Foundation

### Task 1: Add failing backend tests for the dedicated chat schema

**Files:**
- Create: `/Users/asuka/code/magi/backend/tests/chat/test_chat_store.py`
- Create: `/Users/asuka/code/magi/backend/tests/chat/test_chat_migration.py`

- [ ] **Step 1: Write failing tests for `chat_sessions`, `chat_turns`, and `chat_messages`**

Add tests that assert:

- `chat_sessions` stores session metadata only
- `chat_turns` stores turn lifecycle and UX-plan state
- `chat_messages` stores ordered visible transcript items
- a user turn can exist with no assistant final message
- an interim message can later be replaced by a final assistant message

- [ ] **Step 2: Run the targeted backend tests to verify they fail**

Run:

```bash
cd /Users/asuka/code/magi/backend && PYTHONPATH=/Users/asuka/code/magi/backend/src pytest tests/chat/test_chat_store.py tests/chat/test_chat_migration.py -q
```

Expected: FAIL because the chat store package and schema do not exist yet.

- [ ] **Step 3: Implement the minimal chat store foundation**

Implementation requirements:

- add `RuntimePaths.chat_db_path`
- create a dedicated SQLite database under `~/.magi/data/chat.db`
- define tables:
  - `chat_sessions`
  - `chat_turns`
  - `chat_messages`
- create indexes for `(user_id, updated_at)`, `(session_id, created_at)`, `(turn_id, sequence_no)`
- keep `chat_sessions` out of `l1_events.db`

Suggested schema shape:

```sql
CREATE TABLE chat_turns (
  turn_id TEXT PRIMARY KEY,
  session_id TEXT NOT NULL,
  user_id TEXT NOT NULL,
  trace_id TEXT,
  orchestration_id TEXT,
  status TEXT NOT NULL,
  response_mode TEXT NOT NULL,
  execution_mode TEXT,
  ux_plan_json TEXT NOT NULL DEFAULT '{}',
  created_at_ms INTEGER NOT NULL,
  updated_at_ms INTEGER NOT NULL,
  completed_at_ms INTEGER,
  error_text TEXT
);
```

- [ ] **Step 4: Re-run the targeted backend tests**

Run:

```bash
cd /Users/asuka/code/magi/backend && PYTHONPATH=/Users/asuka/code/magi/backend/src pytest tests/chat/test_chat_store.py tests/chat/test_chat_migration.py -q
```

Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add /Users/asuka/code/magi/backend/src/magi/chat /Users/asuka/code/magi/backend/src/magi/utils/runtime.py /Users/asuka/code/magi/backend/src/magi/core/database_initializer.py /Users/asuka/code/magi/backend/tests/chat/test_chat_store.py /Users/asuka/code/magi/backend/tests/chat/test_chat_migration.py
git commit -m "feat: add dedicated chat store"
```

## Chunk 2: Backfill And Bootstrap Ownership

### Task 2: Backfill old chat data into the new chat store and wire lifecycle ownership

**Files:**
- Create: `/Users/asuka/code/magi/backend/src/magi/chat/migration.py`
- Create: `/Users/asuka/code/magi/backend/src/magi/chat/lifecycle.py`
- Modify: `/Users/asuka/code/magi/backend/src/magi/bootstrap/context.py`
- Modify: `/Users/asuka/code/magi/backend/src/magi/bootstrap/builder.py`
- Modify: `/Users/asuka/code/magi/backend/src/magi/bootstrap/api_builder.py`
- Modify: `/Users/asuka/code/magi/backend/src/magi/bootstrap/runtime_worker_builder.py`
- Modify: `/Users/asuka/code/magi/backend/src/magi/bootstrap/exports.py`
- Modify: `/Users/asuka/code/magi/backend/tests/runtime/test_process_role_bootstrap.py`
- Modify: `/Users/asuka/code/magi/backend/tests/chat/test_chat_migration.py`

- [ ] **Step 1: Write failing tests for bootstrap ownership and one-time migration**

Add tests that assert:

- both `api` and `runtime_worker` roles can access the same chat store
- migration can reconstruct sessions and transcript rows from legacy `fact_events` and legacy `chat_sessions`
- migration is idempotent

- [ ] **Step 2: Run the targeted tests to verify they fail**

Run:

```bash
cd /Users/asuka/code/magi/backend && PYTHONPATH=/Users/asuka/code/magi/backend/src pytest tests/runtime/test_process_role_bootstrap.py tests/chat/test_chat_migration.py -q
```

Expected: FAIL because bootstrap does not yet own chat persistence and no migration exists.

- [ ] **Step 3: Implement lifecycle wiring and migration**

Implementation requirements:

- add a bootstrap slice for:
  - `chat_store`
  - `chat_projector`
  - `chat_migration_state`
- initialize chat store in both roles
- run backfill only once when `chat.db` is empty
- migrate:
  - session metadata from legacy `chat_sessions`
  - user/final assistant transcript from legacy `fact_events`
- do not migrate runtime-only status placeholders into the new transcript

- [ ] **Step 4: Re-run the targeted tests**

Run:

```bash
cd /Users/asuka/code/magi/backend && PYTHONPATH=/Users/asuka/code/magi/backend/src pytest tests/runtime/test_process_role_bootstrap.py tests/chat/test_chat_migration.py -q
```

Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add /Users/asuka/code/magi/backend/src/magi/chat/migration.py /Users/asuka/code/magi/backend/src/magi/chat/lifecycle.py /Users/asuka/code/magi/backend/src/magi/bootstrap/context.py /Users/asuka/code/magi/backend/src/magi/bootstrap/builder.py /Users/asuka/code/magi/backend/src/magi/bootstrap/api_builder.py /Users/asuka/code/magi/backend/src/magi/bootstrap/runtime_worker_builder.py /Users/asuka/code/magi/backend/src/magi/bootstrap/exports.py /Users/asuka/code/magi/backend/tests/runtime/test_process_role_bootstrap.py /Users/asuka/code/magi/backend/tests/chat/test_chat_migration.py
git commit -m "feat: bootstrap dedicated chat persistence"
```

## Chunk 3: Make Chat Store The Write-Side Source Of Truth

### Task 3: Persist user chat input before command enqueue

**Files:**
- Modify: `/Users/asuka/code/magi/backend/src/magi/api/services/message_dispatch_service.py`
- Modify: `/Users/asuka/code/magi/backend/tests/api/test_message_dispatch_service.py`

- [ ] **Step 1: Write failing tests for dispatch-time chat persistence**

Add tests that assert:

- sending a message creates:
  - a `chat_turn`
  - a `chat_messages(user_text)` row
- the runtime command contains the created `turn_id`
- API returns success only after the chat write succeeds

- [ ] **Step 2: Run the targeted test to verify it fails**

Run:

```bash
cd /Users/asuka/code/magi/backend && PYTHONPATH=/Users/asuka/code/magi/backend/src pytest tests/api/test_message_dispatch_service.py -q
```

Expected: FAIL because dispatch currently writes only to the command queue.

- [ ] **Step 3: Implement minimal write-side persistence in dispatch**

Implementation requirements:

- ensure the session row exists in `chat_sessions`
- create a `chat_turn` with `status='queued'`
- create a `chat_messages` row with `message_kind='user_text'`
- enqueue `UserMessageCommand` only after the above commit succeeds

- [ ] **Step 4: Re-run the targeted test**

Run:

```bash
cd /Users/asuka/code/magi/backend && PYTHONPATH=/Users/asuka/code/magi/backend/src pytest tests/api/test_message_dispatch_service.py -q
```

Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add /Users/asuka/code/magi/backend/src/magi/api/services/message_dispatch_service.py /Users/asuka/code/magi/backend/tests/api/test_message_dispatch_service.py
git commit -m "feat: persist user chat turns before enqueue"
```

### Task 4: Persist runtime chat outcomes before notifications

**Files:**
- Modify: `/Users/asuka/code/magi/backend/src/magi/agent/task_agents/chat/postprocess_service.py`
- Modify: `/Users/asuka/code/magi/backend/src/magi/agent/task_agents/chat/contracts.py`
- Modify: `/Users/asuka/code/magi/backend/src/magi/agent/task_agents/common/contracts.py`
- Modify: `/Users/asuka/code/magi/backend/tests/agent/test_chat_postprocess_service.py`

- [ ] **Step 1: Write failing tests for final/interim/reaction commit ordering**

Add tests that assert:

- `turn_ux_plan` updates `chat_turns.ux_plan_json`
- `reaction_only` writes no assistant final message
- `interim_then_final` writes an interim message first, then marks it replaced by the final message
- `agent_response` notification is appended only after the chat rows have committed

- [ ] **Step 2: Run the targeted tests to verify they fail**

Run:

```bash
cd /Users/asuka/code/magi/backend && PYTHONPATH=/Users/asuka/code/magi/backend/src pytest tests/agent/test_chat_postprocess_service.py -q
```

Expected: FAIL because postprocess currently writes notifications before chat-domain persistence exists.

- [ ] **Step 3: Implement the minimal runtime-side commit flow**

Implementation requirements:

- on intent-resolution or UX-plan updates:
  - update `chat_turns.status`
  - update `ux_plan_json`
- on interim:
  - create `chat_messages(message_kind='assistant_interim')`
- on reaction-only completion:
  - update the turn to `silent_completed`
  - store reaction metadata on the turn or a dedicated message row
- on final response:
  - create `chat_messages(message_kind='assistant_final')`
  - mark the turn `completed`
  - then append runtime notification

- [ ] **Step 4: Re-run the targeted tests**

Run:

```bash
cd /Users/asuka/code/magi/backend && PYTHONPATH=/Users/asuka/code/magi/backend/src pytest tests/agent/test_chat_postprocess_service.py -q
```

Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add /Users/asuka/code/magi/backend/src/magi/agent/task_agents/chat/postprocess_service.py /Users/asuka/code/magi/backend/src/magi/agent/task_agents/chat/contracts.py /Users/asuka/code/magi/backend/src/magi/agent/task_agents/common/contracts.py /Users/asuka/code/magi/backend/tests/agent/test_chat_postprocess_service.py
git commit -m "feat: commit chat outcomes before notify"
```

## Chunk 4: Move Read Models Off L1 Facts

### Task 5: Make backend history and session APIs read from the chat store

**Files:**
- Modify: `/Users/asuka/code/magi/backend/src/magi/api/services/chat_read_service.py`
- Modify: `/Users/asuka/code/magi/backend/src/magi/api/services/chat_trace_read_service.py`
- Modify: `/Users/asuka/code/magi/backend/src/magi/api/routers/messages.py`
- Modify: `/Users/asuka/code/magi/backend/src/magi/websocket/handlers.py`
- Modify: `/Users/asuka/code/magi/backend/src/magi/agent/task_agents/chat/history_service.py`
- Modify: `/Users/asuka/code/magi/backend/tests/api/test_messages_sessions.py`
- Modify: `/Users/asuka/code/magi/backend/tests/api/test_messages_router_bindings.py`

- [ ] **Step 1: Write failing tests for chat-store-backed reads**

Add tests that assert:

- session list comes from `chat.db.chat_sessions`
- transcript history comes from `chat.db.chat_messages`
- history refresh still includes trace metadata by joining runtime trace by `turn_id`
- missing assistant final message no longer fabricates transcript truth from `fact_events`

- [ ] **Step 2: Run the targeted tests to verify they fail**

Run:

```bash
cd /Users/asuka/code/magi/backend && PYTHONPATH=/Users/asuka/code/magi/backend/src pytest tests/api/test_messages_sessions.py tests/api/test_messages_router_bindings.py -q
```

Expected: FAIL because read services still depend on `l1_events.db`.

- [ ] **Step 3: Implement the minimal read-side switch**

Implementation requirements:

- make `ChatReadService` read only:
  - session metadata from `chat_sessions`
  - transcript items from `chat_messages`
  - turn state from `chat_turns`
- keep trace details in `runtime_trace.db`
- stop using `fact_events` as display-history source of truth
- keep prompt history loading aligned with `chat_messages(user_text, assistant_final)`

- [ ] **Step 4: Re-run the targeted tests**

Run:

```bash
cd /Users/asuka/code/magi/backend && PYTHONPATH=/Users/asuka/code/magi/backend/src pytest tests/api/test_messages_sessions.py tests/api/test_messages_router_bindings.py -q
```

Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add /Users/asuka/code/magi/backend/src/magi/api/services/chat_read_service.py /Users/asuka/code/magi/backend/src/magi/api/services/chat_trace_read_service.py /Users/asuka/code/magi/backend/src/magi/api/routers/messages.py /Users/asuka/code/magi/backend/src/magi/websocket/handlers.py /Users/asuka/code/magi/backend/src/magi/agent/task_agents/chat/history_service.py /Users/asuka/code/magi/backend/tests/api/test_messages_sessions.py /Users/asuka/code/magi/backend/tests/api/test_messages_router_bindings.py
git commit -m "refactor: read chat history from chat store"
```

### Task 6: Make runtime notifications carry committed chat-domain references

**Files:**
- Modify: `/Users/asuka/code/magi/backend/src/magi/websocket/bridge_lifecycle.py`
- Modify: `/Users/asuka/code/magi/backend/tests/websocket/test_bridge_lifecycle.py`

- [ ] **Step 1: Write failing tests for notification payload references**

Add tests that assert:

- `agent_response` carries `message_id` and `turn_id`
- `turn_ux_plan` references committed turn state
- websocket bridge payloads can be applied without reconstructing transcript content from notifications alone

- [ ] **Step 2: Run the targeted tests to verify they fail**

Run:

```bash
cd /Users/asuka/code/magi/backend && PYTHONPATH=/Users/asuka/code/magi/backend/src pytest tests/websocket/test_bridge_lifecycle.py -q
```

Expected: FAIL because notifications still embed transcript content directly as the only truth.

- [ ] **Step 3: Implement the bridge payload rewrite**

Implementation requirements:

- include stable identifiers in websocket payloads
- keep text content for convenience, but document it as cache content, not the only source of truth
- keep `trace_summary` and `ux_plan` for live updates

- [ ] **Step 4: Re-run the targeted tests**

Run:

```bash
cd /Users/asuka/code/magi/backend && PYTHONPATH=/Users/asuka/code/magi/backend/src pytest tests/websocket/test_bridge_lifecycle.py -q
```

Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add /Users/asuka/code/magi/backend/src/magi/websocket/bridge_lifecycle.py /Users/asuka/code/magi/backend/tests/websocket/test_bridge_lifecycle.py
git commit -m "refactor: key chat notifications to committed records"
```

## Chunk 5: Demote L1 To Projection Only

### Task 7: Project only canonical chat facts into L1

**Files:**
- Create: `/Users/asuka/code/magi/backend/src/magi/chat/projector.py`
- Modify: `/Users/asuka/code/magi/backend/src/magi/memory/l1/event_store.py`
- Modify: `/Users/asuka/code/magi/backend/src/magi/memory/l1/chat_sessions.py`
- Modify: `/Users/asuka/code/magi/backend/src/magi/awareness/action_emitter.py`
- Modify: `/Users/asuka/code/magi/backend/tests/memory/l1/test_event_store.py`
- Modify: `/Users/asuka/code/magi/backend/tests/chat/test_chat_store.py`

- [ ] **Step 1: Write failing tests for chat-to-L1 projection boundaries**

Add tests that assert:

- `user_text` projects to `UserMessage`
- `assistant_final` projects to `AIResponse`
- `assistant_interim`, `assistant_reaction`, and `status_note` do not project to L1
- `chat_sessions` no longer lives in `l1_events.db`

- [ ] **Step 2: Run the targeted tests to verify they fail**

Run:

```bash
cd /Users/asuka/code/magi/backend && PYTHONPATH=/Users/asuka/code/magi/backend/src pytest tests/memory/l1/test_event_store.py tests/chat/test_chat_store.py -q
```

Expected: FAIL because L1 still owns session metadata and transcript semantics.

- [ ] **Step 3: Implement the minimal projection-only split**

Implementation requirements:

- move `chat_sessions` ownership completely into `chat.db`
- stop using `ActionEmitter.emit_chat_response_event()` as transcript truth
- project canonical chat content into L1 from committed chat rows
- keep projection asynchronous and retryable

- [ ] **Step 4: Re-run the targeted tests**

Run:

```bash
cd /Users/asuka/code/magi/backend && PYTHONPATH=/Users/asuka/code/magi/backend/src pytest tests/memory/l1/test_event_store.py tests/chat/test_chat_store.py -q
```

Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add /Users/asuka/code/magi/backend/src/magi/chat/projector.py /Users/asuka/code/magi/backend/src/magi/memory/l1/event_store.py /Users/asuka/code/magi/backend/src/magi/memory/l1/chat_sessions.py /Users/asuka/code/magi/backend/src/magi/awareness/action_emitter.py /Users/asuka/code/magi/backend/tests/memory/l1/test_event_store.py /Users/asuka/code/magi/backend/tests/chat/test_chat_store.py
git commit -m "refactor: make l1 a chat projection target"
```

## Chunk 6: Frontend Alignment

### Task 8: Make frontend chat state mirror persisted turn/message rows

**Files:**
- Modify: `/Users/asuka/code/magi/frontend/src/api/modules/messages.ts`
- Modify: `/Users/asuka/code/magi/frontend/src/types/chat.ts`
- Modify: `/Users/asuka/code/magi/frontend/src/types/websocket.ts`
- Modify: `/Users/asuka/code/magi/frontend/src/pages/chat-state.ts`
- Modify: `/Users/asuka/code/magi/frontend/src/stores/conversation-store.ts`
- Modify: `/Users/asuka/code/magi/frontend/src/pages/Chat.tsx`
- Modify: `/Users/asuka/code/magi/frontend/src/__tests__/conversationStore.test.ts`
- Modify: `/Users/asuka/code/magi/frontend/src/__tests__/chatPage.test.tsx`
- Modify: `/Users/asuka/code/magi/frontend/src/__tests__/chatTraceState.test.ts`

- [ ] **Step 1: Write failing frontend tests for persisted chat semantics**

Add tests that assert:

- history refresh returns reaction/interim/final rows with stable IDs
- a final reply replaces an interim row by identifier instead of fragile text matching
- a `reaction_only` turn renders from persisted data even after reload
- trace visibility still follows `ux_plan`, but transcript rows come from backend chat DTOs

- [ ] **Step 2: Run the targeted frontend tests to verify they fail**

Run:

```bash
cd /Users/asuka/code/magi/frontend && npm run test -- --run src/__tests__/conversationStore.test.ts src/__tests__/chatPage.test.tsx src/__tests__/chatTraceState.test.ts
```

Expected: FAIL because the frontend still treats notifications plus ad hoc history merging as the primary model.

- [ ] **Step 3: Implement the minimal frontend rewrite**

Implementation requirements:

- add message IDs and turn-state IDs to frontend DTOs
- let history hydration rebuild exact persisted rows
- let websocket notifications patch or append by ID
- stop inventing transcript placeholders when backend has not persisted a chat message row

- [ ] **Step 4: Re-run the targeted frontend tests**

Run:

```bash
cd /Users/asuka/code/magi/frontend && npm run test -- --run src/__tests__/conversationStore.test.ts src/__tests__/chatPage.test.tsx src/__tests__/chatTraceState.test.ts
```

Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add /Users/asuka/code/magi/frontend/src/api/modules/messages.ts /Users/asuka/code/magi/frontend/src/types/chat.ts /Users/asuka/code/magi/frontend/src/types/websocket.ts /Users/asuka/code/magi/frontend/src/pages/chat-state.ts /Users/asuka/code/magi/frontend/src/stores/conversation-store.ts /Users/asuka/code/magi/frontend/src/pages/Chat.tsx /Users/asuka/code/magi/frontend/src/__tests__/conversationStore.test.ts /Users/asuka/code/magi/frontend/src/__tests__/chatPage.test.tsx /Users/asuka/code/magi/frontend/src/__tests__/chatTraceState.test.ts
git commit -m "refactor: align frontend with chat store"
```

## Chunk 7: Documentation And End-To-End Verification

### Task 9: Update docs and verify the final persistence boundaries

**Files:**
- Modify: `/Users/asuka/code/magi/docs/project-overview.md`
- Modify: `/Users/asuka/code/magi/docs/product-configuration-guide.md`
- Modify: `/Users/asuka/code/magi/docs/task-agent-runtime-architecture.md`

- [ ] **Step 1: Update docs to reflect the new boundaries**

Document:

- `chat.db` as the chat domain source of truth
- `runtime_trace.db` as execution observability only
- `l1_events.db` as canonical memory projection only
- `TurnUXPlan` as chat presentation contract persisted on turns

- [ ] **Step 2: Run focused verification**

Run:

```bash
cd /Users/asuka/code/magi/backend && PYTHONPATH=/Users/asuka/code/magi/backend/src pytest tests/chat/test_chat_store.py tests/chat/test_chat_migration.py tests/api/test_message_dispatch_service.py tests/agent/test_chat_postprocess_service.py tests/api/test_messages_sessions.py tests/api/test_messages_router_bindings.py tests/websocket/test_bridge_lifecycle.py tests/runtime/test_process_role_bootstrap.py tests/memory/l1/test_event_store.py -q
```

Run:

```bash
cd /Users/asuka/code/magi/frontend && npm run test -- --run src/__tests__/conversationStore.test.ts src/__tests__/chatPage.test.tsx src/__tests__/chatTraceState.test.ts
```

Expected: PASS

- [ ] **Step 3: Optional manual verification**

Run:

```bash
cd /Users/asuka/code/magi && ./scripts/dev-tauri-hot.sh
```

Verify:

- user message appears immediately after send
- reaction-only turn survives refresh
- interim message is replaced by final reply after runtime completion
- history refresh does not regress final reply into a status placeholder
- memory recall still finds canonical user/final assistant content through L1 projection

- [ ] **Step 4: Commit**

```bash
git add /Users/asuka/code/magi/docs/project-overview.md /Users/asuka/code/magi/docs/product-configuration-guide.md /Users/asuka/code/magi/docs/task-agent-runtime-architecture.md
git commit -m "docs: describe dedicated chat persistence"
```

## Notes And Guardrails

- `chat.db` should live under `~/.magi/data/`, not under `~/.magi/data/memories/`, because chat transcript is product-domain data rather than memory-layer storage.
- Runtime notifications remain best-effort live fan-out; they must not be the only source for transcript recovery.
- L1 projection should remain lossy by design:
  - project `user_text`
  - project `assistant_final`
  - skip `assistant_interim`
  - skip `assistant_reaction`
  - skip `status_note`
- Do not add compatibility code paths that keep `fact_events` and `chat_messages` co-equal as transcript sources. Migration should be one-way, and post-migration read-side code should treat `chat.db` as canonical.
- Preserve the current dual-process topology:
  - API writes to chat store and runtime command queue
  - runtime worker writes to chat store, runtime trace, and L1 projection pipeline

Plan complete and saved to `docs/superpowers/plans/2026-03-22-chat-domain-store-separation.md`. Ready to execute?
