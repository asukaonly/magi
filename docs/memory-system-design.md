# Memory System Design

## Purpose

This document is the long-term source-of-truth for Magi's memory system. It answers two categories of questions:

- **For product stakeholders**: What does Magi remember, what does it not, and where does each type of data live?
- **For developers**: What contracts govern layering, ingestion, retrieval, identity, idempotency, and downstream cognition?

Related root documents:

- [Project Overview](./project-overview.md)
- [Layered Agent Architecture](./layered-agent-architecture.md)
- [Task-Agent Runtime Architecture](./task-agent-runtime-architecture.md)
- [Unified Plugin Architecture](./plugin-extension-architecture.md)

If this document conflicts with the above, they should be revised together. This document refines the memory subsystem; it does not redefine project-level boundaries.

---

## What the Memory System Solves

Magi's memory system organizes local conversations, external activities, and selected runtime results into short-term attention and retrievable, compressible, long-term memory — while keeping chat truth, runtime traces, and plugin intermediate state cleanly separated.

It is responsible for:

- Maintaining short-term attention for the current session
- Projecting selected facts into durable event memory
- Extracting structured cognition from retained events
- Compressing long histories into reviewable summaries and insights
- Distilling reusable execution experience

It is **not** responsible for:

- Serving as the source of truth for complete chat transcripts
- Serving as the source of truth for runtime spans, tool traces, or execution telemetry
- Permanently storing every raw producer payload
- Rendering persona-voiced chat UI cards; memory may provide traceable snippets,
  but chat/persona layers decide how those snippets are presented in a turn

Magi's memory model is layered by **information lifecycle**, not by functional plugin. `L0` is the disposable attention projection over accepted conversation turns; durable memory begins at `L1`:

- `L0` — Short-term attention
- `L1` — Normalized event facts
- `L2` — Structured cognition (with three product subdomains: semantic, state, episodic)
- `L3` — Reflection and summaries
- `L4` — Procedural memory

---

## Mental Model

The memory system has one short-term attention path and one durable evolution path:

```text
Accepted completed chat turn
  -> Shared post-turn understanding
  -> L0 attention delta for the next turn
  -> Optional, separately validated personality or durable-memory candidates

Source signal
  -> Normalized event contract
  -> Routing and retention policy
  -> L1
  -> Optional L2 cognition
  -> Optional L3 reflection
  -> Optional L4 experience distillation
```

Examples:

- A user chat message and its accepted assistant reply are first chat truth in `chat.db`. Once that complete turn is durable, shared post-turn understanding may update the session's `L0` attention for the next turn, while selected content is projected independently into `L1`.
- A Chrome browsing burst is aggregated into an `L1` event, which may later feed `L2` relation extraction and `L3` temporal summaries.
- A worker heartbeat is runtime telemetry and should not enter long-term user memory.
- A task completion result may be worth retaining in memory, but the detailed execution trace stays in the runtime trace store.

The memory system sits between "raw data sources" and "higher-level reasoning". It is not the raw data source itself.

Sensor ingestion follows the same ownership rule. `awareness/` publishes the
neutral `SensorEventEmitted` envelope; `memory/` owns the conversion from that
envelope into a `MemoryEvent`. Timeline read-model projection is owned by
`timeline/`. This keeps sensor capture separate from memory retention and
timeline presentation.

---

## Runtime Boundaries and Data Stores

Magi explicitly separates chat truth, runtime observations, and persistent memory into different stores.

### Chat Truth

- `~/.magi/data/chat/chat.db`

Holds:

- `chat_sessions`
- `chat_turns`
- `chat_messages`

Read here when you need complete chat transcripts, turn presentation state, or chat-domain read models.

### Runtime Observations

- `~/.magi/runtime/runtime_trace.db`

Holds:

- Turn summaries
- Tool calls
- LLM metrics
- Spans
- Live notifications
- Append-only plugin ingress events

Read here when you need execution replay, debugging, traces, or raw plugin ingress events.

Important rule: runtime observations can feed lightweight prompt-time continuity summaries, but those summaries are lossy and session-scoped. They do not promote execution telemetry into durable memory and do not replace trace inspection tools.

### Persistent Memory

- `~/.magi/data/memory/l1_events.db`
- `~/.magi/data/memory/memory.db`

Holds:

- `L1` fact events stored in `l1_events.db`
- `L0`, `L2`, `L3`, `L4` stored in `memory.db`

Read here when you need historical recall, structured cognition, summaries, long-term insights, or procedural experience.

Product reads must distinguish a successfully opened L1 store with zero matching
events from an unavailable, missing, or unreadable `l1_events.db`. Store failures
return an explicit service-unavailable error and the UI presents a retryable error
state; they must never be rendered as an empty memory history.

### Rebuildable Cache

- `~/.magi/cache/plugins/<plugin_id>/`
- `~/.magi/workspaces/<workspace_id>/cache/`
- `<workspace>/.magi/cache/`

Holds plugin-owned rebuildable intermediate state:

- In-progress sensor aggregation state
- Flush checkpoints
- Plugin-local computation caches
- Workspace-scoped code indexes and retrieval caches

**Cache is not memory truth.**

Workspace overlays may also hold project instructions, rules, skills, and gitignored runtime checkpoints under `<workspace>/.magi/`. These files are project context or recoverable execution state. They must not be treated as durable memory unless a memory projection pipeline explicitly promotes selected facts into `L1`.

### Memory Data Portability

Memory backup and readable export are separate product contracts:

- A version-1 `.magibackup` is restorable. It contains consistent SQLite
  snapshots for L1 and the shared L0-L4 store, configured memory archive
  databases, and only content-addressed manual-entry assets that still have a
  visible owner in memory. Every payload file has a size, purpose, and SHA-256
  digest in a versioned manifest. Optional password protection encrypts and
  authenticates the complete ZIP payload with AES-256-GCM using the single
  version-1 Argon2id profile recorded by the outer envelope.
- A readable export is a non-restorable ZIP of versioned JSONL records, a
  manifest, field guidance, and referenced managed assets. It intentionally
  omits vector indexes, full-text indexes, worker leases, and background-job
  state. L0 may be included only when the user explicitly requests it.

Readable export version 1 is a public DTO contract, not a serialization of the
SQLite schema. Its JSONL files are grouped by product meaning under `l0/`,
`l1/`, `l2/`, `l3/`, `l4/`, `governance/`, and `archives/<date>/`. Every record
has `record_type`, `schema_version`, and `layer`, followed only by the explicit
fields listed for that file in `schema.json` and `README.txt`. Those generated
field lists come from the same contract used to write each record. Storage
columns, tables, or archived-payload keys added later do not enter an existing
export version automatically; exposing new data requires a deliberate DTO and
version decision. Each file contract also records its exact emitted record
count in both `schema.json` and the manifest.

The stable DTOs cover source/category/time/status fields for L1-L4, optional
runtime L0 attention, source-event evidence, and durable correction and
forgetting lineage. L2 entity aliases, mentions, claim-to-entity references,
location samples, place labels, experience membership, seeds, seed evidence,
and chapters remain linked by their stable public IDs. L3 exports both the
field-sourced user profile and the evidence-backed self portrait. Structured
product values such as scopes, selectors, and source-event ID lists are decoded
into JSON values rather than leaking their SQLite text representation. Archived
payload blobs are projected through fixed field allowlists as well. Projection
highwaters, cache tables, experience drafts, indexes, leases, and jobs are not
public memory DTOs and remain excluded. The readable export cannot be restored
into Magi; `.magibackup` is the only restore artifact.

Readable export excludes soft-deleted L1 events, manual entries, and L4
procedures, including their owned source payloads, facets, and procedure traces.
Manual entries must also pass the same pending-deletion, replacement, and
time-range visibility barriers as their managed assets. Archived L1 payloads
marked deleted are omitted. Content-free forgetting markers remain in the
governance files; retaining a tombstone never permits exporting deleted text.

The restorable scope is persisted L0-L4, not every file under `~/.magi`.
Persisted L0 sessions and attention items are included in backup and restored;
in-flight execution state is not. Durable L0 forget cutoffs and tombstones remain
governance state. Chat transcripts and attachments, runtime traces, product
tasks, caches, local models, plugins, credentials, configuration, and persona
state are outside the memory backup contract. The L1 projection may retain
references to chat evidence, but a restored target that does not contain that
chat truth must present the evidence as unavailable rather than fabricate or
silently drop the memory record. History-import source content, speaker and
message identifiers, and source-file lists are redacted from the snapshot; only
opaque batch-to-event lineage remains so a restored import can still be removed
as a batch without carrying the raw imported transcript.

Snapshot creation holds the unified memory maintenance boundary, drains memory
writers, checkpoints persisted L0 for backup and for an explicitly requested L0
readable export, and uses SQLite's online backup API for every database. WAL,
shared-memory, and journal sidecars are never packaged. Excluded readable
content is securely removed from the private snapshot before packaging. The
readable exporter reserves a conservative JSONL expansion budget before writing
and converts a write-time out-of-space failure into `insufficient_space`.
Restore is replace-only; merge semantics are not part of version 1.

---

## Layer Overview

### L0 — Short-Term Attention

`L0` is the bounded, disposable attention state for the current conversation.
It answers one question: what must Magi still keep in mind to receive the next
turn naturally? Its current production source is accepted complete chat turns.
It is not a new source of truth and not a smaller long-term memory store.

It may hold:

- Current topics, concerns, and the user's immediate intent
- Explicit, time-bounded parts of the user's current situation
- Open loops such as unanswered questions, deferred threads, and promises;
  an executable task is one possible subtype, not the organizing center
- Active people, places, media, projects, or other objects, together with why
  each one matters in the current conversation
- Local constraints, recent decisions, and shared understanding that must
  continue to shape the next reply

Each attention item carries a compact neutral summary, source turn or event
references, whether it was explicit or inferred, confidence and salience,
first-seen and last-reinforced timestamps, and a lifecycle state such as
`active`, `background`, `resolved`, or `superseded`. An inferred item must never be
presented as a user-confirmed fact. Repeated evidence reinforces an item;
answers and explicit closure resolve it; corrections supersede it; a topic
shift lowers its salience. Those semantic updates can retire or background an
item before its fixed deadline; when no later update arrives, time-based
expiry is the safety fallback.

The storage and forgetting contracts reserve both turn and event provenance so
future governed producers can participate without weakening deletion rules.
No sensor or generic event-ingest path currently creates L0 attention.
Accepted chat outcomes produce semantic attention deltas, while durable
background-task attempt and terminal notifications directly reopen or close
only the task-linked open loop. Those lifecycle notifications never create
personality or durable-memory observations.

L0 is generated only from accepted, complete turns. The user message and the
accepted assistant outcome must already be durable in `chat.db`, and the exact
delivery attempt must be terminal, before the turn can enter attention
analysis. The current user message is therefore never copied into L0 before
answering that same message. Failed, cancelled, stale, superseded, internal
tool-only, or partially persisted turns do not enter the L0 analysis batch or
advance its last-processed marker.

Post-turn understanding is shared rather than duplicated across memory and
personality features. One bounded analysis batch may emit an L0 attention
delta, personality or relationship observations, and candidates for durable
memory. Those outputs remain separate contracts: each owner validates and
stores only its own projection, and no L0 inference becomes durable merely
because it was produced in the same model call.

The default attention-update policy is:

- Update after three newly accepted complete turns for the session
- Flush after 30 seconds of conversational idle time
- Enforce a 90-second maximum delay from the first pending accepted turn, even
  if later activity keeps resetting the idle timer

These values are configurable as
`attention_update_turn_threshold`,
`attention_update_idle_seconds`, and
`attention_update_max_delay_seconds`. Explicit correction, topic closure,
important current-state change, a new local constraint, or a promise that must
be carried forward may trigger an immediate update instead of waiting for the
batch when it matches the scheduler's conservative message patterns or one of
the explicitly urgent fact kinds. Unmatched wording follows the ordinary batch
timers. Repeated enqueue attempts for the same turn are suppressed while the
same scheduler instance still remembers that turn. There is currently no
separate semantic pre-filter that guarantees acknowledgement-only turns never
join a later analysis batch.

Attention updates run asynchronously and never delay display or delivery of an
accepted reply. One runtime-scoped service owns the pending batch queue, retry
timers, direct task-lifecycle updates, and deduplication across chat-agent
instances. The queue remains process-local: the accepted transcript is durable,
but pending analysis admission is not. Updates for one session are serialized,
while at most two model analyses run across distinct sessions, and failures are
retried with bounded exponential backoff. A stable accepted-outcome identity is
distinct from its source turn identity, so multiple durable deliveries of one
turn are not collapsed accidentally. Background task identity is additionally
scoped by attempt. Each model request contains at most 20 turns, each session
retains at most 60 pending turns, and the same fixed batch is attempted at most
three times. When the pending limit is reached, the oldest turn outside the
in-flight retry batch is discarded in favor of newer conversation context.
When all three attempts fail, that derived-analysis batch is discarded and
later queued turns continue immediately; the durable chat transcript is not
affected.

An analysis failure keeps the fixed batch eligible within that retry budget.
An L0 revision conflict also keeps the fixed batch eligible: the service reads
the newer frame and re-analyzes rather than applying a delta against stale
state. Durable and runtime forgetting barriers are checked before analysis,
after analysis, immediately before the L0 write, and before each personality or
observation write. If only part of a batch was forgotten, the surviving fixed
turns are re-analyzed without the removed evidence. The shared analysis
destinations are not one transaction, however. Personality and
durable-observation application failures are logged as best-effort failures and
do not keep the batch queued, so one destination may update while another does
not. An unexpected exception after an earlier write may instead make the
scheduler retry the batch within the same budget. This path is therefore
neither atomic, exactly-once execution, nor durable at-least-once processing.

Each queued turn therefore carries the durable accepted response's own commit
time, not the later time at which its detached enqueue task happened to run.
Every activated durable forget request advances the runtime memory epoch and
establishes a conservative post-turn boundary. Prepared chat intents do not
take effect until their runtime deletion barrier is activated. Exact raw chat
turns discovered by deletion pages receive a shared per-turn cutoff. A late
write is governed by the source turn's accepted time rather than by the later
time at which analysis happened, including when L0 is disabled and only
personality processing is active. Permanent event and session barriers remain
separate from temporal turn cutoffs. A genuinely new accepted outcome after a
temporal cutoff may form new attention unless its durable source identity was
permanently forgotten.

Removing or replacing one chat-agent instance does not stop the shared queue.
Only runtime shutdown first waits for detached enqueue tasks and then asks the
runtime-scoped scheduler to flush pending batches for up to five seconds. Work
still failing or waiting when that budget expires is cancelled. A forced
process termination loses pending batches and any changed L0 frame that has
not reached its SQLite checkpoint. Startup restores valid checkpointed
attention only; it does not scan the durable transcript to reconstruct a
missed L0 analysis backlog. Ordinary prompt assembly still receives durable
chat history, so missing or delayed L0 analysis does not remove the
conversation itself.

Active items that pass the confidence and salience thresholds are injected
directly as a small, explicitly labelled short-term-context block. Background or
low-salience items are not injected on every turn. Prompt assembly includes a
trustworthy background item only when its compact summary, linked entity, or
linked task shares normalized terms with the current message. It remains
labelled as reference-only background and is explicitly not a new instruction;
selection does not change its stored status back to `active`. Otherwise it
stays out of the prompt. L0 may help resolve references and shape an
explicit long-term-memory query, but L0 itself does not enter the L1-L4
retrieval index.

All L0 state is optional and disposable. Expiry or eviction changes only what
short-term guidance may be supplied to a later prompt; it never cancels,
retries, resumes, or recovers chat work. Live runs, pending interruptions,
cancellation controls, tool results, and execution checkpoints remain owned by
the chat/runtime domains. Chat owns the full transcript and rolling
conversation summaries. `L1` and `L2` own durable evidence and current durable
facts, while personality owns relationship depth and Magi's dynamic persona
state.

The attention-update schedule and the checkpoint schedule are distinct.
Attention-update settings decide when accepted turns are understood; the
checkpoint interval decides how quickly an already changed L0 projection is
persisted. A dirty-state checkpoint remains debounced, mutations that arrive
while a checkpoint is running schedule a later pass, and normal shutdown
flushes changed live sessions. Restart restore keeps only valid, still-relevant
bounded items and discards malformed rows individually.

Expiry is based on the attention item's meaning, not the chat transcript's
retention. The current defaults are six hours for `situation`, 24 hours for
`focus`, `active_object`, `constraint`, and `consensus`, and 72 hours for
`open_loop`. Reinforcement refreshes the kind-specific deadline. Resolved and
superseded items are retained for one hour for inspection but are not injected
into prompts. Expiry is enforced when attention is read or restored; periodic
maintenance removes an idle L0 session only after its remaining attention has
also expired. A row may therefore remain physically present until a read,
checkpoint, or maintenance pass, even though it is already logically
ineligible for prompt use.

L0 may compose chat-owned information in its expert workbench view without
becoming its owner. In particular, context-window usage belongs to the accepted
chat outcome in `chat.db`: it must survive L0 expiry, restore after restart, and
follow visible-answer deletion semantics. Prompts and the chat meter read the
durable chat record.

Attention items that depend on source turns or events retain those references.
When a source is forgotten, affected items are removed or recomputed in live
state and checkpoints. Prompt reads and restart restore recheck source
tombstones, per-turn cutoffs, entity projection blocks, and governed time
ranges so incomplete cleanup cannot re-expose an item. Task attempt and
completion updates change lifecycle state without replacing the original
evidence time. This prevents a later task notification from making old evidence
look newer than its deletion cutoff. Shared per-turn cutoffs survive an
ordinary L0 clear and are removed only by full-memory clear. Full-memory clear
removes dormant rows and vector content from every persisted memory layer even
when that optional layer is disabled in the current runtime.
Normal expiry and checkpoint maintenance never weaken these barriers.

### L1 — Normalized Event Facts

`L1` is the durable fact layer and the factual foundation of the entire memory system.

It stores normalized events that are stable enough to participate in downstream processes:

- Recall
- Search
- Cognition
- Reflection
- Audit and debugging of memory projection pipelines

If a fact will later affect the system's understanding, review, or reasoning, it typically enters `L1` first.

Key properties:

- Durable fact events
- Unified source-normalized contract
- Explicit domain / retention / cognition policies
- Supports vector retrieval and keyword retrieval
- Preserves source-side identity and business idempotency
- Maintains rebuildable source-facet indexes for exact structured recall over
  source-owned fields such as photo locations/counts, browser domains/visit
  counts, and music tracks/artists/play counts
- Vector index uses `event` as the parent object and `chunk` as the retrieval unit: long texts are split into overlapping chunks for vector indexing, then collapsed back to the parent event during retrieval
- `L1` / `L3` / `L4` hybrid retrieval passes through a unified reranker stage after RRF; heuristic reranking is always active
- An optional local cross-encoder reranker can add semantic relevance scoring on top of the heuristic stage
- The cross-encoder reranker is driven by `agent.memory.reranker.cross_encoder` and loads a managed ONNX model by `managed_model_id`; if it is disabled or the model files are unavailable, retrieval falls back to heuristic reranking without interruption

Examples:

- User-authored content
- Chat projection memory facts
- Chrome history bursts
- Hourly app usage summaries

Counter-examples:

- Complete chat transcript truth
- Heartbeat noise
- Step-by-step execution traces
- Exact tool arguments, latencies, and raw tool outputs from a specific turn

#### User-authored Manual Entries

The `manual_entries` row is the product's editable source record; its immutable
L1 projection is the canonical input to recall, timeline assembly, episodes,
experiences, mood aggregation, and later summaries. Editing projected content
does not rewrite the previous L1 event. The mutation path uses the same governed
write boundary as durable forgetting: it checks the replacement occurrence,
atomically stores the complete replacement source snapshot and deterministic
reservation, and writes the replacement L1 event before releasing that
boundary. The pending source stays hidden while the old projection is cleaned
and the new link is completed. A failed or ambiguously committed step therefore
leaves a discoverable recovery identity rather than an unowned L1 event.
Mutations for one entry are serialized, and retries resolve the same replacement
identity instead of producing duplicate source rows.

Creation preserves the user's source row even if its initial L1 projection
temporarily fails. The API returns the saved entry with `memory_status=pending`;
the product closes the editor and tells the user that related memory will finish
later. A later repair completes the same deterministic projection. Startup
recovery pages lightweight identities and checks linked L1 states in batches,
then periodically revisits only durable unfinished rows and exact identities
whose prior batch check failed.

Deletion first closes source mutation and projection completion with a durable
request marker, then governs the linked, reserved, and deterministically
reconstructable event identities across every memory layer. External event or
time-range forgetting uses the same source-owner boundary: selecting the
entry's current occurrence gates and finalizes the source in that forget
operation, while selecting an obsolete projection version removes only that
old event and does not delete the current entry. A time-range rejection before
an edit reservation preserves the old entry so the user can change the time and
retry; a source-identity rejection, or forgetting that wins after the
replacement write, terminalizes the old entry and requires a new identity.
If an initial projection has not reached L1 yet, the durable time-range barrier
still removes the covered source from manual-entry lists and attachment access
as soon as forgetting returns; recovery then completes source deletion without
re-exposing it.
Public list, timeline, and attachment reads exclude pending-deletion and deleted
entries.

Uploaded manual-entry assets are content-addressed but not public by possession
of the reference. The timeline asset route serves an asset only while it is
referenced by an active manual entry, a non-invalidated experience, an experience
draft, or a saved timeline cover. Removing the final user-visible owner makes a
previously known asset reference unreadable without requiring immediate file
garbage collection. Product copy must therefore describe deletion as removing
access to the attachment, not as immediate physical file erasure, unless
owner-aware garbage collection has confirmed that the stored bytes were removed.
An `asset_ref` is a durable resource identity, not an access credential. Desktop
rendering additionally requires a short-lived gateway ticket, but ticket
issuance never bypasses the active-owner and deletion checks described above.
Tickets are not stored in memory records, timeline projections, experience
drafts, chat payloads, or plugin state.

#### Evidence Interpretation and Retrieval Authority

`L1` raw events and retrieval authority are separate concerns. The raw event row records what happened; evidence interpretation records how that event is allowed to participate in fact recall, episode recall, audit views, and downstream cognition.

Evidence interpretation is shared memory governance, not an `L2`-only helper:

- Classification answers what the evidence is: user assertion, user question, user request, assistant freeform answer, assistant quote, tool result, external observation, runtime signal, or other explicit class.
- Policy answers what the evidence can do: enter fact-like retrieval, remain episode/audit-only, write L2 graph/assertions, affect snapshots, count as new evidence, or require a source backlink.
- The baseline durable annotation is event-level. Span-level retrieval atoms are optional derived projections for mixed or long events once they are justified by measured retrieval pollution, not the default raw-memory shape.
- If span-level atoms are introduced, they must hydrate back to the parent `fact_events` row and be protected by immutable source text or content-hash validation.

Fact-like retrieval must constrain the searchable evidence pool before ranking and topK selection. It must not depend on broad L1 recall followed by answer-projection filtering as the primary defense. Assistant memory answers, user recall questions, runtime artifacts, and ungrounded assistant text can remain retrievable in conversation, episode, audit, or debug contexts, but they are not authoritative evidence for new user facts.

Raw `fact_events` content is not rewritten to fix retrieval behavior. Classifier, policy, embedding profile, and index changes mark derived evidence/index records stale and trigger rebuilds; they do not mutate the original L1 fact.

Source-facet indexes are `L1` retrieval infrastructure, not `L2` cognition.
They preserve source-owned exact fields needed for coverage-sensitive queries
where top-K text/vector recall is insufficient, for example "how many photos at
this place", "how many visits to this domain", or "how many plays by this
artist". Plugins may provide these fields through `domain_payload.source_facets`;
`L1` may also rebuild facets from older persisted metadata when the source facts
are still present. A structured recall result may claim total coverage only
inside the explicit source/facet/time/user scope used to query that index.

#### Canonical Source Deletion

Deleting an L1 source event is a cross-layer governance operation, not a direct
soft-delete of one row. The unified workflow separates permanent replay
barriers from broader derivative-cleanup references. Permanent barriers include
the canonical event identity, an optional source-owned item identity, and the
source + event-type + idempotency identity. A linked chat turn may still be used
to clean older coarse-grained derivatives, but it is not permanently blocked by
a single-event or single-message deletion. Turn and session identities become
permanent barriers only when the user deletes that whole turn or session.
Internal source replacement, such as editing a manual entry, blocks the old
event and idempotency identity without blocking the reusable source item. A
paged bulk deletion completes the permanent barrier phase for the selected set
before it starts removing individual rows. This prevents a concurrent
projection, source replay, or later resynchronization from recreating memory
while cleanup is in progress without poisoning an unrelated replacement.

Chat deletion enters this workflow through the Python runtime even in the
desktop build. A session delete first proves that the active session belongs to
the requesting user; an unknown session or wrong owner creates no barrier. A
single-message delete selects L1 rows by both session and message identity,
leaves sibling L1 messages from the same turn visible, and permanently blocks
that source-owned message from being projected again. Turn-linked derivatives
that cannot be attributed more precisely are removed conservatively, without
turn-wide replay blocking. The L1 session preview is rebuilt from surviving
events after a message delete and scrubbed when the whole session is deleted.
After memory cleanup succeeds, single-message deletion first commits an
inaccessible redacted row, removes its public attachment metadata, invalidates
session boundary summaries, clears the complete session Model Context Log and
Surface, clears reply previews that point to it, and rebuilds the visible
session preview. Clearing the complete model context is conservative and
necessary because surviving tool results or summaries may still derive from the
deleted message; the visible transcript is never used to reconstruct a partial
prompt history. A user message also owns the execution boundary for
its turn, so deleting that message removes its delivery copy and linked turn
trace. Deleting a completed assistant message preserves the originating user
turn's trace and delivery row; if its reply is still unfinished, the runtime
closes that delivery so the deleted assistant response cannot be regenerated. A
managed attachment or derived file is deleted only when no other visible
message in an active session still owns that same asset. The redacted message
and its private asset-retry references are physically removed only after the
required trace and file cleanup succeeds. Transcript-snapshot and whole-session
deletion use the same two-phase ordering; a deleted session keeps only its
scrubbed session tombstone after its messages and turns are finalized. These
chat changes start only after memory cleanup succeeds, so a failed memory
request remains visible and retryable. If later physical cleanup fails, the
content is already inaccessible and durable recovery can safely finish it.

Private code-delegation evidence follows the same ownership rule. The tool
registers the exact session, turn, delegation, and workspace before it creates
local artifacts; a committed assistant message then adds its visible ownership
reference. Deleting a message, transcript, session, or all conversations removes
an unshared delegation's logs, diffs, temporary worktree, and private branch.
If another visible message in an active session still references the same
delegation, those artifacts remain available. Edits already applied to the
user's main workspace are not chat-owned evidence and are never reverted.
Cleanup failure leaves the redacted transcript inaccessible and retains only
the private registry required to retry safely.

Committed assistant replies reach L1 through a durable chat-owned projection
queue rather than a best-effort call in response post-processing. Deleting a
message, session, or chat history first activates the durable forget intent;
only then may the matching pending or claimed projection row be cancelled.
This ordering matters for an already claimed worker: the permanent source
barrier rejects any late `AIResponse` ingestion, while lease ownership prevents
that worker from completing or re-creating cancelled work. Startup recovery
uses the same ordering, so a crash cannot make a deleted assistant answer
return to memory.

Each layer owns removal of its own derivatives:

- L2 removes the forgotten occurrence from assertion and relationship evidence,
  entity mentions and facets, episode and experience membership, experience
  seeds and drafts, mood aggregates, correction effects, and derived profile or
  insight dependencies. Claims with independent evidence are recomputed; claims
  with no trustworthy evidence are archived. Entities with remaining evidence
  are rebuilt, while source-only aliases, catalog entries, search rows, and
  vectors are removed. Daily mood projections persist every contributing event
  identity and recheck source deletion or governed time-range barriers in the
  same write transaction; legacy mood rows without attributable sources are
  discarded during schema upgrade.
- L3 removes the source link and search/vector material. A summary with remaining
  evidence becomes stale for regeneration; one with no trustworthy evidence is
  retired.
- L0 removes or recomputes attention items linked by a deleted turn, event, or
  governed time range, then rechecks the same governance on new writes, prompt
  reads, and restart restore.
  Deleting one user chat message removes its execution-owned state without
  clearing unrelated working state. A newer run continues only when the target
  is still unconsumed; if its context may contain the deleted message, that run
  is cancelled and terminalized. Admitted turns that have not established a
  run are recorded in the first durable delete intent, stopped before deletion,
  and replayed only after the remaining context is rebuilt.
  Deleting a completed assistant message preserves the originating user turn's
  execution root, although an unfinished run may still be cancelled by the
  runtime privacy boundary. Deleting a session or all chat history still clears
  the complete L0 session.
- L4 retires a procedural skill when the deleted source contributed to its
  learned aggregate, removes its searchable/vector and L4 trace material, and
  refuses future learning from a deleted or time-range-governed event.
- L1 hides the complete selected source set as soon as the durable replay
  barriers are committed, before slower downstream cleanup begins. This keeps
  a partially completed deletion out of recall while recovery is still running.

When a time-range action retains L1, the raw occurrence remains available for
timeline and audit use, but every event selected for the range is still passed
through the same L0/L2/L3/L4 derivative cleanup. The durable range barrier is
stored independently from the events known when deletion runs. A source that is
connected or backfilled later is checked against the canonical occurrence time
before its first L1 write. Matching events are rejected entirely when the action
also deletes L1; otherwise an event-specific derivative barrier is committed
before the retained raw L1 row is written. L0, L2, L3, L4, and episode writes
recheck either that event barrier or their own canonical observation time, so
late sync and direct derivative writes cannot recreate the forgotten period.
An ordinary episode-removal barrier remains scoped to episode formation and
does not globally suppress the event's unrelated derivatives.

The operation and its cleanup progress are durable and deliberately retryable.
A failed attempt leaves the source hidden and the replay barriers in place, but
does not report a successful user deletion; repeating the same request or
startup recovery resumes the remaining cleanup without reviving or duplicating
state. A competing worker must hold the current operation lease before it can
advance progress, so an expired worker cannot later mark a newer recovery run as
complete.

Correction audit projections derived from the forgotten evidence are governed
by the same deletion. Default user-facing episode and experience lists do not
offer invalidated records, and stale or rejected experience seeds cannot be
promoted into new memories.

Older databases may not retain complete provenance for names and procedural
skills created before source governance existed. Upgrade is intentionally
fail-closed: unattributable legacy names are not treated as independently
user-authored, and pre-governance procedural skills whose recorded attempt count
exceeds their recoverable source links are retired and rebuilt from newly
observed, fully linked evidence. This may discard rebuildable legacy learning,
but it prevents an old untracked source from surviving a later user deletion.

#### Chat Recall Correction Boundary

Feedback on a memory-grounded chat answer is a chat-turn correction before it
is a memory mutation. The visible user message stays natural language, while a
structured turn payload identifies the assistant message being rechecked and,
for item-level feedback, the stable finding reference being excluded. Runtime
routing must use that structured relation and must never infer correction intent
by parsing localized UI copy.

The correction turn reuses the exact compact evidence snapshot that was shown
with the targeted answer. `answer_evidence_mismatch` re-evaluates the conclusion
from that snapshot. `item_irrelevant` removes the selected finding from that
snapshot before prompt assembly. The correction path does not run implicit
memory retrieval from the correction wording, does not reconstruct a removed
finding, and must state when the remaining evidence is insufficient. The new
assistant message links back to the answer it corrects; the previous answer
remains in the transcript for conversational continuity and auditability.

This feedback is local to the question and answer pair. It does not change
global retrieval scores, L1 evidence authority, L2 assertion confidence, graph
state, or portrait material. The visible correction message is retained as
conversation-only interaction history and is never eligible for cognitive
projection. A claim that the stored record itself is wrong is a different
operation and must use the governed L2 assertion or relation feedback path with
explicit user confirmation.

Prompt continuity note:

- The chat runtime may carry a compact `Recent Tool State` summary across nearby turns so the LLM can reuse recent tool outcomes or handles without replaying full tool transcripts.
- This summary is not itself an `L1` fact, `L2` cognition artifact, or durable memory record.
- If the user asks for exact execution details, the system should read `runtime_trace.db` through trace read APIs or the builtin `trace_query` tool instead of searching memory layers.

### L2 — Structured Cognition

`L2` stores structured understanding derived from `L1` events. It is organized into three product subdomains:

- **Semantic memory** — Durable entities, relations, preferences, long-term structure
- **State memory** — Latest truth, current status, versioned facts with supersession
- **Episodic memory** — Bounded historical experiences derived from L1 events

Together, these subdomains let Magi answer "who am I / what am I doing / what happened" with evidence, and feed the timeline, profile, and proactive features from one consistent memory substrate.

L2 holds:

- Entity mentions and canonical entities
- Knowledge graph edges (with `fact_kind`, temporal validity, privacy scope)
- Entity facets (sidecar structured attributes)
- Grounded Claim ledger with normalized evidence links, host-owned temporal fields, and exhaustive semantic-route and projection outcomes
- Governed pending-memory reviews for Claim groups that are meaningful but cannot yet be materialized safely
- ToM trait assertions (versioned, with lifecycle states and supersession)
- ToM snapshots (periodically refreshed entity portraits)
- Episodes (bounded activity and theme segments formed from L1 events)
- Experiences (product-grade, evidence-backed narrative memories promoted from episodes and events)
- Durable projection job queue

Sensor-derived relation candidates reach the L2 knowledge graph through the awareness-owned knowledge graph write queue. That queue is the backpressure boundary for bursty sensor catch-up runs: it batches edge writes before calling the unified memory facade, while the memory layer remains the owner of graph schema, conflict resolution, evidence merging, and embedding status updates.

Implementation boundary: `L2CognitionStore` remains the public storage facade
and transaction coordinator in `memory/l2/store.py`, while its mixins are grouped
by L2 domain rather than by generic helper status: `storage/`, `graph/`,
`assertions/`, `entities/`, `episodes/`, `projection/`, `extraction/`,
`retrieval/`, and `governance/`. Entity-domain code lives under
`memory/l2/entities/`: `catalog/` owns canonical entities and aliases,
`maintenance/` owns offline cleanup, `models.py` owns entity contracts, and
`facets.py` owns sidecar entity attributes.

For user-authored chat, durable self-descriptive profile facts such as identity,
birthday, preferred language, and addressing preferences should land in L2
semantic/state assertions, not in bootstrap-only state. Explicit identity facts
use `identity_profile` assertions such as `identity.real_name`,
`identity.birth_date`, `identity.birth_year`, and `identity.age.stated`.
Communication preferences use `communication_profile` assertions such as
`communication.address.preferred`, `communication.address.disallowed`, and
`communication.response_style.preferred`.
Phase 1 extraction may use profile-signal predicates such as `REAL_NAME`,
`BIRTH_DATE`, `BIRTH_YEAR`, `STATED_AGE`, `PREFERRED_FORM_OF_ADDRESS`,
`DISALLOWED_FORM_OF_ADDRESS`, and
`PREFERRED_COMMUNICATION_STYLE` to keep those facts explicit for deterministic
host routing and Assertion materialization, but
these predicates are not graph relations and must never be persisted as knowledge
graph edges.
Profile-signal claims must be grounded in current user-authored text before they
can produce profile assertions; assistant persona text, recalled history, and
one-off task phrasing are not sufficient evidence for durable identity or
communication-profile fields.
Phase 1 `temporal_cue` records only explicit time wording in the supporting
quote; it does not decide retention by itself. A missing, unknown, or
unsupported cue is normalized to an unambiguous cue detected in the evidence
quote, or to `unspecified` when no cue is present, before contract validation.
The grounded predicate, assertion family, source strength, and any explicit
one-off or recent wording determine the host-owned retention horizon. Therefore
an explicit profile instruction such as a preferred form of address can remain
durable until corrected even when its source sentence has no lexical time cue.
Same-session dialogue context is a bounded interpretation frame, not free-form
evidence. The frame contains at most the three closest messages that precede
the current event by session sequence; future messages are excluded. Direct
claims remain fully grounded in the current quote. A short reply may use
`clarification` only when it cites the nearest user statement and intervening
assistant question, or `confirmation` only when the current user gives an
unambiguous confirmation of the immediately preceding assistant proposition.
Weak acknowledgements and older context cannot authorize a claim. Contextual
claims keep the current user quote as their evidence, carry antecedent event IDs
separately, and receive a lower confidence cap.
Post-turn observers may submit explicit profile candidates from chat, but they
must not write portrait projections directly. The host validates that the
candidate is grounded in the user's own text, persists it as an L2 assertion
candidate, and lets normal assertion state, conflict handling, review, and
portrait projection decide how it appears to the user.

Post-turn observers may also submit explicit task-handling preferences when the
user states how future work should be handled. These preferences belong to L4
procedural memory, not persona behavior evolution or L2 profile facts, because
they describe reusable execution guidance rather than identity traits.

L2 keeps a semi-open graph predicate model so source-specific relationships can
be captured before the core ontology knows every useful verb. That openness is
bounded by a quality gate: custom predicates must describe stable, reusable
facts, while dialogue/query activity such as asking about, mentioning, looking
at, or wanting help with an object belongs in short-lived interaction context,
not the durable knowledge graph. Entity extraction follows the same boundary:
pronouns and vague placeholders such as “那个”, “他”, generic “app”, or generic
“PDF” may help resolve references, but should not become canonical L2 entities
unless they resolve to a concrete named entity or asset.

Preference Claims follow the same stability boundary. An explicit `LIKES` or
`DISLIKES` Claim marked `one_off` may still authorize an Assertion for cautious
profile interpretation, but it cannot authorize a durable knowledge-graph edge.
The semantic route contract owns this distinction and Phase 1 graph projection
reuses that contract-level policy. Route-contract reprojection removes only the
obsolete relationship authority from older Claims; it preserves the Assertion,
shared Claim support, and independent user-correction authority.

Phase 1 must choose the most specific evidence-supported type from the canonical
entity registry. Named collectives belong to `group`, named creative works belong
to `media`, and abstract qualities or styles belong to `concept`. `other` is a
last-resort classification for a concrete entity that does not fit any available
type; unfamiliarity alone is not a reason to use it. The host still validates the
type against the registry, but it does not guess a replacement type from an entity
name when the evidence cannot support that semantic decision.

New named entity IDs use a stable fingerprint of the complete Unicode-normalized
name and entity type. Display slugs never determine identity. Replay keeps the
same identity; changing a catalog name requires explicit rename authority and
must preserve that identity. Ingestion cannot overwrite an existing identity
with an unrelated name.

Knowledge graph endpoints must resolve through the entity catalog before they are
persisted. The LLM is not an authority for inventing `entity_id` values. Every
semantic route declares its projection targets explicitly: graph, assertion, or
both. A graph projection is eligible only after its endpoints resolve to catalog
IDs produced by Phase 1 entity resolution or source-owned structured hints that
have first been registered in the catalog. An assertion route may remain eligible
when its meaning is grounded but the graph endpoint is unresolved. In particular,
an explicit `one_off` `LIKES` or `DISLIKES` Claim remains event/Claim evidence and
does not create a reusable preference relationship. All other preference and
interest routes derive a stable semantic target from either the
catalog entity ID or the complete normalized evidence text; display truncation is
never used as identity. Phase 2 does not emit graph edges. Graph storage and
internal retrieval continue to use stable catalog IDs, while product-facing
relationship read models must batch-hydrate endpoint names from the entity
catalog. A client may cache catalog entities for reuse, but it must not infer a
user-visible name from an ID prefix such as `concept:` or `other:`; an unresolved
opaque endpoint is presented as unknown instead.
Evidence-derived entity text and model-generated summaries have
different language contracts. The configured user language guides Phase 2
natural-language summaries, but it is interpretation context only in Phase 1 and
never authorizes translation of imported evidence. Phase 1 protocol keys and enum
values remain English, while entity surfaces, normalized names, evidence-derived
object references, evidence quotes, and raw time expressions retain the current
evidence language. Phase 1 protocol prose and JSON schemas are instructions, not
candidate evidence. Prompt guidance should express extraction rules structurally
instead of embedding reusable, user-like entity values, and the host must reject
any emitted entity or Claim value that is not grounded in eligible current
evidence.
Before typed validation or persistence, the host detects the current evidence
scripts, requires every entity surface to occur in eligible current evidence,
restores a normalized name to that surface when it drops any source letter script,
and rewrites the matching claim reference when the mapping is unambiguous. The
same rule applies to activities, concepts, topics, and other abstract entities,
not only proper nouns. Same-script spelling, spacing, and punctuation
normalization remains allowed. Non-Latin entity names therefore keep their
original script in catalog names; ASCII slugs are storage identifiers only and
must not replace the source-language name in user-facing evidence.

Phase 1 alias signals are provenance-bearing names, not a place for speculative
translations. An alias may be persisted only when that exact alternate name also
occurs in eligible current evidence; existing catalog aliases may participate in
matching without being copied into new event provenance. A normalized alias that
equals the entity's normalized canonical name is not an alias and must not be
stored as a duplicate catalog row. Exact entity resolution searches canonical
names and aliases as separate first-class namespaces, so canonical lookup must
not depend on that duplicate row. Imported Markdown uses
the same host-owned authorship classifier as claim grounding, so text found only
inside blockquotes, code, or pasted dialogue cannot create an entity or alias.
Governance surfaces present aliases as entity metadata in record details, never
as the record summary or as source-evidence references.

The extraction runtime keeps Phase 1 admission, batch preparation, entity
resolution, evidence grounding, host semantic routing, and deterministic graph
and Assertion projection separate from optional Phase 2 wording. Phase 2 may
return only concise natural-language summaries bound to exact current Claim IDs;
it cannot propose records, families, routes, conflicts, lifecycle fields, or
persistence actions. Shared handoff data lives in a small extraction contract
module so wording can evolve without importing or acquiring authority over host
materialization details.

The grounded Claim is the durable handoff between extraction and downstream
projections. Phase 1 may emit only a `raw_time_expression` copied verbatim from
the current evidence quote, or an empty value; it never calculates or rewrites
dates. The host classifies every supporting event through a closed source-time
policy before Claim persistence. `timestamp_quality` has exactly five meanings:
`exact`, `calendar_anchor`, `approximate_recorded`, `derived_order`, and `low`.
Only `exact` and `calendar_anchor` may prove currentness or anchor relative
expressions. File modification, sync, capture, and import timestamps are
`approximate_recorded`; file or message order without a timestamp is
`derived_order`. Neither can activate a current Goal, calculate recency, or
anchor decay. Unknown sensors are `low` even if arbitrary plugin metadata claims
to be exact. Live chat/channel message timestamps, declared calendar sources,
manual-entry event times, and host-owned history-import provenance are the only
initial trusted policies. Claim evidence stores both the normalized quality and
the accepted `timestamp_anchor_source` for audit.

New L1 writes attach the validated IANA calendar timezone captured at ingestion
when the host can resolve one. History imports capture that timezone before
parsing source-local timestamps and persist it with the source record, so a
later worker or process-timezone change cannot reinterpret the imported wall
clock. Phase 1 renders each event time in its captured timezone with an explicit
UTC offset instead of formatting every event in UTC or in the worker's current
timezone. Calendar-sensitive Claim resolution requires that persisted timezone
and resolves relative expressions only against trusted supporting-event
timestamps. An ordered host rule table handles absolute dates,
relative days, weeks and months, named weekdays, year-bound seasons, half-year
periods, and bounded `N`-unit offsets. A season without a year, such as `秋天`,
remains `unresolved_text`; the host never silently chooses the next season.
Winter ranges cross the civil year boundary. Missing timezone provenance,
conflicting resolved ranges, or a non-positive civil interval fail closed. A
supporting timestamp beyond the bounded future clock-skew window is invalid as a
relative-time anchor even when its quality is trusted; an absolute grounded
calendar expression does not depend on that event-time anchor. Equivalent IANA
aliases may converge only when they produce the same actual calendar range.
Non-intent Claims populate fact-validity fields, while `future_intent` Claims
populate a separate target window. Ambiguous or low-quality relative anchors
preserve the raw expression without inventing a numeric range.

The immutable Claim identity includes the grounded raw expression, temporal
kind, and resolution class, but excludes the host-derived epoch projection and
the complete audit payload. The first durable Claim projection remains
authoritative during replay, so changing the process timezone cannot mutate the
Claim or its downstream target. The persisted frame retains both the numeric
range and an auditable civil descriptor (`timezone_id`, precision, civil start,
exclusive civil end, operator, and anchor event IDs). Knowledge-graph
`valid_from` / `valid_to` use fact validity only; target windows are assertion
routing inputs and must never be written as graph fact validity. A `recent` Claim
without trustworthy time provenance is review-only, while `stable` or
`unspecified` Claims are not rejected merely because their evidence lacks an
exact timestamp.

A concrete `PLANS_TO` Claim with `fact_kind = future_intent` is routed to
`goal_profile` / `goal.intent`, never to the knowledge graph. Its object is the
complete grounded action text, not an entity endpoint. Nested people, projects,
places, and concepts may still be extracted as entities for other claims, but
the goal itself must not be converted into a synthetic `concept` or `other`
node merely to satisfy graph shape.

Only direct user evidence may become a current goal assertion. The host derives
its literal user-facing value from the complete Claim object text rather than
model synthesis or an internal entity ID. Goal slot identity is based on the
subject and normalized goal meaning; its target window is mutable state, not
identity. The assertion stores an opaque `semantic_lineage_key` for deterministic
renewal and a separate `target_window` envelope containing the resolved bounds,
raw expression, resolution, and calendar provenance. Rephrasing or rescheduling
the same goal can therefore update one lineage without creating a new identity
for every date expression. A trusted current goal is bounded recent context whose
expiry follows the resolved target end, or a host-owned fallback when no schedule
was stated; ambiguous or low-confidence timing produces a review outcome, and an
elapsed target produces an expired outcome without creating a current assertion.

Pending review is durable pre-materialization truth, not a tentative Assertion
status and not a model-authored decision. One active review is keyed by subject,
review kind, semantic slot, and value fingerprint; its exact decision identity
also includes the supporting Claim set, host proposal, route contract, evidence
rule, and memory clear generation. Creating or merging the review and appending
its Claim receipts is one fenced transaction, so a projection retry cannot leave
an orphan work item or complete the Claim without its review provenance. An
identical retry is a timestamp no-op.

Review resolution is an optimistically versioned command. The host reloads the
active Claim receipts and current policy versions while holding an immediate
write transaction. Rejecting closes only the review. Confirming, or confirming
with an edit to the literal value or user-facing summary, writes the authoritative
user-feedback Assertion, invalidates pending receipts, appends the resolution and
Assertion receipts, and records the audit identity atomically. Clients cannot
choose the actor or semantic routing fields. A stale version, cleared generation,
changed Claim set, or changed policy returns a conflict instead of applying an
old decision. Pending reviews never enter portrait or chat prompt facts; they are
exposed only as a governance task until resolved.

Semantic-route maintenance is host-owned. Maintenance callers provide only a
Claim identity and a bounded pass size; the host derives the current route
contract, resolution-aware attempt identity, and route decision from durable
Claim state. The highest non-invalidated contract version is the current route,
even if an older outcome has a later wall-clock timestamp after clock rollback.
Reprojection appends the current route and reconciles that Claim's assertion,
relationship, and pending-review receipts in one immediate transaction. Semantically unchanged
targets receive a current-contract receipt, while changed targets lose only the
retired Claim provenance. Reconciliation coalesces duplicate active receipts per
canonical target, preserves an already-current receipt, and maps an
`entity_merged` receipt to the rekeyed target identity before revalidation. A
target is archived only when no other active Claim still authorizes it and it
has no independent correction or non-Claim authority; otherwise its Claim-backed
evidence is recomputed from the remaining valid ledger support. A pending review
similarly updates its exact Claim/evidence set while shared support remains and
closes when its final authority disappears or the route no longer authorizes an
Assertion target. Outcome
invalidation and replacement receipts retain the audit trail, while archived
targets disappear immediately at governed assertion, relationship, and portrait
read boundaries. Portrait tentative-Claim deduplication is scoped to the route
slot and value recorded by an assertion's source attempt, never to the Claim ID
alone, so a later route/value can become visible without reviving the old value.
Only assertions already visible in portrait `world` or `recent` suppress the same
tentative Claim line. A current Assertion that remains in portrait `review` keeps
its grounded self-report Claim eligible for the explicitly uncertain prompt path;
all current assertion values still participate in slot-conflict quarantine.
Portrait freshness recomputes the current eligible top-two tentative selection
with the same deterministic renderer used by the builder, even when the cached
portrait contains no tentative line. It compares both rendered lines and explicit
selected Claim/event provenance, so a same-text fallback cannot retain evidence
for an expired Claim. Validity-window transitions, conflict resolution, prompt
limits, and protected Goal lines therefore cannot leave a stale hidden or newly
visible self-report indefinitely cached.
The persisted portrait also records exact highwaters for portrait-eligible
Assertions, portrait-eligible Claim and tombstone changes, governed review
mutations, and the profile projection it consumed. Source revision and memory
clear generation remain independent fences. Freshness reads must distinguish a
successful empty result from an unavailable or failed dependency: a failed read
is never converted to an empty collection or a fresh verdict. Pending reviews
invalidate the portrait read model for governance consistency, but their proposed
content is not injected as a current user fact.
Host conflict discovery is exhaustive over the current slot and does not depend
on Phase 2 input or output. The host alone defines the comparison set and
authorizes conflict side effects. `HAS_METRIC` remains explicitly unrouted with
`typed_metric_contract_required` until the host can derive metric name, value,
unit, and value identity without free-form model output.

`user_profile_projection` in `memory.db` is the product-facing read model for the
local user profile. It is rebuilt from current L2 profile assertions, records
field sources/conflicts, and derives deterministic fields such as `birth_year`
and `age_years` from `identity.birth_date`. Settings writes are user-authored
evidence: they create an L1 audit event, write confirmed L2 profile assertions,
and then refresh the profile projection and self-portrait projection together.
Product code and prompt assembly should read the projection first and fall back
to raw L2 assertions only when the projection does not yet exist.
The profile row persists the newest consumed Assertion timestamp and the exact
Assertion IDs used by selected fields and conflicts. Reads compare those inputs,
the subject revision, and the memory clear generation before reusing the row;
ordinary Assertion writes therefore do not depend on a correction revision bump
to invalidate the profile. Assertion-driven refresh always rebuilds Profile
before Portrait so the portrait cannot consume a known-stale profile row.

`user_portrait_projection` is the product-facing self-portrait read model for
the local user. It is not an authority over L2 facts. It packages L2 assertions,
explicit profile fields, and governed Assertion review state into a stable `world/review/recent`
page model plus a short `prompt_summary` for main-chat context injection. Raw
graph edges and ToM snapshots do not enter this projection directly because they
lack the assertion-level retention decision. Prompt assembly must use that
human-readable summary when available and must not dump
raw preference dictionaries, internal assertion keys, source tiers, or affinity
metadata into the main model prompt. Clearing L2 cognition artifacts must also
clear profile and portrait projections so local re-imports do not keep stale
user-understanding caches.
Assertion-backed portrait items display the accepted `natural_summary` when one
exists and retain the typed `trait_value` as the correction payload; this prevents
distinct preferences that share an enum-like value such as `like` from collapsing
into one review item. This display rule does not make review Assertions prompt
facts: only their independently grounded Claim may use the tentative path above.
Portrait wording and prompt selection are deterministic host logic. There is no
optional portrait LLM post-processor in the runtime path. A transient freshness,
input, or rebuild failure retains the last successfully persisted projection and
marks the product response stale; when no successful row exists, the product
returns unavailable/omits prompt context and does not persist an empty projection.
Only a successful dependency read whose real result is empty may materialize an
empty profile or portrait. Projection failures are logged with projection kind,
stage, cache-retention decision, user ID, and error type without evidence text.

Portrait projection is a qualification layer above raw assertions. Assertion
promotion owns evidence thresholds and retention; portrait projection consumes
that decision instead of reimplementing source-specific thresholds. Assertions
with `stable` or `persistent` temporal scope may enter `world` when their family
and trait semantics match. Assertions with short-lived or `recent` temporal
scope enter `recent`, while unresolved durable candidates enter `review`. Tool,
device, app, browser, and place names are inventory signals by default: they can
support a higher-level project,
preference, or collaboration-style assertion, but they must not enter the
portrait world as raw profile items. Assertions that fail this gate can remain
L2 facts, review material, or recent clues, but they must not enter `world` or
`prompt_summary`.
The product-facing portrait world uses four stable groups: identity facts,
long-running work, preferences/interests, and collaboration style. Graph
relationships become visible only after graph-to-assertion promotion has produced
a governed recent or durable assertion.
`goal_profile` is always recent context, never portrait world or ToM core-trait
material. The portrait renders a current goal from its literal Claim target as
`近期计划：<target>` and may carry that deterministic line into the bounded
prompt summary without allowing model wording to replace it. When the assertion
expires or disappears, or when a newer Claim route or projection outcome changes
its eligibility, the cached portrait is stale and must rebuild so an obsolete
plan is not retained.
Historical goals whose source time cannot establish currentness remain governed
pending reviews. The product may let the user select and confirm several such
plans together, but each selection resolves through the ordinary versioned
review contract and becomes user-feedback authority. Unselected plans remain
pending for later; omission from a batch is never interpreted as rejection.
The self-portrait API returns this grouped projection directly. It does not
return a second raw-observation shape, and the frontend must not reclassify
assertions or graph material with its own policy.
The materialized portrait has one current shape. It does not carry internal
schema versions or compatibility readers for older portrait payloads.
Materialized portrait rows are cacheable, not permanently authoritative: reads
and prompt assembly must rebuild them when newer profile or assertion inputs
exist. User feedback or correction on a user assertion
should enqueue a debounced portrait projection refresh after the assertion
update succeeds. The delay is controlled by
`agent.memory.l2.portrait_projection_refresh_delay_seconds`, and multiple
assertion changes for the same user within that window are coalesced.

Bootstrap is only responsible for injecting the first assistant opening for a
persona. After that opening is persisted, all profile extraction returns to the
normal chat -> L1 -> L2 pipeline; bootstrap must not own a separate user-profile
extraction path. The first opening may use only the governed portrait prompt
summary; it must not sample raw imported L1 events or source summaries directly.
If onboarding begins the first real chat with a user-authored answer instead,
that answer is persisted as an ordinary chat message and follows the same L1 and
L2 pipeline. Its first-context marker may select narrower extraction guidance,
batch it promptly, suppress one-turn episode or relationship derivation, and
consume the persona's one-shot opening state, but it must not create a parallel
profile write path. Empty or low-signal extraction is a valid outcome and must
not be presented as a successful durable memory.
Recent portrait lines remain tentative, while durable lines have already passed
the normal assertion promotion boundary. A completed sensor backfill triggers
the L2 derive task, and successful derived-profile writes explicitly enqueue the
same debounced portrait refresh used by ordinary assertion changes. This keeps
cold-start personalization timely without creating a second profile pipeline.

Historical imports use the same memory pipeline with an additional source
boundary. After explicit authorship or participant confirmation, a bounded slice
may enter L1 immediately so onboarding can finish without claiming that durable
understanding already exists. The full import persists normalized source records
separately from per-job work state. For host-owned Markdown, a file fingerprint
hashes its normalized relative source name and bytes, and the source-record key
hashes that identity with parsed session key, sequence, speaker, and content.
For platform adapters, source-record identity instead uses the importer package,
importer format version, stable session key, and stable message key. Re-exporting
an expanded archive therefore reuses existing event identities and adds only new
messages; an archive-file fingerprint may deduplicate an identical preview job but
must never define message identity.

After a platform session has been confirmed into L1, its imported stable-message
sequence is append-only. The host rejects an incremental archive that changes the
existing message-key prefix and requires replacement through delete plus complete
re-import. This avoids rewriting sequence metadata on already projected evidence.
Before a preview is persisted, the host also runs the parser outside the memory
clear barrier and off the service event loop; asynchronous parsers receive a
private event loop inside the worker thread. The service admits at most two
parser workers, and the fixed preview deadline includes time spent waiting for a
worker slot. A timed-out or cancelled request abandons its result but retains the
slot until the underlying worker actually returns, so repeated timeouts cannot
create an unbounded parser backlog. Parser output is copied through the declared
schema and checked against source, record, warning, and total-text budgets inside
that same worker before deep Pydantic validation; an oversized constructed model
therefore cannot make the service loop materialize its complete object graph
before rejection. Runtime shutdown closes importer-preview admission and advances
a service generation before giving active workers a bounded drain period. A late
thread result cannot persist through that generation fence, although terminating
an uncooperative Python thread still requires a future process-isolated importer
host. The host then compares full input fingerprints before and after parsing and
rechecks the memory-clear epoch inside the governed operation.

The host Markdown importer treats each file as exactly one user-authored
document. It does not infer chat messages, speakers, sessions, or timestamps from
Markdown syntax or prose. Its complete-selection fingerprint includes a parser
policy version so previews made under an older structural interpretation are not
silently reused. Chat-shaped text remains content inside the document; quoted or
attributed spans still pass through the document authorship gate below rather
than inheriting user authority.

An unconfirmed Markdown preview may be extended transactionally. Existing job
memberships and per-source inclusion choices remain authoritative, newly added
sources receive new memberships and default to included, and records already
attached to that job are skipped by stable source-record identity. Appending is
forbidden after scope confirmation or any import work begins. A Markdown source
name reused with different content is a conflict rather than an in-place update;
the user must rename the file or clear the unconfirmed preview and select the
complete set again. This preview mutation does not apply to platform archives,
whose append-only session rules remain importer-specific.

`history_import_source_records` owns stable source/session/message identity,
explicit source kind, host-namespaced speaker identity and confirmed role,
optional parent-message identity, content,
event time semantics (including the parser-declared confidence/anchor and
captured IANA timezone), and the stable event ID.
For platform imports, `exact` and `inferred` records carry the parser's
`occurred_at`, while `source_order` and `unknown` records carry no source time.
The host creates an internal ordering anchor only for those untimed records and
retains their original confidence. Reader-facing previews may label inferred
time as approximate and untimed records as missing, but must not present either
as an exact timestamp. For platform chat, the maximum event time in a session is
only a session-selection anchor: quick ingestion chooses newer sessions first,
while background handoff can progress from older sessions. Within each selected
session, source order becomes the canonical `session_seq` and governs the quick
prefix, remaining raw handoff, projection handoff, and L2 batch presentation
even when provider timestamps regress. Document imports retain event-time order.
Event timestamps never override declared order inside a chat session.
`history_import_job_records` owns only membership and that job's raw/projection
progress. Its key derives from the job and source-record keys, and the pair is
unique. The versioned complete selected-file fingerprint still identifies an
identical preview job for fast reuse. Shared source records retain one consistent
document-author interpretation across active jobs.

User-authored documents are submitted to ordinary L2 work. Approximate document
timestamps may support ordering but must not be presented as exact history.
Document extraction evaluates author-prose spans across the whole document and
does not treat headings, dialogue-shaped text, or requests as live chat speech
acts.

Confirmation durably commits the selected sources and self-participant scope
before the bounded quick import advances. The quick stage is service-owned work:
the confirming API may wait for its `quick_ready` boundary, but disconnecting or
canceling that request does not cancel the import. Startup resumes jobs whose
scope was committed while `quick_ready` was still false, and an explicit retry
can restart the same stage after failure. Recovery selects only ledger records
whose raw state is still pending, so an interrupted quick pass does not rewrite
records already acknowledged in L1.

History-import completion describes the importer boundary, not completed
cognition. Reader-facing counters distinguish source records durably stored in
L1 from records accepted by the durable L2 projection queue. A duplicate enqueue
is successful when the same stable event already has a projection job. Records
that were stored but could not be handed to that queue remain visibly retryable;
the import does not wait for assertion, graph, or portrait derivation before the
user can continue.

Platform-specific chat importers reuse the normalized history store and memory
handoff only after they supply explicit stable source, session, message, speaker,
source-order, parent-message, and timestamp semantics. The user identifies their
own participant identity in the host-owned confirmation UI; display names are not
identity keys. Counterpart turns remain non-cognitive L1 context, while confirmed
user turns follow the ordinary L2 assertion/graph/portrait pipeline. Historical
questions and requests are archive evidence rather than live instructions, and
counterpart turns may provide bounded conversation context without receiving user
authority. An LLM may analyze normalized messages after import, but it must not
invent structural identities or decide who the user is.
Adapter speaker IDs are source-scoped by default before they become persisted
host participant IDs. Export-global scope is accepted only as an explicit
importer-format guarantee; host-reserved document identities are never accepted
from platform adapters.
Deleting one job forgets an event only when no other active, selected membership
with a committed authorship or participant scope references that source record;
an unconfirmed preview may retain its own preview text but never retains L1 or
derived memory for another job. Deleting the final confirmed membership triggers
governed cross-layer cleanup, removes that job's membership rows, deletes source
plaintext with no remaining preview or job membership, and redacts the job to a
minimal content-free deletion tombstone. A history-import deletion intentionally
uses the reimportable source-event cleanup policy: the host has already stopped
the only passive producer, so the completed cleanup does not retain exact-event,
source-item, or idempotency replay barriers and a later explicit complete import
may restore the same stable event identity. Explicit reimport cleanup also
removes that event's completed L2 projection identity and only its event-scoped
L2 forget evidence when no permanent replay tombstone protects the event; a
mixed rule keeps any evidence belonging to other events.
Upgrade repair resets an affected active import ledger to `pending`/`ready` so
the service re-enqueues real L2 work instead of reporting a stale projection as
complete. Every such deletion creates a new forget operation so a
delete-import-delete cycle cannot reuse an earlier cleanup.
Ordinary source, entity, chat, and user-requested forgetting keep their permanent
replay barriers unchanged. A global memory clear removes source records, job
memberships, and job state under the same import boundary.

An authorship declaration for an imported Markdown document applies to ordinary
author prose, not every byte in the file. Before a document Claim can use direct
user authority, the host locates its exact evidence occurrence inside a
deterministically classified author-prose span. Frontmatter, block quotes,
attributed or pasted dialogue, forwarded mail, fenced or indented code, inline
code, and third-party or unattributed quoted text do not inherit document-level
authorship. A self-attributed quote may remain author prose only when a
deterministic first-person reporting form makes that ownership explicit.
Ambiguous spans fail closed as non-authoritative evidence. This gate may
conservatively omit a real self-report, but it must not promote another speaker's
words or embedded instructions as facts about the user.

`L2` embedding uses a shared embedding pipeline across all layers; each layer defines its own text builder, chunk strategy, parent-table status writeback, and retrieval collapse logic. The entity catalog uses single-entity-single-vector without chunking. All L2 parent tables record unified embedding observation fields (`embedding_status`, `embedding_profile_id`, `last_embedded_at`); `knowledge_graph` also records these fields for relation-edge vectors. Runtime settings expose a persistent vector rebuild job for `L1`, `L2` entities, `L2` edges, `L3`, and `L4`.

Vector rebuilds are online refreshes, not destructive clear-and-refill jobs. Each
layer captures a fixed parent-row high-water mark and scans it with a stable,
monotonic row key, so concurrent retirement or deletion cannot shift the next
page. The rebuild does not globally clear existing vectors or chunk metadata.
Each item is embedded, checked again against its current parent, and then
published under the layer's normal embedding-write guard. Vector rows and parent
metadata use separate database transactions, so this is not a per-item atomic
swap; retrieval still requires a current parent or chunk mapping, and stale
late results remove only the identity they just wrote. This keeps same-identity
maintenance rebuilds searchable while preserving an older usable identity when
a hard-switch result becomes stale.

After a hard embedding-identity change, old vectors remain stored for safe
recovery but are not queried with the incompatible new model; coverage for the
new identity grows as the online rebuild advances. A normal write or delete that
reaches the index after the rebuild starts takes precedence over an older
rebuild result for the same parent. Failure or cancellation never performs a
global rollback and must not erase the sole usable copy; already published
current results and already pruned true orphans may remain. A successful rebuild
prunes vectors without a valid current parent or chunk and removes superseded
model copies only for parents it actually refreshed. Configuration saves that
change vector execution first pause new rebuild starts and cancel and await the
active rebuild before refreshing the runtime. The same boundary advances a
process-local execution generation around the save and refresh; every shared
embedding pipeline captures that generation before model work and checks it
again at the serialized vector-publication gate. A result from an older
configuration is discarded instead of being published as a newer normal write,
and published parent metadata keeps the exact vector identity stamped at that
gate. Independent identity checks still fail a job if its embedding identity
changes through another runtime path. The coordinator is process-local under
the current single Python sidecar model; a future multi-process runtime must
replace it with a database lease and durable generation before allowing
concurrent rebuild owners.

An atomic cutover between incompatible embedding identities would require a
complete shadow index, write replay or dual-write coverage, and roughly double
the temporary vector storage. It is intentionally outside the current rebuild
contract; do not describe a hard model switch as having zero search-coverage
transition time.

Vector indexes must separate incompatible embeddings by hard identity. Remote embedding identity is `model + dimension + text_builder_version`; provider ID, base URL, API format, and provider type are provenance and may produce a soft warning but not a forced table split. Local embedding identity is `model_file_hash + dimension + text_builder_version`, where `model_file_hash` is derived from the ONNX model and tokenizer/config sidecar files. The sqlite-vec registry stores the hard index identity, so changing models or text-builder versions does not silently query stale vectors. When operators intentionally change embedding identity, Settings warns before saving and the rebuild job can regenerate all layer vectors in the background.

`L2` is the "evidence-backed interpretation layer", not the raw truth layer.

Key properties:

- Derived from `L1`, not independently produced
- All artifacts carry evidence references
- Confidence-scored
- Supports conflict handling and subsequent correction
- Has exactly one extraction ingress: durable projection jobs written from `L1`
- Does not accept runtime-only events or maintain an in-memory event staging path
- Manual flushing claims pending durable projection rows; it never fabricates unleased extract jobs
- Routes every grounded Claim to explicit graph/assertion projection targets before downstream materialization

#### L2 Product Subdomains

**State Memory** stores versioned latest-truth about entities. Assertions follow a lifecycle:

- Status values: `tentative` → `corroborated` → `stable`; can transition to `superseded`, `expired`, `archived`, or `user_rejected`
- Supersession: When a fact changes (e.g. "I moved from Hangzhou to Shanghai"), the old assertion is marked `superseded` with `superseded_by` / `superseded_at` linking to the new one. This is a normal lifecycle transition, not a contradiction.
- Decay policies: `session_decay`, `fast_decay`, `time_window`, `evidence_only`, `none`
- Memory subdomain tag: `memory_subdomain` distinguishes `'state'` (mood, stress, engagement) from `'semantic'` (preferences, long-term facts) within assertions
- Reconciliation: the cognition store's `reconcile_entity()` re-derives confidence and stability from evidence counts and time spans. This is the sole reconciliation path; LLM services do not infer lifecycle state or select winning trait values.
- Snapshot evolution: `refresh_entity_snapshot()` rebuilds from reconciled assertions + graph edges, maintaining `core_traits_history`, `preferences_history`, `relationship_history`, `mood_trajectory`, and `emerging_signals`

Assertion family semantics are centralized in `backend/src/magi/memory/l2/assertion_family_policy.py`. The canonical families are `stress`, `mood`, `engagement`, `trigger`, `relationship_shift`, `group_atmosphere`, `public_sentiment`, `identity_profile`, `communication_profile`, `preference_profile`, `interest_profile`, `project_profile`, `goal_profile`, `routine_profile`, and `state_profile`. Families describe meaning, not retention: `preference_profile` is reserved for actual likes and dislikes, `interest_profile` describes grounded attention or interest without claiming affinity, `project_profile` describes active project work, `goal_profile` represents a concrete near-term intention and is always bounded recent context rather than durable identity or snapshot core-trait material, and `routine_profile` owns repeated behavior rhythms and habits. Each family policy defines its durable description, baseline lifecycle defaults, snapshot bucket, and value-localization expectation. Runtime confidence and TTL tuning lives under `agent.memory.l2.assertion`, and host materialization plus assertion reconciliation read those config-backed values rather than maintaining separate TTL or state-threshold constants. These policies drive host validation, materialization defaults, decay, and snapshot placement; they are not model prompt instructions.

Profile assertion confidence and profile assertion horizon are separate decisions. Validation state answers how well supported a judgement is; the host-owned promotion evaluator answers whether the same grounded material remains event-only, is useful as recent context, or is durable enough for long-term profile use. Event-only profile candidates are not persisted as assertions. Recent profile assertions use a bounded time window and may be renewed by new evidence. Durable assertions use evidence-governed lifetime and are not downgraded merely because no new event arrived. User confirmation changes confidence but does not by itself turn recent context into a durable trait.

Claim-backed promotion recomputes both occurrence statistics and policy metadata from the complete active Claim/evidence ledger for the routed slot and canonical value. Fact kind, predicate, temporal cue, evidence class, source strength, and durable permission do not come from the event currently being processed. Direct user self-report has authority over weaker replay evidence; without it, whitelisted sustained-engagement predicates outrank passive external exposure, and unknown or conflicting metadata falls back conservatively. Removing the stronger evidence may legitimately recompute a weaker horizon, but processing order and restart must not change the result for the same ledger.

Source-event forgetting captures the affected route/value identities before it
redacts Claim receipts, then recomputes materialized assertion and pending-review evidence,
validation state, confidence, retention horizon, expiry, and portrait/snapshot
invalidation from the surviving active ledger in the same immediate
transaction. Ordinary writes remain monotonic and cannot shorten a stronger
horizon; explicit forget governance may downgrade, archive, expire, or later
reactivate a `forget:event` assertion when a subsequent deletion changes the
remaining conservative policy. A preliminary source tombstone excludes any
Claim linked through supporting or antecedent evidence from occurrence statistics
and performs this reconciliation before readable Claim state is destroyed, so a
crash between admission and full cleanup cannot leave an authoritative stale
assertion.
Pending reviews participate in the same Claim-authority retirement before
readable Claim data is scrubbed: shared reviews retain only surviving support,
and the last removed support closes the review in the forget transaction.

Forgetting also deletes every affected materialized user snapshot and its
dependency rows inside the forget transaction, before the subject revision is
advanced. The privacy rebuild therefore starts without the previous snapshot as
an evolution baseline; if the rebuild fails, the deleted snapshot stays hidden.
When a snapshot remains materializable, ordinary situation changes and
corrections may retain the prior snapshot as an evolution baseline. Forgotten
material, however, may never survive as a historical location, transition, or
explanatory sentence in that history.

Claim-backed promotion statistics retain the evidence IDs whose wording selected
an aggregated recent policy, and those policy-defining events must have trusted
calendar provenance. A recent assertion's validation, decay, and TTL anchor is
the latest trusted time in the complete ledger, not whichever event happens to
trigger the current projection attempt. A delayed replay therefore cannot
shorten a recent assertion behind newer trusted evidence.

Family choice shapes downstream handling but does not by itself decide trust. Conflict decisions are primarily source-tier and active-key based: user-authored assertions remain authoritative over behavioral or plugin-derived inference unless the user explicitly corrects or rejects them. Family policy determines whether a value behaves like short-lived state, durable semantic profile, preference snapshot content, or core-trait context after it has passed source-tier and evidence gates.

Assertion API rows expose family display metadata, including `trait_value_i18n`, so the frontend can localize controlled state values while preserving literal user-authored profile and preference values.

**Episodic Memory** stores bounded historical activity, episode, and experience structure:

- Three tables: `episodes`, `episode_events`, `episodes_fts` (FTS5)
- Episode types: `activity`, `visit`, `session`, `conversation` (each with different time-gap thresholds)
- Streaming formation: `assign_events_to_episode()` hooks into L2 pipeline extract workers; uses time-gap detection and entity/topic overlap for theme continuity
- Status lifecycle: `candidate` → `active` (promotion), then terminal
  `merged` (explicit curation merge into a survivor episode) or `invalidated`
- Promotion reports newly-active episode IDs to callers; L2 formation stays
  L2-only, while runtime callers that hold L1/L2/L3 handles (periodic L2
  maintenance and manual reconsolidation) generate missing L3 episodic summaries
  for those episodes or for active backfill scope
- Product episode lists default to `status='active'`; episode detail reads join
  event memberships with live L2 assertions whose `evidence_events` intersect
  those events; confirmation uses the lightweight assertion feedback path,
  while rejection and editing use the governed correction surface
- Backend add/remove event curation operates on system-suggested nearby candidate
  events, not a global event search. Merge curation chooses a suggested active
  episode and folds it into the current survivor. Split curation uses a
  chronological breakpoint between member events, creates two active child
  episodes, invalidates the source episode, and regenerates child recaps.
- Explicit merges move event memberships to the survivor, mark the absorbed
  episode `merged`, and recompute the survivor `source_event_count` from
  `episode_events`
- User agency fields: `user_label`, `user_note`, `user_pinned`
- Full-text search via FTS5 over `summary`, `label`, `user_label`
- Episodes can overlap and nest via `parent_episode_id`
- Each episode carries `primary_entity_ids`, `primary_place_ids`, `primary_topic_keys`, `continuity_signals`, `dominant_mode`

Episodes are the L2 episodic substrate, not necessarily the final
user-facing memory object. They organize L1 evidence into bounded activity or
theme segments such as browsing bursts, search sessions, debugging windows, or
conversation spans. They may be useful evidence even when they are too shallow,
generic, or source-driven to feel like a meaningful life/work experience.
Default L2 retrieval must not surface episodes as top-level user results.
`experience_recall` returns promoted experiences, with source episodes attached
only as evidence on those experiences. `episode_recall` is reserved for explicit
activity-span recall, but episodes must not be surfaced or ranked as user-facing
hits; any episode use in that path should only narrow an evidence window before
returning L1 events or promoted experiences.

The frontend review routes use the Experience index, draft editor, and detail
surface. Source episodes remain readable through the episode detail API for
draft evidence expansion. Timeline pin/hide actions and operator reconsolidation
keep their episode APIs; no separate episode card, recap editor, or boundary
curation dialogs are mounted in the product UI.

**Experiences** are the product-grade episodic object surfaced in the review
page and timeline. An experience is promoted only when one or more substrate
episodes/events form a narratable memory with a clear theme, evidence boundary,
user involvement, and some change, outcome, decision, discovery, or unresolved
thread worth revisiting. L2 owns the experience identity, membership, lifecycle,
curation state, user-selected cover asset reference, and evidence backlinks. L3
owns the natural-language review and Magi interpretation attached to that
experience. Timeline and review surfaces consume experiences; they do not define
or persist them.

Experience membership must remain evidence anchored. The durable model should
allow membership rows to reference source episodes first and direct L1 events
when finer curation is needed. The source episode remains a supporting segment;
it does not become a new fact source. Any user/profile claim inferred from an
experience must enter the normal assertion pipeline with source policy,
confidence, and evidence links instead of being treated as true because an
experience summary said it.

Experience promotion is a second-stage process over active episodes:

- Build candidates from a single strong episode, adjacent same-theme episodes,
  or repeated cross-day themes.
- Score candidates for narrative quality: theme coherence, user involvement,
  boundary clarity, outcome or turning point, long-term relevance, and duplicate
  overlap with existing experiences.
- The V1 promotion gate applies deterministic quality checks before persistence:
  source/tool-only clusters, technical artifacts, weak boundaries, and candidates
  without user-action signals are rejected at seed level with a recorded reason,
  while user-accepted manual seeds remain promotable.
- Promote only candidates that can be expressed as a concrete natural-language
  memory, not merely as a source/app cluster.
- Generate the L3 experience review after promotion so the prose is attached to
  a stable L2 object with traceable evidence.
- Experience reviews use an experience-specific review prompt rather than the
  shorter episode recap prompt. The review stores a longer narrative plus
  generated intent/outcome metadata; non-fallback reviews refresh generated L2
  title/body fields so review pages and recall use the same prose, while
  user-owned labels and notes stay independent.
- Trigger promotion from both the manual `l2/episodes/reconsolidate` catch-up
  endpoint and the periodic L2 consolidation job, so the review page can refresh
  from the same evidence pipeline instead of relying on frontend-only filters.

User-guided creation follows the same evidence boundary without exposing the
episode substrate as a flat picker. The user starts with a natural-language
description and optional time range. The first retrieval pass uses that request
unchanged against L1, resolves matching events to active episode evidence, and
lets a validated selector include, exclude, or leave candidate evidence as
possibly related. The result is saved as a resumable draft, not an active
experience. The default draft surface is selection-first: it previews the
proposed title and recap, lets the user include or exclude evidence-backed
memory segments, and reveals their event evidence on demand. Editing generated
prose and time bounds is a secondary action rather than the primary review
surface. Draft changes are autosaved. Only explicit user confirmation creates
the active L2 experience and its durable chapter structure; generated text
cannot introduce evidence identifiers that were not retrieved from L1/L2. A
user-selected draft cover is stored in the same local media asset system as an
active experience cover and is carried into the created experience, including
retry reconciliation after a partially completed create operation. Draft and
active review surfaces share the same cover-hero presentation while keeping
their editing actions and lifecycle behavior separate.

**Semantic Memory** stores durable entities, relations, and preferences:

- Knowledge graph edges carry `fact_kind` (`explicit_fact`, `public_topology`, `interaction_evidence`, `stable_preference`) for admission policy enforcement
- Temporal validity: `valid_from` / `valid_to` on edges
- Privacy scope: `privacy_scope` on edges, facets, assertions, episodes, and experiences
- Synonym-aware edge dedup prevents predicate drift
- Confidence accumulation uses noisy-OR: `1 - (1-old)(1-new)`, capped at `agent.memory.l2.confidence.accumulation_cap` (default 0.99)

#### L2 Projection Pipeline

The default execution model:

1. `L1` fact is successfully written to durable store
2. Synchronous rule evidence classification and policy resolution run on the stored event when available
3. If `cognition_eligible=true` and evidence policy allows cognition, an `l2_projection_jobs` record is created in `memory.db`
4. If evidence classification is unavailable or inconclusive, raw L1 storage remains successful, but fact promotion and L2 graph/assertion writes wait for evidence resolution rather than treating the event as authoritative by default
5. `L2Pipeline` in the `runtime_worker` claims ready jobs and marks them `queued`
6. Claimed events are batched by batch owner / session / user. Before work enters
   the extract worker, the queue atomically binds every member to one canonical
   batch descriptor and attempt key derived from the complete canonical lease set;
   only that exact descriptor may mark the jobs `running` or write results.
7. Successful extraction marks jobs `completed`; failures mark them `failed` or requeue to `pending`
8. Model output must be a JSON object matching the stage's required top-level fields and field types. Repairable auxiliary metadata is normalized before validation; in Phase 1, an absent, unknown, or source-unsupported `temporal_cue` becomes an unambiguous cue detected in the evidence quote, or `unspecified` when no cue is present, without another model call. A semantically invalid Phase 1 claim is rejected individually so one bad candidate cannot discard valid peers or fail the projection job. Invalid top-level JSON or stage structure still receives one stricter format retry. Repeated failure of the required Phase 1 extraction marks the projection job `failed`; failure of optional entity disambiguation leaves those mentions unresolved, while failure of optional Phase 2 wording persists the host-routed Phase 1 projections and completes with an explicit degraded-stage marker. Non-model infrastructure failures may still requeue to `pending`.

Batch policy:

- Plugins provide `l2_batch_policy()` with advisory batching info: `max_events`, `min_ready_events`, `max_estimated_tokens`, `max_wait_seconds`
- For high-throughput sources, plugins can provide `catch_up_owner` for coarser-grained catch-up shards
- The pipeline switches between `catch_up` (throughput-focused) and `steady_state` (latency-focused) modes based on backlog
- Durable claim is subject to runtime backpressure
- Plugin sync cursors only track "synced to L1", not L2 progress. A sensor item
  may advance that cursor only after the memory-owned sensor commit boundary
  returns an explicit L1 confirmation (new write, idempotent duplicate, or an
  intentional forget-governance rejection). Transient write failures and
  memory-clear races fail the sensor job and retain the previous cursor.
- The `runtime_worker` registers `memory_l1_maintenance` as a periodic task for L1 retention cleanup, including compressible L1 events that are already covered by L3 summaries and pinned-payload pruning.
- The `runtime_worker` registers `memory_l2_maintenance` as a periodic task for offline entity catalog / knowledge graph maintenance, including ghost references, mergeable types, orphan entities, assertion reconciliation, edge embedding refresh, predicate consolidation, and promotion-counter pruning.
- The `runtime_worker` registers `memory_l2_consolidate` as a separate periodic task for episode promotion/merge/invalidations, experience promotion, and missing episodic/experience summary generation.
- L2 experience consolidation caps LLM-backed seed selection per run, then falls back to local selection for remaining seeds so daily maintenance cannot spend unbounded time waiting on model calls.
- The `runtime_worker` registers `memory_l3_maintenance` as a periodic task for L3 summary retention cleanup.
- The `runtime_worker` registers `runtime_operational_gc` as a periodic task for non-layer cleanup such as L0 session expiry/checkpointing, runtime operational garbage collection, and chat asset garbage collection.
- `MaintenanceDaemon` remains only for lightweight process-local checks such as health checks and log-size warnings; it does not own data-retention cleanup.
- Manual `/l2/episodes/reconsolidate` uses the same scheduler target lock as `memory_l2_consolidate`; if consolidation is already running, the endpoint returns HTTP 409 instead of competing with scheduled episode consolidation.

Extraction flow:

- Durable L2 projection batches are owner-isolated. Session events stay session-scoped; events without a session are separated by source, optional plugin batch owner, and user. Structured hints are admitted and written per event under that event's evidence policy rather than inheriting the last event's batch context.
- A claimed row is not yet an executable attempt. Final worker batching persists
  the exact descriptor on every member, and batch-state/result writes verify the
  descriptor, bound event set, lease tokens, and attempt counts. Derivation,
  outbox, and clear-boundary paths additionally verify the subject revision or
  clear generation they own. Migration or crash recovery returns unbound/partial
  queued work to `pending`; a subset of leases can never complete the whole batch.
- Phase 1 extracts current-batch entities, facts, and candidate observations from admitted events, using source-owned hints and extraction-profile instructions as anchors. Each fact includes a grounded linguistic temporal cue (`one_off`, `recent`, `recurring`, `stable`, or `unspecified`) that reflects explicit source wording only; it never owns retention policy. The host then assigns each retained fact a deterministic claim reference and verifies its current quote, evidence mode, and bounded antecedent IDs. Missing, out-of-batch, context-only, or unmatchable support rejects that candidate without retrying the full response and without expanding evidence to the whole batch.
- Phase 1 entity candidates are admitted only when their exact surface occurs in eligible current evidence. Cross-script translated normalized names are restored to that surface before typed entity resolution, and alias signals absent from the same evidence are discarded. Imported Markdown occurrence checks exclude blockquotes, code, and pasted dialogue. Extracted entity mentions are then attributed only to events that literally contain the surface or retained normalized name. A context-only entity may be used transiently only for a validated contextual claim when its exact catalog ID and canonical name already exist, but it cannot create catalog records, aliases, event-entity links, or mention evidence for the current event. Underspecified entities are not registered.
- Grounded Phase 1 claims receive a deterministic semantic route before projection. Only routes that explicitly target the graph and have resolved catalog endpoints become graph candidates; independently eligible assertion routes are not discarded merely because an optional graph endpoint is unresolved. The graph store owns merge, corroboration, exclusivity, and opposite-predicate handling; Phase 2 never restates those facts as graph writes.
- Entity disambiguation and Phase 2 wording are optional enrichments. If entity disambiguation exhausts its model/JSON retries, affected mentions remain unresolved and no fallback entity is created. If Phase 2 wording exhausts its retries, validated Phase 1 Claims, graph facts, structured facets, Assertions, reviews, and terminal outcomes are still persisted; only optional wording is lost, and the projection is completed with the degraded stage recorded in diagnostics and logs.
- Host materialization reads the complete active Claim/evidence ledger required for occurrence, currentness, conflict, and lifecycle decisions. This host-owned retrieval does not call an LLM and is never truncated to fit a Phase 2 prompt. Phase 2 receives only the bounded current Claim material needed to produce optional wording.
- Phase 1 resolved entities may be used to fetch directly linked L1 event text through the event-entity index; this is preferred over asking the model to rediscover history. External sensor events without a session must not fall back to arbitrary same-user recent chat context.
- Phase 2 runs only as optional wording synthesis. Its output contains concise summaries bound to deterministic Phase 1 Claim IDs and no record IDs, family, trait, slot, route, confidence, lifecycle, expiry, or persistence action. Invalid or cross-target summaries are discarded without changing materialization. The host independently derives family, evidence, confidence, horizon, volatility, lifecycle, review eligibility, and safe conflict actions from routed Claims and the complete active ledger.
- Passive observations remain graph or episode evidence. They never enter the direct Assertion write path. A graph-derived rule may independently promote aggregated observations into expiring recent context after its own observation, distinct-day, time-span, and recency thresholds; durable profile conclusions additionally require a plugin-declared non-passive signal preset and explicit durable permission.

#### Evidence Classification and Write Policy

L2 ingestion uses shared evidence classification before LLM extraction. The implementation lives in the shared `magi.memory.evidence` package and is consumed by L1 retrieval annotation, fact-like retrieval scoping, and L2 write governance.

Classifier and policy responsibilities:

- Active classifier outputs: `user_self_report`, `user_question`, `user_request`, `assistant_tool_grounded`, `assistant_freeform`, `assistant_runtime_derivation`, `system_runtime`, `external_observation`
- `assistant_quote` remains a reserved provenance class; ordinary assistant quote-like text classifies as `assistant_freeform` unless upstream marks it more specifically
- Each class maps to a `PolicyDecision` controlling `allow_graph_write`, `allow_assertion_write`, `evidence_weight`, etc.
- Event policy uses exact capability booleans rather than an assertion-family scope: direct Assertion writes require `user_self_report`; `external_observation` may extract entities and write Graph facts, while any higher-level Assertion promotion is owned by derived rules with their own thresholds
- Whether a user-authored Claim describes the user or another subject is Claim-level route semantics, not a second event-level evidence class
- `public_topology` and `stable_preference` fact kinds require explicit or structured extraction sources
- User questions, user requests/commands, assistant memory answers, and assistant freeform text must not become new user-profile facts through L2 graph/assertion writes
- Unknown evidence can be retained as raw L1 and episode/audit material, but must not be promoted into fact-like retrieval or L2 graph/assertion state without an explicit policy decision
- Existing L1 rows with missing, stale, or failed evidence annotations are repaired through `L1EventStore.backfill_evidence_annotations`, which reuses the same shared classifier and policy resolver

#### L2 Write-Side Semantic Conventions

Source integrations enrich events before L2 processing:

- Source integrations pass `structured_entity_hints` via `MemoryEvent.metadata_json`
- Sensor integrations pass `fact_hints` as the preferred source-owned structured-fact path
- Legacy `relation_candidates` may still feed older timeline/relation projections, but should not be the primary L2 cognition path for new plugins

Core principle: whoever best understands the raw data produces the high-confidence structural facts. `L2` is responsible for unified integration, conflict handling, persistence, and residual LLM extraction.

Write pipeline:

```text
Plugin / Sensor / Host integration
  -> source-owned semantic enrichment
  -> MemoryEvent.metadata_json
  -> Ingestion gateway normalization + admission
  -> L2 pipeline merge / conflict handling / persistence
```

**Enrichment ownership** is split by who understands the data:

- **Source-owned enrichers** — For browser history, calendar, maps, photo library, git activity, etc.
- **Modality-owned enrichers** — For images, PDFs, links; extract EXIF, OCR, titles, canonical URLs
- **Residual LLM extraction** — For free-form chat text or low-structure sources; fills remaining semantics

**Fact kinds** distinguish object structure from user evidence:

- `public_topology` — Stable object structure (e.g. account belongs to platform, place located in city)
- `interaction_evidence` — User interactions (e.g. visited, viewed, followed, used)
- `stable_preference` — Explicitly expressed preferences or high-confidence configuration exports

"Like" should not be simplified to a single graph predicate at write time. For most passive sources, the more appropriate durable representation is to write interaction evidence first, then let the query side perform affinity aggregation.

Tags, categories, and weak co-occurrence are not fact evidence. They may help search, grouping, or source-local summaries, but they must not become L2 user preferences without an explicit fact source or a host-owned derived rule over accumulated graph evidence.

**Admission rules** — Runtime decides whether a source-owned fact enters the durable graph, based on `fact_kind`, `predicate`, and `origin_mode` (`source_explicit`, `source_structured`, `heuristic`, `llm_inferred`):

- `public_topology` — Only facts from `source_explicit` or high-confidence `source_structured` can directly form rule candidates
- `interaction_evidence` — Real events (`VISITED`, `VIEWED`, `USES`) can typically form rule candidates directly
- `stable_preference` — Passive sources cannot directly write; only explicit self-description, configuration exports, favorites/subscription lists qualify

`FOLLOWS` requires stronger signals than single content page visits; account pages, profile pages, follow lists, or explicit subscription lists are acceptable.

**Plugin and ingestion responsibilities**:

- Source integrations produce: entity hints, fact hints, optional tags/batch hints
- Ingestion gateway handles: schema validation, canonical/local ref normalization, writing hints into `MemoryEvent.metadata_json`, generating rule-backed graph candidates per admission policy
- `L2Pipeline` handles: using source-owned hints as structural anchors, persisting grounded Claims, host semantic routing, graph projection, deterministic Assertion materialization, optional summary wording, governed persistence, and snapshot refresh

**Graph-derived assertions** convert accumulated graph evidence into inferred profile assertions only through host-owned rules. Built-in interest aggregation and plugin-contributed `derived_assertion_specs` both compile into validated `GraphDerivedAssertionRule` instances. Plugins declare the semantic family, a domain signal preset (`passive_exposure`, `sustained_engagement`, `deliberate_choice`, or `structured_source`), recent observation/day thresholds, and whether durable promotion is meaningful. The host reads the original L1 occurrence timestamps for the predicate-bound evidence IDs, calculates exact evidence count, distinct days, span, and recency without an LLM, and then owns the final recent-versus-durable decision. Plugin thresholds may be stricter than the host safety floors but cannot weaken them. Passive exposure can produce only an expiring recent assertion; durable promotion requires an explicitly permitted non-passive preset and higher host floors. All writes use the normal assertion lifecycle and preserve source-tier conflict protection so user-authored assertions are never overwritten by behavioral inference.

Rules may constrain allowed graph object types so broad passive objects such as individual web pages, generic software names, or implementation artifacts do not become user-profile traits unless the source explicitly marks them as suitable profile evidence. Host-owned quality gates also reject low-level object labels such as raw URLs, domains, file paths, coordinates, and hash-like identifiers before they can become profile assertions; those details may remain graph evidence but should not appear as portrait traits. The host fallback interest rule emits `interest_profile` recent context only after repeated activity on multiple original occurrence days. Source-specific rules are appropriate for repeated behavioral domains such as repository work, GitHub project activity, terminal tool usage, foreground app usage, music listening, game play, and browser content interests; single observations from those sources remain graph evidence.

Plugins may strengthen extraction and presentation quality by declaring structured hints, graph relation candidates, extraction profiles, source-specific Phase 1 instructions, optional summary wording instructions, and typed `DerivedAssertionRuleSpec` rules. The host routes every grounded Claim and exclusively chooses Assertion family, trait, slot, target, value, promotion horizon, lifecycle, and governance action. Phase 2 may return only claim-bound natural-language summaries; an empty, invalid, or failed Phase 2 response never creates, suppresses, merges, or changes an Assertion. Plugins do not own the final assertion ontology or bypass source-tier governance.

**Ontology** uses one closed canonical entity registry for both extraction and
structured hints. The Phase 1 prompt defines every registered type and the host
validates profile-specific allowlists without collapsing types into a smaller
second ontology. Existing catalog IDs retain their stored type.

- Choose the most specific evidence-supported registered type.
- `concept` represents an abstract idea, quality, style, or preference.
- `other` represents a concrete reusable entity that fits no more specific type;
  unfamiliarity is not sufficient reason to use it.
- New catalog names must be reusable noun-like labels. Complete sentences, long
  action clauses, and multi-action plans remain in the Claim and are rejected as
  new entities; independently reusable activities, skills, projects, places, and
  named objects remain eligible.
- Internal topology identities such as `presence` are normally supplied by
  source-owned structured hints rather than invented as free-form graph facts.
- Internal topology predicates: `PRESENCE_OF`, `ON_PLATFORM`, `LOCATED_IN`
- Behavioral/preference predicates: `FOLLOWS`, `VISITED`, `VIEWED`, `USES`, `LIKES`, `DISLIKES`, `INTERESTED_IN`

Key constraints:

- Platforms use `software`, not a separate `platform` type
- Creator identity uses `person` / `group` / `organization`
- Venues and cities use `place`
- `category` is not a registered general graph entity type; handle it as a query/topology facet first
- Extraction profiles distinguish model-extraction allowlists from structured-hint allowlists
- `HAS_CATEGORY` does not enter the main graph; classification values are carried in facets/structured hints

**Graph storage** persists `fact_kind` on knowledge graph edges; rule-backed and LLM candidates are unified to the same schema before insertion.

#### L2 Query-Side: Unified Query Mode Pipeline

L2 retrieval uses a unified `query_mode` system (replacing the legacy `recall_intent` + `query_mode` dual system).

**Ten unified modes** are registered in the mode registry:

| Mode | Primary Layer | Evidence Shape | Reducer |
|------|--------------|---------------|---------|
| `event_stream` | L1 | passthrough | passthrough |
| `exact_fact` | L2 | fact_card | span_select |
| `current_state` | L2 | state_card | latest_version |
| `episode_recall` | L2 + L1 | episode_bundle | narrative |
| `experience_recall` | L2 + L1 | episode_bundle | narrative |
| `cross_session` | L2 + L1 | grouped_list | enumerate |
| `temporal_compare` | L2 + L1 | comparison_frame | anchor_compare |
| `summary` | L3 | passthrough | passthrough |
| `activity_summary` | L3 | activity_digest | time_window_aggregate |
| `strategy` | L4 | passthrough | passthrough |

Each mode defines a `QueryModePlan` with:

- Layer weights for mode-adaptive RRF
- Primary and secondary layer preferences
- Evidence assembler type and reducer type

The evidence assembler and reducer fields are the mode contract, not a guarantee that every named reducer has a dedicated implementation today. If a named assembler or reducer is not registered, the hybrid retrieval service still returns normal layer payloads and answer-facing findings for that mode. In the current implementation, `activity_summary` is exposed through the mode registry and `memory_query` tool; its `activity_digest` / `time_window_aggregate` entries describe the intended reduced evidence shape while the answer-facing path prioritizes L3 summary findings and falls back to L1 activity evidence.

**Fallback / auto routing**: Tool callers should pass an explicit `query_mode` when the answer shape is clear. Product-facing search surfaces and uncertain tool callers may omit `query_mode` to request auto routing. In that case the rule router chooses a mode from the query text, defaulting to `exact_fact` when no stronger signal is present. The workbench trace exposes the requested mode, resolved mode, executed layers, and per-layer result counts.

**Legacy mode aliases**: Old `query_mode` names (`detail`, `experience`, `graph`) are mapped to unified modes via `normalize_query_mode()`. The older `recall_intent` contract is no longer accepted by the retrieval query builder; callers should pass `query_mode` or omit it for auto routing.

**Semantic frame**: The `L2SemanticFrame` expresses structured query slots:

- `query_family` — affinity, relationship, profile, activity, lookup
- `subject_scope` — self, explicit, multi, none
- `subject_mode` — self, single, multi, none
- `relation_shape` — single_fact, shared_fact, between_people, comparison, two_hop, unknown
- `subject_mentions` / `object_mentions` — role-specific query mentions, used before generic entity order
- `answer_kind` — creator, place, topic, person, software, media, unknown
- `entity_mentions` — raw entity names or mentions extracted from the query for resolution
- `constraints` — controlled constraint list, not arbitrary graph queries

The semantic frame is the authoritative L2 role contract. Top-level `entities`, `subject_hint`, and `predicate_family` are derived from it for older execution helpers rather than treated as a separate LLM contract. Explicit-subject grounding must bind the resolved subject entity before graph retrieval. If the semantic frame says the query is about a single explicit entity, the first matching `subject_mentions` entry is the graph subject and matching `object_mentions` entries remain object candidates. Collective multi-person queries that ask for shared, common, or mutual facts use `subject_mode=multi` / `relation_shape=shared_fact` and seed retrieval from every matching subject rather than forcing one person. L2 relationship results must also be scoped back through their `L1` evidence event IDs to the current memory owner; an edge that cannot be verified against the caller's L1 scope must not answer a fact-like query.

**Query execution pipeline** conceptually follows this shape:

```text
Natural language
  -> SemanticFrame (extract stable semantic slots)
  -> ResolvedFrame (resolve constraints to executable form)
  -> CandidateSet + EvidenceSet (topology/facet → candidates, then evidence)
  -> RankedAnswer (aggregate and rank by query semantics)
```

**Candidates first, then evidence aggregation**: For `affinity` queries, platform/place/category constraints find candidate objects first, then user-candidate edges are used to compute affinity. Object eligibility and affinity strength are determined by separate mechanisms.

Explicit non-vector entity matches from the query are hard grounding constraints for L2 relationship retrieval. For example, if the query names or aliases a known place/software/person, structured graph lookup narrows to that object id; vector-only entity matches remain soft candidates and must not become hard filters.

**Affinity is read-time aggregation, not a single predicate**. For different answer kinds, strong evidence differs:

- Creator: `FOLLOWS`, explicit `LIKES`, `INTERESTED_IN`, repeated consumption
- Place: explicit `LIKES`, repeated `VISITED`
- Software: `USES`, explicit `LIKES` / `DISLIKES`
- Topic: `INTERESTED_IN`, explicit `LIKES`, repeated consumption

Scoring model: positive and negative evidence aggregate separately; direct evidence outweighs lifted evidence; multiple weak evidences use saturating aggregation; yes/no decisions model positive and negative evidence independently.

**Constraint scopes**:

- `target` — Modifies the answer object itself (e.g. "UP hosts on Bilibili", "cafes in Hangzhou")
- `interaction` — Modifies the interaction context (e.g. "places I frequent when in Hangzhou", "who I watch when using Bilibili")

Controlled facets: `platform`, `located_in`, `category`. Parsed constraints are either entity-backed (resolvable to graph entities) or facet-backed (carried in `entity_facets` sidecar).

**Strategy-style execution helpers**: Query execution templates are selected by `(query_family, answer_kind)` combinations. The current implementation dispatches affinity plans through `L2SemanticRelationshipMixin` and semantic-frame helper functions rather than a standalone registry object. Extending should still be done by adding focused constraint handlers, evidence collectors, grouping/scoring helpers, or new strategy modules instead of adding large query branches.

**`presence` in queries**: Creator affinity candidates are based on `presence`; `presence -> ON_PLATFORM -> software`, `presence -> PRESENCE_OF -> person/group/organization`. Default answers aggregate by identity; only explicit account/channel queries output by `presence`.

**L1 and L2 collaboration**:

- `L2` handles stable structural constraints and long-term affinity
- `L1` handles strong time windows, single experiences, sequence, and count-based evidence
- Hybrid queries combine L2 candidates with L1 time-sliced evidence
- For `exact_fact` recall, answer-facing results should retain direct `L1` evidence for non-enumeration fact questions when available; time-anchored queries should preserve the strongest `L1` evidence first. `L2` may summarize or disambiguate, but should not replace the underlying fact text outright

**Governed answer reads**: every answer-facing assertion or relationship read
uses the same correction-aware view before ranking. This includes structured
graph lookup, topology traversal, vector-candidate hydration, graph spreading,
fallback plans, and query expansion. Administrative memory pages may still use
raw lifecycle reads because users need to inspect and correct inactive records;
those raw reads must not be reused for chat answers.

The governed view applies lifecycle, validity interval, and matching correction
scope together. A query without a time constraint reads current state. `as_of`
reads one historical point, while bounded or open time windows return only the
claim versions that win during some part of that window. A more specific scope
masks a broader claim only while that scoped version is valid. Relationship
history is reconstructed only from complete immutable snapshots written by the
governed correction path; legacy relationship versions that cannot prove their
full evidence, scope, and validity state are not exposed as historical facts.

**Observability**: Execution traces include the generated `SemanticFrame`, `ResolvedFrame`, selected strategy key, active providers/collectors, matched constraints, and top-contributing evidence items.

#### User Agency and Privacy

Users can interact with L2 artifacts directly:

- **Pending-memory decision**: confirm, reject, or confirm with a literal-value/summary edit through the versioned review command; the host creates any resulting authoritative Assertion atomically.
- **Assertion confirmation**: `apply_user_feedback(assertion_id, "confirmed")` strengthens the current evidence-backed interpretation without creating a correction.
- **Assertion or relationship correction**: the unified correction service records `record_error`, `situation_changed`, or `scope_refinement` and applies the same governance rules regardless of whether the caller is About You, Manage Memory, or a future chat flow.
- **Correction history and revert**: the correction action and safe immutable versions remain queryable; forgotten content is redacted rather than exposed through history. Revert eligibility is computed by the backend, and only the latest applicable correction can be reverted. If a future-dated correction is made irrelevant by an explicit forget action, it remains visible as cancelled history and is never activated or offered for revert.
- **Episode annotation**: `update_episode()` supports `user_label`, `user_note`, `user_pinned` fields
- **Episode review curation**: active episodes can regenerate their L3 recap,
  add or remove suggested member events, merge with a suggested active episode,
  or split into two chronological child episodes by event breakpoint. User-facing
  episode review surfaces should default to curated chapter-like episodes and
  keep raw L1 event identifiers in evidence/debug paths rather than primary
  reading views.
- **Experience review curation**: active experiences can be renamed, annotated,
  assigned a local media cover, hidden, regenerated, merged, split, and
  eventually curated at either source episode or direct event granularity.
  Experience edits update the L2 experience object and its membership; the L3
  review is regenerated or superseded from the updated evidence boundary.
- **Forget entity**: `forget_entity(entity_id)` — cascade soft-delete across KG edges, assertions, facets, episodes, retained relationship history, and dependent projections
- **Forget time range**: `forget_time_range(start, end)` — invalidates overlapping episodes and removes only assertion/relationship evidence whose original occurrence falls in the range; a claim remains current when independent evidence remains
- **Forget episode**: `forget_episode(episode_id)` — invalidates the episode, optionally returns member event IDs

Forgetting a time range removes that occurrence; it does not declare that the
same fact can never become true again. A later explicit user correction may
establish a new validity segment without restoring evidence from the forgotten
period. Forgetting an entity remains a durable barrier against passive replay of
the forgotten claims, including replay under a different context scope. Events
already known to support that entity receive a full derivative barrier. Older
unfinished projection jobs receive a narrower entity-candidate barrier instead:
they may still produce unrelated memories, but assertions, relationships,
catalog entries, facets, and episode memberships for the forgotten entity are
rejected. This keeps a large projection backlog usable without allowing an old
in-flight task to recreate the deleted entity. Immediately before catalog
deletion, the final canonical name and alias set is copied atomically onto every
full and candidate event barrier, so a name added while selection is paging
cannot let an older job recreate the same entity under a different identifier.
Entity forgetting also waits for the current L2 projection batch to finish and
holds that boundary through selection and cleanup; queued unrelated jobs resume
afterward under the narrower candidate rules.

Forget governance is stored independently from the mutable assertion or
relationship row. Claim barriers, forgotten evidence identities, and correction
lineage barriers therefore survive archival, maintenance purges, source replay,
and correction reverts. The claim-to-evidence ledger is unbounded and separate
from the small evidence list kept on the visible L2 row. When L1 is available,
each evidence item uses its canonical L1 occurrence time, even when one L2 write
contains evidence from several moments. Historical relationship reads apply the
same barriers and remove forgotten evidence before returning a version.

If a forget action removes a future replacement before it takes effect, the
scheduled correction is cancelled atomically: its rules are disabled, the
original current value is restored when that value was not itself forgotten,
and the scheduler will not activate the cancelled transition later. After any
forget operation, affected snapshots, profile and portrait projections, and L3
insights are hidden and rebuilt from the remaining sources under the new subject
revision. A failed rebuild never exposes the stale projection.

Database upgrades conservatively recover legacy forget markers and historical
relationship evidence. Old archived assertion rows that match the former forget
shape are protected from replay rather than risk reviving content the user had
already removed.

The product exposes this agency through three complementary surfaces. The
**Pending** workspace and memory Overview consume one discriminated pending-memory
read model that combines pre-materialization reviews, tentative or contradicted
Assertions, and reviewable memory stories. They share the same visual decision
lane while dispatching each item to its owning governed command. A
pre-materialization review offers confirm, reject, and edit-then-confirm; its edit
form exposes only the literal memory value and user-facing summary.
**About You**
keeps its grouped summaries read-only and lets the user open the exact source
behind a long-term understanding or a review item. Assertion-backed items use the
governed correction flow, while profile-backed items open Personal Profile because
that is their authoritative source. Confirmation remains a quick action; rejection
and editing open the same governed correction flow. **Manage Memory** provides the
complete assertion and relationship flow, including the
three user meanings (the record was wrong, the situation changed, or the claim
only applies in a specific context), an impact explanation before saving,
immutable history, and revert for the latest active correction. Superseded and
user-rejected records remain discoverable there so their history and valid revert
actions are not lost. The **Knowledge** workspace follows the same boundary:
confirmation remains lightweight, while rejection and editing open the shared
governed correction flow instead of writing assertion rows directly. Snapshots,
portrait summaries, and L3 summaries remain read-only projections; users correct
their supporting assertions or relationships instead of editing derived output.
Raw L1 events are historical evidence and are deleted or forgotten through their
own explicit controls, never "corrected" as if the captured event had not happened.

Durable correction is separate from chat answer rechecking. The public correction
surface is `POST /api/memory/l2/corrections`, with history at
`GET /api/memory/l2/corrections` and revert at
`POST /api/memory/l2/corrections/{correction_id}/revert`. Lightweight assertion
confirmation remains available through
`PATCH /api/memory/l2/assertions/{assertion_id}/feedback`, and that endpoint only
accepts `confirmed`. Rejection and editing of assertions or relationships always
use the governed correction surface; there are no separate public assertion-edit
or relationship-reject shortcuts. The desktop gateway does not implement these
mutations; it forwards them to the Python runtime so desktop and browser callers
share the same governance rules.

Each correction persists the previous claim, the user's reason, any replacement,
its time or scope, and an executable rule that guards future writes. An incorrect
claim is blocked from becoming current again when old events are replayed or a
source is resynchronized. A changed situation closes the previous time range;
a scoped refinement is only current when the query scope matches. Replacement
claims do not inherit evidence that supported the rejected value. Time-bounded
rules are evaluated against when the candidate evidence was observed, so evidence
from before a scheduled change cannot be governed as though the change had already
happened.

Corrections form a lineage over the current claim rather than independent undo
buttons. In an `A -> B -> C` sequence, the correction that produced `C` is the
only immediately revertible action; reverting it returns to the state owned by
the preceding step without overwriting evidence or changes created afterward.
The older correction becomes eligible only when no newer active correction still
depends on it. The API owns `can_revert`; clients must not infer eligibility from
timestamps, visible status, or the presence of a replacement.

The request identity used for retries is stored separately from mutable claim
identities in the same transaction as the correction. Entity repair and identity
merges never rewrite it. A retry therefore remains the same operation after a
claim moves, while reuse of that request identity with different content is
rejected. Corrections created before this immutable identity existed are not
assigned a guessed identity during migration; an unverifiable legacy retry fails
closed instead of being mistaken for a different operation.

Apply, retry, and revert responses all expose the claim that is current at the
response read snapshot. They never return an archived replacement merely because
that row was created by the requested correction, and a retry follows later
corrections or identity merges to the actual current descendant. For a scheduled
change, the current claim remains the committed claim until activation; callers
that need to address the future segment use the correction's explicit replacement
target instead of treating it as current.

Correction scopes use stable local context identities rather than free-text
labels. The stored contract is an `all_of` list of typed context IDs; an empty
retrieval context matches global claims only. The ordinary product currently
exposes only projects that are bound to real chat workspaces. Activity, place,
person, and legacy time identities remain internal until each has an equally
trustworthy user-selectable registry. Retrieval resolves the current context once
at the shared entry point without an LLM or network request. A durably bound
workspace is authoritative for the project dimension; a project name mentioned
in ordinary message text cannot switch recall away from that workspace. Text
aliases are considered only when no trusted workspace is available.

Workspace identities are claimed only after chat persistence commits a real
workspace association. Listing or reading workspaces never creates local state,
and an unclaimed or unreadable workspace remains global rather than receiving an
invented project scope. Copies, path reuse, and ordinary session path changes get
new identities even when the old path has disappeared; the runtime does not infer
that a move occurred from filesystem state alone. A future move operation may
preserve identity only when the user expresses that intent explicitly.

Corrections that change or remove content inherit the exact scope of the source
claim. Only `scope_refinement` may choose a different scope, and it preserves the
claim itself rather than combining a content edit with a scope change. The service rejects
unchanged replacements, unchanged refinements, unknown replacement fields, and
caller-supplied governance identities. Relationships with identical subject,
predicate, and object values may coexist in different project scopes; conflict
resolution, replay protection, correction history, and revert eligibility are
evaluated independently in each scope.

Relationship corrections use the graph's conflict rules within that exact
scope. Every relationship suppressed by a correction is recorded with the
state it had immediately before suppression. Revert restores only effects that
are still owned by that correction, so new evidence written while the
correction is active is preserved. A future-dated correction leaves current
relationships untouched until its effective time, applies all conflict effects
atomically when it activates, and retains evidence that was waiting before the
transition. Periodic recovery applies any activation missed while the runtime
was offline. Existing databases reconstruct missing conflict ownership in
historical order so a chain of corrections can still be reverted one step at a
time. Because legacy L3 dependency records may be incomplete, that one-time
reconciliation invalidates every registered L3 insight for an affected subject
and queues a rebuild; normal runtime corrections remain scoped to exact
dependencies. User-authoritative relationships and future-dated segments are
exempt from automatic stale-record cleanup.

When relationship identities or conflict rules change, stored relationships,
corrections, versions, and recorded correction effects are updated together.
Changing a conflict rule also converges existing relationships immediately. If
that convergence would leave more than one distinct active user-authoritative
relationship in the same conflict set, the rule update is rejected as a whole.

Legacy free-text scopes are migrated to isolated identities, and malformed
legacy scopes must never be widened to global memory. When relationship identity
changes during migration or entity maintenance, every correction, version,
dependency, and derived reference must move with it. If legacy aliases collapse
multiple current claims into one scope, the migration chooses one current winner,
retires incompatible rules, and invalidates derived views for rebuilding rather
than publishing stale references.

Entity catalog merges and ghost-identity repair follow the same governance rule
for both assertions and relationships. Rekeying moves immutable versions,
correction targets and replacements, conflict effects, forget rules, complete
evidence ledgers, and derivation dependencies with the surviving identity; it
does not merely rewrite the current graph row. Forgotten evidence is filtered
before colliding records are combined. Existing snapshots for both identities
are removed inside the rekey transaction and the survivor is rebuilt afterward,
so a failed refresh leaves no stale pre-merge portrait visible.

Identity maintenance keeps relationship and assertion rewrites as separate
connection-scoped operations. The relationship coordinator owns graph identity,
relationship versions, conflict effects, and relationship-shaped derived
references. The assertion coordinator owns assertion slots, assertion
collisions, assertion correction payloads, and snapshot invalidation. They share
only the established correction-governance primitives; neither is a generic
claim-rewrite framework. The caller must already hold the write transaction,
and the coordinators never commit or roll back it themselves. This makes an
entity merge, ghost repair, or predicate consolidation one atomic unit:
failure restores the complete pre-rekey state, while repeating a completed
rewrite converges on the same surviving identity without duplicating evidence.

One exception keeps a rejected duplicate from contaminating an independent
survivor. If a correction removed a claim without a replacement and identity
repair later proves that rejected branch identical to a separately supported
current claim, the old correction is resolved as no longer distinguishable and
its active rules are disabled. Evidence from the rejected branch remains on its
old claim identity; it is not moved into the survivor's evidence ledger or
reintroduced by later deletion recovery. Public history presents this outcome
as resolved by the merge rather than as an ordinary user revert.

If independently corrected identities collapse into the same assertion or
relationship slot, their pre-merge undo lineages are no longer assumed to be
interchangeable. Only an explicit forward handoff such as `A -> B -> C` joins
two corrections into one undo lineage. Multiple disconnected lineages in the
same scope are kept visible but marked non-revertible; databases upgrading with
an existing collision receive the same durable protection. The user can still
correct the surviving current claim. This block survives restarts and identity
maintenance retries, so an old revert cannot silently overwrite the winner
chosen by the merge.

The same protection applies when a correction replacement converges on an
independently supported current claim in the original slot and scope: the
correction remains effective, but its old revert is durably blocked because
restoring the former value would displace independent evidence. A
`scope_refinement` whose original and replacement scopes remain distinct is not
blocked by this rule and can still be reverted safely.

When the same relationship becomes true again after an intervening state, it
reuses the relationship identity but starts a new, non-overlapping validity
segment. Immutable snapshots retain every segment, and later evidence can update
only the segment whose validity interval covers when that evidence was observed.
Reverting a correction restores evidence from the matching segment without
mixing evidence from a later recurrence.

A correction by itself preserves raw L1 evidence for audit and narrative
history, but that evidence does not bypass the correction. Explicit source
deletion follows the stronger cross-layer deletion rules above. For
fact-authoritative modes, an L1 event that
supports an active assertion or relationship correction is removed before
answer fusion and before structured totals are calculated. If the correction
index cannot be read, fact recall fails closed instead of returning possibly
rejected evidence. `event_stream`, episode, and experience modes may retain the
event as a historical record and mark it as later corrected; prompt rendering
must not restate it as current truth. This policy is intentionally event-level
until span-level evidence atoms have a measured need and a verifiable parent
contract.

Correction-sensitive derived views use a monotonically increasing subject
revision. Snapshots, profile projections, portrait projections, and dependent L3
insights are hidden as soon as their source revision is stale, then rebuilt by
durable retryable jobs. A view fenced by a known revision or clear-generation
change remains hidden, while an unrelated transient dependency failure may retain
the last successfully fenced Profile or Portrait as explicitly stale instead of
overwriting it with an empty result. A future-dated situation change stores its time
range immediately but advances the subject revision only when that time arrives.
The pending transition is durable and idempotent; the scheduler keeps the earliest
activation time while the periodic sweep recovers missed wakeups. Page-originated
corrections also create a durable, generic L1 audit marker with
`cognition_eligible=false`; a chat-originated correction points to its existing
L1 source event instead. The audit marker records only the correction identity
and action type. It does not copy the previous value, replacement, or free-text
reason, and its `audit_only` retrieval scope keeps it out of ordinary L1 lists,
timeline context, stories, and recall. Sensitive details are available only from
the governed correction-history API. If a related source or claim is forgotten,
that API removes affected versions, redacts affected values and reasons, and
returns `can_revert=false`. Source-event deletion also forgets any audit marker
that was derived from the deleted source evidence; a generic marker for the
forget action itself may remain because it contains no forgotten content.

Privacy scope (`privacy_scope`) is a day-1 architecture concern carried on every durable L2 object (assertions, edges, facets, episodes, experiences).

The default memory UI starts from a product overview rather than a raw layer
workbench. That overview aggregates L1 source coverage, L2 reviewable
assertions, L3 reviewable insights, storage usage, and recent memory formation.
Its compact summary shows current memory totals plus live same-day formation
deltas from L1 event creation, L2 assertion inference, and L3 summary creation;
storage remains a current usage value until a durable daily snapshot exists.
A dedicated Sources page expands the overview's source coverage with a
first-source onboarding state, then a user-facing ledger with per-source status,
recent intake, and full-page source detail views for recent raw items and source
actions. Raw L1 events, L2 graph
inspection, and L4 skill memory remain available from Manage as
operator/developer surfaces, not as the default mental model for ordinary
memory review.
The memory story feed is a backend-assembled read model over L3 insight and
temporal summary records. The API owns story grouping, summary-page visibility,
featured ordering hints, display timestamps, preview text, detail lead text, and
summary statistics. Frontend story surfaces may translate labels and choose
visual treatment, but they should not reclassify raw `summary_category` values
or recompute story-feed statistics from the raw records. Story previews must
remain concise even for legacy summaries without `essence_prose`; full summary
content belongs to the detail reading surface rather than the feed card.
The About You page presents the user-facing self portrait as an ordered
world model: first a grouped view of identity, long-running projects,
preferences, and working style; then reviewable items that need
user judgment; then recent state observations. Personal-profile fields are
strong inputs to this portrait, not a second visible portrait surface. It should
translate L2 assertion metadata into readable groups and review actions instead
of exposing raw assertion/family/status names as primary UI copy.
During cold start, the page must not render the four empty portrait groups or a
zero-count world shell. It should explain what will form here and provide direct
paths to conversation and source connection. Once understanding exists, only
groups with user-facing content are shown; spacing and typography establish the
hierarchy without a synthetic root card or nested world-map containers.
`GET /api/memory/portrait/self` returns this as a backend-assembled `self_view`
with `world`, `review`, and `recent` sections. The legacy flat `observations`
list is diagnostic support for the endpoint; page classification belongs in the
backend read model. The frontend may translate section, temporary-signal, and
source labels, but it should not infer grouping from keywords, source names, or
raw text.
When a materialized `user_portrait_projection` exists, the endpoint may return
that page model directly only when it is fresh; otherwise it must rebuild it
from current profile and assertion inputs. If no materialized row exists, it
assembles the same shape from the current profile projection and assertion set.
The fallback path must use the same
portrait qualification policy as the materialized projection so weak passive
assertions do not leak into the page before the cache is refreshed.
The chat portrait rail is a separate surface: it may retrieve memory snippets
and render them in the active persona's voice for the current conversation, but
that presentation is not the product-facing self portrait and must not own
memory-layer projection rules.

### L3 — Reflection and Summaries

`L3` stores time-windowed or topic-compressed reflective memory.

Its purpose is to reduce cost for:

- Historical review
- Periodic summarization
- Pattern recognition
- Reflection-oriented prompt assembly

Typical outputs:

- Temporal summaries
- Topic summaries
- State-change summaries
- Trend-shift summaries
- Task reflections

`L3` should be more readable and searchable than raw `L1` event sequences, while always being traceable back to supporting evidence events.

`L3` vector index uses `summary` as the parent object and `chunk` as the retrieval unit.

#### Insight Generation Contract

Insight-style L3 records are produced from structured lower-layer outcomes, not from an open-ended LLM decision. The owning service first builds a typed candidate from L2 reconciliation, contradiction, trend, or task-outcome packets. A deterministic gate decides whether the candidate has user-facing value; only accepted candidates are persisted.

The gate must be rule-based and inspect structured state such as:

- assertion lifecycle status (`tentative`, `corroborated`, `stable`, `contradicted`, `superseded`)
- normalized trait/value changes
- evidence event count and time span
- insight category policy, such as state change vs. trend shift

LLMs may rewrite accepted insight content for readability, but must not decide whether an insight exists, what confidence/status it has, or which evidence supports it. Template text must remain available as a fallback.

Each recurring insight carries a stable `insight_key`. State-change and trend-shift keys are scoped to the entity and reviewable trait group, not to every currently observed value or every exact low-level trait in the packet, so an accumulating preference signal updates one reviewable card instead of creating a new row every time another value or adjacent preference facet appears. Writes are upserts by that key: repeated reconciliation of the same state updates evidence metadata or returns the existing record instead of creating another row. User-review fields such as `review_state` and `insight_metadata` belong to the L3 record so the frontend can present insights as reviewable cards rather than raw debug logs.

Insight-style L3 records also register the exact L2 assertions or relationships
they depend on. A correction immediately marks only those dependent insights
stale and removes them from list, search, and embedding rebuild inputs. The
correction worker rebuilds an insight from the new current claim when possible,
or retires it when no valid replacement exists. Temporal summaries, episodes,
experiences, and unrelated insights are not rewritten merely because one L2
interpretation changed.

Initial insight publication, correction rebuild, and retirement all validate
the complete dependency set and the memory-clear generation in the same write
transaction. A late job may publish only if the stale record it scanned is still
the same record version. Replacing or retiring an insight detaches its old search
and vector entries before the new state becomes visible; embedding computation
may run outside the mutation lock, but its result is written only after the
parent content and version are checked again. Pre-governance insights whose
evidence cannot be verified stay quarantined rather than being treated as
current merely because they predate the dependency ledger.

Trend-shift insights are reserved for durable long-span signals. Sparse or volatile outcomes should remain L2 evidence and should not become L3 trend cards until they have enough evidence, enough elapsed time, and a non-volatile stability kind.

#### Temporal Summary Generation

Temporal L3 summaries are generated by the host memory runtime, not by individual plugins. The runtime scheduler currently registers core interval targets for `hour`, `day`, `week`, and `month`. Source-specific activity schedules are registered from merged plugin summary profiles when their requested windows are in the scheduler interval catalog, and they may request a narrower `source_filter`; they still write normal L3 summary records through the same store. The temporal summary store and LLM service also understand `quarter` and `year` summary categories for explicit callers or future schedules that provide appropriate windows.

L3 summary generation and L3 retention maintenance are separate scheduler targets. `memory_l3_summary` creates or updates summaries; `memory_l3_maintenance` ages out old summaries according to the configured memory history behavior.

L3 does not expose a generic summary-interval setting. Core generation cadence belongs to the scheduler period catalog; `maintenance_interval_seconds` controls retention cleanup only. Settings API requests reject unknown L3 fields instead of silently accepting ineffective options.

There is no separate digest layer or digest-specific scheduler. A digest-style view is just a temporal L3 summary with a time window, evidence links, and normal L3 retrieval behavior.

L3 summary LLM calls use the optional `memory_summarizer` runtime scenario. This scenario is intentionally not a required normal-settings choice: when it is absent, the scenario pool falls back to `core`, so users are not forced to understand or configure a separate summary model. Operators may still define `memory_summarizer` explicitly in configuration when summary generation should use a different model profile.

Temporal LLM generation is split into two calls over the same stable evidence-prefix prompt. The first call produces the user-facing detail body and is the required product output. The second call reuses the same evidence prefix plus the accepted body to extract a short `essence_prose` preview and optional structured fields such as topics, entities, sentiment, and change/pattern metadata. If the structured extraction fails, the accepted body still writes as a `temporal-llm` summary with empty structured fields and no preview. Rule-backed summaries remain an internal fallback and retry/debug lower bound; they should not be treated as normal Summary-page content unless a UI-specific quality gate explicitly allows them.

The same product contract applies to thematic topic summaries and episodic/experience summaries: user-facing prose is generated first and structured fields are extracted afterward. A failed structure pass must not discard accepted prose. L3 insight renderers also apply a display-quality gate; L2 natural summaries that still look like raw machine signals are ignored and the renderer falls back to structured family/value text or skips the insight.

Generation starts from `L1` facts that are eligible for cognition and excludes runtime telemetry and disposable events. The store does not load every matching event into the prompt. Instead, [evidence_selector.py](../backend/src/magi/memory/l3/evidence_selector.py) performs source-aware compaction:

1. Query lightweight per-source counts for the requested time window.
2. Allocate a bounded raw-evidence quota across sources using a per-source floor plus square-root weighted remainder.
3. Fetch a larger per-source feature pool for plugin-local aggregation.
4. Select representative raw events using a mix of recency, importance, and time spread.
5. Attach coverage metadata to the evidence pack so the model knows what was selected and what was omitted.

The default policy is `source_aware_compaction_v1`:

- raw events selected for the LLM evidence pack: up to `120`
- feature events exposed to each source plugin: up to `240` per source
- quota strategy: `per_source_floor_plus_sqrt_weighted_remainder`
- representative strategy: `recent_plus_importance_plus_time_spread`

The temporal evidence pack records:

- `window_event_count` — total eligible L1 events in the window
- `source_event_count` — selected raw events in the prompt evidence pack
- `omitted_event_count` — eligible events not represented as raw prompt events
- `source_distribution` — per-source total, selected, feature-pool, omission, and importance stats
- `selection_policy` — policy version and quota parameters
- `previous_period_summaries` — compact same-category summaries ending before this window, used only for comparison
- `child_period_summaries` — compact lower-granularity summaries inside this window, such as week summaries inside a month

This metadata is part of the prompt contract. The temporal summarizer must treat selected raw events as representative evidence, not as an exhaustive list of everything that happened in the window.

Previous and child period summaries are timeline context, not new evidence. They may help the model describe drift, continuity, or phase changes, but current-window facts must still be grounded in the current evidence pack. By default, `hour` and `day` summaries receive one previous same-period summary; `week` and `month` summaries receive up to three previous same-period summaries; `quarter` and `year` summaries receive up to two previous same-period summaries. Child context uses the next lower timeline scale: day summaries may include hour summaries, week summaries may include day summaries, month summaries may include week summaries, quarter summaries may include month summaries, and year summaries may include quarter summaries.

Temporal summary generation must honor the user's configured language preference even when running from scheduler contexts that do not carry an HTTP language header. The temporal summarizer passes the target language in both system and user prompts and rejects model outputs whose user-facing fields clearly violate the target language, falling back to deterministic rule text rather than storing mixed-language summaries.

Temporal LLM calls use period-specific generation profiles by default:

- `hour` windows get up to `180` seconds, keep thinking disabled, and focus on local sequence, immediate context, and short-lived shifts.
- `day` windows get up to `300` seconds, enable thinking, and focus on day blocks, attention shifts, explicit decisions, and repeated constraints.
- `week` windows get up to `600` seconds, enable thinking, and focus on durable themes, recurring interests, cross-source patterns, and notable changes.
- `month` windows get up to `600` seconds, enable thinking, and focus on cross-week themes, stage changes, sustained interests, project progress, and unusually frequent activities.
- `quarter` windows get up to `600` seconds, enable thinking, and focus on durable projects, decisions, constraints, source-specific habits, and cross-month phase changes.
- `year` windows get up to `600` seconds, enable thinking, and focus on year-scale durable themes, long-running projects, decisions, constraints, recurring interests, and unusually frequent activities.

The legacy flat `temporal_llm_timeout_seconds` setting remains an explicit override for testing or operator tuning; the previous default value `3.0` is treated as "use the period profile" so it does not force production summaries through a three-second budget.

Rule fallback is a user-facing lower bound, not a debug dump. It should describe the dominant sources or themes first, then add compact source-specific signals such as focus domains or repeated sites when available. Raw event counts, internal event type names, and compression counters belong in summary metadata rather than in the summary body unless they materially change interpretation.

Temporal summaries should remain compact, but they must not be over-compressed into a single generic paragraph for `day`, `week`, or `month` windows. The generated `content` field should preserve period-appropriate concrete anchors such as projects, tools, services, domains, media titles, decisions, and unresolved follow-up threads. The optional `essence_prose` field is the card-level preview for product surfaces: it should quickly answer what this period was about without replacing the richer `content`. The structured `change_and_pattern` payload may include `timeline`, `source_signals`, `decisions_and_actions`, `changes`, `patterns`, and `open_threads` arrays. These structured fields are part of the retrieval surface: L3 FTS and vector text include both the readable content and the structured summary fields so later recall can recover details even when the visible recap stays concise.

#### Plugin Temporal Features

Plugins may provide compact source-local features for temporal summaries through `build_temporal_summary_features`. The host passes the plugin a bounded event pool and a `TemporalSummaryFeatureBudget` that reports total, available, selected, and omitted counts for that source.

Plugin outputs should be structured evidence, not final cross-source summaries. Good outputs include:

- top domains, apps, artists, calendars, repositories, tags, or places
- coverage counts and coverage ratio
- time buckets or source-native session counts
- representative event ids
- short source-local `summary_lines` grounded in the provided event pool

The host attaches returned features to `TemporalEvidencePack.plugin_summary_features` and still performs the final L3 generation centrally. This keeps source-specific aggregation close to the source while preserving one cross-source summary model, one L3 persistence contract, and one retrieval surface.

Important boundary: if a source's events are stored in L1 with `cognition_eligible=false`, they will not participate in generic L3 temporal generation unless the selection policy or the source's memory policy is explicitly changed. A plugin hook alone does not override event admission policy.

### L4 — Procedural Memory

`L4` distills "how to do things better next time" execution experience.

It answers:

- What approach usually works best here?
- Which workflows frequently fail?
- Which workflow should be prioritized next time?
- Which tools or strategies should be avoided?

`L4` does not recount historical facts; it distills future execution guidelines.

Authoritative tool execution truth lives in `runtime_trace.trace_tools`. Exact tool attempts, provider challenges, errors, latency, and success counts should be read from runtime trace when a surface needs auditable execution facts. The current L4 store also maintains denormalized procedural rollups such as `total_attempts`, `success_rate`, bounded `l4_execution_traces`, circuit-breaker state, strategy hints, and context affinity for skill learning and fast advisory reads. Treat those L4 fields as cached procedural overlays that must be reconcilable with runtime trace, not as the canonical source for execution-history inspection.

Every source-backed L4 update records an unbounded skill-to-event link in
addition to the bounded source list on the visible skill row. Because a learned
aggregate cannot safely subtract one contributor after the fact, forgetting any
linked source conservatively retires the affected skill and removes its L4
search, vector, and trace projections. The durable source tombstone prevents the
same event from recreating or updating procedural state. This does not rewrite
the separate authoritative runtime trace; retention and deletion of runtime
execution truth remain governed by the runtime-trace domain.

`L4` vector index uses `skill` as the parent object and `chunk` as the retrieval unit.

`L1` / `L2` / `L3` / `L4` vector write pipelines share a common embedding pipeline; each layer defines only its own text builder, chunk strategy, parent-table status writeback, and retrieval collapse logic.

Examples:

- Common workflow templates
- Circuit-breaker states for unstable tools
- Successful strategy templates for task categories
- Context-dependent execution preferences
- Explicit task-handling preferences stated by the user

---

## Event Contract and Routing

All data entering durable memory is normalized into the `MemoryEvent` defined in [backend/src/magi/memory/event_contracts.py](../backend/src/magi/memory/event_contracts.py).

A fully normalized durable `MemoryEvent` carries these required fields, either supplied by the producer or derived during normalization:

- `event_id`
- `correlation_id`
- `event_type`
- `source`
- `timestamp`
- `created_at`
- `content`
- `memory_domain`
- `ingest_target`
- `cognition_eligible`
- `tom_depth`
- `retention_class`
- `author_type`
- `content_type`
- `importance_score`
- `level`

Optional identity, payload, embedding, and observability fields include:

- `source_item_id`, `idempotency_key`, `media_path`, `metadata_json`
- `session_id`, `turn_id`, `user_id`, `task_id`
- `embedding_status`, `embedding_profile_id`
- `causation_id`, `trace_id`, `span_id`, `parent_span_id`

### memory_domain

Expresses what semantic category the event belongs to.

Canonical domains:

- `user_authored`
- `interaction`
- `external_activity`
- `runtime_telemetry`
- `system_control`

This is the foundational field for isolating user experience, external activity, and runtime noise.

### ingest_target

Expresses where the event should initially land.

Canonical targets:

- `runtime_only`
- `l1_only`

This separates runtime-only signals from durable memory facts. L0 attention is
derived after accepted conversation turns and is not an event-ingest target.

### cognition_eligible

A coarse-grained boolean switch controlling whether an event can enter higher-level cognition.

- `true` — Allowed to participate in cognition and summarization
- `false` — Can enter `L1` but defaults to not participating in cognition

Durable storage and higher-level reasoning are not the same thing.

### retention_class

Expresses lifecycle policy:

- `permanent`
- `compressible`
- `disposable`

Retention policy must be an explicit contract, not implicit post-processing.

---

## Event Identity Rules

`L1` explicitly distinguishes internal primary key, stable external reference, source-side identity, and business idempotency key. These are strong constraints.

1. **`id`** — SQLite internal primary key. Used only for internal joins, sorting, and local relationship efficiency.

2. **`event_id`** — Stable external event identifier. Used for timeline references, `L2`/`L3` evidence backlinks, API responses, and logging.

3. **`source_item_id`** — Source-side item identity. Represents the producer's own business item identifier.

4. **`idempotency_key`** — Business idempotency key. Answers "is this the same business event?", not "is this the same database row?".

### L1 Uniqueness Rule

When `idempotency_key` is present, `L1` deduplicates by:

```sql
CREATE UNIQUE INDEX idx_fact_events_business_idempotency
  ON fact_events(source, event_type, idempotency_key);
```

This means:

- `event_id` is not the business dedup key
- `source_item_id` does not default to the business dedup key
- Internal `id` must never be reused as `event_id`

### Concrete Example

A Chrome history burst might look like:

- `id = 128431`
- `event_id = "evt_01JQ..."`
- `source = "chrome_history"`
- `event_type = "SENSOR_EVENT"`
- `source_item_id = "181979-181982"`
- `idempotency_key = "default:181979-181982"`

The system uses:

- `event_id` as the cross-layer stable reference
- `id` for internal joins
- `source_item_id` to display or echo source-side identity
- `(source, event_type, idempotency_key)` for business idempotency

---

## L1 Fact Event Storage

The `L1` canonical store is at [backend/src/magi/memory/l1/event_store.py](../backend/src/magi/memory/l1/event_store.py).

The `fact_events` core schema:

```sql
CREATE TABLE fact_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    event_id TEXT NOT NULL UNIQUE,
    timestamp REAL NOT NULL,
    created_at REAL NOT NULL,
    event_type TEXT NOT NULL,
    source TEXT NOT NULL,
    source_item_id TEXT,
    idempotency_key TEXT,
    memory_domain INTEGER NOT NULL,
    cognition_eligible INTEGER NOT NULL DEFAULT 0,
    retention_class INTEGER NOT NULL DEFAULT 2,
    session_id TEXT,
    turn_id TEXT,
    session_seq INTEGER,
    user_id TEXT,
    content TEXT NOT NULL,
    author_type INTEGER NOT NULL,
    content_type INTEGER NOT NULL,
    importance_score REAL NOT NULL DEFAULT 0.5,
    media_path TEXT,
    metadata_json TEXT,
    deleted_at REAL,
    evidence_status INTEGER NOT NULL DEFAULT 1,
    evidence_class INTEGER NOT NULL DEFAULT 1,
    evidence_rule_version INTEGER NOT NULL DEFAULT 1,
    l1_retrieval_scope INTEGER NOT NULL DEFAULT 1
);

CREATE UNIQUE INDEX idx_fact_events_business_idempotency
    ON fact_events(source, event_type, idempotency_key);

CREATE TABLE l1_session_sequences (
    session_id TEXT PRIMARY KEY,
    next_seq INTEGER NOT NULL DEFAULT 0,
    updated_at REAL NOT NULL DEFAULT 0
);

CREATE TABLE l1_event_embedding_state (
    event_id TEXT PRIMARY KEY,
    embedding_status INTEGER NOT NULL DEFAULT 1,
    embedding_profile_id TEXT,
    embedding_chunk_count INTEGER NOT NULL DEFAULT 0,
    last_embedded_at REAL,
    updated_at REAL NOT NULL
);
```

Key notes:

- `event_id` is the external stable reference key
- `id` is the internal relationship key
- `session_seq` is the stable event order within a session; local context windows, evidence bundles, and same-session L2 batches should use it instead of depending on `turn_id` naming conventions or assuming provider timestamps are monotonic
- `metadata_json` carries structured event payloads
- `author_type`, `content_type`, evidence fields, retrieval scope, and embedding status are stored as compact integer codes and decoded to labels at runtime/API boundaries
- Canonical `l1_retrieval_scope` labels are `none`, `fact_authoritative`, `conversation_only`, `audit_only`, and `source_backlink_only`
- Evidence columns describe L1 retrieval authority for the event; L2 graph/assertion policy remains a runtime decision and is not duplicated into `fact_events`
- Unknown or failed evidence annotations default to `l1_retrieval_scope='none'`
- Versioned evidence annotations can be backfilled in place without rewriting raw event content
- Embedding observation fields live in `l1_event_embedding_state`; `fact_events` remains the durable event truth table
- Durable events support soft deletion via `deleted_at`
- Schema evolution is migration-backed for current local databases; very old pre-Alembic development databases may still need a rebuild

---

## How Data Enters the Memory System

Producers are diverse, but all converge on the same memory contract.

### Chat Projection

Chat truth is first written to `chat.db`. A subset is then projected as `L1` canonical facts. This projection is intentionally lossy: it retains what memory needs, not a full transcript copy.

### Sensors and Plugins

Sensors run in the awareness layer and produce `SensorOutput`. The `SensorIngestionGateway` projects these outputs into memory.

For external activity sources, `SensorOutput` is not the final `L1` string. It is a source-truth envelope with:

- `activity`: structured source/action semantics owned by the plugin
- `narration`: factual body/title owned by the plugin

The host runtime then materializes that truth into durable memory projections:

- `content`: canonical persisted `L1` text
- `metadata_json.activity`: minimal stable retrieval facets (`source_code`, `action_code`, optional `object_code`, optional `qualifiers`)
- `metadata_json.projection`: host-owned projection metadata such as `renderer_version` and optional `embedding_head`

This keeps external activity memory consistent across plugins while avoiding per-plugin free-form `L1` sentence formats.

Gateway-side normalization rules:

- External sensor events are written as durable memory with a stable owner `user_id` taken from `SensorOutput.provenance`, then `domain_payload`, and finally `identity.defaults.CANONICAL_LOCAL_USER` as fallback.
- External sensor events remain session-independent by default: `session_id` and `turn_id` are not inherited from the current chat runtime.
- The host, not the plugin, decides the final `L1` sentence shape and embedding text shape for external activity events.

This is the primary path for:

- Browser history
- App usage
- Terminal / Git activity
- Other external activity plugins

### Runtime-Generated Events

Some runtime events may be normalized into memory when worth auditing or future learning. But runtime observations and durable memory are two systems. Default principle: high-frequency execution telemetry does not enter long-term memory.

---

## Retrieval and Prompt Integration

The memory layer handles recall, retrieval, ranking, and cross-layer evidence organization. The context layer handles prompt shaping and final injection strategy.

This is a deliberate boundary:

- Memory decides "what was found"
- Context decides "which results should actually enter the prompt"

Not all retrievable memories should be implicitly injected into ordinary conversation.

### Unified Retrieval Pipeline

The `HybridRetrievalService` orchestrates cross-layer retrieval with mode-aware behavior:

- Each `query_mode` defines a `QueryModePlan` with layer weight profiles
- Each fact-like mode defines which L1 evidence scopes are authoritative for that mode; BM25, vector, and keyword retrieval must apply those scopes before topK whenever scoped indexes are available
- Fact-authoritative L1 candidates are also checked against active correction evidence before fusion. Missing correction governance, lookup failure, and missing event identity fail closed. Historical event, episode, and experience modes retain the record with explicit historical semantics instead of silently presenting it as current.
- Answer-facing L2 candidates always cross the governed current/history/scope view before ranking. Vector and graph expansion may propose candidates, but neither may publish raw lifecycle rows.
- Mode-adaptive RRF adjusts per-layer weights based on the query mode
- Evidence assemblers shape raw retrieval results into per-mode evidence formats (fact cards, state cards, episode bundles, comparison frames, grouped lists)
- Reducers produce final answering material (span selection, latest version, narrative, anchor comparison, enumeration)
- `memory_query` does not inherit the current chat session unless the caller explicitly provides `session_id`
- Unconstrained `L2` lookups must not degrade into a global "recent relationships" / "recent assertions" scan
- LLM-facing memory tool payloads should keep human-readable findings only; opaque ids stay in debug/observability channels rather than prompt context
- the answer-facing `historical_recall` contract may additionally expose compact `entity_refs` and `asset_refs` for reply-turn continuity and source-owned follow-up resolution, but raw local paths remain outside prompt context
- plugins may optionally enrich these refs through a recall-artifact projection hook keyed by `source_type`; memory still owns the final query contract and chat still owns attachment import/display
- For fact-like recall modes, answer-facing projection treats chat-derived assistant freeform replies and chat-derived user question prompts as non-authoritative artifacts. This projection hygiene is a last-mile defense; the primary defense is authoritative evidence scoping before retrieval ranking. These artifacts may remain in `L1` for audit or conversation replay, but they must not become factual `historical_recall.findings` unless the caller explicitly asks for chat-source evidence or uses a conversation-recall mode.
- Generic topK recall is representative evidence, not an exhaustive count surface. Queries that ask for counts, totals, or full enumeration need an explicit coverage contract. When a source-backed structured recall provider can answer exhaustively, it must set `coverage.can_claim_total=true`; otherwise downstream prompts and UI must treat returned findings as samples, avoid total-count claims, and keep qualitative summaries bounded to patterns directly supported by the returned findings instead of inferring broader habits, preferences, diversity, or frequency.
- Structured source-facet recall applies the same correction evidence blocklist before computing totals or claiming coverage. The answer path has no live L1 co-occurrence fallback that can synthesize ungoverned relationship claims.

Layer contributions:

- `L1` — Primary event fact recall
- `L2` — Structured evidence (graph edges, assertions, episodes, entity facets)
- `L3` — Compressed summary context
- `L4` — Execution experience and reusable strategies

### Prompt Strategy

Current implicit injection remains conservative:

- Only the bounded active subset of `L0` that passes confidence and salience
  thresholds is default implicit context
- Background attention may be included as labelled reference-only context when
  its summary or linked identity matches the current message; prompt selection
  does not reactivate its stored lifecycle state
- L0 may help shape an explicit long-term-memory query, but L0 is not searched
  through the L1-L4 retrieval index
- Higher-layer memories require explicit justification for injection
- Explicit historical recall and implicit prompt injection are separate decisions

This prevents stale, weakly-relevant, or noisy memories from being over-injected into ordinary conversation.

---

## Timeline Integration

The timeline module (`backend/src/magi/timeline/`) is a **read model** that consumes memory products. It does not own canonical truth.

Key integration points:

- **Episode-aware clustering**: At `day` and `week` scales, the timeline cluster builder prefers durable L2 episodes over transient re-clustering. Events not covered by any episode are clustered transiently to fill gaps. At `hour` and `month` scales, transient clustering is used exclusively.
- **State bands**: The state band builder derives `valence`, `stress_level`, and `engagement` from L3 summaries, L2 assertions, and ToM snapshots. Assertions with `superseded`, `archived`, `expired`, or `user_rejected` status are excluded.
- **State transitions**: The viewport builder extracts state transitions from superseded assertion chains, producing `{trait_name, old_value, new_value, changed_at}` records.
- **Episode context bundles**: When an anchor has an `episode_id`, the context bundle builder loads member events from `episode_events` instead of scanning by `representative_event_ids`. Bundles include `user_label` and `user_note`.
- **Viewport payload**: At `day`/`week` scales, the viewport includes `episodes`, `state_transitions`, `state_bands`, `clusters`, and `reflections`.
- **Activity previews**: L1 metadata may carry an `activity_snapshot` block for
  source title, summary, tags, entities, provenance, and asset references. This
  is a neutral memory snapshot; timeline owns the final read-model payload and
  should not require memory metadata to store a `timeline`-named structure.

---

## Retention, Compression, and Deletion

Retention policies are defined per event type and purpose, not as a global rule.

### General Rules

- User-authored durable memory defaults to stronger retention
- External activity is typically `compressible`
- Runtime telemetry is strictly limited or excluded by default
- Summaries and procedural memory must retain evidence backlink capability
- L1 retention uses `agent.memory.l1.retention_days`; L3 summary retention uses
  `agent.memory.l3.retention_days`. The legacy top-level
  `agent.memory.retention_days` is not the owner of scheduled L1/L3 cleanup.
- The settings UI exposes the layer-specific retention knobs that scheduled
  cleanup actually reads: L1 event retention, L3 summary retention, and L4
  inactive-skill retention.
- L1 cleanup may only delete compressible events that are already covered by L3
  summaries and are not still referenced by active L2 episodes, experiences,
  experience seeds, graph edges, assertions, or entity facets.
- L3 cleanup may age out ordinary hot-path summaries, but it must preserve
  reviewable/user-confirmed insights and episodic summaries attached to stable
  L2 episode or experience objects.

### Destructive Full-Clear Boundary

A full user-memory clear is one runtime-wide boundary, not a collection of
independent table deletes.

- Before the desktop asks the backend to mutate data, the desktop host writes
  and syncs a content-free pending marker under `~/.magi/runtime/`. The marker
  contains only a format version and an opaque, unique, content-free
  transaction ID. The backend records that same ID as pending in
  `message_queue.db` before the first
  destructive step. If either process exits at any later point, the host
  forwards the same ID on the next launch and the backend adopts it before
  recovering any previously claimed command. A running backend is restarted
  before replay so it cannot bypass this startup fence. A backend pending row
  without its matching desktop owner marker fails startup instead of exposing
  a partially recovered product.
- Marker publication uses a transaction-named temporary file. If a crash
  leaves exactly one temporary marker with a valid content-free transaction
  name, the host can reconstruct its canonical marker even when the payload is
  empty or only partly written. Invalid names, multiple temporary markers, or
  a complete payload that conflicts with its filename fail closed.
- User-message dispatch holds a shared ingress boundary from attachment
  preparation through chat persistence, L1 projection, runtime-command enqueue,
  and the successful dispatch result.
- Full clear takes the matching exclusive ingress boundary before it takes the
  memory store's exclusive operation boundary. This lock order is mandatory.
- After active chat and embedding work is stopped, clear advances a durable
  clear generation shared by `USER_MESSAGE`, `SENSOR_SYNC`, and
  `SENSOR_STATE_FLUSH`. Every command of those types present at that boundary
  is deleted from the runtime queue in every state, including claimed,
  completed, and failed rows. Runtime-only configuration and channel refresh
  commands are preserved.
- Runtime-command processing holds a shared full-clear boundary from claim
  through handler completion and acknowledgement or requeue. Full clear takes
  the exclusive side first, stops new claims, and waits for in-flight message,
  manual sensor-sync, and sensor-state-flush handlers to exit. Sensor command
  enqueue uses the same boundary, so an enqueue racing clear is either deleted
  as pre-clear work or admitted afterward with the new generation. A stale
  manual backfill or state flush can therefore neither run nor recreate user
  data after clear.
- The generation travels with the command through the local message bus,
  `SensorHub`, router fact, and task-agent admission. It also remains attached to
  user-derived Explore orchestration state, worker updates, and the final
  dossier returned to Chat. A missing required generation or any mismatch is
  rejected once generation governance is active, which prevents a pre-clear
  message or descendant result already held by an in-memory queue from
  recreating chat or memory after clear completes.
- Separately, the in-process message bus snapshots the current process-local
  memory epoch onto every event when the publisher hands it to the bus. Both
  event-to-memory subscribers require that reserved snapshot and pass it into
  the guarded ingestion call. Clear advances the epoch before deleting memory, so any
  pre-clear bus backlog is rejected even when its handler runs after clear.
  The bus overwrites caller-provided values, does not persist this epoch, and
  starts from the new store's epoch after process restart.
- Chat transcripts, session summaries, session-bound runtime traces,
  orchestration payloads, channel conversation mappings, delivery receipts,
  channel notification cursors, queued proactive outreach and its delivery
  log, L0-L4 stores, manual-entry assets and location lookup caches, chat
  portrait caches, learned persona behavior/emotion/relationship state,
  pending personality-generation jobs and their generated reference material,
  plugin ingress payloads, and rebuildable memory projections are cleared
  within the same boundary. Personality generation admission stays closed until
  the clear finishes, and a cancelled pre-clear job cannot publish a late
  result. Notifications derived from memory conflicts and persisted user
  notifications are cleared with their source claims. Channel
  installation, account authentication, enablement, binding preferences, and
  persona definitions are configuration rather than remembered user content
  and are preserved.
- The request stops and removes all active `CHAT` and `EXPLORE` task-agent work
  under one admission boundary, and pauses proactive outreach and external ask
  delivery while it clears conversation-owned channel state. Only the core Chat
  instance is recreated after the boundary resumes. A late worker update cannot
  recreate Explore, and a late Explore completion cannot recreate Chat.
  Proactive external delivery and ask fanout also fail closed while the
  persistent chat clear marker exists. This keeps active replies and
  notifications from racing the cross-store cleanup.
- The same boundary seals the control transcript projector before clearing
  in-memory plan, todo, ask, and pending-permission state. Pending ask and
  permission waiters are rejected rather than resumed with stale answers.
  Control generations and identity checks invalidate operations that started
  before clear, while the existing control services reopen for new sessions
  after the boundary exits.
- Message, session, history, and full-memory deletion also open the matching
  background admission boundary before cancelling existing foreground and
  background work. The boundary rejects matching enqueue and retry until
  memory and chat-surface cleanup finishes, and waits through terminal
  background listeners before taking the final chat snapshot. Exact-message
  deletion applies that boundary to the complete logical replacement chain;
  unrelated sibling work remains admissible. A cancellation completion
  therefore cannot arrive after the transcript has already been removed and
  recreate a user-visible result.
- Full clear deletes terminal task rows, event history, and completion intents
  while global background admission remains sealed. Ordinary task dismissal
  and retention still govern this audit store outside a full clear, but a
  product-wide user-data clear leaves no task goal, result, or error behind.
- Chat clear first commits a persistent global-clear intent together with
  public transcript redaction, then removes traces and managed files, and only
  then deletes the remaining private attachment/code-delegation retry records
  and chat rows. Code-delegation cleanup removes Magi-owned logs, diffs,
  temporary worktrees, and branches but preserves changes already applied to a
  main workspace. The intent deliberately remains after `chat.db` is empty. It
  is removed only after channel conversation state and persisted orchestration
  payloads have also been cleared.
- Chat's internal recovery remains two-stage. Chat cleanup first finishes local
  transcript, trace, asset, and retry cleanup while retaining its conversation
  marker. The channel-owned step then clears channel and orchestration state
  before that marker is released.
- The desktop transaction adds a wider startup fence around that store-level
  recovery. While its marker is pending, startup constructs only the stores and
  clear owners needed to replay the complete operation. It does not restore
  claimed runtime commands, activate plugins or external channels, start the
  message bus, scheduler, sensors, background work, recovery subscribers,
  tools, skills, MCP servers, or agent/LLM execution. The clear therefore works
  even when model configuration is absent, and no pre-clear work can run before
  replay completes.
- The assistant-memory outbox worker and user-turn delivery recovery also share
  an in-process clear lifecycle tied to the durable runtime-command generation.
  A pass captures both generations before its first claim or recovery read and
  checks them around every memory publication and settlement. Full clear closes
  this lifecycle before closing the runtime-command queue, drains or invalidates
  records already held in memory, and keeps new claims and reads blocked until
  L1 and chat deletion finish. Work admitted after the boundary captures the new
  generation and proceeds normally; a record read before it cannot be stamped
  with the new generation and recreate L1 afterward.
- One-shot history import preview, confirmation, recovery, reads, and background
  persistence acquire the global memory boundary before the import service's
  own shared boundary. Full clear takes those boundaries in the same order,
  then cancels and drains every import worker under the service's exclusive
  boundary before deleting preview jobs and normalized records. A preview or
  recovery pass admitted before clear therefore finishes before deletion, and
  work waiting between background batches is canceled instead of recreating an
  import row after the shared database is empty.
- An individually deleted chat session leaves a
  `chat_cleared_session_scopes` tombstone. Session identity is compared
  case-insensitively, `chat_sessions` enforces the same case-insensitive
  uniqueness, and database triggers reject both a direct session recreation
  and late child-row writes. During a full clear, those per-session and
  per-message identifiers remain only until all old writers have drained and
  the global barrier is ready to close. Finalization then removes them and
  securely compacts the chat database and WAL; the generation barrier replaces
  an unbounded permanent list of historical user identifiers.
- The product reports success only after every backend store and plugin hook is
  clean, writers can safely resume, browser-owned retry/session state is gone,
  backend and desktop diagnostic logs are erased, and the desktop marker is
  durably removed. Any failure keeps the transaction pending, stops the normal
  runtime, blocks product interaction, and makes retry replay the same
  idempotent clear. Backend success returns its pending row to an empty `idle`
  state and securely removes the transaction ID instead of retaining a
  completion journal. Startup recovery restarts the normal runtime exactly
  once after the whole transaction finishes.
- External channel admission uses one of two mutually exclusive proofs. A
  timestamped channel supplies the provider-issued event time; local receipt or
  polling time is never accepted as that proof. A polling channel without a
  trustworthy provider time supplies a durable cursor proof for the current
  user-message clear generation. After the generation advances and before chat
  deletion begins, the host asks every running external channel to pause local
  ingress, clear buffered inbound state and message maps, and durably record the
  generation. This hook is local-only and must not depend on provider
  availability; local persistence failure aborts the active clear. A
  provider-time channel may resume after the host boundary closes. A cursor
  channel stays paused while it advances the provider cursor asynchronously and
  may resume only after it durably marks that generation applied. Startup
  repeats missed local preparation per channel; one broken channel remains
  disabled without blocking the desktop or other channels. Session mapping,
  control, attachment, and dispatch calls revalidate the same generation, so a
  pre-clear event cannot recreate local conversation state later.
- Plugin ingress processing holds a shared boundary from queue claim through
  handler completion. Full clear takes the matching exclusive boundary,
  deletes every pending, claimed, completed, and failed payload, and records a
  durable clear-time cutoff. Producers that append directly to the runtime
  trace database cannot revive older payloads after restart: claim discards
  any event whose source occurrence is at or before that cutoff. An unfinished
  global conversation clear also suppresses handler dispatch until recovery
  completes.
- Runtime trace and LLM usage projections use the memory operation epoch stamped
  when an event is published. Full clear seals both subscribers, drains work
  already writing, and rejects both events admitted during the clear and older
  events still queued on the in-process bus. A late completion is also rejected
  when its span began before or during the clear, even if it is published only
  after the boundary reopens. LLM usage clear removes raw calls, error text,
  session and turn links, prompt-cache observations, and retained rollups.
  Scheduled usage retention joins the same write boundary and cannot recreate a
  rollup from rows that are being cleared.
- Scheduler admission is sealed before global background-task admission. Full
  clear cancels and drains active user-created schedule handlers, deletes every
  `user_agent_task` definition and runtime job, and rejects stale handler
  enqueue or settlement by execution generation. All scheduler execution
  history and target error/statistics fields are erased because they may hold
  user-derived result text. System maintenance and source schedules remain,
  together with source cursors, watermarks, bindings, and configuration;
  pending sensor-sync jobs are discarded so no pre-clear queue payload remains.
- Full clear also removes retired user-content locations that current runtime
  code no longer reads: every entry under the managed `others/` directory and
  the reserved `self_memory_v2.db` file with its SQLite sidecars. Cleanup does
  not follow symbolic links and does not touch current stores, configuration,
  persona definitions, models, or installed packages.
- Archive cleanup applies the same rule to the configured archive directory.
  A linked archive directory is unlinked and replaced with a real managed
  directory; it is never traversed. Date-named archive entries are removed as
  directory entries without opening link targets, hard-link targets, FIFOs, or
  other special files.

### What Compression Means

Compression does not mean "delete freely".

Compression means:

- Preserving the important shape of history
- Allowing low-value raw details to be reduced
- Still retaining enough references to explain why a summary or procedure exists

Compression must not sacrifice the only important durable representation.

---

## Operating Rules

These rules must be followed during day-to-day development:

1. Chat transcript truth lives in `chat.db`, not in `L1`
2. Runtime trace truth lives in `runtime_trace.db`, not in `L1`
3. `L1` is the canonical fact projection layer
4. `L2`, `L3`, `L4` are all derived layers that must explain their provenance from lower layers
5. Cache is a rebuildable layer and must not become an implicit truth layer
6. `event_id` is a stable external reference, not a source identity surrogate or business dedup key
7. When `idempotency_key` is present, business uniqueness is defined by `(source, event_type, idempotency_key)`
8. Read paths needing producer-side business identifiers should prefer `source_item_id`, then `idempotency_key`, not `event_id`
9. L1 retrieval authority and L2 write policy must share evidence classification semantics
10. Raw L1 writes can tolerate evidence-classifier failure; fact promotion and L2 graph/assertion writes must not treat unknown evidence as authoritative by default
11. Fact-like retrieval modes must constrain authoritative evidence before topK selection; answer-projection filters are only a last-mile guard
12. Span-level retrieval atoms, if introduced, are derived projections that hydrate back to raw `fact_events`; they are not new raw facts
13. Classifier, policy, embedding profile, and index-version changes mark derived evidence/index records stale and rebuild them instead of mutating `fact_events.content`
14. User deletion of an L1 source must use the unified cross-layer workflow; direct L1 soft-delete helpers are maintenance internals, not product deletion APIs
15. Source tombstones are written before derivative cleanup and are checked again on L2, L3, L4, and L0 write or restore paths so replay fails closed
16. Public correction history and ordinary memory reads must redact or exclude forgotten content; only backend-governed history may expose correction details and decide revert eligibility

---

## Developer Entry Points

Main implementation entry points:

- [backend/src/magi/memory/\_\_init\_\_.py](../backend/src/magi/memory/__init__.py) — Public package entry point for the unified memory store

- [backend/src/magi/memory/unified_store.py](../backend/src/magi/memory/unified_store.py) — Unified L0-L4 memory store composition and lifecycle coordination

- [backend/src/magi/memory/store_source_event_forgetting.py](../backend/src/magi/memory/store_source_event_forgetting.py) and [backend/src/magi/memory/source_event_governance.py](../backend/src/magi/memory/source_event_governance.py) — Cross-layer source deletion and durable replay barriers

- [backend/src/magi/memory/store_corrections.py](../backend/src/magi/memory/store_corrections.py) and [backend/src/magi/memory/l2/corrections/](../backend/src/magi/memory/l2/corrections/) — Privacy-safe correction audit projection, correction lineage, future-write rules, and revert governance

- [backend/src/magi/memory/manual_entries/](../backend/src/magi/memory/manual_entries/) — User-authored source records, retry-safe L1 projection, and attachment storage

- [backend/src/magi/memory/layer_protocol.py](../backend/src/magi/memory/layer_protocol.py) and [backend/src/magi/memory/layers/](../backend/src/magi/memory/layers/) — Fan-out ingestion protocol and layer adapters for L1, L2 projection/pipeline, and L4; L0 attention is derived separately after accepted chat turns

- [backend/src/magi/memory/subscribers/memory_ingestion_subscriber.py](../backend/src/magi/memory/subscribers/memory_ingestion_subscriber.py) — Event-bus subscriber that translates domain events into normalized memory events

- [backend/src/magi/memory/event_contracts.py](../backend/src/magi/memory/event_contracts.py) — Standard event contracts and normalization logic

- [backend/src/magi/memory/l0/working_memory.py](../backend/src/magi/memory/l0/working_memory.py) — `L0` short-term attention store

- [backend/src/magi/memory/l1/event_store.py](../backend/src/magi/memory/l1/event_store.py) — `L1` fact event store, retrieval, and vector index

- [backend/src/magi/memory/l2/store.py](../backend/src/magi/memory/l2/store.py) — `L2` durable cognition store (knowledge graph, assertions, episodes, projection jobs)

- [backend/src/magi/memory/l2/pipeline/__init__.py](../backend/src/magi/memory/l2/pipeline/__init__.py) — `L2` extraction and cognition pipeline facade, durable projection job claim/batching

- [backend/src/magi/memory/l2/episode_formation.py](../backend/src/magi/memory/l2/episode_formation.py) — Streaming episode assignment and consolidation

- [backend/src/magi/memory/evidence/classifier.py](../backend/src/magi/memory/evidence/classifier.py) — Shared deterministic evidence classification used by L1 retrieval and L2 write governance

- [backend/src/magi/memory/evidence/policy.py](../backend/src/magi/memory/evidence/policy.py) — Shared rule-based policy per evidence class for L1 retrieval authority and L2 write governance

- [backend/src/magi/memory/l1/event_store.py](../backend/src/magi/memory/l1/event_store.py) — `L1EventStore.backfill_evidence_annotations` maintenance path for repairing missing or stale L1 evidence annotations

- [backend/src/magi/memory/l3/summary_store.py](../backend/src/magi/memory/l3/summary_store.py) — `L3` summaries and evidence backlinks

- [backend/src/magi/memory/l4/procedural_memory.py](../backend/src/magi/memory/l4/procedural_memory.py) — `L4` procedural memory

- [backend/src/magi/memory/l4/task_preferences.py](../backend/src/magi/memory/l4/task_preferences.py) — Explicit task-handling preferences stored as `L4` procedural memory

- [backend/src/magi/memory/hybrid_retrieval/service.py](../backend/src/magi/memory/hybrid_retrieval/service.py) — Cross-layer unified retrieval orchestrator

- [backend/src/magi/memory/hybrid_retrieval/mode_registry.py](../backend/src/magi/memory/hybrid_retrieval/mode_registry.py) — Query mode registry (9 unified modes)

- [backend/src/magi/memory/hybrid_retrieval/l2_handler.py](../backend/src/magi/memory/hybrid_retrieval/l2_handler.py) — L2-specific handler with semantic frame planning

- [backend/src/magi/memory/integration.py](../backend/src/magi/memory/integration.py) — Runtime-facing memory integration boundary

- [backend/src/magi/awareness/ingestion_gateway.py](../backend/src/magi/awareness/ingestion_gateway.py) — Sensor / plugin event publish entry point

---

## Checklist for Plugin and Feature Developers

When connecting a new memory source, answer these questions first:

1. Is it transcript truth, runtime trace, or durable memory projection?
2. Should it become durable `L1` evidence, influence the current L0 attention
   projection through a governed source reference, or remain outside memory?
3. What is the correct `memory_domain`?
4. Should it participate in downstream cognition?
5. What is the correct `retention_class`?
6. What is its source-side item identity?
7. What is its business idempotency key?

If these questions cannot be clearly answered, the feature is typically not ready to write into memory.

### Common Mistakes

- Writing raw runtime telemetry directly into `L1`
- Using `event_id` as a business source ID
- Defaulting `source_item_id` as the dedup key
- Writing mutable runtime intermediate state into the durable memory store
- Copying complete chat transcript truth into `L1`

---

## What This Document Intentionally Does Not Cover

This document does not describe:

- Phased implementation plans
- Temporary migration choreography
- Legacy schema compatibility layers
- Speculative new layers beyond `L4`

These belong in task plans, design drafts, or change notes — not in the long-term source-of-truth document.

---

## Summary

Magi's memory system is built on a simple but firm separation:

- Chat truth is not memory
- Runtime trace is not memory
- Durable memory starts from normalized `L1` facts

On this foundation:

- `L0` keeps a bounded, disposable projection of what still matters for the
  next conversational turn
- `L1` stores canonical durable facts
- `L2` provides structured cognition across three subdomains: semantic memory (entities, relations, preferences), state memory (versioned latest-truth with supersession), and episodic memory (episode substrates plus promoted experiences)
- `L3` compresses and reflects
- `L4` distills reusable execution experience

The query pipeline uses a unified `query_mode` system, each mode defining its own evidence shape, reducer, and authoritative evidence scope. Retrieval is mode-adaptive, with per-mode RRF weight profiles and structured semantic frames for L2 queries.

User agency is first-class: users can confirm, correct, reject, annotate, and
forget memory artifacts. Correction changes the governed interpretation while
retaining historical evidence; source deletion removes the selected evidence and
its dependent memory across layers, with durable barriers against replay.
Privacy scope is carried on every durable L2 object.

The identity model must always be clear:

- `id` — Internal join key
- `event_id` — Stable external reference
- `source_item_id` — Source-side identity
- `idempotency_key` — Business idempotency key

Polarity is logical negation of the predicate, not sentiment: `DISLIKES` with
positive polarity means an explicit dislike; negative `LIKES` never becomes
`DISLIKES`, and negative `DISLIKES` never becomes `LIKES`. Route contract v7
retains negative Claims, evidence, and temporal scope in the ledger with reason
`negative_claim_requires_scoped_exclusion`. Until a scoped exclusion projection
is supported, these Claims have no graph or portrait/assertion target. Initial
projection, optional wording, and route replay share this boundary.

Assertion `natural_summary` is a host-rendered view of predicate, target, and
time qualifiers. Model wording must exactly match this controlled view to be
accepted; substring overlap is not semantic validation. Materialization renders
again at the write boundary, so portraits, prompts, full-text and vector indexes
cannot receive an optional summary that reverses or extends the Claim.

Temporal summaries persist the union of all generation dependencies in
`source_event_ids` and the evidence-link table: selected samples, events supplied
to a successful plugin feature builder, and the complete event lineage of prior
and child summaries. `insight_metadata.cited_event_ids` retains the smaller
citation sample; `dependency_summary_ids` records transitive summary inputs.
These host-owned fields cannot be overwritten by model output. Forgetting or
blocking any dependency invalidates the complete derived summary.

A rejected L3 summary remains review history but is excluded from retrieval,
prompt material, and future summary context. Summaries derived from a rejected
summary are excluded as well. Replaying the same category, insight, and complete
source set returns the prior rejected record rather than creating a new pending
item. New evidence can produce a new review candidate. Rejection does not delete
or suppress the underlying L1 facts.

Preference scope is checked against the supporting statement at normalization
and grounded-Claim admission. An evaluation of one meal or visit stays event-only;
a direct general preference can be durable without an "always" keyword; an
explicit recent preference retains a bounded lifetime. A transient desire is not
promoted into a durable preference even if extraction labels it `LIKES`.

A mixed user message may admit its asserted clauses even when it ends in a
question. Claim grounding requires the quoted evidence to occur inside an
asserted clause, with question marks, hypothetical context, and quoted speech
preserved as boundaries. The graph preference guard inspects that grounded quote
instead of rejecting the entire source message because another clause asks a
question. The full original message remains unchanged in L1.

Frequency admission evaluates every eligible event once, inside the counter's
serialized transaction. Only admitted events enter the LLM window; a promoted
key never admits unrelated keys or forced structured-only events in its batch.
The durable batch descriptor and leases still cover the original batch. Direct
structured graph and facet writes retain each event's own evidence IDs.
