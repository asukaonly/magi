# Task-Agent Runtime Architecture

## Purpose

This document is the source of truth for Magi's current task-agent runtime. It
covers ordinary chat turns, headless/background execution, child runs, runtime
control, completion governance, reasoning policy, persistence, and read-side
projection.

The architecture is model-first but runtime-governed:

- the main model decides task semantics and the next useful action;
- deterministic code owns admission, permissions, effect policy, budgets,
  cancellation, persistence, completion requirements, and bounded recovery;
- ordinary user messages do not pass through a semantic intent-classifier LLM;
- chat, background, worker, and skill-backed work share one bounded run loop.

Last reviewed against the implementation: 2026-08-25.

## Core Decisions

1. **One model-facing loop.** A direct reply is simply a run whose first model
   step proposes a final response and passes the completion gate. It is not a
   separate execution mode or handler.
2. **No ordinary-turn semantic pre-router.** `ChatTurnAdmissionService` only
   separates user messages from non-user domain facts. `CapabilityResolver`
   builds an initial bounded capability surface deterministically.
3. **Code governs invariants, not task semantics.** Permissions, destructive
   controls, effect replay, validation requirements, budgets, and repair bounds
   are enforced by code. The model chooses whether to answer, call tools, update
   a plan, or launch child runs within those bounds.
4. **Plans are runtime state.** `RunPlan` is versioned and evidence-linked. The
   main model updates it through `todo_write`; the frontend reads a projection
   from the canonical `run_plans` row joined with run events, rather than a
   duplicate chat transcript message.
5. **Child agents are child runs.** The `agent` tool launches bounded runs via
   `ChildRunCoordinator`. There is no separate parent DAG orchestrator.
6. **Reasoning depth is a policy, not an inferred intent field.** The user picks
   `auto`, `fast`, or `deep`; completion evidence and the model's typed
   `request_reasoning_depth` control may request monotonic escalation, while the
   runtime owns the ceiling and budget.
7. **Durable stores have one truth each.** The chat-owned Model Context Log,
   Session Accepted Surface, and per-run Working Surface own reconstructible
   model-visible conversation state; visible transcript rows own product
   presentation; ordered run events own execution observability; `run_plans`
   owns current plan state. None is rebuilt from another as a compatibility
   fallback.

## System Topology

The desktop runtime is split across two Python roles behind the Rust gateway:

- **API process** — accepts product requests, owns chat ingress transactions,
  enqueues durable runtime commands, and serves chat/control/trace read APIs;
- **runtime worker** — consumes commands, runs task agents, owns the in-process
  message bus, executes model/tool loops, and writes runtime events and chat
  outcomes.

The message bus is process-local. SQLite queues and domain stores, not the bus,
own restart recovery.

```mermaid
flowchart TD
    U[User or external message] --> G[Rust gateway]
    G --> I[Typed chat ingress]
    I --> C{Envelope control?}
    C -->|client/control command| X[Deterministic command owner]
    C -->|inline skill| S[Expand trusted skill context]
    C -->|ordinary message| Q[Durable runtime command queue]
    S --> Q
    Q --> B[Runtime worker message bus]
    B --> T[ChatTaskAgent]
    T --> A[Deterministic turn admission]
    A --> R[Build AgentRunRequest]
    R --> L[Unified model/tool loop]
    L -->|tool call| P[Permission + effect policy]
    P --> L
    L -->|agent tool| W[ChildRunCoordinator]
    W --> L
    L -->|proposed final| K[CompletionGate]
    K -->|continue/repair| L
    K -->|blocked| O
    K -->|complete| O[Durable chat outcome]
    L -->|explicit suspend control| H[Checkpoint and wait]
    O --> V[Run-event trace projection]
```

## Bootstrap And Readiness

`bootstrap/` is the composition root. It wires layer-owned modules rather than
placing business logic in one global service bag. Startup follows four broad
phases:

1. infrastructure and database migrations;
2. stores, registries, model providers, tools, skills, and runtime bindings;
3. recovery workers, task-agent runtime, scheduler, channels, and business
   services;
4. exported bindings, maintenance dependencies, and readiness publication.

The current runtime-worker sequence in `bootstrap/runtime_worker_builder.py` is:

### Phase 1: infrastructure bring-up

1. `subprocess_orphan_cleanup`
2. `runtime_core_dependencies`
3. `runtime_initialization_state`
4. `runtime_memory_restore_recovery`
5. `runtime_database_migrations`
6. `runtime_identity`
7. `runtime_configuration`
8. `runtime_command_queue`
9. `runtime_message_bus`
10. `runtime_chat_store`
11. `runtime_plugin_system`
12. `runtime_llm`

### Phase 2: stateful services and read/write stores

13. `runtime_memory`
14. `runtime_chat_forgetting_recovery`
15. `runtime_media_registry`
16. `runtime_location`
17. `runtime_manual_entries`
18. `runtime_history_imports`
19. `runtime_memory_ingestion_subscriber`
20. `runtime_llm_usage_subscriber`
21. `runtime_chat_projector`
22. `runtime_chat_assistant_memory_projection`
23. `runtime_control_transcript_subscriber`
24. `runtime_trace`
25. `runtime_trace_subscriber`
26. `runtime_hooks`
27. `runtime_first_party_tools`
28. `runtime_tools`
29. `runtime_skills`
30. `runtime_mcp`
31. `runtime_personality`
32. `runtime_sensor_hub`
33. `runtime_context`
34. `runtime_agent_core`

### Phase 3: long-running processors and business services

35. `runtime_chat_delivery_recovery`
36. `runtime_command_processor`
37. `runtime_plugin_ingress_processor`
38. `runtime_timeline`
39. `runtime_timeline_subscriber`
40. `runtime_kg_subscriber`
41. `runtime_sensor_state_subscriber`
42. `runtime_scheduler`
43. `runtime_agent_schedule_registration`
44. `runtime_sensor_scheduler`

### Phase 4: exports and maintenance registration

45. `runtime_exports`
46. `runtime_control_plane`
47. `runtime_l1_maintenance_scheduler`
48. `runtime_l2_maintenance_scheduler`
49. `runtime_l2_consolidation_scheduler`
50. `runtime_l2_derive_scheduler`
51. `runtime_l3_summary_scheduler`
52. `runtime_l3_maintenance_scheduler`
53. `runtime_l4_maintenance_scheduler`
54. `runtime_timeline_schedulers`
55. `runtime_operational_gc_scheduler`
56. `runtime_other_dependencies`
57. `runtime_channels`
58. `runtime_outreach`
59. `runtime_scheduler_activation`
60. `runtime_sensor_sync_executor`

Important rule: bootstrap order is dependency order, not ownership order. The
scheduler engine is infrastructure even though it starts after services that
register schedules into it. It remains paused until
`runtime_scheduler_activation`; unchanged registrations are read-only.

The product readiness states remain:

- `ready` — normal agent execution is available;
- `deferred` — configuration/onboarding may proceed, but full model execution is
  not yet guaranteed;
- `degraded` — startup completed with an explicitly reduced capability set;
- `unresponsive` — the IPC worker did not answer the bounded readiness probe.

Full-clear recovery is completed before ordinary runtime commands are admitted.
This prevents pre-clear queue rows, projections, or plugin ingress from
recreating deleted user content.

## Ingress Envelope And Slash Commands

The client sends structured fields for controls that must not be guessed from
natural language:

- reasoning preference (`auto`, `fast`, `deep`);
- active-run disposition (`message` or explicit `replace`);
- inline skill identity and expanded content hash;
- reply target and managed attachments;
- controlled interaction responses;
- workspace and source-channel identity.

Slash recognition is owned before the model-facing run:

- `CommandRegistry` is the canonical catalog for client, control, tool, and
  skill commands;
- client actions such as `/clear` are handled deterministically by their
  declared owner;
- `/auto`, `/fast`, and `/deep` are inline message modifiers: the composer
  keeps the prefix visible, strips it from semantic message content on submit,
  and writes the selected preference into the typed turn envelope;
- selecting a picker result consumes only the active slash query: reasoning
  modifiers are inserted before the remaining draft, while client, tool, and
  skill commands execute without discarding unrelated draft text;
- cancellation remains run-targeted: the locked composer exposes a stop
  button; when interjection keeps the composer enabled, `/cancel` is offered
  only while an exact active foreground turn is known and dispatches against
  that turn identity;
- user-invocable tool commands execute through `CommandRunner`, including the
  same permission boundary used by model-driven calls;
- inline skills are expanded by the backend and become typed, trusted context in
  `UserMessagePayload.skill_invocation`; each `allowed-tools` rule is parsed into
  a base tool name for capability pinning plus an argument-aware, run-scoped
  permission pre-approval rule;
- a slash-like string not resolved by the command catalog remains ordinary user
  text. The model may interpret its meaning, but cannot turn it into a privileged
  command.

Every command invocation/result written to chat uses the chat-owned surface
writer. Commands do not assemble transcript rows directly.

## Deterministic Turn Admission

The generic `TaskAgent` pipeline names its stages after their actual runtime
responsibilities: `admit_context`, `resolve_capabilities`,
`build_execution_request`, `execute_request`, and `finalize_result`:

- `ChatFactClassifier` normalizes fact envelopes into `USER_MESSAGE` or
  `OTHER_FACT` and extracts typed payloads;
- `ChatTurnAdmissionService` routes non-user facts to `ExecutionMode.FACT_ONLY`;
- every ordinary user message returns the `unified_agent_run` admission with no
  route-derived execution mode;
- every ordinary model-facing run deterministically requests a collapsible trace
  entry, while fact-only domain events keep trace display disabled; this
  presentation policy does not depend on semantic intent classification;
- `CapabilityResolver` exposes resident, explicitly pinned,
  attachment-required, and bounded continuity capabilities without predicting
  a chat/code/explore class;
- `ExecutionMode` therefore describes only deterministic domain-event handling,
  not chat/code/explore/orchestration model paths.

This distinction is intentional. Removing the pre-router does not mean removing
typed ingress or validation. It removes an extra semantic prediction whose
output previously duplicated decisions the main model had to make again.

## Initial Capability Resolution

`CapabilityResolver` constructs a bounded, auditable initial tool surface before
the first model call. Its inputs are deterministic:

- resident system tools;
- base tool names referenced by an inline skill's pre-approval rules;
- attachment resolver tools required by current/replied-to assets;
- a bounded continuity pin for a recent failed tool;
- model support for tool calling, feature flags, registrations, and effect
  metadata.

The user's message text is deliberately not an input to initial capability
resolution. Ordinary messages with the same deterministic runtime inputs expose
the same name-sorted tool schemas, so keywords or negation cannot perturb the
provider prompt-cache prefix. The initial surface changes only for an explicit
skill, current/replied-to attachments, bounded failed-tool continuity, model or
feature availability, or registry/configuration changes.

A local-write or unknown-effect pinned capability also causes `verify` to be
exposed when available. It is a policy companion and cannot be silently removed
to satisfy a soft count target; declared model schema limits fail closed instead.

Pinned skill tools are optional capabilities, not hard run requirements. A model
without tool calling may still execute the skill instructions without them.
Attachment resolver tools are hard requirements because the current message
cannot be grounded without resolving its managed assets. Patterned rules such as
`bash(git diff *)` pin only `bash`; the full pattern travels separately on the
run and is matched against actual arguments at the permission boundary.

The initial surface is bounded by `CapabilityResolver` before the first call.
`ModelCapabilityProfile` then fail-closes model-shape constraints such as native
image support, tool calling, image-plus-tool support, tool-schema count, and
schema-token limits when the active profile declares them. It never silently
drops a required attachment or pinned capability to make a call fit.
Tool-schema count and schema-token limits travel through the same production
model metadata, per-model override, and per-scenario selection chain as context
window and output-token limits. An undeclared limit remains unknown; a declared
limit is projected into the resolved model context and enforced before the first
provider call.

If the first surface is insufficient, the model may use the resident,
bounded `find-relevant-tools` capability during the loop. Metadata retrieval and
L4 advisory reranking happen only inside that explicit discovery step. The
runtime appends at most two admitted capabilities for the turn, reserves one of
those slots for `verify` when a discovered capability has a local-write or
unknown effect, and records `CAPABILITIES_EXPANDED`; it does not restart semantic
routing. This intentionally changes the tool-schema prefix only for a run that
has produced evidence that its stable initial surface is insufficient.

## `AgentRunRequest`

`backend/src/magi/agent/execution/function_calling/run_input.py` defines the
single model-facing request contract. It carries:

- typed `UserTurnInput`, effective system prompt, history, summary, reply and
  ephemeral context;
- selected tools and a snapshot of capability resolution;
- user/session/turn identity plus one canonical `run_id`, optional parent run,
  and a separate background task ID owned by the scheduler;
- execution preset, workspace, model capabilities, timeout, and task bounds;
- `ReasoningPolicy` and current `ReasoningState`;
- `CompletionPolicy` and a run-bound reader for the current versioned
  `RunPlan`;
- `RunControl`, checkpoint, and context-source snapshots.

`AgentRunRequest.headless(...)` is used by background and child execution. It
cannot smuggle chat presentation services into the engine. Chat-specific prompt
assembly and outcome projection stay in the chat driver.

## Unified Agent Loop

`AgentRunHandler` prepares the request. `FunctionCallingOrchestrator` and
`FunctionCallingLoopRunner` execute it. One logical iteration is:

```text
safe-boundary control/input drain
  -> resolve effective reasoning depth
  -> model call with current capabilities
  -> if tool calls: permission/effect admission -> execute -> record evidence
  -> if child launch: execute bounded child run(s) -> return structured results
  -> if proposed final: evaluate CompletionGate
       complete  -> finish
       continue  -> append repair observations and iterate
       blocked   -> finish with a governed blocked outcome
```

The runtime owns maximum iterations, model/worker reservations, timeouts,
permission waits, effect identities, repair bounds, context compaction, and
cancellation checks. The model owns semantic decomposition and the choice of
next action within the exposed capabilities.

The loop runner owns sequencing only. `FunctionCallingModelCapabilityFlow`
owns model-shape validation and attachment grounding;
`FunctionCallingRunJournal` owns privacy-safe manifest/context/terminal event
projection; and `FunctionCallingToolBatchJournal` owns requested-tool,
tool-result, evidence, and child-run projection. Tool execution, cancellation,
suppression, and retry policy stay in `FunctionCallingToolBatchExecutor`.

There is no `DirectLLMHandler`, `TaskOrchestrator`, `ExploreTaskAgent`, route
graph, or route-derived handler registry for ordinary turns. A simple chat still
costs one main model call because it naturally takes the shortest path through
the same loop.

## Tool Effects And Replay

Every executable tool is normalized through canonical effect metadata:

- effect class: `read_only`, `local_write`, `external_write`, or `unknown`;
- replay policy and semantic effect identity;
- permission/risk metadata;
- whether uncertain outcomes must be reconciled.

The invocation service records effect attempts before calling effectful tools.
An ambiguous or uncertain attempt is not automatically replayed. Provider-level
idempotency is still required for remote systems; a local ledger cannot make a
remote transaction atomic.

Every tool call crosses the permission gateway, including skill-originated and
child-agent calls. Missing gateway wiring, provider lookup failures, and gateway
exceptions deny execution; they never become an implicit allow. Permission
precedence is deterministic: the system kill list and plan-mode guard run before
skill pre-approval, cached user rules, mode/risk policy, or channel auto-approval.
A skill rule can suppress an interactive prompt for the exact matching call, but
cannot bypass hard safety or plan-mode restrictions. Tests that need permissive
execution must inject an explicit test gateway rather than relying on a runtime
fallback.

Tool results become `ToolExecutionEvidence`. The completion gate consumes this
normalized evidence instead of trusting a model claim that work succeeded.

## Completion Gate And Repair

`CompletionGate` is deterministic. It evaluates a proposed final response using
the run's policy, tool evidence, current canonical plan, and repair count.

It enforces these current invariants:

- an uncertain effect blocks completion until reconciled;
- every required plan item must be terminal and completed items must cite
  successful, task-substantive evidence from the current run; permission,
  discovery, ask, and plan-maintenance calls cannot prove task completion;
- failed validation must be followed by a successful validation after repair;
- canonical `verify` outcomes treat `fail` as failed validation; `timeout` and
  `skipped` are inconclusive, cannot satisfy validation, and do not by
  themselves justify deeper reasoning;
- local-write and unknown-effect work must have current validation evidence;
- repair cannot exceed the configured budget.

Every rejected proposal produces a stable completion reason. A repairable
rejection emits a repair observation for the next model step. If the repair or
task budget is exhausted, the journal emits `REPAIR_EXHAUSTED` and the run ends
with the real blocked/unverified state; it does not disappear as a generic
finalization failure.

Gate rejection is not a hidden fixed workflow such as “always plan, then act,
then validate.” Simple conversation skips plans, tools, and validation. The
runtime adds those constraints only when observed effects, an explicit plan, or
evidence make them necessary.

## Reasoning Depth Policy

Reasoning depth has four layers of ownership:

1. **Explicit preference.** `auto`, `fast`, or `deep` enters through the typed
   message envelope or the corresponding slash control.
2. **Preset baseline.** Chat/background/child presets select an initial depth,
   maximum depth, and escalation budget.
3. **Model/provider clamp.** `ModelCapabilityProfile` maps the requested depth to
   what the active provider/model can actually support.
4. **Evidence-driven escalation.** Validation failure or another completion
   rejection marked `reasoning_helpful` may raise the next policy target
   monotonically.

Composer controls and the `/auto`, `/fast`, and `/deep` modifiers edit the
visible draft prefix rather than hidden UI state. On submit, that prefix writes
only to the current user-turn envelope and is removed from the semantic message
body. The canonical transcript payload preserves an explicitly selected
preference so the user bubble can render the modifier without adding it back to
model or memory content. It is not global or session configuration. A retry
preserves the original turn's explicit preference because it reuses the
already-built envelope.

The resident `request_reasoning_depth` control lets the model request one
policy-defined increase for a small stable set of reasons such as conflicting
evidence or stalled reasoning. The request is advisory: `ReasoningPolicy` may
deny it because of `fast` mode, the maximum depth, or the escalation budget.
Permission, dependency, network, uncertain-effect, user-input, and exhausted-
budget blockers are not reasoning problems and must not be converted into an
escalation.

Approval and denial are both successful runtime-control outcomes. A denial is
recorded in tool evidence and structured logs, then execution continues at the
current depth. It is not promoted to a task error or narrated in the final
answer unless the user explicitly asks to inspect reasoning controls. The tool
result carries an internal visibility marker and an explicit continuation action
so the model cannot reasonably confuse a policy limit with task failure.

`ReasoningState` is checkpointed. Escalation cannot lower depth, exceed the run
maximum, or reset its counter on retry. A validation-required rejection caused
only by missing evidence does not automatically buy more reasoning.

Operationally, ordinary `auto` chat starts at low depth without a router call,
then moves to high and max after at most two independently approved escalation
signals. `fast` starts at none and is capped at low. `deep` starts at medium and
moves through high to max where the provider supports it.

Provider input is assembled in three lifecycle layers instead of one repeated
per-turn blob:

- the Stable Prompt Epoch contains identity, durable behavior constraints, and
  other byte-stable system instructions;
- Runtime World State contains host-owned facts such as local date, IANA
  timezone, OS, working directory, and active agent identity. The first run
  emits a full snapshot; later runs emit another full, superseding snapshot only
  when those canonical fields change or recovery finds no raw snapshot. Exact
  wall-clock time is deliberately absent and is read through
  the resident read-only `current_time` tool when a task actually needs it;
- Working Context contains run-local persona steer, bounded memory recall,
  profile projection, attachment extraction, reply/continuity hints, inline
  skill instructions, and capability guidance. It is visible and reconstructible
  for every call in the run, but is removed when the run is promoted to the
  Session Accepted Surface.

A launch-only typed envelope is the short-lived subset of run-local context used
to explain why a child or detached run started. It remains distinct from Working
Context, survives any compaction before the first provider call, and is removed
by runtime provenance after the first completed tool iteration. The runtime never
tracks this envelope by a mutable message-array index.

Runtime World State, Working Context, and launch-only context use explicit typed
message envelopes. They may project to provider `user` messages for wire
compatibility, but their content identifies them as runtime-owned and they are
never treated as authored user turns. Classification uses runtime-only
provenance metadata rather than a user-spoofable text tag; provider conversion
strips that metadata before the API call while retaining the explanatory
envelope text. The actual user message remains a separate item after them. The
runtime restores or replaces each typed layer independently. Detecting that the
current user turn is already present only suppresses a duplicate user message;
it never suppresses fresh Runtime World State, Working Context, or an unexpired
launch envelope. Launch context is not restored after a completed tool
iteration. The
Stable Prompt Epoch must contain exactly one cache boundary and end there. Every
`AgentRunRequest` rejects a missing, duplicated, or tailed boundary; headless
drivers that do not define specialized stable rules receive the canonical
headless prompt epoch.
Fallback finalization and forced plain-text retry rules are also typed Working
Context. They do not rewrite the Stable Prompt Epoch and cannot be promoted as
user-authored conversation history.

Every provider-visible message is materialized before the next model call. This
includes typed context envelopes, user messages, assistant tool-call messages,
tool results, runtime observations and controls, compaction summaries, and
accepted assistant responses. During execution these messages live on an
isolated run Working Surface. A later call in the same run resumes that surface;
a later turn starts only from the Session Accepted Surface. Model history is
never reconstructed from the visible transcript. This preserves tool-call
identifiers and the exact causal chain the model already observed without
letting an unaccepted draft or turn-local recall become future session history;
runtime controls are not silently removed between calls in the same run. Their
exact causal position remains reconstructible from immutable call boundaries,
but run-only controls are removed when a successful outcome is promoted to the
Session Accepted Surface so later turns do not inherit completed repair rules.
Each internal runtime message also carries a stable context-item identity and
its originating turn where applicable. This provenance is persisted beside the
provider-neutral message, survives compaction and resume, and is stripped before
provider conversion. Context alignment must use that identity; repeated message
text is never sufficient evidence that two context items are the same.

The cacheable system head and tool declarations are stored separately as a
deduplicated context epoch. Each model-call boundary references one surface
revision and one epoch, plus provider-neutral call options such as requested
reasoning depth, JSON mode, and timeout. Revisions are immutable, including
revisions no longer at either frontier, so diagnostics can reconstruct the
exact request shape without copying prompts into the privacy-safe runtime
trace. Persisting a call boundary and its Working Surface happens in one SQLite
transaction. The provider request keeps the stable system/tools/older-history
prefix first; any changed Runtime World State, the current Working Context, and
the current user message follow it. The rolling cache breakpoint is placed
before the first of those dynamic messages. A changed system head, tool set, or
provider reasoning profile may still start a new cache partition. Cache reuse
remains an optimization and never changes semantic context ownership.

Chat, foreground child, background child, detached, scheduled, batch, and forked
skill runs all enter this same lifecycle contract. Child task descriptions and
capability hints belong to Working Context, parent snapshots belong to launch-
only context, and the host captures Runtime World State when the execution
attempt actually starts. Forked skill instructions are Working Context rather
than a dynamic system prompt. Attachment-grounding and finalization instructions
also use typed Working Context, so no runtime path appends instructions beyond
the stable cache boundary.

A chat-derived background run is only created by detaching a live unified run.
Its launch service requires the complete `AgentRunCheckpoint`; it never rebuilds
a chat prompt from a goal string or silently falls back to a generic headless
prompt. Scheduled, batch, and other standalone background work construct their
own explicit headless specs and do not use the chat detach service.

Universal read-only runtime facts are admitted at the shared model-capability
boundary before the effective tool set is journaled. `current_time` is therefore
available to every tool-capable driver without repeating exact wall-clock time in
prompts. Driver-specific control tools and child preset capabilities remain
separate; universal fact admission does not give leaf agents parent control
capabilities and is skipped for models without tool calling.

## Versioned Run Plans

The model uses `todo_write` when a user-visible plan materially helps execution.
The runtime owns plan ID, version, transition validation, and optimistic
concurrency. Plan items may be patched rather than replacing the whole plan.

Important invariants:

- at most one item is `in_progress`;
- completed required items cite current-run evidence;
- blocked items carry a reason;
- cancellation marks the run-owned active plan cancelled;
- the completion gate reads the current `RunPlan`, not model prose.

`run_id` has one meaning across the journal, plan store, tool context,
checkpoint, and child `parent_run_id`. The chat session coordinator's active
run ID becomes this canonical ID when the request is built. A background
`task_id` remains a scheduling/delivery identity and never replaces `run_id`.
Detach preserves the foreground `run_id`; the checkpoint records its current
plan ID and version, and resume fails if that plan cannot be resolved. The plan
store may retain independent plans for multiple runs in the same session.

A successful `todo_write` atomically replaces the versioned `run_plans` row.
`PLAN_UPDATED` carries only the plan ID and version as an observability signal;
it is not a duplicate snapshot. `ChatTraceReadService` reads the plan row and
run events from one SQLite snapshot, so a crash between plan persistence and
later journal notification cannot make an old journal payload override current
plan truth. The retired `todo_state`
chat message and `/control/.../todos` duplicate read API no longer exist. The
workspace cache stores file-read, edit-journal, and rollback-snapshot evidence
only; it has no plan or todo model, so a restart cannot create a second plan
truth outside `run_plans`.

## Child Runs

The parent model decides whether decomposition is useful by calling the `agent`
tool. `ChildRunCoordinator` owns the mechanics:

- `launch`, `status`, `await`, and `cancel` actions;
- single or batch children, optionally parallel;
- parent/child identity and run-revision ownership;
- shared task-level model/worker budgets;
- bounded iteration/await timeouts;
- cancellation propagation and structured result validation.

Presets are capability policies, not semantic task classes:

- `read_only` — read-only tools, low baseline reasoning;
- `workspace_write` — read plus local-write tools, medium baseline reasoning;
- `review` — read-only review surface, medium baseline reasoning;
- `default` — conservative read-only fallback.

Children execute the same unified loop through `AgentRunRequest.headless`. They
cannot recursively launch `agent`, update the parent plan, ask the user, or
detach themselves. Their allowed tools are derived from effect metadata, and
their reasoning ceiling cannot exceed the parent's policy or remaining budget.

## Active-Run Input, Replacement, Cancellation, And Detach

`SessionRunCoordinator` owns one active foreground run per chat session.

Ordinary text received while that run is active is persisted as another user
turn and attached to the run with the single disposition `message`.
`RunInputQueue` drains it exactly once at the next safe model-step boundary and
adds a typed `RunInputMessage` to context. The old AUGMENT/STEER/DEFER semantic
classifier and its extra LLM call are retired.

An explicit `run_disposition=replace` follows a different deterministic path.
It is durably queued as the replacement root, never injected into the old
model context, and cancels the exact active run plus its owned children and
plan. Once that run reaches its terminal boundary, the delivery ledger admits
the replacement as the next root run. This is replacement within one session;
starting a separate task remains the client-owned `/new-session` action and is
not encoded as an in-flight run signal.

Structured interactions that must start a new root turn remain separate from
in-flight text injection. They are not flattened into arbitrary user prose.

Cancellation has two explicit paths:

- structured `/cancel` or UI cancellation;
- a narrow exact-phrase fallback checked by `cancel_protocol.py` against the
  managed phrase list.

The fallback accepts only an unambiguous whole-message cancel protocol; it does
not semantically classify normal text. Durable turn cancellation and active-run
cancellation share the same ownership boundary, so cancellation can win before
admission or stop the exact already-created run. Tools, child launches, model
steps, and final delivery recheck the cancel token at side-effect boundaries.

Detach transfers eligible foreground work into the background runtime through a
typed control/tool path. The background task receives the trigger, remaining
budget, canonical run identity, run-bound plan reader, context snapshot, and
cancellation ownership explicitly; detach is not inferred from arbitrary prose.

## Persona Boundary

Persona planning receives task/runtime signals but does not own execution
routing. It classifies conversational register and applies hard safety/quiet
clamps inside `PersonaTurnPlanner`. The persona plan influences prompt voice,
not capability authorization, completion, or effect policy.

There is no dependency on a `ContextDecider` hint. Persona behavior must remain
correct for ordinary chat, technical analysis, tool work, emotional support,
and safety cases using the typed turn/context signals available at prompt
assembly.

## Durable Run Journal And Trace Projection

`runtime_trace.db` contains:

- `agent_run_manifests` — insert-once prompt, message, tool-schema, and
  context-source fingerprints plus non-content provenance;
- `agent_run_events` — ordered lifecycle facts;
- `run_plans` — versioned plan snapshots;
- normalized spans/tool/model rows for lower-level tracing;
- runtime notifications and plugin ingress records.

Important run events include model output, tool request/result/effect admission,
capability expansion, plan version notification, child lifecycle, validation,
completion decision, repair start/exhaustion, reasoning-depth change,
suspension, blocked, completion, failure, and cancellation.

`ChatTraceReadService` prefers canonical run events when they exist and falls
back to normalized trace rows only for non-unified producers. For unified runs,
canonical events own lifecycle structure and status while normalized model/tool
rows enrich the matching nodes with input/output previews, execution timing, and
provider details. The join uses step identity for model calls and tool-call ID
for tools, then reapplies cancelled-draft redaction. It also joins the current
canonical plan by `run_id`; the combined projection is the source for:

- current plan summary;
- child, validation, repair, and reasoning nodes;
- run status and duration;
- model/tool/validation/repair/child counts;
- first-action and total runtime latency;
- token totals, reasoning escalation count, and repair exhaustion count.

The desktop gateway proxies chat history and trace-detail reads to this
canonical Python projection. It must not maintain a second SQL-to-trace
projection in Rust, because that duplicate would have to reproduce run-event,
plan, and schema evolution semantics.

The journal is an observability source, not a second prompt archive. Manifests
and `CONTEXT_PREPARED` events never copy system prompts, conversation messages,
rendered memory/persona/skill context, tool schemas, or attachment bytes. They
store deterministic digests, encoded sizes, counts, and stable source IDs. The
chat-owned Model Context Log retains reconstructible foreground context; an
explicitly persisted background handoff checkpoint may retain the model-facing
context required for headless continuation. Chat forgetting removes both through
their owning session or origin-turn boundaries.

Visible transcript truth and model-context truth both live in `chat.db`, but in
separate schemas with separate consumers. Execution plans and intermediate
runtime state are not duplicated as visible chat messages. Runtime notifications
are best-effort wakeups; reload always reconstructs from durable stores.

The backend text log also emits privacy-safe `agent_run.*` breadcrumbs for
manual diagnostics: run start/resume/terminal, step boundaries, requested and
finished tools, safe-boundary input injection, completion decisions, reasoning
escalation, context-layer materialization, and model-capability or attachment-
grounding outcomes. Context-layer breadcrumbs report only whether world state
was emitted and the character counts of the runtime/working layers. These
records include stable IDs, reason codes, counts, tool names, and policy state,
but never user message bodies, tool arguments, tool results, prompts, or
attachment observations.

## Persistence Boundaries

- `chat.db` — sessions, turns, visible messages, attachments, reply/label state,
  accepted-turn delivery ledger, the append-only Model Context Log, immutable
  surface revisions, the Session Accepted Surface pointer, per-run Working
  Surface pointers, model-call epochs/boundaries, named boundary summaries, and
  projection intents;
- `runtime_trace.db` — run manifests/events/plans, normalized execution traces,
  and live notification records;
- `message_queue.db` — durable command admission and delivery attempts;
- `background_tasks.db` — background specifications, attempts, effect ledger,
  completion intents, and budgets;
- memory databases — governed memory facts and lifecycle state, never the
  source of truth for active execution recovery;
- `scheduler.db` — schedules, target state, execution records, and sensor jobs.

The retired `orchestration_id` column has been removed from chat, trace, and
background current schemas. `run_id`, `parent_run_id`, turn identity, and task
identity are the only execution ownership seams.

## Prompt History And Context Capacity

Chat prompt assembly combines:

- the active run's ordered Working Surface when it exists, otherwise the
  Session Accepted Surface, loaded from `chat_model_context_*`;
- the Stable Prompt Epoch, changed-only Runtime World State, and current
  run-local Working Context and launch-only snapshot as separate typed inputs;
- the current typed turn and reply target;
- managed attachment references;
- bounded recent tool-state continuity;
- memory retrieval and persona plan;
- explicit inline skill context;
- the current tool schemas only on calls that send tools.

Prompt assembly also records memory capability facts separately from retrieval
results: whether bounded memory retrieval is available, whether it was
retrieved, empty, bypassed, unavailable, or failed, and whether `memory_query`
is exposed. An empty bounded result is never represented as proof that the user
has no relevant history, and a retrieval outage does not fail an otherwise
valid chat turn.

Before each foreground model call, the loop synchronizes the exact provider-
neutral message list into that run's Working Surface and atomically records a
boundary referencing the matching system/tool epoch and immutable revision.
After an assistant tool-call response, each tool result, attachment-grounding
observation, compaction, and repair control, it commits the updated Working
Surface before any later call can depend on it. Raw image bytes are not copied
into SQLite; stable attachment handles remain resolvable by the chat domain.

The Working Surface is never accepted merely because a model produced text.
Visible assistant delivery and model-context promotion share one transaction.
Promotion removes the current run's Working Context and launch-only context,
unaccepted assistant drafts, and superseded Runtime World State snapshots, then
appends the exact visible assistant outcome. Only the latest host-owned snapshot
is retained; memory recall, persona steer, attachment extraction, parent launch
snapshots, and other run-local material are not.
Cancellation, governed failure, and delivery recovery promote an explicit
runtime outcome instead. Terminal promotion canonicalizes the provider-neutral
transcript at this ownership boundary: an assistant tool-call message survives
only when the immediately following tool results answer every declared call ID
exactly once. An incomplete assistant/tool group and any orphan tool result are
removed before the runtime outcome is appended. The model boundary enforces the
same invariant defensively before every provider call and records only privacy-
safe repair counts, so an interrupted historical run cannot poison a later
turn. Cancellation persistence owns Accepted Surface promotion and closes the
run's Working Surface; after observing cancellation, the Agent Loop may journal
its terminal state but must not attempt a second Working Surface commit. If any
terminal chat write fails, both visible delivery and the Accepted Surface pointer
roll back, leaving the Working Surface and its call boundaries available for
exact retry. A recovered run loads its Working Surface by `run_id` and replaces
the current user payload in place when richer attachment bytes are available; it
never appends the same user turn after an assistant/tool tail.

Display-history pagination never defines model context. Under pressure, the
runtime compactor creates a new immutable Working Surface revision while the
prior revision and its model-call boundary remain readable until governed
deletion. Compaction keeps complete protocol groups and tool-call identifiers.
It excludes runtime-owned context envelopes from summary input, retains only the
latest Runtime World State, current Working Context, and active launch-only
context as raw typed messages, and places them after the new compaction boundary.
Consequently, superseded host state is dropped, launch context remains removable
after reindexing, and run-local recall cannot leak into a durable compaction
summary that would survive Accepted Surface promotion.
The active model's input/output limits determine the capacity decision, and
provider-facing prompt measurement occurs before every model call.

`chat_context_summaries` is an explicitly named boundary-summary cache, currently
used for persona-switch continuity. Persona boundary detection and retained-tail
rendering consume canonical Model Context events and their persona provenance;
they never rebuild from visible chat rows. This preserves assistant tool-call
messages, tool results, runtime controls, and correct A-to-B-to-A switch-back
boundaries. The summary cache is not the normal prompt-history owner and has no
implicit `token_budget` mode. L0 is a disposable semantic-attention projection;
it may contribute to the current run's Working Context but never stores either
model conversation frontier.

Ephemeral onboarding persona preview uses the same three rendered artifacts and
projects Runtime World State and Working Context as typed messages before the
preview user's current message. It does not rebuild dynamic persona steer into
the system prompt or introduce a preview-only prompt path.

There is deliberately no import from historical transcript rows into the Model
Context Log. A pre-cutover session therefore starts with an empty Context Surface
and Accepted Surface on its first new turn. This project is pre-release and does
not carry a legacy
fallback that would create two competing prompt histories.

## Background And Scheduled Execution

Background tasks, scheduled agent tasks, fork-context skills, and child runs all
call the unified loop with explicit presets and durable budgets. A fork-context
skill is a background root task so the foreground chat remains available; it is
not represented as a child owned by an unrelated active foreground run. Child
lineage is reserved for work launched by a parent through the `agent` tool.
Child environment prompts follow the same clock rule: they carry local date and
timezone, while exact wall-clock time comes from the resident `current_time`
tool.
Background completion is stored before delivery fan-out so startup can resume
pending completion intents without rerunning the model task.

Scheduler targets own timing and enqueueing. The background runtime owns model
and tool execution. Successful user-facing results are projected back to the
originating chat as ordinary assistant outcomes while background rows remain
available for audit.

## Delivery, Recovery, And Privacy Boundaries

Chat acceptance is a single chat-domain transaction covering the session/turn,
first user message, attachment ownership, and initial delivery record. Runtime
queue admission is durable at-least-once; execution side effects are not
globally atomic with that queue.

The accepted final chat surface is idempotent by stable turn and delivery
attempt. A stale attempt cannot close or overwrite a newer run. Assistant memory
projection begins only after the visible outcome is durable.

Explicit deletion and full clear establish barriers before active work,
recovery workers, plugin ingress, projections, and memory writes may continue.
L0 does not persist active runs or pending run input. A missed in-process
post-turn analysis may be lost, but durable chat truth and run journals remain
recoverable.

External channel replies still occur after the durable chat commit without a
per-target durable egress outbox. A crash in that gap may preserve the desktop
answer while losing the external send; this path must not be described as
exactly-once delivery.

## Layer Ownership

- `agent/execution/` owns the unified run request, loop, journal, capability
  policy, reasoning state, effect evidence, completion gate, context-port
  contract, and checkpoints;
- `agent/workers/` owns bounded child-run mechanics and presets;
- `agent/task_agents/` owns generic task-agent hooks and handler contracts;
- `chat/task_agent/` owns the chat adapter for the Model Context Log, typed
  context-layer assembly, session/run admission, safe-boundary input, presentation,
  post-processing, and transcript outcome policy;
- `commands/` and `skills/` own typed slash resolution and expansion;
- `control/` owns permissions, asks, plan state, run control, and user-content
  clear coordination;
- `runtime_trace/` owns durable execution observability and read projections;
- `bootstrap/` only composes these owners.

The agent layer must not import chat presentation or persistence implementations.
Chat supplies narrow protocols and constructs `AgentRunRequest`; the loop returns
a domain-neutral execution result.

## Cost And Latency Consequences

| Scenario | Current model calls | Runtime consequence |
| --- | --- | --- |
| Simple chat | one main call | no serial router latency |
| Ordinary tool task | main loop calls only | stable initial capability resolution is local; discovery expands only on model request |
| Inline skill | skill expansion plus main loop | no additional intent call |
| Child decomposition | parent calls plus child calls | fan-out occurs only when the parent requests it |
| Validation repair | additional main repair calls | paid only after observed evidence requires repair |
| Model reasoning request | no routing call | may raise effort on a later step only if policy approves |
| Active-run replacement | no classifier call | old run cancels before the durable replacement becomes root |
| `fast` / `deep` | same call count | changes reasoning effort/budget, not route shape |
| Model-context durability | no additional model calls | one atomic local transaction before each model boundary; changed surfaces allocate an immutable revision and reuse unchanged events |
| Accepted-surface promotion | no additional model calls | joins the terminal chat transaction; failures roll back both surfaces rather than leaking draft state |
| Persona switch | one summary call only when a foreign-persona prefix exists and no exact cache entry exists | operates on canonical model context and preserves the retained protocol tail |

The architecture removes one serial auxiliary LLM call from every ordinary
turn. It may spend extra calls when capability recovery, child work, or repair
is actually needed. Those costs are evidence-driven and visible in runtime
metrics.

## Files To Read First

- `backend/src/magi/chat/task_agent/turn_admission_service.py`
- `backend/src/magi/chat/task_agent/coordinator.py`
- `backend/src/magi/chat/model_context.py`
- `backend/src/magi/chat/task_agent/model_context_port.py`
- `backend/src/magi/chat/storage/model_context.py`
- `backend/src/magi/chat/task_agent/persona_boundary.py`
- `backend/src/magi/agent/execution/function_calling/run_input.py`
- `backend/src/magi/agent/execution/function_calling/loop_runner.py`
- `backend/src/magi/agent/execution/function_calling/model_capability_flow.py`
- `backend/src/magi/agent/execution/function_calling/run_journal.py`
- `backend/src/magi/agent/execution/function_calling/step_tool_batch.py`
- `backend/src/magi/agent/execution/function_calling/tool_batch_journal.py`
- `backend/src/magi/agent/execution/capability_resolver.py`
- `backend/src/magi/agent/execution/completion_gate.py`
- `backend/src/magi/agent/execution/reasoning.py`
- `backend/src/magi/control/tools/reasoning_depth_tool.py`
- `backend/src/magi/agent/execution/journal.py`
- `backend/src/magi/agent/workers/worker_manager.py`
- `backend/src/magi/chat/task_agent/run_input_queue.py`
- `backend/src/magi/runtime_trace/chat_trace/run_event_projection.py`
- `backend/src/magi/runtime_trace/run_events.py`

## Contributor Rules

- Do not add a semantic pre-router for ordinary turns.
- Add a deterministic branch only for protocol, ownership, safety, permission,
  effect, budget, or persistence invariants.
- Do not create a second direct/chat/code/explore loop.
- Add capabilities through registry metadata and runtime resolution, not phrase
  dictionaries in the chat driver.
- Keep current plans in `run_plans` and intermediate lifecycle in the run
  journal/read projection, not the chat transcript.
- A child execution feature must use `ChildRunCoordinator` and the unified loop.
- Every new effectful tool must declare effect/replay metadata and have a
  validation story.
- Tests should prove the current contracts. Delete tests whose only purpose is
  to preserve retired routes, fields, or compatibility behavior.
