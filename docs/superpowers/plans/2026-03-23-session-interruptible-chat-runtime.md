# Session-Interruptible Chat Runtime Implementation Plan

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a session-scoped chat runtime that supports user interruptions and augmenting turns during active execution without letting stale results pollute newer planning state.

**Architecture:** Chat routing becomes `session_id` scoped, active execution is managed by a new `SessionRunCoordinator`, planning remains in `ContextDecider`, and function calling is refactored into step-wise execution. Trace-only loop events are removed from the main execution queue, while result payloads gain `run_id` and `revision` for revision barriers.

**Tech Stack:** Python 3.10+, FastAPI runtime services, asyncio task agents, SQLite-backed chat and trace stores, pytest

---

## Chunk 1: Session Routing Foundation

### Task 1: Route chat agents by `session_id`

**Files:**
- Modify: `backend/src/magi/agent/runtime/task_agent_manager.py`
- Modify: `backend/src/magi/awareness/sensor_hub.py`
- Test: `backend/tests/agent/test_task_agent_manager.py`

- [ ] **Step 1: Write the failing tests**

Add tests that verify:
- `USER_MESSAGE` routes to `chat:<session_id>`
- missing `session_id` is rejected or handled explicitly, not silently downgraded to `user_id`

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd backend && pytest backend/tests/agent/test_task_agent_manager.py -v`
Expected: FAIL because routing still uses `user_id`

- [ ] **Step 3: Implement session-scoped routing**

Update `resolve_targets(...)` to use `payload["session_id"]` for chat routing and keep `user_id` as payload data only.

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd backend && pytest backend/tests/agent/test_task_agent_manager.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add backend/src/magi/agent/runtime/task_agent_manager.py backend/src/magi/awareness/sensor_hub.py backend/tests/agent/test_task_agent_manager.py
git commit -m "refactor: route chat agents by session"
```

### Task 2: Ensure internal result payloads can target a session chat agent

**Files:**
- Modify: `backend/src/magi/agent/workers/worker_manager.py`
- Modify: `backend/src/magi/agent/task_agents/explore/postprocess_service.py`
- Test: `backend/tests/agent/test_session_result_routing.py`

- [ ] **Step 1: Write the failing tests**

Add tests that verify worker and explore completion payloads include:
- `target_task_agent_type="chat"`
- `target_task_agent_id=<session_id>`

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd backend && pytest backend/tests/agent/test_session_result_routing.py -v`
Expected: FAIL because payloads do not yet target session instances

- [ ] **Step 3: Implement explicit session target metadata**

Propagate session-scoped target metadata into internal chat result payloads.

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd backend && pytest backend/tests/agent/test_session_result_routing.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add backend/src/magi/agent/workers/worker_manager.py backend/src/magi/agent/task_agents/explore/postprocess_service.py backend/tests/agent/test_session_result_routing.py
git commit -m "feat: target chat results by session"
```

## Chunk 2: Session Run State

### Task 3: Add typed session run contracts and in-memory store

**Files:**
- Create: `backend/src/magi/agent/task_agents/chat/run_contracts.py`
- Create: `backend/src/magi/agent/task_agents/chat/run_store.py`
- Test: `backend/tests/agent/test_chat_run_store.py`

- [ ] **Step 1: Write the failing tests**

Add tests for:
- creating an active run
- appending a pending turn
- bumping a revision
- marking stale results

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd backend && pytest backend/tests/agent/test_chat_run_store.py -v`
Expected: FAIL because the store and contracts do not exist

- [ ] **Step 3: Implement typed run contracts and store**

Create focused dataclasses for `ActiveRun`, `PendingTurn`, and a small store API keyed by `session_id`.

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd backend && pytest backend/tests/agent/test_chat_run_store.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add backend/src/magi/agent/task_agents/chat/run_contracts.py backend/src/magi/agent/task_agents/chat/run_store.py backend/tests/agent/test_chat_run_store.py
git commit -m "feat: add session run state store"
```

### Task 4: Add interruption classification

**Files:**
- Create: `backend/src/magi/agent/task_agents/chat/interruption_classifier.py`
- Test: `backend/tests/agent/test_interruption_classifier.py`

- [ ] **Step 1: Write the failing tests**

Cover:
- explicit stop/change-goal text -> `interrupt`
- additive context text -> `augment`
- atomic or side-effecting step state -> `defer`

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd backend && pytest backend/tests/agent/test_interruption_classifier.py -v`
Expected: FAIL because the classifier does not exist

- [ ] **Step 3: Implement rules-first classifier**

Keep the first version deterministic and state-aware. Do not add an LLM fallback in the first pass.

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd backend && pytest backend/tests/agent/test_interruption_classifier.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add backend/src/magi/agent/task_agents/chat/interruption_classifier.py backend/tests/agent/test_interruption_classifier.py
git commit -m "feat: add chat interruption classifier"
```

## Chunk 3: Coordinator Layer

### Task 5: Introduce `SessionRunCoordinator`

**Files:**
- Create: `backend/src/magi/agent/task_agents/chat/session_run_coordinator.py`
- Modify: `backend/src/magi/agent/task_agents/chat/__init__.py`
- Test: `backend/tests/agent/test_session_run_coordinator.py`

- [ ] **Step 1: Write the failing tests**

Cover:
- first turn creates a new run
- interjection during active run is classified and stored
- interrupt bumps revision
- augment is visible at next checkpoint

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd backend && pytest backend/tests/agent/test_session_run_coordinator.py -v`
Expected: FAIL because the coordinator does not exist

- [ ] **Step 3: Implement coordinator**

Keep responsibilities narrow:
- accept user turns and internal results
- maintain active run state
- expose checkpoint merge decisions

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd backend && pytest backend/tests/agent/test_session_run_coordinator.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add backend/src/magi/agent/task_agents/chat/session_run_coordinator.py backend/src/magi/agent/task_agents/chat/__init__.py backend/tests/agent/test_session_run_coordinator.py
git commit -m "feat: add session run coordinator"
```

### Task 6: Wire chat task agent through the coordinator

**Files:**
- Modify: `backend/src/magi/agent/task_agents/chat_task_agent.py`
- Modify: `backend/src/magi/agent/task_agents/chat/fact_classifier.py`
- Modify: `backend/src/magi/agent/task_agents/chat/coordinator.py`
- Test: `backend/tests/agent/test_chat_task_agent_runtime.py`

- [ ] **Step 1: Write the failing tests**

Cover:
- user facts now drive session-run state transitions
- tool-loop trace facts no longer dominate user-intent routing

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd backend && pytest backend/tests/agent/test_chat_task_agent_runtime.py -v`
Expected: FAIL because the current runtime still routes directly through the old pipeline

- [ ] **Step 3: Implement coordinator-first runtime wiring**

Route user and result facts into `SessionRunCoordinator` before calling the planner. Reduce or remove dependence on `latest_fact` for user-message dominance.

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd backend && pytest backend/tests/agent/test_chat_task_agent_runtime.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add backend/src/magi/agent/task_agents/chat_task_agent.py backend/src/magi/agent/task_agents/chat/fact_classifier.py backend/src/magi/agent/task_agents/chat/coordinator.py backend/tests/agent/test_chat_task_agent_runtime.py
git commit -m "refactor: drive chat runtime with session coordinator"
```

## Chunk 4: Step-Wise Function Calling

### Task 7: Extract a step executor from function calling

**Files:**
- Create: `backend/src/magi/agent/execution/function_calling_step_executor.py`
- Modify: `backend/src/magi/agent/execution/function_calling.py`
- Test: `backend/tests/agent/test_function_calling_step_executor.py`

- [ ] **Step 1: Write the failing tests**

Cover:
- one step performs one LLM decision and one tool batch
- control returns after the step
- no internal unbounded while loop is required for the new path

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd backend && pytest backend/tests/agent/test_function_calling_step_executor.py -v`
Expected: FAIL because the step executor does not exist

- [ ] **Step 3: Implement step executor**

Preserve current protocol handling but move loop control outside the executor.

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd backend && pytest backend/tests/agent/test_function_calling_step_executor.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add backend/src/magi/agent/execution/function_calling_step_executor.py backend/src/magi/agent/execution/function_calling.py backend/tests/agent/test_function_calling_step_executor.py
git commit -m "refactor: extract function calling step executor"
```

### Task 8: Drive step execution from session checkpoints

**Files:**
- Modify: `backend/src/magi/agent/task_agents/chat/session_run_coordinator.py`
- Modify: `backend/src/magi/agent/task_agents/chat/handlers.py`
- Test: `backend/tests/agent/test_chat_checkpoint_merge.py`

- [ ] **Step 1: Write the failing tests**

Cover:
- augment turns are merged at the next checkpoint
- interrupt turns stop continuation and trigger replanning

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd backend && pytest backend/tests/agent/test_chat_checkpoint_merge.py -v`
Expected: FAIL because step checkpoints are not yet integrated

- [ ] **Step 3: Implement coordinator-driven checkpoints**

Let the coordinator decide whether to continue, merge, replan, or terminate after each step.

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd backend && pytest backend/tests/agent/test_chat_checkpoint_merge.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add backend/src/magi/agent/task_agents/chat/session_run_coordinator.py backend/src/magi/agent/task_agents/chat/handlers.py backend/tests/agent/test_chat_checkpoint_merge.py
git commit -m "feat: merge interjection turns at checkpoints"
```

## Chunk 5: Revision Barriers And Trace Hygiene

### Task 9: Add revision metadata and stale-result barriers

**Files:**
- Modify: `backend/src/magi/agent/workers/worker_manager.py`
- Modify: `backend/src/magi/agent/task_agents/explore/postprocess_service.py`
- Modify: `backend/src/magi/runtime_trace/contracts.py`
- Test: `backend/tests/agent/test_revision_barrier.py`

- [ ] **Step 1: Write the failing tests**

Cover:
- results from older revisions are retained for trace
- results from older revisions are excluded from active planning context

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd backend && pytest backend/tests/agent/test_revision_barrier.py -v`
Expected: FAIL because revision metadata and barriers do not exist

- [ ] **Step 3: Implement result revision tagging and stale barriers**

Thread `run_id` and `revision` through result payloads and reject stale results in the coordinator.

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd backend && pytest backend/tests/agent/test_revision_barrier.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add backend/src/magi/agent/workers/worker_manager.py backend/src/magi/agent/task_agents/explore/postprocess_service.py backend/src/magi/runtime_trace/contracts.py backend/tests/agent/test_revision_barrier.py
git commit -m "feat: add chat revision barriers"
```

### Task 10: Stop feeding trace-only tool loop facts into chat execution

**Files:**
- Modify: `backend/src/magi/agent/task_agents/chat/postprocess_service.py`
- Test: `backend/tests/agent/test_chat_postprocess_service.py`

- [ ] **Step 1: Write the failing tests**

Add tests asserting:
- tool loop progress still emits trace/runtime notifications
- tool loop progress no longer enqueues chat execution facts

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd backend && pytest backend/tests/agent/test_chat_postprocess_service.py -v`
Expected: FAIL because tool loop facts still re-enter the main chat queue

- [ ] **Step 3: Implement trace-only loop behavior**

Preserve observability while removing execution-queue pollution.

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd backend && pytest backend/tests/agent/test_chat_postprocess_service.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add backend/src/magi/agent/task_agents/chat/postprocess_service.py backend/tests/agent/test_chat_postprocess_service.py
git commit -m "refactor: keep chat tool loop events trace only"
```

## Chunk 6: Persistence And Product Metadata

### Task 11: Persist run metadata on chat turns

**Files:**
- Modify: `backend/src/magi/chat/store.py`
- Modify: `backend/src/magi/chat/contracts.py`
- Modify: `backend/src/magi/chat/read_service.py`
- Modify: `backend/src/magi/chat/migration.py`
- Test: `backend/tests/chat/test_chat_run_metadata.py`

- [ ] **Step 1: Write the failing tests**

Cover:
- `run_id`, `run_revision`, and `run_disposition` round-trip through chat storage

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd backend && pytest backend/tests/chat/test_chat_run_metadata.py -v`
Expected: FAIL because the schema and contracts do not include run metadata

- [ ] **Step 3: Implement schema and read-model changes**

Add the minimal turn metadata fields required to explain interruption behavior in product surfaces.

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd backend && pytest backend/tests/chat/test_chat_run_metadata.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add backend/src/magi/chat/store.py backend/src/magi/chat/contracts.py backend/src/magi/chat/read_service.py backend/src/magi/chat/migration.py backend/tests/chat/test_chat_run_metadata.py
git commit -m "feat: persist chat run metadata"
```

## Chunk 7: End-To-End Validation

### Task 12: Add integration coverage for interruptible chat sessions

**Files:**
- Create: `backend/tests/agent/test_interruptible_chat_session_integration.py`

- [ ] **Step 1: Write the failing integration tests**

Cover:
- session A and session B for one user do not cross streams
- augment turn is applied at the next checkpoint
- interrupt turn creates a new revision and drops stale reuse
- trace-only loop events remain visible without affecting execution

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd backend && pytest backend/tests/agent/test_interruptible_chat_session_integration.py -v`
Expected: FAIL because the full runtime path is not yet complete

- [ ] **Step 3: Implement any missing glue**

Only add the minimal missing integration glue discovered by the tests.

- [ ] **Step 4: Run the focused integration tests**

Run: `cd backend && pytest backend/tests/agent/test_interruptible_chat_session_integration.py -v`
Expected: PASS

- [ ] **Step 5: Run the broader safety checks**

Run: `cd backend && pytest`
Expected: PASS

Run: `cd frontend && npm run type-check`
Expected: PASS or no relevant changes required

- [ ] **Step 6: Commit**

```bash
git add backend/tests/agent/test_interruptible_chat_session_integration.py
git commit -m "test: cover interruptible chat sessions"
```

## Notes For Execution

- Keep commits atomic and immediate after each completed task.
- Prefer rules-first interruption classification; add an LLM fallback only after the deterministic version is stable.
- Do not reintroduce `user_id`-scoped chat routing as a compatibility path.
- Do not let stale results re-enter prompt assembly under any fallback behavior.
- If an internal result lacks `session_id` targeting metadata, fail loudly rather than guessing.

## Relevant Docs To Re-Read Before Execution

- `docs/project-overview.md`
- `docs/task-agent-runtime-architecture.md`
- `docs/product-configuration-guide.md`
- `docs/superpowers/specs/2026-03-23-session-interruptible-chat-runtime-design.md`

Plan complete and saved to `docs/superpowers/plans/2026-03-23-session-interruptible-chat-runtime.md`. Ready to execute?
