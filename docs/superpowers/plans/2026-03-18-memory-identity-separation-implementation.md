# Memory Identity Separation Implementation Plan

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Separate runtime/account identities from canonical memory identities so multi-channel accounts can map to a single memory self entity (`user:self`) without polluting L1/L2/L3 semantics.

**Architecture:** Introduce an explicit identity layering model: runtime/account identity stays at transport and session boundaries, while memory storage and cognition use a canonical memory owner identity. Add a dedicated identity resolver plus mapping persistence, then progressively update event contracts, memory pipelines, retrieval, and UI/debug surfaces to rely on `memory_owner_id` instead of transport-facing `user_id`.

**Tech Stack:** Python 3.12, FastAPI, Pydantic v2, aiosqlite, structlog, React 18 + TypeScript, Vitest, existing Magi memory stores and websocket/chat transports.

---

## Design Summary

### Identity layers

1. `runtime_user_id`
   - Channel/account identity used by chat routing, websocket rooms, API defaults, and session partitioning.
   - Examples: `web_user`, `telegram:asuka_main`, `discord:uid_123`.

2. `memory_owner_id`
   - Canonical memory identity used by L1/L2/L3/L4 ownership semantics.
   - In the current single-user product shape, this should resolve to `user:self`.

3. `memory_entity_id`
   - Structured graph/assertion entity ids used inside cognition.
   - For the local user, also `user:self`.

### Invariants

- A single human user may have multiple `runtime_user_id` values.
- All first-party self-authored or self-observed events should map to one `memory_owner_id`.
- L2 graph/assertion/snapshot should use `user:self`, never `user:web_user`.
- Transport/session logic may continue using `runtime_user_id` until explicitly migrated.
- No compatibility branches that preserve dual write behavior indefinitely; migrations must be staged and retired.

### Naming decision

- Canonical self entity id: `user:self`
- Runtime default web chat account id remains `web_user` unless explicitly changed in a later transport-focused task.

---

## Scope and Priority

### P0: Canonical memory identity foundation

Required before broader migration.

- Define identity terminology and canonical ids.
- Add `memory_owner_id` / `runtime_user_id` to normalized memory events.
- Introduce `IdentityResolver` with a default single-user mapping to `user:self`.
- Update L2 to use canonical self ids.
- Add migration for existing memory records that use `user:web_user`.

### P1: Runtime-to-memory mapping persistence

Needed to support multiple account identities cleanly.

- Add persistent identity mapping table.
- Allow mapping multiple runtime identities to one `memory_owner_id`.
- Update ingestion and retrieval code to resolve through the mapping layer.

### P2: Transport and product boundary cleanup

Improves conceptual consistency but can land after memory correctness.

- Surface both runtime and memory identities in API/debug responses.
- Update L2 Lab, memory pages, and diagnostics to display canonical self clearly.
- Reduce direct references to `web_user` in memory-adjacent UI.

### P3: Broader runtime cleanup

Nice-to-have after the memory model is stable.

- Revisit websocket room naming, chat runtime keys, and session naming.
- Decide whether a transport-level rename from `web_user` to another runtime default is worthwhile.

---

## File Map

### Backend core memory files

- Modify: `backend/src/magi/memory/event_contracts.py`
  - Add `runtime_user_id` and `memory_owner_id` to `MemoryEvent`.
  - Update normalization to derive both values.
- Modify: `backend/src/magi/memory/l1_event_store.py`
  - Persist and restore the new identity fields.
- Modify: `backend/src/magi/memory/l2_pipeline.py`
  - Use `memory_owner_id` when constructing self graph/assertion entities.
- Modify: `backend/src/magi/memory/l2_cognition_store.py`
  - Ensure self-owned cognition records use `user:self`.
- Modify: `backend/src/magi/memory/l2_models.py`
  - Carry `memory_owner_id` in request/result payloads where relevant.

### New backend identity module

- Create: `backend/src/magi/memory/identity_resolver.py`
  - Encapsulate runtime-to-memory identity mapping.
- Create: `backend/tests/memory/test_identity_resolver.py`
  - Verify mapping rules and persistence behavior.

### Memory persistence / migration

- Modify: `backend/src/magi/memory/__init__.py`
  - Initialize identity resolver and pass it into memory subsystems.
- Modify: `backend/src/magi/memory/l2_entity_catalog.py`
  - Normalize self aliases/canonical self entity if needed.
- Create or modify: migration helper under `backend/src/magi/core/` or `backend/src/magi/memory/`
  - One-shot rewrite of legacy `user:web_user` memory references to `user:self`.
- Test: `backend/tests/memory/test_l1_event_store.py`
- Test: `backend/tests/memory/test_l2_pipeline.py`
- Test: `backend/tests/memory/test_l2_cognition_store.py`

### API / transport boundary

- Modify: `backend/src/magi/api/routers/messages.py`
  - Keep `runtime_user_id` behavior stable; do not force transport rename.
- Modify: `backend/src/magi/api/routers/memory.py`
  - Expose canonical self identity where memory records are returned.
- Modify: `backend/src/magi/websocket/handlers.py`
  - Preserve routing on `runtime_user_id`; ensure any memory writes pass through resolver.

### Frontend memory/debug surfaces

- Modify: `frontend/src/pages/Events.tsx`
- Modify: `frontend/src/components/memory/L2Tab.tsx`
- Modify: `frontend/src/hooks/useMemory.ts`
- Modify: `frontend/src/api/modules/memory.ts`
- Modify: locale files under `frontend/src/i18n/locales/en/` and `frontend/src/i18n/locales/zh-CN/`
  - Present canonical self as `user:self` or localized label such as “Self”.

---

## Chunk 1: Identity Vocabulary And Contracts

### Task 1: Document the identity model in code contracts

**Files:**
- Modify: `backend/src/magi/memory/event_contracts.py`
- Test: `backend/tests/memory/test_l2_pipeline.py`

- [ ] **Step 1: Write failing tests for normalized events carrying both ids**

```python
def test_normalized_memory_event_tracks_runtime_and_memory_owner_ids():
    event = Event(
        type=EventTypes.USER_MESSAGE,
        data={"user_id": "web_user", "message": "hello"},
        source="chat",
        level=EventLevel.INFO,
    )

    normalized = normalize_runtime_event(event)

    assert normalized.runtime_user_id == "web_user"
    assert normalized.memory_owner_id == "user:self"
```

- [ ] **Step 2: Run the failing tests**

Run: `PYTHONPATH=/Users/asuka/code/magi/backend/src pytest backend/tests/memory/test_l2_pipeline.py -k runtime_and_memory_owner_ids -v`
Expected: FAIL because the fields do not exist yet.

- [ ] **Step 3: Add `runtime_user_id` and `memory_owner_id` to `MemoryEvent`**

Implementation notes:
- `runtime_user_id` should capture the inbound `user_id`/transport account id.
- `memory_owner_id` should come from a resolver, not hardcoded inline.
- `to_dict()` and metadata round-trip must include both fields.

- [ ] **Step 4: Run focused tests**

Run: `PYTHONPATH=/Users/asuka/code/magi/backend/src pytest backend/tests/memory/test_l2_pipeline.py -k runtime_and_memory_owner_ids -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/src/magi/memory/event_contracts.py backend/tests/memory/test_l2_pipeline.py
git commit -m "feat: add memory identity fields"
```

### Task 2: Add the identity resolver abstraction

**Files:**
- Create: `backend/src/magi/memory/identity_resolver.py`
- Test: `backend/tests/memory/test_identity_resolver.py`

- [ ] **Step 1: Write failing resolver tests**

```python
def test_default_identity_resolver_maps_web_runtime_to_self():
    resolver = IdentityResolver.in_memory_default()

    result = resolver.resolve_memory_owner_id(runtime_user_id="web_user", source="chat")

    assert result == "user:self"
```

```python
def test_identity_resolver_allows_multiple_runtime_accounts_for_same_self():
    resolver = IdentityResolver.in_memory_default(
        links=[
            ("web", "web_user", "user:self"),
            ("telegram", "asuka_main", "user:self"),
        ]
    )

    assert resolver.resolve_memory_owner_id(runtime_user_id="web_user", source="web") == "user:self"
    assert resolver.resolve_memory_owner_id(runtime_user_id="asuka_main", source="telegram") == "user:self"
```

- [ ] **Step 2: Run the failing tests**

Run: `PYTHONPATH=/Users/asuka/code/magi/backend/src pytest backend/tests/memory/test_identity_resolver.py -v`
Expected: FAIL because the module does not exist.

- [ ] **Step 3: Implement a focused resolver API**

Suggested surface:

```python
class IdentityResolver:
    async def initialize(self) -> None: ...
    async def shutdown(self) -> None: ...
    def resolve_memory_owner_id(self, *, runtime_user_id: str | None, source: str | None) -> str: ...
```

Default behavior:
- Single-user mode resolves any self-authored runtime identity to `user:self`.
- Unknown or absent runtime user ids still resolve to `user:self` for self-authored chat flows.

- [ ] **Step 4: Run focused tests**

Run: `PYTHONPATH=/Users/asuka/code/magi/backend/src pytest backend/tests/memory/test_identity_resolver.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/src/magi/memory/identity_resolver.py backend/tests/memory/test_identity_resolver.py
git commit -m "feat: add memory identity resolver"
```

---

## Chunk 2: L1 And L2 Migration To Canonical Self Identity

### Task 3: Persist new identity fields in L1

**Files:**
- Modify: `backend/src/magi/memory/l1_event_store.py`
- Test: `backend/tests/memory/test_l1_event_store.py`

- [ ] **Step 1: Write failing L1 round-trip tests**

```python
async def test_l1_round_trip_preserves_runtime_and_memory_owner_ids():
    event = build_memory_event(runtime_user_id="web_user", memory_owner_id="user:self")
    await store.write_event(event)

    reloaded = await store.get_memory_event(event.event_id)

    assert reloaded.runtime_user_id == "web_user"
    assert reloaded.memory_owner_id == "user:self"
```

- [ ] **Step 2: Run the failing tests**

Run: `PYTHONPATH=/Users/asuka/code/magi/backend/src pytest backend/tests/memory/test_l1_event_store.py -k runtime_and_memory_owner -v`
Expected: FAIL.

- [ ] **Step 3: Update L1 storage schema and row decoding**

Implementation notes:
- Prefer explicit columns over hiding these ids in freeform metadata.
- If schema evolution is needed, add a targeted migration path.

- [ ] **Step 4: Run focused tests**

Run: `PYTHONPATH=/Users/asuka/code/magi/backend/src pytest backend/tests/memory/test_l1_event_store.py -k runtime_and_memory_owner -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/src/magi/memory/l1_event_store.py backend/tests/memory/test_l1_event_store.py
git commit -m "feat: persist memory owner ids in l1"
```

### Task 4: Switch L2 self references from transport ids to `user:self`

**Files:**
- Modify: `backend/src/magi/memory/l2_pipeline.py`
- Modify: `backend/src/magi/memory/l2_cognition_store.py`
- Test: `backend/tests/memory/test_l2_pipeline.py`
- Test: `backend/tests/memory/test_l2_cognition_store.py`

- [ ] **Step 1: Write failing L2 graph/assertion tests**

```python
async def test_unified_extraction_uses_canonical_self_entity():
    # ingest a user-authored preference event
    edges = await store.l2.list_knowledge_graph(entity_id="user:self")

    assert any(edge["subject_id"] == "user:self" for edge in edges)
```

```python
async def test_reconcile_and_snapshot_use_canonical_self_id():
    assertions = await store.l2.list_tom_assertions(entity_id="user:self")
    assert assertions
```

- [ ] **Step 2: Run failing tests**

Run: `PYTHONPATH=/Users/asuka/code/magi/backend/src pytest backend/tests/memory/test_l2_pipeline.py backend/tests/memory/test_l2_cognition_store.py -k canonical_self -v`
Expected: FAIL because the code still emits transport-shaped self ids.

- [ ] **Step 3: Update L2 subject/entity construction**

Implementation notes:
- `focal_subject` should use `memory_owner_id`.
- Graph subjects and assertion entities should use `user:self` for the self actor.
- Do not mutate third-party entity ids.

- [ ] **Step 4: Run focused tests**

Run: `PYTHONPATH=/Users/asuka/code/magi/backend/src pytest backend/tests/memory/test_l2_pipeline.py backend/tests/memory/test_l2_cognition_store.py -k canonical_self -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/src/magi/memory/l2_pipeline.py backend/src/magi/memory/l2_cognition_store.py backend/tests/memory/test_l2_pipeline.py backend/tests/memory/test_l2_cognition_store.py
git commit -m "refactor: use canonical self in l2"
```

### Task 5: Migrate existing self-owned memory rows

**Files:**
- Create or modify: `backend/src/magi/memory/identity_migration.py`
- Modify: `backend/src/magi/memory/__init__.py`
- Test: `backend/tests/memory/test_identity_resolver.py`
- Test: `backend/tests/memory/test_l2_cognition_store.py`

- [ ] **Step 1: Write a migration test for legacy `user:web_user` rows**

```python
async def test_identity_migration_rewrites_legacy_web_user_refs():
    seed_legacy_rows(subject_id="user:web_user", entity_id="user:web_user")

    await run_identity_migration()

    assert not find_rows("user:web_user")
    assert find_rows("user:self")
```

- [ ] **Step 2: Run the failing tests**

Run: `PYTHONPATH=/Users/asuka/code/magi/backend/src pytest backend/tests/memory/test_identity_resolver.py backend/tests/memory/test_l2_cognition_store.py -k legacy_web_user -v`
Expected: FAIL.

- [ ] **Step 3: Implement the migration helper**

Migration targets:
- L2 knowledge graph subject/object ids where the self user was stored as `user:web_user`.
- L2 assertions, snapshots, and entity catalog rows using the legacy self id.
- Any L1 event ownership columns introduced in Task 3.

Requirements:
- Idempotent.
- Explicitly logs migrated row counts.
- Runs once at memory initialization or under a controlled migration hook.

- [ ] **Step 4: Run focused tests**

Run: `PYTHONPATH=/Users/asuka/code/magi/backend/src pytest backend/tests/memory/test_identity_resolver.py backend/tests/memory/test_l2_cognition_store.py -k legacy_web_user -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/src/magi/memory/identity_migration.py backend/src/magi/memory/__init__.py backend/tests/memory/test_identity_resolver.py backend/tests/memory/test_l2_cognition_store.py
git commit -m "feat: migrate legacy memory self ids"
```

---

## Chunk 3: Persistent Identity Mapping

### Task 6: Add persistent runtime-to-memory identity links

**Files:**
- Modify: `backend/src/magi/memory/identity_resolver.py`
- Modify: `backend/src/magi/memory/l2_cognition_store.py` or a dedicated sqlite helper file
- Test: `backend/tests/memory/test_identity_resolver.py`

- [ ] **Step 1: Write failing persistence tests**

```python
async def test_identity_links_persist_across_store_instances():
    await resolver.upsert_identity_link(namespace="telegram", runtime_user_id="asuka_main", memory_owner_id="user:self")
    await resolver.shutdown()

    reopened = IdentityResolver(db_path=db_path)
    await reopened.initialize()

    assert reopened.resolve_memory_owner_id(runtime_user_id="asuka_main", source="telegram") == "user:self"
```

- [ ] **Step 2: Run the failing tests**

Run: `PYTHONPATH=/Users/asuka/code/magi/backend/src pytest backend/tests/memory/test_identity_resolver.py -k persist_across_store_instances -v`
Expected: FAIL.

- [ ] **Step 3: Implement the identity link table**

Suggested columns:
- `namespace`
- `runtime_user_id`
- `memory_owner_id`
- `link_type`
- `created_at`
- `updated_at`

Constraints:
- Unique `(namespace, runtime_user_id)`
- Single-user default seed may be optional; resolver can still default to `user:self`

- [ ] **Step 4: Run focused tests**

Run: `PYTHONPATH=/Users/asuka/code/magi/backend/src pytest backend/tests/memory/test_identity_resolver.py -k persist_across_store_instances -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/src/magi/memory/identity_resolver.py backend/tests/memory/test_identity_resolver.py
git commit -m "feat: persist memory identity links"
```

### Task 7: Route memory ingestion through the resolver everywhere

**Files:**
- Modify: `backend/src/magi/memory/__init__.py`
- Modify: `backend/src/magi/memory/event_contracts.py`
- Modify: `backend/src/magi/awareness/sensor_hub.py`
- Modify: `backend/src/magi/api/routers/messages.py`
- Modify: `backend/src/magi/websocket/handlers.py`
- Test: `backend/tests/memory/test_l2_pipeline.py`
- Test: `backend/tests/api/test_messages_api.py`
- Test: `backend/tests/websocket/test_connection_manager.py` or matching websocket test file

- [ ] **Step 1: Write failing end-to-end mapping tests**

```python
async def test_chat_ingest_resolves_runtime_identity_to_memory_self():
    # submit message with runtime user id web_user
    event = await l1.get_memory_event(event_id)
    assert event.runtime_user_id == "web_user"
    assert event.memory_owner_id == "user:self"
```

```python
async def test_sensor_ingest_uses_same_memory_owner_for_multiple_accounts():
    # seed link for telegram account
    # ingest event from telegram source
    assert event.memory_owner_id == "user:self"
```

- [ ] **Step 2: Run the failing tests**

Run the narrow API/websocket/memory tests for the new identity behavior.
Expected: FAIL.

- [ ] **Step 3: Update ingestion call sites**

Implementation notes:
- Transport code should continue accepting `user_id`/runtime ids as request input.
- Before memory normalization, resolve canonical ownership.
- Do not rename public request fields in this task.

- [ ] **Step 4: Run focused tests**

Run the same API/websocket/memory suite and expect PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/src/magi/memory/__init__.py backend/src/magi/memory/event_contracts.py backend/src/magi/awareness/sensor_hub.py backend/src/magi/api/routers/messages.py backend/src/magi/websocket/handlers.py backend/tests/memory/test_l2_pipeline.py backend/tests/api/test_messages_api.py backend/tests/websocket/test_connection_manager.py
git commit -m "refactor: route memory ownership through identity resolver"
```

---

## Chunk 4: Retrieval, API, And Debug Surfaces

### Task 8: Update retrieval and memory APIs to expose both identity layers clearly

**Files:**
- Modify: `backend/src/magi/api/routers/memory.py`
- Modify: retrieval helpers under `backend/src/magi/memory/`
- Test: `backend/tests/api/test_memory_api.py`

- [ ] **Step 1: Write failing API tests**

```python
async def test_memory_api_returns_canonical_self_for_l2_records():
    payload = client.get("/memory/l2/statistics").json()
    assert payload["canonical_self_id"] == "user:self"
```

```python
async def test_memory_api_preserves_runtime_user_context_when_available():
    event = client.get("/memory/events/... ").json()
    assert event["runtime_user_id"] == "web_user"
    assert event["memory_owner_id"] == "user:self"
```

- [ ] **Step 2: Run the failing tests**

Run: `PYTHONPATH=/Users/asuka/code/magi/backend/src pytest backend/tests/api/test_memory_api.py -k canonical_self_id -v`
Expected: FAIL.

- [ ] **Step 3: Implement API response updates**

Requirements:
- Memory records expose canonical owner identity explicitly.
- Debug APIs include both `runtime_user_id` and `memory_owner_id` where useful.
- Do not leak transport-specific defaults into graph/assertion entity ids.

- [ ] **Step 4: Run focused tests**

Run the same API suite and expect PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/src/magi/api/routers/memory.py backend/tests/api/test_memory_api.py
git commit -m "feat: expose canonical memory identities"
```

### Task 9: Update frontend memory and debug surfaces

**Files:**
- Modify: `frontend/src/api/modules/memory.ts`
- Modify: `frontend/src/hooks/useMemory.ts`
- Modify: `frontend/src/pages/Events.tsx`
- Modify: `frontend/src/components/memory/L2Tab.tsx`
- Modify: `frontend/src/i18n/locales/en/app.json`
- Modify: `frontend/src/i18n/locales/zh-CN/app.json`
- Test: `frontend/src/__tests__/l2LabPage.test.tsx`
- Test: `frontend/src/__tests__/eventsPage.test.tsx`

- [ ] **Step 1: Write failing frontend tests**

Add assertions that the L2 page displays the canonical self label/value and no longer implies `web_user` is the memory entity.

- [ ] **Step 2: Run the failing tests**

Run: `cd frontend && npm run test -- src/__tests__/l2LabPage.test.tsx src/__tests__/eventsPage.test.tsx`
Expected: FAIL.

- [ ] **Step 3: Update API types and UI labels**

Implementation notes:
- Show canonical self as `user:self` or a localized display label like `Self`.
- Keep transport ids in debug sub-panels only when relevant.

- [ ] **Step 4: Run frontend verification**

Run:
- `cd frontend && npm run type-check`
- `cd frontend && npm run test -- src/__tests__/l2LabPage.test.tsx src/__tests__/eventsPage.test.tsx`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/api/modules/memory.ts frontend/src/hooks/useMemory.ts frontend/src/pages/Events.tsx frontend/src/components/memory/L2Tab.tsx frontend/src/i18n/locales/en/app.json frontend/src/i18n/locales/zh-CN/app.json frontend/src/__tests__/l2LabPage.test.tsx frontend/src/__tests__/eventsPage.test.tsx
git commit -m "feat: show canonical self in memory ui"
```

---

## Chunk 5: Runtime Cleanup And Follow-Through

### Task 10: Audit memory-adjacent `web_user` defaults and classify them

**Files:**
- Modify: `docs/superpowers/plans/2026-03-18-memory-identity-separation-implementation.md`
- Optional modify: selected runtime files after audit

- [ ] **Step 1: Produce an audit list of remaining `web_user` call sites**

Run:

```bash
rg -n "web_user|user:web_user" backend frontend
```

- [ ] **Step 2: Classify each call site**

Buckets:
- transport/session only: keep for now
- memory ownership leak: migrate now
- test fixture only: update when affected

- [ ] **Step 3: Apply only memory ownership cleanups discovered by the audit**

Keep this task small; do not rename transport ids globally unless the code path is truly memory-owned.

- [ ] **Step 4: Run the relevant targeted tests**

Run only the suites impacted by the selected cleanups.

- [ ] **Step 5: Commit**

Use a narrowly scoped conventional commit based on what was changed.

### Task 11: Final regression and merge readiness

**Files:**
- No new product files expected
- Update docs if validation uncovers gaps

- [ ] **Step 1: Run backend regression for the identity split**

```bash
cd backend
PYTHONPATH=/Users/asuka/code/magi/backend/src pytest \
  tests/memory/test_identity_resolver.py \
  tests/memory/test_l1_event_store.py \
  tests/memory/test_l2_entity_catalog.py \
  tests/memory/test_l2_cognition_store.py \
  tests/memory/test_l2_pipeline.py \
  tests/api/test_memory_api.py \
  tests/api/test_messages_api.py -v
```

Expected: PASS.

- [ ] **Step 2: Run frontend verification**

```bash
cd frontend
npm run type-check
npm run test -- src/__tests__/l2LabPage.test.tsx src/__tests__/eventsPage.test.tsx
```

Expected: PASS.

- [ ] **Step 3: Manually verify one real chat event**

Suggested verification:
- send a user message from the chat UI with `runtime_user_id = web_user`
- inspect the resulting L1 record and L2 graph/assertion rows
- confirm the event stores `runtime_user_id = web_user`
- confirm cognition records use `user:self`

- [ ] **Step 4: Update docs if behavior or boundaries changed**

Touch the relevant memory or product docs only if execution changed the plan.

- [ ] **Step 5: Merge or prepare PR**

Use superpowers:finishing-a-development-branch and include validation evidence in the final handoff.

---

## Risks And Decisions

### Risk 1: Hidden coupling to `user_id`

Many modules likely assume `user_id` is both a routing id and a memory owner id.

Mitigation:
- Introduce `runtime_user_id` and `memory_owner_id` explicitly.
- Update call sites incrementally with tests at each boundary.

### Risk 2: Existing databases contain legacy self ids

Without migration, retrieval and L2 graphs may split across `user:web_user` and `user:self`.

Mitigation:
- Add an idempotent migration task before rolling out new writes broadly.

### Risk 3: Over-migrating transport semantics

If transport/session identifiers are renamed too early, websocket/chat routing may break.

Mitigation:
- Keep runtime ids stable through P0/P1.
- Only change transport names in a dedicated later task.

### Risk 4: Tests that assert old prompt or id semantics

The repository already has tests that may assert historical shapes.

Mitigation:
- Update tests only when their assumptions conflict with the approved architecture.
- Prefer changing tests rather than reintroducing compatibility behavior.

---

## Recommended Execution Order

1. Task 1
2. Task 2
3. Task 3
4. Task 4
5. Task 5
6. Task 6
7. Task 7
8. Task 8
9. Task 9
10. Task 10
11. Task 11

This order front-loads memory correctness and data migration before API/UI cleanup.

## Out Of Scope

- Global rename of transport `web_user` defaults across the entire app.
- Multi-human-user memory partitioning beyond the current single-user local-first model.
- Cross-device identity sync or cloud account linking.
- Personality layer redesign unrelated to identity ownership.

## Success Criteria

- Self-authored memory events retain `runtime_user_id` for routing/audit.
- The same events store `memory_owner_id = user:self`.
- L2 graph/assertion/snapshot no longer store `user:web_user`.
- Legacy memory data migrates cleanly to `user:self`.
- UI/debug surfaces clearly distinguish runtime identity from canonical memory identity.
- Multiple runtime accounts can map to the same canonical memory self.

Plan complete and saved to `docs/superpowers/plans/2026-03-18-memory-identity-separation-implementation.md`. Ready to execute?
