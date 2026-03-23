# LLM Global Concurrency Implementation Plan

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a provider-model shared global concurrency limiter for chat and embedding requests, expose per-model advanced concurrency settings, and add bounded L1 embedding backpressure.

**Architecture:** Keep scenario-based model selection unchanged, but resolve concurrency from a shared runtime override table keyed by normalized provider-model-family identity. Enforce limits in the shared LLM runtime layer for chat requests and in the embedding service for embedding requests, then bound the L1 embedding queue so provider-side backpressure becomes controlled waiting instead of unbounded growth.

**Tech Stack:** Python 3.12, Pydantic v2, asyncio, FastAPI config router, React 18, TypeScript, Vitest, pytest

---

## File Map

- Modify: `backend/src/magi/config/models.py`
  - add `max_concurrency` to limit settings and add shared runtime override config models
- Modify: `backend/src/magi/config/llm_registry.py`
  - extend embedding metadata limits and add helpers to resolve effective concurrency defaults
- Modify: `backend/configs/llm_providers.yaml`
  - define packaged per-model `max_concurrency` defaults for chat and embedding models
- Modify: `backend/src/magi/llm/provider_bridge.py`
  - enforce chat-model concurrency limits around outbound provider calls
- Create: `backend/src/magi/llm/concurrency_limiter.py`
  - own process-wide semaphores, key normalization, and limiter stats
- Modify: `backend/src/magi/memory/embedding_service.py`
  - enforce embedding-model concurrency limits around outbound embedding requests
- Modify: `backend/src/magi/memory/l1/event_store.py`
  - change the embedding queue to a bounded queue and expose backlog-aware behavior
- Modify: `backend/src/magi/api/routers/config.py`
  - persist and return shared runtime overrides through the config API
- Modify: `backend/tests/api/test_config_api.py`
  - cover config schema, registry defaults, and update-path behavior
- Create or Modify: `backend/tests/llm/test_concurrency_limiter.py`
  - cover limiter keying, shared semaphore behavior, and stats
- Modify: `backend/tests/memory/l1/test_event_store.py`
  - cover bounded embedding queue behavior
- Modify: `backend/tests/memory/test_embedding_service.py`
  - cover embedding limiter integration
- Modify: `frontend/src/api/modules/config.ts`
  - add frontend types for `max_concurrency` and shared runtime overrides
- Modify: `frontend/src/components/config-forms/LLMModelSelectionSection.tsx`
  - add advanced max concurrency editing with shared-value semantics
- Modify: `frontend/src/__tests__/settingsPage.test.tsx`
  - verify the advanced control renders and saves correctly
- Modify: `frontend/src/i18n/locales/en/app.json`
  - add settings copy for advanced max concurrency
- Modify: `frontend/src/i18n/locales/zh-CN/app.json`
  - add matching Chinese copy
- Modify: `docs/superpowers/specs/2026-03-23-llm-global-concurrency-design.md`
  - only if implementation reveals a necessary design correction

## Chunk 1: Config Schema And Registry Defaults

### Task 1: Add failing config tests for shared concurrency settings

**Files:**
- Modify: `backend/tests/api/test_config_api.py`
- Modify: `backend/src/magi/config/models.py`
- Modify: `backend/src/magi/config/llm_registry.py`
- Modify: `backend/configs/llm_providers.yaml`

- [ ] **Step 1: Write the failing backend config tests**

Add tests that cover:

```python
def test_llm_limits_support_max_concurrency():
    config = SystemConfigModel(llm={"selections": {
        "context_decider": {"provider_id": "openai", "model": "gpt-5.2", "limits": {"max_concurrency": 4}},
        "core": {"provider_id": "openai", "model": "gpt-5.2"},
    }})
    assert config.llm.selections["context_decider"].limits.max_concurrency == 4


def test_default_registry_exposes_embedding_concurrency_defaults():
    registry = _default_llm_provider_registry()
    assert registry.providers[0].embedding_models[0].limits.max_concurrency is not None
```

- [ ] **Step 2: Run the focused tests to verify they fail**

Run: `PYTHONPATH=backend/src pytest backend/tests/api/test_config_api.py -q -k "max_concurrency or embedding_concurrency"`
Expected: FAIL because the models and registry do not expose the new fields yet.

- [ ] **Step 3: Add minimal config schema support**

Implement:

- `LLMLimitsSettings.max_concurrency`
- a shared override model such as `LLMModelRuntimeOverrideSettings`
- `LLMSettings.model_runtime_overrides`
- embedding registry metadata limits in `LLMEmbeddingModelMetaModel`

- [ ] **Step 4: Add packaged defaults to the provider registry**

Update `backend/configs/llm_providers.yaml` so:

- chat models declare `limits.max_concurrency`
- embedding models declare `limits.max_concurrency`
- defaults stay conservative and vary by model/provider

- [ ] **Step 5: Update config API plumbing and builders**

Ensure:

- `_build_system_config()` returns runtime overrides
- `_build_update_paths()` persists runtime overrides cleanly
- onboarding/template payloads continue to validate

- [ ] **Step 6: Run the focused tests to verify they pass**

Run: `PYTHONPATH=backend/src pytest backend/tests/api/test_config_api.py -q -k "max_concurrency or embedding_concurrency"`
Expected: PASS

- [ ] **Step 7: Commit**

```bash
git add backend/src/magi/config/models.py backend/src/magi/config/llm_registry.py backend/configs/llm_providers.yaml backend/src/magi/api/routers/config.py backend/tests/api/test_config_api.py
git commit -m "feat: add llm concurrency config defaults"
```

## Chunk 2: Runtime Limiter For Chat Models

### Task 2: Add a shared concurrency limiter service

**Files:**
- Create: `backend/src/magi/llm/concurrency_limiter.py`
- Modify: `backend/src/magi/llm/provider_bridge.py`
- Create or Modify: `backend/tests/llm/test_concurrency_limiter.py`

- [ ] **Step 1: Write the failing limiter tests**

Add tests that cover:

```python
@pytest.mark.asyncio
async def test_requests_for_same_provider_model_share_one_semaphore():
    ...


@pytest.mark.asyncio
async def test_custom_provider_base_url_host_participates_in_key():
    ...
```

- [ ] **Step 2: Run the focused limiter tests to verify they fail**

Run: `PYTHONPATH=backend/src pytest backend/tests/llm/test_concurrency_limiter.py -q`
Expected: FAIL because the limiter service does not exist yet.

- [ ] **Step 3: Implement the limiter service**

Add a small runtime service that:

- normalizes a limiter key from provider type, base URL host, model, and request family
- owns one `asyncio.Semaphore` per key
- exposes active/waiting/limit stats
- offers an async helper to run a coroutine under a permit

- [ ] **Step 4: Integrate the limiter into chat request paths**

Wrap outbound calls in:

- `LLMProviderBridge.chat_response()`
- `LLMProviderBridge.chat_with_tools()`

Do not duplicate provider-specific code paths; acquire the permit around the existing request execution boundary.

- [ ] **Step 5: Run the focused limiter tests to verify they pass**

Run: `PYTHONPATH=backend/src pytest backend/tests/llm/test_concurrency_limiter.py -q`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add backend/src/magi/llm/concurrency_limiter.py backend/src/magi/llm/provider_bridge.py backend/tests/llm/test_concurrency_limiter.py
git commit -m "feat: add shared llm concurrency limiter"
```

## Chunk 3: Embedding Integration And L1 Backpressure

### Task 3: Enforce embedding concurrency limits

**Files:**
- Modify: `backend/src/magi/memory/embedding_service.py`
- Modify: `backend/tests/memory/test_embedding_service.py`
- Modify: `backend/tests/llm/test_concurrency_limiter.py`

- [ ] **Step 1: Write the failing embedding limiter tests**

Add coverage for:

```python
@pytest.mark.asyncio
async def test_embedding_requests_share_global_limit():
    ...


@pytest.mark.asyncio
async def test_embedding_limit_uses_embedding_family_key():
    ...
```

- [ ] **Step 2: Run the focused tests to verify they fail**

Run: `PYTHONPATH=backend/src pytest backend/tests/memory/test_embedding_service.py backend/tests/llm/test_concurrency_limiter.py -q -k embedding`
Expected: FAIL because embedding calls do not go through the limiter yet.

- [ ] **Step 3: Wire the limiter into the embedding service**

Update `MemoryEmbeddingService` to:

- resolve the active embedding adapter identity
- compute the effective concurrency override/default for the embedding model
- acquire the shared limiter before `get_embedding()` or `get_embeddings()`

- [ ] **Step 4: Run the focused tests to verify they pass**

Run: `PYTHONPATH=backend/src pytest backend/tests/memory/test_embedding_service.py backend/tests/llm/test_concurrency_limiter.py -q -k embedding`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add backend/src/magi/memory/embedding_service.py backend/tests/memory/test_embedding_service.py backend/tests/llm/test_concurrency_limiter.py
git commit -m "feat: limit embedding model concurrency"
```

### Task 4: Bound the L1 embedding queue

**Files:**
- Modify: `backend/src/magi/memory/l1/event_store.py`
- Modify: `backend/tests/memory/l1/test_event_store.py`

- [ ] **Step 1: Write the failing bounded-queue test**

Add a test such as:

```python
@pytest.mark.asyncio
async def test_async_embedding_queue_waits_when_full():
    ...
```

The test should enqueue more items than the bound while stalling the worker and assert the producer waits instead of growing the queue indefinitely or dropping work.

- [ ] **Step 2: Run the focused test to verify it fails**

Run: `PYTHONPATH=backend/src pytest backend/tests/memory/l1/test_event_store.py -q -k queue_waits_when_full`
Expected: FAIL because the queue is currently unbounded.

- [ ] **Step 3: Implement bounded queue behavior**

Keep the implementation narrow:

- make the queue bounded
- keep semantics lossless
- add simple queue-size/backpressure stats if needed for assertions

- [ ] **Step 4: Run the focused test to verify it passes**

Run: `PYTHONPATH=backend/src pytest backend/tests/memory/l1/test_event_store.py -q -k queue_waits_when_full`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add backend/src/magi/memory/l1/event_store.py backend/tests/memory/l1/test_event_store.py
git commit -m "perf: bound l1 embedding backlog"
```

## Chunk 4: Frontend Advanced Settings For Shared Concurrency

### Task 5: Expose max concurrency in the model selection UI

**Files:**
- Modify: `frontend/src/api/modules/config.ts`
- Modify: `frontend/src/components/config-forms/LLMModelSelectionSection.tsx`
- Modify: `frontend/src/__tests__/settingsPage.test.tsx`
- Modify: `frontend/src/i18n/locales/en/app.json`
- Modify: `frontend/src/i18n/locales/zh-CN/app.json`

- [ ] **Step 1: Write the failing frontend test**

Add a test that:

- opens the settings model selection UI
- expands the advanced section for a scenario
- edits `Max Concurrency`
- asserts the saved config payload writes to the shared runtime override entry for the selected model

- [ ] **Step 2: Run the focused frontend test to verify it fails**

Run: `cd frontend && npm exec -- vitest run src/__tests__/settingsPage.test.tsx --testNamePattern="max concurrency"`
Expected: FAIL because the advanced control and config shape do not exist yet.

- [ ] **Step 3: Add frontend config and UI support**

Implement:

- `LLMLimits.max_concurrency`
- `LLMConfig.model_runtime_overrides`
- advanced `Max Concurrency` input in `LLMModelSelectionSection`
- a hint when the same model is reused by other scenarios
- aligned i18n keys in English and Chinese

- [ ] **Step 4: Run the focused frontend test to verify it passes**

Run: `cd frontend && npm exec -- vitest run src/__tests__/settingsPage.test.tsx --testNamePattern="max concurrency"`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add frontend/src/api/modules/config.ts frontend/src/components/config-forms/LLMModelSelectionSection.tsx frontend/src/__tests__/settingsPage.test.tsx frontend/src/i18n/locales/en/app.json frontend/src/i18n/locales/zh-CN/app.json
git commit -m "feat: add shared llm concurrency controls"
```

## Chunk 5: Final Verification

### Task 6: Re-run affected backend and frontend suites

**Files:**
- Modify: none unless verification uncovers a regression

- [ ] **Step 1: Run backend config and limiter suites**

Run: `PYTHONPATH=backend/src pytest backend/tests/api/test_config_api.py backend/tests/llm/test_concurrency_limiter.py backend/tests/memory/test_embedding_service.py backend/tests/memory/l1/test_event_store.py -q`
Expected: PASS

- [ ] **Step 2: Run adjacent regression suites**

Run: `PYTHONPATH=backend/src pytest backend/tests/llm/test_scenario_llm_pool.py backend/tests/config/test_config_loader.py -q`
Expected: PASS

- [ ] **Step 3: Run the frontend settings test**

Run: `cd frontend && npm exec -- vitest run src/__tests__/settingsPage.test.tsx`
Expected: PASS

- [ ] **Step 4: Check git status**

Run: `git status --short`
Expected: clean working tree

- [ ] **Step 5: If verification reveals a regression, fix and commit it immediately**

```bash
git add <files>
git commit -m "fix: stabilize llm concurrency controls"
```
