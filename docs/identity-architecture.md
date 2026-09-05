# Identity Architecture

**Status**: Implemented for the current single-user product scope
**Owner**: Channels, Memory, and Chat runtime maintainers
**Last Updated**: 2026-07-14

## 1. Purpose

This document defines a unified user-identity layer for Magi: the
canonical authority that decides "who is the human behind this
inbound event" and surfaces a typed identifier (`MagiUserID`) that
every higher layer stores instead of channel-specific external ids.

It establishes one binding boundary — external identifier
(WeChat OpenID, Telegram chat_id, future iMessage handle / OAuth sub /
email address) → internal `MagiUserID` — and forbids external ids from
flowing past that boundary into memory, chat, runtime trace, or any
downstream store.

Read it together with [Layered Agent Architecture](./layered-agent-architecture.md)
(which fixes the layer position), [Task-Agent Runtime Architecture](./task-agent-runtime-architecture.md)
(which owns the ingress paths that call this layer).

## 2. Problem

Magi historically had no central identity service. The closest thing
to a canonical user id was a bare `"local_user"` default shared through
runtime-default helpers and used by the desktop / HTTP `/chat` path. External
channels synthesize their own id at
`channels/session_mapper.py:57`:

```python
magi_user_id = f"channel_{channel_type}_{external_user_id}"
```

So when the same human writes from WeChat instead of the desktop UI,
every downstream layer sees a different `user_id` and stores their
events in a completely separate partition. The DB shows this clearly
on a single-user instance that has been used from both surfaces:

| Store                                       | Distinct user_id values                            |
| ------------------------------------------- | -------------------------------------------------- |
| `memory/l1_events.fact_events`              | `local_user` 426 + `channel_weixin_o9cq…` 22       |
| `memory/l1_events.chat_sessions`            | `local_user` 10 + `channel_weixin_o9cq…` 1         |
| `chat.chat_messages`                        | `local_user` 41 + `channel_weixin_o9cq…` 22        |
| `memory/memory.l0_sessions`                 | `local_user` 10 + `channel_weixin_o9cq…` 1         |
| `memory/growth_memory.relationships`        | `local_user` 1 + `channel_weixin_o9cq…` 1          |
| `runtime/runtime_trace.runtime_notifications` | `local_user` 1229 + `channel_weixin_o9cq…` 206 + `default_user` 53 (stray) |
| `channels/channels.channel_session_mappings.magi_user_id` | `channel_weixin_o9cq…` 1                |

Net effect: the user-visible problem is "weixin can't see desktop
memory and vice versa", and the deeper problem is that **the
external identifier (WeChat OpenID) and the internal identifier
(MagiUserID) are stored in the same column**, so once a value flows
out of `session_mapper` nothing downstream can tell what kind of id
it is or how to canonicalize it.

The codebase has partially recognized this:

- `memory/l2/pipeline/entities/helpers.py:202` collapses any
  `channel_*`-prefixed `user_id` to `user:local_user` when writing
  the L2 self entity — but only at the L2 self-entity site, not at
  L1 write, chat write, runtime-trace write, or any other layer.
- `memory/hybrid_retrieval/l2_query_frame_utils.py:62` adds a
  `user:self` alias when the query's `user_id == DEFAULT_USER_ID` —
  but a weixin query passes `user_id = "channel_weixin_*"`, so the
  alias branch never fires and the read side does not collapse even
  when the write side did. The net L2 state is half-normalized.

Five separate ad-hoc normalization sites exist across the codebase
(synthesis, write-side collapse, read-side alias, defaults,
fallbacks), none of which are the canonical authority and none of
which agree on the same string scheme.

## 3. Goals

- Establish `MagiUserID` as the single internal identifier type for
  the human user, with `magi/identity/` as the canonical authority.
- Confine external-identifier semantics to one binding boundary;
  external ids must not flow past the channels (L13) / api (L13) /
  awareness (L9) ingress layer.
- Make the existing partial normalization (L2 self-entity collapse,
  hybrid-retrieval `user:self` alias) unnecessary by canonicalizing
  earlier; let those sites become defensive only.
- Provide a migration path that collapses today's
  `channel_*`-prefixed rows into `local_user` so existing weixin
  history becomes visible from desktop and vice versa.
- Preserve outbound delivery: `magi_session_id` ↔ `external_chat_id`
  mapping in `channel_session_mappings` keeps working — only
  `magi_user_id` semantics tighten.
- Keep the change additive and reversible per phase: data migration,
  code wiring, and type discipline land separately and each can
  ship without the next.

## 4. Non-Goals

- Multi-user authorization (who can see whose memory). Identity
  answers "who you are", not "what you can see". Authorization is
  out of scope for this document.
- Federated identity across multiple Magi instances. The single-user
  assumption stays for the current generation; this layer just
  makes the future multi-user upgrade a config flip rather than a
  cross-cutting refactor.
- Persona switching. `personality/` (L9) owns the agent-side
  persona; identity is orthogonal.
- Plugin sandboxing of identity reads. The SDK already exposes
  `user_id` to capability tools via `ToolExecutionContext`; that
  contract is unchanged in shape, only the value semantics tighten.
- Replacing `magi_session_id` / `external_chat_id` plumbing. Session
  identity stays in channels (L13); user identity moves to L1. The
  two stop overlapping.

## 5. Existing State

### 5.1 Default user id

- `identity.defaults.CANONICAL_LOCAL_USER` is the canonical desktop /
  HTTP `/chat` default and is typed as `MagiUserID`.
- `user_profile/models.py` re-exports the same value for profile read
  models instead of declaring an independent source of truth.
- `awareness/source_hub.py` falls back to `DEFAULT_USER_ID` when an
  inbound event lacks `user_id`.

### 5.2 External-id synthesis

`channels/session_mapper.py` is the only synthesis site. On a fresh
inbound from an external channel:

```python
# resolve_or_create
magi_user_id = f"channel_{channel_type}_{external_user_id}"
```

The resulting string is stored on `channel_session_mappings.magi_user_id`,
returned to the channel adapter, and then propagated as the `user_id`
on every subsequent event the adapter dispatches via
`dispatch_user_message`. From there it flows verbatim into chat
storage, source_hub → fact_events, runtime_notifications, and
anything else keyed by `user_id`.

### 5.3 Partial normalization

- `memory/l2/pipeline/entities/helpers.py::_resolve_self_entity_id`:
  collapses `"self"` / `channel_*` → `user:local_user` for the L2
  self-entity catalog node. Write-side only.
- `memory/hybrid_retrieval/l2_query_frame_utils.py::make_self_entities`:
  adds `user:self` alias only when querying as `DEFAULT_USER_ID`.
  Read-side, narrow trigger.
- `memory/l2/context_collector.py:27`: sets the deterministic
  pronoun-binding resolved_ref to `event.user_id` directly, with
  `"user:self"` as fallback only when user_id is empty.

These are useful evidence that the team has run into the problem
before; this design unifies and supersedes them.

### 5.4 Internal namespaces that touch user_id

Eleven tables across five SQLite stores currently key on `user_id`:

```
memory/growth_memory      relationships
memory/l1_events          fact_events, chat_sessions, l1_event_vec_*
memory/memory             l0_sessions, user_profile_projection
chat/chat                 chat_sessions, chat_turns, chat_messages, chat_attachments
channels/channels         channel_session_mappings (column: magi_user_id)
runtime/background_tasks  background_tasks
runtime/runtime_trace     trace_turns, runtime_notifications, user_notifications
```

Every one of these is a `TEXT` column with no FK and no type
discipline. Eight currently hold values from both the canonical
namespace and the synthesized channel namespace.

## 6. Architecture

### 6.1 Layer placement

`magi/identity/` joins L1 (Application Infrastructure) as a sibling
of `core/`, `scheduler/`, and `runtime_trace/`.

Rationale:

- **Dependency graph forces L1.** Every upper layer that touches
  user identity must be able to import the resolver: channels (L13),
  api (L13), chat (L13), awareness (L9), memory (L7), agent (L11),
  tools (L7 capability ports), runtime_trace (L1, the data-plane
  cousin). The resolver must therefore sit at the bottom of the
  dependency graph.
- **Conceptual symmetry with runtime_trace.** Both are typed-API +
  persistent-store substrates that every layer consumes downward.
  `runtime_trace` owns observability data and a typed API for
  appending traces; `identity` owns binding data and a typed API
  for resolving / binding identifiers. Same shape, same layer.
- **Identity has no event-bus or control-plane dependency.** It
  does not need to publish events on the message bus (L2 events) or
  drive InteractionBroker state (L3 control), so it can sit below
  both, like `core/` does.

`magi/identity/` may depend on `core/` (for `runtime_paths` so it
knows where to put its SQLite file). It must not depend on anything
in L2 or above.

### 6.2 Module shape

```
magi/identity/
  __init__.py
  types.py              # MagiUserID = NewType("MagiUserID", str)
                        # ExternalIdentity dataclass(channel_type, external_user_id)
  defaults.py           # CANONICAL_LOCAL_USER: MagiUserID = MagiUserID("local_user")
  resolver.py           # IdentityResolver — the public service surface
  bindings_store.py     # SQLite store for user_identity_bindings
  bootstrap.py          # build_identity_module(runtime_paths) -> IdentityModule
```

The boundary with the rest of the codebase is `IdentityResolver`:

```python
class IdentityResolver(Protocol):
    async def resolve(self, external: ExternalIdentity) -> MagiUserID: ...
    async def bind(self, external: ExternalIdentity, user: MagiUserID) -> None: ...
    async def lookup_externals(self, user: MagiUserID) -> list[ExternalIdentity]: ...
    def canonical_local(self) -> MagiUserID: ...
```

Single-user implementation (default):

```python
class LocalUserResolver(IdentityResolver):
    """Every resolve() returns CANONICAL_LOCAL_USER; bindings are recorded
    for forensics but not used to differentiate users. This is the
    single-user mode the codebase already assumes elsewhere."""
```

Multi-user implementation (future, when product demands it):

```python
class BindingTableResolver(IdentityResolver):
    """resolve() queries user_identity_bindings; bind() creates a row.
    Unbound external identities get auto-bound to CANONICAL_LOCAL_USER
    (preserving single-user-default behavior until an explicit rebind)."""
```

Same Protocol, two strategies. Bootstrap picks one based on config;
all callers see one interface.

### 6.3 Types

`MagiUserID = NewType("MagiUserID", str)` is a runtime no-op (still a
`str`) and a type-checker handle. Adoption follows the
**BASELINE + RATCHET** pattern already used by `.importlinter`:

- Phase 2 (shipped): declare the type, use it inside `magi/identity/`
  exclusively. Outside callers still pass `str`; no signature
  changes. This is the "relaxed" path — defense relies on ingress
  discipline, not the type system.
- Phase 3 (separate future PR): ratchet `MagiUserID` outward,
  starting at the ingress edges (`channels/dispatcher.py`,
  `api/services/message_dispatch_service.py`,
  `awareness/source_hub.py`) and growing inward toward storage
  call sites. Each PR shrinks the `str` perimeter, identical to how
  `.importlinter` shrinks its `ignore_imports` list.

### 6.4 Bindings store

New table in a dedicated SQLite database under
`runtime_paths.data_dir / "identity" / "identity.db"`:

```sql
CREATE TABLE user_identity_bindings (
    channel_type      TEXT    NOT NULL,
    external_user_id  TEXT    NOT NULL,
    magi_user_id      TEXT    NOT NULL,
    created_at_ms     INTEGER NOT NULL,
    last_seen_at_ms   INTEGER NOT NULL,
    UNIQUE(channel_type, external_user_id)
);
CREATE INDEX idx_user_identity_bindings_magi_user
    ON user_identity_bindings(magi_user_id);
```

Independent SQLite file, like `runtime_trace.db` and `channels.db`.
Not co-located in any existing store because identity is
cross-cutting: putting it in `memory/` would invert dependencies,
putting it in `channels/` would conflate session and user identity.

### 6.5 Resolver call sites at ingress

There are exactly four ingress boundaries that must call
`identity.resolve()` to canonicalize before the value flows
downstream:

| # | Site                                                                                  | Layer | What it receives                              | What it must store |
| - | ------------------------------------------------------------------------------------- | ----- | --------------------------------------------- | ------------------ |
| 1 | `channels/dispatcher.py::ChannelMessageDispatcher.dispatch_user_message`              | L13   | `source` (channel scheme) + adapter-provided `external_user_id` via metadata | resolve → `MagiUserID` → pass downstream as `user_id` |
| 2 | `api/services/message_dispatch_service.py::dispatch_user_message`                     | L13   | `user_id` query arg / form arg (defaults to `DEFAULT_USER_ID`) | canonicalize (today: always equals `local_user`) → continue |
| 3 | `awareness/source_hub.py::SourceHub._on_user_message`                                 | L9    | `event.data["user_id"]` from the published Event | already-canonical, asserts |
| 4 | `channels/session_mapper.py::resolve_or_create`                                       | L13   | `(channel_type, external_user_id)`            | resolve → store canonical in `magi_user_id` column |

After Phase 2, no other layer should be the first to see an
external identifier. Memory, chat, runtime_trace, tools — all see
already-canonical `MagiUserID` values.

## 7. Cleanup Inventory

When the resolver is wired at all four ingress sites, the following
existing code becomes redundant or simplifies:

| File:line                                                                          | Today                                                            | After                                                                |
| ---------------------------------------------------------------------------------- | ---------------------------------------------------------------- | -------------------------------------------------------------------- |
| `channels/session_mapper.py:57`                                                    | `f"channel_{channel_type}_{external_user_id}"`                   | `await identity.resolve(ExternalIdentity(channel_type, external_user_id))` |
| `memory/l2/pipeline/entities/helpers.py:202`                                       | `if raw == "self" or raw.startswith("channel_"): return "user:local_user"` | defensive-only assert; the `channel_*` branch becomes unreachable    |
| `memory/hybrid_retrieval/l2_query_frame_utils.py:62`                               | special-case `user:self` alias only for `DEFAULT_USER_ID`        | unconditional alias (all callers now pass canonical user)            |
| `memory/l2/context_collector.py:27`                                                | `str(event.user_id or "user:self")`                              | always-canonical user_id; `or` fallback never fires                  |
| `user_profile/models.py:9`                                                         | duplicated `DEFAULT_USER_ID = "local_user"`                      | re-export from `identity.defaults.CANONICAL_LOCAL_USER`              |
| `identity/defaults.py`                                                             | canonical `CANONICAL_LOCAL_USER`                                 | single owner for the desktop default user id                         |
| `tools/builtin/schedule_tool.py:149`                                               | `"local_user"` literal                                           | `identity.defaults.CANONICAL_LOCAL_USER`                             |
| `chat/control_transcript_subscriber.py:51`                                         | `return normalized or DEFAULT_USER_ID`                           | typed canonical fallback                                             |

## 8. Migration Plan

Originally proposed as three independently mergeable phases (data
migration → code wiring → type ratchet). The shipped rollout
landed Phase 2 and Phase 3 only — Phase 1 was intentionally skipped
because this codebase had not launched at the time of the rollout
and carried no production data to migrate.

### 8.1 Phase 1 — Data migration (one-shot SQL) — **NOT SHIPPED**

The original draft included a script
(`scripts/migrations/2026-06-identity-collapse.py`) that would have
SQL-collapsed every legacy `channel_*`-prefixed `user_id` row across
all stores. The draft was authored, smoke-tested against a
pre-launch dev instance, and then deliberately removed before merge
because the project had no production data to migrate.

If this design ever ships to a deployment that DOES have legacy
`channel_*`-prefixed rows, the migration shape is preserved here for
reference:

```sql
-- Memory partition
UPDATE fact_events           SET user_id = 'local_user' WHERE user_id LIKE 'channel_%';
UPDATE chat_sessions         SET user_id = 'local_user' WHERE user_id LIKE 'channel_%';
                          -- (in memory/l1_events.db)
UPDATE l0_sessions           SET user_id = 'local_user' WHERE user_id LIKE 'channel_%';
                          -- (in memory/memory.db)
UPDATE relationships         SET user_id = 'local_user' WHERE user_id LIKE 'channel_%';
                          -- (in memory/growth_memory.db)

-- Chat partition
UPDATE chat_sessions         SET user_id = 'local_user' WHERE user_id LIKE 'channel_%';
UPDATE chat_turns            SET user_id = 'local_user' WHERE user_id LIKE 'channel_%';
UPDATE chat_messages         SET user_id = 'local_user' WHERE user_id LIKE 'channel_%';
UPDATE chat_attachments      SET user_id = 'local_user' WHERE user_id LIKE 'channel_%';

-- Channels partition
UPDATE channel_session_mappings SET magi_user_id = 'local_user' WHERE magi_user_id LIKE 'channel_%';

-- Runtime trace partition
UPDATE trace_turns           SET user_id = 'local_user' WHERE user_id LIKE 'channel_%';
UPDATE runtime_notifications SET user_id = 'local_user' WHERE user_id LIKE 'channel_%';

-- Stray cleanup
UPDATE user_notifications    SET user_id = 'local_user' WHERE user_id = 'default_user';
```

A migration that ships would additionally trigger an L1 vec0
partition rebuild (`l1_event_vec_*` uses `user_id` as its partition
key, so collapsing the column doesn't relocate vectors automatically).

### 8.2 Phase 2 — Code wiring

In dependency order:

1. Create `magi/identity/` (types, defaults, bindings store,
   `LocalUserResolver`, bootstrap).
2. Add `IdentityModule` to the bootstrap orchestrator order
   (between `core/` and `config/`).
3. Wire the resolver at the four ingress sites (table in §6.5).
4. Update `session_mapper.resolve_or_create` to call the resolver
   instead of synthesizing.
5. Remove the now-unreachable `channel_*` branch in
   `l2/pipeline/entities/helpers.py:202` (or downgrade to
   defensive assertion).
6. Drop the `if user_id == DEFAULT_USER_ID` special case in
   `l2_query_frame_utils.py:62`.

Each step is a separate commit. Regression suite stays green
throughout because `LocalUserResolver` is behavior-equivalent to
"always return `local_user`" — which matches what the system already
does for desktop. (For deployments with legacy data, what Phase 1
would have done by SQL is what Phase 2 now does for every
inbound: collapse to canonical at ingress.)

### 8.3 Phase 3 — Type discipline ratchet

1. Declare `MagiUserID = NewType("MagiUserID", str)` in
   `identity/types.py`.
2. Annotate `IdentityResolver.resolve()` to return `MagiUserID`.
3. Annotate the four ingress sites to receive `MagiUserID` from
   `resolve()` and pass it forward. mypy or ruff TC005 catches any
   `str` that leaks past.
4. Walk outward, store by store. Each PR converts one downstream
   `user_id: str` to `user_id: MagiUserID`. The pattern is identical
   to the `.importlinter` BASELINE + RATCHET roll-down.

Phase 3 is the optional rigor pass; the system is correct after
Phase 2 and Phase 3 just makes it impossible to regress.

## 9. Test Strategy

Three tiers:

- **Identity unit tests** (`backend/tests/identity/`): resolver
  contract (resolve / bind / lookup_externals / canonical_local),
  bindings store CRUD, idempotent bind, concurrent-binding race.
- **Ingress integration tests**: each of the four ingress sites in
  §6.5 gets a focused test that an external-id-bearing payload
  produces a canonical `user_id` downstream. Mirrors the test we
  already added for `SourceHub` source-field propagation in
  `tests/awareness/test_source_hub_source_propagation.py`.
- **End-to-end test**: weixin inbound → run completes → fact_events
  row has `user_id = 'local_user'`. This is the user-visible win:
  cross-channel memory recall works.

If Phase 1 is ever revived (deployment with legacy data), the
script should ship with a self-check that verifies the
post-migration row counts match the pre-migration sum (no rows
lost, only re-keyed).

## 10. Open Questions

- **iMessage / Slack / email**: when these channels land, do they
  bind to the same `MagiUserID` automatically, or does the user
  approve via UI? Default is auto-bind to `CANONICAL_LOCAL_USER`
  on first inbound (matches today's single-user assumption); UI
  binding management lands when multi-user does.
- **L2 entity rebuild scope**: the `user:channel_*` nodes in
  `entity_catalog` that were created before the L2 helper
  normalization landed — do those need a cleanup pass to merge
  into `user:local_user`? On a deployment with legacy data, yes —
  a revived Phase 1 should include an audit query and a targeted
  UPDATE. On this codebase (pre-launch, no legacy data), N/A.
- **Background task ownership**: `background_tasks.user_id` is
  currently empty in the surveyed instance, but the column exists.
  When a tool spawns a background job on behalf of a weixin user,
  the canonical user is the right answer — confirms the design
  rather than complicating it.
- **Cross-instance sync**: if a future feature syncs memory between
  two Magi installations on different machines for the same human,
  `MagiUserID` becomes the cross-instance handle. Out of scope for
  this layer; this design just doesn't preclude it.

## 11. Future Work

- Multi-user binding via UI ("connect another account" flow that
  hits `IdentityResolver.bind`).
- Authorization layer (L4-ish) that sits between identity and
  memory, gating read scopes per user — only meaningful once
  multi-user actually ships.
- Identity export / portability — given a `MagiUserID`, emit a
  bundle of all memory / chat / bindings, importable on another
  instance. Federated identity is the eventual destination.

## 12. Out of Scope

- Magi-side authentication of the human (we trust the channel; if
  Telegram says "this user_id is Alice", we accept it).
- Anti-spoofing within a channel (e.g. WeChat OpenID collision
  attacks) — that's a channel-plugin concern.
- Persona-scoped memory (memory partitioned by persona × user).
  Persona owns its own surface in L9; this layer doesn't intersect.
- Renaming `magi_user_id` columns in existing tables. The column
  name stays for stability; only the semantic of what's stored
  tightens.

---

## Appendix A: Layer Position Diagram

```
┌───────────────────────────────────────────────────────────────┐
│ L14   transport | ipc                                          │
│ L13   api | chat | channels  ◄── ingress: resolve() call sites │
│ L12   timeline                                                 │
│ L11   agent                                                    │
│ L10   context                                                  │
│ L9    awareness         ◄── ingress: source_hub resolve() site │
│ L8    personality                                              │
│ L7    tools | skills                                           │
│ L6    memory            ◄── consumes MagiUserID (write/read)   │
│ L5    llm                                                      │
│ L4    plugins                                                  │
│ L3    control                                                  │
│ L2    events                                                   │
│ L1.5  config                                                   │
│ L1    scheduler | runtime_trace | ★ identity ★ | core         │
└───────────────────────────────────────────────────────────────┘
```

All resolver calls flow downward from the call site to L1. No L1
module imports anything above it.
