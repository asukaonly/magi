# Session-Interruptible Chat Runtime Design

## Purpose

This document defines the ideal runtime design for making chat sessions interruptible while a tool loop, orchestration flow, or worker-backed execution is already in progress.

The goal is to let a user send a new message during active execution and have the runtime treat it as either:

- an interruption of the current run
- an augmentation of the current run context
- a deferred input that should be applied after the current atomic step

This design keeps transcript truth in the chat domain while moving execution control into a session-scoped runtime model.

## Design Goals

- Preserve the product invariant that every user message is a new chat turn.
- Make active execution session-scoped rather than user-scoped.
- Allow user interjections to be applied at safe checkpoints.
- Prevent stale tool or worker results from polluting newer planning context.
- Keep execution-control decisions separate from task-planning decisions.
- Preserve existing chat transcript ownership in `chat.db`.
- Preserve runtime observability ownership in `runtime_trace.db`.

## Non-Goals

- True mid-request injection into a single in-flight LLM call.
- Force-killing arbitrary tools without an explicit cancellation contract.
- Redesigning the whole agent runtime around sessions for all task-agent types.
- Changing chat transcript semantics so that multiple user messages collapse into one turn.

## Current Problem

The current chat runtime has three coupling points that block robust interruption behavior:

1. Chat task-agent routing is effectively keyed by `user_id`, not `session_id`.
2. The function-calling runtime owns a closed loop and does not yield control until it reaches a final response.
3. tool-loop progress facts are re-enqueued into the same chat execution queue, where they can mix with new user messages and distort intent routing.

Together, these make user interjections visible to persistence but not reliably actionable during active execution.

## Core Design

### 1. Session-Scoped Chat Runtime

`ChatTaskAgent` should run as a dynamic instance keyed by `session_id`.

This means:

- the runtime target for direct user chat execution is `chat:<session_id>`
- concurrent sessions from the same user do not share one execution queue
- interruption state belongs to the session, which matches the product model

`user_id` remains business identity and memory scope, but not the chat-agent instance key.

### 2. Separate Execution Control From Planning

Introduce a session-owned coordinator:

- `SessionRunCoordinator`

Responsibilities:

- own the active run for one session
- manage run revisions
- collect pending interjection turns
- decide when the planner should run again
- enforce stale-result barriers
- drive checkpoint progression

Introduce a narrow classifier:

- `InterruptionClassifier`

Responsibilities:

- inspect the new user turn and active run state
- emit one of `interrupt`, `augment`, or `defer`

Keep `ContextDecider` as the planner:

- decide intent
- decide tools
- decide execution mode
- decide orchestration shape

Important boundary:

- `InterruptionClassifier` answers: "What should this new turn do to the current run?"
- `ContextDecider` answers: "Given the current visible context, what should the runtime do next?"

## Session Run Model

### ActiveRun

Each session may have at most one `ActiveRun`.

Suggested fields:

- `run_id`
- `session_id`
- `user_id`
- `root_turn_id`
- `active_revision`
- `status`
- `current_step_kind`
- `pending_turns`
- `accepted_results`
- `stale_results`
- `started_at_ms`
- `updated_at_ms`

### PendingTurn

Each interjection turn should remain a first-class chat turn and may also be attached to the active run as a pending execution-control input.

Suggested fields:

- `turn_id`
- `session_id`
- `user_id`
- `content`
- `arrived_at_ms`
- `disposition`
- `applied_revision`

### Revision

Every planning state of a run is versioned.

Rules:

- a new interrupt creates a new active revision
- augment messages are applied to the active revision at the next checkpoint
- results from older revisions are recorded but never fed back into planning

## Checkpoint Model

User interjections are only applied at explicit checkpoints.

Valid checkpoints:

- after one LLM planning/tool-decision call completes
- after one tool batch completes
- after one worker or orchestration batch completes
- after one explore aggregation step completes

Invalid checkpoints:

- during a single in-flight LLM request
- during a single atomic tool step
- during a non-interruptible side-effecting operation

This keeps the runtime deterministic and removes the need for unsafe mid-request mutation.

## Execution Flow

### No Active Run

If a new chat turn arrives and the session has no active run:

1. create a new run
2. call `ContextDecider`
3. execute the next step

### Active Run + New Turn

If a new chat turn arrives while a run is active:

1. attach the turn to the session run inbox
2. call `InterruptionClassifier`
3. branch by disposition

Branch behavior:

- `interrupt`
  - bump revision
  - cancel cancellable work
  - mark current revision stale
  - invoke `ContextDecider` with the new visible context

- `augment`
  - keep the active run alive
  - store the turn in `pending_turns`
  - merge it at the next checkpoint before the next planning step

- `defer`
  - retain the turn
  - wait until the current atomic step completes
  - reevaluate at the next checkpoint

## Step Execution

The current function-calling loop should be refactored into a step executor.

The executor should handle one bounded execution step at a time:

- one LLM decision
- zero or one tool batch
- zero or one final answer

The enclosing loop belongs to `SessionRunCoordinator`.

This allows the runtime to:

- inspect pending turns between steps
- promote interrupts at safe boundaries
- re-run planning with merged augment turns

## Routing Rules

### Default User Turn Routing

User turns should route to:

- `TaskAgentType.CHAT`
- `agent_instance_id = session_id`

### Internal Result Routing

Any result that should influence the visible answer for a chat session must explicitly carry:

- `target_task_agent_type = chat`
- `target_task_agent_id = session_id`
- `session_id`
- `run_id`
- `revision`

This includes:

- worker progress, completion, and failure
- orchestration aggregation results
- explore-task completion results

### Trace-Only Events

These should not re-enter the chat execution queue:

- tool-loop progress events
- runtime-only telemetry
- UI progress notifications

They still belong in runtime trace and live notifications, but not in the execution-driving fact stream.

## Tool Cancellation Contract

Tools must expose cancellation semantics to support safe interruption.

Suggested metadata:

- `interruptible`
- `side_effecting`
- `atomic`

Expected behavior:

- `interruptible=true`
  - may be cancelled when a newer revision becomes active

- `side_effecting=true`
  - may require `defer` instead of immediate interruption

- `atomic=true`
  - must finish the current step before the pending turn can affect execution

## Persistence Boundaries

### chat.db

Remains the source of truth for:

- sessions
- turns
- transcript messages

Recommended turn metadata additions:

- `run_id`
- `run_revision`
- `run_disposition`

### runtime_trace.db

Stores:

- run creation
- revision bumps
- interruption decisions
- checkpoints
- stale-result drops
- tool and worker execution spans

### In-Memory Session Run Store

The active session-run state can be kept in memory first, with durable projection of critical execution metadata into trace storage.

This is consistent with the current runtime model, where chat transcript truth and execution observability are already separated.

## Error Handling Rules

- If interruption classification fails, default to `defer` rather than silently ignoring the turn.
- If cancellation fails, mark the step as non-cancellable and let the revision barrier prevent result reuse.
- If a stale result arrives after a revision bump, record it and drop it from planning context.
- If session routing metadata is missing for an internal result, treat it as a runtime error instead of guessing a target session.

## Testing Strategy

The implementation should verify:

- two sessions for one user run independently
- a new augment turn is merged at the next checkpoint
- a new interrupt turn creates a new revision and blocks stale result reuse
- trace-only tool loop events never drive intent routing
- non-interruptible tools cause `defer`, not unsafe cancellation
- worker/explore results route back to the correct session-scoped chat agent

## Migration Strategy

1. switch chat routing from `user_id` to `session_id`
2. introduce session-owned run state
3. split function calling into step-wise execution
4. add interruption classification and checkpoint merge logic
5. stop feeding trace-only tool loop events into the main chat execution queue
6. add revision metadata to result payloads and trace projections

## Rationale

This design matches the product mental model:

- every user message remains a first-class turn
- active execution is local to one session
- user interjections can change execution safely
- planning stays separate from execution control

It also aligns with the current repository architecture:

- task-agent logic stays in the chat task agent layer
- transcript truth stays in `chat.db`
- execution observability stays in `runtime_trace.db`
- typed internal contracts remain the preferred runtime boundary
